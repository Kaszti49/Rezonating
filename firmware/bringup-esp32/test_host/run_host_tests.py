"""Build and run the bring-up firmware's host test (link codec + decimator against the shared vectors, DRDY edge
classifier against its own cases and a reader simulation).

    python firmware/bringup-esp32/test_host/run_host_tests.py

Generates build/vectors_gen.h from the JSON vectors, compiles test_main.c with ../main/rz_link.c, ../main/rz_decim.c
and ../main/rz_drdy.c using the host C compiler, runs it and returns its exit code. Compiler: $CC (gcc/clang style) if set, else MSVC found
through vswhere / the Visual Studio 2022 vcvars64.bat. Floating point is compiled without contraction
(-ffp-contract=off, or /fp:precise which never contracts on MSVC x64 unless /fp:contract is given), as dsp.py requires.
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN = HERE.parent / "main"
ROOT = HERE.parents[2]
BUILD = HERE / "build"


def find_vcvars() -> str | None:
    pats = [
        r"C:\Program Files\Microsoft Visual Studio\*\*\VC\Auxiliary\Build\vcvars64.bat",
        r"C:\Program Files (x86)\Microsoft Visual Studio\*\*\VC\Auxiliary\Build\vcvars64.bat",
    ]
    for p in pats:
        hits = sorted(glob.glob(p))
        if hits:
            return hits[-1]
    return None


def main() -> int:
    BUILD.mkdir(exist_ok=True)
    gen = BUILD / "vectors_gen.h"
    subprocess.run([sys.executable, str(HERE / "gen_vectors.py"), str(ROOT), str(gen)], check=True)
    srcs = [str(HERE / "test_main.c"), str(MAIN / "rz_link.c"), str(MAIN / "rz_decim.c"), str(MAIN / "rz_drdy.c")]
    exe = BUILD / ("test_host.exe" if os.name == "nt" else "test_host")
    cc = os.environ.get("CC")
    if cc:
        cmd = [cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-ffp-contract=off", f"-I{MAIN}", f"-I{BUILD}", *srcs]
        cmd += ["-o", str(exe), "-lm"]
        subprocess.run(cmd, check=True)
    else:
        vcvars = find_vcvars()
        if vcvars is None:
            print("no host C compiler: set CC or install Visual Studio C++ build tools")
            return 2
        bat = BUILD / "build_msvc.bat"
        bat.write_text(
            "@echo off\r\n"
            f'call "{vcvars}" >nul || exit /b 1\r\n'
            f'cl /nologo /std:c11 /O2 /W3 /fp:precise /I"{MAIN}" /I"{BUILD}" '
            + " ".join(f'"{s}"' for s in srcs)
            + f' /Fo"{BUILD}\\\\" /Fe"{exe}"\r\n',
            encoding="ascii",
        )
        subprocess.run(["cmd", "/d", "/c", str(bat)], check=True)
    return subprocess.run([str(exe)]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
