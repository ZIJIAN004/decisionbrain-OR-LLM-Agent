from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_bwor_dataset() -> Path:
    return repo_root() / "data" / "datasets" / "bwor.jsonl"


def default_or_ci_root() -> Path:
    return repo_root().parent / "or-ci"


def default_problem_path(problem_id: str, or_ci_root: Path | None = None) -> Path:
    root = or_ci_root or default_or_ci_root()
    return root / "tests" / "fixtures" / "bwor" / problem_id / "problem.json"


def load_bwor_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"could not parse {path}:{line_num}: {exc}") from exc
            record_id = record.get("id")
            if not record_id:
                raise ValueError(f"missing id in {path}:{line_num}")
            records[str(record_id)] = record
    return records


def load_bwor_record(path: Path, problem_id: str) -> dict[str, Any]:
    records = load_bwor_records(path)
    try:
        return records[problem_id]
    except KeyError as exc:
        raise KeyError(f"BWOR id not found in {path}: {problem_id}") from exc


def load_problem(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

