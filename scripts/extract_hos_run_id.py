"""Validate a HOS result manifest and print its run ID for CI consumers."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def extract_run_id(manifest: Path, runs_dir: Path = Path("runs")) -> str:
    if not manifest.is_file():
        raise ValueError(f"result JSON was not generated: {manifest}")
    try:
        result = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"result JSON is invalid: {manifest}: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError(f"result JSON must contain one object: {manifest}")
    run_id = result.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError(f"result JSON has no run_id: {manifest}")
    if not (runs_dir / run_id).is_dir():
        raise ValueError(f"run directory does not exist: {runs_dir / run_id}")
    return run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", nargs="?", default="hos-run-result.json")
    parser.add_argument("--runs-dir", default="runs")
    args = parser.parse_args(argv)
    try:
        print(extract_run_id(Path(args.manifest), Path(args.runs_dir)))
    except ValueError as exc:
        print(f"HOS run completed but result manifest parsing failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
