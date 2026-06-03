"""Tests for response readability enforcement — issue #953."""
from __future__ import annotations
import pytest
from igris.core.response_readability import (
    check_readability,
    LONG_RESPONSE_WORD_THRESHOLD,
    MAX_PARAGRAPH_WORDS,
    MAX_CONSECUTIVE_PLAIN_LINES,
)


def _words(n: int) -> str:
    """Generate a string with exactly n words."""
    return " ".join(["word"] * n)


def _lines(n: int) -> str:
    """Generate n non-empty lines of plain text (no structure)."""
    return "\n".join([f"This is plain line {i}." for i in range(n)])


# ---------------------------------------------------------------------------
# Short responses
# ---------------------------------------------------------------------------

def test_short_response_no_structure_passes():
    """Short response (< 200 words) passes even without any structure."""
    text = _words(50)
    report = check_readability(text)
    assert report.passed
    assert report.violations == []
    assert report.word_count == 50


def test_empty_text_passes():
    """Empty/whitespace text passes trivially."""
    report = check_readability("")
    assert report.passed
    assert report.word_count == 0


def test_whitespace_only_passes():
    report = check_readability("   \n\n  ")
    assert report.passed


# ---------------------------------------------------------------------------
# Long responses with structure
# ---------------------------------------------------------------------------

def test_long_response_with_headings_passes():
    """Long response with headings and short paragraphs passes."""
    # 10 sections, each with a heading and ~25 words — total > 200 words, structured
    sections = []
    for i in range(10):
        sections.append(f"## Section {i}\n\n" + _words(25))
    text = "\n\n".join(sections)
    report = check_readability(text)
    assert report.has_structure
    assert report.passed, report.violations


def test_long_response_with_bullets_passes():
    """Long response with bullet points passes.
    Each bullet is one line so no paragraph exceeds 150 words.
    """
    bullets = "\n".join([f"- Item {i}: some detail about this point." for i in range(60)])
    report = check_readability(bullets)
    assert report.has_structure
    assert report.passed, report.violations


def test_long_response_with_numbered_list_passes():
    """Numbered list counts as structure."""
    numbered = "\n".join([f"{i+1}. Step {i}: do something specific here." for i in range(60)])
    report = check_readability(numbered)
    assert report.has_structure
    assert report.passed, report.violations


# ---------------------------------------------------------------------------
# Long responses WITHOUT structure (violations)
# ---------------------------------------------------------------------------

def test_long_wall_of_text_fails():
    """Long response (>200 words) with no structure must fail."""
    text = _words(LONG_RESPONSE_WORD_THRESHOLD + 1)
    report = check_readability(text)
    assert not report.passed
    assert len(report.violations) >= 1
    assert any("words" in v for v in report.violations)


def test_paragraph_over_limit_fails():
    """Single paragraph exceeding MAX_PARAGRAPH_WORDS words fails."""
    big_para = _words(MAX_PARAGRAPH_WORDS + 10)
    # Use a heading so the only violation is the paragraph size
    text = "## Section\n\n" + big_para
    report = check_readability(text)
    assert not report.passed
    assert any("Paragraph" in v for v in report.violations)


def test_paragraph_exactly_at_limit_passes():
    """Paragraph exactly at MAX_PARAGRAPH_WORDS is acceptable."""
    para = _words(MAX_PARAGRAPH_WORDS)
    text = "## Section\n\n" + para
    report = check_readability(text)
    assert report.passed


# ---------------------------------------------------------------------------
# Consecutive plain lines
# ---------------------------------------------------------------------------

def test_too_many_consecutive_plain_lines_fails():
    """Block of > MAX_CONSECUTIVE_PLAIN_LINES consecutive plain lines fails."""
    text = _lines(MAX_CONSECUTIVE_PLAIN_LINES + 2)
    report = check_readability(text)
    assert not report.passed
    assert any("consecutive" in v for v in report.violations)


def test_consecutive_lines_under_limit_passes():
    """Block under the limit is fine."""
    text = _lines(MAX_CONSECUTIVE_PLAIN_LINES - 1)
    report = check_readability(text)
    # may fail due to word count but not consecutive
    assert not any("consecutive" in v for v in report.violations)


# ---------------------------------------------------------------------------
# Integration — realistic IGRIS-style responses
# ---------------------------------------------------------------------------

IGRIS_RESPONSE_STRUCTURED = """
## IGRIS Status Report

The system is currently operating within normal parameters.

### Active Modules
- DevOps Manager: online
- TTS Engine: degraded (model not loaded)
- GitHub Gateway: online

### Recent Actions
1. Fetched PR list from Solarfox88/IGRIS_GPT
2. Deployed hotfix to VPS node-01
3. Ran readability check on last 5 responses

All operations completed without errors.
"""

IGRIS_RESPONSE_SHORT = "The build is green. All tests passed."


def test_realistic_structured_response_passes():
    report = check_readability(IGRIS_RESPONSE_STRUCTURED)
    assert report.has_structure
    assert report.passed


def test_realistic_short_response_passes():
    report = check_readability(IGRIS_RESPONSE_SHORT)
    assert report.passed
