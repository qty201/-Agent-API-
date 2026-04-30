"""Workflow state machine — defines upgrade pipeline steps."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StepName(str, Enum):
    SCAN = "scan"
    ANALYZE = "analyze"
    REPAIR = "repair"
    VALIDATE = "validate"
    REPORT = "report"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowStep:
    """A single step in the upgrade workflow."""

    name: StepName
    status: StepStatus = StepStatus.PENDING
    started_at: str | None = None
    ended_at: str | None = None
    result: Any = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 2

    def start(self) -> None:
        self.status = StepStatus.RUNNING
        self.started_at = datetime.now(timezone.utc).isoformat()

    def succeed(self, result: Any = None) -> None:
        self.status = StepStatus.SUCCEEDED
        self.ended_at = datetime.now(timezone.utc).isoformat()
        self.result = result

    def fail(self, error: str) -> None:
        self.status = StepStatus.FAILED
        self.ended_at = datetime.now(timezone.utc).isoformat()
        self.error = error

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> WorkflowStep:
        d["name"] = StepName(d["name"])
        d["status"] = StepStatus(d["status"])
        return cls(**d)


@dataclass
class WorkflowState:
    """Serialisable state of an entire upgrade run."""

    session_id: str
    project_path: str
    target_deps: dict[str, str]  # dep_name -> target_version
    steps: dict[str, WorkflowStep] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.steps:
            self.steps = {
                s.value: WorkflowStep(name=s) for s in StepName
            }

    def step(self, name: StepName | str) -> WorkflowStep:
        if isinstance(name, StepName):
            name = name.value
        return self.steps[name]

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def is_complete(self) -> bool:
        return all(
            s.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED)
            for s in self.steps.values()
        )

    def is_failed(self) -> bool:
        return any(s.status == StepStatus.FAILED for s in self.steps.values())

    def next_step(self) -> WorkflowStep | None:
        """Return the first pending step, or ``None``."""
        for s in self.steps.values():
            if s.status == StepStatus.PENDING:
                return s
        return None

    # ── persistence ────────────────────────────────────────────

    SAVE_DIR = Path.home() / ".claude" / "upgrade_sessions"

    def save(self) -> Path:
        self.SAVE_DIR.mkdir(parents=True, exist_ok=True)
        path = self.SAVE_DIR / f"{self.session_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        logger.info("Session %s saved to %s", self.session_id, path)
        return path

    @classmethod
    def load(cls, session_id: str) -> WorkflowState | None:
        path = cls.SAVE_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return cls.from_dict(data)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "project_path": self.project_path,
            "target_deps": self.target_deps,
            "steps": {k: v.to_dict() for k, v in self.steps.items()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WorkflowState:
        d["steps"] = {
            k: WorkflowStep.from_dict(v) for k, v in d["steps"].items()
        }
        return cls(**d)
