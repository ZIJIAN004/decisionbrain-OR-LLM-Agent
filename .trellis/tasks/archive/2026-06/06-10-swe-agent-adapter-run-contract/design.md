# Design: SWE-Agent Run Manifest

## Boundary

This task extends the existing Codex agent adapter only. It does not add a new
agent engine and does not modify OR-CI.

## Data Flow

```text
or-llm-agent generate/solve/pilot --mode agent
  -> build_agent_paths(...)
  -> run_codex_agent(...)
  -> codex exec --json
  -> submissions/reports/raw/status/events/last-message
  -> agent-run-manifest.json
```

## Manifest Contract

Path:

```text
<artifact-root>/agent-status/<problem-id>.agent-run-manifest.json
```

Fields:

- `schema_version`: `swe_agent_run_manifest_v1`
- `adapter`: `codex-cli`
- `problem_id`
- `command`
- `options`
- `paths`
- `outputs`
- `result`
- `harvested_artifacts`

## Compatibility

`CodexAgentPaths` gains a new `manifest_path` field. Existing callers use
keyword construction in production via `build_agent_paths`; tests that build the
dataclass directly must provide the new path.

The change is intentionally additive. Existing `status.json`, raw payloads, and
summaries remain valid. New fields point to the manifest path.

## Risk

GitNexus reports critical blast radius for `build_agent_paths` and
`run_codex_agent` because they sit under multiple CLI flows. The mitigation is
to avoid changing prompt construction, command construction, verification, or
return-code semantics. Tests should focus on ensuring old artifacts still exist
and the new manifest is written.
