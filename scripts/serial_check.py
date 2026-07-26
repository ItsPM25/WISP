"""Serial sanity check — run this the MOMENT the ESP32 streams, before anything else.

It answers the three questions that decide whether the live path will work:
  1. Are CSI_DATA lines actually arriving on this port?  (hardware/driver/SSID ok?)
  2. Does wisp.ingest.parser.parse_csi_line understand the real line format?
  3. Is the subcarrier count stable packet-to-packet?  (masking/calibration need this)

It only READS the port (no flashing, no writes). Prints a verdict, then exits.

Usage (inside the WSL venv, from the repo root):
    python scripts/serial_check.py --port /dev/ttyUSB0
    python scripts/serial_check.py --port /dev/ttyUSB0 --baud 921600 --n 20 --seconds 15
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wisp.ingest.parser import parse_csi_line  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="e.g. /dev/ttyUSB0 (WSL/Linux) or COM5 (Windows)")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--prefix", default="CSI_DATA")
    ap.add_argument("--n", type=int, default=12, help="how many CSI packets to sample")
    ap.add_argument("--seconds", type=float, default=15.0, help="give up after this long")
    args = ap.parse_args()

    try:
        import serial
    except Exception:
        print("pyserial not installed. In the venv:  pip install pyserial")
        sys.exit(2)

    try:
        ser = serial.Serial()
        ser.port = args.port
        ser.baudrate = args.baud
        ser.timeout = 1.0
        ser.dtr = False   # don't reset the ESP32 on open (RTS->EN, DTR->GPIO0)
        ser.rts = False
        ser.open()
        ser.dtr = False
        ser.rts = False
    except Exception as exc:
        print(f"could not open {args.port} @ {args.baud}: {exc}")
        print("  -> check the port name (ls /dev/ttyUSB*), re-attach USB (usbipd), and the baud.")
        sys.exit(2)

    print(f"listening on {args.port} @ {args.baud} for up to {args.seconds:.0f}s ...\n")
    total_lines = 0
    csi = 0
    widths: Counter = Counter()
    shown = 0
    parse_fail = 0
    deadline = time.time() + args.seconds
    first_amp = None

    try:
        while time.time() < deadline and csi < args.n:
            raw = ser.readline().decode("ascii", errors="ignore").strip()
            if not raw:
                continue
            total_lines += 1
            if not raw.startswith(args.prefix):
                continue
            csi += 1
            try:
                amp = parse_csi_line(raw)
            except ValueError as exc:
                parse_fail += 1
                if parse_fail <= 3:
                    print(f"  [parse FAIL] {exc}\n     line: {raw[:90]}...")
                continue
            widths[amp.size] += 1
            if shown < 4:
                shown += 1
                print(f"  [ok] subcarriers={amp.size:>3}  amp[min/mean/max]="
                      f"{amp.min():.1f}/{amp.mean():.1f}/{amp.max():.1f}")
                print(f"       raw: {raw[:90]}{'...' if len(raw) > 90 else ''}")
            if first_amp is None:
                first_amp = amp
    finally:
        ser.close()

    print("\n" + "=" * 60)
    print(f"lines seen: {total_lines}   |   CSI_DATA packets: {csi}   |   parse failures: {parse_fail}")
    if csi == 0:
        print("VERDICT: NO CSI. Nothing with the CSI_DATA prefix arrived.")
        print("  -> SSID/password mismatch between active_ap and active_sta is the #1 cause;")
        print("     also check the RX is the AP board and the TX (STA) actually connected.")
        sys.exit(1)
    if widths:
        common, count = widths.most_common(1)[0]
        stable = len(widths) == 1
        print(f"subcarrier width: {dict(widths)}  ({'STABLE' if stable else 'VARYING — investigate'})")
        print("VERDICT: CSI IS FLOWING and parser.py understands it. "
              + ("Widths are stable — you're ready to go live." if stable
                 else "Widths vary — masking still works, but note it."))
        print("\nNext:  python server/app.py --serial %s --room \"Washroom 3B\"" % args.port)
    else:
        print("VERDICT: CSI_DATA lines arrived but parser.py could not decode any.")
        print("  -> the real line format differs; capture one line and adjust wisp/ingest/parser.py.")
        sys.exit(1)


if __name__ == "__main__":
    main()
