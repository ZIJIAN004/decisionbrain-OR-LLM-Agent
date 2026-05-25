# CLI Contracts

> Command signatures and artifact contracts for packaged OR-LLM-Agent CLI work.

---

## Scenario: OR-CI Producer CLI

### 1. Scope / Trigger

Use this contract when modifying the packaged `or-llm-agent` CLI under
`src/or_llm_agent/`. The CLI is the deterministic execution surface for Codex and
other agents that produce OR-CI submissions from BWOR problems.

### 2. Signatures

```bash
uv run or-llm-agent health --model <model> [--live]
uv run or-llm-agent health --agent
uv run or-llm-agent classify-statement --mode agent --statement-file <problem.txt> --problem-id <ID> --out <capability.json> [--raw <raw.txt>] [--artifact-dir <dir>]
uv run or-llm-agent spec --mode agent --statement-file <problem.txt> --problem-id <ID> --out <problem.json> --raw <raw.txt> [--status <status.json>] [--artifact-dir <dir>]
uv run or-llm-agent generate --mode api --bwor-id <BWOR-ID> --model <model> --out <submission.py> --raw <raw.txt>
uv run or-llm-agent generate --mode agent --bwor-id <BWOR-ID> --out <submission.py> --raw <raw.txt> [--artifact-dir <dir>]
uv run or-llm-agent generate --mode agent --problem <problem.json> --statement-file <problem.txt> --out <submission.py> --raw <raw.txt> [--artifact-dir <dir>]
uv run or-llm-agent verify --problem <problem.json> --submission <submission.py> --out <report.json>
uv run or-llm-agent pilot --mode api --ids <BWOR-ID>... --model <model> --artifact-dir <dir> [--reuse-submissions]
uv run or-llm-agent pilot --mode agent --ids <BWOR-ID>... --artifact-dir <dir> [--reuse-submissions]
uv run or-llm-agent solve --mode agent --statement-file <problem.txt> --problem-id <ID> --artifact-dir <dir>
uv run or-llm-agent solve-batch --mode agent --ids <BWOR-ID>... --artifact-dir <dir> [--statements-dir <dir>] [--dataset <bwor.jsonl>]
uv run or-llm-agent prepare-clarification --artifact-dir <case-dir> --out <questions.json>
uv run or-llm-agent answer-clarification --artifact-dir <case-dir> --answers <answers.json> --reviewer <name>
uv run or-llm-agent solve-clarified --artifact-dir <case-dir> --clarification <answers.json> --resolution-dir <dir>
uv run or-llm-agent prepare-clarification-batch --artifact-dir <batch-dir> [--ids <BWOR-ID>...]
uv run or-llm-agent solve-clarified-batch --artifact-dir <batch-dir> --clarifications-dir <dir> [--ids <BWOR-ID>...]
uv run or-llm-agent review-fidelity --mode manual --artifact-dir <solve-dir> --status accepted|rejected --reviewer <name> --note <text> [--evidence <text>]...
uv run or-llm-agent review-fidelity --mode agent --artifact-dir <solve-dir>
uv run or-llm-agent review-fidelity-batch --mode manual --artifact-dir <batch-dir> [--ids <ID>...] --status accepted|rejected --reviewer <name> --note <text> [--evidence <text>]...
uv run or-llm-agent review-fidelity-batch --mode agent --artifact-dir <batch-dir> [--ids <ID>...]
uv run or-llm-agent resolve-fidelity --mode agent --artifact-dir <solve-dir> [--resolution-dir <dir>]
uv run or-llm-agent resolve-fidelity-batch --mode agent --artifact-dir <batch-dir> [--ids <ID>...] [--resolution-dir <dir>]
uv run or-ci validate-spec --problem <problem.json>
```

### 3. Contracts

- Provider dispatch remains prefix-based: model names starting with `claude` use
  Anthropic; all other model names use the OpenAI-compatible chat completions
  API.
- `api` mode is the default for backward compatibility.
- `agent` mode launches one persisted noninteractive `codex exec` session per
  BWOR id. Use `codex -a <policy> exec ...`, because approval is a top-level
  Codex flag on the local CLI.
- `agent` mode must use a neutral Codex work directory, not the OR-CI repository
  or requested artifact directory, as the `-C` path. Local `codex exec` can
  no-op with `input_tokens=0` when `-C` points inside the OR-CI tree.
- `agent` mode passes the requested artifact directory with `--add-dir`. If the
  nested Codex sandbox cannot write absolute artifact paths directly, it writes
  equivalent relative files under the neutral work directory and the parent CLI
  harvests them into the requested artifact directory after `codex exec` exits.
- `agent` mode writes JSON events with `codex exec --json` and the final agent
  message with `--output-last-message`.
- Provider environment keys are `OPENAI_API_KEY` and optional
  `OPENAI_API_BASE` for OpenAI-compatible models; `CLAUDE_API_KEY` or
  `ANTHROPIC_API_KEY` for Claude models.
- `agent` mode must not require API-provider environment keys; it relies on
  Codex CLI authentication.
- `generate` reads BWOR question text from `data/datasets/bwor.jsonl` and OR-CI
  metadata from `../or-ci/tests/fixtures/bwor/<BWOR-ID>/problem.json` unless
  flags override the paths.
- `classify-statement` is the source-statement capability gate before
  ProblemSpec generation. It writes a normalized JSON report with
  `status=supported|needs_human|unsupported`, `problem_family`,
  `supported_features`, `unsupported_features`, `missing_information`,
  `recommended_next_action`, `confidence`, and `review_note`.
- `solve` runs capability classification before `spec` by default and writes
  `spec/capability.json` plus `raw/capability.txt`. If capability status is
  `needs_human` or `unsupported`, it stops before ProblemSpec generation, writes
  `classification=blocked_capability`, and leaves model generation and OR-CI
  verification skipped.
- `spec` is the statement-to-ProblemSpec producer. V1 supports agent mode first:
  nested Codex returns one JSON object, the parent CLI writes raw text and
  extracted `problem.json`, then calls `or-ci validate-spec`.
- `generate --problem` loads the explicit OR-CI metadata path instead of a BWOR
  fixture. `--statement-file` supplies natural-language context to the model but
  does not change OR-CI verification semantics.
- `solve` writes `spec/`, `submissions/`, `reports/`, `raw/`, `sessions/`, and
  `summary.json` under `--artifact-dir`. Its summary separates
  `capability_status`, `spec_generation_status`, `spec_validation_status`,
  `model_generation_status`, and `verification_status`.
- `solve` writes `spec/fidelity-review.md` plus `spec/fidelity-review.json`.
  These are source-statement fidelity review gates, not proof artifacts. The
  default gate status is `manual_review_required` for valid specs and
  `blocked_spec_invalid` when metadata validation fails.
- `review-fidelity --mode manual` is the deterministic manual review transition
  for one `solve` artifact directory. It updates `summary.json`,
  `spec/fidelity-review.json`, and `spec/fidelity-review.md`, setting
  `spec_fidelity_status` and `spec_fidelity_gate_status` to `accepted` or
  `rejected`.
- `review-fidelity --mode agent` launches a nested Codex reviewer for one
  `solve` artifact directory. The reviewer must return one JSON object with
  `status=accepted|rejected`, `confidence`, `issues`, `review_note`, and
  `evidence`. The parent CLI records the transition as `llm_accepted` or
  `llm_rejected` to distinguish automated review from human certification.
- `review-fidelity` must not allow `accepted` or `llm_accepted` unless OR-CI
  metadata validation passed, parent OR-CI verification returned `PASS`, and the
  generated spec file exists. It may always record `rejected` or
  `llm_rejected`.
- `review-fidelity-batch` applies the same transition across a `solve-batch`
  artifact root, then rewrites aggregate `summary.json` and `report.md`. In
  `--mode agent`, it runs one reviewer per case so each case has independent
  review evidence.
- `resolve-fidelity --mode agent` is the automated post-rejection transition for
  one `solve` artifact directory. It uses the fidelity issue as ProblemSpec
  repair context, writes a repaired solve artifact under `--resolution-dir` or a
  new `fidelity-resolution/attempt-N/` directory, regenerates the model,
  reruns OR-CI verification, reruns agent fidelity review, and writes
  `fidelity-resolution.json`.
- `resolve-fidelity-batch --mode agent` applies the same transition across a
  `solve-batch` root. When `--ids` is omitted and `--force` is false, it only
  processes cases whose source artifact has `spec_fidelity_status` of
  `rejected` or `llm_rejected`; it still rewrites the full aggregate
  `summary.json` and `report.md`.
- Fidelity resolution statuses are:
  `repaired_accepted`, `repair_failed`, `residual_harmless_equivalent`,
  `residual_material`, `residual_unresolved`, and `skipped_not_rejected`.
- Impact classifications are:
  `not_needed`, `harmless_equivalent`, `material`, and `unresolved`. Impact
  analysis is deterministic and currently compares `original_solver_status`
  objective values between the source artifact and repaired artifact.
- `solve-batch` runs statement-only `solve` once per id under
  `<artifact-dir>/<ID>/`, writes any dataset-sourced statement text to
  `<artifact-dir>/statements/<ID>.txt`, and writes aggregate `summary.json` and
  `report.md` at the batch root.
- `prepare-clarification` applies only to a single blocked solve artifact whose
  `capability_status` is `needs_human`. It launches a nested Codex question
  planner, writes the requested question artifact, and keeps a canonical copy at
  `<case-dir>/clarification/questions.json` plus raw/events evidence under the
  source artifact. Question artifacts use `problem_id`, `source_artifact`,
  `blocking_status=needs_human`, and a non-empty `questions[]` list.
- Supported clarification `issue_type` values are:
  `missing_numeric_data`, `ambiguous_objective`, `unit_conflict`,
  `domain_choice`, `timing_convention`, `data_conflict`, and
  `modeling_convention`. Supported answer artifact `resolution_status` values
  are `answered`, `partially_answered`, `rejected`, and `unresolved`.
- `answer-clarification` validates an answer artifact against canonical
  questions, stamps missing per-answer reviewer fields from `--reviewer`, and
  writes the normalized canonical copy at
  `<case-dir>/clarification/answers.json` without modifying an external
  `--answers` file. If `--answers` already points at the canonical copy, it is
  normalized in place. If required questions remain unanswered, the command
  records `resolution_status=partially_answered` and returns nonzero.
- `solve-clarified` does not overwrite the original blocked artifact and refuses
  `--resolution-dir` values that resolve to the source `--artifact-dir`. It
  requires answered required clarification questions, writes a separate
  clarified solve artifact under `--resolution-dir`, passes the original
  statement plus approved clarification answers to ProblemSpec generation and
  model generation, marks generated metadata with top-level `source_context`,
  reruns OR-CI, and writes fidelity review artifacts that include clarification
  context.
- Clarified solve summaries include `clarified_from`, `clarification_status`,
  `clarification_question_count`, `clarification_answer_count`,
  `clarification_source`, and `clarification_gate_status`.
- `prepare-clarification-batch` and `solve-clarified-batch` default to only
  `needs_human` rows from the source `solve-batch` summary when `--ids` is
  omitted. They write `clarification-summary.json` and
  `clarification-report.md` at the batch root.
- Generated specs are run artifacts until reviewed. Do not treat a generated
  `problem.json` as benchmark ground truth.
- Generated submissions must be extracted from fenced Python code blocks and
  expose `def build_model(data: dict)`.
- Generated specs must be extracted as a single JSON object and validated with
  OR-CI metadata validation before any model generation. If validation fails,
  `spec`/`solve` may run a bounded repair loop using the OR-CI validation error
  and previous JSON as repair context.
- `verify` runs OR-CI out of process and writes the OR-CI report JSON unchanged.
  If the `or-ci` console script is unavailable, use `python -m or_ci.cli` as the
  out-of-process fallback.
- `pilot` writes `raw/`, `submissions/`, `reports/`, `summary.json`, and
  `report.md`. `generation_status` and OR-CI `classification` are separate
  fields.
- Agent-mode pilot runs additionally write `sessions/<BWOR-ID>/codex-events.jsonl`,
  `sessions/<BWOR-ID>/last-message.md`, and `agent-status/<BWOR-ID>.json`.
- Parent CLI verification remains the source of truth for `classification`, even
  if nested Codex ran OR-CI first.

### 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Missing provider key | `health` marks the key check `FAIL` and returns nonzero. |
| Provider rejects key | `health --live` or `generate` reports a redacted provider error. |
| Agent mode requested | `health --agent` checks `codex --help`, `codex exec --help`, Gurobi, and OR-CI without checking provider keys. |
| Nested Codex exits nonzero | Record `agent_returncode`, keep any produced artifacts, and let parent OR-CI verification classify the submission. |
| Nested Codex times out | Terminate the nested process, record return code `124` and `timed_out=true`, and still write raw/status artifacts. |
| Nested Codex writes fallback artifacts in the neutral work dir | Parent CLI copies `submissions/`, `reports/`, `agent-status/`, and `sessions/` files into the requested artifact directory before classifying generation. |
| Nested Codex writes no submission | Write a stub submission, record `agent_failed`, and still produce raw/status artifacts. |
| Capability classifier returns no JSON or invalid status | Record `capability_status=needs_human`, stop before ProblemSpec generation, and preserve raw/events artifacts. |
| Capability classifier returns `needs_human` or `unsupported` | Write a complete blocked solve summary with `classification=blocked_capability`; do not generate a ProblemSpec. |
| `prepare-clarification` source artifact is not `needs_human` | Return nonzero and do not create a clarification question artifact. |
| Clarification question JSON is malformed | Return nonzero with a schema-specific error. |
| Clarification answer JSON is malformed | Return nonzero with a schema-specific error. |
| Required clarification question is unanswered | `answer-clarification` writes/keeps `partially_answered`; `solve-clarified` refuses to run ProblemSpec generation. |
| Clarification artifact is `rejected` or `unresolved` | `solve-clarified` refuses to run ProblemSpec generation. |
| Clarified solve is run | Write all new artifacts under the requested resolution directory; preserve the original blocked solve summary and classifier output. |
| No fenced Python block | `generate` writes a stub submission, records `no_python_code`, and returns nonzero. |
| Missing `def build_model` | `generate` writes the extracted code, records `generated_without_build_model`, and returns nonzero. |
| Spec agent returns no JSON object | `spec` writes raw output, records `no_json`, writes a status JSON, and returns nonzero. |
| `or-ci validate-spec` rejects generated metadata | `spec` records the failed attempt and retries up to `--max-repair-attempts`; if still failed, `solve` stops before model generation. |
| `review-fidelity --status accepted` for a failed or unverified case | Return nonzero and do not mark the artifact accepted. |
| `review-fidelity --status rejected` for a failed or unverified case | Record the rejection and preserve failed generation/verification status. |
| `review-fidelity --mode agent` reviewer returns no JSON or invalid status | Record `llm_rejected`, preserve agent events and final-message paths as evidence, and keep generated run status unchanged. |
| `review-fidelity --mode agent` reviewer tries to accept a failed or unverified case | Record `llm_rejected` with a parent-gate note; do not mark the artifact accepted. |
| `resolve-fidelity` source artifact is not rejected | Skip unless `--force` is set; record `skipped_not_rejected` if explicitly invoked. |
| Repaired ProblemSpec does not validate or repaired solve fails | Record `repair_failed`; do not overwrite the source solve artifact. |
| Repaired solve verifies but fidelity review still rejects | Run deterministic impact analysis and classify as `residual_harmless_equivalent`, `residual_material`, or `residual_unresolved`. |
| OR-CI report exists | Preserve report JSON; summarize classification/status separately. |
| OR-CI command fails before report | Record `VERIFY_COMMAND_FAILED` in CLI summary data. |

### 5. Good/Base/Bad Cases

- Good: `pilot` completes with at least one generated or reused submission and
  reports each OR-CI classification in `summary.json`.
- Good: `spec` writes raw output, extracted `problem.json`, status JSON, and
  `spec_validation_status=passed`.
- Good: `classify-statement` writes raw output and a normalized capability JSON
  with a valid capability status.
- Good: `solve` reaches OR-CI verification and reports `PASS` as "passed
  generated spec", not as proof that the source statement was fully modeled.
- Good: `solve` blocks goal-programming, symbolic-coefficient, or other
  unsupported statements before ProblemSpec generation instead of inventing an
  LP-shaped spec.
- Good: `solve-batch` writes one case directory per id, an aggregate
  `summary.json`, and a `report.md` that lists spec validation, model
  generation, OR-CI classification, capability status, and fidelity gate status
  per case.
- Good: `prepare-clarification` turns a `needs_human` blocked artifact into a
  concise question artifact without changing the blocked `summary.json`.
- Good: `solve-clarified` turns an answered clarification artifact into a
  separate generated/verified run whose summary is traceable to the blocked
  source artifact and clarification answers.
- Good: `prepare-clarification-batch` only processes `needs_human` cases by
  default and leaves `unsupported` cases alone.
- Good: `review-fidelity-batch` transitions reviewed cases from
  `manual_review_required` to `accepted` or `rejected` and updates the aggregate
  batch report.
- Good: `review-fidelity-batch --mode agent` transitions reviewed cases from
  `manual_review_required` to `llm_accepted` or `llm_rejected`, preserving per
  case agent evidence in each case's `spec/fidelity-review.json`.
- Good: `resolve-fidelity` repairs a rejected source artifact into a new
  `repaired_accepted` artifact without mutating the original generated spec or
  submission.
- Good: `resolve-fidelity` classifies an unrepaired residual mismatch as
  `residual_harmless_equivalent` only when both source and repaired artifacts
  verify and their original objective values match within tolerance.
- Base: provider credentials are invalid; `pilot` still writes the full artifact
  tree with redacted errors and failed generation statuses.
- Base: generated ProblemSpec fails OR-CI metadata validation; `solve` writes
  `summary.json`, writes blocked fidelity artifacts, and skips model generation
  after repair attempts are exhausted.
- Base: nested Codex exits nonzero; `pilot --mode agent` still writes
  `codex-events.jsonl`, `last-message.md` if available, raw/status JSON, the
  parent OR-CI report, `summary.json`, and `report.md`.
- Bad: a raw provider exception containing an API key appears in stdout,
  `summary.json`, `report.md`, or `raw/*.txt`.

### 6. Tests Required

- Run `uv run python -m compileall src/or_llm_agent` after CLI code changes.
- Run `uv run python -m unittest tests.test_codex_agent` after agent-mode code
  changes.
- Run `uv run or-llm-agent --help` to verify the console entry point.
- Run `uv run or-llm-agent spec --help`, `generate --help`, and `solve --help`
  after changing parser flags.
- Run `uv run or-llm-agent classify-statement --help` after changing capability
  routing flags.
- Run `uv run or-llm-agent solve-batch --help` after changing batch parser flags.
- Run `uv run or-llm-agent prepare-clarification --help`,
  `answer-clarification --help`, `solve-clarified --help`,
  `prepare-clarification-batch --help`, and `solve-clarified-batch --help` after
  changing clarification parser flags.
- Run `uv run or-llm-agent review-fidelity --help` and
  `uv run or-llm-agent review-fidelity-batch --help` after changing review flags.
- Run `uv run or-ci validate-spec --problem tests/fixtures/bwor/BWOR-001/problem.json`
  from the OR-CI repo, or `uv run python -m or_ci.cli validate-spec --problem ...`
  from this repo when the console script is unavailable.
- Add tests that `spec` writes `problem.json`, raw output, and status JSON from
  a mocked valid agent result.
- Add tests that `classify-statement` writes capability JSON from a mocked valid
  agent result.
- Add tests that `solve` stops before ProblemSpec generation for
  `needs_human` and `unsupported` capability statuses.
- Add tests that clarification question and answer schemas validate and reject
  malformed artifacts.
- Add tests that required unanswered clarification questions block
  `solve-clarified`, and answered required questions allow a clarified solve
  without overwriting the original blocked artifact.
- Add tests that clarification batch preparation processes only `needs_human`
  cases by default.
- Add tests that `solve` stops before model generation when spec validation
  fails.
- Add tests that `solve-batch` writes an aggregate summary/report from mocked
  per-case solves.
- Add tests that `review-fidelity` updates single-case summary/report artifacts
  and that `review-fidelity-batch` rewrites aggregate batch status.
- Add tests that `review-fidelity --mode agent` records `llm_accepted` for a
  valid reviewer JSON and `llm_rejected` when the reviewer returns no JSON.
- Add tests that `resolve-fidelity` records `repaired_accepted`, records
  `residual_harmless_equivalent` when repaired review still rejects but
  objective values match, and that `resolve-fidelity-batch` processes only
  rejected cases by default.
- Run `uv run or-llm-agent health --model <model>` for static local readiness.
- Run `uv run or-llm-agent health --model <model> --live` when checking provider
  credentials or redaction behavior.
- Run `uv run or-llm-agent health --agent` after agent-mode code changes.
- Run `uv run or-llm-agent generate --help` and `uv run or-llm-agent pilot --help`
  after changing parser flags.
- Run `uv run or-llm-agent pilot --mode agent --ids BWOR-001 --artifact-dir <tmp>`
  when local Codex auth/runtime is available.
- Run one `verify` smoke test against an OR-CI fixture when changing OR-CI
  subprocess handling.
- Run `uv run pytest` from `../or-ci` when a change could affect standalone
  verifier behavior.

### 7. Wrong vs Correct

#### Wrong

```python
subprocess.run(["or-ci", "verify", ...], check=True)
```

This crashes before artifact summarization when the console script is missing or
the verifier reports a failure.

#### Correct

```python
command = ["or-ci"] if shutil.which("or-ci") else [sys.executable, "-m", "or_ci.cli"]
result = subprocess.run([*command, "verify", ...], capture_output=True, text=True, check=False)
```

Keep the verifier out of process, capture stdout/stderr for redaction, and let
the caller summarize failures deterministically.

#### Wrong

```python
summary["verification_note"] = "proved original statement correct"
```

This overclaims what OR-CI verified when the spec itself was generated.

#### Correct

```python
summary["verification_note"] = "passed generated spec"
```

Keep source-statement fidelity separate from generated-spec verification.

#### Wrong

```python
if source_summary["capability_status"] == "needs_human":
    solve_command(source_args)
```

This reruns the original blocked artifact and invites the agent to guess missing
or ambiguous source facts.

#### Correct

```python
if clarification_gate_status != "passed":
    raise CLIError("clarification gate is not passed")
solve_clarified_artifact(..., resolution_dir=separate_dir)
```

Clarified runs must require explicit answers, write to a separate resolution
artifact, and keep the original capability block intact.
