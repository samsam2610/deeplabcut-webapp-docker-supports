"""Tests for the tqdm-progress-line log throttler used by run_train_subprocess.

Without throttling, litpose emits ~2 lines per training step and ~1 per predict
batch — overwhelming the Redis log list and pushing every structural event
(config dump, epoch transitions, our STAGE 1/2 emits, errors) past the visible
30-line tail. The throttler keeps tqdm lines at a usable rate while letting
all non-tqdm output through unchanged.
"""
from __future__ import annotations

import time

from dlc_3d_bp.lp.train_runner import _make_log_throttler


def test_throttler_passes_non_tqdm_lines_through():
    emitted: list = []
    f = _make_log_throttler(emitted.append, min_interval=10.0)
    for line in [
        "Output directory: /x/y",
        "two-stage: STAGE 1 starting (sv-pretrain)",
        "Dataset splits -- train: 540, val: 28, test: 0",
        "two-stage: STAGE 1 done — ckpt /tmp/x.ckpt",
    ]:
        f(line)
    assert emitted == [
        "Output directory: /x/y",
        "two-stage: STAGE 1 starting (sv-pretrain)",
        "Dataset splits -- train: 540, val: 28, test: 0",
        "two-stage: STAGE 1 done — ckpt /tmp/x.ckpt",
    ]


def test_throttler_emits_first_and_throttles_subsequent_tqdm_lines():
    """First tqdm line per prefix is always emitted; rapid successors are dropped
    until min_interval elapses."""
    emitted: list = []
    f = _make_log_throttler(emitted.append, min_interval=10.0)
    for pct in (1, 2, 3, 4, 5):
        f(f"Epoch 0:   {pct}%|▏         | {pct}/270 [00:00<00:01, 10.0it/s, v_num=0]")
    # Only the first line — successors are throttled within the 10s window.
    assert len(emitted) == 1
    assert "Epoch 0:" in emitted[0]
    assert "1%" in emitted[0]


def test_throttler_always_emits_100_percent_completion():
    """The completion line (100%) must always survive the throttle so the user
    sees an epoch finishing."""
    emitted: list = []
    f = _make_log_throttler(emitted.append, min_interval=10.0)
    f("Epoch 0:   1%|▏         | 1/270 [00:00<00:01]")
    f("Epoch 0:  50%|█████     | 135/270 [00:10<00:10]")  # throttled
    f("Epoch 0: 100%|██████████| 270/270 [00:20<00:00]")  # always emitted
    # First + 100% completion (50% throttled out)
    assert len(emitted) == 2
    assert "1%" in emitted[0]
    assert "100%" in emitted[1]


def test_throttler_independent_state_per_prefix():
    """Different tqdm bar prefixes (e.g., 'Epoch 0' vs 'Predicting DataLoader 0')
    have their own first-line / throttle windows."""
    emitted: list = []
    f = _make_log_throttler(emitted.append, min_interval=10.0)
    f("Epoch 0:   1%|▏| 1/270 [00:00<00:01]")
    f("Predicting DataLoader 0:   1%|▏| 1/284 [00:00<00:01]")
    # Both prefixes are "new" → both pass.
    assert len(emitted) == 2
    assert "Epoch 0:" in emitted[0]
    assert "Predicting DataLoader 0:" in emitted[1]


def test_throttler_re_emits_after_interval():
    emitted: list = []
    f = _make_log_throttler(emitted.append, min_interval=0.01)
    f("Epoch 0:   1%|▏| 1/270 [00:00<00:01]")
    time.sleep(0.02)
    f("Epoch 0:  20%|██| 54/270 [00:00<00:01]")
    time.sleep(0.02)
    f("Epoch 0:  40%|████| 108/270 [00:00<00:01]")
    # All three pass because we slept past the throttle window each time
    assert len(emitted) == 3
