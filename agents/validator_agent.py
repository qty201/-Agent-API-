"""Validator Agent — tests migrated code and reports results."""

from __future__ import annotations

import logging
import subprocess  # nosec
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from core.agent import BaseAgent
from core.message_bus import Message
from config.settings import settings
from llm.claude_client import ClaudeClient
from llm.prompts import get_prompt

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Results from running project tests after migration."""

    passed: bool = False
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    errors: list[str] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    test_output: str = ""
    review_notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class ValidatorAgent(BaseAgent):
    """Runs project tests and validates migration patches."""

    def __init__(self, message_bus):
        super().__init__("validator_agent", message_bus)
        self._llm = ClaudeClient() if settings.is_llm_available() else None
        self.subscribe("validate", self._handle_validate)

    async def _handle_validate(self, message: Message) -> None:
        payload = message.payload
        project_path = payload.get("project_path", "")
        repair_results = payload.get("step_results", {}).get("repair", {})

        logger.info("Validating migration for %s", project_path)

        result = ValidationResult()

        # Phase 1: Run the project's test suite
        self._run_tests(project_path, result)

        # Phase 2: LLM review of the patches
        if self._llm:
            await self._review_patches(result, repair_results, project_path)

        # Phase 3: Basic sanity checks
        self._sanity_checks(project_path, result)

        result.passed = (
            result.failed_tests == 0
            and not result.errors
            and result.total_tests > 0
        )

        logger.info(
            "Validation: %d/%d passed, %d errors",
            result.passed_tests,
            result.total_tests,
            len(result.errors),
        )

        await self.reply(message, result.to_dict())

    def _run_tests(self, project_path: str, result: ValidationResult) -> None:
        """Attempt to run the project's test suite."""
        root = Path(project_path)
        test_commands = self._detect_test_commands(root)

        if not test_commands:
            result.test_output = "No test framework detected."
            return

        for cmd in test_commands:
            try:
                logger.info("Running: %s", " ".join(cmd))
                output = subprocess.run(  # nosec
                    cmd,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                result.test_output += f"$ {' '.join(cmd)}\n{output.stdout}\n{output.stderr}\n"
                self._parse_test_output(output, result)
            except subprocess.TimeoutExpired:
                result.errors.append(f"Test command timed out: {' '.join(cmd)}")
            except FileNotFoundError:
                result.errors.append(f"Test command not found: {cmd[0]}")
            except Exception as e:
                result.errors.append(f"Test error: {e}")

    def _detect_test_commands(self, root: Path) -> list[list[str]]:
        """Detect available test runners."""
        commands: list[list[str]] = []
        has_node = (root / "package.json").exists()
        has_python = (root / "pyproject.toml").exists() or (root / "setup.cfg").exists()

        if has_node:
            commands.append([sys.executable, "-m", "npm", "test", "--", "--run"])
            # fallback
            commands.append([self._npm_path(), "test", "--", "--run"])

        if has_python:
            commands.append([sys.executable, "-m", "pytest", "--tb=short", "-q"])
            commands.append([sys.executable, "-m", "unittest", "discover", "-q"])

        return commands

    @staticmethod
    def _npm_path() -> str:
        """Return npm path (cross-platform)."""
        import shutil
        return shutil.which("npm") or "npm"

    @staticmethod
    def _parse_test_output(output: subprocess.CompletedProcess, result: ValidationResult) -> None:
        """Parse common test output formats for pass/fail counts."""
        import re

        stdout = output.stdout + output.stderr

        # pytest summary: "1 passed, 2 failed"
        for m in re.finditer(r"(\d+)\s+passed", stdout):
            result.passed_tests += int(m.group(1))
        for m in re.finditer(r"(\d+)\s+failed", stdout):
            result.failed_tests += int(m.group(1))

        # Jest/Node: "Tests: 5 passed, 5 total"
        jest_match = re.search(r"Tests:\s+(\d+)\s+(passed|failed)", stdout)
        if jest_match:
            count = int(jest_match.group(1))
            if jest_match.group(2) == "passed":
                result.passed_tests = count
            else:
                result.failed_tests = count

        # Total: sum passed + failed
        result.total_tests = result.passed_tests + result.failed_tests

        # Collect FAIL lines
        for line in stdout.splitlines():
            if line.strip().startswith("FAIL") or "FAILED" in line:
                result.failures.append({"line": line.strip()[:200]})

    async def _review_patches(
        self, result: ValidationResult, repair_results: dict, project_path: str
    ) -> None:
        """Use LLM to review the generated patches for correctness."""
        try:
            system, user_msg = get_prompt(
                "validate",
                {
                    "patches": str(repair_results.get("suggestions", [])),
                    "project_type": self._detect_project_type(project_path),
                },
            )
            review = await self._llm.chat(
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            result.review_notes = review
        except Exception as e:
            logger.warning("LLM patch review failed: %s", e)

    @staticmethod
    def _detect_project_type(project_path: str) -> str:
        root = Path(project_path)
        if (root / "package.json").exists():
            return "node"
        if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
            return "python"
        if (root / "pom.xml").exists():
            return "java"
        return "unknown"

    @staticmethod
    def _sanity_checks(project_path: str, result: ValidationResult) -> None:
        """Basic post-migration sanity: syntax checks, import resolution."""
        root = Path(project_path)

        # Python: try to compile all .py files
        for py_file in root.rglob("*.py"):
            if "node_modules" in py_file.parts or ".venv" in py_file.parts:
                continue
            try:
                compile(py_file.read_text(encoding="utf-8"), str(py_file), "exec")
            except SyntaxError as e:
                result.errors.append(f"Syntax error in {py_file}: {e}")

        # JS/TS: basic syntax check via node --check
        for js_file in root.rglob("*.js"):
            if "node_modules" in js_file.parts:
                continue
            try:
                subprocess.run(  # nosec
                    [sys.executable, "-m", "node", "--check", str(js_file)],
                    capture_output=True,
                    timeout=10,
                )
            except Exception:
                pass  # node may not be available
