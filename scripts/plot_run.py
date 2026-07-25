"""Plot a detection run so you can SEE the signals and where alerts fire.

Runs the exact pipeline on the synthetic demo room and saves a PNG with two stacked
time-series: motion intensity and transient sharpness, with the staged-collapse windows
shaded, the calibration thresholds drawn, and each confirmed alert marked.

Usage:
    python scripts/plot_run.py [--profile room_profile.pkl] [--rate HZ] [--out run.png]
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib

matplotlib.use("Agg")  # headless-safe: write a file, don't require a display
import matplotlib.pyplot as plt  # noqa: E402

from wisp.calibrate.profile import RoomProfile   # noqa: E402
from wisp.detect.state_machine import DetectionStateMachine  # noqa: E402
from wisp.features.extract import feature_stream   # noqa: E402
from wisp.source.synthetic import SyntheticSource  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="room_profile.pkl")
    ap.add_argument("--rate", type=float, default=50.0)
    ap.add_argument("--out", default="run.png")
    args = ap.parse_args()

    if os.path.exists(args.profile):
        profile = RoomProfile.load(args.profile)
    else:
        profile = RoomProfile.fit(
            SyntheticSource.normal_only(minutes=3.0, sample_rate_hz=args.rate),
            sample_rate_hz=args.rate,
        )

    demo = SyntheticSource.demo(sample_rate_hz=args.rate)
    sm = DetectionStateMachine(
        still_threshold=profile.still_threshold, occupied_threshold=profile.occupied_threshold,
        sharp_threshold=profile.sharp_threshold, confirm_s=profile.confirm_s,
        slow_confirm_s=profile.slow_confirm_s, recent_activity_s=profile.recent_activity_s,
        debounce_s=profile.debounce_s,
    )

    ts, motion, sharp, alerts = [], [], [], []
    for t, feat in feature_stream(demo, profile.mask, profile.win_samples, profile.hop_samples):
        a = sm.update(t, feat, is_anomaly=profile.model.is_anomaly(feat))
        ts.append(t); motion.append(feat["motion_intensity"]); sharp.append(feat["transient_sharpness"])
        if a:
            alerts.append(a)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    for ax, series, color, label, thr in [
        (ax1, motion, "#0e9a94", "motion intensity", [("stillness floor", profile.still_threshold, "#5b48d6"),
                                                       ("occupied", profile.occupied_threshold, "#888")]),
        (ax2, sharp, "#5b48d6", "transient sharpness", [("impact threshold", profile.sharp_threshold, "#d83a2a")]),
    ]:
        for ev in demo.events:
            ax.axvspan(ev.onset, ev.end, color="#e0a020", alpha=0.15,
                       label="staged collapse" if ev is demo.events[0] else None)
        ax.plot(ts, series, color=color, lw=1.4, label=label)
        for name, v, c in thr:
            ax.axhline(v, color=c, ls="--", lw=1, label=name)
        for a in alerts:
            c = "#d83a2a" if a.kind.startswith("sudden") else "#c07800"
            ax.axvline(a.timestamp, color=c, lw=1.3)
        ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
        ax.set_ylabel(label.split()[0])
        ax.grid(True, alpha=0.15)

    for a in alerts:
        ax1.annotate(f"ALERT · {a.kind.replace('_',' ')}", xy=(a.timestamp, max(motion)),
                     fontsize=8, color="#d83a2a" if a.kind.startswith("sudden") else "#c07800",
                     ha="left", va="top")

    ax2.set_xlabel("time (s)")
    fig.suptitle("wisp — detection run on the synthetic demo room", fontsize=13, y=0.98)
    fig.tight_layout()
    fig.savefig(args.out, dpi=130)
    print(f"caught {[a.kind for a in alerts]}")
    print(f"saved -> {args.out}")


if __name__ == "__main__":
    main()
