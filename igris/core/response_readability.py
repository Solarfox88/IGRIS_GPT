"""Readability invariants for IGRIS responses.
Enforces measurable constraints on long responses to prevent wall-of-text outputs.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

@dataclass
class ReadabilityReport:
    passed: bool
    violations: list[str]
    word_count: int
    paragraph_count: int
    has_structure: bool  # headings or bullets present

# Thresholds
LONG_RESPONSE_WORD_THRESHOLD = 200      # responses longer than this must have structure
MAX_PARAGRAPH_WORDS = 150               # no single paragraph > 150 words
MAX_CONSECUTIVE_PLAIN_LINES = 20        # no block > 20 lines without break/heading/bullet

def check_readability(text: str) -> ReadabilityReport:
    """Check a response text against readability invariants."""
    words = text.split()
    word_count = len(words)

    # Split into paragraphs (double newline)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    paragraph_count = len(paragraphs)

    # Check for structural elements
    has_headings = bool(re.search(r'^#{1,6}\s+\S', text, re.MULTILINE))
    has_bullets = bool(re.search(r'^\s*[-*•]\s+\S', text, re.MULTILINE))
    has_numbered = bool(re.search(r'^\s*\d+[.)]\s+\S', text, re.MULTILINE))
    has_structure = has_headings or has_bullets or has_numbered

    violations = []

    # Long responses must have structure
    if word_count > LONG_RESPONSE_WORD_THRESHOLD and not has_structure:
        violations.append(
            f"Response has {word_count} words but no headings, bullets, or numbered lists"
        )

    # No single paragraph too long — skip paragraphs that are primarily lists/headings
    for i, para in enumerate(paragraphs):
        para_lines = para.split('\n')
        # If most lines are structured (bullets, numbered, headings), skip the check
        structured_lines = sum(
            1 for l in para_lines
            if re.match(r'^\s*(?:#{1,6}\s|[-*•]\s|\d+[.)]\s)', l.strip())
        )
        if para_lines and (structured_lines / len(para_lines)) >= 0.5:
            continue  # paragraph is primarily structured — exempt from word limit
        para_words = len(para.split())
        if para_words > MAX_PARAGRAPH_WORDS:
            violations.append(
                f"Paragraph {i+1} has {para_words} words (max {MAX_PARAGRAPH_WORDS})"
            )

    # No huge unbroken block of consecutive non-empty lines
    lines = text.split('\n')
    consecutive = 0
    for line in lines:
        stripped = line.strip()
        if stripped and not re.match(r'^#{1,6}\s|^[-*•]\s|^\d+[.)]\s|^\s*$', stripped):
            consecutive += 1
            if consecutive > MAX_CONSECUTIVE_PLAIN_LINES:
                violations.append(
                    f"Block of {consecutive}+ consecutive plain lines without structure break"
                )
                break
        else:
            consecutive = 0

    return ReadabilityReport(
        passed=len(violations) == 0,
        violations=violations,
        word_count=word_count,
        paragraph_count=paragraph_count,
        has_structure=has_structure,
    )
