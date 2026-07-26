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


def normalize_agc(amp: np.ndarray) -> np.ndarray:
    """Per-packet amplitude normalization for ESP32 CSI.

    Raw ESP32 CSI amplitude includes the receiver's automatic gain control (AGC): the whole
    packet scales up/down between frames for reasons unrelated to the channel, which shows up
    as large fake "motion". Dividing each packet by its own mean removes that global scale and
    keeps only the RELATIVE subcarrier shape — so downstream variance reflects real channel
    change (a body moving) rather than AGC jitter. Empty/near-zero packets pass through.
    """
    mean = float(np.mean(amp))
    return amp / mean if mean > 1e-6 else amp


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

        # Open WITHOUT asserting DTR/RTS: on ESP32 dev boards RTS->EN and DTR->GPIO0, so a
        # normal open resets the chip (and can hold it in reset), which shows up as garbage /
        # no CSI. Configure the lines low before opening so the running firmware keeps streaming.
        ser = serial.Serial()
        ser.port = self.port
        ser.baudrate = self.baud
        ser.timeout = self.timeout
        ser.dtr = False
        ser.rts = False
        ser.open()
        ser.dtr = False
        ser.rts = False
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
