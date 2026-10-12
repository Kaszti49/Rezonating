# Rezonating Lab (phase 1)

Bench tool for the node link: protocol v0 codec, a simulated node and a text monitor.
Spec: `PROTOCOL.md`. Golden vectors for the firmware: `tests/vectors/link-v0.json`.

## Install

```bash
pip install -e "tools/lab[dev]"      # gives the `rzlab` command; Python 3.10+, numpy, pyserial
python -m pytest -q tools/lab/tests
```

## Run

```bash
rzlab sim                       # simulated node on 127.0.0.1:7350 (USB session rules)
rzlab sim --auth --speed 3 --corrupt-rate 0.02 --truth truth.jsonl
rzlab tail                      # connects to 127.0.0.1:7350, STARTs all streams, one line per second per stream
rzlab tail --serial COM5        # a real node; also --serial socket://127.0.0.1:7350 or --tcp HOST:PORT [--key HEX]
```

`rzlab sim` options: `--clock-error PERCENT` (default +0.8), `--device-drop-rate P` (per sample),
`--link-drop-rate P` (per DATA packet), `--corrupt-rate P` (per DATA frame, flips a byte on the wire),
`--speed X`, `--seed N`, `--truth FILE.jsonl` (ground-truth footstep times).

`rzlab tail` prints measured rate (from STATUS and from its own `t_dev_us` fit) with the offset against
nominal, then received / dev / link / gap (host gap) / bad_frames / lost_frames. Ctrl+C sends STOP and
prints the final per-stream loss summary.

Regenerate the vectors after a protocol change: `python -m rezonating_lab.link.vectors --write`.
`adc_dec` in the simulator is a placeholder (every 2nd raw sample, no FIR).
