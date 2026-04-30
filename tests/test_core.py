"""Tests for core framework: message bus, agent lifecycle, workflow state."""

import pytest
from core.message_bus import Message, MessageBus
from core.agent import BaseAgent
from core.workflow import WorkflowState, WorkflowStep, StepName, StepStatus


@pytest.mark.asyncio
async def test_message_bus_register_and_publish():
    bus = MessageBus()

    class FakeAgent(BaseAgent):
        def __init__(self):
            super().__init__("test_agent", bus)

    agent = FakeAgent()
    await agent.start()

    received = []

    async def handler(msg: Message):
        received.append(msg)

    agent.subscribe("test.event", handler)

    await bus.publish(Message(type="test.event", source="orchestrator", target="test_agent", payload={"key": "val"}))
    await bus.publish(Message(type="test.event", source="orchestrator", target="test_agent", payload={"key2": "val2"}))

    # Give the agent time to process
    import asyncio
    await asyncio.sleep(0.05)

    assert len(received) == 2
    assert received[0].payload["key"] == "val"
    await agent.stop()


@pytest.mark.asyncio
async def test_message_bus_request_reply():
    bus = MessageBus()

    class EchoAgent(BaseAgent):
        def __init__(self):
            super().__init__("echo", bus)

    agent = EchoAgent()
    await agent.start()

    async def echo_handler(msg: Message):
        await agent.reply(msg, msg.payload)

    agent.subscribe("ping", echo_handler)

    import asyncio
    await asyncio.sleep(0.05)

    reply = await bus.request("tester", "echo", "ping", {"hello": "world"}, timeout=5.0)
    assert reply.payload == {"hello": "world"}
    await agent.stop()


def test_workflow_state_initial():
    state = WorkflowState(
        session_id="test-123",
        project_path="/test/project",
        target_deps={"react": "18.0.0"},
    )
    assert state.session_id == "test-123"
    assert len(state.steps) == 5
    assert state.next_step() is not None
    assert state.next_step().name == StepName.SCAN


def test_workflow_step_lifecycle():
    step = WorkflowStep(name=StepName.SCAN)
    assert step.status == StepStatus.PENDING

    step.start()
    assert step.status == StepStatus.RUNNING

    step.succeed({"deps": ["react"]})
    assert step.status == StepStatus.SUCCEEDED
    assert step.result == {"deps": ["react"]}


def test_workflow_state_persistence(tmp_path):
    import os
    os.environ["HOME"] = str(tmp_path)

    state = WorkflowState(
        session_id="persist-test",
        project_path="/test",
        target_deps={"dep": "2.0"},
    )
    state.step(StepName.SCAN).succeed({"ok": True})
    state.save()

    loaded = WorkflowState.load("persist-test")
    assert loaded is not None
    assert loaded.session_id == "persist-test"
    assert loaded.step(StepName.SCAN).status == StepStatus.SUCCEEDED


def test_workflow_state_complete():
    state = WorkflowState(session_id="c", project_path="/p", target_deps={})
    for s in state.steps.values():
        s.succeed()
    assert state.is_complete() is True


def test_workflow_state_failed():
    state = WorkflowState(session_id="f", project_path="/p", target_deps={})
    state.step(StepName.ANALYZE).fail("oops")
    assert state.is_failed() is True
