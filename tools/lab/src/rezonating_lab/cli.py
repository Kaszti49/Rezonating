"""``rzlab`` command line: ``sim`` (simulated node) and ``tail`` (text monitor)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from . import __version__
from .link.transport_tcp import DEFAULT_PORT, parse_host_port


def _prob(text: str) -> float:
    value = float(text)
    if not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return value


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rzlab", description="Rezonating Lab bench tool")
    ap.add_argument("--version", action="version", version=f"rzlab {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    sim = sub.add_parser("sim", help="run a simulated node (TCP, protocol v0)")
    sim.add_argument("--host", default="127.0.0.1")
    sim.add_argument("--port", type=int, default=DEFAULT_PORT)
    sim.add_argument("--auth", action="store_true", help="follow the TCP session rules (AUTH, 2 s timeout)")
    sim.add_argument("--key", default="000102030405060708090a0b0c0d0e0f", help="AUTH key, 32 hex digits")
    sim.add_argument("--seed", type=int, default=1)
    sim.add_argument(
        "--clock-error", type=float, default=0.8, metavar="PERCENT", help="ADC sample clock error in %% (default +0.8)"
    )
    sim.add_argument("--device-drop-rate", type=_prob, default=0.0, metavar="P", help="chance a sample index is lost")
    sim.add_argument("--link-drop-rate", type=_prob, default=0.0, metavar="P", help="chance a DATA packet is dropped")
    sim.add_argument("--corrupt-rate", type=_prob, default=0.0, metavar="P", help="chance a DATA frame is corrupted")
    sim.add_argument("--speed", type=float, default=1.0, help="device time runs this many times faster than wall time")
    sim.add_argument("--truth", type=Path, default=None, metavar="FILE.jsonl", help="write ground-truth events here")

    tail = sub.add_parser("tail", help="start a session, START the streams and print loss and rates every second")
    where = tail.add_mutually_exclusive_group()
    where.add_argument("--tcp", metavar="HOST:PORT", help="TCP node or simulator (default 127.0.0.1:7350)")
    where.add_argument(
        "--serial", metavar="URL", help="serial port or pyserial URL, e.g. COM5 or socket://127.0.0.1:7350"
    )
    tail.add_argument("--key", default=None, help="send AUTH with this key (32 hex digits) instead of GET_INFO")
    tail.add_argument("--streams", default=None, help="comma-separated: adc_raw,adc_dec,accel (default all)")
    tail.add_argument("--duration", type=float, default=None, metavar="SECONDS", help="stop after this long")
    return ap


def _key(text: str) -> bytes:
    try:
        key = bytes.fromhex(text)
    except ValueError:
        key = b""
    if len(key) != 16:
        raise SystemExit("rzlab: the key must be 32 hex digits (16 bytes)")
    return key


def cmd_sim(args: argparse.Namespace) -> int:
    from .sim.faults import FaultConfig
    from .sim.node import SimConfig
    from .sim.server import SimServer

    cfg = SimConfig(
        seed=args.seed,
        auth=args.auth,
        key=_key(args.key),
        speed=args.speed,
        truth_path=args.truth,
        faults=FaultConfig(
            clock_error=args.clock_error / 100.0,
            device_drop_rate=args.device_drop_rate,
            link_drop_rate=args.link_drop_rate,
            corrupt_rate=args.corrupt_rate,
        ),
    )
    server = SimServer(cfg, args.host, args.port)
    rules = "TCP rules (AUTH)" if args.auth else "USB rules (GET_INFO)"

    async def run() -> None:
        await server.start()
        print(
            f"rzlab sim: node {cfg.node_id} on {args.host}:{server.port}, {rules}, speed {args.speed:g}x, "
            f"clock error {args.clock_error:+g} %. Ctrl+C to stop.",
            flush=True,
        )
        try:
            await asyncio.Event().wait()
        finally:
            await server.stop()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("rzlab sim: stopped")
    return 0


def cmd_tail(args: argparse.Namespace) -> int:
    from .link.transport_serial import SerialTransport
    from .link.transport_tcp import TcpTransport
    from .tail import TailError, run_tail, stream_mask

    try:
        mask = stream_mask(args.streams.split(",") if args.streams else None)
        if args.serial:
            transport = SerialTransport(args.serial)
        else:
            host, port = parse_host_port(args.tcp or f"127.0.0.1:{DEFAULT_PORT}")
            transport = TcpTransport(host, port)
    except TailError as exc:
        print(f"rzlab tail: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"rzlab tail: cannot connect: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pyserial raises SerialException for a missing port
        print(f"rzlab tail: cannot open: {exc}", file=sys.stderr)
        return 1
    key = _key(args.key) if args.key else None
    return run_tail(transport, key=key, mask=mask, duration_s=args.duration)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "sim":
        return cmd_sim(args)
    return cmd_tail(args)


if __name__ == "__main__":
    raise SystemExit(main())
