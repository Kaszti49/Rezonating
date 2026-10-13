"""The phone marker: a tiny LAN listener, separate from the Lab server, that lets a phone mark walk starts and ends.

Why a separate listener: the Lab server is loopback-only and has no login (D-017). A phone cannot reach it, and it
must not be made reachable. This listener has its own port and its own uvicorn server, exists only while a recording
runs, and serves exactly one thing: ``/m/<token>`` (the page) and ``/m/<token>/ws`` (its WebSocket).

* The token comes from :mod:`secrets` (160 bits), is compared in constant time, and dies when the recording ends.
* A wrong, unknown or expired token, a wrong method, and every other path give the *same* 404: nothing tells a
  scanner which part was wrong. There is no ``/api``, no ``/ws``, no static files, no docs, no OpenAPI.
* The listener exposes no data: only whether a mark is open.
* The phone page measures its round trip to the server (ping/pong over the WebSocket) and sends it with every mark.
  The server stamps the arrival itself and subtracts half the round trip; ``unc_ms`` of the label includes that half
  round trip, which is the largest error the correction can have (all the latency on one side of the trip).

Hosted pages and the clipboard of a phone are not trusted: messages are small JSON, rate limited, and validated.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import io
import json
import logging
import re
import secrets
import socket
import threading
import time
from collections.abc import Callable
from typing import Protocol

from .config import HOST_WITH_PORT, IPV6_REFUSED, host_with_port, is_ipv6

TOKEN_BYTES = 20  # 160 bits
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_CLIENTS = 4
MAX_MESSAGES_PER_S = 20
IDLE_TIMEOUT_S = 90.0
MAX_RTT_MS = 2000.0
WS_MAX_BYTES = 2048

NOT_FOUND_BODY = b"Not Found"
NOT_FOUND_HEADERS = [
    (b"content-type", b"text/plain; charset=utf-8"),
    (b"content-length", str(len(NOT_FOUND_BODY)).encode()),
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
]


class MarkSink(Protocol):
    """What the marker needs from the recorder."""

    def mark_from_phone(self, edge: str, arrival_us: float, rtt_ms: float) -> dict: ...
    def marker_state(self) -> dict: ...
    def add_state_listener(self, fn: Callable[[dict], None]) -> None: ...
    def remove_state_listener(self, fn: Callable[[dict], None]) -> None: ...


class MarkRefused(Exception):
    """A mark was refused. ``code`` is a short word the phone page shows."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TokenStore:
    """One secret token. Compared through SHA-256 digests with ``hmac.compare_digest``, so neither the content
    nor the length of a guess changes how long the comparison takes. After :meth:`revoke` nothing matches."""

    def __init__(self, token: str | None = None) -> None:
        self.token = token or secrets.token_urlsafe(TOKEN_BYTES)
        self._digest: bytes | None = hashlib.sha256(self.token.encode()).digest()
        self._dummy = hashlib.sha256(secrets.token_bytes(16)).digest()

    @property
    def alive(self) -> bool:
        return self._digest is not None

    def revoke(self) -> None:
        self._digest = None

    def matches(self, candidate: str) -> bool:
        want = self._digest if self._digest is not None else self._dummy
        ok = hmac.compare_digest(hashlib.sha256(candidate.encode("utf-8", "ignore")).digest(), want)
        return ok and self._digest is not None


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark"><meta name="robots" content="noindex">
<title>Marker</title>
<style>
:root{--bg:#f6f6f4;--fg:#1b1b1a;--mut:#6a6a66;--on:#0d7a4f;--off:#9a2a2a;--btn:#e4e3de}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ececea;--mut:#9a9a95;--on:#38b583;--off:#e0605f;--btn:#2a2a28}}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--fg);font:16px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
 display:flex;flex-direction:column;padding:16px;padding-bottom:max(16px,env(safe-area-inset-bottom))}
h1{font-size:1rem;font-weight:600;margin:0 0 4px}
#st{color:var(--mut);font-size:.9rem;min-height:2.6em}
#go{flex:1;margin:16px 0;border:0;border-radius:20px;font-size:2rem;font-weight:700;color:#fff;background:var(--on);
 touch-action:manipulation;-webkit-tap-highlight-color:transparent}
#go.end{background:var(--off)}#go:disabled{background:var(--btn);color:var(--mut)}
#rtt{color:var(--mut);font-size:.85rem;text-align:center}
</style></head><body>
<h1>Walk marker</h1><div id="st">Connecting...</div>
<button id="go" disabled>Start mark</button><div id="rtt">round trip: -</div>
<script>
(function(){
'use strict';
var st=document.getElementById('st'),go=document.getElementById('go'),rttEl=document.getElementById('rtt');
var ws=null,marking=false,recording=false,rtts=[],pingId=0,sent={},backoff=500,timer=null,wake=null;
function median(a){var b=a.slice().sort(function(x,y){return x-y});var n=b.length;return n?b[n>>1]:null}
function ui(msg){if(msg)st.textContent=msg;
 go.textContent=marking?'End mark':'Start mark';go.className=marking?'end':'';
 go.disabled=!(ws&&ws.readyState===1&&recording&&rtts.length>0)}
function send(o){if(ws&&ws.readyState===1)ws.send(JSON.stringify(o))}
function ping(){var id=++pingId;sent[id]=performance.now();send({op:'ping',id:id});
 var keys=Object.keys(sent);if(keys.length>20)delete sent[keys[0]]}
function connect(){
 var p=(location.protocol==='https:'?'wss://':'ws://')+location.host+location.pathname.replace(/\\/+$/,'')+'/ws';
 ws=new WebSocket(p);
 ws.onopen=function(){backoff=500;ui('Connected');ping();clearInterval(timer);timer=setInterval(ping,1000)};
 ws.onmessage=function(ev){var m;try{m=JSON.parse(ev.data)}catch(e){return}
  if(m.op==='pong'){var t0=sent[m.id];if(t0!==undefined){delete sent[m.id];var r=performance.now()-t0;
    rtts.push(r);if(rtts.length>7)rtts.shift();rttEl.textContent='round trip: '+Math.round(median(rtts))+' ms';ui()}}
  else if(m.op==='state'){marking=!!m.marking;recording=!!m.recording;
    ui(recording?(marking?'Mark open - tap when the walk ends':'Recording - tap when the walk starts'):'Not recording');}
  else if(m.op==='ack'){if(m.ok){if(navigator.vibrate)navigator.vibrate(40);}else{ui('Refused: '+m.error)}}};
 ws.onclose=function(){clearInterval(timer);ui('Disconnected - reconnecting...');setTimeout(connect,backoff);backoff=Math.min(backoff*2,5000)};
 ws.onerror=function(){try{ws.close()}catch(e){}}}
var lastFire=-1e9;
function fire(){var now=performance.now();if(now-lastFire<300)return;var r=median(rtts);if(r===null)return;
 lastFire=now;send({op:'mark',edge:marking?'end':'start',rtt_ms:r})}
/* The mark is the moment of the touch, not its release (a click comes after the press has lasted 50-150 ms). */
go.addEventListener('pointerdown',function(ev){if(ev.pointerType==='mouse'&&ev.button!==0)return;fire()});
go.addEventListener('click',function(ev){if(ev.detail===0)fire()}); /* keyboard / switch access: no pointer event */
try{if(navigator.wakeLock){navigator.wakeLock.request('screen').then(function(l){wake=l},function(){})}}catch(e){}
connect();
})();
</script></body></html>
"""
PAGE_BYTES = PAGE.encode("utf-8")
PAGE_HEADERS = [
    (b"content-type", b"text/html; charset=utf-8"),
    (b"content-length", str(len(PAGE_BYTES)).encode()),
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (
        b"content-security-policy",
        b"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        b"connect-src 'self' ws: wss:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    ),
]


def parse_marker_path(path: str) -> tuple[str, bool] | None:
    """``/m/<token>`` gives ``(token, False)``, ``/m/<token>/ws`` gives ``(token, True)``; anything else None."""
    parts = path.split("/")
    if len(parts) == 3 and parts[0] == "" and parts[1] == "m":
        token, is_ws = parts[2], False
    elif len(parts) == 4 and parts[0] == "" and parts[1] == "m" and parts[3] == "ws":
        token, is_ws = parts[2], True
    else:
        return None
    return (token, is_ws) if TOKEN_RE.match(token) else None


class MarkerApp:
    """Pure ASGI application (no framework, so there is no documentation or schema route to forget to turn off)."""

    def __init__(
        self,
        tokens: TokenStore,
        sink: MarkSink,
        clock_us: Callable[[], float],
        max_clients: int = MAX_CLIENTS,
        idle_timeout_s: float = IDLE_TIMEOUT_S,
    ) -> None:
        self.tokens = tokens
        self.sink = sink
        self.clock_us = clock_us
        self.max_clients = max_clients
        self.idle_timeout_s = idle_timeout_s
        self._clients = 0

    # ----------------------------------------------------------------------------------------- dispatch

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        kind = scope["type"]
        if kind == "lifespan":
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif msg["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif kind == "http":
            await self._http(scope, receive, send)
        elif kind == "websocket":
            await self._websocket(scope, receive, send)

    def _authorised(self, scope: dict, want_ws: bool) -> bool:
        parsed = parse_marker_path(scope.get("path", ""))
        token, is_ws = parsed if parsed else ("-", False)
        ok = self.tokens.matches(token)  # always runs, so the work does not depend on the path's shape
        return bool(parsed) and ok and is_ws == want_ws

    async def _http(self, scope: dict, receive: Callable, send: Callable) -> None:
        while True:  # read the (ignored) request body so the connection stays clean
            msg = await receive()
            if msg["type"] != "http.request" or not msg.get("more_body"):
                break
        if scope.get("method") == "GET" and self._authorised(scope, want_ws=False):
            await send({"type": "http.response.start", "status": 200, "headers": PAGE_HEADERS})
            await send({"type": "http.response.body", "body": PAGE_BYTES})
            return
        await send({"type": "http.response.start", "status": 404, "headers": NOT_FOUND_HEADERS})
        await send({"type": "http.response.body", "body": NOT_FOUND_BODY})

    @staticmethod
    def _same_origin(scope: dict) -> bool:
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        origin = headers.get(b"origin")
        if origin is None:
            return True  # not a browser page; the token still has to match
        host = headers.get(b"host", b"").decode("latin-1").lower()
        o = origin.decode("latin-1").lower()
        return o in (f"http://{host}", f"https://{host}")

    async def _deny(self, scope: dict, send: Callable) -> None:
        """Refuse a WebSocket handshake with the same 404 as everything else when the server can, else close."""
        if "websocket.http.response" in scope.get("extensions", {}):
            await send({"type": "websocket.http.response.start", "status": 404, "headers": NOT_FOUND_HEADERS})
            await send({"type": "websocket.http.response.body", "body": NOT_FOUND_BODY})
        else:
            await send({"type": "websocket.close", "code": 1008})

    async def _websocket(self, scope: dict, receive: Callable, send: Callable) -> None:
        first = await receive()  # websocket.connect
        if first["type"] != "websocket.connect":
            return
        if not self._authorised(scope, want_ws=True) or not self._same_origin(scope):
            await self._deny(scope, send)
            return
        if self._clients >= self.max_clients:
            await send({"type": "websocket.close", "code": 1013})
            return
        self._clients += 1
        loop = asyncio.get_running_loop()
        outbox: asyncio.Queue = asyncio.Queue(maxsize=32)

        def push(state: dict) -> None:  # called from recorder threads
            def put() -> None:
                with contextlib.suppress(asyncio.QueueFull):
                    outbox.put_nowait({"op": "state", **state})

            with contextlib.suppress(RuntimeError):  # loop already closed
                loop.call_soon_threadsafe(put)

        self.sink.add_state_listener(push)
        try:
            await send({"type": "websocket.accept"})
            await send({"type": "websocket.send", "text": json.dumps({"op": "state", **self.sink.marker_state()})})
            sender = asyncio.create_task(self._pump(outbox, send))
            try:
                await self._serve(receive, send)
            finally:
                sender.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await sender
        finally:
            self.sink.remove_state_listener(push)
            self._clients -= 1

    @staticmethod
    async def _pump(outbox: asyncio.Queue, send: Callable) -> None:
        while True:
            msg = await outbox.get()
            await send({"type": "websocket.send", "text": json.dumps(msg)})

    async def _serve(self, receive: Callable, send: Callable) -> None:
        window_start = time.monotonic()
        count = 0

        async def reply(obj: dict) -> None:
            await send({"type": "websocket.send", "text": json.dumps(obj)})

        while True:
            try:
                msg = await asyncio.wait_for(receive(), self.idle_timeout_s)
            except asyncio.TimeoutError:
                await send({"type": "websocket.close", "code": 1001})
                return
            stamp = self.clock_us()  # the server's own arrival time: the very first thing after the message
            if msg["type"] == "websocket.disconnect":
                return
            if msg["type"] != "websocket.receive":
                continue
            now = time.monotonic()
            if now - window_start >= 1.0:
                window_start, count = now, 0
            count += 1
            if count > MAX_MESSAGES_PER_S:
                await send({"type": "websocket.close", "code": 1008})
                return
            text = msg.get("text")
            if text is None or len(text) > WS_MAX_BYTES:
                await send({"type": "websocket.close", "code": 1003})
                return
            try:
                req = json.loads(text)
            except ValueError:
                continue
            if not isinstance(req, dict):
                continue
            op = req.get("op")
            if op == "ping":
                pid = req.get("id")
                if isinstance(pid, int) and not isinstance(pid, bool):
                    await reply({"op": "pong", "id": pid})
            elif op == "mark":
                await self._mark(req, stamp, reply)

    async def _mark(self, req: dict, stamp_us: float, reply: Callable) -> None:
        edge, rtt = req.get("edge"), req.get("rtt_ms")
        ok_rtt = isinstance(rtt, (int, float)) and not isinstance(rtt, bool) and 0 <= rtt <= MAX_RTT_MS
        try:
            if edge not in ("start", "end"):
                raise MarkRefused("bad_edge", "edge must be start or end")
            if not ok_rtt:
                raise MarkRefused("rtt_required", f"the round trip must be measured first (0 to {MAX_RTT_MS:g} ms)")
            result = await asyncio.to_thread(self.sink.mark_from_phone, edge, stamp_us, float(rtt))
            await reply({"op": "ack", "ok": True, "edge": edge, **result})
        except MarkRefused as exc:
            await reply({"op": "ack", "ok": False, "edge": edge, "code": exc.code, "error": exc.message})


# --------------------------------------------------------------------------------------------- server


class _DenialNoise(logging.Filter):
    """uvicorn logs an ERROR every time an app refuses a WebSocket handshake with an HTTP response, although the
    client got the 404 and nothing is wrong. A scanner probing the port would fill the console with them."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "returned without completing handshake" not in record.getMessage()


class MarkerServer:
    """Runs a :class:`MarkerApp` on its own uvicorn server and event loop in a background thread."""

    def __init__(self, app: MarkerApp, bind: str = "0.0.0.0", port: int = 0) -> None:
        import uvicorn

        self.app = app
        self.bind = bind
        self._config = uvicorn.Config(
            app,
            host=bind,
            port=port,
            log_level="warning",
            access_log=False,
            lifespan="off",
            ws_max_size=WS_MAX_BYTES,
            server_header=False,
            date_header=False,
            timeout_keep_alive=5,
            limit_concurrency=16,
        )
        self._server = uvicorn.Server(self._config)
        self._thread = threading.Thread(target=self._server.run, name="rzlab-marker", daemon=True)
        self.port = 0

    def start(self, timeout_s: float = 10.0) -> int:
        if not any(isinstance(f, _DenialNoise) for f in logging.getLogger("uvicorn.error").filters):
            logging.getLogger("uvicorn.error").addFilter(_DenialNoise())
        self._thread.start()
        deadline = time.monotonic() + timeout_s
        while not self._server.started and self._thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not self._server.started:
            self.stop()
            raise OSError(f"the marker listener did not start on {self.bind}:{self._config.port}")
        self.port = self._server.servers[0].sockets[0].getsockname()[1]
        return self.port

    def stop(self) -> None:
        """Revoke the token first (so a request that races the shutdown still gets the 404), then close the port."""
        self.app.tokens.revoke()
        self._server.should_exit = True
        self._thread.join(5)
        if self._thread.is_alive():  # a phone holding a WebSocket open: do not wait for it
            self._server.force_exit = True
            self._thread.join(5)


# ------------------------------------------------------------------------------------------- QR code


def qr_svg(url: str) -> str:
    """The QR code of ``url`` as an inline SVG string (pure Python, ``segno``)."""
    import segno

    buf = io.BytesIO()
    segno.make(url, error="m", micro=False).save(buf, kind="svg", scale=8, border=2, xmldecl=False, nl=False)
    return buf.getvalue().decode("utf-8")


def lan_addresses() -> list[str]:
    """This PC's IPv4 addresses a phone on the same network can try, best guess first (no loopback, no link-local)."""
    found: list[str] = []

    def add(ip: str) -> None:
        if ip and not ip.startswith(("127.", "169.254.", "0.")) and ip not in found:
            found.append(ip)

    try:  # the address of the interface that would carry traffic to the LAN; UDP connect sends nothing
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(str(info[4][0]))
    except OSError:
        pass
    return found


WILDCARD_BINDS = ("0.0.0.0", "")  # IPv4 only: an IPv6 bind is refused (config.is_ipv6)
LOOPBACK = "127.0.0.1"


class MarkerHostError(ValueError):
    """A marker address that the listener does not use (or may not be asked to use)."""


def is_wildcard(bind: str) -> bool:
    return bind.strip() in WILDCARD_BINDS


def resolve_bind(bind: str) -> str:
    """``auto`` becomes this PC's first LAN address (the phone's network), or loopback when it has none."""
    if bind.strip().lower() != "auto":
        return bind
    addrs = lan_addresses()
    return addrs[0] if addrs else LOOPBACK


def marker_hosts(configured_bind: str) -> list[str]:
    """The addresses the Record page may offer *before* the recording starts (the listener binds exactly one).

    This PC's LAN addresses, plus the default bind when it is a concrete address that is not among them (loopback
    when the PC has no LAN address), so the list is only empty when the config binds every interface."""
    hosts = lan_addresses()
    default = resolve_bind(configured_bind)
    if not is_wildcard(default) and default not in hosts:
        hosts.append(default)
    return hosts


def choose_bind(configured_bind: str, requested: str | None) -> str:
    """The one address the listener binds: ``requested`` (the start form) if it is a current LAN address, the
    configured address or loopback; otherwise the configured bind (``auto`` = first LAN address).

    Raises :class:`MarkerHostError` for any other ``requested``. ``0.0.0.0`` can only come from the config."""
    if requested is None or requested == "":
        return resolve_bind(configured_bind)
    if host_with_port(requested):
        raise MarkerHostError(f"marker_host: {HOST_WITH_PORT}")
    if is_ipv6(requested):
        raise MarkerHostError(f"marker_host: {IPV6_REFUSED}")
    default = resolve_bind(configured_bind)
    allowed = {*lan_addresses(), LOOPBACK}
    if not is_wildcard(default):
        allowed.add(default)
    if requested not in allowed:
        raise MarkerHostError(
            f"{requested!r} is not an address of this PC that the phone marker can use; choose one of "
            f"{', '.join(sorted(allowed))}."
        )
    return requested


def marker_url(host: str, port: int, token: str) -> str:
    return f"http://{host}:{port}/m/{token}"


def describe_marker(token: str, port: int, bind: str, advertised: str | None, host: str | None = None) -> dict:
    """What the loopback UI shows: the URL (with token), the QR code, and the addresses it may choose from.

    The listener is bound to ``bind``, and the URL always names an address it really listens on. A concrete
    ``bind`` is the only address: ``hosts == [bind]`` and any other ``host`` raises :class:`MarkerHostError`. Only
    when the config bound every interface (``0.0.0.0``) are the PC's LAN addresses offered; then ``host`` (one of
    them) beats ``advertised`` (config ``marker_host``) beats the first guess."""
    if is_wildcard(bind):
        candidates = lan_addresses()
        if advertised and advertised not in candidates:
            candidates.append(advertised)
        if host:
            if host not in candidates:
                raise MarkerHostError(f"{host!r} is not an address of this PC; choose one of {', '.join(candidates)}.")
            chosen = host
        else:
            chosen = advertised or (candidates[0] if candidates else LOOPBACK)
        hosts = candidates
    else:
        if host and host != bind:
            raise MarkerHostError(f"The phone marker listens on {bind} only; {host!r} would not reach it.")
        chosen, hosts = bind, [bind]
    url = marker_url(chosen, port, token)
    return {"host": chosen, "port": port, "url": url, "hosts": hosts, "qr_svg": qr_svg(url)}
