"""Generate vectors_gen.h for the bring-up firmware's host test from the shared golden vectors.

Reads (never writes) tools/lab/tests/vectors/link-v0.json and ml/tests/vectors/decimator_fir.json and emits C that
calls the firmware's portable codec (main/rz_link.c) and decimator (main/rz_decim.c) with the decoded fields and
compares the bytes and values. Usage: python gen_vectors.py <repo root> <out .h>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def cbytes(b: bytes) -> str:
    if not b:
        return "NULL"
    return "(const uint8_t[]){" + ",".join(str(x) for x in b) + "}"


def cstr(s: str) -> str:
    return '"' + "".join(f"\\{x:03o}" for x in s.encode("utf-8")) + '"'


def u64(v: int) -> str:
    return f"UINT64_C({v})"


def f32(v: float) -> str:
    return f"(float){v!r}"


NODE_ENCODERS = {"HELLO", "CONFIG", "DATA", "STATUS", "ACK", "ERR", "PONG"}


def enc_call(ftype: str, f: dict) -> str:
    """C statements that encode ``f`` into writer ``w``."""
    if ftype == "HELLO":
        st = ",".join(
            f"{{{s['id']},{s['n_ch']},{s['nominal_hz']},{s['bits']},{s['clock']},{s['fir_taps']},{s['fir_delay']}}}"
            for s in f["streams"]
        )
        hd = ",".join(
            f"{{{h['port']},{cbytes(bytes.fromhex(h['descriptor']))},{len(bytes.fromhex(h['descriptor']))}}}"
            for h in f["heads"]
        )
        return (
            f"rzl_stream_info_t st[] = {{{st or '{0}'}}}; rzl_head_info_t hd[] = {{{hd or '{0}'}}};\n"
            f"rzl_enc_hello(&w, {f['proto']}, {cstr(f['fw_version'])}, {cstr(f['node_id'])}, {u64(f['t_dev_us'])}, "
            f"st, {len(f['streams'])}, hd, {len(f['heads'])});"
        )
    if ftype == "CONFIG":
        lines, cfgs = [], []
        for i, s in enumerate(f["streams"]):
            ch = s["channels"]
            lines.append(
                f"static const uint8_t g{i}[] = {{{','.join(str(c['gain']) for c in ch)}}};"
                f" static const float s{i}[] = {{{','.join(f32(c['scale']) for c in ch)}}};"
                f" static const uint8_t u{i}[] = {{{','.join(str(c['units']) for c in ch)}}};"
            )
            cfgs.append(f"{{{s['id']},{len(ch)},g{i},s{i},u{i}}}")
        lines.append(f"rzl_stream_cfg_t cf[] = {{{','.join(cfgs)}}};")
        lines.append(
            f"rzl_enc_config(&w, cf, {len(cfgs)}, {f['accel_range_g']}, {f['status_period_ms']});"
        )
        return "\n".join(lines)
    if ftype == "DATA":
        smp = [v for row in f["samples"] for v in row]
        n, nch = len(f["samples"]), len(f["samples"][0])
        return (
            f"static const int32_t smp[] = {{{','.join(str(v) for v in smp)}}};\n"
            f"rzl_enc_data(&w, {f['stream']}, {nch}, {n}, {u64(f['first_sample'])}, {u64(f['t_dev_us'])}, smp);"
        )
    if ftype == "STATUS":
        ss = ",".join(
            f"{{{s['id']},{s['running']},{u64(s['produced'])},{u64(s['device_dropped'])},{s['rate_mhz']},"
            f"{s['clipped']},{u64(s['win_first'])},{u64(s['win_end'])},{u64(s['win_device'])},{u64(s['win_link'])}}}"
            for s in f["streams"]
        )
        return (
            f"rzl_status_hdr_t h = {{{u64(f['t_dev_us'])},{f['queue_fill']},{f['sd_state']},{f['sd_free_mb']},"
            f"{f['rssi_dbm']},{f['heap_free']},{f['temp_c_x10']}}};\n"
            f"rzl_stream_status_t ss[] = {{{ss}}};\n"
            f"rzl_enc_status(&w, &h, ss, {len(f['streams'])});"
        )
    if ftype == "ACK":
        return f"rzl_enc_ack(&w, {f['cmd_seq']});"
    if ftype == "ERR":
        return f"rzl_enc_err(&w, {f['cmd_seq']}, {f['code']}, {cstr(f['msg'])});"
    if ftype == "PONG":
        return f"rzl_enc_pong(&w, {u64(f['host_t_us'])}, {u64(f['t_dev_us'])});"
    raise ValueError(ftype)


def pc_parse_checks(ftype: str, f: dict) -> str:
    """C checks on the payload ``fr`` that the receiver delivered for a PC -> node frame."""
    if ftype in ("START", "STOP"):
        return f'CHECK(fr.len >= 1 && fr.payload[0] == {f["stream_mask"]}, "mask");'
    if ftype == "PING":
        return (
            "{ rzl_r_t r; rzl_r_init(&r, fr.payload, fr.len); "
            f'CHECK(rzl_get_u64(&r) == {u64(f["host_t_us"])} && !r.short_, "host_t_us"); }}'
        )
    if ftype == "SET":
        key = f["key"].encode()
        t = {"i32": 0, "f32": 1, "str8": 2, "blob16": 3}[f["type"]]
        out = (
            "{ rzl_set_t s; CHECK(rzl_parse_set(fr.payload, fr.len, &s), \"parse\"); "
            f'CHECK(s.key_len == {len(key)} && memcmp(s.key, {cbytes(key)}, {len(key)}) == 0, "key"); '
            f'CHECK(s.type == {t}, "type"); '
        )
        if t == 0:
            out += f'CHECK(s.i32 == {f["value"]}, "i32"); '
        elif t == 1:
            out += f'CHECK(s.f32 == {f32(f["value"])}, "f32"); '
        else:
            vb = f["value"].encode() if t == 2 else bytes.fromhex(f["value"])
            out += f'CHECK(s.bytes_len == {len(vb)} && memcmp(s.bytes, {cbytes(vb)}, {len(vb)}) == 0, "value"); '
            if t == 3:
                pass
        # every shorter prefix of the payload must be rejected as ERR 2 (bad payload)
        out += (
            'for (size_t k = 0; k < fr.len; k++) { rzl_set_t s2; '
            'CHECK(!rzl_parse_set(fr.payload, k, &s2), "short SET payload accepted"); } }'
        )
        return out
    return ""


def main() -> int:
    root = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    link = json.loads((root / "tools/lab/tests/vectors/link-v0.json").read_text(encoding="utf-8"))
    dec = json.loads((root / "ml/tests/vectors/decimator_fir.json").read_text(encoding="utf-8"))
    o: list[str] = ["/* Generated by gen_vectors.py from link-v0.json and decimator_fir.json. Do not edit. */"]

    o.append("static void gen_link(void) {")
    o.append('{ const char *case_name = "crc16 check value"; CHECK(rzl_crc16((const uint8_t *)"123456789", 9) == 0x29B1, "crc"); }')
    for c in link["cases"]:
        name = c["name"]
        o.append(f"{{ const char *case_name = {cstr(name)}; (void)case_name; tests_run++;")
        if c["kind"] == "cobs":
            raw = bytes.fromhex(c["raw_hex"])
            enc = bytes.fromhex(c["encoded_hex"])
            o.append(f"static const uint8_t raw[] = {{{','.join(str(x) for x in raw)}}};")
            o.append(f"static const uint8_t enc[] = {{{','.join(str(x) for x in enc)}}};")
            o.append("size_t n = rzl_cobs_encode(raw, sizeof raw, g_wire);")
            o.append('check_bytes(case_name, "encode", g_wire, n, enc, sizeof enc);')
            o.append("int d = rzl_cobs_decode(enc, sizeof enc, g_raw, sizeof g_raw);")
            o.append('check_bytes(case_name, "decode", g_raw, d < 0 ? 0 : (size_t)d, raw, sizeof raw);')
        elif c["kind"] == "frame":
            raw = bytes.fromhex(c["raw_hex"])
            wire = bytes.fromhex(c["wire_hex"])
            ftype, seq, tid = c["frame_type"], c["seq"], c["type_id"]
            o.append(f"static const uint8_t raw[] = {{{','.join(str(x) for x in raw)}}};")
            o.append(f"static const uint8_t wire[] = {{{','.join(str(x) for x in wire)}}};")
            # 1. header + CRC + COBS around the vector's payload
            o.append("memcpy(g_raw, raw, sizeof raw);")
            o.append(f"size_t n = rzl_finish(g_raw, sizeof raw - 6, {tid}, {seq}, g_wire);")
            o.append('check_bytes(case_name, "finish", g_wire, n, wire, sizeof wire);')
            # 2. the typed encoder from the decoded fields
            if ftype in NODE_ENCODERS:
                o.append("{ rzl_w_t w; rzl_payload_w(&w, g_raw, sizeof g_raw);")
                o.append(enc_call(ftype, c["fields"]))
                o.append('CHECK(!w.overflow, "writer overflow");')
                o.append(f"size_t m = rzl_finish(g_raw, w.n, {tid}, {seq}, g_wire);")
                o.append('check_bytes(case_name, "typed encoder", g_wire, m, wire, sizeof wire); }')
            # 3. the receiver, byte by byte and in one piece
            o.append("for (int piece = 0; piece < 2; piece++) { rzl_rx_init(&g_rx); rzl_frame_t fr; int got_n = 0;")
            o.append("size_t step = piece ? sizeof wire : 1; size_t pos = 0;")
            o.append("while (pos < sizeof wire) { size_t len = (sizeof wire - pos < step) ? sizeof wire - pos : step;")
            o.append("size_t used = 0; while (used < len) { bool got; used += rzl_rx_feed(&g_rx, wire + pos + used, len - used, &fr, &got);")
            o.append("if (got) { got_n++;")
            o.append(f'CHECK(fr.type == {tid} && fr.seq == {seq}, "rx header");')
            o.append('check_bytes(case_name, "rx payload", fr.payload, fr.len, raw + 4, sizeof raw - 6);')
            if tid >= 0x81:
                o.append(pc_parse_checks(ftype, c["fields"]))
            o.append("} } pos += len; }")
            o.append('CHECK(got_n == 1 && g_rx.bad_frames == 0, "rx count"); }')
        elif c["kind"] == "stream":
            wire = bytes.fromhex(c["wire_hex"])
            exp = c["expect"]
            n_frames = len(exp["frames"]) + exp.get("unknown_types", 0)
            seqs = [fr["seq"] for fr in exp["frames"]] if exp.get("unknown_types", 0) == 0 else []
            o.append(f"static const uint8_t wire[] = {{{','.join(str(x) for x in wire)}}};")
            if seqs:
                o.append(f"static const int seqs[] = {{{','.join(str(s) for s in seqs)}}};")
            o.append("for (int piece = 0; piece < 3; piece++) { rzl_rx_init(&g_rx); rzl_frame_t fr; int got_n = 0;")
            o.append("size_t step = piece == 0 ? 1 : piece == 1 ? 7 : sizeof wire; size_t pos = 0;")
            o.append("while (pos < sizeof wire) { size_t len = (sizeof wire - pos < step) ? sizeof wire - pos : step;")
            o.append("size_t used = 0; while (used < len) { bool got; used += rzl_rx_feed(&g_rx, wire + pos + used, len - used, &fr, &got);")
            if seqs:
                o.append(f'if (got) {{ CHECK(got_n < {len(seqs)} && fr.seq == seqs[got_n], "stream seq"); got_n++; }} }} pos += len; }}')
            else:
                o.append("if (got) got_n++; } pos += len; }")
            o.append(
                f'CHECK(got_n == {n_frames} && g_rx.bad_frames == {exp["bad_frames"]}, "stream frames/bad_frames"); }}'
            )
        o.append("}")
    o.append("}")

    # Decimator
    x = dec["input"]
    o.append(f"#define DEC_N {len(x)}")
    o.append(f"#define DEC_M {len(dec['expected'])}")
    o.append(f"static const int32_t dec_in[DEC_N] = {{{','.join(str(int(v)) for v in x)}}};")
    o.append(f"static const unsigned char dec_valid[DEC_N] = {{{','.join('1' if v else '0' for v in dec['valid'])}}};")
    o.append(f"static const float dec_exp[DEC_M] = {{{','.join(repr(float(v)) + 'f' for v in dec['expected'])}}};")
    o.append(
        f"static const unsigned char dec_exp_valid[DEC_M] = {{{','.join('1' if v else '0' for v in dec['expected_valid'])}}};"
    )
    o.append(f"static const int32_t dec_exp_codes[DEC_M] = {{{','.join(str(v) for v in dec['expected_codes'])}}};")
    tol = dec["tolerance"]
    o.append(f"#define DEC_TOL_ABS {tol['abs']!r}")
    o.append(f"#define DEC_TOL_CODES {tol['codes_abs']}")
    # CONFIG scale as the simulator computes it: float32(1.2 / gain / 2^23) (sim/node.py build_config)
    import numpy as np

    scales = [repr(float(np.float32(1.2 / g / 8388608))) for g in (1, 2, 4, 8, 16, 32, 64, 128)]
    o.append(f"static const float cfg_scale_py[8] = {{{','.join(s + 'f' for s in scales)}}};")
    out_path.write_text("\n".join(o) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
