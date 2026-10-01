#!/usr/bin/env python3
"""Validate Rezonating JSON files against the Tier 1 schemas.

Checks:
  - every schema in schemas/ is itself a valid JSON Schema
  - schemas/examples/<schema-name>.<anything>.json against its schema
  - packs/*/pack.json against the pack manifest schema
  - data/**/*.json sidecars against the sidecar schema

Exit code 0 = all valid, 1 = at least one problem.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def validator_for(name: str) -> Draft202012Validator:
    schema = load(SCHEMAS / f"{name}.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def check(v: Draft202012Validator, path: Path) -> list[str]:
    try:
        doc = load(path)
    except json.JSONDecodeError as e:
        return [f"{path.relative_to(ROOT)}: invalid JSON: {e}"]
    return [
        f"{path.relative_to(ROOT)}: {'/'.join(map(str, err.absolute_path)) or '(root)'}: {err.message}"
        for err in sorted(v.iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]


def main() -> int:
    errors: list[str] = []
    checked = 0
    names = [p.name.removesuffix(".schema.json") for p in SCHEMAS.glob("*.schema.json")]
    validators = {n: validator_for(n) for n in names}

    for ex in sorted((SCHEMAS / "examples").glob("*.json")):
        name = ex.name.split(".")[0]
        if name not in validators:
            errors.append(f"{ex.relative_to(ROOT)}: no schema named '{name}'")
            continue
        errors += check(validators[name], ex)
        checked += 1

    for pack in sorted((ROOT / "packs").glob("*/pack.json")):
        errs = check(validators["pack-manifest"], pack)
        doc = load(pack)
        if doc.get("id") != pack.parent.name:
            errs.append(f"{pack.relative_to(ROOT)}: id '{doc.get('id')}' must match folder name")
        errors += errs
        checked += 1

    for sidecar in sorted((ROOT / "data").rglob("*.json")):
        if sidecar.name == "manifest.json":
            continue
        errors += check(validators["sidecar"], sidecar)
        checked += 1

    for e in errors:
        print(f"FAIL {e}")
    print(f"{checked} files checked, {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
