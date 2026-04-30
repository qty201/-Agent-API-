"""Repairer Agent — generates and applies migration patches for compatibility issues."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.agent import BaseAgent
from core.message_bus import Message
from config.settings import settings
from fixers import ImportFixer, ApiSignatureFixer, ConfigFixer
from fixers.base import FixResult, FixSuggestion
from llm.claude_client import ClaudeClient
from llm.prompts import get_prompt
from agents.analyzer_agent import CompatibilityIssue

logger = logging.getLogger(__name__)


class RepairerAgent(BaseAgent):
    """Generates migration patches by combining rule-based fixers with LLM analysis."""

    def __init__(self, message_bus):
        super().__init__("repairer_agent", message_bus)
        self._fixers = {
            "import": ImportFixer(),
            "api_sig": ApiSignatureFixer(),
            "config": ConfigFixer(),
        }
        self._llm = ClaudeClient() if settings.is_llm_available() else None
        self.subscribe("repair", self._handle_repair)

    async def _handle_repair(self, message: Message) -> None:
        payload = message.payload
        project_path = payload.get("project_path", "")
        analysis_results = payload.get("step_results", {}).get("analyze", {})
        scan_results = payload.get("step_results", {}).get("scan", {})

        issues_data = analysis_results.get("issues", [])
        issues = [CompatibilityIssue(**i) if isinstance(i, dict) else i for i in issues_data]

        logger.info("Repairing %d issues for %s", len(issues), project_path)

        result = FixResult()

        # Phase 1: Rule-based fixes
        self._apply_rule_based_fixes(issues, project_path, result)

        # Phase 2: LLM-generated patches
        if self._llm:
            await self._apply_llm_fixes(result, issues, project_path, scan_results)

        # Phase 3: Apply all suggestions
        dry_run = settings.dry_run
        for suggestion in result.suggestions:
            if not suggestion.file_path:
                continue
            success = self._apply_fixer(suggestion, dry_run)
            if success:
                result.applied_count += 1
            else:
                result.failed_count += 1

        logger.info(
            "Repair complete: %d applied, %d failed",
            result.applied_count,
            result.failed_count,
        )

        await self.reply(message, result.to_dict())

    def _apply_rule_based_fixes(
        self, issues: list[CompatibilityIssue], project_path: str, result: FixResult
    ) -> None:
        """Run known-issue patterns through the appropriate fixers."""
        for issue in issues:
            for fixer_name, fixer in self._fixers.items():
                try:
                    suggestions = fixer.suggest(issue, project_path)
                    result.suggestions.extend(suggestions)
                except Exception as e:
                    logger.warning("Fixer %s failed for %s: %s", fixer_name, issue.dependency, e)

    async def _apply_llm_fixes(
        self,
        result: FixResult,
        issues: list[CompatibilityIssue],
        project_path: str,
        scan_results: dict,
    ) -> None:
        """Use LLM to generate fixes for issues without rule-based matches."""
        try:
            # Filter issues needing LLM help
            llm_issues = [
                i for i in issues
                if not any(
                    s.description == i.description
                    for s in result.suggestions
                )
            ]
            if not llm_issues:
                return

            system, user_msg = get_prompt(
                "repair",
                {
                    "issues": str([i.to_dict() for i in llm_issues]),
                    "context": str(scan_results.get("file_usage_map", {})),
                },
            )
            llm_output = await self._llm.chat(
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )

            # Parse patches from LLM output
            self._parse_llm_patches(llm_output, result, project_path)

        except Exception as e:
            logger.warning("LLM repair failed: %s", e)
            result.errors.append(f"LLM repair error: {e}")

    def _parse_llm_patches(
        self, llm_output: str, result: FixResult, project_path: str
    ) -> None:
        """Parse unified-diff patches from LLM output into FixSuggestions."""
        import re

        # Match unified diff hunks: --- a/file +++ b/file @@ ... @@
        diff_pattern = re.compile(
            r"--- a/(.+?)\n\+\+\+ b/(.+?)\n@@[^@]*@@\n(.*?)(?=---|\Z)",
            re.DOTALL,
        )

        for m in diff_pattern.finditer(llm_output):
            file_path = m.group(2)
            full_path = str(Path(project_path) / file_path)

            # Parse the hunk body for actual changes
            hunk = m.group(3)
            for line in hunk.splitlines():
                if line.startswith("+"):
                    result.suggestions.append(
                        FixSuggestion(
                            file_path=full_path,
                            original="",  # Will need context matching
                            replacement=line[1:],
                            description="LLM-generated patch",
                            confidence="medium",
                        )
                    )

    def _apply_fixer(self, suggestion: FixSuggestion, dry_run: bool) -> bool:
        """Apply a single suggestion using the appropriate fixer."""
        for fixer in self._fixers.values():
            try:
                if fixer.apply(suggestion, dry_run=dry_run):
                    return True
            except Exception:
                continue
        return False
