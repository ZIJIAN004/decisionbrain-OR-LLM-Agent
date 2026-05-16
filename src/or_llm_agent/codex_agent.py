from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from or_llm_agent.redaction import redact_text


@dataclass(frozen=True)
class CodexAgentPaths:
    artifact_root: Path
    session_dir: Path
    events_path: Path
    last_message_path: Path
    submission_path: Path
    report_path: Path
    raw_path: Path
    status_path: Path


@dataclass(frozen=True)
class CodexAgentOptions:
    codex_model: str | None
    codex_sandbox: str
    codex_approval: str
    max_repair_attempts: int
    timeout_seconds: int | None


@dataclass(frozen=True)
class CodexAgentResult:
    returncode: int
    timed_out: bool
    command: list[str]
    events_path: Path
    last_message_path: Path
    status_path: Path


def build_agent_paths(
    *,
    problem_id: str,
    artifact_root: Path,
    submission_path: Path | None = None,
    raw_path: Path | None = None,
    report_path: Path | None = None,
) -> CodexAgentPaths:
    root = artifact_root.resolve()
    return CodexAgentPaths(
        artifact_root=root,
        session_dir=root / "sessions" / problem_id,
        events_path=root / "sessions" / problem_id / "codex-events.jsonl",
        last_message_path=root / "sessions" / problem_id / "last-message.md",
        submission_path=(submission_path or root / "submissions" / f"{problem_id}.py").resolve(),
        report_path=(report_path or root / "reports" / f"{problem_id}.json").resolve(),
        raw_path=(raw_path or root / "raw" / f"{problem_id}.txt").resolve(),
        status_path=(root / "agent-status" / f"{problem_id}.json").resolve(),
    )


def run_codex_agent(
    *,
    problem_id: str,
    record: dict[str, Any],
    problem: dict[str, Any],
    problem_path: Path,
    paths: CodexAgentPaths,
    options: CodexAgentOptions,
    verify_command: list[str],
) -> CodexAgentResult:
    _ensure_agent_dirs(paths)
    prompt = build_agent_prompt(
        problem_id=problem_id,
        record=record,
        problem=problem,
        problem_path=problem_path,
        paths=paths,
        options=options,
        verify_command=verify_command,
    )
    command = build_codex_command(paths, options)
    timed_out = False
    try:
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            check=False,
            timeout=options.timeout_seconds if options.timeout_seconds and options.timeout_seconds > 0 else None,
        )
        returncode = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        stdout = _coerce_timeout_stream(exc.stdout)
        stderr = _coerce_timeout_stream(exc.stderr)
        timeout_message = f"codex exec timed out after {options.timeout_seconds} seconds"
        stderr = f"{stderr.rstrip()}\n{timeout_message}\n" if stderr else timeout_message + "\n"

    paths.events_path.write_text(redact_text(stdout), encoding="utf-8")
    raw_payload = {
        "problem_id": problem_id,
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "events_path": str(paths.events_path),
        "last_message_path": str(paths.last_message_path),
        "stderr": redact_text(stderr),
    }
    if not paths.last_message_path.exists():
        paths.last_message_path.write_text(
            "Nested Codex did not produce a final message before exit.\n",
            encoding="utf-8",
        )
    paths.raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status_payload = _read_existing_status(paths.status_path)
    status_payload.update(
        {
            "problem_id": problem_id,
            "generation_mode": "agent",
            "agent_returncode": returncode,
            "timed_out": timed_out,
            "submission_path": str(paths.submission_path),
            "report_path": str(paths.report_path),
            "events_path": str(paths.events_path),
            "last_message_path": str(paths.last_message_path),
            "status_path": str(paths.status_path),
        }
    )
    paths.status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return CodexAgentResult(
        returncode=returncode,
        timed_out=timed_out,
        command=command,
        events_path=paths.events_path,
        last_message_path=paths.last_message_path,
        status_path=paths.status_path,
    )


def _read_existing_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    try:
        existing = json.loads(content)
    except json.JSONDecodeError:
        return {"nested_status_text": content}
    if isinstance(existing, dict):
        return existing
    return {"nested_status": existing}


def build_codex_command(paths: CodexAgentPaths, options: CodexAgentOptions) -> list[str]:
    command = [
        "codex",
        "-a",
        options.codex_approval,
        "exec",
        "--json",
        "-C",
        str(paths.session_dir),
        "--add-dir",
        str(paths.artifact_root),
        "--skip-git-repo-check",
        "-s",
        options.codex_sandbox,
        "-o",
        str(paths.last_message_path),
    ]
    if options.codex_model:
        command.extend(["-m", options.codex_model])
    command.append("-")
    return command


def build_agent_prompt(
    *,
    problem_id: str,
    record: dict[str, Any],
    problem: dict[str, Any],
    problem_path: Path,
    paths: CodexAgentPaths,
    options: CodexAgentOptions,
    verify_command: list[str],
) -> str:
    question = record.get("en_question") or record.get("cn_question") or ""
    verify_base = shlex.join([*verify_command, "verify"])
    return f"""You are running as a nested Codex agent for OR-LLM-Agent agent mode.

Goal: generate one OR-CI submission for `{problem_id}`, verify it, inspect failures, and repair it up to {options.max_repair_attempts} times.

Write only inside this artifact workspace:
{paths.artifact_root}

Required output paths:
- Submission Python module: {paths.submission_path}
- OR-CI report JSON: {paths.report_path}
- Agent status JSON: {paths.status_path}
- Final answer message: {paths.last_message_path}

Do not edit repository source files. Do not write outside the artifact workspace.

Natural language problem:
{question}

OR-CI problem metadata path:
{problem_path}

OR-CI instance data passed to build_model(data):
```json
{json.dumps(problem["instance"], ensure_ascii=False, indent=2)}
```

Metamorphic verifier configuration:
```json
{json.dumps(problem.get("metamorphic", {}), ensure_ascii=False, indent=2)}
```

Submission contract:
```python
import gurobipy as gp
from gurobipy import GRB

def build_model(data: dict) -> gp.Model:
    ...
```

Rules:
- Return an unoptimized gurobipy.Model.
- Do not call optimize() inside build_model.
- Do not print output from the submission module.
- Do not read files, call APIs, or use external packages other than gurobipy in the submission.
- Do not hard-code the known optimal objective value or solution.
- Use values from the data argument so transformed OR-CI data changes the model.
- Do not use evaluation_only fields; they are not passed to build_model.

Verification command template:
```bash
{verify_base} --problem {shlex.quote(str(problem_path))} --submission {shlex.quote(str(paths.submission_path))} --out {shlex.quote(str(paths.report_path))}
```

Process:
1. Write the submission to the exact submission path.
2. Run the OR-CI verification command.
3. If verification fails, read the report JSON and repair the submission. Repeat up to {options.max_repair_attempts} repair attempts.
4. Write status JSON to the exact status path with at least: problem_id, attempts, final_classification, final_status, submission_path, report_path.
5. End with a concise final message summarizing generation status and OR-CI classification.
"""


def _ensure_agent_dirs(paths: CodexAgentPaths) -> None:
    for path in (
        paths.session_dir,
        paths.submission_path.parent,
        paths.report_path.parent,
        paths.raw_path.parent,
        paths.status_path.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _coerce_timeout_stream(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
