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

PROBLEM_METADATA_TEMPLATE: dict[str, Any] = {
    "id": "<problem_id>",
    "problem_type": "LP",
    "instance": {
        "<sets_or_indices>": ["<item_1>", "<item_2>"],
        "<objective_coefficient_field>": {"<index>": 0.0},
        "<resource_or_requirement_field>": {"<index>": 0.0},
    },
    "metamorphic": {
        "cost_scaling": {
            "coefficient_paths": ["instance.<objective_coefficient_field>"],
            "factors": [2.0],
            "tolerance_abs": 1e-6,
            "tolerance_rel": 1e-6,
        },
        "constraint_relaxation": {
            "relaxations": [
                {
                    "name": "capacity_increase",
                    "paths": ["instance.<resource_or_requirement_field>"],
                    "factor": 1.2,
                    "objective_relation": "non_decrease",
                }
            ],
            "tolerance_abs": 1e-6,
            "tolerance_rel": 1e-6,
        },
    },
}


def build_problem_metadata_template(problem_id: str) -> str:
    template = json.loads(json.dumps(PROBLEM_METADATA_TEMPLATE))
    template["id"] = problem_id
    return json.dumps(template, ensure_ascii=False, indent=2)


def build_problem_spec_prompt(problem_id: str, statement: str) -> str:
    return f"""Problem id: {problem_id}

Natural language problem statement:
{statement}

Generate exactly one JSON object matching this OR-CI problem metadata template:

```json
{build_problem_metadata_template(problem_id)}
```

Rules:
- Output only one JSON object. Do not include markdown, commentary, or Python.
- Use the provided problem id as the `id`.
- Put all model data needed by solver code under `instance`.
- Preserve primitive statement quantities under `instance`. If the statement gives separate profit and transport cost, keep both fields; do not replace them only with a derived net-benefit field.
- Derived fields may be included only when the primitive fields used to derive them are also present.
- Include `metamorphic.cost_scaling` with at least one numeric objective coefficient path.
- Point `cost_scaling.coefficient_paths` at primitive objective coefficients where practical. For profit-minus-cost objectives, include both profit and cost coefficient paths.
- Add `metamorphic.constraint_relaxation` only when the statement has a clear resource, demand, supply, or capacity value whose relaxation direction is defensible.
- Each `constraint_relaxation.relaxations[]` entry must use `name`, `paths`, `factor`, and `objective_relation`; do not use `path`, `amount`, or `direction`.
- `paths` must be a non-empty list of JSON paths under `instance`, and `factor` must be a positive multiplier such as `1.1` for a resource increase or `0.9` for a requirement decrease.
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
