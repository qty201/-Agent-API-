"""Abstract fixer interface and shared result types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FixSuggestion:
    """A single atomic code change suggestion."""

    file_path: str
    original: str
    replacement: str
    description: str = ""
    confidence: str = "medium"  # "high" | "medium" | "low"
    language: str = ""
    start_line: int = 0
    end_line: int = 0


@dataclass
class FixResult:
    """Aggregated result of applying fixes to a project."""

    suggestions: list[FixSuggestion] = field(default_factory=list)
    applied_count: int = 0
    failed_count: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "applied_count": self.applied_count,
            "failed_count": self.failed_count,
            "suggestion_count": len(self.suggestions),
            "errors": self.errors,
        }


class BaseFixer(ABC):
    """Abstract fixer — each type of fix implements ``suggest`` + ``apply``."""

    @abstractmethod
    def suggest(self, issue: Any, project_path: str | Path) -> list[FixSuggestion]:
        """Generate fix suggestions for a given compatibility issue."""
        ...

    def apply(self, suggestion: FixSuggestion, dry_run: bool = False) -> bool:
        """Apply a single fix suggestion to the file system.

        Returns ``True`` if applied, ``False`` if the original text was not found.
        """
        if dry_run:
            return True

        path = Path(suggestion.file_path)
        if not path.exists():
            return False

        try:
            text = path.read_text(encoding="utf-8")
            if suggestion.original not in text:
                return False
            new_text = text.replace(suggestion.original, suggestion.replacement, 1)
            path.write_text(new_text, encoding="utf-8")
            return True
        except Exception as e:
            return False
