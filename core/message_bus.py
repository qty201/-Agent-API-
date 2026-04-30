"""Async message bus for inter-agent communication."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Message:
    """Message exchanged between agents via the message bus."""

    type: str
    source: str
    target: str
    payload: Any
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict = field(default_factory=dict)
    in_reply_to: str | None = None


class MessageBus:
    """Async message bus — agents register and exchange messages through it."""

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}
        self._agents: dict[str, Any] = {}
        self._reply_queues: dict[int, asyncio.Queue] = {}

    async def register(self, agent: Any) -> None:
        """Register an agent so it can receive messages."""
        self._queues[agent.name] = asyncio.Queue()
        self._agents[agent.name] = agent

    async def unregister(self, agent: Any) -> None:
        """Remove an agent from the bus."""
        self._queues.pop(agent.name, None)
        self._agents.pop(agent.name, None)

    async def publish(self, message: Message) -> None:
        """Deliver a message to the target agent's inbox."""
        queue = self._queues.get(message.target)
        if queue is None:
            raise ValueError(
                f"Agent '{message.target}' not found. "
                f"Registered: {list(self._agents.keys())}"
            )
        await queue.put(message)

    async def consume(self, agent_name: str) -> Message:
        """Block until the next message arrives for *agent_name*."""
        queue = self._queues.get(agent_name)
        if queue is None:
            raise ValueError(f"Agent '{agent_name}' not found")
        return await queue.get()

    async def broadcast(
        self,
        msg_type: str,
        payload: Any,
        source: str,
        exclude: list[str] | None = None,
    ) -> list[Message]:
        """Send a message to every registered agent except *source*."""
        exclude = set(exclude or [])
        exclude.add(source)
        sent: list[Message] = []
        for name in self._agents:
            if name not in exclude:
                msg = Message(
                    type=msg_type, source=source, target=name, payload=payload
                )
                await self.publish(msg)
                sent.append(msg)
        return sent

    async def request(
        self, source: str, target: str, msg_type: str, payload: Any, timeout: float = 30.0
    ) -> Message:
        """Send a request and wait for a reply."""
        reply_queue: asyncio.Queue[Message] = asyncio.Queue()
        msg = Message(
            type=msg_type, source=source, target=target, payload=payload
        )
        qid = id(reply_queue)
        msg.metadata["_reply_queue_id"] = qid
        self._reply_queues[qid] = reply_queue
        await self.publish(msg)
        try:
            reply = await asyncio.wait_for(reply_queue.get(), timeout)
            return reply
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Request {msg_type} from {source} to {target} timed out ({timeout}s)"
            )
        finally:
            self._reply_queues.pop(qid, None)

    async def reply(self, original: Message, payload: Any) -> None:
        """Send a reply to a prior request message."""
        qid = original.metadata.get("_reply_queue_id")
        if qid is not None:
            queue = self._reply_queues.get(qid)
            if queue:
                reply = Message(
                    type=f"{original.type}.reply",
                    source=original.target,
                    target=original.source,
                    payload=payload,
                    in_reply_to=original.id,
                )
                await queue.put(reply)
                return
        # fallback — direct message
        await self.publish(
            Message(
                type=f"{original.type}.reply",
                source=original.target,
                target=original.source,
                payload=payload,
                in_reply_to=original.id,
            )
        )
