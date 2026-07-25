"""SerialSource — the ONLY file that touches hardware. Written last, by design.

Reads CSI_DATA lines from the RX ESP32 over pyserial, hands each line to
``ingest.parser.parse_csi_line``, and yields ``(timestamp, amplitude)`` exactly like
every other source. Because the whole pipeline was built and tested against this same
interface, plugging this in runs the already-validated brain on live data unchanged.

pyserial is imported lazily inside ``stream`` so the module (and the rest of wisp) imports
fine on a machine with no hardware and no pyserial installed. Timestamps are wall-clock
arrival times relative to the first packet.
"""

from __future__ import annotations

import time
from typing import Iterator, Optional, Tuple

import numpy as np

from ..ingest.parser import parse_csi_line
from .base import CSISource


class SerialSource(CSISource):
    """Live CSI stream from the RX ESP32 over a serial port.

    Parameters
    ----------
    port : str
        Serial device, e.g. ``COM5`` (Windows) or ``/dev/ttyUSB0`` (Linux).
    baud : int
        Must match the firmware (MVP target 921600).
    prefix : str
        Only lines starting with this token are parsed (skips boot/log chatter).
    timeout : float
        Per-line read timeout in seconds.
    max_packets : int, optional
        Stop after this many packets (handy for a bounded capture); None = run forever.
    """

    def __init__(
        self,
        port: str,
        baud: int = 921600,
        prefix: str = "CSI_DATA",
        timeout: float = 1.0,
        max_packets: Optional[int] = None,
    ) -> None:
        self.port = port
        self.baud = baud
        self.prefix = prefix
        self.timeout = timeout
        self.max_packets = max_packets

    def stream(self) -> Iterator[Tuple[float, np.ndarray]]:
        import serial  # pyserial — imported lazily so no-hardware machines still import wisp

        ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        t0 = time.time()
        n = 0
        try:
            while self.max_packets is None or n < self.max_packets:
                raw = ser.readline().decode("ascii", errors="ignore").strip()
                if not raw or (self.prefix and not raw.startswith(self.prefix)):
                    continue
                try:
                    amp = parse_csi_line(raw)
                except ValueError:
                    continue  # malformed/partial line — skip, don't crash the stream
                yield time.time() - t0, amp
                n += 1
        finally:
            ser.close()
