# OR-LLM-Agent Feature-Family Pilot Summary

Date: 2026-05-25

## Scope

This report summarizes the runnable post-merge pilot experiments for the
OR-CI feature-family integration in OR-LLM-Agent.

The run used the clean BWOR experiment input contract:

```text
/Users/zhangbowen/Projects/OR/code/or_llm_agent/data/datasets/bwor_run.jsonl
```

Each row contains only:

- `id`
- `en_question`
- `answer`

Only `id` and `en_question` are prompt-visible. `answer` is evaluator-only.

## Experiments Run

### 1. Clean Six-Case Feature-Family Pilot

Command:

```bash
uv run or-llm-agent solve-batch \
  --mode agent \
  --ids BWOR-012 BWOR-014 BWOR-015 BWOR-032 BWOR-067 BWOR-071 \
  --artifact-dir ../or-ci/artifacts/pilot/or-llm-agent-feature-family-integration-2026-05-25-final \
  --agent-concurrency 2 \
  --codex-sandbox workspace-write \
  --codex-approval never \
  --codex-timeout-seconds 900
```

Artifact root:

```text
/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/or-llm-agent-feature-family-integration-2026-05-25-final/
```

Aggregate result:

- Total cases: 6
- OR-CI `SUCCESS` / `PASS`: 2
- Blocked at capability gate as `needs_human`: 4
- LLM fidelity accepted among generated cases: 2

Case matrix:

| Case | Capability | Spec | Model | OR-CI | Fidelity Gate | Interpretation |
|---|---|---|---|---|---|---|
| `BWOR-012` | `needs_human` | skipped | skipped | skipped | `blocked_capability` | strict inequality and priority semantics need clarification |
| `BWOR-014` | `needs_human` | skipped | skipped | skipped | `blocked_capability` | goal-programming scalarization is underspecified |
| `BWOR-015` | `needs_human` | skipped | skipped | skipped | `blocked_capability` | prioritized goal-programming semantics are underspecified |
| `BWOR-032` | `needs_human` | skipped | skipped | skipped | `blocked_capability` | classifier requested inventory/timing clarification |
| `BWOR-067` | `supported` | passed | generated | `SUCCESS` / `PASS` | `llm_accepted` | QP quadratic-objective path works |
| `BWOR-071` | `supported` | passed | generated | `SUCCESS` / `PASS` | `llm_accepted` | QP quadratic-objective path works |

### 2. Corrected Multi-Scenario Rerun

The first full targeted run showed the multi-scenario path could pass OR-CI, but
one generated `BWOR-032` spec collapsed the two requested outcomes into a
single LP. The prompt was tightened to require `MULTI_SCENARIO` when a
statement asks for a base infeasible case plus a modified feasible case.

Command:

```bash
uv run or-llm-agent solve-batch \
  --mode agent \
  --ids BWOR-032 \
  --artifact-dir ../or-ci/artifacts/pilot/or-llm-agent-feature-family-integration-2026-05-25-bwor032-rerun \
  --agent-concurrency 1 \
  --codex-sandbox workspace-write \
  --codex-approval never \
  --codex-timeout-seconds 900
```

Artifact root:

```text
/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/or-llm-agent-feature-family-integration-2026-05-25-bwor032-rerun/
```

Result:

- Capability: `supported`
- ProblemSpec: `problem_type: "MULTI_SCENARIO"`
- Required scenarios: 2
- Spec validation: `passed`
- Model generation: `generated`
- OR-CI: `SUCCESS` / `PASS`
- Fidelity gate: `llm_accepted`

The OR-CI report records two scenario models:

- `scenario_in_house_warehouse_only`
- `scenario_external_warehouse_rental_allowed`

### 3. Clarification-Question Pilot

Command:

```bash
uv run or-llm-agent prepare-clarification-batch \
  --artifact-dir ../or-ci/artifacts/pilot/or-llm-agent-feature-family-integration-2026-05-25-final \
  --codex-sandbox workspace-write \
  --codex-approval never \
  --codex-timeout-seconds 900
```

Artifacts:

```text
/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/or-llm-agent-feature-family-integration-2026-05-25-final/clarification-summary.json
/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/or-llm-agent-feature-family-integration-2026-05-25-final/clarification-report.md
```

Result:

- Attempted `needs_human` cases: 4
- Generated questions: 12
- Answered questions: 0
- Clarification gate: `awaiting_answers` for all 4

Generated question counts:

- `BWOR-012`: 2 questions
- `BWOR-014`: 3 questions
- `BWOR-015`: 3 questions
- `BWOR-032`: 4 questions

No clarified solves were run because there are no human-approved answers yet.

### 4. Fidelity Review Pilot

Commands:

```bash
uv run or-llm-agent review-fidelity-batch \
  --mode agent \
  --artifact-dir ../or-ci/artifacts/pilot/or-llm-agent-feature-family-integration-2026-05-25-final \
  --ids BWOR-067 BWOR-071 \
  --codex-sandbox workspace-write \
  --codex-approval never \
  --codex-timeout-seconds 900

uv run or-llm-agent review-fidelity-batch \
  --mode agent \
  --artifact-dir ../or-ci/artifacts/pilot/or-llm-agent-feature-family-integration-2026-05-25-bwor032-rerun \
  --ids BWOR-032 \
  --codex-sandbox workspace-write \
  --codex-approval never \
  --codex-timeout-seconds 900
```

Result:

| Case | Fidelity Gate | Confidence | Issue Count |
|---|---|---:|---:|
| `BWOR-067` | `llm_accepted` | 0.96 | 0 |
| `BWOR-071` | `llm_accepted` | 0.94 | 1 |
| `BWOR-032` rerun | `llm_accepted` | 0.92 | 0 |

These are automated LLM fidelity reviews, not human certification.

## Implementation Notes

During the pilot, `review-fidelity-batch --ids` was found to rewrite the batch
aggregate report using only the reviewed subset. This was fixed so subset review
updates the requested cases while rebuilding the aggregate report across the
whole batch.

Regression test added:

```text
test_review_fidelity_batch_with_ids_preserves_unreviewed_rows
```

## Verification

Local verification after implementation and pilot fixes:

```bash
uv run python -m unittest discover
uv run python -m compileall src/or_llm_agent tests scripts
uv run or-llm-agent --help
uv run or-llm-agent solve-batch --help
git diff --check
```

Observed result:

- Unit tests: 61 passed
- Compileall: passed
- CLI help smoke checks: passed
- Diff whitespace check: passed

## Main Finding

The runnable pilots support this current interpretation:

1. OR-LLM-Agent can now use OR-CI's QP quadratic-objective support from
   statement-only input for `BWOR-067` and `BWOR-071`.
2. The corrected prompt can produce a true OR-CI `MULTI_SCENARIO` spec for
   `BWOR-032`, and OR-CI verifies both required scenarios.
3. Goal-programming cases remain blocked when the source statement does not
   specify weights, priorities, aspiration targets, or deviation semantics
   clearly enough.
4. The clarification workflow can now generate concrete human questions for
   these blocked cases, but cannot continue to solved clarified runs until those
   answers are supplied.

## Next Blocked Step

To continue beyond the runnable pilots, answer the clarification questions for:

- `BWOR-012`
- `BWOR-014`
- `BWOR-015`
- `BWOR-032`

Then run:

```bash
uv run or-llm-agent solve-clarified-batch \
  --artifact-dir ../or-ci/artifacts/pilot/or-llm-agent-feature-family-integration-2026-05-25-final \
  --clarifications-dir <answers-dir> \
  --ids BWOR-012 BWOR-014 BWOR-015 BWOR-032
```
