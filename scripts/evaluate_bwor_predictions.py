# /// script
# requires-python = ">=3.10"
# ///
"""Evaluate BWOR prediction JSONL files against the public release.

Prediction records are keyed by ``id`` and may provide either:
  * ``objective`` or ``answer``: numeric prediction for optimal instances; or
  * ``solution_status``: status prediction for no_optimal instances.

Example:
    uv run scripts/evaluate_bwor_predictions.py \
        --predictions outputs/bwor_predictions.jsonl \
        --output outputs/bwor_eval_report.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = REPO_ROOT / "data" / "datasets" / "bwor.jsonl"
DEFAULT_TOLERANCE = 0.1
NO_OPTIMAL_STATUSES = {
    "no_optimal",
    "no optimum",
    "no optimal",
    "infeasible",
    "unbounded",
    "infeasible_or_unbounded",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open() as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} line {lineno} is not valid JSON: {exc}") from exc
    return records


def normalize_status(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def evaluate_record(
    gold: dict[str, Any],
    pred: dict[str, Any] | None,
    tolerance: float,
) -> dict[str, Any]:
    if pred is None:
        return {
            "id": gold["id"],
            "correct": False,
            "reason": "missing_prediction",
            "gold_status": gold["solution_status"],
            "gold_answer": gold["answer"],
            "pred_status": None,
            "pred_answer": None,
        }

    pred_status = normalize_status(pred.get("solution_status") or pred.get("status"))
    pred_answer = parse_float(pred.get("objective", pred.get("answer")))
    gold_status = gold["solution_status"]

    if gold_status == "no_optimal":
        correct = pred_status in NO_OPTIMAL_STATUSES
        reason = "status_match" if correct else "status_mismatch"
    else:
        gold_answer = float(gold["answer"])
        correct = pred_answer is not None and abs(pred_answer - gold_answer) <= tolerance
        reason = "within_tolerance" if correct else "answer_mismatch"

    return {
        "id": gold["id"],
        "correct": bool(correct),
        "reason": reason,
        "gold_status": gold_status,
        "gold_answer": gold["answer"],
        "pred_status": pred_status,
        "pred_answer": pred_answer,
        "absolute_error": None
        if pred_answer is None or gold["answer"] is None
        else abs(pred_answer - float(gold["answer"])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    args = parser.parse_args()

    gold_records = load_jsonl(args.dataset)
    pred_records = load_jsonl(args.predictions)
    gold_by_id = {r["id"]: r for r in gold_records}
    pred_by_id = {r["id"]: r for r in pred_records}

    unknown_ids = sorted(set(pred_by_id) - set(gold_by_id))
    instance_reports = [
        evaluate_record(gold, pred_by_id.get(gold["id"]), args.tolerance)
        for gold in gold_records
    ]
    correct = sum(1 for r in instance_reports if r["correct"])
    total = len(instance_reports)
    runnable = sum(1 for r in instance_reports if r["pred_answer"] is not None or r["pred_status"])

    report = {
        "dataset": str(args.dataset),
        "predictions": str(args.predictions),
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "tolerance": args.tolerance,
        "missing_predictions": sum(1 for r in instance_reports if r["reason"] == "missing_prediction"),
        "unknown_prediction_ids": unknown_ids,
        "runnable_or_status_count": runnable,
        "instances": instance_reports,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"correct={correct}/{total} accuracy={report['accuracy']:.4f}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
