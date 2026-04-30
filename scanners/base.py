"""Abstract scanner interface and shared data types."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class Dependency:
    """A single dependency discovered in a project."""

    name: str
    current_version: str
    target_version: str | None = None
    is_dev: bool = False
    is_direct: bool = True
    source_file: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Dependency:
        return cls(**d)


@dataclass
class DependencyFile:
    """A manifest file that declares dependencies (package.json, etc.)."""

    path: str
    format: str  # "package_json" | "requirements_txt" | "pyproject_toml" | etc.
    raw_content: str = ""
    dependencies: list[Dependency] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "format": self.format,
            "dependencies": [d.to_dict() for d in self.dependencies],
        }


@dataclass
class ScanResult:
    """Aggregated output of a scanner pass."""

    project_path: str
    dependency_files: list[DependencyFile] = field(default_factory=list)
    all_dependencies: dict[str, Dependency] = field(default_factory=dict)
    file_usage_map: dict[str, list[dict]] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "project_path": self.project_path,
            "dependency_files": [f.to_dict() for f in self.dependency_files],
            "all_dependencies": {
                k: v.to_dict() for k, v in self.all_dependencies.items()
            },
            "file_usage_count": len(self.file_usage_map),
        }


class BaseScanner(ABC):
    """Abstract scanner — each ecosystem implements ``discover`` + ``parse``."""

    @abstractmethod
    def discover(self, project_path: str | Path) -> list[DependencyFile]:
        """Find dependency manifest files under *project_path*."""
        ...

    @abstractmethod
    def parse(self, dep_file: DependencyFile) -> list[Dependency]:
        """Parse a manifest file into ``Dependency`` objects (populates in-place)."""
        ...

    def scan(self, project_path: str | Path) -> ScanResult:
        """Convenience: discover + parse all files."""
        result = ScanResult(project_path=str(project_path))
        for dep_file in self.discover(project_path):
            self.parse(dep_file)
            result.dependency_files.append(dep_file)
            for dep in dep_file.dependencies:
                result.all_dependencies[dep.name] = dep
        return result
