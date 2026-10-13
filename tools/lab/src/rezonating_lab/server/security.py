"""Loopback-only guard for the Lab server (D-017: an internal bench tool, never reachable from the network).

Three layers:

1. ``check_bind_host``: ``rzlab serve`` refuses to bind anything but 127.0.0.1, ::1 or localhost.
2. Host header check (DNS rebinding): only ``127.0.0.1:PORT``, ``localhost:PORT`` and ``[::1]:PORT`` are served.
3. Origin check (a web page in the browser calling us): a request that carries an ``Origin`` must come from the
   same origins. Only ``rzlab serve --dev`` also lets in the Vite dev server (``http://localhost:5173`` /
   ``http://127.0.0.1:5173``): in a normal run, any other local project on port 5173 is a foreign origin. A foreign
   origin gets 403 on HTTP, and the WebSocket handshake is closed before it is accepted. Requests without an
   ``Origin`` (curl, the soak client, plain navigation) pass the Origin check but still need a good Host.

There is no CORS: nothing sends ``Access-Control-Allow-*``, so browsers never expose responses cross-origin.
"""

from __future__ import annotations

import json

LOOPBACK_BIND_HOSTS = ("127.0.0.1", "::1", "localhost")
LOOPBACK_NAMES = ("127.0.0.1", "localhost", "[::1]")
DEV_SERVER_PORTS = (5173,)


def check_bind_host(host: str) -> str:
    """Return ``host`` when it is a loopback address; raise ``ValueError`` otherwise."""
    if host.strip().lower() not in LOOPBACK_BIND_HOSTS:
        raise ValueError(
            f"refusing to bind {host!r}: rzlab serve only listens on loopback (127.0.0.1, ::1 or localhost). "
            "The Lab has no login and must not be reachable from the network."
        )
    return host.strip()


def allowed_hosts(port: int, extra_ports: tuple[int, ...] = ()) -> frozenset[str]:
    hosts: set[str] = set()
    for p in {port, *extra_ports}:
        for name in LOOPBACK_NAMES:
            hosts.add(f"{name}:{p}")
            if p == 80:
                hosts.add(name)
    return frozenset(hosts)


def allowed_origins(port: int, extra_ports: tuple[int, ...] = ()) -> frozenset[str]:
    origins: set[str] = set()
    for p in {port, *extra_ports}:
        for name in LOOPBACK_NAMES:
            origins.add(f"http://{name}:{p}")
            if p == 80:
                origins.add(f"http://{name}")
    return frozenset(origins)


class LoopbackGuard:
    """Pure ASGI middleware (it also sees WebSocket handshakes, which Starlette's HTTP middleware does not)."""

    def __init__(self, app, port: int, dev_ports: tuple[int, ...] = ()) -> None:
        self.app = app
        self.hosts = allowed_hosts(port, dev_ports)
        self.origins = allowed_origins(port, dev_ports)

    def refusal(self, scope) -> tuple[str, str] | None:
        """``(code, message)`` when the request must be refused, else None."""
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        host = headers.get(b"host", b"").decode("latin-1").strip().lower()
        if host not in self.hosts:
            return "bad_host", f"Host {host!r} is not allowed; use 127.0.0.1, localhost or [::1] with the server's port"
        origin = headers.get(b"origin")
        if origin is not None:
            o = origin.decode("latin-1").strip().lower()
            if o not in self.origins:
                return "bad_origin", f"Origin {o!r} is not allowed"
        return None

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        why = self.refusal(scope)
        if why is None:
            await self.app(scope, receive, send)
            return
        code, message = why
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 1008, "reason": code})  # refused before accept: HTTP 403
            return
        body = json.dumps({"error": {"code": code, "message": message}}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})
