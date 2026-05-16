from __future__ import annotations

import json
from typing import Any


OR_CI_SYSTEM_PROMPT = (
    "You are an operations research modeling code generator. "
    "Produce a single Python module that implements the OR-CI submission contract."
)


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

