# /// script
# requires-python = ">=3.10"
# ///
"""Convert internal BWOR.json to public-release bwor.jsonl.

Input  (BWOR.json, JSONL of 5-field records):
    en_question, cn_question, en_answer, difficulty, id

Output (bwor.jsonl, JSONL of 8-field records):
    id, en_question, cn_question, answer, solution_status, domain, problem_type, difficulty

Per-record changes:
  * id (int 0..81)               -> id (str "BWOR-001".."BWOR-082"; 1-indexed)
  * en_answer (str numeric)      -> answer (float) + solution_status ("optimal")
  * en_answer == "No Best Solution"
                                 -> answer=null + solution_status="no_optimal" (2 records)
  * domain, problem_type         -> filled from scripts.bwor_annotations.ANNOTATIONS,
                                    or null if missing (for incremental annotation work)
  * difficulty                   -> preserved verbatim
  * cn_question, en_question     -> preserved verbatim (bilingual)

Dataset-level constants (NOT stored per record; documented in data card):
  * answer_tolerance: 0.1 (absolute) -- only applies when solution_status == "optimal"
  * split: "test" (all 82 records)
  * provenance: "Hu2010 + Hu2012, translated and normalized into English"

Run:
    uv run scripts/build_bwor_release.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = REPO_ROOT / "data" / "datasets" / "BWOR.json"
OUTPUT_PATH = REPO_ROOT / "data" / "datasets" / "bwor.jsonl"
ANNOTATIONS_PATH = REPO_ROOT / "scripts" / "bwor_annotations.py"


def load_bwor() -> list[dict]:
    records = []
    with INPUT_PATH.open() as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"BWOR.json line {lineno} not valid JSON: {e}") from e
    return records


def load_annotations() -> dict[int, dict]:
    if not ANNOTATIONS_PATH.exists():
        return {}
    namespace: dict = {}
    exec(ANNOTATIONS_PATH.read_text(), namespace)
    return namespace.get("ANNOTATIONS", {})


def to_bwor_id(bwor_id: int) -> str:
    return f"BWOR-{bwor_id + 1:03d}"


def parse_answer(raw: str) -> tuple[float | None, str]:
    """Return (numeric_answer, solution_status).

    Records whose en_answer literally equals 'No Best Solution' are treated
    as no_optimal (infeasible / unbounded / no unique objective). All other
    records must parse cleanly as float.
    """
    s = raw.strip()
    if s == "No Best Solution":
        return None, "no_optimal"
    return float(s), "optimal"


def transform(record: dict, annotations: dict[int, dict]) -> dict:
    bwor_id = record["id"]
    ann = annotations.get(bwor_id, {})
    answer, status = parse_answer(record["en_answer"])
    return {
        "id": to_bwor_id(bwor_id),
        "en_question": record["en_question"],
        "cn_question": record["cn_question"],
        "answer": answer,
        "solution_status": status,
        "domain": ann.get("domain"),
        "problem_type": ann.get("problem_type"),
        "difficulty": record["difficulty"],
    }


def main() -> None:
    records = load_bwor()
    annotations = load_annotations()
    out = [transform(r, annotations) for r in records]

    annotated = sum(1 for r in out if r["domain"] is not None and r["problem_type"] is not None)
    no_optimal = sum(1 for r in out if r["solution_status"] == "no_optimal")
    print(f"Loaded {len(records)} BWOR records")
    print(f"Annotated {annotated}/{len(out)} with domain+problem_type")
    print(f"solution_status: {len(out) - no_optimal} optimal, {no_optimal} no_optimal")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
