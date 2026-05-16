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
uv run or-llm-agent generate --mode api --bwor-id <BWOR-ID> --model <model> --out <submission.py> --raw <raw.txt>
uv run or-llm-agent generate --mode agent --bwor-id <BWOR-ID> --out <submission.py> --raw <raw.txt> [--artifact-dir <dir>]
uv run or-llm-agent verify --problem <problem.json> --submission <submission.py> --out <report.json>
uv run or-llm-agent pilot --mode api --ids <BWOR-ID>... --model <model> --artifact-dir <dir> [--reuse-submissions]
uv run or-llm-agent pilot --mode agent --ids <BWOR-ID>... --artifact-dir <dir> [--reuse-submissions]
```

### 3. Contracts

- Provider dispatch remains prefix-based: model names starting with `claude` use
  Anthropic; all other model names use the OpenAI-compatible chat completions
  API.
- `api` mode is the default for backward compatibility.
- `agent` mode launches one persisted noninteractive `codex exec` session per
  BWOR id. Use `codex -a <policy> exec ...`, because approval is a top-level
  Codex flag on the local CLI.
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
- Generated submissions must be extracted from fenced Python code blocks and
  expose `def build_model(data: dict)`.
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
| Nested Codex writes no submission | Write a stub submission, record `agent_failed`, and still produce raw/status artifacts. |
| No fenced Python block | `generate` writes a stub submission, records `no_python_code`, and returns nonzero. |
| Missing `def build_model` | `generate` writes the extracted code, records `generated_without_build_model`, and returns nonzero. |
| OR-CI report exists | Preserve report JSON; summarize classification/status separately. |
| OR-CI command fails before report | Record `VERIFY_COMMAND_FAILED` in CLI summary data. |

### 5. Good/Base/Bad Cases

- Good: `pilot` completes with at least one generated or reused submission and
  reports each OR-CI classification in `summary.json`.
- Base: provider credentials are invalid; `pilot` still writes the full artifact
  tree with redacted errors and failed generation statuses.
- Base: nested Codex exits nonzero; `pilot --mode agent` still writes
  `codex-events.jsonl`, `last-message.md` if available, raw/status JSON, the
  parent OR-CI report, `summary.json`, and `report.md`.
- Bad: a raw provider exception containing an API key appears in stdout,
  `summary.json`, `report.md`, or `raw/*.txt`.

### 6. Tests Required

- Run `uv run python -m compileall src/or_llm_agent` after CLI code changes.
- Run `uv run or-llm-agent --help` to verify the console entry point.
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
