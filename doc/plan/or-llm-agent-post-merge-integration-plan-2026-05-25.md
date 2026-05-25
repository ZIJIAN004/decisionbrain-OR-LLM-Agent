# OR-LLM-Agent Post-Merge Integration Plan

Date: 2026-05-25

## Purpose

Define the next OR-LLM-Agent work after the reviewed
`feature/needs-human-clarification-workflow` branch was merged to `main`.

This document records the integration order, input contract, and pilot gates
needed before the next large-scale run.

## Current State

`main` now includes the needs-human clarification workflow merge:

```text
aa118ad Merge needs-human clarification workflow
```

OR-CI now supports more deterministic verifier families:

- linear LP/MILP checks from the original pipeline
- QP/MIQP cases with quadratic objectives
- weighted and lexicographic goal-programming metadata
- multi-scenario cases with per-scenario solver-status and objective checks

The targeted OR-CI feature-extension pilot passed 6 / 6 cases. The artifact
root is:

```text
/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/or-ci-feature-family-extensions-2026-05-23/
```

The original integration gap was on the OR-LLM-Agent side: its statement
capability prompt and ProblemSpec-generation prompt still described the main
supported surface as linear LP/MILP and still treated several newly supported
families as unsupported.

Implementation update on 2026-05-25:

- `solve-batch` now defaults to a clean BWOR run dataset.
- Prompt builders are covered by regression tests that prevent leaking
  evaluator answers or analysis labels.
- Capability and ProblemSpec prompts now describe QP/MIQP quadratic-objective,
  goal-programming, and multi-scenario metadata contracts.
- Model-generation prompts now render multi-scenario metadata without assuming
  a top-level `instance`.

## Merge Verification Gate

The review branch has been merged. Keep this historical merge command for
traceability:

```bash
git merge --ff-only feature/needs-human-clarification-workflow
```

Run post-merge smoke checks:

```bash
uv run python -m unittest discover
uv run python -m compileall src/or_llm_agent tests
uv run or-llm-agent --help
uv run or-llm-agent solve --help
uv run or-llm-agent solve-batch --help
```

Do not start the next feature implementation until these checks pass, because
the next work will likely touch `cli.py`, `prompts.py`, and
ProblemSpec-generation tests.

## Experiment Input Contract

For statement-only experiments, the agent-visible input should contain only the
source statement.

Create a dedicated BWOR run file before the next pilot:

```text
/Users/zhangbowen/Projects/OR/code/or_llm_agent/data/datasets/bwor_run.jsonl
```

Allowed fields:

- `id`
- `en_question`
- `answer`

Prompt-visible fields:

- `id`
- `en_question`

Evaluator-only fields:

- `answer`

Disallowed from prompts and generated `problem.json`:

- `answer`
- `problem_type`
- `difficulty`
- `domain`
- `solution_status`

The full BWOR dataset can still be used later for analysis, but type,
difficulty, domain, and other labels must be joined by `id` after generation
and verification.

## Integration Tasks

1. Run post-merge smoke checks.
2. Add a clean BWOR run-file builder and schema check for `bwor_run.jsonl`.
3. Update capability routing so newly supported OR-CI feature families are not
   automatically blocked when the statement provides enough semantics.
4. Update ProblemSpec-generation prompts and templates for:
   - quadratic-objective QP/MIQP
   - weighted goal programming
   - lexicographic goal programming
   - multi-scenario verification
5. Add regression tests proving the prompt builders do not expose dataset
   labels or answers.
6. Run targeted statement-only pilots on the recovered feature-extension cases.
7. Run a larger 50-case or 82-case pilot after targeted cases pass.

Tasks 1-6 have been implemented or run. Task 7 remains pending.

## Pilot Order

Use this sequence:

1. `needs_human` post-merge smoke test.
2. Clean run-file generation and prompt-isolation test.
3. Targeted feature-family rerun:
   - `BWOR-012`
   - `BWOR-014`
   - `BWOR-015`
   - `BWOR-032`
   - `BWOR-067`
   - `BWOR-071`
4. Clarification pilot on a small `needs_human` subset.
5. 50-case layered-verification pilot.
6. 82-case full BWOR pilot if the 50-case run does not expose a structural
   process failure.

## Verification Checklist

- [x] Claude review completed or explicitly deferred.
- [x] `feature/needs-human-clarification-workflow` merged cleanly.
- [x] Unit tests pass after merge.
- [x] CLI help smoke checks pass after merge.
- [x] `bwor_run.jsonl` exists with only `id`, `en_question`, and `answer`.
- [x] Prompt builders are tested against leaking `answer` or dataset labels.
- [x] Capability prompt lists newly supported OR-CI feature families.
- [x] ProblemSpec prompt can produce metadata for the new feature families.
- [x] Targeted feature-family statement-only pilot completed; QP/MIQP and
      multi-scenario supported cases passed OR-CI, while underspecified
      goal-programming statements correctly remained `needs_human`.
- [ ] Clarification pilot report is generated.
- [ ] Next 50-case or 82-case report separates verifier pass, source-fidelity
      pass, clarification recovery, and evaluator answer accuracy.

## Report Capstone

The next report should include:

- input-isolation evidence
- capability-routing distribution
- feature-family recovery count
- `needs_human` clarification recovery count
- OR-CI verification outcomes
- source-fidelity outcomes
- answer scoring as a post-hoc evaluator-only metric
- remaining unsupported families and why they are intentional limits

## Pilot Result

Targeted six-case run:

```text
/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/or-llm-agent-feature-family-integration-2026-05-25/
```

Result:

- `BWOR-012`: `needs_human`, blocked before ProblemSpec generation.
- `BWOR-014`: `needs_human`, blocked before ProblemSpec generation.
- `BWOR-015`: `needs_human`, blocked before ProblemSpec generation.
- `BWOR-032`: `SUCCESS` / `PASS`.
- `BWOR-067`: `SUCCESS` / `PASS`.
- `BWOR-071`: `SUCCESS` / `PASS`.

Follow-up `BWOR-032` rerun after tightening the multi-scenario prompt:

```text
/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/or-llm-agent-feature-family-integration-2026-05-25-bwor032-rerun/
```

The rerun generated `problem_type: "MULTI_SCENARIO"` with two required
scenarios and OR-CI reported `PASS` / `SUCCESS`.
