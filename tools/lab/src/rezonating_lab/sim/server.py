"""asyncio TCP front end of the simulated node (127.0.0.1:7350 by default)."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable

from ..link.transport_tcp import DEFAULT_PORT
from .node import Connection, SimConfig, SimNode

TICK_S = 0.01


class SimServer:
    def __init__(self, cfg: SimConfig, host: str = "127.0.0.1", port: int = DEFAULT_PORT, clock=None) -> None:
        self.cfg = cfg
        self.host = host
        self.port = port
        self.node = SimNode(cfg) if clock is None else SimNode(cfg, clock)
        self._server: asyncio.AbstractServer | None = None
        self._tick_task: asyncio.Task | None = None
        self._writers: dict[Connection, asyncio.StreamWriter] = {}

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]  # the real port when 0 was asked for
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        if self._tick_task:
            self._tick_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tick_task
        for writer in list(self._writers.values()):
            writer.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.node.close()

    async def serve_forever(self) -> None:
        await self.start()
        try:
            await asyncio.Event().wait()
        finally:
            await self.stop()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        def backlog() -> int:
            return writer.transport.get_write_buffer_size()

        conn = self.node.connect(writer.write, backlog, writer.close)
        self._writers[conn] = writer
        try:
            while not conn.closed:
                data = await reader.read(65536)
                if not data:
                    break
                conn.feed(data)
                with contextlib.suppress(ConnectionError):
                    await writer.drain()
        except ConnectionError:
            pass
        finally:
            conn.transport_closed()  # TCP rules: end the session; USB rules: the node doesn't see the close
            self._writers.pop(conn, None)
            writer.close()

    async def _tick_loop(self) -> None:
        while True:
            self.node.tick()
            for writer in list(self._writers.values()):
                if not writer.is_closing() and writer.transport.get_write_buffer_size() < 1_000_000:
                    with contextlib.suppress(ConnectionError):
                        await writer.drain()
            await asyncio.sleep(TICK_S)


class SimThread:
    """Runs a :class:`SimServer` on its own event loop in a background thread (tests, notebooks)."""

    def __init__(
        self, cfg: SimConfig, host: str = "127.0.0.1", port: int = 0, clock: Callable[[], float] | None = None
    ):
        self.server = SimServer(cfg, host, port, clock)
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="rzlab-sim", daemon=True)

    @property
    def node(self) -> SimNode:
        return self.server.node

    @property
    def port(self) -> int:
        return self.server.port

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self.server.start())
        except BaseException as exc:  # noqa: BLE001
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        self._loop.run_forever()

    def start(self) -> SimThread:
        self._thread.start()
        self._ready.wait(10)
        if self._error:
            raise self._error
        return self

    def stop(self) -> None:
        if not self._thread.is_alive():
            return
        asyncio.run_coroutine_threadsafe(self.server.stop(), self._loop).result(10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(10)
        self._loop.close()

    def __enter__(self) -> SimThread:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
