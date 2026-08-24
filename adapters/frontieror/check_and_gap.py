"""Run FrontierOR hidden checkers and compute gaps for OR-LLM-Agent outputs."""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# The large-all index does not carry a reliable objective direction.  This
# mapping was verified against each Agent-visible FrontierOR problem statement.
MAXIMIZATION_TASKS = frozenset({
    "bront2009",
    "caprara1999",
    "forrest2006",
    "furini2016",
    "lai2021",
    "savelsbergh1997",
    "wang2025",
})


def objective_direction(paper_id: str) -> str:
    return "maximize" if paper_id in MAXIMIZATION_TASKS else "minimize"


def objective(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("objective_value")
        return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None
    except (OSError, ValueError, TypeError):
        return None


def load_jsonl(path: Path | None) -> dict[str, dict]:
    if path is None or not path.is_file():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("paper_id"):
                result[str(row["paper_id"])] = row
        except (json.JSONDecodeError, OSError):
            continue
    return result


def load_cases(index: Path) -> dict[str, dict]:
    raw = json.loads(index.read_text(encoding="utf-8"))
    cases = raw.get("cases", raw) if isinstance(raw, dict) else raw
    if isinstance(cases, list):
        return {str(item): {} for item in cases}
    if not isinstance(cases, dict):
        raise ValueError("suite index must contain a cases mapping")
    return {str(key): value if isinstance(value, dict) else {} for key, value in cases.items()}


def adapter_info(adapter_root: Path | None, paper_id: str) -> dict | None:
    if adapter_root is None:
        return None
    report = adapter_root / "report.jsonl"
    rows = load_jsonl(report)
    row = rows.get(paper_id)
    if not row:
        return None
    adapter = row.get("adapter") if isinstance(row.get("adapter"), dict) else {}
    errors = adapter.get("errors") if isinstance(adapter.get("errors"), list) else []
    return {
        "status": row.get("status") or adapter.get("status"),
        "attempts": row.get("adapter_attempts", adapter.get("attempts")),
        "error_count": row.get("adapter_error_count", len(errors)),
        "log": row.get("log"),
        "report": str(report),
    }


def find_candidate(candidate_root: Path, adapter_root: Path | None, paper_id: str):
    candidates = [(candidate_root / paper_id / "solution.json", "workspace")]
    if adapter_root:
        candidates.extend(
            [
                (adapter_root / paper_id / "solution.json", "adapter_retry"),
                (adapter_root / "workspaces" / paper_id / "solution.json", "adapter_retry"),
            ]
        )
    for path, source in candidates:
        if path.is_file():
            return path, source
    return candidates[0]


def run_checker(checker: Path, instance: Path, candidate: Path, timeout: float) -> dict:
    started = time.time()
    result = {
        "executed": False,
        "candidate": str(candidate),
        "checker": str(checker),
        "instance": str(instance),
    }
    if not checker.is_file() or not instance.is_file():
        result.update(outcome="checker_input_missing", wall_s=round(time.time() - started, 3))
        return result
    with tempfile.TemporaryDirectory(prefix="or-frontieror-check-") as tmp:
        result_path = Path(tmp) / "feasibility_result.json"
        command = [
            sys.executable,
            str(checker),
            "--instance_path",
            str(instance),
            "--solution_path",
            str(candidate),
            "--result_path",
            str(result_path),
        ]
        try:
            process = subprocess.run(
                command,
                cwd=str(checker.parent),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            result.update(outcome="checker_timeout", wall_s=round(time.time() - started, 3))
            return result
        except OSError as exc:
            result.update(
                outcome="checker_execution_error",
                error=f"{type(exc).__name__}: {exc}",
                wall_s=round(time.time() - started, 3),
            )
            return result
        result.update(
            executed=True,
            returncode=process.returncode,
            stdout=process.stdout[-2000:],
            stderr=process.stderr[-4000:],
        )
        if not result_path.is_file():
            result.update(outcome="checker_execution_error", error="checker produced no result file")
        else:
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                result["checker_result"] = payload
                feasible = payload.get("feasible")
                result["outcome"] = (
                    "feasible" if feasible is True else
                    "infeasible" if feasible is False else
                    "checker_execution_error"
                )
                if result["outcome"] == "checker_execution_error":
                    result["error"] = "checker result has no boolean feasible field"
            except (OSError, ValueError, TypeError) as exc:
                result.update(outcome="checker_execution_error", error=f"invalid checker result: {exc}")
    result["wall_s"] = round(time.time() - started, 3)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--instance-root", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checker-report", type=Path,
                        help="optional prior report; retained as per-instance provenance")
    parser.add_argument("--checker-output", type=Path,
                        help="checker JSONL output; defaults beside --output")
    parser.add_argument("--adapter-retry-root", type=Path,
                        help="formatter retry output; defaults to the run directory's adapter-retry")
    parser.add_argument("--checker-timeout", type=float, default=300.0)
    args = parser.parse_args()

    cases = load_cases(args.index)
    adapter_root = args.adapter_retry_root
    if adapter_root is None:
        adapter_root = args.candidate_root.parent / "adapter-retry"
    prior = load_jsonl(args.checker_report)
    checker_output = args.checker_output or args.output.with_name("hidden-check-report.jsonl")
    checker_output.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    gaps = []
    for paper_id, case in sorted(cases.items()):
        candidate, source = find_candidate(args.candidate_root, adapter_root, paper_id)
        retry = adapter_info(adapter_root, paper_id)
        if retry and retry.get("status") == "formatted":
            source = "adapter_retry"
        task = args.task_root / paper_id
        instance_index = case.get("instance_index", 1)
        instance = args.instance_root / paper_id / "instance" / f"large_instance_{instance_index}.json"
        item = {
            "paper_id": paper_id,
            "candidate": str(candidate),
            "candidate_source": source,
            "prior_checker_outcome": prior.get(paper_id, {}).get("outcome"),
            "adapter_retry": retry,
        }
        if not candidate.is_file():
            item.update(outcome="missing_candidate", executed=False, wall_s=0.0)
        else:
            item.update(run_checker(task / "hidden" / "feasibility_check.py", instance, candidate,
                                    args.checker_timeout))
        rows.append(item)

        if item.get("outcome") == "feasible":
            refs = sorted((args.instance_root / paper_id / "gurobi_solution").glob("large_solution_*.json"))
            ref = refs[0] if refs else None
            candidate_objective = objective(candidate)
            reference_objective = objective(ref) if ref else None
            gap = None
            if candidate_objective is not None and reference_objective not in (None, 0):
                direction = objective_direction(paper_id)
                item["objective_direction"] = direction
                gap = ((candidate_objective - reference_objective) / abs(reference_objective)
                       if direction != "maximize" else
                       (reference_objective - candidate_objective) / abs(reference_objective))
                gaps.append(gap)
            item.update(candidate_objective=candidate_objective,
                        reference_objective=reference_objective, gap=gap)

    checker_output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    summary = {
        "count": len(rows),
        "gap_count": len(gaps),
        "average_gap": sum(gaps) / len(gaps) if gaps else None,
        "checker_report": str(checker_output),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("count", "gap_count", "average_gap", "checker_report")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
