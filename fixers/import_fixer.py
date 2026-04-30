"""Fixer for import/module path changes caused by dependency upgrades."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fixers.base import BaseFixer, FixSuggestion

# Known import path migrations
IMPORT_MIGRATIONS: dict[str, dict[str, str]] = {
    "react-dom": {
        "import ReactDOM from 'react-dom'": "import { createRoot } from 'react-dom/client'",
        "import * as ReactDOM from 'react-dom'": "import { createRoot } from 'react-dom/client'",
        "const ReactDOM = require('react-dom')": "const { createRoot } = require('react-dom/client')",
    },
}


class ImportFixer(BaseFixer):
    """Fixes import/require statements that changed between dependency versions."""

    def suggest(self, issue: Any, project_path: str | Path) -> list[FixSuggestion]:
        suggestions: list[FixSuggestion] = []
        dep_name = issue.dependency if hasattr(issue, "dependency") else ""

        # Check known migrations
        migrations = IMPORT_MIGRATIONS.get(dep_name, {})
        if migrations and issue.affected_file:
            full_path = str(Path(project_path) / issue.affected_file)
            for original, replacement in migrations.items():
                if original in issue.current_code:
                    suggestions.append(
                        FixSuggestion(
                            file_path=full_path,
                            original=original,
                            replacement=replacement,
                            description=f"Update import for {dep_name}",
                            confidence="high",
                            language="javascript",
                        )
                    )

        # Generic import path updates
        if issue.suggested_fix and issue.affected_file:
            suggestions.append(
                FixSuggestion(
                    file_path=str(Path(project_path) / issue.affected_file),
                    original=issue.current_code,
                    replacement=issue.suggested_fix,
                    description=issue.description,
                    confidence="medium",
                )
            )

        return suggestions

    def suggest_from_pattern(
        self,
        file_path: str,
        old_import_pattern: str,
        new_import: str,
    ) -> list[FixSuggestion]:
        """Find and suggest fixes for imports matching a regex pattern."""
        suggestions: list[FixSuggestion] = []
        try:
            path = Path(file_path)
            if not path.exists():
                return suggestions
            text = path.read_text(encoding="utf-8", errors="ignore")

            for line in text.splitlines():
                stripped = line.strip()
                if re.search(old_import_pattern, stripped):
                    suggestions.append(
                        FixSuggestion(
                            file_path=file_path,
                            original=stripped,
                            replacement=new_import,
                            description=f"Migrate import matching '{old_import_pattern}'",
                            confidence="medium",
                        )
                    )
        except Exception:
            pass
        return suggestions
