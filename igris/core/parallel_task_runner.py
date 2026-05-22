from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from igris.core.agent_reasoning_loop import AgentReasoningLoop, LoopResult

logger = logging.getLogger(__name__)


@dataclass
class ParallelTask:
    task_id: str
    goal: str
    max_steps: int = 20
    task_type: str = "code_reasoning"
    preferred_profile: Optional[str] = None
    initial_context: dict = field(default_factory=dict)


@dataclass
class ParallelResult:
    task_id: str
    result: Optional[LoopResult]
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.result is not None and self.result.status == "finished"


class ParallelTaskRunner:
    """Runs multiple AgentReasoningLoop instances concurrently."""

    def __init__(self, project_root: str, max_concurrent: int = 3) -> None:
        self.project_root = project_root
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def _run_one(self, task: ParallelTask) -> ParallelResult:
        async with self._semaphore:
            try:
                loop = AgentReasoningLoop(
                    project_root=self.project_root,
                    max_steps=task.max_steps,
                    task_type=task.task_type,
                    preferred_profile=task.preferred_profile,
                )
                result = await asyncio.to_thread(
                    loop.run,
                    goal=task.goal,
                    initial_context=task.initial_context,
                )
                return ParallelResult(task_id=task.task_id, result=result)
            except Exception as exc:
                logger.error("parallel task %s failed: %s", task.task_id, exc)
                return ParallelResult(task_id=task.task_id, result=None, error=str(exc))

    async def run(self, tasks: List[ParallelTask]) -> List[ParallelResult]:
        if not tasks:
            return []
        coros = [self._run_one(t) for t in tasks]
        return list(await asyncio.gather(*coros))

    def run_sync(self, tasks: List[ParallelTask]) -> List[ParallelResult]:
        return asyncio.run(self.run(tasks))
