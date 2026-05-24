"""
ToolOutputCompactor — rule-driven stdout compaction before LLM injection.

Implements configurable compaction rules to reduce token usage and noise
from tool outputs (bash stdout, test runner logs, etc.).
"""

import re
from typing import List, Optional, Set


class ToolOutputCompactor:
    """Apply compaction rules to tool output text."""

    # ANSI escape sequence pattern (most common types)
    ANSI_ESCAPE = re.compile(
        r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])'
    )

    # Recognisable test runner markers (case-insensitive)
    TEST_RUNNER_MARKERS = re.compile(
        r'(FAILED|ERROR|PASSED|FAILURES|test session starts|'
        r'Ran \d+ tests? in|\d+ passed|\d+ failed|'
        r'OK \(\d+ tests?\))',
        re.IGNORECASE
    )

    # Characters to collapse when they repeat verbatim
    COLLAPSE_CHARS = re.compile(r'([.-=*#])\1{2,}')

    # Stack trace line pattern (typical indent or "at " prefix)
    STACK_TRACE_LINE = re.compile(
        r'^\s+at\s+|^\s+File\s+".*",\s+line\s+|^Traceback|^\s+\^\s*$'
    )

    DEFAULT_RULES: List[str] = [
        'strip_ansi',
        'dedup_adjacent',
        'collapse_patterns',
        'truncate_stacktraces',
        'tail_test_runners'
    ]

    def __init__(self, rules: Optional[List[str]] = None):
        self.rules = rules or self.DEFAULT_RULES

    def compact(self, text: str, rules: Optional[List[str]] = None) -> str:
        """Apply all requested rules and return the compacted string."""
        active = rules or self.rules
        result = text

        for rule in active:
            method = getattr(self, f'_rule_{rule}', None)
            if method is None:
                # Unknown rule – skip silently
                continue
            result = method(result)

        return result

    # ---- private rule methods ----

    def _rule_strip_ansi(self, text: str) -> str:
        """Remove ANSI color/style escape codes."""
        return self.ANSI_ESCAPE.sub('', text)

    def _rule_dedup_adjacent(self, text: str) -> str:
        """Deduplicate consecutive identical lines.

        Lines that repeat more than once are collapsed to a single instance,
        optionally with a count annotation.
        """
        lines = text.splitlines()
        if not lines:
            return text

        out: List[str] = []
        prev = None
        count = 0

        for line in lines:
            if line == prev:
                count += 1
            else:
                if prev is not None:
                    if count == 1:
                        out.append(prev)
                    else:
                        out.append(f'{prev}  [repeated {count} times]')
                prev = line
                count = 1

        # handle trailing group
        if prev is not None:
            if count == 1:
                out.append(prev)
            else:
                out.append(f'{prev}  [repeated {count} times]')

        return '\n'.join(out)

    def _rule_collapse_patterns(self, text: str) -> str:
        """Collapse long runs of the same character (e.g. dots, dashes)."""
        def _replace(match):
            char = match.group(0)[0]
            length = len(match.group(0))
            return f'[{length}× "{char}"]'

        return self.COLLAPSE_CHARS.sub(_replace, text)

    def _rule_truncate_stacktraces(self, text: str) -> str:
        """Keep first 10 + last 5 lines of a stack trace, elide middle.

        We identify a contiguous block of lines that look like a stack trace
        and shorten it.
        """
        lines = text.splitlines()
        trace_blocks = self._find_trace_blocks(lines)
        if not trace_blocks:
            return text

        # Work from end to start to keep indices stable
        for start, end in reversed(trace_blocks):
            if end - start + 1 <= 15:
                continue  # short trace, keep as-is
            keep_head = lines[start:start + 10]
            keep_tail = lines[end - 4:end + 1]  # last 5 lines
            elision = [
                f'  [... {end - start + 1 - 15} lines elided ...]',
            ]
            replacement = keep_head + elision + keep_tail
            lines[start:end + 1] = replacement

        return '\n'.join(lines)

    def _rule_tail_test_runners(self, text: str) -> str:
        """For test runner output, keep the opening and the final summary.

        Keeps first 5 lines (command header) and last 80 lines.
        If the output does not look like a test run, it is returned unchanged.
        """
        if not self._is_test_output(text):
            return text

        lines = text.splitlines()
        if len(lines) <= 85:
            return text

        head = lines[:5]
        tail = lines[-80:]
        return '\n'.join(head + [f'  [... {len(lines) - 85} lines omitted ...]'] + tail)

    # ---- helpers ----

    def _is_test_output(self, text: str) -> bool:
        """Return True if text looks like a test runner summary."""
        return bool(self.TEST_RUNNER_MARKERS.search(text))

    def _find_trace_blocks(self, lines: List[str]) -> List[List[int]]:
        """Return list of [start, end] indices (inclusive) of stack trace blocks."""
        blocks = []
        i = 0
        while i < len(lines):
            if not self.STACK_TRACE_LINE.match(lines[i]):
                i += 1
                continue
            start = i
            while i < len(lines) and self.STACK_TRACE_LINE.match(lines[i]):
                i += 1
            end = i - 1
            blocks.append([start, end])
        return blocks
