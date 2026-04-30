"""Parser for JavaScript / TypeScript source files using regex-based heuristics.

For a production system, prefer ``@babel/parser`` or ``tree-sitter``. This
implementation uses regex patterns that cover the vast majority of real-world
import/require and API-call patterns.
"""

from __future__ import annotations

import re
from pathlib import Path

from parsers.base import BaseParser, FunctionCall, ImportStatement, ParsedFile


class JsTsParser(BaseParser):
    """Heuristic JS/TS parser — safe for static analysis and migration."""

    language = "javascript"

    IMPORT_PATTERNS: list[re.Pattern] = [
        # import default from 'module'
        re.compile(r'import\s+(\w+)\s+from\s+[\'"]([^\'"]+)[\'"]'),
        # import { a, b } from 'module'
        re.compile(r'import\s+\{([^}]+)\}\s+from\s+[\'"]([^\'"]+)[\'"]'),
        # import * as name from 'module'
        re.compile(r'import\s+\*\s+as\s+\w+\s+from\s+[\'"]([^\'"]+)[\'"]'),
        # const x = require('module')
        re.compile(r'(?:const|let|var)\s+\w+\s*=\s*require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)'),
        # dynamic import('module')
        re.compile(r'import\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)'),
    ]

    # Match object.method(...) or method(...) calls
    CALL_PATTERN = re.compile(r"""
        (?:(\w+)\.)?                # optional object
        (\w+)\s*                    # method name
        \(([^)]*)\)                 # args
    """, re.VERBOSE)

    EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}

    @classmethod
    def supported_extensions(cls) -> set[str]:
        return cls.EXTENSIONS

    def parse(self, file_path: str | Path) -> ParsedFile:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()

        parsed = ParsedFile(path=str(path), language=self.language)

        for i, line in enumerate(lines, 1):
            self._match_import(line, i, str(path), parsed)
            self._match_calls(line, i, str(path), parsed)

        return parsed

    def _match_import(self, line: str, line_num: int, file_path: str, parsed: ParsedFile) -> None:
        for pattern in self.IMPORT_PATTERNS:
            m = pattern.search(line)
            if m:
                groups = m.groups()
                module = groups[-1]  # last group is always the module name
                names: list[str] = []
                is_default = False
                if len(groups) == 2:
                    # import default from 'module' or import {a,b} from 'module'
                    first = groups[0]
                    if "{" not in first:
                        is_default = True
                        names = [first.strip()]
                    else:
                        names = [n.strip() for n in first.split(",")]
                parsed.imports.append(
                    ImportStatement(
                        module=module,
                        names=names,
                        is_default=is_default,
                        line=line_num,
                        source=line.strip()[:120],
                        file_path=file_path,
                    )
                )
                break  # first match wins per line

    def _match_calls(self, line: str, line_num: int, file_path: str, parsed: ParsedFile) -> None:
        for m in self.CALL_PATTERN.finditer(line):
            obj, method, args_str = m.groups()
            # Skip non-identifier-like calls (e.g. if, for, while)
            if method in ("if", "for", "while", "switch", "catch", "function", "return", "class"):
                continue
            # Parse args list (simple comma split — won't handle nested commas)
            args = [a.strip() for a in args_str.split(",") if a.strip()]
            parsed.function_calls.append(
                FunctionCall(
                    name=method,
                    object=obj,
                    args=args,
                    line=line_num,
                    source=line.strip()[:120],
                    file_path=file_path,
                )
            )
