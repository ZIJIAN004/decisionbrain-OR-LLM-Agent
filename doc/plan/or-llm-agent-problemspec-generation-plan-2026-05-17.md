# OR-LLM-Agent ProblemSpec Generation Plan

Date: 2026-05-17

## Summary

Add a ProblemSpec generation stage for real-use OR-CI workflows where the user may
only have a natural-language problem statement.

The stage belongs in `or_llm_agent`, not OR-CI core. OR-CI remains the
deterministic verifier and schema owner. `or_llm_agent` becomes the producer that
can generate an OR-CI-compatible `problem.json`, generate solver code, and call
OR-CI for validation and verification.

Target pipeline:

```text
problem statement
  -> or-llm-agent spec
  -> OR-CI metadata validation
  -> or-llm-agent generate/pilot
  -> OR-CI verify
```

## Key Interface Changes

Add `or-llm-agent spec`:

```bash
uv run or-llm-agent spec \
  --mode agent \
  --statement-file problem.txt \
  --problem-id BWOR-011 \
  --out artifacts/specs/BWOR-011/problem.json \
  --raw artifacts/specs/BWOR-011/raw.txt
```

Add OR-CI metadata validation:

```bash
uv run or-ci validate-spec \
  --problem artifacts/specs/BWOR-011/problem.json
```

Extend `or-llm-agent generate` so it can use either a fixture id or an explicit
generated ProblemSpec:

```bash
uv run or-llm-agent generate \
  --mode agent \
  --problem artifacts/specs/BWOR-011/problem.json \
  --statement-file problem.txt \
  --out submission.py \
  --raw raw.txt
```

Add `or-llm-agent solve` as the real-use one-command path:

```bash
uv run or-llm-agent solve \
  --mode agent \
  --statement-file problem.txt \
  --problem-id case-001 \
  --artifact-dir artifacts/runs/case-001
```

`solve` should run spec generation, spec validation, model generation, parent
OR-CI verification, and a single summary report.

## Behavior Rules

- OR-CI must not call LLMs or Codex. It only validates metadata and verifies
  submissions.
- Generated specs must be saved as artifacts, not hidden in memory.
- V1 uses the existing OR-CI `problem.json` metadata shape as the generated
  ProblemSpec.
- Reports must separate these statuses:
  - `spec_generation_status`
  - `spec_validation_status`
  - `model_generation_status`
  - `verification_status`
- If spec validation fails, stop before model generation.
- If model verification passes, report it as "passed generated spec", not as
  proof that the original natural-language statement was fully correct.
- Benchmark fixtures remain reviewed or trusted metadata. Generated specs are
  run artifacts until reviewed.

## Implementation Plan

1. Add `or-ci validate-spec`.
   - Reuse `load_problem_metadata()`.
   - Return nonzero for schema errors.
   - Print a compact success/error message.

2. Add ProblemSpec prompting in `or_llm_agent`.
   - Create a prompt that asks for one JSON object matching OR-CI metadata.
   - Include the natural-language statement and required fields.
   - Instruct the agent to omit `evaluation_only` unless a trusted reference
     answer is explicitly supplied.

3. Add `or-llm-agent spec`.
   - Support `--mode agent` first.
   - Write raw model output, extracted `problem.json`, and a status payload.
   - Run `or-ci validate-spec` after extraction.

4. Extend `generate`.
   - Keep `--bwor-id` for benchmark fixtures.
   - Add `--problem` and `--statement-file` for generated-spec runs.
   - When `--problem` is supplied, load that metadata instead of
     `tests/fixtures/bwor/<id>/problem.json`.

5. Add `solve`.
   - Create an artifact tree with `spec/`, `submissions/`, `reports/`, `raw/`,
     `sessions/`, and `summary.json`.
   - Run the full statement-to-spec-to-model-to-verification path.
   - Preserve parent-run OR-CI verification as the final classification source.

## Test Plan

- `uv run or-ci validate-spec --problem tests/fixtures/bwor/BWOR-001/problem.json`
- Unit tests that `validate-spec` rejects missing `instance`, missing
  `metamorphic.cost_scaling`, and invalid constraint-relaxation fields.
- Unit tests that `or-llm-agent spec` writes `problem.json`, raw output, and
  status JSON when the generator returns valid JSON.
- Unit tests that `solve` stops before model generation when spec validation
  fails.
- Regression checks:

```bash
uv run python -m unittest tests.test_codex_agent
uv run python -m compileall src/or_llm_agent tests
uv run or-llm-agent health --agent
uv run or-llm-agent pilot \
  --mode agent \
  --ids BWOR-001 BWOR-002 BWOR-010 \
  --artifact-dir <tmp>
```

## Assumptions

- `agent` mode is the first implementation target because local Codex auth works
  and API-provider credentials are currently unreliable.
- API mode can reuse the same spec prompt later.
- Human review is not required for ad hoc real-use runs, but benchmark fixtures
  should still be reviewed before being treated as ground truth.
- The next implementation should start with `spec` and `validate-spec`; add
  `solve` only after those are stable.
