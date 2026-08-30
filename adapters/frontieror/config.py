"""Paths, staging and the prompt block for the FrontierOR adaptation."""

from __future__ import annotations

import json
import os
import shutil
import sys
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
# Run output lives beside the baseline repositories rather than inside this one,
# so every baseline's results sit together under one parent and nothing a run
# produces is mixed into the checkout.
RUNS_ROOT = Path(os.environ.get("ADAPTER_RUNS_ROOT", "/home/bhz/baselines/or-llm-agent-runs"))
WORKSPACE_ROOT = Path(os.environ.get("ADAPTER_WORKSPACE_ROOT", RUNS_ROOT / "workspaces"))


def ensure_import_path() -> None:
    """Make the upstream modules importable without installing the package.

    or_llm_eval.py sits at the repository root but imports or_llm_agent, which
    is a src-layout package under src/. The baseline conda environment does not
    have it installed, so both directories go on the path.
    """
    for entry in (REPO_ROOT, REPO_ROOT / "src"):
        text = str(entry)
        if text not in sys.path:
            sys.path.insert(0, text)


def new_run_dir(tag: str = "frontieror") -> Path:
    """RUNS_ROOT/<tag>-<UTC timestamp>/ with report.jsonl and logs/ inside it."""
    import time

    run_dir = RUNS_ROOT / f"{tag}-{time.strftime('%Y%m%d-%H%M%SZ', time.gmtime())}"
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    return run_dir


# Repair budget, for the budget-controlled re-run only.
#
# or_llm_agent runs a fixed three-step script and every loop in it is a repair
# loop with a counted bound: the first solve gets max_attempts=3 by default, and
# the two fallback branches call generate_or_code_solver again with 1 and 2
# hardcoded (or_llm_eval.py:117 and :125). A task therefore gets at most five
# code generations no matter how much of its wall clock is left, and in the
# 65-instance run 18 tasks printed "Reached maximum number of attempts" -- 15 of
# the 16 tasks that ended with no candidate at all. The other 47 tasks produced
# exactly one such ending between them.
#
# Those runs averaged 852 seconds against a 7200-second budget, so what stopped
# them was the count, not the clock. Setting this raises all three call sites at
# once and leaves TASK_TIMEOUT_SECONDS as the only bound, which is the bound
# DecisionBrain runs under. Nothing is lost to a task that is still working when
# the clock runs out: candidate recovery and schema conversion run after the
# agent process ends, by design (schedule.py).
#
# 0 means "leave the upstream numbers alone", so an ordinary run is unchanged.
SOLVE_MAX_ATTEMPTS = int(os.environ.get("ADAPTER_SOLVE_MAX_ATTEMPTS", "0")) or None

TOTAL_BUDGET_GB = int(os.environ.get("ADAPTER_TOTAL_BUDGET_GB", "100"))
TOTAL_CPU_CORES = int(os.environ.get("ADAPTER_TOTAL_CPU_CORES", "24"))
JOBS = int(os.environ.get("ADAPTER_JOBS", "4"))
TASK_TIMEOUT_SECONDS = int(os.environ.get("ADAPTER_TASK_TIMEOUT", "7200"))
SOLVER_TIMEOUT_SECONDS = int(os.environ.get("ADAPTER_SOLVER_TIMEOUT", "600"))
# A formatter response is checked after each tool round. Contract errors are
# returned to the same adapter conversation for correction, up to ten rounds.
RESULT_ADAPTER_MAX_ATTEMPTS = int(os.environ.get("ADAPTER_RESULT_MAX_ATTEMPTS", "10"))

# The outer task deadline applies only to the original agent. Candidate recovery
# and schema adaptation deliberately happen after that process has stopped.
RESULT_ADAPTER_TIMEOUT_SECONDS = int(os.environ.get("ADAPTER_RESULT_TIMEOUT", "900"))

INSTANCE_FILENAME = "instance.json"


def solution_schema_path(paper_id: str) -> Path:
    return PROBLEM_ROOT / paper_id / "hidden" / "solution_schema.json"

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

3. The evaluator enforces a hard {SOLVER_TIMEOUT_SECONDS}-second limit on every
   `model.optimize()` call and saves the best incumbent whenever Gurobi reports
   `TIME_LIMIT`. Do not design the program as if unlimited solve time were available.
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

    # shutil.copy2, matching DecisionBrain's runner (benchmark/runner.py:698).
    # problem.md is not staged here: unlike DecisionBrain's agent, which reads it
    # through its tools, OR-LLM-Agent receives the statement as its prompt.
    shutil.copy2(instance_path(paper_id, instance_index), workspace / INSTANCE_FILENAME)
    return workspace


def build_question(paper_id: str) -> str:
    return problem_md_path(paper_id).read_text(encoding="utf-8").rstrip() + POINTER_BLOCK
