"""Reporter Agent — generates comprehensive upgrade reports."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.agent import BaseAgent
from core.message_bus import Message
from config.settings import settings
from llm.claude_client import ClaudeClient
from llm.prompts import get_prompt

logger = logging.getLogger(__name__)


class ReporterAgent(BaseAgent):
    """Generates final upgrade reports consolidating all agents' outputs."""

    def __init__(self, message_bus):
        super().__init__("reporter_agent", message_bus)
        self._llm = ClaudeClient() if settings.is_llm_available() else None
        self.subscribe("report", self._handle_report)

    async def _handle_report(self, message: Message) -> None:
        payload = message.payload
        session_id = payload.get("session_id", "unknown")
        project_path = payload.get("project_path", "")
        target_deps = payload.get("target_deps", {})
        step_results = payload.get("step_results", {})

        logger.info("Generating report for session %s", session_id)

        report = self._build_report(session_id, project_path, target_deps, step_results)

        # Save report to disk
        report_path = self._save_report(session_id, report)

        # LLM-enhanced narrative
        if self._llm:
            await self._enrich_report(report, step_results)

        report["saved_to"] = str(report_path)
        logger.info("Report saved to %s", report_path)

        await self.reply(message, report)

    def _build_report(
        self,
        session_id: str,
        project_path: str,
        target_deps: dict[str, str],
        step_results: dict[str, Any],
    ) -> dict:
        """Assemble the structured report from all step results."""

        scan_result = step_results.get("scan", {})
        analysis_result = step_results.get("analyze", {})
        repair_result = step_results.get("repair", {})
        validation_result = step_results.get("validate", {})

        # Determine overall status
        status = "success"
        if validation_result.get("failed_tests", 0) > 0 or validation_result.get("errors"):
            status = "partial"
        if repair_result.get("failed_count", 0) == repair_result.get("applied_count", 0) and repair_result.get("applied_count", 0) == 0:
            if analysis_result.get("issues"):
                status = "failed"

        issues = analysis_result.get("issues", [])
        break_count = sum(1 for i in issues if i.get("severity") == "break")
        deprecation_count = sum(1 for i in issues if i.get("severity") == "deprecate")
        migration_count = sum(1 for i in issues if i.get("severity") == "migration")

        report = {
            "session_id": session_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "project_path": project_path,
            "status": status,
            "summary": {
                "dependencies_upgraded": len(target_deps),
                "target_versions": target_deps,
                "total_issues_found": len(issues),
                "breaking_changes": break_count,
                "deprecations": deprecation_count,
                "migration_items": migration_count,
                "patches_applied": repair_result.get("applied_count", 0),
                "patches_failed": repair_result.get("failed_count", 0),
                "tests_passed": validation_result.get("passed_tests", 0),
                "tests_failed": validation_result.get("failed_tests", 0),
                "overall_status": status,
            },
            "details": {
                "scan": {
                    "dependencies_found": len(scan_result.get("all_dependencies", {})),
                    "files_scanned": len(scan_result.get("file_usage_map", {})),
                },
                "analysis": {
                    "issues": issues,
                },
                "repair": {
                    "patches": repair_result.get("suggestions", []),
                    "applied": repair_result.get("applied_count", 0),
                    "failed": repair_result.get("failed_count", 0),
                    "errors": repair_result.get("errors", []),
                },
                "validation": {
                    "total_tests": validation_result.get("total_tests", 0),
                    "passed": validation_result.get("passed_tests", 0),
                    "failed": validation_result.get("failed_tests", 0),
                    "errors": validation_result.get("errors", []),
                    "failures": validation_result.get("failures", []),
                },
            },
            "manual_steps_required": self._extract_manual_steps(issues, repair_result),
            "risk_assessment": self._assess_risk(break_count, validation_result, repair_result),
        }

        return report

    async def _enrich_report(self, report: dict, step_results: dict) -> None:
        """Add LLM-generated narrative sections to the report."""
        try:
            system, user_msg = get_prompt(
                "report",
                {
                    "scan_results": json.dumps(step_results.get("scan", {}), indent=2, default=str)[:2000],
                    "analysis_results": json.dumps(step_results.get("analyze", {}), indent=2, default=str)[:2000],
                    "patches": json.dumps(step_results.get("repair", {}), indent=2, default=str)[:2000],
                    "validation_results": json.dumps(step_results.get("validate", {}), indent=2, default=str)[:2000],
                },
            )
            narrative = await self._llm.chat(
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            report["narrative"] = narrative
        except Exception as e:
            logger.warning("LLM report enrichment failed: %s", e)

    @staticmethod
    def _extract_manual_steps(
        issues: list[dict], repair_result: dict[str, Any]
    ) -> list[dict]:
        """Identify issues that require manual intervention."""
        manual_steps = []
        for issue in issues:
            if issue.get("confidence") == "low" and issue.get("severity") == "break":
                manual_steps.append({
                    "dependency": issue.get("dependency"),
                    "description": issue.get("description"),
                    "affected_file": issue.get("affected_file"),
                    "reason": "Low-confidence automated fix — requires human review",
                })
        # Failed patches
        for err in repair_result.get("errors", []):
            manual_steps.append({
                "description": f"Patch application error: {err}",
                "reason": "Automated fix failed — manual resolution needed",
            })
        return manual_steps

    @staticmethod
    def _assess_risk(
        break_count: int, validation_result: dict, repair_result: dict
    ) -> dict:
        """Assess overall risk of the upgrade."""
        risk_level = "low"
        reasons: list[str] = []

        if break_count > 5:
            risk_level = "high"
            reasons.append(f"{break_count} breaking changes detected")
        elif break_count > 2:
            risk_level = "medium"
            reasons.append(f"{break_count} breaking changes detected")

        failed_tests = validation_result.get("failed_tests", 0)
        if failed_tests > 0:
            risk_level = "high" if risk_level != "high" else risk_level
            reasons.append(f"{failed_tests} test(s) failing after migration")

        if repair_result.get("failed_count", 0) > 0:
            if risk_level != "high":
                risk_level = "medium"
            reasons.append(f"{repair_result['failed_count']} patch(es) failed to apply")

        return {
            "level": risk_level,
            "reasons": reasons,
        }

    @staticmethod
    def _save_report(session_id: str, report: dict) -> Path:
        """Write the report to disk."""
        report_dir = Path(settings.session_dir) / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / f"{session_id}.json"
        path.write_text(
            json.dumps(report, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        return path
