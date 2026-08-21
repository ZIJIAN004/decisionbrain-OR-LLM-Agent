"""Run OR-LLM-Agent over the 65 FrontierOR cases.

Each task runs as its own process under a memory cap and a wall clock, so a task
that exhausts either is killed on its own without touching the host or the other
tasks, and its cost is measured separately.

Everything a run produces goes under runs/<tag>-<timestamp>/:

    report.jsonl          one line per task: result plus resource usage
    logs/<paper_id>.json  the task's own record and its full tool transcript
    logs/<paper_id>.log   whatever the task process wrote to stdout and stderr
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from . import config


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _run_task(
    paper_id: str,
    model: str,
    batch_slice: str,
    memory_budget_gb: int,
    cpu_cores: int,
    run_dir: Path,
) -> dict:
    """Spawn wrapper.py so this task's resource usage is measured on its own."""
    task_log = run_dir / "logs" / f"{paper_id}.json"
    argv = [
        sys.executable, "-m", "adapters.frontieror.wrapper",
        "--batch-slice", batch_slice,
        "--memory-budget-gb", str(memory_budget_gb),
        "--cpu-cores", str(cpu_cores),
        "--timeout", str(config.TASK_TIMEOUT_SECONDS),
        "--cwd", str(config.REPO_ROOT),
        "--log", str(run_dir / "logs" / f"{paper_id}.log"),
        "--",
        sys.executable, "-m", "adapters.frontieror.run_one",
        "--problem", paper_id,
        "--model", model,
        "--log", str(task_log),
    ]
    proc = subprocess.run(
        argv, cwd=str(config.REPO_ROOT), capture_output=True, text=True, check=False
    )

    try:
        usage = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        usage = {
            "outcome": "wrapper_failed",
            "returncode": proc.returncode,
            "stderr": proc.stderr[-2000:],
        }

    record = {"paper_id": paper_id, "model": model, **usage}
    # The objective is read from the task's own record rather than parsed out of
    # its stdout, so a task that died mid-run simply has no result field.
    if task_log.is_file():
        try:
            record["result"] = json.loads(task_log.read_text(encoding="utf-8"))["result"]
        except (ValueError, KeyError):
            record["result"] = None
    # The 7200-second budget ends with the original agent process. Candidate
    # recovery and schema conversion intentionally run afterwards so a useful
    # incumbent is not discarded merely because the agent reached its deadline.
    try:
        post = subprocess.run(
            [
                sys.executable,
                "-m",
                "adapters.frontieror.postprocess",
                "--problem",
                paper_id,
                "--model",
                model,
            ],
            cwd=str(config.REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=config.RESULT_ADAPTER_TIMEOUT_SECONDS,
            check=False,
        )
        record["result_adapter"] = json.loads(post.stdout.strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        record["result_adapter"] = {
            "status": "adapter_timeout",
            "schema_valid": False,
            "raw_candidate_preserved": True,
        }
    except (ValueError, IndexError):
        record["result_adapter"] = {
            "status": "adapter_failed",
            "schema_valid": False,
            "error": (post.stderr or post.stdout)[-2000:],
        }

    workspace = config.WORKSPACE_ROOT / paper_id
    raw_candidate = workspace / "raw_candidate.json"
    solution = workspace / "solution.json"
    record["raw_candidate"] = str(raw_candidate) if raw_candidate.is_file() else None
    record["solution"] = str(solution) if solution.is_file() else None
    record["candidate_available"] = raw_candidate.is_file()
    _atomic_json(run_dir / "logs" / f"{paper_id}.final.json", record)
    return record


def _create_batch_slice(memory_budget_gb: int) -> str:
    """Create a transient parent cgroup shared by every agent task in this batch."""
    unit = f"or-llm-frontieror-batch-{uuid.uuid4().hex}.slice"
    completed = subprocess.run(
        [
            "systemctl",
            "--user",
            "set-property",
            "--runtime",
            unit,
            f"MemoryMax={memory_budget_gb}G",
            "MemorySwapMax=0",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"failed to configure batch memory slice {unit}: {completed.stderr.strip()}"
        )
    return unit


def _release_batch_slice(unit: str) -> None:
    subprocess.run(
        ["systemctl", "--user", "stop", unit],
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["systemctl", "--user", "revert", unit],
        capture_output=True,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=config.JOBS)
    parser.add_argument("--budget-gb", type=int, default=config.TOTAL_BUDGET_GB)
    parser.add_argument("--model", default=os.environ.get("LLM_CHAT_MODEL", "deepseek-v4-flash"))
    parser.add_argument("--only", nargs="*", help="restrict to these paper_ids")
    parser.add_argument("--run-dir", type=Path, default=None, help="defaults to a new runs/ folder")
    args = parser.parse_args()

    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    memory_budget_gb = max(1, args.budget_gb)
    cpu_cores = max(1, config.TOTAL_CPU_CORES // args.jobs)

    cases = config.load_cases()
    if args.only:
        cases = {k: v for k, v in cases.items() if k in set(args.only)}
        if not cases:
            parser.error("no matching paper_ids in the suite index")

    # Smallest first: the two instances above 100 MB are the likeliest to hit the
    # cap, and finishing the cheap cases first makes a partial run useful.
    ordered = sorted(cases.items(), key=lambda kv: kv[1]["instance_bytes"])

    run_dir = args.run_dir or config.new_run_dir()
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.jsonl"

    batch_slice = _create_batch_slice(memory_budget_gb)
    print(f"{len(ordered)} cases | jobs={args.jobs} | {memory_budget_gb} GB batch memory "
          f"| {cpu_cores} CPU cores per task "
          f"| {config.TASK_TIMEOUT_SECONDS}s wall | model={args.model}", flush=True)
    print(f"run dir: {run_dir}", flush=True)

    started = time.time()
    try:
        with (
            report_path.open("w", encoding="utf-8") as out,
            concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool,
        ):
            futures = {
                pool.submit(
                    _run_task,
                    pid,
                    args.model,
                    batch_slice,
                    memory_budget_gb,
                    cpu_cores,
                    run_dir,
                ): pid
                for pid, _ in ordered
            }
            for future in concurrent.futures.as_completed(futures):
                paper_id = futures[future]
                try:
                    record = future.result()
                except Exception as exc:  # noqa: BLE001
                    record = {
                        "paper_id": paper_id,
                        "outcome": "scheduler_failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
                result = record.get("result") or {}
                print(
                    f"  {paper_id:<20} {record.get('outcome', '?'):<16} "
                    f"obj={result.get('objective')} "
                    f"tools={result.get('tool_calls')} "
                    f"peak={record.get('peak_rss_gb')}GB "
                    f"{record.get('wall_s')}s",
                    flush=True,
                )
    finally:
        _release_batch_slice(batch_slice)

    print(f"\ndone in {time.time() - started:.0f}s -> {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
