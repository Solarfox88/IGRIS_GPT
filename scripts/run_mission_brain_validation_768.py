from __future__ import annotations

from igris.agent.mission.validation_runner import run_validation_suite


def main() -> int:
    json_path, md_path = run_validation_suite(project_root=".")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

