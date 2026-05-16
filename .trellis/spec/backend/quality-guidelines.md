# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

This project currently has no configured linter, formatter, or test framework in
`pyproject.toml`. Quality control therefore depends on small, readable functions,
clear return conventions, direct CLI verification with `uv run`, and focused
review of generated-code execution paths.

Prefer the newer style in `scripts/evaluate_bwor_predictions.py` for new utility
scripts: `Path`, type hints, explicit parser functions, and structured output.
Existing root agent scripts are less typed; do not rewrite them wholesale during
small feature work.

---

## Required Patterns

Use Python 3.10+ syntax and run files through `uv`.

Example from `pyproject.toml`:

```toml
requires-python = ">=3.10"
dependencies = [
    "anthropic==0.49.0",
    "gurobipy==12.0.1",
    "openai==1.66.3",
]
```

For new standalone scripts, use explicit imports, typed helpers, and `Path`
objects.

Example from `scripts/evaluate_bwor_predictions.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_TOLERANCE = 0.1
```

Use small parser helpers for input normalization instead of inlining conversion
logic into the main loop.

Example from `scripts/evaluate_bwor_predictions.py`:

```python
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
```

---

## Data Handling Standards

Dataset loaders should accept both current JSONL benchmark files and legacy JSON
objects where the entry point already supports both.

Example from `or_llm_eval.py`:

```python
first_line = f.readline().strip()
f.seek(0)

if first_line.startswith('{"en_question"') or first_line.startswith('{"cn_question"'):
    for line_num, line in enumerate(f, 1):
        item = json.loads(line)
else:
    dataset = json.load(f)
```

For release-quality evaluation scripts, write deterministic JSON with indentation
and create parent directories.

Example from `scripts/evaluate_bwor_predictions.py`:

```python
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
```

---

## Testing Expectations

There is no test suite configured. For behavior changes, run the smallest
relevant command with `uv run` and a small dataset or handcrafted prediction file.

Minimum checks by change type:

- LLM dispatch or prompts: run one sync or async case with the target model.
- Generated-code execution: run the helper path and inspect stdout/stderr.
- Dataset parsing: run with both JSONL and legacy JSON if touched.
- BWOR report scripts: run `uv run scripts/evaluate_bwor_predictions.py` with a
  small prediction JSONL and inspect the output report.
- MCP wrapper: run `uv run python MCP/mcp_server.py` only when tool behavior changes.

---

## Review Checklist

- Does the change preserve the tuple return convention used by callers?
- Does generated code still execute in a subprocess and clean up temp files?
- Are API connection errors retried only where the async evaluator expects them?
- Does batch output include case id, failure category, and aggregate counts?
- Are file paths built with `Path` in new scripts?
- Are secrets loaded from environment variables rather than literals?
- Are new prompts named constants when reused across async paths?

---

## Anti-Patterns

- Do not add hard-coded API keys. `or_llm_show.py` has an old commented credential
  example near its API setup; do not copy that style.
- Do not introduce a formatter or linter config as a side effect of unrelated
  agent behavior changes.
- Do not mutate the shared `messages` list in retry helpers without understanding
  whether the caller expects the original conversation to remain unchanged.
- Do not use broad `except Exception` without returning or logging a failure reason.
- Do not add large framework abstractions around this flat research script layout.

