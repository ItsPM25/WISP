"""S5 — the anomaly model flags clear outliers and passes normal points."""

import numpy as np

from wisp.detect.model import AnomalyModel


def test_flags_outlier_not_normal():
    rng = np.random.default_rng(0)
    # normal cluster: low motion, low sharpness
    normal = rng.normal([1.0, 0.1], [0.2, 0.05], size=(400, 2))
    model = AnomalyModel(contamination=0.01, random_state=0)
    model.fit(normal)

    normal_pt = {"motion_intensity": 1.0, "transient_sharpness": 0.1}
    outlier = {"motion_intensity": 50.0, "transient_sharpness": 30.0}

    assert model.is_anomaly(outlier) is True
    assert model.is_anomaly(normal_pt) is False
    # score is higher (more anomalous) for the outlier
    assert model.score(outlier) > model.score(normal_pt)


def test_to_vector_is_ordered():
    v = AnomalyModel.to_vector({"transient_sharpness": 9.0, "motion_intensity": 2.0})
    assert list(v) == [2.0, 9.0]   # motion first, then sharpness (FEATURES order)
