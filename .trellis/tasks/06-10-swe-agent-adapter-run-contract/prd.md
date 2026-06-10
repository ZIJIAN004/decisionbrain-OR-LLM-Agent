# SWE-agent adapter run contract

## Goal

Create the first reusable run-contract layer for SWE-agent OR modeling
experiments. The immediate adapter target is the existing Codex agent mode in
`src/or_llm_agent/codex_agent.py`; the output should make future Codex/Pi-style
agent runs comparable without changing OR-CI verifier behavior.

## Research Context

The selected OR-CI research direction is a constructed source-fidelity fault
benchmark. One supporting ablation is fixed API workflow versus agent-native
workflow. Existing `or-llm-agent` code can already launch nested Codex runs, but
the run evidence is spread across raw output, events, status files, reports, and
summaries. The next research stage needs one stable manifest per agent attempt.

## Requirements

- Keep OR-CI verifier logic unchanged.
- Keep existing Codex command execution behavior unchanged.
- Add an additive run manifest for Codex/SWE-agent attempts.
- Manifest must record:
  - schema version;
  - adapter type;
  - problem id;
  - command;
  - Codex options;
  - artifact/work/session paths;
  - expected output paths;
  - return code and timeout state after execution;
  - harvested fallback artifacts.
- Expose the manifest path through existing agent generation/status payloads
  where practical.
- Preserve redaction discipline for stdout/stderr; do not add secrets or
  provider credentials.
- Add focused tests for manifest path creation and manifest content.

## Acceptance Criteria

- [ ] A Codex agent run writes `agent-run-manifest.json`.
- [ ] `generate_agent_submission` exposes the manifest path in its returned
      generation payload.
- [ ] The existing Codex agent prompt/command tests still pass.
- [ ] New tests prove manifest schema/content for a mocked Codex run.
- [ ] `uv run pytest` passes.
- [ ] GitNexus impact was checked before edits and detect-changes runs before
      commit.

## Non-Goals

- Do not implement a new autonomous agent provider in this increment.
- Do not run expensive live Codex/SWE-agent experiments in this task.
- Do not change mutation benchmark denominators or OR-CI acceptance semantics.
