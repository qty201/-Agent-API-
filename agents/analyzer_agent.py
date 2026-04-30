"""Analyzer Agent — detects breaking changes and compatibility issues."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any

from core.agent import BaseAgent
from core.message_bus import Message
from config.settings import settings
from llm.claude_client import ClaudeClient
from llm.prompts import get_prompt
from parsers import JsTsParser, PythonParser

logger = logging.getLogger(__name__)


@dataclass
class CompatibilityIssue:
    """A single compatibility issue found during analysis."""

    dependency: str
    current_version: str
    target_version: str
    severity: str  # "break" | "deprecate" | "migration"
    description: str
    affected_file: str = ""
    line: int = 0
    current_code: str = ""
    suggested_fix: str = ""
    confidence: str = "medium"  # "high" | "medium" | "low"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> CompatibilityIssue:
        return cls(**d)


@dataclass
class AnalysisResult:
    """Output of the analyzer agent pass."""

    issues: list[CompatibilityIssue] = field(default_factory=list)
    summary: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "issues": [i.to_dict() for i in self.issues],
            "summary": self.summary,
            "issue_count": len(self.issues),
            "break_count": sum(1 for i in self.issues if i.severity == "break"),
        }


# ── Known breaking-change patterns (rule-based, no LLM needed) ──

KNOWN_BREAKING_CHANGES: dict[str, dict[str, list[dict]]] = {
    "react": {
        "18": [
            {
                "severity": "migration",
                "match": "ReactDOM.render",
                "description": "ReactDOM.render is deprecated in React 18, use createRoot instead",
                "suggested_fix": "Use createRoot from react-dom/client",
            }
        ],
    },
    "express": {
        "4": [
            {
                "severity": "break",
                "match": "res.send",
                "description": "Express 4 removes some app.configure() and res.send(body) overloads",
                "suggested_fix": "Use explicit middleware setup instead of app.configure()",
            }
        ],
    },
    "chalk": {
        "5": [
            {
                "severity": "break",
                "match": "import chalk from",
                "description": "Chalk 5 is ESM-only, no CommonJS require support",
                "suggested_fix": "Convert to ESM import or use chalk@4 for CJS",
            }
        ],
    },
}


class AnalyzerAgent(BaseAgent):
    """Analyses dependencies for breaking changes between versions."""

    def __init__(self, message_bus):
        super().__init__("analyzer_agent", message_bus)
        self._llm = ClaudeClient() if settings.is_llm_available() else None
        self._js_parser = JsTsParser()
        self._py_parser = PythonParser()
        self.subscribe("analyze", self._handle_analyze)

    async def _handle_analyze(self, message: Message) -> None:
        payload = message.payload
        project_path = payload.get("project_path", "")
        target_deps = payload.get("target_deps", {})
        scan_results = payload.get("step_results", {}).get("scan", {})

        logger.info("Analysing %d dependency upgrades", len(target_deps))

        result = AnalysisResult()

        # Phase 1: Rule-based checks (fast path)
        self._rule_based_analysis(result, scan_results, target_deps)

        # Phase 2: LLM-enhanced analysis (deep path)
        if self._llm:
            await self._llm_analysis(result, scan_results, target_deps)

        # Phase 3: Source-code cross-reference
        self._cross_reference_source(result, scan_results, project_path)

        result.summary = (
            f"Found {len(result.issues)} issues "
            f"({result.to_dict()['break_count']} breaking)"
        )
        logger.info(result.summary)

        await self.reply(message, result.to_dict())

    def _rule_based_analysis(
        self, result: AnalysisResult, scan_data: dict, targets: dict[str, str]
    ) -> None:
        """Apply known breaking-change patterns."""
        all_deps = scan_data.get("all_dependencies", {})

        for dep_name, target_ver in targets.items():
            dep_info = all_deps.get(dep_name, {})
            current_ver = dep_info.get("current_version", "")

            # Check known rules for this dependency
            dep_rules = KNOWN_BREAKING_CHANGES.get(dep_name, {})
            if not dep_rules:
                continue

            # Find matching version transition rules
            for ver_key, rules in dep_rules.items():
                if self._version_gte(target_ver, ver_key) and not self._version_gte(current_ver, ver_key):
                    for rule in rules:
                        result.issues.append(
                            CompatibilityIssue(
                                dependency=dep_name,
                                current_version=current_ver,
                                target_version=target_ver,
                                severity=rule["severity"],
                                description=rule["description"],
                                suggested_fix=rule["suggested_fix"],
                                confidence="high",
                            )
                        )

    async def _llm_analysis(
        self, result: AnalysisResult, scan_data: dict, targets: dict[str, str]
    ) -> None:
        """Use Claude to identify breaking changes from changelogs / release data."""
        try:
            system, user_msg = get_prompt(
                "analyze",
                {
                    "project_path": scan_data.get("project_path", ""),
                    "target_deps": str(targets),
                    "deps_summary": str(scan_data.get("all_dependencies", {})),
                    "usages": str(scan_data.get("file_usage_map", {})),
                },
            )
            llm_response = await self._llm.chat_structured(
                system=system,
                messages=[{"role": "user", "content": user_msg}],
                response_model=None,
            )

            # Parse LLM output — expect JSON array of issue objects
            if isinstance(llm_response, str):
                try:
                    issues_data = json.loads(llm_response)
                except json.JSONDecodeError:
                    logger.warning("LLM response not JSON, storing raw")
                    result.metadata["llm_raw"] = llm_response
                    return
            elif isinstance(llm_response, list):
                issues_data = llm_response
            else:
                issues_data = []

            for item in issues_data:
                if isinstance(item, dict):
                    result.issues.append(
                        CompatibilityIssue(
                            dependency=item.get("dependency", "unknown"),
                            current_version=item.get("current_version", ""),
                            target_version=item.get("target_version", ""),
                            severity=item.get("severity", "migration"),
                            description=item.get("description", ""),
                            affected_file=item.get("affected_file", ""),
                            line=item.get("line", 0),
                            current_code=item.get("current_code", ""),
                            suggested_fix=item.get("suggested_fix", ""),
                            confidence=item.get("confidence", "medium"),
                        )
                    )

        except Exception as e:
            logger.warning("LLM analysis failed: %s", e)
            result.metadata["llm_error"] = str(e)

    def _cross_reference_source(
        self, result: AnalysisResult, scan_data: dict, project_path: str
    ) -> None:
        """Cross-reference issues with actual source code using parsers."""
        file_usage = scan_data.get("file_usage_map", {})
        if not file_usage:
            return

        for issue in result.issues:
            for file_path, usages in file_usage.items():
                for usage in usages:
                    dep_name = usage.get("dependency", "")
                    if dep_name == issue.dependency:
                        issue.affected_file = usage.get("file", file_path)
                        issue.line = usage.get("line", 0)
                        issue.current_code = usage.get("code", "")

    @staticmethod
    def _version_gte(version: str, target: str) -> bool:
        """Rough version comparison — handles semver-ish strings."""
        try:
            v_parts = [int(p) for p in str(version).split(".")[:3]]
            t_parts = [int(p) for p in target.split(".")[:3]]
            # Pad with zeros
            while len(v_parts) < 3:
                v_parts.append(0)
            while len(t_parts) < 3:
                t_parts.append(0)
            return tuple(v_parts) >= tuple(t_parts)
        except (ValueError, TypeError):
            return version.lower() >= target.lower()
