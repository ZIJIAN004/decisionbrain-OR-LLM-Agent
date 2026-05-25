# OR-LLM-Agent Needs-Human Clarification Workflow Plan

Date: 2026-05-23

## Purpose

Add a controlled clarification loop for cases classified as `needs_human`.

The goal is to recover cases blocked by missing data, ambiguous objectives,
contradictory units, timing conventions, or modeling choices without letting
the LLM invent assumptions. Clarified cases should remain traceable from the
original source statement to explicit clarification answers, then to the
generated ProblemSpec, generated model, OR-CI report, and fidelity review.

This plan belongs in OR-LLM-Agent because the main work is CLI orchestration,
agent prompting, artifact management, and batch reporting. OR-CI remains the
deterministic verifier that consumes the generated metadata and submission.

## Baseline

The 82-case agent-mode BWOR pilot produced:

- 82 total cases.
- 61 `SUCCESS` / `PASS` cases.
- 21 `blocked_capability` cases.
- 13 `needs_human` cases.
- 8 `unsupported` cases.

The first clarification workflow should target the `needs_human` cases that
appear blocked by source ambiguity rather than missing verifier feature support.

Initial clarification-only target cases:

- `BWOR-004`
- `BWOR-008`
- `BWOR-013`
- `BWOR-020`
- `BWOR-024`
- `BWOR-027`
- `BWOR-030`
- `BWOR-038`
- `BWOR-041`
- `BWOR-046`
- `BWOR-069`
- `BWOR-072`

Keep `BWOR-035` separate because clarification may still leave a nonlinear or
probabilistic verification gap.

## Workflow Goal

Convert `needs_human` from a terminal block into a governed state transition:

1. The classifier blocks a case as `needs_human`.
2. OR-LLM-Agent generates explicit clarification questions from the classifier
   result and source statement.
3. A reviewer supplies answers with provenance.
4. OR-LLM-Agent validates that required answers exist.
5. OR-LLM-Agent reruns ProblemSpec generation using the original statement plus
   clarification answers.
6. The generated model is verified by OR-CI.
7. Fidelity review is run against the original statement plus clarification
   context.

The workflow must never silently convert an ambiguity into an assumption.

## CLI Contract

Add single-case commands:

```bash
uv run or-llm-agent prepare-clarification \
  --artifact-dir <case-dir> \
  --out <questions.json>

uv run or-llm-agent answer-clarification \
  --artifact-dir <case-dir> \
  --answers <answers.json> \
  --reviewer <name>

uv run or-llm-agent solve-clarified \
  --artifact-dir <case-dir> \
  --clarification <answers.json> \
  --resolution-dir <dir>
```

Add batch commands:

```bash
uv run or-llm-agent prepare-clarification-batch \
  --artifact-dir <batch-dir> \
  [--ids <BWOR-ID>...]

uv run or-llm-agent solve-clarified-batch \
  --artifact-dir <batch-dir> \
  --clarifications-dir <dir> \
  [--ids <BWOR-ID>...]
```

Batch commands should process only `needs_human` cases by default when `--ids`
is omitted.

## Clarification Artifact Contract

Question artifact:

```json
{
  "problem_id": "BWOR-013",
  "source_artifact": "path/to/BWOR-013",
  "blocking_status": "needs_human",
  "questions": [
    {
      "id": "q1",
      "issue_type": "unit_conflict",
      "prompt": "Which reserve requirement should be used?",
      "source_evidence": "The statement says 10% of 1000 thousand yuan, but also says 1 million yuan.",
      "allowed_answer_type": "single_choice",
      "options": ["100 thousand yuan", "1 million yuan"],
      "required": true
    }
  ]
}
```

Answer artifact:

```json
{
  "problem_id": "BWOR-013",
  "answers": [
    {
      "question_id": "q1",
      "answer": "100 thousand yuan",
      "reviewer": "human",
      "rationale": "10% of 1000 thousand yuan is 100 thousand yuan.",
      "source": "manual_review"
    }
  ],
  "resolution_status": "answered"
}
```

Supported `issue_type` values:

- `missing_numeric_data`
- `ambiguous_objective`
- `unit_conflict`
- `domain_choice`
- `timing_convention`
- `data_conflict`
- `modeling_convention`

Supported `resolution_status` values:

- `answered`
- `partially_answered`
- `rejected`
- `unresolved`

## Execution Rules

- Do not overwrite the original blocked artifact.
- Write clarified runs under a separate resolution directory.
- Refuse to continue if any required question is unanswered.
- Preserve original classifier output.
- Pass both original statement and approved clarification answers to the
  ProblemSpec generation prompt.
- Mark the generated ProblemSpec as clarified, not source-only.
- Fidelity review must read the clarification artifact and report whether the
  generated model matches the clarified source.

Required summary fields:

- `clarified_from`
- `clarification_status`
- `clarification_question_count`
- `clarification_answer_count`
- `clarification_source`
- `clarification_gate_status`

## Implementation Checklist

- [x] Add question and answer dataclasses or typed dictionaries.
- [x] Add JSON loader and validator for question artifacts.
- [x] Add JSON loader and validator for answer artifacts.
- [x] Add `prepare-clarification`.
- [x] Add `answer-clarification`.
- [x] Add `solve-clarified`.
- [x] Add `prepare-clarification-batch`.
- [x] Add `solve-clarified-batch`.
- [x] Add prompt text for clarification-question generation.
- [x] Add prompt text for clarified ProblemSpec generation.
- [x] Update solve summaries with clarification fields.
- [x] Update batch summaries with clarification metrics.
- [x] Update fidelity review input assembly to include clarification artifacts.
- [x] Update CLI help text and Trellis CLI contract notes.

## Verification Checklist

- [x] Unit test question schema validation.
- [x] Unit test answer schema validation.
- [x] Unit test required unanswered questions block `solve-clarified`.
- [x] Unit test answered required questions allow `solve-clarified`.
- [x] Unit test original blocked artifacts are not overwritten.
- [x] Unit test batch selection processes only `needs_human` cases by default.
- [x] Golden test for `BWOR-013` unit conflict.
- [x] Golden test for `BWOR-020` missing numeric truck costs.
- [x] Golden test for `BWOR-027` route return and distance convention.
- [x] Golden test for `BWOR-046` infeasible capacity-demand ambiguity.
- [ ] Pilot 4 clarified cases before running all target cases.
- [ ] Pilot all 12 clarification-only target cases.
- [x] Confirm unresolved cases remain blocked rather than guessed.

Progress note: live question-prep was run for the four capstone cases
`BWOR-013`, `BWOR-020`, `BWOR-027`, and `BWOR-046` under
`outputs/runtime/needs-human-clarification-pilot-4case/`. Full target
question-prep was also run for all 12 clarification-only cases under
`outputs/runtime/needs-human-clarification-pilot-12case/`. The full target run
produced 25 reviewer questions and left all 12 cases at `awaiting_answers`; the
clarified solve pilot still requires reviewer answer artifacts. Safe unresolved
answer templates for those 12 cases were generated under
`outputs/runtime/needs-human-clarification-pilot-12case/answer-templates/`.
An unresolved-gate run was also executed in
`outputs/runtime/needs-human-clarification-pilot-12case-unresolved-gate/`; all
12 cases were classified as `blocked_clarification`, OR-CI was skipped, and no
clarified artifacts were produced.

## Report Capstone Checklist

Generate:

```text
clarification-report.md
clarification-summary.json
```

The Markdown report must include:

- [x] Baseline blocked reason for each attempted case.
- [x] Generated question set.
- [x] Answer provenance.
- [x] Clarified rerun status.
- [x] OR-CI verification status.
- [x] Fidelity status against original statement plus clarification.
- [x] Unresolved cases.
- [x] Cases that moved from `needs_human` to supported.

The summary JSON must include:

- [x] attempted `needs_human` count.
- [x] generated question count.
- [x] answered question count.
- [x] clarified-supported case count.
- [x] unresolved case count.
- [x] OR-CI pass/fail count.
- [x] fidelity accepted/rejected/manual-review count.

## Success Criteria

- No `needs_human` case proceeds without explicit answers.
- Every clarified case links to its question and answer artifacts.
- Every clarified generated ProblemSpec is marked as clarified.
- Every clarified solve has an OR-CI report.
- Every clarified solve has fidelity review status that distinguishes clarified
  source matching from original-only source matching.
