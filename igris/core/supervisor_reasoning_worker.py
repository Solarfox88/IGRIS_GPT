"""Subprocess entrypoint for bounded supervisor reasoning runs."""

from __future__ import annotations

import json
import sys

from igris.core.agent_reasoning_loop import AgentReasoningLoop


def main() -> int:
    payload = json.load(sys.stdin)
    loop = AgentReasoningLoop(
        project_root=str(payload["project_root"]),
        max_steps=int(payload["max_steps"]),
    )
    result = loop.run(
        goal=str(payload["goal"]),
        initial_context=dict(payload.get("initial_context") or {}),
    )
    print(json.dumps(result.to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
