"""``rzlab`` command line: ``sim`` (simulated node), ``tail`` (text monitor), ``serve`` (web server),
``validate`` (check a data root), ``build-ui`` (build the browser UI) and ``soak`` (long-run check of the server)."""

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
    sim.add_argument("--swap-channels", action="store_true", help="fault: ADC ch0 and ch1 swapped")
    sim.add_argument("--no-gravity", action="store_true", help="fault: the ADXL355 z axis shows no 1 g")
    sim.add_argument("--no-adc", action="store_true", help="fault: the ADC never answers (no samples)")
    sim.add_argument(
        "--shorted-inputs", action="store_true", help="bench mode: ADC inputs shorted, channels read only noise"
    )
    sim.add_argument("--speed", type=float, default=1.0, help="device time runs this many times faster than wall time")
    sim.add_argument("--clock-drift-ppm", type=float, default=0.0, help="device clock error against the host clock")
    sim.add_argument(
        "--timestamp-jitter-us", type=float, default=0.0, metavar="US", help="Gaussian noise on DATA and PONG stamps"
    )
    sim.add_argument("--truth", type=Path, default=None, metavar="FILE.jsonl", help="write ground-truth events here")
    sim.add_argument(
        "--walkers", default=None, metavar="P1,P2", help="simulated people walk --protocol (default: generic footsteps)"
    )
    sim.add_argument(
        "--protocol", default="walk-pass-v1", help="protocol the --walkers walk (docs/protocols/<name>.yaml)"
    )
    sim.add_argument(
        "--difficulty", type=_prob, default=0.5, help="0 = walkers far apart .. 1 = all alike (default 0.5)"
    )
    sim.add_argument(
        "--walk-start", type=float, default=10.0, metavar="SECONDS", help="walk starts this long after the ADC starts"
    )

    simds = sub.add_parser("sim-dataset", help="write labelled simulated sessions (recorder layout, no link, fast)")
    simds.add_argument("--out", type=Path, required=True, help="output folder (a data root of simulated sessions)")
    simds.add_argument("--sessions", type=int, required=True)
    simds.add_argument("--persons", required=True, metavar="P1,P2,P3")
    simds.add_argument("--seed", type=int, default=1)
    simds.add_argument("--days", type=int, default=None, help="distinct work days (default: one per session)")
    simds.add_argument("--floors", nargs="+", default=["lab"], help="floor names, used in turn (default: lab)")
    simds.add_argument("--protocol", default="walk-pass-v1")
    simds.add_argument("--difficulty", type=_prob, default=0.5, help="0 = persons far apart .. 1 = all alike")
    simds.add_argument("--passes-scale", type=float, default=1.0, help="scale the passes of every step (quick sets)")
    simds.add_argument("--start", default=None, metavar="YYYY-MM-DD", help="first day (default 2026-11-02)")
    simds.add_argument(
        "--into-data-root",
        action="store_true",
        help="allow --out inside the configured data root (never inside the repository or the sidecar folder)",
    )
    simds.add_argument(
        "--schema", type=Path, default=None, help="schemas/sidecar.schema.json (default: found from the checkout)"
    )

    tail = sub.add_parser("tail", help="start a session, START the streams and print loss and rates every second")
    where = tail.add_mutually_exclusive_group()
    where.add_argument("--tcp", metavar="HOST:PORT", help="TCP node or simulator (default 127.0.0.1:7350)")
    where.add_argument(
        "--serial", metavar="URL", help="serial port or pyserial URL, e.g. COM5 or socket://127.0.0.1:7350"
    )
    tail.add_argument("--key", default=None, help="send AUTH with this key (32 hex digits) instead of GET_INFO")
    tail.add_argument("--streams", default=None, help="comma-separated: adc_raw,adc_dec,accel (default all)")
    tail.add_argument("--duration", type=float, default=None, metavar="SECONDS", help="stop after this long")

    serve = sub.add_parser("serve", help="run the web server (loopback only) for the browser UI")
    serve.add_argument("--host", default="127.0.0.1", help="loopback only: 127.0.0.1, ::1 or localhost")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument(
        "--connect",
        default=None,
        metavar="sim|tcp:HOST:PORT|serial:URL",
        help="connect to a node at start-up (sim = 127.0.0.1:7350)",
    )
    serve.add_argument("--key", default=None, help="pairing key for --connect tcp:... (32 hex digits)")
    serve.add_argument(
        "--dev",
        action="store_true",
        help="also accept the Vite dev server (http://localhost:5173 and http://127.0.0.1:5173) as Host and Origin",
    )
    serve.add_argument(
        "--no-embedded-sim",
        action="store_true",
        help="do not start an in-process simulator when the 'simulator' connection finds none listening",
    )

    val = sub.add_parser(
        "validate", help="check every session folder of a data root (names, sidecars, WAV headers, labels)"
    )
    val.add_argument("root", type=Path, help="the data root, or a folder of sidecars with --sidecars-only")
    val.add_argument("--sidecars-only", action="store_true", help="no WAV files are expected (the repository's data/)")
    val.add_argument(
        "--schema", type=Path, default=None, help="schemas/sidecar.schema.json (default: found from the checkout)"
    )

    imp = sub.add_parser(
        "import-sd",
        help="import session folders from a node's SD card into the data root (validated, never overwriting)",
    )
    imp.add_argument("folder", type=Path, help="the SD card's folder (or one session folder on it)")
    imp.add_argument(
        "--schema", type=Path, default=None, help="schemas/sidecar.schema.json (default: found from the checkout)"
    )

    sub.add_parser("build-ui", help="npm ci + npm run build in tools/lab/web/ (output: src/rezonating_lab/static/)")

    soak = sub.add_parser("soak", help="long-run check: sim at --speed, server, WebSocket client, CPU/RSS/loss report")
    soak.add_argument("--minutes", type=float, default=10.0)
    soak.add_argument("--speed", type=float, default=3.0, help="simulator speed (device time / wall time)")
    soak.add_argument("--sample-period", type=float, default=5.0, metavar="SECONDS", help="CPU/RSS sampling period")
    soak.add_argument("--json", type=Path, default=None, metavar="FILE", help="also write the report as JSON")
    soak.add_argument("--no-ui-load", action="store_true", help="do not poll the view endpoints during the run")
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

    walk_note = ""
    adc_signal = None
    if args.walkers:
        from .recorder.config import find_repo_root
        from .recorder.forms import PSEUDONYM_RE
        from .recorder.protocol import ProtocolError, load_named
        from .sim.people import WalkerAdcSignal

        persons = [p.strip() for p in args.walkers.split(",") if p.strip()]
        if not persons or not all(PSEUDONYM_RE.match(p) for p in persons):
            print("rzlab sim: --walkers takes pseudonyms P1,P2,...", file=sys.stderr)
            return 2
        try:
            plan = load_named(find_repo_root(), args.protocol).expand(persons)
        except ProtocolError as exc:
            print(f"rzlab sim: {exc}", file=sys.stderr)
            return 2
        adc_signal = WalkerAdcSignal.factory(
            persons, plan, seed=args.seed, difficulty=args.difficulty, start_s=args.walk_start
        )
        sched = adc_signal.schedule
        walk_note = (
            f", {','.join(persons)} walk {args.protocol} ({len(sched.passes())} passes, "
            f"{sched.end_s / 60:.1f} device min from ADC start)"
        )
    cfg = SimConfig(
        seed=args.seed,
        auth=args.auth,
        key=_key(args.key),
        speed=args.speed,
        clock_drift_ppm=args.clock_drift_ppm,
        timestamp_jitter_us=args.timestamp_jitter_us,
        truth_path=args.truth,
        faults=FaultConfig(
            clock_error=args.clock_error / 100.0,
            device_drop_rate=args.device_drop_rate,
            link_drop_rate=args.link_drop_rate,
            corrupt_rate=args.corrupt_rate,
            swap_channels=args.swap_channels,
            no_gravity=args.no_gravity,
            no_adc=args.no_adc,
            shorted_inputs=args.shorted_inputs,
        ),
        adc_signal=adc_signal,
    )
    server = SimServer(cfg, args.host, args.port)
    rules = "TCP rules (AUTH)" if args.auth else "USB rules (GET_INFO)"
    rig = [n for n in ("swap_channels", "no_gravity", "no_adc", "shorted_inputs") if getattr(args, n)]

    async def run() -> None:
        await server.start()
        print(
            f"rzlab sim: node {cfg.node_id} on {args.host}:{server.port}, {rules}, speed {args.speed:g}x, "
            f"clock error {args.clock_error:+g} %"
            + (f", {', '.join(r.replace('_', ' ') for r in rig)}" if rig else "")
            + walk_note
            + ". Ctrl+C to stop.",
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


def cmd_sim_dataset(args: argparse.Namespace) -> int:
    from datetime import date

    from .recorder.config import ConfigError, find_repo_root, load_config
    from .recorder.forms import PSEUDONYM_RE
    from .recorder.protocol import ProtocolError, load_named
    from .sim.dataset import DEFAULT_START, DatasetConfig, check_out_dir, generate_dataset

    persons = [p.strip() for p in args.persons.split(",") if p.strip()]
    if not persons or not all(PSEUDONYM_RE.match(p) for p in persons):
        print("rzlab sim-dataset: --persons takes pseudonyms P1,P2,...", file=sys.stderr)
        return 2
    try:
        lab_cfg = load_config()
        repo = find_repo_root()
        check_out_dir(
            args.out,
            repo_root=repo,
            data_root=lab_cfg.data_root,
            sidecar_dir=lab_cfg.sidecar_dir,
            into_data_root=args.into_data_root,
        )
        schema = args.schema or lab_cfg.require_schema()
        protocol = load_named(repo, args.protocol)
        cfg = DatasetConfig(
            sessions=args.sessions,
            persons=persons,
            seed=args.seed,
            days=args.days,
            floors=args.floors,
            difficulty=args.difficulty,
            passes_scale=args.passes_scale,
            start=date.fromisoformat(args.start) if args.start else DEFAULT_START,
        )
        results = generate_dataset(cfg, protocol, args.out, Path(schema))
    except ConfigError as exc:
        print(f"rzlab sim-dataset: {exc.message}", file=sys.stderr)
        return 2
    except (ProtocolError, ValueError, FileExistsError) as exc:
        print(f"rzlab sim-dataset: {exc}", file=sys.stderr)
        return 2
    for r in results:
        print(
            f"ok   {r.name}  {r.duration_s / 60:.1f} min, {r.n_passes} passes, {r.n_steps} steps, "
            f"adc {r.adc_rate_hz:.2f} Hz, persons {','.join(r.persons)}"
        )
    print(f"rzlab sim-dataset: {len(results)} simulated session(s) in {args.out} (ground truth: <session>.truth.jsonl)")
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


def cmd_serve(args: argparse.Namespace) -> int:
    from .server.app import create_app
    from .server.device import DeviceError, parse_connect_arg
    from .server.security import DEV_SERVER_PORTS, check_bind_host

    try:
        host = check_bind_host(args.host)
    except ValueError as exc:
        print(f"rzlab serve: {exc}", file=sys.stderr)
        return 2
    spec = None
    if args.connect:
        try:
            spec = parse_connect_arg(args.connect)
            if args.key:
                spec.key = _key(args.key)
            spec.validate()
        except (ValueError, DeviceError) as exc:
            print(f"rzlab serve: {exc}", file=sys.stderr)
            return 2
    import uvicorn

    from .recorder.config import ConfigError, load_config

    try:
        lab_config = load_config()
    except ConfigError as exc:
        print(f"rzlab serve: {exc.message}", file=sys.stderr)
        return 2
    app = create_app(
        port=args.port,
        initial_connect=spec,
        embedded_sim=not args.no_embedded_sim,
        dev_ports=DEV_SERVER_PORTS if args.dev else (),
        lab_config=lab_config,
    )
    shown = f"[{host}]" if ":" in host else host
    dev_note = "; Vite dev server on 5173 allowed (--dev)" if args.dev else ""
    print(f"rzlab serve: http://{shown}:{args.port}/  (loopback only{dev_note}; Ctrl+C to stop)", flush=True)
    try:
        uvicorn.run(app, host=host, port=args.port, log_level="warning", access_log=False)
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print(f"rzlab serve: cannot listen on {host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from .recorder.config import ConfigError, find_repo_root, load_config
    from .recorder.validate import run_validate

    try:
        schema = args.schema or load_config().require_schema()
    except ConfigError as exc:
        print(f"rzlab validate: {exc.message}", file=sys.stderr)
        return 2
    return run_validate(args.root, Path(schema), sidecars_only=args.sidecars_only, repo_root=find_repo_root())


def cmd_import_sd(args: argparse.Namespace) -> int:
    from .recorder.config import ConfigError, check_data_root, load_config
    from .recorder.sdimport import run_import

    try:
        cfg = load_config()
        schema = args.schema or cfg.require_schema()
    except ConfigError as exc:
        print(f"rzlab import-sd: {exc.message}", file=sys.stderr)
        return 2
    st = check_data_root(cfg, probe_write=True)
    if not st.ok or cfg.data_root is None:
        print(f"rzlab import-sd: {st.message}", file=sys.stderr)
        return 2
    return run_import(
        args.folder,
        cfg.data_root,
        cfg.staging_dir,
        Path(schema),
        cfg.sidecar_dir,
        copy_sim=cfg.copy_sim_sidecars,
        repo_root=cfg.repo_root,
    )


def cmd_build_ui(_args: argparse.Namespace) -> int:
    from .buildui import build_ui

    return build_ui()


def cmd_soak(args: argparse.Namespace) -> int:
    from .soak import run_soak

    return run_soak(args.minutes, args.speed, args.sample_period, args.json, ui_load=not args.no_ui_load)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "sim":
        return cmd_sim(args)
    if args.command == "sim-dataset":
        return cmd_sim_dataset(args)
    if args.command == "serve":
        return cmd_serve(args)
    if args.command == "validate":
        return cmd_validate(args)
    if args.command == "import-sd":
        return cmd_import_sd(args)
    if args.command == "build-ui":
        return cmd_build_ui(args)
    if args.command == "soak":
        return cmd_soak(args)
    return cmd_tail(args)


if __name__ == "__main__":
    raise SystemExit(main())
