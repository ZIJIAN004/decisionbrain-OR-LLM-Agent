"""Retry ResultAdapter for preserved raw candidates without rerunning solvers."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def retry_one(repo: Path, workspace_root: Path, output_root: Path, paper_id: str,
              model: str, timeout: int) -> dict:
    workspace = workspace_root / paper_id
    log = output_root / f"{paper_id}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    result = {"paper_id": paper_id, "log": str(log), "timeout_s": timeout}
    if not (workspace / "raw_candidate.json").is_file():
        result["status"] = "no_candidate"
        return result
    started = time.time()
    command = [sys.executable, "-m", "adapters.frontieror.postprocess",
               "--problem", paper_id, "--model", model]
    env = os.environ.copy()
    env["ADAPTER_WORKSPACE_ROOT"] = str(workspace_root)
    with log.open("w", encoding="utf-8", buffering=1) as handle:
        handle.write(json.dumps({"paper_id": paper_id, "command": command}, ensure_ascii=False) + "\n")
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
            result.update(returncode=proc.returncode,
                          adapter=adapter_record,
                          status="formatted" if adapter_record and adapter_record.get("status") == "formatted" else "format_failed")
        except subprocess.TimeoutExpired:
            result["status"] = "adapter_timeout"
        handle.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}] status={result['status']}\n")
    result["solution_present"] = (workspace / "solution.json").is_file()
    result["wall_s"] = round(time.time() - started, 1)
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
