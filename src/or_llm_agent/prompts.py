from __future__ import annotations

import json
from typing import Any


OR_CI_SYSTEM_PROMPT = (
    "You are an operations research modeling code generator. "
    "Produce a single Python module that implements the OR-CI submission contract."
)

PROBLEM_SPEC_SYSTEM_PROMPT = (
    "You are an operations research metadata generator. "
    "Produce one OR-CI-compatible problem metadata JSON object."
)


def build_problem_spec_prompt(problem_id: str, statement: str) -> str:
    return f"""Problem id: {problem_id}

Natural language problem statement:
{statement}

Generate exactly one JSON object matching the OR-CI problem metadata shape:

```json
{{
  "id": "{problem_id}",
  "problem_type": "LP",
  "instance": {{}},
  "metamorphic": {{
    "cost_scaling": {{
      "coefficient_paths": ["instance.<objective_coefficient_field>"],
      "factors": [2.0],
      "tolerance_abs": 1e-6,
      "tolerance_rel": 1e-6
    }}
  }}
}}
```

Rules:
- Output only one JSON object. Do not include markdown, commentary, or Python.
- Use the provided problem id as the `id`.
- Put all model data needed by solver code under `instance`.
- Include `metamorphic.cost_scaling` with at least one numeric objective coefficient path.
- Add `metamorphic.constraint_relaxation` only when the statement has a clear resource, demand, supply, or capacity value whose relaxation direction is defensible.
- Valid `constraint_relaxation.relaxations[].objective_relation` values are: `non_decrease`, `increase`, `non_increase`, `decrease`.
- Omit `evaluation_only` unless a trusted reference answer is explicitly supplied in the statement.
- Prefer simple JSON numbers, strings, lists, and nested objects that are easy for Python/Gurobi code to consume.
"""


def build_or_ci_prompt(problem_id: str, record: dict[str, Any], problem: dict[str, Any]) -> str:
    question = record.get("en_question") or record.get("cn_question") or ""
    return f"""Problem id: {problem_id}

Natural language problem:
{question}

OR-CI instance data passed to build_model(data):
```json
{json.dumps(problem["instance"], ensure_ascii=False, indent=2)}
```

Metamorphic verifier configuration:
```json
{json.dumps(problem.get("metamorphic", {}), ensure_ascii=False, indent=2)}
```

Write one Python module with exactly this public contract:

```python
import gurobipy as gp
from gurobipy import GRB

def build_model(data: dict) -> gp.Model:
    ...
```

Rules:
- Return an unoptimized gurobipy.Model.
- Do not call optimize().
- Do not print output.
- Do not read files, call APIs, or use external packages other than gurobipy.
- Do not hard-code the known optimal objective value or solution.
- Use the values in data, not copied constants, so transformed OR-CI data changes the model.
- Do not use evaluation_only fields; they are not passed to build_model.
- Output only a fenced python code block.
"""
