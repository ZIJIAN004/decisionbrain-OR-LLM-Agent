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
                "You are a result adapter, not an optimizer. Convert the existing raw "
                "candidate into one JSON object that validates against solution_schema.json. "
                "Use the workspace tools to inspect raw_candidate.json, solver.py, "
                "instance.json, and solution_schema.json. Preserve the candidate's decisions; "
                "do not improve, replace, or fabricate a solution. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": f"Problem statement:\n{question}\n\nConvert the saved candidate now.",
        },
    ]
    errors: list[dict[str, Any]] = []
    call_tool = tools.dispatcher(box)

    for attempt in range(1, config.RESULT_ADAPTER_MAX_ATTEMPTS + 1):
        response = query_llm_with_tools(
            messages,
            model_name=model_name,
            tool_schemas=tools.schemas(),
            call_tool=call_tool,
            temperature=0.0,
        )
        candidate = _extract_json_object(response)
        try:
            if candidate is None:
                raise jsonschema.ValidationError("tool output did not contain a JSON object")
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
                            "The result-adapter tool rejected that output. Treat this as a "
                            "recoverable tool error and return a corrected complete JSON object. "
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
        }
        _atomic_json(workspace / "result_adapter.json", record)
        return record

    record = {
        "status": "format_failed",
        "attempts": config.RESULT_ADAPTER_MAX_ATTEMPTS,
        "schema_valid": False,
        "errors": errors,
        "raw_candidate_preserved": True,
    }
    _atomic_json(workspace / "result_adapter.json", record)
    return record
