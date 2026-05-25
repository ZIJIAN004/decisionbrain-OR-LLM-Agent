# OR-LLM-Agent Agent-Mode Bounded Concurrency Plan

Date: 2026-05-22

## Goal

Make `or-llm-agent solve-batch --mode agent` able to run multiple independent
problem solves concurrently, with a reasonable bounded parallel amount, while
preserving the current per-problem workflow and artifact contract.

The intended outcome is faster batch execution in agent mode without changing
the semantics of a single problem solve. Each problem still runs its internal
pipeline sequentially:

1. Source-statement capability classification.
2. ProblemSpec generation and bounded repair.
3. Nested Codex model generation and repair.
4. Parent-run OR-CI verification.

Concurrency is only across different problem IDs. It must not parallelize the
dependent steps inside one problem.

## Verification Standard

The change is acceptable only if all of the following are true:

- `solve-batch --mode agent --agent-concurrency 1` preserves the current serial
  behavior and aggregate artifact format.
- `solve-batch --mode agent --agent-concurrency 2` can execute two independent
  cases at the same time in a unit test that would fail under serial execution.
- A larger mocked batch, currently 12 cases with `--agent-concurrency 4`, runs in
  multiple worker waves and preserves aggregate output.
- Aggregate `summary.json` and `report.md` preserve the input problem ID order,
  even when concurrent workers finish out of order.
- Duplicate problem IDs are rejected before any case starts, because duplicates
  would share the same case artifact directory.
- Invalid concurrency values such as `0` are rejected before any case starts.
- A per-case unexpected exception is recorded as that case failing, while other
  cases continue and the aggregate batch summary is still written.
- Existing agent-mode tests still pass:
  - `uv run python -m unittest tests.test_problemspec_generation`
  - `uv run python -m unittest tests.test_codex_agent`
  - `uv run python -m compileall src/or_llm_agent tests`
  - `uv run or-llm-agent solve-batch --help`

## Interface Changes

- Add `--agent-concurrency <N>` to `solve-batch`.
- Default to `2`.
- Treat `1` as the compatibility path that keeps serial execution.
- Enforce `N >= 1`.
- Use an effective worker count of `min(N, len(ids))`.
- Do not add this flag to `solve`, `generate`, `review-fidelity-batch`, or
  `resolve-fidelity-batch` in this first change.

## Implementation Plan

- Before changing code, run GitNexus impact analysis for `solve_batch_command`
  and report the blast radius as required by the project instructions.
- Refactor `solve_batch_command` into three parts:
  - Prepare case inputs serially: resolve the batch artifact root, validate
    problem IDs, resolve or write each statement file, and compute each case
    artifact directory.
  - Execute cases with `concurrent.futures.ThreadPoolExecutor` only when
    `--agent-concurrency` is greater than `1`; keep the current direct loop for
    `1`.
  - Build rows, write aggregate `summary.json`, and write `report.md`
    single-threaded after all case workers finish.
- Each worker must create its own `argparse.Namespace` and call the existing
  `solve_command(solve_args)` unchanged.
- The worker return value should contain `problem_id`, `exit_code`, `case_dir`,
  `statement_path`, and any redacted unexpected error message.
- The parent should build `_solve_batch_row(...)` in the original ID order, not
  completion order.
- Keep `run_codex_agent` as a blocking `subprocess.run` implementation. The
  concurrency boundary is at the case level, not inside the nested Codex runner.

## Risk Controls

- Keep default concurrency conservative at `2`, because one solve can spawn
  several nested Codex subprocesses plus OR-CI/Gurobi verification.
- Document that higher values are for local experimentation and should be chosen
  based on machine capacity and Codex account limits.
- Keep aggregate artifact writes out of worker threads to avoid corrupting
  `summary.json` or `report.md`.
- Keep case artifact roots isolated at `<artifact-dir>/<problem-id>/`.
- Reject duplicate IDs rather than trying to create unique suffixes, because
  preserving user-provided IDs is part of the artifact contract.

## Out of Scope

- No async rewrite of nested Codex execution.
- No concurrency inside a single problem solve.
- No changes to API mode.
- No concurrent implementation for `review-fidelity-batch` or
  `resolve-fidelity-batch` yet.
- No automatic dynamic tuning based on CPU, memory, provider rate limits, or
  Codex account state.

## Assumptions

- A reasonable first default parallel amount is `2`.
- The existing per-case artifact layout is already isolated enough for bounded
  cross-case concurrency.
- The parent CLI remains the final source of truth for OR-CI classification.
- The nested Codex agent may still write fallback artifacts under its neutral
  work directory, and the existing parent harvest behavior remains unchanged.
