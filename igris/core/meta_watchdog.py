from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Dict

from igris.core.smw_actions import execute_action
from igris.core.smw_diagnosis import diagnose
from igris.core.smw_patterns import detect_patterns
from igris.core.smw_sensors import take_snapshot
from igris.core.smw_teach import Incident, record_incident, teach_back

_SMW_POLL_SECONDS = 120
_SMW_COOLDOWN_PATTERNS: Dict[str, float] = {}


async def _smw_loop(project_root: str) -> None:
    logger = logging.getLogger("igris.smw")
    while True:
        try:
            snapshot = await take_snapshot(project_root)
            patterns = detect_patterns(snapshot)
            for detected in patterns:
                name = detected.pattern.name
                last = _SMW_COOLDOWN_PATTERNS.get(name, 0)
                if (detected.detected_at - last) < detected.pattern.cooldown_seconds:
                    continue
                _SMW_COOLDOWN_PATTERNS[name] = detected.detected_at
                d = diagnose(detected, project_root)
                actions_applied = []
                for action_name in d.recommended_actions:
                    result = await execute_action(action_name, tier=d.recommended_tier, dry_run=(d.confidence < 0.6), project_root=project_root, pattern_name=name, evidence=detected.evidence, actions_tried=actions_applied)
                    actions_applied.append(action_name)
                    logger.info("SMW: action %s => %s", action_name, result.success)
                await asyncio.sleep(1)
                still_active = any(p.pattern.name == name for p in detect_patterns(await take_snapshot(project_root)))
                outcome = "failed" if still_active else "resolved"
                incident = Incident(uuid.uuid4().hex, name, detected.detected_at, None if still_active else asyncio.get_running_loop().time(), d.root_cause, actions_applied, outcome, detected.evidence)
                record_incident(incident, project_root)
                if outcome == "resolved":
                    await teach_back(incident, project_root)
                else:
                    await execute_action("open_diagnostic_issue", tier=2, dry_run=False, project_root=project_root, pattern_name=name, evidence=detected.evidence, actions_tried=actions_applied)
        except Exception as exc:
            logger.warning("SMW error: %s", exc)
        await asyncio.sleep(_SMW_POLL_SECONDS)


def start_smw(project_root: str) -> asyncio.Task:
    return asyncio.create_task(_smw_loop(project_root))
