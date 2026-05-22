# OR-CI Full Process Report

Date: 2026-05-20

## Purpose

This report explains the current full process from a natural-language
operations research statement to generated model artifacts, OR-CI verification,
source-fidelity review, and final reporting.

OR-CI means Operations Research Continuous Integration. OR-CI is the standalone
deterministic verifier. It does not call an LLM and does not decide whether the
generated ProblemSpec fully matches the original source statement.

`or_llm_agent` is the producer and orchestrator. It calls Codex agent mode for
generation/review work and calls OR-CI for deterministic validation and
verification.

## Path Convention Used In This Report

Project roots:

| Name | Full Path |
|---|---|
| OR-LLM-Agent root | `/Users/zhangbowen/Projects/OR/code/or_llm_agent` |
| OR-CI root | `/Users/zhangbowen/Projects/OR/code/or-ci` |
| This report | `/Users/zhangbowen/Projects/OR/code/or_llm_agent/doc/plan/or-ci-full-process-report-2026-05-20.md` |

Concrete case used for path examples:

| Name | Value |
|---|---|
| Case id | `BWOR-001` |
| Latest completed pilot root | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case` |
| Current-process example root, for a rerun with capability routing | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-20-current-process-example` |

Important note:

- The latest completed 20-case pilot was run before capability routing was
  added, so it has real files for statement intake, ProblemSpec generation,
  model generation, OR-CI verification, fidelity review, and resolution.
- A current rerun would additionally create capability-routing files:
  `spec/capability.json`, `raw/capability.txt`, and
  `sessions/BWOR-001-capability/...`.

## Step 0. Readiness Check

1. Short explanation:

   Check whether the local machine can run the full agent-mode workflow.
   This is not problem solving. It checks local tools.

2. Input data, content and file path:

   | Content | File Path |
   |---|---|
   | Codex CLI installation | no input data file; checked from the local shell environment |
   | `codex exec` availability | no input data file; checked from the local shell environment |
   | Gurobi installation/license | no input data file; checked from the local shell environment |
   | OR-CI package/CLI availability | `/Users/zhangbowen/Projects/OR/code/or-ci` |
   | OR-LLM-Agent CLI package | `/Users/zhangbowen/Projects/OR/code/or_llm_agent` |

3. Who deals with these data:

   `or_llm_agent health --agent`.

4. Output results, content and data path:

   | Content | File Path |
   |---|---|
   | Health result printed to terminal | no output file by default |
   | Optional saved terminal log if the operator redirects output | user-chosen path |

## Step 1. Statement Intake

1. Short explanation:

   Load the natural-language OR problem statement and create a case artifact
   directory. In batch mode, one directory is created for each case id.

2. Input data, content and file path:

   | Content | File Path |
   |---|---|
   | BWOR source statement dataset | `/Users/zhangbowen/Projects/OR/code/or_llm_agent/data/datasets/bwor.jsonl` |
   | Existing copied BWOR-001 statement from the latest completed pilot | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/statements/BWOR-001.txt` |

3. Who deals with these data:

   `or_llm_agent solve` for one case, or `or_llm_agent solve-batch` for a batch.

4. Output results, content and data path:

   | Content | File Path |
   |---|---|
   | Saved statement text used by the run | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/statements/BWOR-001.txt` |
   | Per-case artifact directory | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001` |
   | Current rerun per-case artifact directory | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-20-current-process-example/BWOR-001` |

## Step 2. Capability Routing

1. Short explanation:

   Decide whether the current automated pipeline can safely handle the source
   statement before generating a ProblemSpec. The status is one of `supported`,
   `needs_human`, or `unsupported`.

2. Input data, content and file path:

   | Content | File Path |
   |---|---|
   | Source statement text | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-20-current-process-example/statements/BWOR-001.txt` |
   | Capability classification prompt template | `/Users/zhangbowen/Projects/OR/code/or_llm_agent/src/or_llm_agent/prompts.py` |

3. Who deals with these data:

   Parent `or_llm_agent` launches nested Codex agent mode through
   `classify-statement --mode agent`. Parent `or_llm_agent` accepts only
   `capability_status=supported`.

4. Output results, content and data path:

   | Content | File Path |
   |---|---|
   | Normalized capability JSON with status, supported features, unsupported features, missing information, confidence, and recommended next action | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-20-current-process-example/BWOR-001/spec/capability.json` |
   | Raw capability classifier output | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-20-current-process-example/BWOR-001/raw/capability.txt` |
   | Capability Codex event log | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-20-current-process-example/BWOR-001/sessions/BWOR-001-capability/codex-events.jsonl` |
   | Capability Codex final message | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-20-current-process-example/BWOR-001/sessions/BWOR-001-capability/last-message.md` |
   | If blocked: summary with `classification=blocked_capability` | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-20-current-process-example/BWOR-001/summary.json` |

## Step 3. ProblemSpec Generation

1. Short explanation:

   Convert the natural-language statement into OR-CI metadata. This generated
   metadata is the `problem.json` that OR-CI can validate and later use for
   verification.

2. Input data, content and file path:

   | Content | File Path |
   |---|---|
   | Source statement text | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/statements/BWOR-001.txt` |
   | Capability result in a current rerun | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-20-current-process-example/BWOR-001/spec/capability.json` |
   | ProblemSpec prompt/template code | `/Users/zhangbowen/Projects/OR/code/or_llm_agent/src/or_llm_agent/prompts.py` |

3. Who deals with these data:

   Nested Codex agent mode generates the JSON. Parent `or_llm_agent` extracts
   one JSON object and writes it as `problem.json`.

4. Output results, content and data path:

   | Content | File Path |
   |---|---|
   | Generated OR-CI ProblemSpec metadata | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/spec/problem.json` |
   | Spec generation status, validation status, attempts, and repair status | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/spec/status.json` |
   | Raw final spec output | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/raw/spec.txt` |
   | Raw first spec attempt | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/raw/spec-attempt-1.txt` |
   | ProblemSpec Codex event log | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/sessions/BWOR-001-spec/codex-events.jsonl` |
   | ProblemSpec Codex final message | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/sessions/BWOR-001-spec/last-message.md` |

## Step 4. ProblemSpec Validation

1. Short explanation:

   Validate that the generated `problem.json` has the required OR-CI metadata
   shape. This checks metadata structure, not source-statement fidelity.

2. Input data, content and file path:

   | Content | File Path |
   |---|---|
   | Generated ProblemSpec metadata | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/spec/problem.json` |
   | OR-CI metadata loader/validator implementation | `/Users/zhangbowen/Projects/OR/code/or-ci/src/or_ci` |

3. Who deals with these data:

   OR-CI through `or-ci validate-spec`, called by parent `or_llm_agent`.

4. Output results, content and data path:

   | Content | File Path |
   |---|---|
   | Validation status and validation return code saved in spec status | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/spec/status.json` |
   | Validation summary copied into case summary | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/summary.json` |
   | If validation fails: repair-loop raw attempts | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/raw/spec-attempt-<N>.txt` |

## Step 5. Model Generation

1. Short explanation:

   Generate a Python Gurobi submission from the validated ProblemSpec. The
   submission must expose `build_model(data: dict) -> gurobipy.Model` and return
   an unoptimized model.

2. Input data, content and file path:

   | Content | File Path |
   |---|---|
   | Valid generated ProblemSpec | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/spec/problem.json` |
   | Source statement context | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/statements/BWOR-001.txt` |

3. Who deals with these data:

   Nested Codex agent mode generates the Python code. Parent `or_llm_agent`
   extracts the Python block, writes the submission, checks for `build_model`,
   and records agent status.

4. Output results, content and data path:

   | Content | File Path |
   |---|---|
   | Generated Gurobi submission | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/submissions/BWOR-001.py` |
   | Raw model-generation output | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/raw/BWOR-001.txt` |
   | Parent agent status, including generation status and return code | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/agent-status/BWOR-001.json` |
   | Model-generation Codex event log | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/sessions/BWOR-001/codex-events.jsonl` |
   | Model-generation Codex final message | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/sessions/BWOR-001/last-message.md` |

## Step 6. OR-CI Verification

1. Short explanation:

   Verify the generated Gurobi submission against the generated ProblemSpec.
   OR-CI builds the model, extracts a linear ModelIR, solves with Gurobi, runs
   metamorphic checks, and writes a report.

2. Input data, content and file path:

   | Content | File Path |
   |---|---|
   | Generated ProblemSpec metadata | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/spec/problem.json` |
   | Generated Gurobi submission | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/submissions/BWOR-001.py` |

3. Who deals with these data:

   OR-CI verifies the generated spec/submission pair. Parent `or_llm_agent`
   calls OR-CI and records the OR-CI status/classification in the case summary.

4. Output results, content and data path:

   | Content | File Path |
   |---|---|
   | OR-CI report with solver status, objective values, ModelIR summary, cost-scaling checks, constraint-relaxation checks, and classification | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/reports/BWOR-001.json` |
   | Case summary fields such as `verification_status=PASS` and `classification=SUCCESS` | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/summary.json` |

Important interpretation:

- OR-CI `SUCCESS` means the generated code passed configured checks against the
  generated ProblemSpec.
- OR-CI `SUCCESS` does not prove that the generated ProblemSpec faithfully
  represents the original natural-language statement.

## Step 7. Source-Fidelity Review

1. Short explanation:

   Check whether the generated ProblemSpec and verified model preserve the
   original source statement. This is the gate that OR-CI intentionally does not
   cover.

2. Input data, content and file path:

   | Content | File Path |
   |---|---|
   | Original statement | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/statements/BWOR-001.txt` |
   | Generated ProblemSpec | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/spec/problem.json` |
   | OR-CI verification report | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/reports/BWOR-001.json` |
   | Case summary | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/summary.json` |

3. Who deals with these data:

   Human reviewer in manual mode, or nested Codex reviewer in agent mode.
   Parent `or_llm_agent` enforces that a case cannot be accepted unless
   metadata validation passed, OR-CI verification returned `PASS`, and the
   generated spec exists.

4. Output results, content and data path:

   | Content | File Path |
   |---|---|
   | Structured fidelity review with status, confidence, issues, evidence, and review note | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/spec/fidelity-review.json` |
   | Human-readable fidelity review | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/spec/fidelity-review.md` |
   | Updated case summary with `spec_fidelity_status` and `spec_fidelity_gate_status` | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/summary.json` |
   | Fidelity-review Codex event log | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/sessions/BWOR-001-fidelity-review/codex-events.jsonl` |
   | Fidelity-review Codex final message | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/BWOR-001/sessions/BWOR-001-fidelity-review/last-message.md` |

## Step 8. Fidelity Resolution

1. Short explanation:

   If source-fidelity review rejects a case, try to repair the ProblemSpec and
   rerun downstream generation, OR-CI verification, and fidelity review. The
   original failed artifact is preserved.

2. Input data, content and file path:

   | Content | File Path |
   |---|---|
   | Rejected case summary | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/<CASE_ID>/summary.json` |
   | Rejected structured fidelity report | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/<CASE_ID>/spec/fidelity-review.json` |
   | Original source statement | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/statements/<CASE_ID>.txt` |
   | Original generated ProblemSpec | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/<CASE_ID>/spec/problem.json` |

3. Who deals with these data:

   `or_llm_agent resolve-fidelity --mode agent` for one case, or
   `or_llm_agent resolve-fidelity-batch --mode agent` for a batch. Nested Codex
   attempts the repair. OR-CI revalidates and reverifies repaired artifacts.
   Parent `or_llm_agent` runs deterministic impact analysis if a residual
   mismatch remains.

4. Output results, content and data path:

   | Content | File Path |
   |---|---|
   | Repaired attempt directory for each rejected case | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/fidelity-resolution/<CASE_ID>/attempt-1` |
   | Repaired ProblemSpec, if repair reaches spec generation | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/fidelity-resolution/<CASE_ID>/attempt-1/spec/problem.json` |
   | Repaired Gurobi submission, if repair reaches model generation | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/fidelity-resolution/<CASE_ID>/attempt-1/submissions/<CASE_ID>.py` |
   | Repaired OR-CI report, if repair reaches verification | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/fidelity-resolution/<CASE_ID>/attempt-1/reports/<CASE_ID>.json` |
   | Per-case fidelity resolution result | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/fidelity-resolution/<CASE_ID>/attempt-1/fidelity-resolution.json` |
   | Aggregate fidelity resolution summary | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/fidelity-resolution-summary.json` |
   | Aggregate fidelity resolution report | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/fidelity-resolution-report.md` |

Possible resolution statuses:

- `repaired_accepted`
- `repair_failed`
- `residual_harmless_equivalent`
- `residual_material`
- `residual_unresolved`
- `skipped_not_rejected`

## Step 9. Final Batch Reporting

1. Short explanation:

   Summarize all cases and keep the statuses separate. A final report should not
   collapse capability, OR-CI verification, source fidelity, and fidelity
   resolution into one success label.

2. Input data, content and file path:

   | Content | File Path |
   |---|---|
   | All per-case summaries | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/<CASE_ID>/summary.json` |
   | All OR-CI reports | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/<CASE_ID>/reports/<CASE_ID>.json` |
   | All fidelity reviews | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/<CASE_ID>/spec/fidelity-review.json` |
   | Fidelity resolution summary, if resolution was run | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/fidelity-resolution-summary.json` |

3. Who deals with these data:

   Parent `or_llm_agent` writes machine-readable and human-readable batch
   reports. Human/researcher makes the final decision from these reports.

4. Output results, content and data path:

   | Content | File Path |
   |---|---|
   | Aggregate machine-readable batch summary | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/summary.json` |
   | Aggregate human-readable batch report | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/report.md` |
   | Fidelity resolution summary | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/fidelity-resolution-summary.json` |
   | Fidelity resolution report | `/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case/fidelity-resolution-report.md` |

## Acceptance Rule

A case should be treated as accepted by the current automated process only when
all required gates pass:

```text
capability_status = supported
spec_validation_status = passed
model_generation_status = generated
verification_status = PASS
OR-CI classification = SUCCESS
source fidelity = accepted / llm_accepted
or fidelity resolution = repaired_accepted / residual_harmless_equivalent
```

OR-CI `SUCCESS` alone is not enough. It proves only that the generated code
passed configured checks against the generated ProblemSpec.

## Current Evidence From The 20-Case Pilot

Latest completed pilot root:

```text
/Users/zhangbowen/Projects/OR/code/or-ci/artifacts/pilot/statement-solve-scale-2026-05-19-v2-20case
```

Results:

- 20/20 generated ProblemSpecs validated.
- 20/20 model submissions generated.
- 20/20 OR-CI verifications passed.
- 20/20 parent classifications were `SUCCESS`.
- Initial source-fidelity review accepted 15/20.
- Fidelity resolution repaired 3 rejected cases.
- 1 rejected case was residual harmless-equivalent.
- 1 rejected case remained residual material.

Main conclusion:

- the pipeline can generate OR-CI-valid artifacts at this scale.
- source-fidelity review is required before claiming full statement-to-result
  success.
- capability routing is now required before ProblemSpec generation so unsupported
  or ambiguous statements do not force invented metadata.
