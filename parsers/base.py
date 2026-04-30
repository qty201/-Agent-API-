"""Abstract parser interface and shared AST data types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ImportStatement:
    """Represents a single import / require statement in source code."""

    module: str
    names: list[str] = field(default_factory=list)
    is_default: bool = False
    line: int = 0
    source: str = ""
    file_path: str = ""


@dataclass
class FunctionCall:
    """Represents a function or method call in source code."""

    name: str
    object: str | None = None
    args: list[str] = field(default_factory=list)
    keywords: dict[str, str] = field(default_factory=dict)
    line: int = 0
    source: str = ""
    file_path: str = ""


@dataclass
class ParsedFile:
    """Full parsed representation of a source file."""

    path: str
    language: str
    imports: list[ImportStatement] = field(default_factory=list)
    function_calls: list[FunctionCall] = field(default_factory=list)
    raw_ast: Any = None


class BaseParser(ABC):
    """Abstract parser — every language implements ``parse``."""

    language: str = ""

    @abstractmethod
    def parse(self, file_path: str | Path) -> ParsedFile:
        """Parse a source file and return its structured representation."""
        ...

    def parse_directory(
        self, directory: str | Path, pattern: str | None = None
    ) -> list[ParsedFile]:
        """Parse all matching files in a directory."""
        root = Path(directory).resolve()
        results: list[ParsedFile] = []
        for path in root.rglob(pattern or "*"):
            if path.is_file() and path.suffix in self.supported_extensions():
                try:
                    results.append(self.parse(str(path)))
                except Exception:
                    continue
        return results

    @classmethod
    @abstractmethod
    def supported_extensions(cls) -> set[str]:
        """Return the file extensions this parser handles (e.g. ``{".py"}``)."""
        ...
