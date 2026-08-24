"""Convert a raw incumbent into the task's FrontierOR solution schema."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import jsonschema

from . import config, tools
from .tool_loop import query_llm_with_tools
from .workspace import Workspace


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    candidates = [text.strip()]
    candidates.extend(
        match.strip()
        for match in re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    )
    decoder = json.JSONDecoder()
    for start, character in enumerate(text):
        if character == "{":
            try:
                _, end = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            candidates.append(text[start : start + end])
    for value in candidates:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def adapt(paper_id: str, model_name: str) -> dict[str, Any]:
    workspace = config.WORKSPACE_ROOT / paper_id
    candidate_path = workspace / "raw_candidate.json"
    if not candidate_path.is_file():
        return {"status": "no_candidate", "attempts": 0, "schema_valid": False}

    schema_source = config.solution_schema_path(paper_id)
    schema_path = workspace / "solution_schema.json"
    shutil.copy2(schema_source, schema_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    question = config.problem_md_path(paper_id).read_text(encoding="utf-8")
    box = Workspace(workspace)
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a result adapter, not an optimizer. You must convert the existing raw "
                "candidate by writing a workspace-local Python script named convert_solution.py. "
                "Use write_file to create or replace that script, then use run_python to execute "
                "it. The script must read raw_candidate.json and instance/schema files and write "
                "solution.json at the workspace root. Do not return the solution as chat JSON and "
                "do not write solution.json directly with shell. Preserve candidate decisions; "
                "do not optimize, rerun a solver, or fabricate missing values. After execution, "
                "inspect the tool result and repair the script until solution.json validates."
            ),
        },
        {
            "role": "user",
            "content": f"Problem statement:\n{question}\n\nConvert the saved candidate now.",
        },
    ]
    errors: list[dict[str, Any]] = []
    tool_transcript: list[dict[str, Any]] = []
    call_tool = tools.dispatcher(box)

    for attempt in range(1, config.RESULT_ADAPTER_MAX_ATTEMPTS + 1):
        # Each attempt must produce a fresh artifact; never accept a stale file
        # left by an earlier failed conversion.
        (workspace / "solution.json").unlink(missing_ok=True)
        try:
            attempt_calls: list[dict[str, Any]] = []
            def record_call(name: str, arguments: str, result: str) -> None:
                entry = {"name": name, "arguments": arguments, "result": result[:4000]}
                attempt_calls.append(entry)
                tool_transcript.append({"attempt": attempt, **entry})
            response = query_llm_with_tools(
                messages,
                model_name=model_name,
                tool_schemas=tools.schemas(),
                call_tool=call_tool,
                temperature=0.0,
                on_call=record_call,
            )
        except Exception as exc:  # adapter/tool failures are recoverable rounds
            error = {
                "attempt": attempt,
                "message": f"{type(exc).__name__}: {exc}",
                "path": [],
                "schema_path": [],
            }
            errors.append(error)
            messages.append({
                "role": "user",
                "content": (
                    "The adapter tool call failed. Treat this as a recoverable error, "
                    "inspect the workspace again, and return a complete corrected JSON object. "
                    f"Error: {json.dumps(error, ensure_ascii=False)}"
                ),
            })
            continue
        try:
            script_path = workspace / "convert_solution.py"
            if not script_path.is_file():
                raise jsonschema.ValidationError(
                    "convert_solution.py was not created; write the conversion script and run it"
                )
            if not any(c["name"] == "run_python" for c in attempt_calls):
                raise jsonschema.ValidationError(
                    "convert_solution.py was not executed; call run_python after writing it"
                )
            if not (workspace / "solution.json").is_file():
                raise jsonschema.ValidationError(
                    "solution.json was not created by convert_solution.py"
                )
            candidate = json.loads((workspace / "solution.json").read_text(encoding="utf-8"))
            if not isinstance(candidate, dict):
                raise jsonschema.ValidationError("solution.json top level must be an object")
            jsonschema.validate(instance=candidate, schema=schema)
        except (jsonschema.ValidationError, jsonschema.SchemaError) as exc:
            error = {
                "attempt": attempt,
                "message": exc.message,
                "path": list(exc.absolute_path),
                "schema_path": list(exc.absolute_schema_path),
            }
            errors.append(error)
            messages.extend(
                [
                    {"role": "assistant", "content": response},
                    {
                        "role": "user",
                        "content": (
                            "The conversion script or its output failed validation. Treat this "
                            "as a recoverable tool error: repair convert_solution.py, run it "
                            "again, and ensure it writes a complete valid solution.json. "
                            f"Validation error: {json.dumps(error, ensure_ascii=False)}"
                        ),
                    },
                ]
            )
            continue

        _atomic_json(workspace / "solution.json", candidate)
        record = {
            "status": "formatted",
            "attempts": attempt,
            "schema_valid": True,
            "errors": errors,
            "tool_transcript": tool_transcript,
        }
        _atomic_json(workspace / "result_adapter.json", record)
        return record

    record = {
        "status": "format_failed",
        "attempts": config.RESULT_ADAPTER_MAX_ATTEMPTS,
        "schema_valid": False,
        "errors": errors,
        "raw_candidate_preserved": True,
        "tool_transcript": tool_transcript,
    }
    _atomic_json(workspace / "result_adapter.json", record)
    return record
