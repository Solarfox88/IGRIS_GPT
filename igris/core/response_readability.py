"""
Response Readability — audit helper for IGRIS chat responses (issue #953).

Checks a response text for readability violations (walls of text, excessive
length, missing structure). Non-blocking: results are logged as warnings and
optionally surfaced in the API response, but never block or modify the reply.

Usage:
    from igris.core.response_readability import check_readability
    result = check_readability(text)
    if not result.passed:
        logger.warning("Readability violations: %s", result.violations)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

# Thresholds
_MAX_WORDS_NO_STRUCTURE = 200       # words before structure (headers/bullets) is expected
_MAX_PARAGRAPH_WORDS = 150          # single paragraph word limit
_MAX_TOTAL_WORDS = 1000             # hard ceiling before wall-of-text warning
_MIN_WORDS_SHORT = 5                # below this, readability is N/A


@dataclass
class ReadabilityResult:
    """Result of a readability audit."""
    passed: bool
    word_count: int
    violations: List[str] = field(default_factory=list)
    short: bool = False  # True if text is too short to audit meaningfully

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "word_count": self.word_count,
            "violations": self.violations,
            "short": self.short,
        }


def check_readability(text: str) -> ReadabilityResult:
    """Audit a response text for readability violations.

    Rules:
    1. Short responses (< MIN_WORDS_SHORT words) always pass (short=True).
    2. Wall-of-text: > MAX_WORDS_NO_STRUCTURE words without any bullet/header.
    3. Long paragraph: any paragraph > MAX_PARAGRAPH_WORDS words.
    4. Total word count: > MAX_TOTAL_WORDS words → warning.

    Returns a ReadabilityResult with passed=True if no violations found.
    """
    if not text or not text.strip():
        return ReadabilityResult(passed=True, word_count=0, short=True)

    words = text.split()
    word_count = len(words)

    if word_count < _MIN_WORDS_SHORT:
        return ReadabilityResult(passed=True, word_count=word_count, short=True)

    violations: List[str] = []

    # Check for structure indicators (headers, bullets, numbered lists)
    has_structure = _has_structure(text)

    # Rule 1: Wall of text — many words with no structure
    if word_count > _MAX_WORDS_NO_STRUCTURE and not has_structure:
        violations.append(
            f"wall_of_text: {word_count} words with no headers or bullets "
            f"(threshold={_MAX_WORDS_NO_STRUCTURE})"
        )

    # Rule 2: Long paragraph
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for i, para in enumerate(paragraphs):
        para_words = len(para.split())
        if para_words > _MAX_PARAGRAPH_WORDS:
            violations.append(
                f"long_paragraph[{i}]: {para_words} words "
                f"(threshold={_MAX_PARAGRAPH_WORDS})"
            )

    # Rule 3: Total word ceiling
    if word_count > _MAX_TOTAL_WORDS:
        violations.append(
            f"excessive_length: {word_count} words total "
            f"(threshold={_MAX_TOTAL_WORDS})"
        )

    passed = len(violations) == 0
    return ReadabilityResult(passed=passed, word_count=word_count, violations=violations)


def _has_structure(text: str) -> bool:
    """Return True if text contains markdown headers, bullets, or numbered lists."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Markdown headers
        if stripped.startswith("#"):
            return True
        # Bullet points
        if stripped.startswith(("-", "*", "•", "+")):
            return True
        # Numbered list
        if len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in ".):":
            return True
    return False
