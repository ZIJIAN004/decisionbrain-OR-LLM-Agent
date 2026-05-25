# /// script
# requires-python = ">=3.10"
# ///
"""Build the statement-only BWOR run dataset for OR-LLM-Agent pilots.

The output intentionally keeps only:

  id, en_question, answer

`answer` is retained for post-hoc evaluator scoring only. OR-LLM-Agent prompts
must use only `id` and `en_question` during capability routing, ProblemSpec
generation, model generation, clarification, and fidelity review.

Run:
    uv run scripts/build_bwor_run_dataset.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from or_llm_agent.bwor import default_bwor_dataset, default_bwor_run_dataset, write_bwor_run_dataset


def main() -> None:
    source_path = default_bwor_dataset()
    output_path = default_bwor_run_dataset()
    count = write_bwor_run_dataset(source_path, output_path)
    print(f"Loaded {count} BWOR records from {source_path}")
    print(f"Wrote clean run dataset to {output_path}")


if __name__ == "__main__":
    main()
