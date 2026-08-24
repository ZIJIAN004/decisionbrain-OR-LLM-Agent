"""Retry ResultAdapter for preserved raw candidates without rerunning solvers."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def retry_one(repo: Path, workspace_root: Path, output_root: Path, paper_id: str,
              model: str, timeout: int) -> dict:
    workspace = workspace_root / paper_id
    log = output_root / f"{paper_id}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    started_at = datetime.now(timezone.utc).isoformat()
    result = {
        "paper_id": paper_id,
        "log": str(log),
        "timeout_s": timeout,
        "started_at": started_at,
    }
    if not (workspace / "raw_candidate.json").is_file():
        result["status"] = "no_candidate"
        result["ended_at"] = datetime.now(timezone.utc).isoformat()
        result["wall_s"] = 0.0
        log.write_text(
            json.dumps({"event": "no_candidate", **result}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return result
    command = [sys.executable, "-m", "adapters.frontieror.postprocess",
               "--problem", paper_id, "--model", model]
    env = os.environ.copy()
    # The project .env uses LLM_* names and stores the full chat-completions
    # URL. The OpenAI-compatible client expects credential aliases and the API
    # root, otherwise it requests /chat/completions/chat/completions.
    if not env.get("OPENAI_API_KEY") and env.get("LLM_API_KEY"):
        env["OPENAI_API_KEY"] = env["LLM_API_KEY"]
    if not env.get("OPENAI_API_BASE") and env.get("LLM_MODEL_URL"):
        env["OPENAI_API_BASE"] = env["LLM_MODEL_URL"]
    env["OPENAI_API_BASE"] = env.get("OPENAI_API_BASE", "").removesuffix("/chat/completions").rstrip("/")
    env["ADAPTER_WORKSPACE_ROOT"] = str(workspace_root)
    with log.open("w", encoding="utf-8", buffering=1) as handle:
        handle.write(json.dumps({
            "event": "formatter_start",
            "paper_id": paper_id,
            "command": command,
            "started_at": started_at,
            "timeout_s": timeout,
        }, ensure_ascii=False) + "\n")
        try:
            proc = subprocess.run(command, cwd=str(repo), env=env, stdout=handle,
                                  stderr=subprocess.STDOUT, text=True,
                                  timeout=timeout, check=False)
            adapter_record = None
            record_path = workspace / "result_adapter.json"
            if record_path.is_file():
                try:
                    adapter_record = json.loads(record_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            result.update(
                returncode=proc.returncode,
                adapter=adapter_record,
                status=("formatted" if adapter_record and adapter_record.get("status") == "formatted"
                        else "format_failed"),
            )
        except subprocess.TimeoutExpired:
            result["status"] = "adapter_timeout"
            result["returncode"] = None
            handle.write(json.dumps({
                "event": "formatter_timeout",
                "paper_id": paper_id,
                "timeout_s": timeout,
            }, ensure_ascii=False) + "\n")
    result["solution_present"] = (workspace / "solution.json").is_file()
    result["ended_at"] = datetime.now(timezone.utc).isoformat()
    result["wall_s"] = round(time.time() - started, 1)
    adapter = result.get("adapter") or {}
    result["adapter_attempts"] = adapter.get("attempts")
    result["adapter_error_count"] = len(adapter.get("errors", [])) if isinstance(adapter.get("errors"), list) else None
    with log.open("a", encoding="utf-8", buffering=1) as handle:
        handle.write(json.dumps({
            "event": "formatter_end",
            "paper_id": paper_id,
            "status": result["status"],
            "returncode": result.get("returncode"),
            "solution_present": result["solution_present"],
            "adapter_attempts": result["adapter_attempts"],
            "adapter_error_count": result["adapter_error_count"],
            "ended_at": result["ended_at"],
            "wall_s": result["wall_s"],
        }, ensure_ascii=False) + "\n")
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument("--workspace-root", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--timeout", type=int, default=1200)
    p.add_argument("--only", nargs="*")
    args = p.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    ids = args.only or sorted(x.name for x in args.workspace_root.iterdir()
                               if x.is_dir() and (x / "raw_candidate.json").is_file()
                               and not (x / "solution.json").is_file())
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda pid: retry_one(args.repo, args.workspace_root,
                                                       args.output_root, pid, args.model,
                                                       args.timeout), ids))
    report = args.output_root / "report.jsonl"
    report.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in results), encoding="utf-8")
    print(json.dumps({"tasks": len(results), "formatted": sum(x["status"] == "formatted" for x in results),
                      "report": str(report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
