from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BWOR_RUN_DATASET_KEYS = ("id", "en_question", "answer")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_bwor_dataset() -> Path:
    return repo_root() / "data" / "datasets" / "bwor.jsonl"


def default_bwor_run_dataset() -> Path:
    return repo_root() / "data" / "datasets" / "bwor_run.jsonl"


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


def build_bwor_run_records(path: Path) -> list[dict[str, Any]]:
    records = load_bwor_records(path)
    return [_to_bwor_run_record(record, path=path, problem_id=problem_id) for problem_id, record in records.items()]


def write_bwor_run_dataset(source_path: Path, output_path: Path) -> int:
    records = build_bwor_run_records(source_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(records)


def load_bwor_run_records(path: Path) -> dict[str, dict[str, Any]]:
    records = load_bwor_records(path)
    for problem_id, record in records.items():
        validate_bwor_run_record(record, path=path, problem_id=problem_id)
    return records


def load_bwor_run_record(path: Path, problem_id: str) -> dict[str, Any]:
    records = load_bwor_run_records(path)
    try:
        return records[problem_id]
    except KeyError as exc:
        raise KeyError(f"BWOR id not found in {path}: {problem_id}") from exc


def validate_bwor_run_record(record: dict[str, Any], *, path: Path, problem_id: str) -> None:
    keys = set(record)
    expected = set(BWOR_RUN_DATASET_KEYS)
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if extra:
            details.append(f"extra keys: {', '.join(extra)}")
        raise ValueError(
            f"BWOR run record {problem_id} in {path} must contain exactly "
            f"{', '.join(BWOR_RUN_DATASET_KEYS)}; {'; '.join(details)}"
        )
    if not isinstance(record["id"], str) or not record["id"].strip():
        raise ValueError(f"BWOR run record {problem_id} in {path} has an invalid id")
    if record["id"] != problem_id:
        raise ValueError(f"BWOR run record id mismatch in {path}: key {problem_id}, record {record['id']}")
    if not isinstance(record["en_question"], str) or not record["en_question"].strip():
        raise ValueError(f"BWOR run record {problem_id} in {path} has no en_question text")


def _to_bwor_run_record(record: dict[str, Any], *, path: Path, problem_id: str) -> dict[str, Any]:
    missing = [key for key in BWOR_RUN_DATASET_KEYS if key not in record]
    if missing:
        raise ValueError(f"BWOR source record {problem_id} in {path} missing keys: {', '.join(missing)}")
    run_record = {key: record[key] for key in BWOR_RUN_DATASET_KEYS}
    validate_bwor_run_record(run_record, path=path, problem_id=problem_id)
    return run_record


def load_problem(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
