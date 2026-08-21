"""Paths, staging and the prompt block for the FrontierOR adaptation."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

INDEX_JSON = Path(
    os.environ.get(
        "FRONTIEROR_INDEX",
        "/home/bhz/Decision Brain/benchmarks/frontieror-large-all/index.json",
    )
)
INSTANCE_ROOT = Path(os.environ.get("FRONTIEROR_INSTANCE_ROOT", "/home/bhz/FrontierOR_all"))
PROBLEM_ROOT = Path(
    os.environ.get("FRONTIEROR_PROBLEM_ROOT", "/home/bhz/Decision Brain/benchmarks/frontieror")
)
WORKSPACE_ROOT = Path(os.environ.get("ADAPTER_WORKSPACE_ROOT", REPO_ROOT / "workspaces"))

TOTAL_BUDGET_GB = int(os.environ.get("ADAPTER_TOTAL_BUDGET_GB", "100"))
JOBS = int(os.environ.get("ADAPTER_JOBS", "4"))
TASK_TIMEOUT_SECONDS = int(os.environ.get("ADAPTER_TASK_TIMEOUT", "7200"))

INSTANCE_FILENAME = "instance.json"

# The only text this adaptation authors. Both paragraphs exist because of how
# the harness works, not because of anything about the problems:
#
#   * the generated program is written to a temp file and run with the parent's
#     working directory (utils.py: extract_and_execute_python_code), which is
#     the workspace, so a relative path resolves and no real path is exposed;
#   * the objective is recovered by matching "Best objective", "Optimal
#     objective" or "Optimal cost" in stdout (utils.py: extract_best_objective),
#     so a silenced solver log is read as "no solution found" even when the
#     model solved the instance correctly.
POINTER_BLOCK = f"""

---

The numeric data for this problem is not included above. It is in the file
`{INSTANCE_FILENAME}` in your working directory, which you can inspect with the
tools available to you before deciding on a model.

Two requirements for the program you will write later:

1. Load the data at run time from `{INSTANCE_FILENAME}` using that relative path.
   Do not copy values into the source, and do not assume any other location.
2. Leave the Gurobi solver log on. Do not set `OutputFlag` to 0 or otherwise
   suppress output; the objective value is read from the solver log.
"""


def load_cases() -> dict:
    with INDEX_JSON.open(encoding="utf-8") as handle:
        return json.load(handle)["cases"]


def instance_path(paper_id: str, instance_index: int) -> Path:
    return INSTANCE_ROOT / paper_id / "instance" / f"large_instance_{instance_index}.json"


def problem_md_path(paper_id: str) -> Path:
    return PROBLEM_ROOT / paper_id / "input" / "problem.md"


def stage_workspace(paper_id: str, instance_index: int) -> Path:
    """Build a directory containing the instance and nothing else.

    The reference solution lives in a sibling directory of the real instance
    (`<paper_id>/gurobi_solution/`) and the hidden checker and reference
    formulation live beside the problem statement, so the agent is given a copy
    and is never told where it came from.
    """
    workspace = WORKSPACE_ROOT / paper_id
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)

    # A copy, not a link: the agent has a shell, and a hard link or symlink
    # would let a stray write reach the original benchmark data through the
    # same inode. The largest instance is 1.8 GB against 776 GB free.
    source = instance_path(paper_id, instance_index)
    target = workspace / INSTANCE_FILENAME
    shutil.copyfile(source, target)
    target.chmod(0o444)
    return workspace


def build_question(paper_id: str) -> str:
    return problem_md_path(paper_id).read_text(encoding="utf-8").rstrip() + POINTER_BLOCK
