# Backend Development Guidelines

> Project-specific backend guidance for the OR-LLM-Agent research codebase.

---

## Overview

This repository is a Python 3.10+ research project, not a service monolith. The
backend is a flat collection of scripts and helper modules that evaluate
operations research problems with LLM-generated Gurobi code.

The central execution flows identified with GitNexus are:

1. MCP tool -> sync agent -> code generation -> shared executor -> objective parser.
2. Async batch runner -> per-case agent -> async LLM query -> async subprocess executor.
3. Show/demo runner -> streaming LLM output -> shared executor -> terminal rendering.

Keep changes consistent with those flows. New backend work should usually extend
one of the existing entry modules instead of adding another framework layer.

---

## Canonical Runtime

Use `uv` for Python commands in this project. The package metadata is deliberately
small and pinned enough for research reproducibility.

Example from `pyproject.toml`:

```toml
[project]
requires-python = ">=3.10"
dependencies = [
    "anthropic==0.49.0",
    "gurobipy==12.0.1",
    "mcp[cli]>=1.6.0",
    "openai==1.66.3",
    "python-dotenv==1.0.1",
]
```

Common commands:

```bash
uv run python or_llm_eval.py --agent --model o3 --data_path data/datasets/BWOR.json
uv run python or_llm_eval_async_resilient.py --math --debug --model o3-mini
uv run python MCP/mcp_server.py
uv run scripts/evaluate_bwor_predictions.py --predictions outputs/preds.jsonl --output outputs/report.json
```

---

## Guidelines Index

| Guide | Description |
|-------|-------------|
| [Directory Structure](./directory-structure.md) | Flat script layout, module ownership, and where new backend logic belongs |
| [CLI Contracts](./cli-contracts.md) | Packaged `or-llm-agent` command signatures, artifact contracts, and verification checks |
| [LLM Integration](./llm-integration.md) | OpenAI/Anthropic client setup, message format, prompt constants, and model dispatch |
| [Async Patterns](./async-patterns.md) | Async client usage, retry/backoff behavior, subprocess timeouts, and batch evaluation |
| [Code Execution](./code-execution.md) | Generated-code extraction, subprocess execution, temp files, and objective parsing |
| [MCP Server](./mcp-server.md) | FastMCP tool wrapper, stdout capture, timeout handling, and import path constraints |
| [Error Handling](./error-handling.md) | Tuple returns, retry loops, failure categories, parser errors, and timeouts |
| [Logging Guidelines](./logging-guidelines.md) | Print-based evaluation logs, batch summaries, shell log files, and sensitive output limits |
| [Quality Guidelines](./quality-guidelines.md) | Python style, type hints, data parsers, testing expectations, and review checklist |

There is intentionally no database guide. This project has no ORM, migrations,
transaction layer, or persistent service database.

---

## Pre-Development Checklist

Before editing backend code:

1. Read this index and the specific guideline matching the module you will touch.
2. Use GitNexus query/context for unfamiliar flows before changing behavior.
3. Search for an existing pattern before adding a new helper, parser, prompt, or flag.
4. Keep examples and commands compatible with `uv run`.
5. Preserve the flat layout unless the task explicitly requires packaging changes.
6. For packaged `or-llm-agent` CLI work, read [CLI Contracts](./cli-contracts.md).

Example flow from `or_llm_eval.py`:

```python
if args.agent:
    is_solve_success, llm_result = or_llm_agent(user_question, model_name)
else:
    is_solve_success, llm_result = gpt_code_agent_simple(user_question, model_name)

pass_flag, correct_flag = eval_model_result(is_solve_success, llm_result, answer)
```

Example shared utility import from `or_llm_eval.py`:

```python
from utils import (
    is_number_string,
    convert_to_number,
    extract_best_objective,
    extract_and_execute_python_code,
    eval_model_result
)
```

---

## Anti-Patterns

- Do not add a database abstraction. Dataset input is JSON/JSONL and output is
  stdout or files under paths such as `logs/`.
- Do not create a new entry-point script when an existing sync, async, MCP, or
  reporting entry point can be extended.
- Do not call LLM SDKs directly from new deep helper functions without matching
  the project message format and return conventions.
- Do not execute generated Python with `exec` or `eval`; use the subprocess
  patterns documented in `code-execution.md`.
- Do not introduce source examples in these specs without a real repository path.
