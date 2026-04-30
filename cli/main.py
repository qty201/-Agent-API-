"""CLI entry point — ``python -m api_upgrade_agent.cli.main upgrade ...``"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid

from config.settings import settings
from core.message_bus import MessageBus
from core.orchestrator import OrchestratorAgent

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="api-upgrade-agent",
        description="Multi-agent API dependency upgrade & compatibility repair system",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ── upgrade ────────────────────────────────────────────────
    up = sub.add_parser("upgrade", help="Run a full upgrade workflow")
    up.add_argument("--project", "-p", required=True, help="Path to project root")
    up.add_argument(
        "--deps", "-d", required=True, nargs="+",
        help="Dependencies to upgrade, e.g. ``react@18 express@5``",
    )
    up.add_argument("--resume", help="Session ID to resume")
    up.add_argument("--dry-run", action="store_true", help="Don't apply changes")
    up.add_argument("--auto-apply", action="store_true", help="Auto-apply patches")
    up.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )

    # ── scan ───────────────────────────────────────────────────
    sc = sub.add_parser("scan", help="Scan a project for dependencies")
    sc.add_argument("--project", "-p", required=True)

    # ── analyze ────────────────────────────────────────────────
    an = sub.add_parser("analyze", help="Analyze compatibility issues")
    an.add_argument("--project", "-p", required=True)

    # ── repair ─────────────────────────────────────────────────
    rp = sub.add_parser("repair", help="Generate migration patches")
    rp.add_argument("--project", "-p", required=True)

    # ── report ─────────────────────────────────────────────────
    rpt = sub.add_parser("report", help="Generate upgrade report")
    rpt.add_argument("--session", required=True)

    return p


async def _cmd_upgrade(args: argparse.Namespace) -> None:
    settings.dry_run = args.dry_run
    settings.auto_apply = args.auto_apply
    settings.project_root = args.project
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    target_deps: dict[str, str] = {}
    for dep in args.deps:
        if "@" in dep:
            name, version = dep.rsplit("@", 1)
        else:
            name, version = dep, "latest"
        target_deps[name] = version

    bus = MessageBus()
    orchestrator = OrchestratorAgent(bus, session_id=args.resume or uuid.uuid4().hex[:12])

    # Create and start all agents
    from agents.scanner_agent import ScannerAgent
    from agents.analyzer_agent import AnalyzerAgent
    from agents.repair_agent import RepairerAgent
    from agents.validator_agent import ValidatorAgent
    from agents.reporter_agent import ReporterAgent

    agents = [
        orchestrator,
        ScannerAgent(bus),
        AnalyzerAgent(bus),
        RepairerAgent(bus),
        ValidatorAgent(bus),
        ReporterAgent(bus),
    ]

    for a in agents:
        await a.start()

    try:
        if args.resume:
            state = await orchestrator.resume(args.resume)
            if state is None:
                logger.error("Session %s not found", args.resume)
                return
        else:
            state = await orchestrator.run_upgrade(
                project_path=args.project,
                target_deps=target_deps,
            )
    finally:
        for a in reversed(agents):
            await a.stop()

    # Print summary
    print("\n=== Upgrade Summary ===")
    print(f"Session:  {state.session_id}")
    print(f"Project:  {state.project_path}")
    for step in state.steps.values():
        status_icon = "✓" if step.status.value == "succeeded" else "✗" if step.status.value == "failed" else "…"
        print(f"  {status_icon} {step.name.value}: {step.status.value}")
        if step.error:
            print(f"     error: {step.error}")

    if state.is_failed():
        sys.exit(1)


async def _cmd_scan(args: argparse.Namespace) -> None:
    from scanners import NodeScanner, PythonScanner

    scanners = [NodeScanner(), PythonScanner()]
    all_deps = {}
    for scanner in scanners:
        for dep_file in scanner.discover(args.project):
            deps = scanner.parse(dep_file)
            for dep in deps:
                all_deps.setdefault(dep.name, []).append(dep.model_dump())

    print(json.dumps(all_deps, indent=2, default=str))


async def _cmd_analyze(args: argparse.Namespace) -> None:
    logger.warning("analyze command requires full workflow context. Use `upgrade` instead.")


async def _cmd_repair(args: argparse.Namespace) -> None:
    logger.warning("repair command requires full workflow context. Use `upgrade` instead.")


async def _cmd_report(args: argparse.Namespace) -> None:
    from core.workflow import WorkflowState

    state = WorkflowState.load(args.session)
    if state is None:
        logger.error("Session %s not found", args.session)
        sys.exit(1)
    print(json.dumps(state.to_dict(), indent=2, default=str))


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    command_map = {
        "upgrade": _cmd_upgrade,
        "scan": _cmd_scan,
        "analyze": _cmd_analyze,
        "repair": _cmd_repair,
        "report": _cmd_report,
    }

    coro = command_map[args.command](args)
    asyncio.run(coro)


if __name__ == "__main__":
    main()
