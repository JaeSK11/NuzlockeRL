"""Asynchronous env pool: one worker process per env, and the trainer acts on whichever
envs are ready instead of waiting for the slowest one.

    pool = AsyncEnvPool(env_fns, seed=0)
    batch = pool.recv()                      # the envs that are ready now
    pool.send(batch.env_ids, actions)        # they step while the others keep running

Every env is in exactly one of three places: stepping in its worker, ready (its result
has arrived), or held by the caller (handed out by recv(), waiting for an action).

Autoreset happens inside the worker, in the same step that ends the episode. That
step's result carries the finished episode's last observation and info in final_obs and
final_infos, and the new episode's first observation in obs. So one send() is exactly
one decision, and no reset step shows up as a transition.
"""
import multiprocessing as mp
import time
import traceback
from dataclasses import dataclass
from multiprocessing.connection import wait

import cloudpickle
import numpy as np


class WorkerError(RuntimeError):
    """An env worker raised, died, or stopped answering. The pool is closed."""


@dataclass
class Batch:
    """Results from the envs that were ready. Row i belongs to env env_ids[i].

    obs and infos describe the state to act on next. rewards, terminated and truncated
    describe the step that led there, and are zero and False for the first reset.
    final_obs[i] and final_infos[i] are None unless that step ended an episode."""
    env_ids: np.ndarray
    obs: np.ndarray
    infos: list
    rewards: np.ndarray
    terminated: np.ndarray
    truncated: np.ndarray
    final_obs: list
    final_infos: list

    def __len__(self):
        return len(self.env_ids)

    @property
    def action_masks(self) -> np.ndarray:
        return np.stack([info["action_mask"] for info in self.infos])


def _worker(env_fn: bytes, conn, seed):
    env = None
    try:
        env = cloudpickle.loads(env_fn)()
        obs, info = env.reset(seed=seed)
        conn.send((obs, info, 0.0, False, False, None, None))
        while (action := conn.recv()) is not None:
            obs, reward, terminated, truncated, info = env.step(action)
            final_obs = final_info = None
            if terminated or truncated:
                final_obs, final_info = obs, info
                obs, info = env.reset()
            conn.send((obs, info, float(reward), bool(terminated), bool(truncated), final_obs, final_info))
    except (EOFError, BrokenPipeError, KeyboardInterrupt):
        pass    # the trainer is gone or shutting down
    except Exception:
        conn.send(traceback.format_exc())
    finally:
        if env is not None:
            env.close()


class AsyncEnvPool:
    """env_fns are zero-argument env factories. Env i's first reset is seeded seed + i.

    recv() raises WorkerError when a worker raises or dies, or when no stepping env
    answers within `timeout` seconds."""

    def __init__(self, env_fns, seed: int | None = None, timeout: float = 300.0):
        # spawn, not fork: the trainer process holds torch threads, and a forked child can
        # inherit a lock one of them held.
        ctx = mp.get_context("spawn")
        self.num_envs, self.timeout = len(env_fns), timeout
        self._conns, self._procs = [], []
        for i, fn in enumerate(env_fns):
            parent, child = ctx.Pipe()
            proc = ctx.Process(target=_worker, daemon=True,
                               args=(cloudpickle.dumps(fn), child, None if seed is None else seed + i))
            proc.start()
            child.close()
            self._conns.append(parent)
            self._procs.append(proc)
        self._stepping = set(range(self.num_envs))
        self._ready: dict[int, tuple] = {}
        self._held: set[int] = set()

    @property
    def pids(self) -> list[int]:
        return [p.pid for p in self._procs]

    def _fail(self, message: str):
        self.close()
        raise WorkerError(message)

    def _collect(self, timeout: float):
        conns = {self._conns[i]: i for i in self._stepping}
        sentinels = {self._procs[i].sentinel: i for i in self._stepping}
        arrived = wait([*conns, *sentinels], timeout)
        if not arrived and timeout:
            self._fail(f"no env answered within {timeout:.0f} s; stepping: {sorted(self._stepping)}")
        for obj in arrived:
            if obj not in conns:
                continue
            i = conns[obj]
            try:
                msg = obj.recv()
            except (EOFError, OSError):
                self._procs[i].join(1)
                self._fail(f"env {i}'s worker died (exit code {self._procs[i].exitcode})")
            if isinstance(msg, str):
                self._fail(f"env {i}'s worker raised:\n{msg}")
            self._ready[i] = msg
            self._stepping.discard(i)
        for obj in arrived:
            if obj in sentinels and sentinels[obj] in self._stepping:
                i = sentinels[obj]
                self._fail(f"env {i}'s worker died (exit code {self._procs[i].exitcode})")

    def recv(self, min_ready: int = 1) -> Batch:
        """Block until at least min_ready envs are ready, then hand out every ready env."""
        if min_ready > len(self._ready) + len(self._stepping):
            raise ValueError(f"recv(min_ready={min_ready}) would wait forever: "
                             f"{len(self._held)} of {self.num_envs} envs are waiting for send()")
        while len(self._ready) < min_ready:
            self._collect(self.timeout)
        if self._stepping:
            self._collect(0)
        ids = list(self._ready)
        obs, infos, rewards, terminated, truncated, final_obs, final_infos = zip(*self._ready.values())
        self._ready.clear()
        self._held.update(ids)
        return Batch(np.array(ids), np.stack(obs), list(infos), np.array(rewards, dtype=np.float32),
                     np.array(terminated), np.array(truncated), list(final_obs), list(final_infos))

    def send(self, env_ids, actions):
        """Step each env in env_ids with its action. Only envs handed out by recv() may step."""
        for i, action in zip(env_ids, actions):
            i = int(i)
            if i not in self._held:
                raise ValueError(f"env {i} is not waiting for an action")
            try:
                self._conns[i].send(action)
            except (BrokenPipeError, OSError):
                self._procs[i].join(1)
                self._fail(f"env {i}'s worker died (exit code {self._procs[i].exitcode})")
            self._held.discard(i)
            self._stepping.add(i)

    def close(self):
        for conn in self._conns:
            try:
                conn.send(None)
            except (BrokenPipeError, OSError):
                pass
        deadline = time.monotonic() + 2
        for proc in self._procs:
            proc.join(max(0, deadline - time.monotonic()))
            if proc.is_alive():
                proc.terminate()
                proc.join()
        for conn in self._conns:
            conn.close()
        self._conns, self._procs = [], []
        self._stepping, self._ready, self._held = set(), {}, set()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
