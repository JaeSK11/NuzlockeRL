"""Tests for ppo.py on fake envs. No emulator needed.
Run: ~/venvs/nuzlockerl/bin/python -m pytest -q tests/test_ppo.py"""
import json, os, sys, threading, types
import gymnasium as gym
import numpy as np
import pytest
import torch
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from pool import Batch
from ppo import Agent, Collector, Config, ObsNorm, Rollout, Transition, gae, latest_checkpoint, train


class BanditEnv(gym.Env):
    """Observation is a one-hot context. Reward is +1 for the action that matches it, else
    -1. Action 3 is always masked, and taking it raises. An episode is 5 steps."""
    observation_space = gym.spaces.Box(0, 1, (3,), np.float32)
    action_space = gym.spaces.Discrete(4)
    MASK = np.array([True, True, True, False])

    def _obs(self):
        self.context = int(self.np_random.integers(3))
        return np.eye(3, dtype=np.float32)[self.context]

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.t, self.correct = 0, 0
        return self._obs(), {"action_mask": self.MASK}

    def step(self, action):
        if not self.MASK[action]:
            raise ValueError(f"action {action} is masked")
        hit = action == self.context
        self.t, self.correct = self.t + 1, self.correct + hit
        info = {"action_mask": self.MASK, "state": "/states/bandit.state"}
        if self.t == 5:
            info["outcome"] = "WON" if self.correct == 5 else "LOST"
        return self._obs(), 1.0 if hit else -1.0, self.t == 5, False, info


BANDITS = [BanditEnv] * 4


def rows(run_dir):
    with open(os.path.join(run_dir, "metrics.jsonl")) as f:
        return [json.loads(line) for line in f]


def random_masks(n, n_actions, allowed):
    mask = torch.zeros(n, n_actions, dtype=torch.bool)
    mask[:, :allowed] = torch.rand(n, allowed) < 0.4
    mask[torch.arange(n), torch.randint(allowed, (n,))] = True
    return mask


def test_masking_never_samples_an_invalid_action():
    torch.manual_seed(0)
    agent = Agent(5, 9)
    with torch.no_grad():
        agent.actor[-1].bias[5:] = 30.0     # the policy badly wants actions 5-8
    obs, mask = torch.randn(4000, 5), random_masks(4000, 9, allowed=5)
    for _ in range(20):
        action, logp, _ = agent.act(obs, mask)
        assert mask.gather(1, action[:, None]).all()
        assert torch.isfinite(logp).all()
    forced = mask.sum(1) == 1
    assert forced.any() and (logp[forced] == 0).all()
    assert (action[forced] == mask[forced].float().argmax(1)).all()


def test_the_loss_gives_invalid_actions_no_probability_and_no_gradient():
    torch.manual_seed(1)
    agent = Agent(5, 9)
    obs, mask = torch.randn(256, 5), random_masks(256, 9, allowed=5)
    action, old_logp, _ = agent.act(obs, mask)
    logp, entropy, value = agent.evaluate(obs, mask, action)
    assert torch.allclose(logp, old_logp)
    assert (entropy <= mask.sum(1).log() + 1e-5).all() and (entropy[mask.sum(1) == 1] == 0).all()
    (-(logp * torch.randn(256)).mean() - entropy.mean() + value.pow(2).mean()).backward()
    grads = [p.grad for p in agent.parameters()]
    assert all(torch.isfinite(g).all() for g in grads)
    bias_grad = agent.actor[-1].bias.grad
    assert (bias_grad[5:] == 0).all() and (bias_grad[:5] != 0).all()


def test_gae_matches_a_hand_computed_example():
    # gamma 0.5, lambda 0.5, so the trace decays by 0.25 per step.
    # d2 = 1 + 0.5*4 - 3 = 0      A2 = 0
    # d1 = 1 + 0.5*3 - 2 = 0.5    A1 = 0.5 + 0.25*0   = 0.5
    # d0 = 1 + 0.5*2 - 1 = 1      A0 = 1   + 0.25*0.5 = 1.125
    args = dict(rewards=[1, 1, 1], values=[1, 2, 3], gamma=0.5, lam=0.5)
    none = [False] * 3
    assert gae(next_values=[2, 3, 4], terminated=none, done=none, **args).tolist() == [1.125, 0.5, 0]
    # Step 1 terminates: d1 = 1 - 2 = -1 with no bootstrap, and A2 does not flow back.
    # A0 = 1 + 0.25*(-1) = 0.75
    end = [False, True, False]
    assert gae(next_values=[2, 99, 4], terminated=end, done=end, **args).tolist() == [0.75, -1, 0]
    # Step 1 is truncated with a final-state value of 10: d1 = 1 + 0.5*10 - 2 = 4.
    # A0 = 1 + 0.25*4 = 2
    assert gae(next_values=[2, 10, 4], terminated=none, done=end, **args).tolist() == [2, 4, 0]


def test_a_rollout_runs_gae_over_each_env_stream():
    def row(env, value, reward, next_value, terminated=False):
        return Transition(env, torch.zeros(1), torch.ones(2, dtype=torch.bool), 0, 0.0,
                          value, reward, terminated, False, next_value)
    rollout = Rollout()
    # Env 0 is the first stream of the test above. Env 1: step 0 terminates, so
    # A = 2 - 0 = 2; then d = 0 + 0.5*5 - 1 = 1.5.
    for t in (row(0, 1, 1, 2), row(1, 0, 2, 1, terminated=True), row(0, 2, 1, 3),
              row(0, 3, 1, 4), row(1, 1, 0, 5)):
        rollout.add(t)
    data = rollout.tensors(gamma=0.5, lam=0.5)
    assert data["advantage"].tolist() == [1.125, 2, 0.5, 0, 1.5]
    assert data["return"].tolist() == [2.125, 2, 2.5, 3, 2.5]


def batch(env_ids, obs, rewards=None, terminated=None, truncated=None, final_obs=None):
    n = len(env_ids)
    info = {"action_mask": np.array([True, True, False])}
    final_obs = final_obs or [None] * n
    final_infos = [None if f is None else {"state": "/s/a.state", "outcome": "WON"} for f in final_obs]
    return Batch(np.array(env_ids), np.array(obs, dtype=np.float32), [info] * n,
                 np.array(rewards or [0.0] * n, dtype=np.float32), np.array(terminated or [False] * n),
                 np.array(truncated or [False] * n), final_obs, final_infos)


def test_truncation_bootstraps_from_the_final_observation_and_termination_does_not():
    torch.manual_seed(2)
    agent, norm = Agent(2, 3), ObsNorm(2)
    collector, rollout, episodes = Collector(agent, norm), Rollout(), []
    value = lambda obs: agent.value(norm(torch.tensor([obs], dtype=torch.float64))).item()

    collector.act(batch([0, 1], [[1, 2], [3, 4]]), rollout, episodes)
    assert len(rollout) == 0
    final = np.array([9, 9], dtype=np.float32)
    collector.act(batch([1], [[5, 6]], rewards=[1.0], truncated=[True], final_obs=[final]), rollout, episodes)
    v_final = value([9, 9])
    collector.act(batch([0], [[7, 8]], rewards=[2.0], terminated=[True], final_obs=[final]), rollout, episodes)

    truncated, terminated = rollout.rows
    assert (truncated.env_id, truncated.truncated, truncated.terminated) == (1, True, False)
    assert (terminated.env_id, terminated.truncated, terminated.terminated) == (0, False, True)
    assert truncated.next_value == pytest.approx(v_final) and v_final != 0
    adv = rollout.tensors(gamma=0.9, lam=0.95)["advantage"].tolist()
    assert adv[0] == pytest.approx(1.0 + 0.9 * v_final - truncated.value, abs=1e-5)
    assert adv[1] == pytest.approx(2.0 - terminated.value, abs=1e-5)
    assert episodes == [{"state": "a.state", "outcome": "WON", "return": 1.0, "length": 1},
                        {"state": "a.state", "outcome": "WON", "return": 2.0, "length": 1}]


def test_an_env_with_no_valid_action_is_an_error():
    stuck = batch([0], [[1, 2]])
    stuck.infos = [{"action_mask": np.zeros(3, dtype=bool), "state": "/s/a.state"}]
    with pytest.raises(RuntimeError, match="env 0 has no valid action"):
        Collector(Agent(2, 3), ObsNorm(2)).act(stuck, Rollout(), [])


def test_training_learns_the_bandit(tmp_path):
    cfg = Config(rollout=256, lr=3e-3, checkpoint_every=100)
    train(BANDITS, str(tmp_path), 256 * 20, seed=0, cfg=cfg, log=lambda *_: None)
    log = rows(tmp_path)
    assert log[0]["mean_return"] < 0 and log[0]["win_rate"] < 0.2
    assert log[-1]["mean_return"] > 3 and log[-1]["win_rate"] > 0.5
    assert log[-1]["states"]["bandit.state"]["mean_length"] == 5
    assert log[-1]["entropy"] < log[0]["entropy"]


def test_resume_continues_from_the_saved_step_count(tmp_path):
    run, messages = str(tmp_path), []
    cfg = Config(rollout=64, checkpoint_every=2)
    first = train(BANDITS, run, 64 * 3, seed=0, cfg=cfg, log=messages.append)
    before = rows(run)
    assert [r["update"] for r in before] == [1, 2, 3] and before[-1]["decisions"] == first

    # A kill after update 3 was logged but before its checkpoint: update 2's is the newest.
    os.remove(latest_checkpoint(run))
    saved = torch.load(latest_checkpoint(run), weights_only=True)
    assert (saved["update"], saved["decisions"]) == (2, before[1]["decisions"])

    # A learning rate of 0 keeps the weights, so the next checkpoint shows what was loaded.
    second = train(BANDITS, run, saved["decisions"] + 64, seed=0,
                   cfg=Config(rollout=64, checkpoint_every=2, lr=0.0), log=messages.append)
    after = rows(run)
    assert f"update 2, {saved['decisions']} decisions" in " ".join(messages)
    assert after[:2] == before[:2]
    assert [r["update"] for r in after] == [1, 2, 3]
    assert 64 <= after[2]["decisions"] - saved["decisions"] < 64 + len(BANDITS)
    assert second == after[-1]["decisions"]
    resumed = torch.load(latest_checkpoint(run), weights_only=True)
    assert resumed["update"] == 3
    for key, tensor in saved["agent"].items():
        assert torch.equal(resumed["agent"][key], tensor)

    assert train(BANDITS, run, second, seed=0, cfg=cfg, log=messages.append) == second
    assert rows(run) == after


def test_a_tripped_thermal_guard_stops_the_run_at_a_checkpoint(tmp_path):
    guard = types.SimpleNamespace(temp=55.0, tripped=threading.Event())

    def log(message):
        if message.startswith("update 2 "):
            guard.tripped.set()
    cfg = Config(rollout=64, checkpoint_every=100)
    decisions = train(BANDITS, str(tmp_path), 64 * 50, cfg=cfg, guard=guard, log=log)
    log_rows = rows(tmp_path)
    assert [r["update"] for r in log_rows] == [1, 2] and log_rows[-1]["cpu_temp"] == 55.0
    saved = torch.load(latest_checkpoint(str(tmp_path)), weights_only=True)
    assert (saved["update"], saved["decisions"]) == (2, decisions) and decisions == log_rows[-1]["decisions"]


def test_resume_refuses_a_checkpoint_from_another_observation_layout(tmp_path):
    cfg = Config(rollout=32, checkpoint_every=1)
    train(BANDITS, str(tmp_path), 32, cfg=cfg, log=lambda *_: None)
    path = latest_checkpoint(str(tmp_path))
    state = torch.load(path, weights_only=True)
    state["obs_dim"] = 111
    torch.save(state, path)
    with pytest.raises(RuntimeError, match="Start a new --run-dir"):
        train(BANDITS, str(tmp_path), 64, cfg=cfg, log=lambda *_: None)
