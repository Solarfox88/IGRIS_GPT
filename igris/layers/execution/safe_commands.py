"""
Definition of safe commands for the terminal MVP.

Each entry defines a human-friendly name mapped to a list representing the
command and its arguments.  Only commands listed here may be executed by the
safe runner.
"""

from __future__ import annotations

import sys
from typing import Dict, List

ALLOWED_COMMANDS: Dict[str, List[str]] = {
    "git_status": ["git", "status", "--short"],
    "git_log": ["git", "log", "--oneline", "-10"],
    "run_tests": [sys.executable, "-m", "pytest", "-q"],
    "list_files": [sys.executable, "-c", "import os; print('\\n'.join(sorted(os.listdir('.'))))"],
    "system_info": [sys.executable, "-c", "from igris.core.system_info import get_system_info; import json; print(json.dumps(get_system_info(), indent=2))"],
}
