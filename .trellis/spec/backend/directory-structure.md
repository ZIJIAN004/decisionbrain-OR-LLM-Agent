# Directory Structure

> How backend code is organized in this project.

---

## Overview

The project is primarily a flat research-script codebase. Root scripts still
import sibling modules directly, with `utils.py` carrying shared parsing,
generated-code execution, and result evaluation helpers.

The exception is the packaged `or-llm-agent` CLI under `src/or_llm_agent/`. Use
that package only for console-script behavior, OR-CI producer workflow helpers,
provider dispatch shared by root scripts, and deterministic artifact writing.

The design is research-script oriented: entry points are executable files at the
repository root or in `scripts/`, data lives under `data/`, and the MCP wrapper
lives under `MCP/`.

---

## Directory Layout

```text
or_llm_agent/
├── or_llm_eval.py                    # sync evaluation and agent entry point
├── or_llm_eval_async_resilient.py    # async resilient batch evaluator
├── or_llm_show.py                    # streaming/show-mode console runner
├── utils.py                          # shared parsing and code execution helpers
├── src/or_llm_agent/                 # packaged CLI and OR-CI producer helpers
│   ├── cli.py                        # argparse entry point for or-llm-agent
│   ├── provider.py                   # shared OpenAI/Anthropic dispatch
│   └── *.py                          # prompts, BWOR paths, redaction, OR-CI subprocess helpers
├── MCP/
│   ├── mcp_server.py                 # FastMCP stdio server
│   └── README.md
├── data/
│   ├── datasets/                     # benchmark JSON/JSONL files
│   └── *.py                          # dataset conversion/analysis scripts
├── scripts/                          # BWOR release, plotting, evaluation tools
├── artifacts/BWOR/                   # public release docs and baselines
├── logs/                             # batch-evaluation output logs
├── pyproject.toml
└── run_eval_batch_agent.sh
```

Do not treat unrelated local folders as part of the backend architecture unless
they become committed project sources and appear in the project docs.

---

## Module Responsibilities

`or_llm_eval.py` is the synchronous baseline. It owns the three-stage agent
pipeline, CLI parsing, dataset loading, and per-record evaluation loop. Its
`query_llm` symbol is kept as a compatibility wrapper around
`or_llm_agent.provider.query_llm`.

Example from `or_llm_eval.py`:

```python
def or_llm_agent(user_question, model_name="o3", max_attempts=3):
    messages = [
        {"role": "system", "content": (
            "You are an operations research expert. Based on the optimization problem provided by the user, construct a mathematical model that effectively models the original problem using mathematical (linear programming) expressions."
        )},
        {"role": "user", "content": user_question}
    ]

    math_model = query_llm(messages, model_name)
    messages.append({"role": "assistant", "content": math_model})
```

`or_llm_eval_async_resilient.py` is the concurrent evaluator. It owns async
subprocess execution and batch summaries. Its `async_query_llm` symbol is kept as
a compatibility wrapper around `or_llm_agent.provider.async_query_llm`, which
owns async provider dispatch and retry/backoff.

Example from `or_llm_eval_async_resilient.py`:

```python
dataset_items = list(dataset.items())
batch_size = 50
total_batches = (len(dataset_items) + batch_size - 1) // batch_size
```

`utils.py` is shared by sync and show-mode flows. Keep reusable parsing and
execution logic here when both root entry points need it.

Example from `or_llm_eval.py`:

```python
from utils import (
    is_number_string,
    convert_to_number,
    extract_best_objective,
    extract_and_execute_python_code,
    eval_model_result
)
```

`MCP/mcp_server.py` is a thin adapter. It should remain focused on exposing the
sync agent as a FastMCP tool, capturing stdout, and applying a wall-clock timeout.

`src/or_llm_agent/` owns packaged console-script code. Keep command contracts in
`cli.py`, provider dispatch in `provider.py`, prompt text in `prompts.py`, OR-CI
subprocess handling in `or_ci.py`, redaction in `redaction.py`, and BWOR path or
JSONL helpers in `bwor.py`.

---

## Where New Code Belongs

- New evaluation CLI flags usually belong in `or_llm_eval.py` or
  `or_llm_eval_async_resilient.py`.
- New `or-llm-agent` console commands or OR-CI producer workflow helpers belong
  under `src/or_llm_agent/`.
- New reusable generated-code parsing belongs in `utils.py`.
- New dataset/report transformations belong in `scripts/` when they are release
  tooling, or `data/` when they convert or inspect datasets.
- New MCP behavior belongs in `MCP/mcp_server.py` only if it is tool-facing.
- New public benchmark artifacts belong under `artifacts/BWOR/`, not root scripts.

Example from `scripts/evaluate_bwor_predictions.py` showing release-tool style:

```python
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = REPO_ROOT / "data" / "datasets" / "bwor.jsonl"
DEFAULT_TOLERANCE = 0.1
```

---

## Naming Conventions

Root evaluation files use descriptive snake_case names beginning with `or_llm_`.
Utility functions use snake_case and return simple Python values or tuples.
Command-line flags use long snake-compatible names such as `--data_path`.

Dataset scripts are imperative and task-specific. Prefer names that describe the
conversion or evaluation target, as in `convert_industryOR_to_default_format.py`
and `evaluate_bwor_predictions.py`.

---

## Anti-Patterns

- Do not introduce new package namespaces or `src/` subtrees as part of a small
  feature. The existing `src/or_llm_agent/` package is reserved for the
  `or-llm-agent` console script and shared provider/OR-CI workflow helpers.
- Do not move shared helpers into an entry-point script if `utils.py` already owns
  that concern.
- Do not put MCP-specific path setup or stdout capture into core agent modules.
- Do not put benchmark release tooling into the MCP folder.
- Do not create a database directory; project state is file-based.
