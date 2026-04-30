"""Parser for Python source files using the built-in ``ast`` module."""

from __future__ import annotations

import ast
from pathlib import Path

from parsers.base import BaseParser, FunctionCall, ImportStatement, ParsedFile


class PythonParser(BaseParser):
    """Python source parser using stdlib ``ast``."""

    language = "python"

    EXTENSIONS = {".py"}

    @classmethod
    def supported_extensions(cls) -> set[str]:
        return cls.EXTENSIONS

    def parse(self, file_path: str | Path) -> ParsedFile:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8", errors="ignore")
        parsed = ParsedFile(path=str(path), language=self.language)

        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            return parsed  # return empty on parse error

        for node in ast.walk(tree):
            self._handle_import(node, text, parsed, str(path))
            self._handle_call(node, text, parsed, str(path))

        return parsed

    def _handle_import(self, node: ast.AST, source: str, parsed: ParsedFile, file_path: str) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                parsed.imports.append(
                    ImportStatement(
                        module=alias.name,
                        names=[alias.asname or alias.name],
                        line=node.lineno if hasattr(node, "lineno") else 0,
                        source=self._get_line(source, node),
                        file_path=file_path,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = []
            for alias in node.names:
                names.append(alias.asname or alias.name)
            parsed.imports.append(
                ImportStatement(
                    module=module,
                    names=names,
                    is_default=False,
                    line=node.lineno if hasattr(node, "lineno") else 0,
                    source=self._get_line(source, node),
                    file_path=file_path,
                )
            )

    def _handle_call(self, node: ast.AST, source: str, parsed: ParsedFile, file_path: str) -> None:
        if not isinstance(node, ast.Call):
            return

        func = node.func
        name: str = ""
        obj: str | None = None

        if isinstance(func, ast.Attribute):
            name = func.attr
            if isinstance(func.value, ast.Name):
                obj = func.value.id
            elif isinstance(func.value, ast.Attribute):
                obj = f"{self._expr_to_str(func.value)}.{func.attr}"  # simplified
        elif isinstance(func, ast.Name):
            name = func.id

        if not name:
            return

        args = [self._expr_to_str(a) for a in node.args]
        keywords = {}
        for kw in node.keywords:
            if kw.arg:
                keywords[kw.arg] = self._expr_to_str(kw.value)

        parsed.function_calls.append(
            FunctionCall(
                name=name,
                object=obj,
                args=args,
                keywords=keywords,
                line=node.lineno if hasattr(node, "lineno") else 0,
                source=self._get_line(source, node),
                file_path=file_path,
            )
        )

    @staticmethod
    def _get_line(source: str, node: ast.AST) -> str:
        try:
            lines = source.splitlines()
            return lines[node.lineno - 1].strip()[:120] if node.lineno else ""
        except (IndexError, TypeError):
            return ""

    @staticmethod
    def _expr_to_str(node: ast.AST) -> str:
        """Convert an AST expression node to a string representation."""
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{PythonParser._expr_to_str(node.value)}.{node.attr}"
        if isinstance(node, ast.List):
            return f"[{', '.join(PythonParser._expr_to_str(e) for e in node.elts)}]"
        if isinstance(node, ast.Call):
            return f"{PythonParser._expr_to_str(node.func)}(...)"
        if isinstance(node, ast.BinOp):
            return f"{PythonParser._expr_to_str(node.left)} op {PythonParser._expr_to_str(node.right)}"
        return "<expr>"
