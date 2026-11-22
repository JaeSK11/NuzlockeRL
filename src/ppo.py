"""Masked PPO on CPU over an asynchronous env pool (src/pool.py), after CleanRL's ppo.py.

The pool hands back whichever envs are ready, so a rollout is not a (time, env) grid.
It is a flat list of transitions, each tagged with its env id. GAE runs over each
env's transitions in the order they happened.

Invalid actions get a logit of -inf, both when sampling and in the loss. The env must
put a boolean mask in info["action_mask"], with at least one valid action.

train() resumes from the newest checkpoint in its run directory. A checkpoint is taken
at an update boundary, so a resumed run repeats at most the updates after it.
"""
import collections, glob, json, os, time
from dataclasses import asdict, dataclass

import numpy as np
import torch
from torch import nn

from pool import AsyncEnvPool


@dataclass
class Config:
    rollout: int = 1024             # decisions per update
    epochs: int = 4
    minibatches: int = 4
    lr: float = 2.5e-4
    gamma: float = 0.99
    lam: float = 0.95
    clip: float = 0.2
    ent_coef: float = 0.01
    ball_ent_coef: float = 0.0      # extra entropy bonus at decisions where ball_action is legal
    ball_action: int | None = None  # the env's throw-a-ball action (battle_env.BALL_ACTION), if any
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    hidden: int = 64
    checkpoint_every: int = 10      # updates


Transition = collections.namedtuple(
    "Transition", "env_id obs mask action logp value reward terminated truncated next_value")


def _layer(n_in: int, n_out: int, std: float) -> nn.Linear:
    layer = nn.Linear(n_in, n_out)
    nn.init.orthogonal_(layer.weight, std)
    nn.init.zeros_(layer.bias)
    return layer


class Agent(nn.Module):
    def __init__(self, obs_dim: int, n_actions: int, hidden: int = 64):
        super().__init__()
        self.actor = nn.Sequential(_layer(obs_dim, hidden, 2 ** 0.5), nn.Tanh(),
                                   _layer(hidden, hidden, 2 ** 0.5), nn.Tanh(),
                                   _layer(hidden, n_actions, 0.01))
        self.critic = nn.Sequential(_layer(obs_dim, hidden, 2 ** 0.5), nn.Tanh(),
                                    _layer(hidden, hidden, 2 ** 0.5), nn.Tanh(),
                                    _layer(hidden, 1, 1.0))

    def log_probs(self, obs, mask):
        return torch.log_softmax(self.actor(obs).masked_fill(~mask, -torch.inf), dim=-1)

    def value(self, obs):
        return self.critic(obs).squeeze(-1)

    @torch.no_grad()
    def act(self, obs, mask, generator=None):
        """Sampled action, its log-probability, and the state value."""
        logp = self.log_probs(obs, mask)
        action = torch.multinomial(logp.exp(), 1, generator=generator)
        return action.squeeze(-1), logp.gather(-1, action).squeeze(-1), self.value(obs)

    def evaluate(self, obs, mask, action):
        """Log-probability of action, the policy's entropy, and the state value."""
        logp = self.log_probs(obs, mask)
        entropy = -(logp.exp() * logp.masked_fill(~mask, 0.0)).sum(-1)
        return logp.gather(-1, action[:, None]).squeeze(-1), entropy, self.value(obs)


class ObsNorm(nn.Module):
    """Running per-feature mean and variance. The rollout stores normalized observations,
    so an update sees exactly the inputs the policy acted on."""

    def __init__(self, dim: int):
        super().__init__()
        self.register_buffer("mean", torch.zeros(dim, dtype=torch.float64))
        self.register_buffer("var", torch.ones(dim, dtype=torch.float64))
        self.register_buffer("count", torch.zeros((), dtype=torch.float64))

    def update(self, x):
        n = x.shape[0]
        total = self.count + n
        delta = x.mean(0) - self.mean
        self.var.copy_((self.var * self.count + x.var(0, unbiased=False) * n
                        + delta ** 2 * self.count * n / total) / total)
        self.mean.add_(delta * n / total)
        self.count.copy_(total)

    def forward(self, x):
        return ((x - self.mean) / (self.var + 1e-8).sqrt()).clamp(-10, 10).float()


def gae(rewards, values, next_values, terminated, done, gamma: float, lam: float) -> np.ndarray:
    """Advantages for one env's transitions in time order.

    next_values[t] is the value of the state after step t: the next observation's, or the
    final observation's when step t was truncated. A terminated step bootstraps from
    nothing. `done` (terminated or truncated) stops the advantage of a later episode from
    flowing back into this one."""
    adv = np.zeros(len(rewards), dtype=np.float32)
    last = 0.0
    for t in reversed(range(len(rewards))):
        delta = rewards[t] + gamma * next_values[t] * (not terminated[t]) - values[t]
        last = delta + gamma * lam * (not done[t]) * last
        adv[t] = last
    return adv


class Rollout:
    """Transitions in arrival order, from any mix of envs."""

    def __init__(self):
        self.rows: list[Transition] = []

    def __len__(self):
        return len(self.rows)

    def add(self, transition: Transition):
        self.rows.append(transition)

    def tensors(self, gamma: float, lam: float) -> dict:
        cols = Transition(*zip(*self.rows))
        env_ids = np.array(cols.env_id)
        values = np.array(cols.value, dtype=np.float32)
        rewards, next_values = np.array(cols.reward, dtype=np.float32), np.array(cols.next_value, dtype=np.float32)
        terminated, truncated = np.array(cols.terminated), np.array(cols.truncated)
        adv = np.zeros(len(self), dtype=np.float32)
        for env in np.unique(env_ids):
            i = np.flatnonzero(env_ids == env)
            adv[i] = gae(rewards[i], values[i], next_values[i], terminated[i],
                         terminated[i] | truncated[i], gamma, lam)
        return {"obs": torch.stack(cols.obs), "mask": torch.stack(cols.mask),
                "action": torch.tensor(cols.action), "logp": torch.tensor(cols.logp),
                "value": torch.from_numpy(values), "advantage": torch.from_numpy(adv),
                "return": torch.from_numpy(adv + values)}


def _player_faints(info: dict) -> int:
    """Player faints in one step, from the env's info["events"] (BattleEnv's event names)."""
    return list(info.get("events", ())).count("PLAYER_FAINTED")


def _tally(info: dict) -> collections.Counter:
    """Counts from one step's info, for the logs: the decision's kind (pick.<kind>) and move
    (move.<name>), a move's last PP spent (pp_ran_dry), and each faint, of the team's
    strongest Pokémon (ace_faints) or another (other_faints). Envs without these keys count nothing."""
    t = collections.Counter()
    if info.get("pick"):
        t["pick." + info["pick"]] += 1
    if info.get("move"):
        t["move." + info["move"]] += 1
    if info.get("pp_before") == 1:
        t["pp_ran_dry"] += 1
    for strength in info.get("fainted_strengths", ()):
        t["ace_faints" if strength >= 1.0 else "other_faints"] += 1
    return t


def _result_mismatch(e: dict) -> bool:
    """The env's WON or LOST disagrees with the game's own result (resultMask: 1 win, 2 loss)."""
    want = {"WON": 1, "LOST": 2}.get(e.get("outcome"))
    return want is not None and e.get("result_mask") is not None and not e["result_mask"] & want


class Collector:
    """Acts on pool batches and pairs each env's result with the action that caused it."""

    def __init__(self, agent: Agent, norm: ObsNorm, generator=None):
        self.agent, self.norm, self.generator = agent, norm, generator
        self.pending: dict[int, tuple] = {}
        self.returns = collections.defaultdict(float)
        self.lengths = collections.defaultdict(int)
        self.faints = collections.defaultdict(int)
        self.tallies = collections.defaultdict(collections.Counter)

    @torch.no_grad()
    def act(self, batch, rollout: Rollout, episodes: list) -> np.ndarray:
        """Actions for the batch. Completed transitions go to rollout, finished episodes to episodes."""
        masks = batch.action_masks
        dead = np.flatnonzero(~masks.any(axis=1))
        if len(dead):
            raise RuntimeError(f"env {batch.env_ids[dead[0]]} has no valid action "
                               f"(state {batch.infos[dead[0]].get('state')})")
        raw = torch.as_tensor(batch.obs, dtype=torch.float64).flatten(1)
        self.norm.update(raw)
        obs, mask = self.norm(raw), torch.as_tensor(masks)
        action, logp, value = self.agent.act(obs, mask, self.generator)
        for row, env in enumerate(batch.env_ids.tolist()):
            if env in self.pending:
                terminated, truncated = bool(batch.terminated[row]), bool(batch.truncated[row])
                next_value = value[row].item()
                if truncated:
                    final = torch.as_tensor(batch.final_obs[row], dtype=torch.float64).flatten()[None]
                    next_value = self.agent.value(self.norm(final)).item()
                reward = float(batch.rewards[row])
                rollout.add(Transition(env, *self.pending[env], reward, terminated, truncated, next_value))
                info = batch.final_infos[row] if terminated or truncated else batch.infos[row]
                self.returns[env] += reward
                self.lengths[env] += 1
                self.faints[env] += _player_faints(info)
                self.tallies[env] += _tally(info)
                if terminated or truncated:
                    episodes.append({"state": os.path.basename(str(info.get("state", ""))),
                                     "outcome": info.get("outcome"), "return": self.returns.pop(env),
                                     "length": self.lengths.pop(env), "faints": self.faints.pop(env),
                                     "tally": dict(self.tallies.pop(env)), "result_mask": info.get("result_mask"),
                                     "route_step": info.get("route_step"), "error": info.get("error")})
            self.pending[env] = (obs[row], mask[row], action[row].item(), logp[row].item(), value[row].item())
        return action.numpy()


def ppo_update(agent: Agent, optimizer, data: dict, cfg: Config, generator=None) -> dict:
    n = len(data["action"])
    size = -(-n // cfg.minibatches)
    ball = {}
    if cfg.ball_action is not None:     # the ball's chances in this rollout, and the policy's odds of taking them
        chances = data["mask"][:, cfg.ball_action]
        with torch.no_grad():
            p = agent.log_probs(data["obs"][chances], data["mask"][chances])[:, cfg.ball_action].exp()
        ball = {"ball_chances": int(chances.sum()), "ball_prob": p.mean().item() if len(p) else None}
    for _ in range(cfg.epochs):
        stats = collections.defaultdict(list)
        order = torch.randperm(n, generator=generator)
        for start in range(0, n, size):
            i = order[start:start + size]
            logp, entropy, value = agent.evaluate(data["obs"][i], data["mask"][i], data["action"][i])
            log_ratio = logp - data["logp"][i]
            ratio = log_ratio.exp()
            adv = data["advantage"][i]
            if len(i) > 1:
                adv = (adv - adv.mean()) / (adv.std() + 1e-8)
            policy_loss = torch.max(-adv * ratio, -adv * ratio.clamp(1 - cfg.clip, 1 + cfg.clip)).mean()
            value_loss = 0.5 * (value - data["return"][i]).pow(2).mean()
            bonus = cfg.ent_coef
            if cfg.ball_action is not None:
                bonus = bonus + cfg.ball_ent_coef * data["mask"][i][:, cfg.ball_action].float()
            loss = policy_loss + cfg.vf_coef * value_loss - (bonus * entropy).mean()
            optimizer.zero_grad()
            loss.backward()
            # Clipped apart: returns reach about ±13, and under one shared norm the value
            # gradient would scale the policy gradient down with it.
            nn.utils.clip_grad_norm_(agent.actor.parameters(), cfg.max_grad_norm)
            nn.utils.clip_grad_norm_(agent.critic.parameters(), cfg.max_grad_norm)
            optimizer.step()
            stats["policy_loss"].append(policy_loss.item())
            stats["value_loss"].append(value_loss.item())
            stats["entropy"].append(entropy.mean().item())
            stats["approx_kl"].append(((ratio - 1) - log_ratio).mean().item())
            stats["clip_frac"].append(((ratio - 1).abs() > cfg.clip).float().mean().item())
    out = {k: float(np.mean(v)) for k, v in stats.items()} | ball
    var = data["return"].var().item()
    out["explained_variance"] = 1 - (data["return"] - data["value"]).var().item() / var if var > 0 else 0.0
    return out


def episode_stats(episodes: list) -> dict:
    """Mean return, win rate, clean-win rate (won with no player faint), faints, and length over
    all episodes, and the same per state. From the episodes' tallies (see _tally): decisions by
    kind (picks) and by move (moves), faints of the ace and of the others per episode, moves
    run out of PP, and episodes whose outcome the game's own result contradicts."""
    def summary(eps):
        tally = sum((collections.Counter(e.get("tally", {})) for e in eps), collections.Counter())
        return {"episodes": len(eps),
                "mean_return": float(np.mean([e["return"] for e in eps])),
                "win_rate": float(np.mean([e["outcome"] == "WON" for e in eps])),
                "clean_win_rate": float(np.mean([e["outcome"] == "WON" and e.get("faints", 0) == 0 for e in eps])),
                "mean_faints": float(np.mean([e.get("faints", 0) for e in eps])),
                "mean_length": float(np.mean([e["length"] for e in eps])),
                "outcomes": dict(collections.Counter(str(e["outcome"]) for e in eps)),
                "picks": {k[5:]: v for k, v in sorted(tally.items()) if k.startswith("pick.")},
                "moves": {k[5:]: v for k, v in sorted(tally.items()) if k.startswith("move.")},
                "mean_ace_faints": tally["ace_faints"] / len(eps),
                "mean_other_faints": tally["other_faints"] / len(eps),
                "pp_ran_dry": tally["pp_ran_dry"],
                "result_mismatches": sum(_result_mismatch(e) for e in eps),
                **({"mean_route_step": float(np.mean(steps)), "max_route_step": max(steps)}
                   if (steps := [e["route_step"] for e in eps if e.get("route_step") is not None]) else {}),
                **({"errors": dict(collections.Counter(errors))}      # why runs ended route_error
                   if (errors := [e["error"] for e in eps if e.get("error")]) else {})}
    if not episodes:
        return {"episodes": 0, "states": {}}
    by_state = collections.defaultdict(list)
    for e in episodes:
        by_state[e["state"]].append(e)
    return {**summary(episodes), "states": {s: summary(eps) for s, eps in sorted(by_state.items())}}


def latest_checkpoint(run_dir: str) -> str | None:
    return max(glob.glob(os.path.join(run_dir, "ckpt_*.pt")), default=None)


def save_checkpoint(run_dir: str, state: dict) -> str:
    path = os.path.join(run_dir, f"ckpt_{state['update']:08d}.pt")
    with open(path + ".tmp", "wb") as f:
        torch.save(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(path + ".tmp", path)
    return path


def _drop_log_rows_after(path: str, update: int):
    """A run killed between checkpoints has logged updates that the resumed run repeats.
    Drop them, and any half-written last line, so each update is logged once."""
    if not os.path.exists(path):
        return
    kept = []
    with open(path) as f:
        for line in f:
            try:
                if json.loads(line)["update"] > update:
                    break
            except ValueError:
                break
            kept.append(line)
    with open(path + ".tmp", "w") as f:
        f.writelines(kept)
    os.replace(path + ".tmp", path)


def _print(message: str):
    print(message, flush=True)     # so that progress shows under nohup or a pipe


def train(env_fns, run_dir: str, total_decisions: int, seed: int = 0, cfg: Config | None = None,
          guard=None, log=_print) -> int:
    """Train until total_decisions transitions have gone into updates, resuming from the
    newest checkpoint in run_dir. Returns the decisions trained on.

    Stops early, after saving a checkpoint, once guard.tripped is set (see thermal.py)."""
    cfg = cfg or Config()
    os.makedirs(run_dir, exist_ok=True)
    log_path = os.path.join(run_dir, "metrics.jsonl")
    torch.set_num_threads(1)    # the net is tiny, and extra threads would take cores from the emulators

    ckpt_path = latest_checkpoint(run_dir)
    ckpt = torch.load(ckpt_path, weights_only=True) if ckpt_path else None
    update, decisions, elapsed = (ckpt["update"], ckpt["decisions"], ckpt["elapsed"]) if ckpt else (0, 0, 0.0)
    _drop_log_rows_after(log_path, update)
    if ckpt:
        log(f"resuming from {ckpt_path}: update {update}, {decisions} decisions")
    if decisions >= total_decisions:
        return decisions

    # Seeded by the update count too, so a resumed run does not replay the battles it started with.
    env_seed, torch_seed = (int(s) for s in np.random.SeedSequence([seed, update]).generate_state(2))
    generator = torch.Generator().manual_seed(torch_seed)
    torch.manual_seed(torch_seed)
    with AsyncEnvPool(env_fns, seed=env_seed % 2 ** 31) as pool:
        batch = pool.recv()
        obs_dim, n_actions = int(np.prod(batch.obs.shape[1:])), batch.action_masks.shape[1]
        agent, norm = Agent(obs_dim, n_actions, cfg.hidden), ObsNorm(obs_dim)
        optimizer = torch.optim.Adam(agent.parameters(), lr=cfg.lr, eps=1e-5)
        if ckpt:
            if (ckpt["obs_dim"], ckpt["n_actions"]) != (obs_dim, n_actions):
                raise RuntimeError(
                    f"{ckpt_path} was trained on {ckpt['obs_dim']} observation values and "
                    f"{ckpt['n_actions']} actions, but the env now gives {obs_dim} and {n_actions}. "
                    f"Start a new --run-dir.")
            agent.load_state_dict(ckpt["agent"])
            norm.load_state_dict(ckpt["obs_norm"])
            optimizer.load_state_dict(ckpt["optimizer"])
            for group in optimizer.param_groups:
                group["lr"] = cfg.lr
        collector = Collector(agent, norm, generator)

        def checkpoint():
            return save_checkpoint(run_dir, {
                "update": update, "decisions": decisions, "elapsed": elapsed,
                "obs_dim": obs_dim, "n_actions": n_actions, "seed": seed, "config": asdict(cfg),
                "agent": agent.state_dict(), "obs_norm": norm.state_dict(),
                "optimizer": optimizer.state_dict()})

        saved = update
        with open(log_path, "a", buffering=1) as log_file:
            while decisions < total_decisions:
                started = time.time()
                rollout, episodes = Rollout(), []
                while len(rollout) < cfg.rollout and not (guard and guard.tripped.is_set()):
                    pool.send(batch.env_ids, collector.act(batch, rollout, episodes))
                    batch = pool.recv()
                if len(rollout) < cfg.rollout:
                    break
                collected = time.time()
                losses = ppo_update(agent, optimizer, rollout.tensors(cfg.gamma, cfg.lam), cfg, generator)
                update, decisions = update + 1, decisions + len(rollout)
                now = time.time()
                elapsed += now - started
                row = {"update": update, "decisions": decisions, "elapsed_s": round(elapsed, 1),
                       "decisions_per_s": round(len(rollout) / (now - started), 2),
                       "update_s": round(now - collected, 3),
                       **episode_stats(episodes), **losses,
                       "cpu_temp": guard.temp if guard else None}
                log_file.write(json.dumps(row) + "\n")
                log(f"update {update}  decisions {decisions}  {row['decisions_per_s']:.1f}/s  "
                    f"episodes {row['episodes']}  return {row.get('mean_return', float('nan')):+.2f}  "
                    f"win {row.get('win_rate', float('nan')):.2f}  clean {row.get('clean_win_rate', float('nan')):.2f}  "
                    f"entropy {losses['entropy']:.3f}  "
                    f"kl {losses['approx_kl']:.4f}  temp {row['cpu_temp']}")
                if update % cfg.checkpoint_every == 0 or decisions >= total_decisions:
                    checkpoint()
                    saved = update
        if update > saved:
            checkpoint()
    return decisions


def widen_checkpoint(ckpt: dict, obs_dim: int) -> dict:
    """The checkpoint for an observation with new values appended at its end. The new inputs
    get zero weights, so the policy and the value start exactly as before, and learn from
    there. Their running mean starts at 0 and variance at 1, and adapt at the rate the old
    count allows."""
    old = ckpt["obs_dim"]
    if obs_dim < old:
        raise ValueError(f"the checkpoint has {old} observation values, more than {obs_dim}")
    extra, out = obs_dim - old, dict(ckpt, obs_dim=obs_dim)

    def widen(t, fill=0.0):     # a first layer's weights (or its Adam moments), or a norm buffer
        pad = t.new_full((*t.shape[:-1], extra), fill)
        return torch.cat([t, pad], -1)
    first = ("actor.0.weight", "critic.0.weight")
    out["agent"] = {k: widen(v) if k in first else v for k, v in ckpt["agent"].items()}
    norm = ckpt["obs_norm"]
    out["obs_norm"] = dict(norm, mean=widen(norm["mean"]), var=widen(norm["var"], 1.0))
    names = list(ckpt["agent"])     # Agent has no buffers: its parameters, in the optimizer's order
    out["optimizer"] = dict(ckpt["optimizer"], state={
        i: {k: widen(v) if names[i] in first and k != "step" else v for k, v in st.items()}
        for i, st in ckpt["optimizer"]["state"].items()})
    return out


def load_policy(ckpt_path: str) -> tuple[Agent, ObsNorm]:
    """The agent and observation normalization saved in a checkpoint."""
    ckpt = torch.load(ckpt_path, weights_only=True)
    agent, norm = Agent(ckpt["obs_dim"], ckpt["n_actions"], ckpt["config"]["hidden"]), ObsNorm(ckpt["obs_dim"])
    agent.load_state_dict(ckpt["agent"])
    norm.load_state_dict(ckpt["obs_norm"])
    return agent, norm


@torch.no_grad()
def evaluate(agent: Agent, norm: ObsNorm, env_fns, episodes_per_env: int, greedy: bool = False,
             seed: int = 0, guard=None) -> list[dict]:
    """Play episodes_per_env episodes in every env with a fixed policy. Greedy takes the most
    likely valid action, otherwise actions are sampled. Nothing is learned, and the
    normalization statistics stay as saved. Returns one record per episode, as episode_stats
    takes them, plus the env index. Stops early once guard.tripped is set."""
    generator = torch.Generator().manual_seed(seed)
    records, done, stepped = [], collections.Counter(), set()
    returns, lengths, faints = collections.defaultdict(float), collections.defaultdict(int), collections.defaultdict(int)
    tallies = collections.defaultdict(collections.Counter)
    with AsyncEnvPool(env_fns, seed=seed) as pool:
        batch = pool.recv()
        while not (guard and guard.tripped.is_set()):
            act = []
            for row, env in enumerate(batch.env_ids.tolist()):
                if env in stepped:
                    ended = batch.terminated[row] or batch.truncated[row]
                    info = batch.final_infos[row] if ended else batch.infos[row]
                    returns[env] += float(batch.rewards[row])
                    lengths[env] += 1
                    faints[env] += _player_faints(info)
                    tallies[env] += _tally(info)
                    if ended:
                        records.append({"env": env, "state": os.path.basename(str(info.get("state", ""))),
                                        "outcome": info.get("outcome"), "return": returns.pop(env),
                                        "length": lengths.pop(env), "faints": faints.pop(env),
                                        "tally": dict(tallies.pop(env)), "result_mask": info.get("result_mask")})
                        done[env] += 1
                if done[env] < episodes_per_env:
                    act.append(row)
            if all(done[env] >= episodes_per_env for env in range(len(env_fns))):
                break
            if act:
                masks = batch.action_masks[act]
                if not masks.any(axis=1).all():
                    raise RuntimeError("an env has no valid action")
                obs = norm(torch.as_tensor(batch.obs[act], dtype=torch.float64).flatten(1))
                logp = agent.log_probs(obs, torch.as_tensor(masks))
                action = logp.argmax(-1) if greedy else torch.multinomial(logp.exp(), 1, generator=generator).squeeze(-1)
                pool.send(batch.env_ids[act], action.numpy())
                stepped.update(batch.env_ids[act].tolist())
            batch = pool.recv()
    return records
