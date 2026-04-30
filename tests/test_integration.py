"""End-to-end integration test — simulates the full upgrade workflow."""

import pytest
from core.message_bus import MessageBus
from core.orchestrator import OrchestratorAgent
from agents.scanner_agent import ScannerAgent
from agents.analyzer_agent import AnalyzerAgent
from agents.repair_agent import RepairerAgent
from agents.validator_agent import ValidatorAgent
from agents.reporter_agent import ReporterAgent
from config.settings import settings


FIXTURE_PATH = "tests/fixtures/sample-node-project"


@pytest.mark.asyncio
async def test_full_upgrade_workflow():
    """Run the full upgrade pipeline on the sample Node.js project."""
    bus = MessageBus()
    session_id = "e2e-test"

    orchestrator = OrchestratorAgent(bus, session_id=session_id)
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
        state = await orchestrator.run_upgrade(
            project_path=FIXTURE_PATH,
            target_deps={
                "react": "18.0.0",
                "express": "4.0.0",
                "chalk": "5.0.0",
            },
        )
    finally:
        for a in reversed(agents):
            await a.stop()

    # Verify workflow completed
    assert state is not None
    assert state.session_id == session_id

    # All steps should have run (may have failures, but shouldn't be pending)
    for step in state.steps.values():
        assert step.status.value != "pending", f"Step {step.name} still pending"

    # Scan step must have found dependencies
    scan_step = state.step("scan")
    assert scan_step.status.value == "succeeded", f"Scan failed: {scan_step.error}"
    scan_result = scan_step.result
    assert scan_result is not None
    deps = scan_result.get("all_dependencies", {})
    assert "react" in deps
    assert "express" in deps
    assert "chalk" in deps

    # Analyzer should have detected issues
    analyze_step = state.step("analyze")
    assert analyze_step.status.value != "failed", f"Analyze failed: {analyze_step.error}"
    if analyze_step.status.value == "succeeded":
        issues = analyze_step.result.get("issues", [])
        dependencies_with_issues = {i["dependency"] for i in issues}
        assert "react" in dependencies_with_issues or "express" in dependencies_with_issues

    # Report step should have been created
    report_step = state.step("report")
    assert report_step.status.value in ("succeeded", "failed")

    print("\n=== E2E Test Results ===")
    for step in state.steps.values():
        print(f"  {step.name}: {step.status.value}")
        if step.error:
            print(f"    error: {step.error}")


@pytest.mark.asyncio
async def test_scanner_agent_direct():
    """Test scanner agent directly (without orchestrator)."""
    bus = MessageBus()
    agent = ScannerAgent(bus)
    await agent.start()

    try:
        reply = await bus.request(
            source="tester",
            target="scanner_agent",
            msg_type="scan",
            payload={
                "project_path": FIXTURE_PATH,
                "target_deps": {"react": "18.0.0"},
            },
            timeout=10.0,
        )
        assert reply is not None
        payload = reply.payload
        assert "all_dependencies" in payload
        assert "react" in payload["all_dependencies"]
        assert payload["all_dependencies"]["react"]["current_version"] == "17.0.0"
    finally:
        await agent.stop()
