"""Orchestrator agent — workflow coordinator & state machine."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.agent import BaseAgent
from core.message_bus import Message
from core.workflow import (
    StepName,
    StepStatus,
    WorkflowState,
)

logger = logging.getLogger(__name__)

AGENT_SCANNER = "scanner_agent"
AGENT_ANALYZER = "analyzer_agent"
AGENT_REPAIRER = "repairer_agent"
AGENT_VALIDATOR = "validator_agent"
AGENT_REPORTER = "reporter_agent"


class OrchestratorAgent(BaseAgent):
    """Central coordinator — delegates to specialist agents, tracks state.

    Orchestrator handles the ``*`` (catch-all) message pattern and routes
    based on ``message.type``.  Specialist agents send their results back
    here so the orchestrator can advance the workflow.
    """

    def __init__(self, message_bus, session_id: str):
        super().__init__("orchestrator", message_bus)
        self._state: WorkflowState | None = None
        self._session_id = session_id
        self._pending_requests: dict[str, asyncio.Future] = {}

        # Register internal handlers
        self.subscribe("step.completed", self._on_step_completed)
        self.subscribe("step.failed", self._on_step_failed)
        self.subscribe("log", self._on_log)

    # ── public API ─────────────────────────────────────────────

    async def run_upgrade(
        self, project_path: str, target_deps: dict[str, str]
    ) -> WorkflowState:
        """Execute the full upgrade workflow, returning the final state."""
        self._state = WorkflowState(
            session_id=self._session_id,
            project_path=project_path,
            target_deps=target_deps,
        )
        self._state.save()

        logger.info(
            "Starting upgrade session %s for %s",
            self._session_id,
            project_path,
        )

        while True:
            step = self._state.next_step()
            if step is None:
                break
            await self._execute_step(step)

            if step.status == StepStatus.FAILED and not step.can_retry():
                logger.error("Step %s failed, aborting workflow", step.name)
                break

        self._state.save()
        return self._state

    async def resume(self, session_id: str) -> WorkflowState | None:
        """Resume a previously-saved session."""
        state = WorkflowState.load(session_id)
        if state is None:
            return None
        self._state = state
        logger.info("Resumed session %s at step %s", session_id, state.next_step())
        return state

    # ── step execution ─────────────────────────────────────────

    async def _execute_step(self, step) -> None:
        step.start()

        mapping = {
            StepName.SCAN: (AGENT_SCANNER, "scan"),
            StepName.ANALYZE: (AGENT_ANALYZER, "analyze"),
            StepName.REPAIR: (AGENT_REPAIRER, "repair"),
            StepName.VALIDATE: (AGENT_VALIDATOR, "validate"),
            StepName.REPORT: (AGENT_REPORTER, "report"),
        }

        target_agent, msg_type = mapping[step.name]

        logger.info("Executing step %s → %s", step.name, target_agent)

        try:
            reply = await self.request(
                target=target_agent,
                msg_type=msg_type,
                payload={
                    "session_id": self._session_id,
                    "project_path": self._state.project_path,
                    "target_deps": self._state.target_deps,
                    "step_results": {
                        name: s.result
                        for name, s in self._state.steps.items()
                        if s.status == StepStatus.SUCCEEDED
                    },
                },
                timeout=300.0,
            )
            step.succeed(reply.payload)
        except TimeoutError:
            step.fail("Timeout waiting for agent response")
        except Exception as exc:
            step.fail(str(exc))

        if step.status == StepStatus.FAILED and step.can_retry():
            step.retry_count += 1
            logger.warning("Retrying step %s (attempt %d)", step.name, step.retry_count)
            step.status = StepStatus.PENDING

    # ── message handlers ───────────────────────────────────────

    async def _on_step_completed(self, message: Message) -> None:
        agent = message.source
        logger.info("Agent %s completed: %s", agent, message.payload)

    async def _on_step_failed(self, message: Message) -> None:
        logger.error("Agent %s failed: %s", message.source, message.payload)

    async def _on_log(self, message: Message) -> None:
        level = message.payload.get("level", "info").upper()
        text = message.payload.get("text", "")
        getattr(logger, level.lower(), logger.info)("[%s] %s", message.source, text)
