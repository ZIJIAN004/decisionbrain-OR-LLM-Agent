"""Run OR-LLM-Agent on one FrontierOR task.

The method itself is untouched: this calls or_llm_agent(), which carries the
three prompted steps and the repair rounds. What changes is where the data
lives and how the model reaches it.

Two mechanisms are worth naming, because both are additions rather than
configuration:

1. The first LLM call of the task gets tools. or_llm_agent issues its calls in a
   fixed order and the first one is the modelling step (or_llm_eval.py:83), so
   the tool loop is attached by replacing or_llm_eval.query_llm with a wrapper
   that is stateful for exactly one call and then defers to the original for
   every later call -- writing the Gurobi code and repairing it are unchanged.

2. The process runs with the workspace as its working directory. The generated
   program is executed with subprocess.run and no cwd argument
   (utils.py: extract_and_execute_python_code), so it inherits this one, which
   is what lets the program open "instance.json" by relative path without any
   real filesystem path ever appearing in a prompt.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import config, tools
from .tool_loop import query_llm_with_tools
from .workspace import Workspace


def run(paper_id: str, case: dict, model_name: str, log_path: Path | None = None) -> dict:
    workspace = config.stage_workspace(paper_id, case["instance_index"])
    question = config.build_question(paper_id)

    tool_log: list[dict] = []

    def record(name: str, arguments: str, result: str) -> None:
        # The full exchange is kept so it can be checked afterwards that the
        # agent only ever looked inside its own workspace.
        tool_log.append({"tool": name, "arguments": arguments, "result": result[:4000]})

    config.ensure_import_path()
    import or_llm_eval

    original_query_llm = or_llm_eval.query_llm
    state = {"first": True}
    box = Workspace(workspace)
    call_tool = tools.dispatcher(box)

    def query_llm(messages, model_name=model_name, temperature=0.2):
        if state["first"]:
            state["first"] = False
            return query_llm_with_tools(
                messages,
                model_name=model_name,
                tool_schemas=tools.schemas(),
                call_tool=call_tool,
                temperature=temperature,
                on_call=record,
            )
        return original_query_llm(messages, model_name=model_name, temperature=temperature)

    previous_cwd = Path.cwd()
    or_llm_eval.query_llm = query_llm
    started = time.time()
    try:
        os.chdir(workspace)
        success, objective = or_llm_eval.or_llm_agent(question, model_name)
    finally:
        or_llm_eval.query_llm = original_query_llm
        os.chdir(previous_cwd)

    record_out = {
        "paper_id": paper_id,
        "model": model_name,
        "success": bool(success),
        "objective": objective,
        "tool_calls": len(tool_log),
        "wall_s": round(time.time() - started, 1),
        "instance_bytes": case["instance_bytes"],
        "formulation_type": case["formulation_type"],
    }
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps({"result": record_out, "tool_log": tool_log}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return record_out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem", required=True, help="paper_id from the suite index")
    parser.add_argument("--model", default=os.environ.get("LLM_CHAT_MODEL", "deepseek-v4-flash"))
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="defaults to a new single-<timestamp>/logs/<problem>.json under the runs root",
    )
    args = parser.parse_args()

    cases = config.load_cases()
    if args.problem not in cases:
        parser.error(f"unknown problem {args.problem!r}; not in {config.INDEX_JSON}")

    # A run always leaves a record. The scheduler passes an explicit path so all
    # of its tasks land in one run folder; a bare single-task run gets its own.
    log_path = args.log or (config.new_run_dir("single") / "logs" / f"{args.problem}.json")
    print(f"log: {log_path}", file=sys.stderr, flush=True)

    result = run(args.problem, cases[args.problem], args.model, log_path)
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
