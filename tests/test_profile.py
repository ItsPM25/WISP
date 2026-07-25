"""S4 — RoomProfile fits sensible thresholds and survives save/load."""

import numpy as np

from wisp.calibrate.profile import RoomProfile
from wisp.source.synthetic import SyntheticSource

RATE = 25.0


def _fit():
    return RoomProfile.fit(
        SyntheticSource.normal_only(minutes=1.0, sample_rate_hz=RATE),
        sample_rate_hz=RATE,
    )


def test_fit_produces_ordered_thresholds():
    p = _fit()
    assert 0 < p.still_threshold < p.occupied_threshold      # still floor below occupied
    assert p.sharp_threshold > 0
    assert 0 < int(p.mask.sum()) < p.mask.size               # some subcarriers dropped as dead
    assert p.win_samples >= 2 and p.hop_samples >= 1


def test_save_load_roundtrip_preserves_detection(tmp_path):
    p = _fit()
    fp = tmp_path / "profile.pkl"
    p.save(str(fp))
    q = RoomProfile.load(str(fp))

    assert np.array_equal(p.mask, q.mask)
    assert p.still_threshold == q.still_threshold
    feat = {"motion_intensity": 100.0, "transient_sharpness": 50.0}
    assert p.model.is_anomaly(feat) == q.model.is_anomaly(feat)
