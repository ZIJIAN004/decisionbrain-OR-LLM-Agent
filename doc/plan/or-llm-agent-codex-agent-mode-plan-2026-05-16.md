# OR-LLM-Agent Codex Agent Mode Plan

Date: 2026-05-16

## Summary

Add a second generation backend to the packaged `or-llm-agent` CLI. The current `api` mode calls OpenAI/Anthropic-compatible APIs directly. The new `agent` mode launches a persistent noninteractive Codex session with `codex exec` and lets that Codex instance solve one OR problem end to end.

The spawned Codex session should generate `build_model(data)`, run OR-CI, repair failures, and leave artifacts for inspection.

## CLI Changes

- Extend existing commands with a mode flag:
  - `or-llm-agent generate --mode api|agent ...`
  - `or-llm-agent pilot --mode api|agent ...`
- Keep `api` as the default for backward compatibility.
- Add Codex-specific options used only in `agent` mode:
  - `--codex-model <model>` defaults to Codex CLI default if omitted
  - `--codex-sandbox workspace-write`
  - `--codex-approval never`
  - `--max-repair-attempts 3`
- Keep `health --live` as API-provider health.
- Add `health --agent` to check:
  - `codex --help` works
  - `codex exec --help` works
  - OR-CI verification path works
  - Gurobi model creation works

## Agent Mode Behavior

- `generate --mode agent` creates a per-problem artifact workspace, a neutral
  Codex work directory under `~/.cache/or_llm_agent/codex-work/`, and runs:

```bash
codex -a never exec \
  -C <neutral-codex-work-dir> \
  --add-dir <artifact-dir> \
  --skip-git-repo-check \
  -s workspace-write \
  --output-last-message <artifact-dir>/sessions/<BWOR-ID>/last-message.md \
  ...
```

- Do not use an OR-CI repository or artifact path as the `-C` working directory.
  Local testing showed that `codex exec` can no-op with `input_tokens=0` when
  `-C` points inside the OR-CI tree, even for trivial prompts.
- The spawned Codex session first tries to write the absolute artifact paths. If
  the Codex sandbox blocks those writes, it writes the same relative files under
  the neutral work directory. The parent CLI harvests these fallback files back
  into the requested artifact directory after Codex exits.
- Do not pass `--ephemeral`; the Codex session should persist and be resumable.
- The Codex prompt must include:
  - BWOR natural-language problem text
  - OR-CI `problem.json` instance and metamorphic config
  - absolute output paths for submission, report, final message, and status JSON
  - neutral work directory path for temporary or fallback files
  - fallback relative artifact paths for sandbox-blocked writes
  - instruction to write final artifacts only inside the artifact workspace
  - explicit instruction to start the workflow immediately
  - instruction to create `def build_model(data: dict) -> gurobipy.Model`, run OR-CI, inspect failures, and repair until success or attempt limit
- After `codex exec` exits, the parent CLI always runs one final `or-ci verify` itself and uses that result for `summary.json`.
- `pilot --mode agent` runs one Codex session per BWOR id, not one batch-wide session.

## Artifact Contract

Each problem under `--artifact-dir` writes:

- `sessions/<BWOR-ID>/codex-events.jsonl`
- `sessions/<BWOR-ID>/last-message.md`
- `submissions/<BWOR-ID>.py`
- `reports/<BWOR-ID>.json`
- `raw/<BWOR-ID>.txt`
- `agent-status/<BWOR-ID>.json`

Batch output remains:

- `summary.json`
- `report.md`

`summary.json` adds:

- `generation_mode: "agent"`
- `agent_returncode`
- `agent_timed_out`

It preserves existing fields:

- `generation_status`
- `classification`
- `failure_check`
- `checks`

`raw/<BWOR-ID>.txt` records the nested Codex command, return code, timeout
status, neutral work directory, and any fallback artifacts harvested by the
parent CLI.

## Implementation Notes

- Add an internal module such as `src/or_llm_agent/codex_agent.py` for Codex command construction, prompt rendering, subprocess execution, and transcript redaction.
- Keep API provider code in `provider.py`; agent mode must not require `OPENAI_API_KEY`, `OPENAI_API_BASE`, or Claude keys.
- Update the Codex skill at `~/.codex/skills/or-llm-agent/SKILL.md` so OR-CI pilot work prefers:
  - `uv run or-llm-agent health --agent`
  - `uv run or-llm-agent pilot --mode agent --ids ...`
- Update `.trellis/spec/backend/cli-contracts.md` to document `api` vs `agent` mode and the new artifact fields.

## Test Plan

- Static checks:
  - `uv run python -m compileall src/or_llm_agent`
  - `uv run python -m unittest tests.test_codex_agent`
  - `uv run or-llm-agent --help`
  - `uv run or-llm-agent generate --help`
  - `uv run or-llm-agent pilot --help`
- Agent health:
  - `uv run or-llm-agent health --agent`
- Dry/smoke behavior:
  - run `pilot --mode agent --ids BWOR-001 --artifact-dir <tmp-artifact-dir>`
  - confirm a Codex session is launched
  - confirm artifacts are written
  - confirm the final parent-run OR-CI report exists
- Regression:
  - `uv run or-llm-agent pilot --mode api ...` still behaves as before
  - from `../or-ci`, run `uv run pytest` and confirm OR-CI remains standalone

## Implementation Outcome: 2026-05-16 / 2026-05-17

- Initial agent-mode reruns failed before generation because nested `codex exec`
  exited with return code `0`, no final message, and `input_tokens=0`.
- Minimal reproduction showed this no-op behavior when `-C` pointed inside the
  OR-CI repository or artifact tree.
- The implementation now runs nested Codex from a neutral cache work directory
  and passes the requested artifact directory with `--add-dir`.
- Nested Codex may still be unable to write absolute artifact paths directly from
  the neutral workdir. The parent CLI therefore harvests fallback files from:
  - `submissions/<BWOR-ID>.py`
  - `reports/<BWOR-ID>.json`
  - `agent-status/<BWOR-ID>.json`
  - `sessions/<BWOR-ID>/last-message.md`
- Successful pilot:

```bash
uv run or-llm-agent pilot \
  --mode agent \
  --ids BWOR-001 BWOR-002 BWOR-010 \
  --artifact-dir ../or-ci/artifacts/pilot/phase-1-integration-agent-2026-05-16-rerun \
  --codex-timeout-seconds 900
```

Result: all three generated submissions passed OR-CI with classification
`SUCCESS`; `original_solver_status`, `cost_scaling`, and
`constraint_relaxation` passed for every problem.

## Assumptions

- `agent` mode uses `codex exec`, not the interactive Codex TUI.
- One Codex session handles one BWOR problem from generation through verification and repair.
- The parent CLI remains the final source of truth for OR-CI classification.
- Agent mode does not use API-provider credentials from `.env`; it relies on Codex CLI authentication.
- The spawned Codex session should not edit repo source files. If it does, the parent CLI records this as an unexpected side effect rather than reverting automatically.
