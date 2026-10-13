"""Session start-up shared by ``rzlab tail`` and the recorder: handshake, then a clean START.

PROTOCOL.md section 1, "left-over USB session": the node can't see the PC close the port, so a PC that
reconnects within 5 s lands in the old session, streams still running with an old window. After HELLO the
PC therefore sends ``STOP`` for every stream and waits for its ACK before its first ``START``, and it ignores
STATUS windows until its own START is acknowledged (``SessionMonitor.start_sent``).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .core.monitor import SessionMonitor
from .link.client import LinkClient
from .link.codec import Ack, Auth, Err, Frame, GetInfo, Start, Stop

HANDSHAKE_TIMEOUT_S = 3.0
CLEAN_STOP_TIMEOUT_S = 2.0

FrameHandler = Callable[[list[Frame]], None]


class SessionError(RuntimeError):
    pass


def open_session(
    client: LinkClient,
    mon: SessionMonitor,
    key: bytes | None,
    handle: FrameHandler,
    wall: Callable[[], float] = time.perf_counter,
    timeout_s: float | None = None,
) -> None:
    """Write the opening 0x00 and the session start; return when HELLO and CONFIG have arrived."""
    timeout_s = HANDSHAKE_TIMEOUT_S if timeout_s is None else timeout_s
    client.open_session(Auth(key) if key else GetInfo())
    deadline = wall() + timeout_s
    while (mon.hello is None or mon.config is None) and wall() < deadline:
        handle(client.poll(0.05))
        if mon.errors:
            raise SessionError(f"node refused the session: ERR {mon.errors[0].code} {mon.errors[0].msg}")
    if mon.hello is None or mon.config is None:
        raise SessionError("no HELLO and CONFIG within 3 s; is the node (or `rzlab sim`) running?")


def wait_for_reply(
    client: LinkClient,
    cmd_seq: int,
    handle: FrameHandler,
    wall: Callable[[], float],
    timeout_s: float,
) -> bool:
    """Poll until the ACK or ERR for ``cmd_seq`` arrives; False on timeout."""
    deadline = wall() + timeout_s
    while wall() < deadline:
        frames = client.poll(0.05)
        handle(frames)
        if any(isinstance(f.msg, (Ack, Err)) and f.msg.cmd_seq == cmd_seq for f in frames):
            return True
    return False


def all_streams_mask(mon: SessionMonitor) -> int:
    if mon.hello is None:
        raise SessionError("no HELLO yet")
    mask = 0
    for s in mon.hello.streams:
        mask |= 1 << s.id
    return mask


def clean_stop(
    client: LinkClient,
    mon: SessionMonitor,
    handle: FrameHandler,
    wall: Callable[[], float] = time.perf_counter,
    stop_timeout_s: float | None = None,
) -> bool:
    """STOP every stream and wait for the ACK (PROTOCOL.md section 1, left-over USB session).

    Returns False when the ACK did not arrive in time. The caller must then START with ``force=True``
    (``SessionMonitor.start_sent``): the node's state is unknown, so a stale window shows up as host gap
    instead of being hidden.
    """
    stop_seq = client.send(Stop(all_streams_mask(mon)))
    mon.expect_stop_ack(stop_seq, all_streams_mask(mon))
    return wait_for_reply(
        client, stop_seq, handle, wall, CLEAN_STOP_TIMEOUT_S if stop_timeout_s is None else stop_timeout_s
    )


def begin_recording(
    client: LinkClient,
    mon: SessionMonitor,
    mask: int,
    handle: FrameHandler,
    wall: Callable[[], float] = time.perf_counter,
    stop_timeout_s: float | None = None,
) -> int:
    """STOP everything, wait for the ACK, then START ``mask``. Returns the START's cmd_seq.

    The STOP clears whatever a previous (killed) PC left running. Without its ACK we go on anyway
    (``force=True``): the START's own ACK still arms the accounting, and the report would show the stale
    window as host loss, not hide it.
    """
    if mon.hello is None:
        raise SessionError("begin_recording before HELLO")
    acked = clean_stop(client, mon, handle, wall, stop_timeout_s)
    start_seq = client.send(Start(mask))
    mon.start_sent(start_seq, mask, force=not acked)
    return start_seq
