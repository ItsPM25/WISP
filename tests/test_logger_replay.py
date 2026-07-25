"""S1.5 / S1.6 — a packet written by RawLogger round-trips through ReplaySource."""

import numpy as np

from wisp.ingest.logger import RawLogger
from wisp.source.replay import ReplaySource


def test_log_then_replay_roundtrip(tmp_path):
    fp = tmp_path / "capture.csv"
    packets = [
        (0.000, np.array([21.3, 0.0, 18.7, 4.25])),
        (0.010, np.array([21.1, 0.0, 19.2, 4.30])),
        (0.020, np.array([20.9, 0.0, 18.4, 4.10])),
    ]
    with RawLogger(str(fp)) as log:
        for t, amp in packets:
            log.log(t, amp)

    replayed = list(ReplaySource(str(fp)).stream())
    assert len(replayed) == len(packets)
    for (t0, a0), (t1, a1) in zip(packets, replayed):
        assert np.isclose(t0, t1, atol=1e-6)
        assert np.allclose(a0, a1, atol=1e-4)   # logger writes 4 decimal places
