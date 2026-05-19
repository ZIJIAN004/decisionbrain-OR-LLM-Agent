# OR-LLM-Agent Agent Fidelity Review and Scale Pilot

Date: 2026-05-18

## Decision

Add an agent-mode source-statement fidelity review stage to OR-LLM-Agent.

Manual review remains the stronger certification path and keeps the existing
statuses `accepted` and `rejected`. Agent review records `llm_accepted` or
`llm_rejected` so automated review evidence is visible but not confused with a
human decision.

## Implemented CLI Contract

```bash
uv run or-llm-agent review-fidelity --mode agent --artifact-dir <solve-dir>
uv run or-llm-agent review-fidelity-batch --mode agent --artifact-dir <batch-dir> [--ids <ID>...]
```

The agent reviewer reads the original statement, generated ProblemSpec,
OR-CI report, solve summary, and existing fidelity report. It must return one
JSON object with:

- `status`: `accepted` or `rejected`
- `confidence`
- `issues`
- `review_note`
- `evidence`

The parent CLI applies the transition, stores reviewer evidence in
`spec/fidelity-review.json`, rewrites `spec/fidelity-review.md`, and updates
case and batch summaries.

## Safety Rules

- Parent-side acceptance guards still apply to both `accepted` and
  `llm_accepted`.
- An agent reviewer cannot accept an artifact unless OR-CI spec validation
  passed, OR-CI verification returned `PASS`, and the generated spec exists.
- Missing reviewer JSON, invalid status, timeout, or invalid acceptance is
  recorded as `llm_rejected`.
- OR-CI `SUCCESS` is still interpreted only as passing the generated spec.

## Scale Pilot Result

Artifact root:
`/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-18-10case/`

Summary:

- `solve-batch`: 10 / 10 succeeded.
- OR-CI classification: 10 / 10 `SUCCESS`.
- ProblemSpec validation: 10 / 10 `passed`.
- Model generation: 10 / 10 `generated`.
- Fidelity review: 9 `llm_accepted`, 1 `llm_rejected`.

Notable finding:

- `BWOR-003` was rejected because the generated spec omits 2006 from
  `bank_deposit_years`, while the statement permits surplus funds to be
  deposited at the beginning of each year.

## Verification

- `uv run python -m unittest discover`: 17 passed.
- `uv run python -m compileall src/or_llm_agent tests`: passed.
- `uv run or-llm-agent --help`: passed.
- `uv run or-llm-agent review-fidelity --help`: passed.
- `uv run or-llm-agent review-fidelity-batch --help`: passed.
- `uv run or-llm-agent health --agent`: passed.
- OR-CI `uv run pytest`: 25 passed.

## 2026-05-19 Extension: Fidelity Resolution Loop

The automated process now has an explicit post-rejection transition:

```bash
uv run or-llm-agent resolve-fidelity --mode agent --artifact-dir <solve-dir>
uv run or-llm-agent resolve-fidelity-batch --mode agent --artifact-dir <batch-dir>
```

Behavior:

- For a rejected source artifact, OR-LLM-Agent uses the fidelity issue as
  ProblemSpec repair context.
- It writes repaired solve artifacts into `fidelity-resolution/attempt-N/` or
  the explicit `--resolution-dir`.
- It regenerates the model, reruns OR-CI verification, reruns agent fidelity
  review, and writes `fidelity-resolution.json`.
- If the repaired artifact is accepted, the source summary records
  `fidelity_resolution_status=repaired_accepted`.
- If the repaired artifact still fails fidelity review, the CLI runs deterministic
  impact analysis by comparing source and repaired `original_solver_status`
  objective values.
- Residual cases are classified as `residual_harmless_equivalent`,
  `residual_material`, or `residual_unresolved`.

Batch behavior:

- `resolve-fidelity-batch` processes only `rejected` / `llm_rejected` cases by
  default when `--ids` is omitted.
- It writes `fidelity-resolution-summary.json`,
  `fidelity-resolution-report.md`, and refreshes the full batch `summary.json`
  and `report.md`.

Live result on the 10-case pilot:

- The command processed only `BWOR-003`.
- Resolution status: `repaired_accepted`.
- Repaired artifact:
  `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-18-10case/fidelity-resolution/BWOR-003/attempt-1/`
- The repaired ProblemSpec restored `bank_deposit_years` to
  `[2003, 2004, 2005, 2006]`.
- Repaired artifact status: spec validation `passed`, model generation
  `generated`, OR-CI verification `PASS` / `SUCCESS`, fidelity review
  `llm_accepted`.
