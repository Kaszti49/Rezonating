"""TCP transport (Wi-Fi node on port 7350, or the simulator)."""

from __future__ import annotations

import socket

DEFAULT_PORT = 7350


class TransportClosed(ConnectionError):
    """The other side closed the connection, or the port went away."""


def parse_host_port(text: str, default_port: int = DEFAULT_PORT) -> tuple[str, int]:
    """``host``, ``host:port`` or ``:port`` (host defaults to 127.0.0.1)."""
    host, sep, port = text.rpartition(":")
    if not sep:
        return text, default_port
    return host or "127.0.0.1", int(port)


class TcpTransport:
    def __init__(self, host: str, port: int = DEFAULT_PORT, connect_timeout_s: float = 3.0) -> None:
        self.host = host
        self.port = port
        self._sock: socket.socket | None = socket.create_connection((host, port), timeout=connect_timeout_s)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def read(self, timeout_s: float) -> bytes:
        """Bytes available within ``timeout_s`` (empty on timeout). Raises :class:`TransportClosed`."""
        if self._sock is None:
            raise TransportClosed("closed")
        self._sock.settimeout(max(timeout_s, 0.0001))
        try:
            data = self._sock.recv(65536)
        except TimeoutError:
            return b""
        except OSError as exc:
            raise TransportClosed(str(exc)) from exc
        if not data:
            raise TransportClosed("connection closed by the other side")
        return data

    def write(self, data: bytes) -> None:
        if self._sock is None:
            raise TransportClosed("closed")
        try:
            self._sock.settimeout(5.0)
            self._sock.sendall(data)
        except OSError as exc:
            raise TransportClosed(str(exc)) from exc

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __repr__(self) -> str:
        return f"TcpTransport({self.host}:{self.port})"
