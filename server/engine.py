"""server/engine.py — the live monitoring engine behind the dashboard.

Responsibilities (framework-agnostic; no Flask here, so it stays unit-testable):

1. **Source selection with a fallback chain** — the heart of the demo's honesty:
       LIVE ESP32 (CSI actually streaming)  ->  real-data replay (CSI-Bench / recording)
       ->  synthetic demo room
   Whichever is chosen is reported as ``mode`` = LIVE | FALLBACK plus a human label, so the
   UI can ALWAYS show which one is running. A fallback is never silent.

2. **One detection path** — runs ``wisp.pipeline.detection_telemetry`` (same code the gate
   harness uses) in a background thread and keeps a thread-safe snapshot of room state.

3. **Escalation** — on a confirmed collapse, a cancellable countdown runs; if nobody
   cancels it, it "notifies the emergency contact". All timing is computed from wall-clock
   in ``snapshot`` so any number of dashboard viewers agree.

The web layer (``server/app.py``) is a thin shell over this.
"""

from __future__ import annotations

import glob
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional

from wisp.calibrate.profile import RoomProfile
from wisp.pipeline import detection_telemetry
from wisp.source.base import CSISource
from wisp.source.replay import ReplaySource
from wisp.source.serial_source import SerialSource
from wisp.source.synthetic import SyntheticSource

# ------------------------------------------------------------------ config

_KIND_LABEL = {"sudden_collapse": "sudden collapse", "slow_collapse": "slow collapse"}
_STATE_LABEL = {
    "NORMAL": "normal",
    "DISTURBANCE": "disturbance",
    "STILL": "still",
    "CONFIRMED": "collapse confirmed",
}
_HISTORY = 160          # motion-history samples kept for the sparkline
_STALE_AFTER_S = 3.0    # no telemetry update for this long => feed considered stale
_ESCALATION_HOLD_S = 6.0  # keep "notified" on screen this long before re-arming (looping demo)


@dataclass
class EngineOptions:
    # source chain
    serial_port: Optional[str] = None     # explicit port; None => autodetect (unless probe_serial False)
    probe_serial: bool = True             # try live ESP32 first
    baud: int = 921600
    probe_s: float = 6.0                  # how long to wait for a CSI line before giving up
    csi_bench: Optional[str] = None       # path to CSI-Bench .h5 file/dir (real-data fallback)
    replay: Optional[str] = None          # path to a recorded RawLogger CSV (real-data fallback)
    # calibration
    profile_path: str = "room_profile.pkl"
    calibrate_s: float = 20.0             # seconds of live "normal" to fit a live profile
    rate_hz: float = 50.0                 # synthetic sample rate / nominal live rate
    # playback + demo flavour
    speed: float = 3.0                    # fallback playback speed multiplier (live is real-time)
    loop: bool = True                     # loop finite fallback streams (unattended demo)
    escalate_s: float = 15.0              # countdown before auto-notifying the contact
    room: str = "Room 1"
    contact: str = "Emergency contact"


@dataclass
class _SourceChoice:
    source: CSISource
    mode: str        # "LIVE" | "FALLBACK"
    live: bool
    kind: str        # serial | csi_bench | replay | synthetic
    label: str       # human label for the badge
    note: str        # why this source / extra context
    sample_rate_hz: float


# ------------------------------------------------------------------ probing / selection

def _autodetect_ports() -> List[str]:
    """Linux/WSL serial devices the ESP32 typically shows up as."""
    return sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))


def probe_serial(port: str, baud: int, probe_s: float, prefix: str = "CSI_DATA") -> bool:
    """Return True iff a ``CSI_DATA`` line arrives on ``port`` within ``probe_s`` seconds.

    Safe on machines with no hardware / no pyserial: any failure => False (=> fallback).
    """
    try:
        import serial  # pyserial, lazy
    except Exception:
        return False
    try:
        with serial.Serial(port, baud, timeout=0.5) as ser:
            deadline = time.time() + probe_s
            while time.time() < deadline:
                raw = ser.readline().decode("ascii", errors="ignore").strip()
                if raw.startswith(prefix):
                    return True
    except Exception:
        return False
    return False


def choose_source(opts: EngineOptions) -> _SourceChoice:
    """Walk the fallback chain and return the first source that is actually available."""
    # 1) LIVE ESP32 — only if a port probes positive for real CSI
    if opts.probe_serial:
        ports = [opts.serial_port] if opts.serial_port else _autodetect_ports()
        for port in ports:
            if port and probe_serial(port, opts.baud, opts.probe_s):
                return _SourceChoice(
                    source=SerialSource(port, opts.baud),
                    mode="LIVE", live=True, kind="serial",
                    label=f"ESP32 · {port}",
                    note=f"live CSI streaming from the ESP32 on {port}",
                    sample_rate_hz=opts.rate_hz,
                )
        tried = ", ".join(p for p in ports if p) or "no serial ports found"
        fallback_note = f"no live ESP32 CSI ({tried}) — running on fallback data"
    else:
        fallback_note = "live probe disabled — running on fallback data"

    # 2) real-data replay — CSI-Bench (real captured CSI) or a recorded CSV
    if opts.csi_bench:
        try:
            from wisp.source.csi_bench_source import CSIBenchSource
            return _SourceChoice(
                source=CSIBenchSource(opts.csi_bench, sample_rate_hz=opts.rate_hz),
                mode="FALLBACK", live=False, kind="csi_bench",
                label="CSI-Bench · real captured CSI",
                note=f"{fallback_note}; replaying CSI-Bench clips: {opts.csi_bench}",
                sample_rate_hz=opts.rate_hz,
            )
        except Exception as exc:  # pragma: no cover - depends on optional h5py/data
            fallback_note += f"; CSI-Bench unavailable ({exc})"
    if opts.replay:
        return _SourceChoice(
            source=ReplaySource(opts.replay),
            mode="FALLBACK", live=False, kind="replay",
            label="Recording · replayed CSI log",
            note=f"{fallback_note}; replaying recording: {opts.replay}",
            sample_rate_hz=opts.rate_hz,
        )

    # 3) synthetic demo room — always available, correct, self-contained
    return _SourceChoice(
        source=SyntheticSource.demo(sample_rate_hz=opts.rate_hz),
        mode="FALLBACK", live=False, kind="synthetic",
        label="Synthetic demo room",
        note=f"{fallback_note}; using the built-in synthetic room",
        sample_rate_hz=opts.rate_hz,
    )


# ------------------------------------------------------------------ calibration

def build_profile(opts: EngineOptions, choice: _SourceChoice) -> RoomProfile:
    """Load a saved profile if present, else fit one appropriate to the chosen source."""
    import os

    if os.path.exists(opts.profile_path):
        return RoomProfile.load(opts.profile_path)

    if choice.live:
        # Calibrate on the room's OWN live normal (room must be behaving normally now).
        n = max(200, int(opts.calibrate_s * opts.rate_hz))
        cal = SerialSource(choice.source.port, choice.source.baud, max_packets=n)  # type: ignore[attr-defined]
        profile = RoomProfile.fit(cal, sample_rate_hz=opts.rate_hz)
        profile.save(opts.profile_path)
        return profile

    # Fallback sources: calibrate on synthetic normal at the same rate (matches the
    # synthetic demo exactly; a reasonable default for replay code-path demos too).
    profile = RoomProfile.fit(
        SyntheticSource.normal_only(minutes=3.0, sample_rate_hz=opts.rate_hz),
        sample_rate_hz=opts.rate_hz,
    )
    return profile


# ------------------------------------------------------------------ the engine

class MonitorEngine:
    """Runs detection in a background thread and exposes a thread-safe snapshot."""

    def __init__(self, opts: Optional[EngineOptions] = None) -> None:
        self.opts = opts or EngineOptions()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.choice: Optional[_SourceChoice] = None
        self.profile: Optional[RoomProfile] = None

        self._started_at = 0.0
        self._last_update = 0.0
        self._packets = 0
        self._cur = {"t": 0.0, "state": "NORMAL", "motion": 0.0, "sharp": 0.0, "motion_norm": 0.0}
        self._history: deque = deque(maxlen=_HISTORY)
        self._stream_ended = False
        self._error: Optional[str] = None

        # alert / escalation state
        self._alert: Optional[dict] = None   # {kind_raw, kind, confidence, stillness_s, at_t, deadline}
        self._escalated_at: Optional[float] = None
        self._resolution: Optional[str] = None   # "cancelled" | "notified"
        self._last_resolved_at = 0.0

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> "MonitorEngine":
        self.choice = choose_source(self.opts)
        self.profile = build_profile(self.opts, self.choice)
        self._started_at = time.time()
        self._last_update = time.time()
        self._thread = threading.Thread(target=self._run, name="wisp-monitor", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        assert self.choice is not None and self.profile is not None
        try:
            first_pass = True
            # Loop finite fallback streams so the demo runs unattended; live never loops.
            while not self._stop.is_set() and (first_pass or (self.opts.loop and not self.choice.live)):
                first_pass = False
                # A fresh source each pass (generators are one-shot).
                source = self.choice.source if self.choice.live else self._fresh_source()
                wall0 = time.time()
                for t, feat, state, alert in detection_telemetry(source, self.profile):
                    if self._stop.is_set():
                        return
                    if not self.choice.live and self.opts.speed > 0:
                        target = wall0 + t / self.opts.speed
                        gap = target - time.time()
                        if gap > 0:
                            time.sleep(min(gap, 0.25))  # cap so stop stays responsive
                    self._ingest(t, feat, state, alert)
                if self.choice.live:
                    break
            with self._lock:
                self._stream_ended = True
        except Exception as exc:  # keep the server alive; surface the error to the UI
            with self._lock:
                self._error = f"{type(exc).__name__}: {exc}"
                self._stream_ended = True

    def _fresh_source(self) -> CSISource:
        """Re-create the chosen fallback source for another playback loop."""
        assert self.choice is not None
        c = self.choice
        if c.kind == "synthetic":
            return SyntheticSource.demo(sample_rate_hz=c.sample_rate_hz)
        if c.kind == "replay":
            return ReplaySource(self.opts.replay)  # type: ignore[arg-type]
        if c.kind == "csi_bench":
            from wisp.source.csi_bench_source import CSIBenchSource
            return CSIBenchSource(self.opts.csi_bench, sample_rate_hz=c.sample_rate_hz)  # type: ignore[arg-type]
        return c.source

    # -- ingest one window -------------------------------------------------
    def _ingest(self, t: float, feat: dict, state: str, alert) -> None:
        occ = self.profile.occupied_threshold or 1e-9
        motion = float(feat["motion_intensity"])
        with self._lock:
            self._last_update = time.time()
            self._packets += 1
            self._cur = {
                "t": round(t, 2),
                "state": state,
                "motion": motion,
                "sharp": float(feat["transient_sharpness"]),
                "motion_norm": max(0.0, min(motion / occ, 1.6)),
            }
            self._history.append(round(self._cur["motion_norm"], 4))

            if alert is not None and self._alert is None and self._resolution is None:
                self._alert = {
                    "kind_raw": alert.kind,
                    "kind": _KIND_LABEL.get(alert.kind, alert.kind.replace("_", " ")),
                    "confidence": alert.confidence,
                    "stillness_s": alert.stillness_s,
                    "at_t": round(alert.timestamp, 1),
                    "deadline": time.time() + self.opts.escalate_s,
                }
                self._escalated_at = None

    # -- external commands -------------------------------------------------
    def cancel(self) -> bool:
        """Dashboard 'I'm OK' — cancel an in-progress alert/escalation."""
        with self._lock:
            if self._alert is not None:
                self._alert = None
                self._escalated_at = None
                self._resolution = "cancelled"
                self._last_resolved_at = time.time()
                return True
            return False

    def reset(self) -> None:
        """Clear any resolved/alert state so the monitor returns to a clean baseline."""
        with self._lock:
            self._alert = None
            self._escalated_at = None
            self._resolution = None

    # -- snapshot ----------------------------------------------------------
    def _advance_escalation(self) -> None:
        """Compute escalation phase from wall clock; auto-clear after the hold window."""
        now = time.time()
        if self._alert is not None:
            if self._escalated_at is None and now >= self._alert["deadline"]:
                self._escalated_at = now
                self._resolution = "notified"
        # auto-clear a resolved alert after the hold, so a looping demo can re-fire
        if self._resolution is not None:
            ref = self._escalated_at or self._last_resolved_at
            if self._resolution == "notified" and self._escalated_at is not None and now - self._escalated_at >= _ESCALATION_HOLD_S:
                self._alert = None
                self._escalated_at = None
                self._resolution = None
            elif self._resolution == "cancelled" and now - self._last_resolved_at >= 2.0:
                self._resolution = None

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            self._advance_escalation()
            c = self.choice
            stale = c is not None and c.live and (now - self._last_update > _STALE_AFTER_S)

            if self._alert is not None:
                phase = "escalated" if self._escalated_at is not None else "active"
                countdown = max(0.0, self._alert["deadline"] - now)
                alert = {
                    "phase": phase,
                    "kind": self._alert["kind"],
                    "kind_raw": self._alert["kind_raw"],
                    "confidence": self._alert["confidence"],
                    "stillness_s": self._alert["stillness_s"],
                    "at_t": self._alert["at_t"],
                    "countdown_s": round(countdown, 1),
                    "resolution": self._resolution,
                }
            elif self._resolution == "cancelled":
                alert = {"phase": "cancelled", "resolution": "cancelled"}
            else:
                alert = {"phase": "none"}

            state = self._cur["state"]
            status_label = _STATE_LABEL.get(state, state.lower())

            return {
                "mode": None if c is None else c.mode,
                "live": bool(c and c.live),
                "source_kind": None if c is None else c.kind,
                "source_label": None if c is None else c.label,
                "note": None if c is None else c.note,
                "sample_rate_hz": None if c is None else c.sample_rate_hz,
                "room": self.opts.room,
                "contact": self.opts.contact,
                "escalate_s": self.opts.escalate_s,
                "running": self._thread is not None and self._thread.is_alive(),
                "stream_ended": self._stream_ended,
                "stale": stale,
                "error": self._error,
                "uptime_s": round(now - self._started_at, 1) if self._started_at else 0.0,
                "packets": self._packets,
                "thresholds": None if self.profile is None else {
                    "still": round(self.profile.still_threshold, 4),
                    "occupied": round(self.profile.occupied_threshold, 4),
                    "sharp": round(self.profile.sharp_threshold, 4),
                },
                "profile_summary": None if self.profile is None else self.profile.summary(),
                "monitor": {
                    "t": self._cur["t"],
                    "state": state,
                    "status_label": status_label,
                    "motion": round(self._cur["motion"], 4),
                    "motion_norm": round(self._cur["motion_norm"], 4),
                    "sharp": round(self._cur["sharp"], 4),
                    "history": list(self._history),
                },
                "alert": alert,
            }
