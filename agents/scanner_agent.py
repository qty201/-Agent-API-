"""Scanner Agent — discovers dependencies and maps their usage in source code."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.agent import BaseAgent
from core.message_bus import Message
from scanners import NodeScanner, PythonScanner
from scanners.base import ScanResult
from config.settings import settings
from llm.claude_client import ClaudeClient
from llm.prompts import get_prompt

logger = logging.getLogger(__name__)


class ScannerAgent(BaseAgent):
    """Scans a project for dependency manifests and source-level usage."""

    def __init__(self, message_bus):
        super().__init__("scanner_agent", message_bus)
        self._scanners = [NodeScanner(), PythonScanner()]
        self._llm = ClaudeClient() if settings.is_llm_available() else None
        self.subscribe("scan", self._handle_scan)
        self.subscribe("scan.file_usages", self._handle_file_usages)

    async def _handle_scan(self, message: Message) -> None:
        """Main scan handler — called by the orchestrator."""
        payload: dict = message.payload
        project_path = payload["project_path"]
        target_deps = payload.get("target_deps", {})

        logger.info("Scanning project: %s", project_path)
        result = self._scan_project(project_path)
        self._merge_target_versions(result, target_deps)
        self._build_file_usage_map(result, project_path)

        if self._llm and result.all_dependencies:
            await self._enrich_with_llm(result, project_path, target_deps)

        await self.reply(message, result.to_dict())

    def _scan_project(self, project_path: str) -> ScanResult:
        """Run all registered scanners and merge results."""
        result = ScanResult(project_path=project_path)
        for scanner in self._scanners:
            try:
                scanner_result = scanner.scan(project_path)
                result.dependency_files.extend(scanner_result.dependency_files)
                result.all_dependencies.update(scanner_result.all_dependencies)
            except Exception as e:
                logger.warning("Scanner %s failed: %s", type(scanner).__name__, e)
        return result

    @staticmethod
    def _merge_target_versions(result: ScanResult, targets: dict[str, str]) -> None:
        """Overlay user-specified target versions onto discovered dependencies."""
        for name, version in targets.items():
            if name in result.all_dependencies:
                result.all_dependencies[name].target_version = version
            else:
                logger.warning("Target dep %s not found in project", name)

    @staticmethod
    def _build_file_usage_map(result: ScanResult, project_path: str) -> None:
        """Simple heuristic: grep for import/require statements matching deps."""
        root = Path(project_path).resolve()
        source_extensions = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".py", ".java"}
        dep_names = set(result.all_dependencies.keys())

        for path in root.rglob("*"):
            if path.suffix not in source_extensions or path.is_dir():
                continue
            if "node_modules" in path.parts or ".venv" in path.parts or "__pycache__" in path.parts:
                continue

            usages: list[dict] = []
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(text.splitlines(), 1):
                    stripped = line.strip()
                    for dep_name in dep_names:
                        # Check import/require patterns
                        if dep_name in stripped and any(
                            keyword in stripped
                            for keyword in ("import", "require", "from", "export")
                        ):
                            usages.append({
                                "file": str(path.relative_to(root)),
                                "line": i,
                                "code": stripped[:120],
                                "dependency": dep_name,
                            })
            except Exception:
                continue

            if usages:
                result.file_usage_map[str(path)] = usages

    async def _enrich_with_llm(
        self, result: ScanResult, project_path: str, target_deps: dict[str, str]
    ) -> None:
        """Use the LLM to identify deeper usage patterns."""
        try:
            system, user = get_prompt(
                "scan",
                {
                    "project_path": project_path,
                    "target_deps": str(target_deps),
                    "scan_data": str(result.to_dict()),
                },
            )
            enriched = await self._llm.chat(system=system, messages=[{"role": "user", "content": user}])
            logger.info("LLM enrichment received (%d chars)", len(enriched))
            result.metadata["llm_analysis"] = enriched
        except Exception as e:
            logger.warning("LLM enrichment failed: %s", e)

    async def _handle_file_usages(self, message: Message) -> None:
        """Handle a targeted file usage request (for repair agent)."""
        dep_name = message.payload.get("dependency", "")
        result = self._scan_project(message.payload.get("project_path", ""))
        self._build_file_usage_map(result, message.payload.get("project_path", ""))
        filtered = {
            k: v for k, v in result.file_usage_map.items()
            if any(u["dependency"] == dep_name for u in v)
        }
        await self.reply(message, filtered)
