"""S1 — CSI_DATA line parsing on known inputs and malformed lines."""

import numpy as np
import pytest

from wisp.ingest.parser import parse_csi_line


def test_space_separated_iq():
    # pairs (3,4),(6,8),(0,0),(-5,12) -> |.| = 5, 10, 0, 13
    amp = parse_csi_line("CSI_DATA,STA,aa:bb:cc,-40,11,[3 4 6 8 0 0 -5 12]")
    assert np.allclose(amp, [5.0, 10.0, 0.0, 13.0])


def test_comma_separated_iq_inside_brackets():
    amp = parse_csi_line("CSI_DATA,[3,4,6,8]")
    assert np.allclose(amp, [5.0, 10.0])


def test_missing_bracket_raises():
    with pytest.raises(ValueError):
        parse_csi_line("CSI_DATA,STA,no,iq,block,here")


def test_odd_iq_count_raises():
    with pytest.raises(ValueError):
        parse_csi_line("CSI_DATA,[1 2 3]")
