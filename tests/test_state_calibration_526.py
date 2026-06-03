"""Tests for StateCalibration — issue #526."""
import pytest
from igris.core.state_calibration import StateCalibration


@pytest.fixture()
def sc():
    return StateCalibration()


def test_routine_state(sc):
    s = sc.detect("Show me the current status")
    assert s.state in ("routine", "confusion")  # mild


def test_urgency_detection(sc):
    s = sc.detect("asap! restart the server now!!")
    assert s.is_urgent


def test_frustration_detection(sc):
    s = sc.detect("It's broken again! Still doesn't work!")
    assert s.is_frustrated or s.state in ("urgency", "frustration")


def test_confusion_detection(sc):
    s = sc.detect("I don't understand what to do, help me explain")
    assert s.is_confused or s.state in ("confusion",)


def test_response_mode_novice(sc):
    sig = sc.detect("help me please")
    mode = sc.select_response_mode(sig, expertise_level="novice", communication_style="casual")
    assert mode.simplify_language or mode.verbosity in ("normal", "detailed")


def test_response_mode_expert(sc):
    sig = sc.detect("run deploy pipeline")
    mode = sc.select_response_mode(sig, expertise_level="expert", communication_style="technical")
    assert mode.verbosity in ("minimal", "normal")
