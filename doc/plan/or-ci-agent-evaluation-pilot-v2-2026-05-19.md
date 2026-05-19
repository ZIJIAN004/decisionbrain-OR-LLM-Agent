# OR-CI Agent Evaluation Pilot v2

Date: 2026-05-19

OR-CI means Operations Research Continuous Integration. In this pilot,
`or_llm_agent` is the producer and standalone OR-CI is the verifier.

## Decision

Agent mode is ready for continued pilots, but the automated process must keep
the source-fidelity gate and the fidelity-resolution loop as required stages.

The 20-case BWOR run shows that Codex agent mode can generate OR-CI-compatible
ProblemSpecs and Gurobi submissions at this scale: all 20 cases passed metadata
validation, model generation, OR-CI verification, and parent classification.
However, initial source-statement fidelity accepted only 15 of 20 cases. The
resolution loop reduced this to one material residual case.

Do not report an end-to-end statement-to-result solve as accepted from OR-CI
`SUCCESS` alone. Treat the acceptable automated result set as:

- 15 cases initially `llm_accepted`.
- 3 cases repaired and then `llm_accepted`.
- 1 case with residual mismatch but unchanged verified objective.
- 1 case with residual material impact that remains unresolved.

## Artifact Root

`/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/`

Generated pilot artifacts are under the OR-CI artifact tree and are intentionally
not tracked by git.

## Commands

```bash
uv run or-llm-agent health --agent

uv run or-llm-agent solve-batch \
  --mode agent \
  --ids BWOR-001 BWOR-002 BWOR-003 BWOR-004 BWOR-005 \
        BWOR-006 BWOR-007 BWOR-008 BWOR-009 BWOR-010 \
        BWOR-011 BWOR-012 BWOR-013 BWOR-014 BWOR-015 \
        BWOR-016 BWOR-017 BWOR-018 BWOR-019 BWOR-020 \
  --artifact-dir ../or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case

uv run or-llm-agent review-fidelity-batch \
  --mode agent \
  --artifact-dir ../or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case

uv run or-llm-agent resolve-fidelity-batch \
  --mode agent \
  --artifact-dir ../or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case
```

## Results

| Stage | Result |
|---|---:|
| Problems | 20 |
| Spec validation `passed` | 20 |
| Model generation `generated` | 20 |
| OR-CI verification `PASS` | 20 |
| Parent classification `SUCCESS` | 20 |
| Initial fidelity `llm_accepted` | 15 |
| Initial fidelity `llm_rejected` | 5 |
| Resolution `repaired_accepted` | 3 |
| Resolution `residual_harmless_equivalent` | 1 |
| Resolution `residual_material` | 1 |

Per-case matrix:

| Problem | OR-CI | Fidelity | Resolution | Impact |
|---|---|---|---|---|
| BWOR-001 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-002 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-003 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-004 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-005 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-006 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-007 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-008 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-009 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-010 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-011 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-012 | `SUCCESS` | `llm_rejected` | `repaired_accepted` | `not_needed` |
| BWOR-013 | `SUCCESS` | `llm_rejected` | `residual_harmless_equivalent` | `harmless_equivalent` |
| BWOR-014 | `SUCCESS` | `llm_rejected` | `residual_material` | `material` |
| BWOR-015 | `SUCCESS` | `llm_rejected` | `repaired_accepted` | `not_needed` |
| BWOR-016 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-017 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-018 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-019 | `SUCCESS` | `llm_accepted` | `-` | `-` |
| BWOR-020 | `SUCCESS` | `llm_rejected` | `repaired_accepted` | `not_needed` |

## Rejection Themes

- `BWOR-012`: The source used strict composition limits, but the generated spec
  used closed bounds. The repair was accepted.
- `BWOR-013`: The source had an internally inconsistent emergency-reserve unit.
  The residual mismatch remained, but source and repaired objective values were
  both `67.5`, so impact analysis classified it as harmless-equivalent.
- `BWOR-014`: The source asked for a goal-programming model with separate
  minimization goals, but the generated model used an unstated equal-weight
  scalar objective. The repaired objective changed from `32.31944444444444` to
  `1.2083333333333333`, so this is material.
- `BWOR-015`: The generated spec invented priority coefficients for a
  prioritized goal-programming problem. The repair was accepted.
- `BWOR-020`: The source used symbolic truck costs `c_j`, but the generated spec
  invented all costs as `1.0`. The repair was accepted.

## Main Finding

OR-CI remains valuable as a deterministic verifier, but it verifies the generated
ProblemSpec, not the original natural-language statement. The pilot demonstrates
that source-fidelity review is not optional in a full automated process. Without
that gate, the run would report 20 / 20 success while hiding five statement-level
semantic mismatches.

The strongest remaining gap is multi-objective and goal-programming semantics.
For this class, the current ProblemSpec/action space can allow plausible but
source-unsound scalarizations. The correct next step is not to weaken fidelity
review; it is to either extend the ProblemSpec contract for preemptive or
multi-goal formulations, or classify those cases as unsupported / needs-human
until the representation is explicit.

## Next Work

1. Add an unsupported or needs-human classification path for source statements
   with symbolic coefficients, source ambiguities, strict inequalities, or
   multi-objective / goal-programming semantics that the current ProblemSpec
   cannot represent faithfully.
2. Extend ProblemSpec only for the semantics that are needed repeatedly in BWOR,
   starting with goal programming and preemptive priorities.
3. Keep reporting three separate statuses: OR-CI generated-spec verification,
   source-fidelity review, and fidelity-resolution impact.
4. Run the next scale pilot after the unsupported/needs-human routing is in
   place, so failures are not forced into invented numeric or scalarized specs.

## Verification

- `uv run python -m unittest discover`: 20 tests passed.
- `uv run python -m compileall src/or_llm_agent tests`: passed.
- `uv run or-llm-agent health --agent`: passed.
- `git diff --check`: passed.
- OR-CI repo status: clean; pilot artifacts remained ignored.
