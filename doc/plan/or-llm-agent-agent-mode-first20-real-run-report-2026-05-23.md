# OR-LLM-Agent Agent-Mode First-20 Real Run Report

Date: 2026-05-23

## Follow-up After Codex Path Fix

After the stale `/usr/local/bin/codex` installation was removed from the active
path, nested `codex exec` stopped being killed by macOS and the real agent-mode
batch progressed normally.

Per the request to increase scale without requiring all 20 cases to complete, I
ran a higher-scale real experiment on the first 8 BWOR cases with
`--agent-concurrency 4`.

| Run | Command shape | Artifact directory | Wall time | Return code | Max case IDs sampled | Max matching `codex exec` process rows | Result |
|---|---|---|---:|---:|---:|---:|---|
| Post-fix partial c2 run | `solve-batch --ids BWOR-001...BWOR-020 --agent-concurrency 2` | `artifacts/agent-mode-concurrency/first20-fixed-c2-20260523-134901` | 443s | 143 | 2 | 3 | stopped early after 3 generated `SUCCESS` cases |
| Post-fix scale run | `solve-batch --ids BWOR-001...BWOR-008 --agent-concurrency 4` | `artifacts/agent-mode-concurrency/first8-fixed-c4-20260523-135723` | 658s | 1 | 4 | 5 | 7 generated `SUCCESS` cases, 1 expected `needs_human` block |

The c4 process-row peak of 5 happened during a handoff between nested Codex
stages. The distinct case IDs in flight never exceeded the configured cap of 4,
which is the batch-level concurrency standard.

Post-fix c4 outcomes:

| Case | Capability | Spec validation | Model generation | Verification | Classification |
|---|---|---|---|---|---|
| BWOR-001 | supported | passed | generated | PASS | SUCCESS |
| BWOR-002 | supported | passed | generated | PASS | SUCCESS |
| BWOR-003 | supported | passed | generated | PASS | SUCCESS |
| BWOR-004 | needs_human | skipped | skipped | skipped | blocked_capability |
| BWOR-005 | supported | passed | generated | PASS | SUCCESS |
| BWOR-006 | supported | passed | generated | PASS | SUCCESS |
| BWOR-007 | supported | passed | generated | PASS | SUCCESS |
| BWOR-008 | supported | passed | generated | PASS | SUCCESS |

Conclusion for the increased-scale run: the bounded-concurrency scheduler worked
at scale 4, no signal-9/macOS malware-style Codex failure reappeared, and the
CLI return code was nonzero only because BWOR-004 was classified as
`needs_human`.

## Initial Pre-fix Summary

I ran real `or-llm-agent solve-batch --mode agent` experiments on the first 20
BWOR cases, `BWOR-001` through `BWOR-020`, using the new bounded concurrency
flag.

The batch runner did schedule work concurrently. The monitor sampled the
expected number of case IDs in flight:

- `--agent-concurrency 4`: up to 4 case IDs sampled concurrently.
- `--agent-concurrency 2`: up to 2 case IDs sampled concurrently.

However, the runs did not reach ProblemSpec generation or model generation. In
both 20-case runs, every nested Codex capability classifier exited with
returncode `-9` and wrote empty event/final-message files. A separate direct
`codex exec` smoke test also exited as `Killed: 9`, so the blocker is the
current nested Codex execution environment, not the new `solve-batch`
concurrency scheduler.

## Initial Pre-fix Runs

| Run | Command shape | Artifact directory | Wall time | Return code | Max case IDs sampled | Max matching `codex exec` process rows | Result |
|---|---|---|---:|---:|---:|---:|---|
| Stress run | `solve-batch --ids BWOR-001...BWOR-020 --agent-concurrency 4` | `artifacts/agent-mode-concurrency/first20-c4-20260523-132308` | 13s | 1 | 4 | 8 | 20/20 blocked at capability gate |
| Default-scale run | `solve-batch --ids BWOR-001...BWOR-020 --agent-concurrency 2` | `artifacts/agent-mode-concurrency/first20-c2-20260523-132439` | 75s | 1 | 2 | 4 | 20/20 blocked at capability gate |
| Serial sanity run | `solve-batch --ids BWOR-001 --agent-concurrency 1` | `artifacts/agent-mode-concurrency/single-c1-20260523-132632` | 2s | 1 | 0 sampled before exit | 0 sampled before exit | 1/1 blocked at capability gate |

The process-row count is higher than the case count because a single nested
Codex run can appear as more than one matching process row. The case-ID column
is the better measure of batch-level task parallelism.

## Initial Pre-fix Batch Outcomes

For both first-20 runs:

- Total cases: 20
- Succeeded: 0
- Failed: 20
- Classification: `blocked_capability` for all 20
- Capability status: `needs_human` for all 20
- Capability generation status: `no_json` for all 20
- ProblemSpec generation: skipped for all 20
- Model generation: skipped for all 20

Representative capability artifact:

```text
BWOR-001 agent_returncode=-9
agent_timed_out=false
capability_generation_status=no_json
review_note=capability classifier exited with returncode=-9; capability classifier did not return a JSON object; stopping before ProblemSpec generation
```

The direct smoke test:

```bash
printf 'Return exactly: {"status":"ok"}\n' | \
  codex -a never exec --json -C <tmp> --skip-git-repo-check -s read-only -o <tmp>/last-message.md -
```

Result:

```text
Killed: 9
return_code=137
last_message: missing
events.jsonl: 0 bytes
stderr.txt: 0 bytes
```

## Timing And Parallelism

The monitoring method did not require repo code changes. It used a shell sampler
that ran during the batch and recorded matching nested `codex exec` processes
every 5 seconds:

```bash
ps -axo pid=,command= | grep '[c]odex.*exec' | grep "$ARTIFACT_DIR"
```

Observed samples:

- c4 run:
  - `2026-05-23T05:23:13Z`: 4 case IDs in flight (`BWOR-005` to `BWOR-008`)
  - `2026-05-23T05:23:18Z`: 4 case IDs in flight (`BWOR-009` to `BWOR-012`)
- c2 run:
  - multiple samples with 2 case IDs in flight, including `BWOR-001,BWOR-002`,
    `BWOR-005,BWOR-006`, `BWOR-009,BWOR-010`, and `BWOR-013,BWOR-014`

This confirms the new scheduler runs multiple case workers at once. It does not
confirm full solve throughput because nested Codex execution was killed before
the pipeline reached spec/model generation.

## Do We Need Extra Tools Or Code?

For wall time and approximate concurrent case count: no repo code is required.
The shell monitor is enough.

For exact per-case/per-stage timing: yes, lightweight instrumentation would be
better. The current artifacts do not record start/end timestamps for each case
or each nested agent stage. A small follow-up could add per-case timing fields
such as:

- `batch_started_at`
- `batch_finished_at`
- `batch_elapsed_seconds`
- per-stage elapsed seconds for capability, ProblemSpec, model generation, and
  OR-CI verification

For the immediate blocker, instrumentation is secondary. The first thing to
resolve is why `codex exec` is being killed with signal 9 in the current
environment.

## Current Conclusion

The concurrency feature is observable and working: the batch runner launched
multiple case workers concurrently and respected the configured cap. The initial
first-20 runs exposed a broken stale Codex executable on the path, but the
post-fix runs confirmed useful solve throughput with real nested agent work:
three generated successes before the c2 run was intentionally stopped, then
seven generated successes out of eight cases in the c4 scale run, with the
remaining case correctly blocked as `needs_human`.
