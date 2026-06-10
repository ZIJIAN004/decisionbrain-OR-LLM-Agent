# Implementation Plan

## Checklist

1. Add `manifest_path` to `CodexAgentPaths` and `build_agent_paths`.
2. Add a small manifest builder/writer in `codex_agent.py`.
3. Write the manifest after `codex exec` completes and fallback artifacts are
   harvested.
4. Include `agent_manifest` in raw/status/generation payloads.
5. Update Codex agent tests for the new dataclass field and manifest content.
6. Run unit tests and GitNexus detect-changes.

## Validation Commands

```bash
uv run pytest tests/test_codex_agent.py
uv run pytest
npx gitnexus detect-changes --repo or_llm_agent --scope unstaged
npx gitnexus detect-changes --repo or_llm_agent --scope staged
```
