"""Tests for conservative directional news interpretation."""
from oracle.news_signal import headline_direction


def test_explicit_direction():
    assert headline_direction("Gold rises as traders reassess rates", "Gold") == "LONG"
    assert headline_direction("Crude oil falls after supply update", "WTI") == "SHORT"


def test_no_direction_from_generic_headline():
    assert headline_direction("Fed comments on interest rates", "Gold") is None
    assert headline_direction("Gold market awaits inflation report", "Gold") is None
