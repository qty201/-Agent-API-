"""Scanner for Node.js / npm / yarn projects — reads ``package.json`` files."""

from __future__ import annotations

import json
import re
from pathlib import Path

from scanners.base import BaseScanner, Dependency, DependencyFile


class NodeScanner(BaseScanner):
    """Discover and parse ``package.json`` files in a project tree."""

    MANIFEST = "package.json"

    def discover(self, project_path: str | Path) -> list[DependencyFile]:
        root = Path(project_path).resolve()
        dep_files: list[DependencyFile] = []

        # Root-level manifest
        pkg = root / self.MANIFEST
        if pkg.exists():
            dep_files.append(
                DependencyFile(path=str(pkg), format="package_json")
            )

        # Monorepo workspaces
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
                workspaces = data.get("workspaces", [])
                if isinstance(workspaces, list):
                    for pattern in workspaces:
                        for wksp_path in sorted(root.glob(pattern)):
                            wksp_pkg = wksp_path / self.MANIFEST
                            if wksp_pkg.exists() and wksp_pkg not in dep_files:
                                dep_files.append(
                                    DependencyFile(
                                        path=str(wksp_pkg), format="package_json"
                                    )
                                )
            except (json.JSONDecodeError, KeyError):
                pass

        return dep_files

    def parse(self, dep_file: DependencyFile) -> list[Dependency]:
        try:
            data = json.loads(Path(dep_file.path).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

        deps: list[Dependency] = []

        for category, is_dev in [("dependencies", False), ("devDependencies", True)]:
            for name, version in data.get(category, {}).items():
                deps.append(
                    Dependency(
                        name=name,
                        current_version=self._clean_version(version),
                        is_dev=is_dev,
                        is_direct=True,
                        source_file=dep_file.path,
                    )
                )

        dep_file.dependencies = deps
        return deps

    @staticmethod
    def _clean_version(version: str) -> str:
        """Strip semver range prefixes like ``^``, ``~``, ``>=``."""
        return re.sub(r"^[\^~>=<]+", "", version).strip()
