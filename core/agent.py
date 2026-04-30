"""Base agent with async lifecycle and message dispatch."""

import asyncio
import logging
from abc import ABC
from collections.abc import Awaitable, Callable
from typing import Any

from core.message_bus import Message, MessageBus

logger = logging.getLogger(__name__)

MessageHandler = Callable[[Message], Awaitable[Any]]


class BaseAgent(ABC):
    """Every agent in the system extends this base class.

    Lifecycle::

        agent = MyAgent("name", bus)
        await agent.start()
        # ... messages flow ...
        await agent.stop()
    """

    def __init__(self, name: str, message_bus: MessageBus):
        self.name = name
        self.message_bus = message_bus
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    # ── lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        """Register with the bus and begin processing messages."""
        self._running = True
        await self.message_bus.register(self)
        self._task = asyncio.create_task(self._message_loop())
        logger.info("Agent %s started", self.name)

    async def stop(self) -> None:
        """Shut down the agent gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.message_bus.unregister(self)
        logger.info("Agent %s stopped", self.name)

    # ── message helpers ────────────────────────────────────────

    def subscribe(self, message_type: str, handler: MessageHandler) -> None:
        """Register a handler for *message_type* (``*`` catches all)."""
        self._handlers.setdefault(message_type, []).append(handler)

    async def send(
        self, target: str, msg_type: str, payload: Any, **metadata: Any
    ) -> Message:
        """Fire-and-forget a message."""
        msg = Message(
            source=self.name,
            target=target,
            type=msg_type,
            payload=payload,
            metadata=metadata,
        )
        await self.message_bus.publish(msg)
        return msg

    async def request(
        self, target: str, msg_type: str, payload: Any, timeout: float = 30.0
    ) -> Message:
        """Send a request and wait for a reply."""
        return await self.message_bus.request(
            source=self.name,
            target=target,
            msg_type=msg_type,
            payload=payload,
            timeout=timeout,
        )

    async def reply(self, original: Message, payload: Any) -> None:
        """Reply to a request message."""
        await self.message_bus.reply(original, payload)

    # ── internal ───────────────────────────────────────────────

    async def _message_loop(self) -> None:
        while self._running:
            try:
                message = await self.message_bus.consume(self.name)
                await self._dispatch(message)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in %s message loop", self.name)

    async def _dispatch(self, message: Message) -> None:
        handlers = self._handlers.get(message.type, []) + self._handlers.get("*", [])
        for handler in handlers:
            try:
                await handler(message)
            except Exception:
                logger.exception(
                    "Handler failed in %s for message %s", self.name, message.id
                )
