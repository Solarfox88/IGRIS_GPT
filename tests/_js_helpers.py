"""Shared helpers for JS frontend tests (#1318).

After modularizing app.js into ES modules, many tests that checked for
string presence in app.js need to check across all JS files instead.

This helper provides a single function that concatenates all JS source
files so tests can search the full frontend codebase.
"""
from pathlib import Path

_REPO = Path(__file__).parent.parent
_JS_DIR = _REPO / "igris" / "web" / "static" / "js"


def read_all_js() -> str:
    """Concatenate all JS source files in the static/js directory.

    Returns a single string containing the content of every .js file,
    separated by newlines. This allows tests to search for strings that
    may now live in any of the extracted ES modules.
    """
    parts = []
    for js_file in sorted(_JS_DIR.glob("*.js")):
        parts.append(js_file.read_text(encoding="utf-8"))
    return "\n".join(parts)


def read_app_js() -> str:
    """Read only app.js (the entry point)."""
    return (_JS_DIR / "app.js").read_text(encoding="utf-8")


def read_auth_js() -> str:
    """Read auth.js + auth_ui.js combined."""
    parts = []
    for name in ("auth.js", "auth_ui.js"):
        p = _JS_DIR / name
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)
