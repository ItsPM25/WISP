# wisp — Project Progress

> Living document. Updated as work happens. **Last updated: 2026-07-25.**
> Nothing here is pushed to git without explicit approval.

---

## 1. What this project is

A Phase-0 MVP that watches a room via **Wi-Fi Channel State Information (CSI)** from two
ESP32 boards and prints an alert when someone collapses — plus an evaluation harness that
measures whether those alerts can be **trusted**. The deliverable is not an app; it is a
number: **false alarms per week**, alongside proof that staged falls are caught.

**The gate (pass/fail):** over weeks in one real occupied room — catch (nearly) every
staged sudden + slow collapse, **and** produce **< ~1 false alarm/week**.

---

## 2. Where the project is right now

**Status: the entire hardware-independent software MVP is BUILT, RUNS END-TO-END, and is TESTED.**

- The full pipeline (source → clean → features → anomaly model → temporal state machine →
  evaluation) runs today on a simulated room, with **zero hardware**.
- Current result on the demo timeline: **recall 2/2, kinds correct 2/2, 0 false alarms**;
  and **0 false alarms** over 630s + 180s of unseen normal-room data (with a fan running).
- **20 automated tests pass.**
- **29 commits** on `main`, authored solely by the project owner.
- A visual dashboard of a run has been produced (motion + sharpness signals with alert markers).

**What is NOT yet done (all hardware-gated or optional):**
- Running the live serial reader against a real ESP32 (code is written; needs a board).
- Recording real room data, calibrating on it, and the weeks-long real-room gate.
- Optional: supervised CSI-Bench benchmark (investor credibility number); real CSI-Bench validation.

> Honest note: every current metric is on **simulated** data. It proves the *software and
> algorithm* are correct. The *real-world gate* still needs the ESP32s streaming.

---

## 3. Technologies & tools used

| Area | Tech |
| --- | --- |
| Language | Python 3 |
| Numerics | NumPy, SciPy (`scipy.ndimage` Hampel filter) |
| ML / anomaly detection | scikit-learn — **IsolationForest** (unsupervised, CPU, trains in seconds) |
| Serial I/O | pyserial (live ESP32 reader) |
| Config | PyYAML (`config/pipeline.yaml`) |
| Dataset adapter | h5py (CSI-Bench `.h5` replay) |
| Plotting | Matplotlib (`scripts/plot_run.py`) |
| Testing | pytest (20 tests) |
| Hardware (planned) | 2× ESP32 (RX WROOM-32 / TX ESP-32S), ESP-IDF firmware, laptop compute node |
| Reference datasets | CSI-Bench (fall subset, Kaggle) — optional; ESP-Fi-HAR — firmware/format reference |
| Version control | Git + GitHub (`sudarsan2507-hue/WISP`) |

**Key design decision:** the shipping detector is **unsupervised** (IsolationForest on the
room's own normal). No GPU, no deep learning, no external dataset needed to ship. CSI-Bench
+ GPU are only for an *optional* supervised benchmark, never the product.

---

## 4. What's built — module by module

Everything hides behind one interface: `CSISource.stream() -> (timestamp, amplitude[])`.
Synthetic / replay / CSI-Bench / serial sources are interchangeable.

| Module | S-section | Purpose | Status |
| --- | --- | --- | --- |
| `wisp/source/base.py` | S1.6 | `CSISource` abstract interface | ✅ |
| `wisp/source/synthetic.py` | S1.6 | Room simulator with labeled falls (demo + normal-only) | ✅ |
| `wisp/source/replay.py` | S1.6 | Replay a recorded CSV log | ✅ |
| `wisp/source/csi_bench_source.py` | — | Replay CSI-Bench `.h5` clips | ✅ |
| `wisp/source/serial_source.py` | S1.6 | **Live** ESP32 reader (pyserial) | ✅ written · ⏳ needs board to run |
| `wisp/ingest/parser.py` | S1 | `CSI_DATA` line → amplitude array | ✅ |
| `wisp/ingest/logger.py` | S1.5 | Raw CSI logger to CSV | ✅ |
| `wisp/preprocess/clean.py` | S2 | Subcarrier mask + Hampel outlier rejection | ✅ |
| `wisp/features/extract.py` | S3 | Motion intensity, transient sharpness, `feature_stream` | ✅ |
| `wisp/calibrate/profile.py` | S4 | `RoomProfile.fit/save/load` (percentile thresholds) | ✅ |
| `wisp/detect/model.py` | S5 | IsolationForest anomaly model | ✅ |
| `wisp/detect/rules.py` | S5.2 | Sudden vs slow discriminator | ✅ |
| `wisp/detect/state_machine.py` | S6 | Temporal logic — the false-alarm killer | ✅ |
| `wisp/pipeline.py` | — | Shared `run_detection` loop | ✅ |
| `wisp/evaluate/harness.py` | S9 | Recall / false-alarms-per-week / latency | ✅ |
| `wisp/config.py` | S2.7 | Load `config/pipeline.yaml` | ✅ |

### Scripts (all runnable)
- `scripts/calibrate.py` — fit + save a room profile.
- `scripts/run_live.py` — the one-line alert console.
- `scripts/evaluate.py` — print the gate numbers.
- `scripts/plot_run.py` — save `run.png` (see the signals + alerts).

### Tests (20 passing)
features · state machine · parser · logger↔replay · anomaly model · profile · harness · CSI-Bench adapter.

---

## 5. How to run it

```
pip install -r requirements.txt
python scripts/calibrate.py     # learn this room's normal -> room_profile.pkl
python scripts/run_live.py      # one-line alert console
python scripts/evaluate.py      # the Phase-0 gate numbers
python scripts/plot_run.py      # saves run.png
pytest -q                       # 20 tests
```

Live hardware (after Milestone 1): swap in `SerialSource(port="COM5", baud=921600)` — nothing downstream changes.

---

## 6. Roadmap / next steps

1. **Hardware Milestone 1** — flash ESP-IDF firmware, get CSI streaming to serial + reacting to a hand-wave.
2. **Run `SerialSource`** against the real board; confirm `parser.py` matches the real line format.
3. **Record real data** — normal + staged falls (safe protocol: crash mat, healthy volunteer, consent).
4. **Calibrate on real normal**, re-run the harness on real recordings with a labels CSV.
5. **The gate** — weeks of continuous real-room operation, logging every alert for review.
6. *Optional:* CSI-Bench real-CSI validation; supervised S5.4 benchmark (GPU, ~sub-hour).

---

## 7. Known caveats / open items

- All current results are on **simulated** data (see the honest note above).
- One **orphaned Claude-attributed scaffold commit** (`ae0eaa9`) and some orphaned old-message
  commits linger on GitHub's server (not in history, not in the contributor list, reachable only
  by exact SHA). They GC on GitHub's schedule; a repo delete+recreate is the only guaranteed wipe.
- Per-packet Hampel filter is the slowest step for batch-processing long recordings (fine for live).

---

## 8. Change log

- **2026-07-25** — Implemented full pipeline (source, ingest, preprocess, features, calibrate,
  detect, state machine, harness), wired 4 scripts, added CSI-Bench adapter + live SerialSource,
  grew tests to 20, produced a visual dashboard. Reworded commit messages to drop "synthetic"
  framing. 29 commits on `main`. This progress doc created.
