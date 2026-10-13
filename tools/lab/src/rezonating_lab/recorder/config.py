"""Where recordings go: the data root, local staging, the repo's ``data/`` for validated sidecars.

Settings come from environment variables (they win) and from ``config.toml`` in the user's config folder
(``%APPDATA%\\rzlab\\config.toml`` on Windows)::

    data_root = "D:\\\\rezonating-recordings"     # the shared drive; never inside the git repo (D-017)
    staging_dir = "C:\\\\Users\\\\me\\\\AppData\\\\Local\\\\rzlab\\\\staging"   # optional
    sidecar_dir = "C:\\\\work\\\\Rezonating\\\\data"                        # optional: where validated sidecars are copied
    marker_port = 8766                                          # optional: phone marker port (0 = any free port)

``RZ_DATA_ROOT``, ``RZ_STAGING_DIR``, ``RZ_SIDECAR_DIR``, ``RZ_MARKER_PORT``, ``RZ_MARKER_HOST`` (the address put
in the QR code), ``RZ_MARKER_BIND`` (the interface the marker listens on), ``RZ_COPY_SIM_SIDECARS``,
``RZ_REPO_ROOT``, ``RZ_SCHEMA`` and ``RZ_CONFIG`` (path of the config file) override the file.

``RZ_MARKER_BIND`` defaults to ``auto``: the phone marker listens on one address, this PC's first LAN address unless the
start request names another (``marker_host``), never on every interface (a public Wi-Fi at a site would reach it).
Set ``0.0.0.0`` to listen everywhere, on purpose. ``RZ_MARKER_HOST`` only matters then.

The staging folder holds the WAV files while they are written, so it must not be inside the repository either
(:func:`check_staging_dir`). ``sidecar_dir`` is meant to lie in the repository (``data/``): only validated ``.json``
sidecars are ever copied there.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    import tomli as tomllib

SCHEMA_REL = Path("schemas") / "sidecar.schema.json"


class ConfigError(Exception):
    """A setting the recorder cannot use. ``code`` is the API error code, ``message`` is fit for a toast."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def find_repo_root(start: Path | None = None, env: Mapping[str, str] | None = None) -> Path | None:
    """The repository checkout: ``RZ_REPO_ROOT``, else the first parent of this file with ``schemas/sidecar.schema.json``."""
    env = os.environ if env is None else env
    if env.get("RZ_REPO_ROOT"):
        return Path(env["RZ_REPO_ROOT"]).resolve()
    here = (start or Path(__file__)).resolve()
    for folder in here.parents:
        if (folder / SCHEMA_REL).is_file():
            return folder
    return None


def default_config_path(env: Mapping[str, str]) -> Path:
    if env.get("RZ_CONFIG"):
        return Path(env["RZ_CONFIG"])
    if os.name == "nt":
        base = env.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "rzlab" / "config.toml"


def default_staging_dir(env: Mapping[str, str]) -> Path:
    if os.name == "nt":
        base = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "rzlab" / "staging"


def is_inside(path: Path, root: Path) -> bool:
    """True when ``path`` is ``root`` or lies below it. Follows links and short names through ``samefile``,
    and also works for a ``path`` that does not exist yet (its nearest existing parent decides)."""
    for p in (path, *path.parents):
        try:
            if p.exists() and os.path.samefile(p, root):
                return True
        except OSError:
            continue
    return False


@dataclass
class LabConfig:
    data_root: Path | None = None
    data_root_source: str | None = None  # "env" | "config" | None
    staging_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "rzlab-staging")
    sidecar_dir: Path | None = None  # where validated sidecars are copied (<dir>/<session>/); None = do not copy
    copy_sim_sidecars: bool = False  # simulated sessions are not copied to the repo's data/ unless asked
    marker_bind: str = "auto"  # "auto": the first LAN address; an address; or 0.0.0.0 for every interface
    marker_port: int = 0
    marker_host: str | None = None  # address put into the QR code; None = detect
    repo_root: Path | None = None
    schema_path: Path | None = None
    config_path: Path | None = None

    def require_schema(self) -> Path:
        if self.schema_path is None or not self.schema_path.is_file():
            raise ConfigError(
                "no_schema",
                "schemas/sidecar.schema.json was not found. Run rzlab from a checkout of the repository "
                "or set RZ_REPO_ROOT (or RZ_SCHEMA) to it.",
            )
        return self.schema_path


def _truthy(text: str | None) -> bool:
    return (text or "").strip().lower() in ("1", "true", "yes", "on")


def load_config(env: Mapping[str, str] | None = None) -> LabConfig:
    """Read the settings. Never touches the data root itself (see :func:`check_data_root`)."""
    env = dict(os.environ if env is None else env)
    cfg_path = default_config_path(env)
    file_cfg: dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            file_cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError("bad_config", f"cannot read {cfg_path}: {exc}") from exc
    repo = find_repo_root(env=env)

    def pick(env_key: str, file_key: str) -> tuple[str | None, str | None]:
        if env.get(env_key, "").strip():
            return env[env_key].strip(), "env"
        v = file_cfg.get(file_key)
        return (str(v), "config") if v not in (None, "") else (None, None)

    root_text, root_src = pick("RZ_DATA_ROOT", "data_root")
    staging_text, _ = pick("RZ_STAGING_DIR", "staging_dir")
    sidecar_text, _ = pick("RZ_SIDECAR_DIR", "sidecar_dir")
    port_text, _ = pick("RZ_MARKER_PORT", "marker_port")
    host_text, _ = pick("RZ_MARKER_HOST", "marker_host")
    bind_text, _ = pick("RZ_MARKER_BIND", "marker_bind")
    copy_sim = _truthy(env.get("RZ_COPY_SIM_SIDECARS")) or bool(file_cfg.get("copy_sim_sidecars", False))
    try:
        marker_port = int(port_text) if port_text else 0
    except ValueError as exc:
        raise ConfigError("bad_config", f"marker_port must be a number, got {port_text!r}") from exc
    if not 0 <= marker_port <= 65535:
        raise ConfigError("bad_config", "marker_port must be between 0 and 65535")
    schema = Path(env["RZ_SCHEMA"]) if env.get("RZ_SCHEMA") else (repo / SCHEMA_REL if repo else None)
    if sidecar_text:
        sidecar_dir: Path | None = Path(sidecar_text)
    else:
        sidecar_dir = (repo / "data") if repo else None
    return LabConfig(
        data_root=Path(root_text) if root_text else None,
        data_root_source=root_src,
        staging_dir=Path(staging_text) if staging_text else default_staging_dir(env),
        sidecar_dir=sidecar_dir,
        copy_sim_sidecars=copy_sim,
        marker_bind=bind_text or "auto",
        marker_port=marker_port,
        marker_host=host_text,
        repo_root=repo,
        schema_path=schema,
        config_path=cfg_path,
    )


@dataclass
class DataRootStatus:
    configured: bool
    ok: bool
    path: str | None
    source: str | None
    config_file: str | None
    error_code: str | None = None
    message: str | None = None
    free_gb: float | None = None

    def to_dict(self) -> dict:
        return {
            "configured": self.configured,
            "ok": self.ok,
            "path": self.path,
            "source": self.source,
            "config_file": self.config_file,
            "free_gb": self.free_gb,
            "error": None if self.ok else {"code": self.error_code, "message": self.message},
        }


def check_data_root(cfg: LabConfig, probe_write: bool = True) -> DataRootStatus:
    """Is the data root usable? Never creates it: a mistyped shared-drive path must not make a new folder."""
    cfg_file = str(cfg.config_path) if cfg.config_path else None
    if cfg.data_root is None:
        example = 'data_root = "D:\\\\rezonating-recordings"'
        return DataRootStatus(
            False,
            False,
            None,
            None,
            cfg_file,
            "no_data_root",
            "No data root is configured. Choose a folder on the shared drive and set it here, or set the "
            f"RZ_DATA_ROOT environment variable, or add {example} to {cfg_file}.",
        )
    path = cfg.data_root

    def bad(code: str, message: str) -> DataRootStatus:
        return DataRootStatus(True, False, str(path), cfg.data_root_source, cfg_file, code, message)

    if not path.is_absolute():
        return bad("data_root_relative", f"The data root must be a full path, not {str(path)!r}.")
    if cfg.repo_root is not None and is_inside(path, cfg.repo_root):
        return bad(
            "data_root_in_repo",
            f"The data root {str(path)!r} is inside the git repository. Recordings must never go into git (D-017): "
            "choose a folder outside the repository.",
        )
    if not path.is_dir():
        return bad("data_root_missing", f"The data root {str(path)!r} does not exist or is not a folder.")
    if probe_write:
        try:
            fd, tmp = tempfile.mkstemp(prefix=".rzlab-write-test-", dir=path)
            os.close(fd)
            os.unlink(tmp)
        except OSError as exc:
            return bad("data_root_not_writable", f"Cannot write to the data root {str(path)!r}: {exc}")
    try:
        import shutil

        free = round(shutil.disk_usage(path).free / 1e9, 1)
    except OSError:
        free = None
    return DataRootStatus(True, True, str(path), cfg.data_root_source, cfg_file, free_gb=free)


def check_staging_dir(cfg: LabConfig) -> DataRootStatus | None:
    """None when the staging folder is fine; otherwise a status with the error (WAV files must never land in git)."""
    path = cfg.staging_dir
    if not path.is_absolute():
        return DataRootStatus(
            True,
            False,
            str(path),
            None,
            None,
            "staging_relative",
            f"The staging folder must be a full path, not {str(path)!r}.",
        )
    if cfg.repo_root is not None and is_inside(path, cfg.repo_root):
        return DataRootStatus(
            True,
            False,
            str(path),
            None,
            None,
            "staging_in_repo",
            f"The staging folder {str(path)!r} is inside the git repository, and WAV files are written there. "
            "Set RZ_STAGING_DIR (or staging_dir in the config file) to a folder outside the repository.",
        )
    return None


def save_data_root(cfg: LabConfig, path_text: str) -> None:
    """Write ``data_root`` into ``config.toml`` (other keys are kept), and update ``cfg``.

    Refuses a path that is not usable (relative, inside the repo, missing, not writable) before writing anything.
    """
    probe = LabConfig(
        data_root=Path(path_text), data_root_source="config", repo_root=cfg.repo_root, config_path=cfg.config_path
    )
    status = check_data_root(probe)
    if not status.ok:
        raise ConfigError(status.error_code or "bad_data_root", status.message or "unusable data root")
    if cfg.config_path is None:
        raise ConfigError("bad_config", "no config file location is known")
    existing: dict[str, Any] = {}
    if cfg.config_path.is_file():
        try:
            existing = tomllib.loads(cfg.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError("bad_config", f"cannot read {cfg.config_path}: {exc}") from exc
    existing["data_root"] = str(Path(path_text))
    lines = []
    for k, v in existing.items():
        if isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
        else:
            lines.append(f"{k} = {json.dumps(str(v))}")  # JSON string escapes are valid TOML basic strings
    cfg.config_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cfg.data_root = Path(path_text)
    cfg.data_root_source = "config"
