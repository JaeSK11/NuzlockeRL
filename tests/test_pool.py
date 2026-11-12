"""Tests for pool.py on a tiny fake env. No emulator needed.
Run: ~/venvs/nuzlockerl/bin/python -m pytest -q tests/test_pool.py"""
import functools, os, sys, threading, time
import gymnasium as gym
import numpy as np
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from pool import AsyncEnvPool, WorkerError


class FakeEnv(gym.Env):
    """Observation is [tag, step in episode]. An episode lasts `length` steps and ends
    terminated, or truncated if `truncate`. Reward is the action. `fail_at` makes global
    step number fail_at raise, exit the process, or hang."""
    observation_space = gym.spaces.Box(0, np.inf, (2,), np.float32)
    action_space = gym.spaces.Discrete(3)

    def __init__(self, tag, length=3, delay=0.0, truncate=False, fail_at=None, fail="raise"):
        self.tag, self.length, self.delay, self.truncate = tag, length, delay, truncate
        self.fail_at, self.fail, self.steps = fail_at, fail, 0

    def _obs(self):
        return np.array([self.tag, self.t], dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        self.t = 0
        return self._obs(), {"action_mask": np.array([True, True, False]), "seed": seed}

    def step(self, action):
        self.steps += 1
        if self.steps == self.fail_at:
            if self.fail == "raise":
                raise RuntimeError("boom in the fake env")
            if self.fail == "exit":
                os._exit(3)
            time.sleep(3600)
        time.sleep(self.delay)
        self.t += 1
        done = self.t == self.length
        return (self._obs(), float(action), done and not self.truncate, done and self.truncate,
                {"action_mask": np.array([True, True, False]), "t": self.t})


def fns(n, **kw):
    return [functools.partial(FakeEnv, tag, **kw) for tag in range(n)]


def within(seconds, fn):
    """Run fn in a thread so that a hang fails the test instead of blocking the suite."""
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as e:
            box["error"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), f"still blocked after {seconds} s"
    if "error" in box:
        raise box["error"]
    return box["value"]


def test_rows_belong_to_their_env_ids():
    with AsyncEnvPool(fns(4, length=5), seed=10) as pool:
        first = within(30, lambda: pool.recv(min_ready=4))
        assert sorted(first.env_ids) == [0, 1, 2, 3]
        assert [first.infos[r]["seed"] for r in np.argsort(first.env_ids)] == [10, 11, 12, 13]
        assert not first.rewards.any() and not first.terminated.any() and not first.truncated.any()
        pool.send(first.env_ids, [1] * 4)
        received, steps = 0, {i: 0 for i in range(4)}
        while received < 60:
            batch = within(30, pool.recv)
            assert batch.action_masks.shape == (len(batch), 3)
            for row, i in enumerate(batch.env_ids):
                steps[i] += 1
                done = steps[i] % 5 == 0
                assert batch.obs[row, 0] == i
                assert batch.obs[row, 1] == steps[i] % 5
                assert batch.rewards[row] == 1.0 and batch.terminated[row] == done
            received += len(batch)
            pool.send(batch.env_ids, [1] * len(batch))


def test_one_send_is_one_decision_across_an_episode_end():
    with AsyncEnvPool(fns(1, length=2)) as pool:
        pool.send(within(30, pool.recv).env_ids, [0])
        mid = within(30, pool.recv)
        assert mid.obs[0].tolist() == [0, 1] and mid.final_obs[0] is None and mid.final_infos[0] is None
        pool.send(mid.env_ids, [1])
        end = within(30, pool.recv)
        assert end.terminated[0] and not end.truncated[0] and end.rewards[0] == 1.0
        assert end.final_obs[0].tolist() == [0, 2] and end.final_infos[0]["t"] == 2
        assert end.obs[0].tolist() == [0, 0] and "seed" in end.infos[0]
        pool.send(end.env_ids, [0])
        after = within(30, pool.recv)
        assert after.obs[0].tolist() == [0, 1] and not after.terminated[0]


def test_truncation_is_reported_with_the_final_observation():
    with AsyncEnvPool(fns(1, length=1, truncate=True)) as pool:
        pool.send(within(30, pool.recv).env_ids, [0])
        end = within(30, pool.recv)
        assert end.truncated[0] and not end.terminated[0]
        assert end.final_obs[0].tolist() == [0, 1] and end.obs[0].tolist() == [0, 0]


def test_a_slow_env_does_not_hold_back_the_others():
    envs = [functools.partial(FakeEnv, 0, length=1000, delay=1.0),
            functools.partial(FakeEnv, 1, length=1000, delay=0.01)]
    with AsyncEnvPool(envs) as pool:
        first = within(30, lambda: pool.recv(min_ready=2))
        pool.send(first.env_ids, [0, 0])
        steps = {0: 0, 1: 0}
        while steps[1] < 20:
            batch = within(30, pool.recv)
            for i in batch.env_ids:
                steps[i] += 1
            pool.send(batch.env_ids, [0] * len(batch))
        assert steps[0] <= 1


def test_send_refuses_an_env_that_is_not_waiting():
    with AsyncEnvPool(fns(2)) as pool:
        batch = within(30, lambda: pool.recv(min_ready=2))
        pool.send([0], [0])
        with pytest.raises(ValueError, match="env 0 is not waiting"):
            pool.send([0], [0])
        with pytest.raises(ValueError, match="would wait forever"):
            pool.recv(min_ready=2)


@pytest.mark.parametrize("fail, message", [("raise", "boom in the fake env"), ("exit", "exit code 3")])
def test_a_worker_crash_raises_instead_of_hanging(fail, message):
    envs = fns(3, length=1000)
    envs[1] = functools.partial(FakeEnv, 1, length=1000, fail_at=4, fail=fail)
    pool = AsyncEnvPool(envs)

    def run():
        while True:
            batch = pool.recv()
            pool.send(batch.env_ids, [0] * len(batch))
    with pytest.raises(WorkerError, match=message):
        within(30, run)
    assert pool.pids == []


def test_a_hung_worker_raises_after_the_timeout():
    pool = AsyncEnvPool(fns(1, fail_at=1, fail="hang"), timeout=1.0)
    pool.send(within(30, pool.recv).env_ids, [0])
    with pytest.raises(WorkerError, match="no env answered within 1 s"):
        within(30, pool.recv)
