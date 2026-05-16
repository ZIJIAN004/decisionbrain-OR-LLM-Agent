from __future__ import annotations

import re


PYTHON_FENCE_RE = re.compile(r"```python\s*([\s\S]*?)```", re.IGNORECASE)
BUILD_MODEL_RE = re.compile(r"^\s*def\s+build_model\s*\(", re.MULTILINE)


def extract_python_module(text: str) -> str | None:
    blocks = [match.strip() for match in PYTHON_FENCE_RE.findall(text) if match.strip()]
    if not blocks:
        return None
    return blocks[-1]


def has_build_model_contract(code: str) -> bool:
    return bool(BUILD_MODEL_RE.search(code))

