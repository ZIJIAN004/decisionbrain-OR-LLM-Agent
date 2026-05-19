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

CAPABILITY_SYSTEM_PROMPT = (
    "You are an operations research capability classifier. "
    "Decide whether the current OR-CI ProblemSpec and verifier can faithfully handle a problem statement."
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


def build_statement_capability_prompt(problem_id: str, statement: str) -> str:
    return f"""Problem id: {problem_id}

Natural language problem statement:
{statement}

Classify whether the current OR-CI workflow can safely automate this statement.

Current supported target:
- deterministic, numeric, single-objective linear optimization models;
- LP/MILP-style variables and linear constraints that Gurobi can expose through the current linear ModelIR;
- all objective coefficients, bounds, capacities, demands, and requirements are explicit numeric data;
- objective direction and all constraint families can be represented without inventing semantics.

Current unsupported or needs-human triggers:
- symbolic coefficients without numeric values, such as c_j;
- source contradictions, missing required data, or unit ambiguity;
- strict inequalities whose intended modeling treatment is not explicit;
- multi-objective, goal-programming, lexicographic objective, preemptive-priority, or achievement-function semantics;
- nonlinear, quadratic, conic, stochastic, robust, dynamic, or simulation-based formulations;
- solver features OR-CI currently rejects, including multiple objectives, quadratic terms or constraints, SOS, general constraints, and piecewise-linear objectives.

Return exactly one JSON object with this shape:

```json
{{
  "status": "supported",
  "problem_family": "short family label",
  "supported_features": ["features the current pipeline can handle"],
  "unsupported_features": ["features that block faithful automation"],
  "missing_information": ["missing or ambiguous source facts"],
  "recommended_next_action": "continue_to_problemspec | ask_human | extend_schema_or_verifier",
  "confidence": 0.0,
  "review_note": "short rationale"
}}
```

Decision rules:
- The `status` value must be exactly one of `supported`, `needs_human`, or `unsupported`.
- Use `supported` only when the statement can be faithfully represented by the current OR-CI ProblemSpec and verified as a generated-spec LP/MILP workflow.
- Use `needs_human` when the problem might be representable after clarification but the statement has missing, symbolic, contradictory, or ambiguous information.
- Use `unsupported` when the problem requires semantics outside the current ProblemSpec/verifier support.
- Do not solve the problem. Do not generate a ProblemSpec. Only classify capability.
- Output only one JSON object. Do not include markdown or commentary.
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
