"""Fixer for API signature changes — parameters, return types, method renames."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fixers.base import BaseFixer, FixSuggestion

# Known API signature migrations
API_MIGRATIONS: dict[str, list[dict]] = {
    "ReactDOM.render": [
        {
            "pattern": r"ReactDOM\.render\(<([^>]+)>,\s*document\.getElementById\(['\"]([^'\"]+)['\"]\)\)",
            "description": "ReactDOM.render -> createRoot API migration",
        }
    ],
}


class ApiSignatureFixer(BaseFixer):
    """Fixes API call-site changes — renamed methods, new signatures, etc."""

    def suggest(self, issue: Any, project_path: str | Path) -> list[FixSuggestion]:
        suggestions: list[FixSuggestion] = []
        if not hasattr(issue, "current_code") or not issue.current_code:
            return suggestions

        # Try known migrations
        for api_name, rules in API_MIGRATIONS.items():
            for rule in rules:
                pattern = rule["pattern"]
                m = re.search(pattern, issue.current_code)
                if m:
                    full_path = str(Path(project_path) / issue.affected_file) if issue.affected_file else ""
                    if full_path:
                        suggestions.append(
                            FixSuggestion(
                                file_path=full_path,
                                original=m.group(0),
                                replacement=self._build_replacement(rule["replacement"], m),
                                description=rule["description"],
                                confidence="high",
                            )
                        )

        # LLM-suggested fix
        if issue.suggested_fix and issue.current_code != issue.suggested_fix:
            suggestions.append(
                FixSuggestion(
                    file_path=str(Path(project_path) / issue.affected_file) if issue.affected_file else "",
                    original=issue.current_code,
                    replacement=issue.suggested_fix,
                    description=issue.description,
                    confidence=issue.confidence if hasattr(issue, "confidence") else "medium",
                )
            )

        return suggestions

    @staticmethod
    def _build_replacement(template: str, match: re.Match) -> str:
        """Replace ``{N}`` placeholders with captured groups."""
        result = template
        for i in range(1, len(match.groups()) + 1):
            result = result.replace(f"{{{i}}}", match.group(i))
        return result
