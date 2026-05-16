# OR-LLM-Agent CLI + Codex Skill Plan

Date: 2026-05-16

## Current Situation

- `or_llm_agent` is currently a research-script project with root scripts such as `or_llm_eval.py`, `or_llm_eval_async_resilient.py`, and `utils.py`.
- `or_llm_agent` already depends on standalone OR-CI through an editable dependency:
  - `or-ci = { path = "../or-ci", editable = true }`
- OR-CI has passed its OR-CI-only Phase 1 pilot and constraint-relaxation continuation.
- The first integration attempt has started, with `or_llm_agent` as producer and OR-CI as verifier.
- The current integration run is blocked before code generation because the configured OpenAI-compatible provider rejects the key. Saved provider errors are sanitized.
- The integration pilot artifacts currently live under:
  - `../or-ci/artifacts/pilot/phase-1-integration-2026-05-16/`

## Summary

Turn `or_llm_agent` into a Codex-usable producer tool for OR-CI pilots. The first version focuses only on the OR-CI workflow: generate `build_model(data) -> gurobipy.Model` submissions, verify them with standalone OR-CI, and write reproducible pilot artifacts.

Install a user-level Codex skill at `~/.codex/skills/or-llm-agent` that teaches Codex when and how to call the CLI.

## Key Changes

- Add a real CLI command to `or_llm_agent`:
  - `or-llm-agent health --model o3-mini [--live]`
  - `or-llm-agent generate --bwor-id BWOR-001 --model o3-mini --out submission.py --raw raw.txt`
  - `or-llm-agent verify --problem problem.json --submission submission.py --out report.json`
  - `or-llm-agent pilot --ids BWOR-001 BWOR-002 BWOR-010 --model o3-mini --artifact-dir ...`
- Package the CLI through `pyproject.toml` with `[project.scripts]`.
- Implement a small `src/or_llm_agent/` package for CLI code, prompt construction, code-block extraction, provider-health checks, artifact writing, and log redaction.
- Reuse the existing OpenAI/Anthropic dispatch behavior from `or_llm_eval_async_resilient.py`, but move shared logic into package modules rather than duplicating it.
- Keep existing research scripts working. Do not rewrite or remove `or_llm_eval.py`, `or_llm_eval_async_resilient.py`, or `utils.py` except for minimal compatibility imports if needed.

## CLI Behavior

- `health` checks:
  - required environment variables are present
  - Gurobi imports and can create a model
  - `or-ci` CLI is importable/runnable
  - `--live` performs a minimal provider call and redacts provider errors
- `generate`:
  - reads BWOR question text from `data/datasets/bwor.jsonl`
  - reads OR-CI instance/metamorphic metadata from sibling `../or-ci/tests/fixtures/bwor/<id>/problem.json`
  - prompts for a fenced Python module exposing only `build_model(data)`
  - writes raw provider response and extracted submission file
  - never stores unredacted API/provider secrets
- `verify`:
  - shells out to `or-ci verify`
  - writes the OR-CI JSON report unchanged except for subprocess/provider log redaction
- `pilot`:
  - runs `generate` then `verify` for each id
  - writes `raw/`, `submissions/`, `reports/`, `summary.json`, and `report.md`
  - separates generation status from OR-CI classification

## Codex Skill

- Create `~/.codex/skills/or-llm-agent/SKILL.md`.
- Skill triggers: OR model generation, BWOR pilots, OR-CI integration, generated Gurobi submissions, and `or_llm_agent` evaluation.
- Skill workflow:
  - run `or-llm-agent health --model <model> --live` before generation
  - use `pilot` for BWOR batches
  - use `generate` plus `verify` for single problems
  - inspect `summary.json` and OR-CI reports before answering
  - treat OR-CI `SUCCESS` as "configured invariants passed," not proof of full correctness
- No bundled scripts in v1. The CLI is the deterministic execution surface.

## Test Plan

- Static checks:
  - `uv run python -m compileall src/or_llm_agent`
  - `uv run or-llm-agent --help`
  - `uv run or-llm-agent health --model o3-mini`
- Failure-path check:
  - run `uv run or-llm-agent health --model o3-mini --live` with current invalid provider key and confirm output/artifacts redact the key
- Integration check after credentials are fixed:
  - `uv run or-llm-agent pilot --ids BWOR-001 BWOR-002 BWOR-010 --model o3-mini --artifact-dir ../or-ci/artifacts/pilot/phase-1-integration-2026-05-16-rerun`
  - confirm each generated file has `def build_model(data: dict)`
  - confirm OR-CI report JSON exists for each id
- Regression check:
  - from `code/or-ci`, run `uv run pytest` and confirm the standalone verifier still passes

## Assumptions

- v1 ignores legacy solve-only output mode; it is strictly an OR-CI producer workflow.
- The skill is installed as a user-level Codex skill, not only a project-local skill.
- OR-CI remains standalone; no OpenAI, Anthropic, or dotenv dependency is added to `or-ci`.
- Existing dirty or untracked files in `or_llm_agent` must be preserved and extended, not reverted.
- Provider credentials will be fixed separately; the implementation must handle invalid credentials cleanly and safely.
