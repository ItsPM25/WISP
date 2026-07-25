"""S9 — the gate harness catches staged falls with zero false alarms on the demo."""

from wisp.calibrate.profile import RoomProfile
from wisp.evaluate.harness import evaluate
from wisp.source.synthetic import SyntheticSource

RATE = 25.0


def test_demo_meets_the_gate():
    profile = RoomProfile.fit(
        SyntheticSource.normal_only(minutes=1.0, sample_rate_hz=RATE),
        sample_rate_hz=RATE,
    )
    demo = SyntheticSource.demo(sample_rate_hz=RATE)
    m = evaluate(demo, demo.events, profile)

    assert m.n_events == 2
    assert m.n_detected == 2            # recall: both staged collapses caught
    assert m.false_alarms == 0          # the gate number
    assert m.false_alarms_per_week == 0.0
    assert m.kind_correct == 2          # sudden vs slow labelled right
    assert m.mean_latency > 0           # alerts arrive after onset, as expected
