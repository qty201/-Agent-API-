"""Fixer for configuration file changes — env vars, config keys, file format migrations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fixers.base import BaseFixer, FixSuggestion

KNOWN_CONFIG_MIGRATIONS: dict[str, list[dict]] = {
    "webpack": [
        {
            "pattern": r"mode:\s*['\"]development['\"]",
            "replacement": 'mode: "development"',
            "files": ["webpack.config.js", "webpack.config.ts"],
        }
    ],
    "next": [
        {
            "pattern": r"next@12",
            "replacement": "next@13",
            "files": ["package.json"],
        }
    ],
}


class ConfigFixer(BaseFixer):
    """Fixes configuration files — package.json, .env, config.*, etc."""

    def suggest(self, issue: Any, project_path: str | Path) -> list[FixSuggestion]:
        suggestions: list[FixSuggestion] = []
        dep_name = issue.dependency if hasattr(issue, "dependency") else ""

        # Check known config migrations
        migrations = KNOWN_CONFIG_MIGRATIONS.get(dep_name, [])
        root = Path(project_path)

        for rule in migrations:
            for fname in rule.get("files", []):
                fpath = root / fname
                if not fpath.exists():
                    continue
                try:
                    text = fpath.read_text(encoding="utf-8")
                except Exception:
                    continue

                for m in re.finditer(rule["pattern"], text):
                    suggestions.append(
                        FixSuggestion(
                            file_path=str(fpath),
                            original=m.group(0),
                            replacement=rule["replacement"],
                            description=f"Config migration for {dep_name}",
                            confidence="high",
                        )
                    )

        return suggestions

    def update_package_json(
        self, project_path: str | Path, dep_name: str, new_version: str
    ) -> list[FixSuggestion]:
        """Update a dependency version in package.json."""
        pkg_path = Path(project_path) / "package.json"
        if not pkg_path.exists():
            return []

        try:
            data = json.loads(pkg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return []

        suggestions: list[FixSuggestion] = []
        for category in ("dependencies", "devDependencies", "peerDependencies"):
            if dep_name in data.get(category, {}):
                old_ver = data[category][dep_name]
                new_ver_str = f'"{new_version}"'
                suggestions.append(
                    FixSuggestion(
                        file_path=str(pkg_path),
                        original=f'"{dep_name}": "{old_ver}"',
                        replacement=f'"{dep_name}": "{new_version}"',
                        description=f"Bump {dep_name} from {old_ver} to {new_version}",
                        confidence="high",
                    )
                )
        return suggestions
