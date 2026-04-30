"""Global configuration — loaded from env / config file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class Settings:
    # ── LLM ────────────────────────────────────────────────────
    anthropic_api_key: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )
    llm_model: str = "claude-sonnet-4-20250514"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.3

    # ── agent behaviour ────────────────────────────────────────
    agent_request_timeout: float = 300.0  # seconds
    max_repair_iterations: int = 3
    retry_delay: float = 2.0

    # ── paths ──────────────────────────────────────────────────
    project_root: str = ""
    session_dir: str = str(Path.home() / ".claude" / "upgrade_sessions")

    # ── logging ────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ── feature toggles ────────────────────────────────────────
    use_llm_fallback: bool = True
    dry_run: bool = False
    auto_apply: bool = False

    def is_llm_available(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def resolved_project_root(self) -> Path:
        return Path(self.project_root).resolve() if self.project_root else Path.cwd()


settings = Settings()
