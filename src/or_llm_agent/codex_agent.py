from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from or_llm_agent.redaction import redact_text


@dataclass(frozen=True)
class CodexAgentPaths:
    artifact_root: Path
    work_dir: Path
    session_dir: Path
    events_path: Path
    last_message_path: Path
    submission_path: Path
    report_path: Path
    raw_path: Path
    status_path: Path
    manifest_path: Path


@dataclass(frozen=True)
class CodexAgentOptions:
    codex_model: str | None
    codex_sandbox: str
    codex_approval: str
    max_repair_attempts: int
    timeout_seconds: int | None
    codex_reasoning_effort: str | None = None


@dataclass(frozen=True)
class CodexAgentResult:
    returncode: int
    timed_out: bool
    command: list[str]
    events_path: Path
    last_message_path: Path
    status_path: Path
    run_metadata: dict[str, Any] = field(default_factory=dict)


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
        work_dir=neutral_work_dir(root, problem_id),
        session_dir=root / "sessions" / problem_id,
        events_path=root / "sessions" / problem_id / "codex-events.jsonl",
        last_message_path=root / "sessions" / problem_id / "last-message.md",
        submission_path=(submission_path or root / "submissions" / f"{problem_id}.py").resolve(),
        report_path=(report_path or root / "reports" / f"{problem_id}.json").resolve(),
        raw_path=(raw_path or root / "raw" / f"{problem_id}.txt").resolve(),
        status_path=(root / "agent-status" / f"{problem_id}.json").resolve(),
        manifest_path=(root / "agent-status" / f"{problem_id}.agent-run-manifest.json").resolve(),
    )


def neutral_work_dir(artifact_root: Path, problem_id: str) -> Path:
    root_hash = hashlib.sha256(str(artifact_root).encode("utf-8")).hexdigest()[:16]
    return Path.home() / ".cache" / "or_llm_agent" / "codex-work" / root_hash / problem_id


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

    run_metadata = build_codex_run_metadata(command=command, options=options, stdout=stdout)
    harvested = _harvest_work_dir_artifacts(paths)
    manifest_payload = _build_run_manifest(
        problem_id=problem_id,
        problem_path=problem_path,
        paths=paths,
        options=options,
        command=command,
        returncode=returncode,
        timed_out=timed_out,
        harvested_artifacts=harvested,
        run_metadata=run_metadata,
    )
    paths.manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths.events_path.write_text(redact_text(stdout), encoding="utf-8")
    raw_payload = {
        "problem_id": problem_id,
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "manifest_path": str(paths.manifest_path),
        "events_path": str(paths.events_path),
        "last_message_path": str(paths.last_message_path),
        "work_dir": str(paths.work_dir),
        "harvested_artifacts": harvested,
        "stderr": redact_text(stderr),
    }
    raw_payload.update(codex_run_metadata_summary_fields(run_metadata))
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
            "work_dir": str(paths.work_dir),
            "status_path": str(paths.status_path),
            "agent_manifest": str(paths.manifest_path),
        }
    )
    status_payload.update(codex_run_metadata_summary_fields(run_metadata))
    paths.status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return CodexAgentResult(
        returncode=returncode,
        timed_out=timed_out,
        command=command,
        events_path=paths.events_path,
        last_message_path=paths.last_message_path,
        status_path=paths.status_path,
        run_metadata=run_metadata,
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


def build_codex_run_metadata(
    *,
    command: list[str],
    options: CodexAgentOptions,
    stdout: str,
) -> dict[str, Any]:
    config = _codex_config_values()
    effective_model, model_source = _effective_codex_value(options.codex_model, config.get("model"))
    effective_effort, effort_source = _effective_codex_value(
        options.codex_reasoning_effort,
        config.get("model_reasoning_effort"),
    )
    return {
        "schema_version": "codex_run_metadata_v1",
        "adapter": "codex-cli",
        "codex_model_arg": options.codex_model or "",
        "codex_reasoning_effort_arg": options.codex_reasoning_effort or "",
        "codex_effective_model": effective_model,
        "codex_effective_model_source": model_source,
        "codex_effective_reasoning_effort": effective_effort,
        "codex_effective_reasoning_effort_source": effort_source,
        "codex_cli_version": _codex_cli_version(),
        "codex_config_path": str(_codex_config_path()),
        "codex_command": [redact_text(item) for item in command],
        "codex_command_string": redact_text(shlex.join(command)),
        "codex_thread_id": _extract_codex_thread_id(stdout),
        "codex_usage": _extract_codex_usage(stdout),
    }


def codex_run_metadata_summary_fields(
    metadata: dict[str, Any] | None,
    *,
    prefix: str = "",
) -> dict[str, Any]:
    if not isinstance(metadata, dict) or not metadata:
        return {}
    stem = f"{prefix}_" if prefix else ""
    return {
        f"{stem}codex_run_metadata": metadata,
        f"{stem}codex_effective_model": metadata.get("codex_effective_model", ""),
        f"{stem}codex_effective_reasoning_effort": metadata.get("codex_effective_reasoning_effort", ""),
        f"{stem}codex_cli_version": metadata.get("codex_cli_version", ""),
        f"{stem}codex_usage": metadata.get("codex_usage", {}),
    }


def codex_exec_model_args(options: CodexAgentOptions) -> list[str]:
    command: list[str] = []
    if options.codex_reasoning_effort:
        command.extend(["-c", f"model_reasoning_effort={json.dumps(options.codex_reasoning_effort)}"])
    if options.codex_model:
        command.extend(["-m", options.codex_model])
    return command


def _effective_codex_value(requested: str | None, configured: str | None) -> tuple[str, str]:
    if requested:
        return requested, "arg"
    if configured:
        return configured, "codex_config"
    return "", "unknown"


def _codex_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


@lru_cache(maxsize=1)
def _codex_config_values() -> dict[str, str]:
    path = _codex_config_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    section = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.strip("[]").strip()
            continue
        if section:
            continue
        key, separator, raw_value = stripped.partition("=")
        if not separator:
            continue
        key = key.strip()
        if key not in {"model", "model_reasoning_effort"}:
            continue
        value = _simple_toml_string_value(raw_value.strip())
        if value:
            values[key] = value
    return values


def _simple_toml_string_value(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value.strip('"')
        return parsed if isinstance(parsed, str) else ""
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value.split("#", 1)[0].strip()


@lru_cache(maxsize=1)
def _codex_cli_version() -> str:
    if shutil.which("codex") is None:
        return ""
    try:
        result = subprocess.run(
            ["codex", "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    version = (result.stdout or result.stderr).strip()
    return redact_text(version)


def _extract_codex_usage(stdout: str) -> dict[str, Any]:
    usage: dict[str, Any] = {}
    for event in _iter_codex_json_events(stdout):
        candidate = event.get("usage")
        if not isinstance(candidate, dict):
            turn = event.get("turn")
            candidate = turn.get("usage") if isinstance(turn, dict) else None
        if isinstance(candidate, dict):
            usage = candidate
    return usage


def _extract_codex_thread_id(stdout: str) -> str:
    for event in _iter_codex_json_events(stdout):
        candidate = event.get("thread_id")
        if isinstance(candidate, str) and candidate:
            return candidate
        thread = event.get("thread")
        if isinstance(thread, dict) and isinstance(thread.get("id"), str):
            return thread["id"]
    return ""


def _iter_codex_json_events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _build_run_manifest(
    *,
    problem_id: str,
    problem_path: Path,
    paths: CodexAgentPaths,
    options: CodexAgentOptions,
    command: list[str],
    returncode: int,
    timed_out: bool,
    harvested_artifacts: list[str],
    run_metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "swe_agent_run_manifest_v1",
        "adapter": "codex-cli",
        "problem_id": problem_id,
        "command": command,
        "codex_run_metadata": run_metadata,
        "options": {
            "codex_model": options.codex_model,
            "codex_reasoning_effort": options.codex_reasoning_effort,
            "codex_sandbox": options.codex_sandbox,
            "codex_approval": options.codex_approval,
            "max_repair_attempts": options.max_repair_attempts,
            "timeout_seconds": options.timeout_seconds,
        },
        "paths": {
            "artifact_root": str(paths.artifact_root),
            "work_dir": str(paths.work_dir),
            "session_dir": str(paths.session_dir),
            "problem_path": str(problem_path),
        },
        "outputs": {
            "submission_path": str(paths.submission_path),
            "report_path": str(paths.report_path),
            "raw_path": str(paths.raw_path),
            "status_path": str(paths.status_path),
            "events_path": str(paths.events_path),
            "last_message_path": str(paths.last_message_path),
            "manifest_path": str(paths.manifest_path),
        },
        "result": {
            "returncode": returncode,
            "timed_out": timed_out,
        },
        "harvested_artifacts": harvested_artifacts,
    }


def build_codex_command(paths: CodexAgentPaths, options: CodexAgentOptions) -> list[str]:
    command = [
        "codex",
        "-a",
        options.codex_approval,
        "exec",
        "--json",
        "-C",
        str(paths.work_dir),
        "--add-dir",
        str(paths.artifact_root),
        "--skip-git-repo-check",
        "-s",
        options.codex_sandbox,
        "-o",
        str(paths.last_message_path),
    ]
    command.extend(codex_exec_model_args(options))
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
    metadata_context = _problem_metadata_context(problem)
    return f"""You are running as a nested Codex agent for OR-LLM-Agent agent mode.

Goal: generate one OR-CI submission for `{problem_id}`, verify it, inspect failures, and repair it up to {options.max_repair_attempts} times.

Write only inside this artifact workspace:
{paths.artifact_root}

Current Codex working directory for temporary files:
{paths.work_dir}

Required output paths:
- Submission Python module: {paths.submission_path}
- OR-CI report JSON: {paths.report_path}
- Agent status JSON: {paths.status_path}
- Final answer message: {paths.last_message_path}

Do not edit repository source files. Final artifacts must be written only inside the artifact workspace. Temporary files may be created in the current Codex working directory and then moved or copied to the required output paths.

If the sandbox blocks writes to the absolute artifact workspace, write the same relative files under the current Codex working directory instead:
- submissions/{problem_id}.py
- reports/{problem_id}.json
- agent-status/{problem_id}.json
- sessions/{problem_id}/last-message.md

The parent CLI will harvest those fallback files after Codex exits.

Natural language problem:
{question}

OR-CI problem metadata path:
{problem_path}

{metadata_context}

Submission contract:
```python
import gurobipy as gp
from gurobipy import GRB

def build_model(data: dict) -> gp.Model:
    ...
```

Rules:
- You have enough information in this prompt to use standard gurobipy Model/addVars/addConstr/setObjective patterns; do not fetch external docs unless verification fails because a Gurobi API call is unknown.
- Return an unoptimized gurobipy.Model.
- Do not call optimize() inside build_model.
- Do not print output from the submission module.
- Do not read files, call APIs, or use external packages other than gurobipy in the submission.
- Do not hard-code the known optimal objective value or solution.
- Use values from the data argument so transformed OR-CI data changes the model.
- Do not use evaluation_only fields; they are not passed to build_model.
- Do not run cleanup or removal commands; leave generated cache files alone.

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

Start now. Complete the workflow without asking for confirmation.
"""


def _problem_metadata_context(problem: dict[str, Any]) -> str:
    scenarios = problem.get("scenarios")
    if isinstance(scenarios, list) and scenarios:
        return f"""OR-CI multi-scenario metadata:
```json
{json.dumps({"problem_type": problem.get("problem_type"), "scenarios": scenarios}, ensure_ascii=False, indent=2)}
```

For `MULTI_SCENARIO`, OR-CI calls `build_model(data)` once per scenario using that scenario's `instance` object as `data`.
"""
    return f"""OR-CI instance data passed to build_model(data):
```json
{json.dumps(problem.get("instance", {}), ensure_ascii=False, indent=2)}
```

Metamorphic verifier configuration:
```json
{json.dumps(problem.get("metamorphic", {}), ensure_ascii=False, indent=2)}
```
"""


def _neutral_work_dir(artifact_root: Path, problem_id: str) -> Path:
    return neutral_work_dir(artifact_root, problem_id)


def _harvest_work_dir_artifacts(paths: CodexAgentPaths) -> list[str]:
    harvested: list[str] = []
    pairs = (
        (paths.work_dir / "submissions" / paths.submission_path.name, paths.submission_path),
        (paths.work_dir / paths.submission_path.name, paths.submission_path),
        (paths.work_dir / "reports" / paths.report_path.name, paths.report_path),
        (paths.work_dir / paths.report_path.name, paths.report_path),
        (paths.work_dir / "agent-status" / paths.status_path.name, paths.status_path),
        (
            paths.work_dir / "sessions" / paths.session_dir.name / paths.last_message_path.name,
            paths.last_message_path,
        ),
    )
    for source, target in pairs:
        if not source.is_file():
            continue
        if target.exists() and target.stat().st_size > 0:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        harvested.append(str(target))
    return harvested


def _ensure_agent_dirs(paths: CodexAgentPaths) -> None:
    for path in (
        paths.work_dir,
        paths.session_dir,
        paths.submission_path.parent,
        paths.report_path.parent,
        paths.raw_path.parent,
        paths.status_path.parent,
        paths.manifest_path.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _coerce_timeout_stream(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
