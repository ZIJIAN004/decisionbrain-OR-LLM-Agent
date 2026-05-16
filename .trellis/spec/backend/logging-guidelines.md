# Logging Guidelines

> How runtime information is emitted in this project.

---

## Overview

The project uses print-based logging. There is no configured structured logging
library for the OR-LLM-Agent scripts. This is intentional enough for research
evaluation: stdout is easy to inspect, redirect to files, and return through the
MCP tool.

Use clear section separators, per-case summaries, and final aggregate summaries.
When adding new output, make it useful in long batch logs where hundreds of cases
may be interleaved with generated-code output.

---

## Evaluation Progress Output

The synchronous evaluator logs each dataset record, execution status, comparison
result, and aggregate totals.

Example from `or_llm_eval.py`:

```python
print(f"=============== num {i} ==================")
print(user_question)
print('-------------')
print(f'solve: {is_solve_success}, llm: {llm_result}, ground truth: {answer}')
print(f'[Final] run pass: {pass_flag}, solve correct: {correct_flag}')
```

Example final summary from `or_llm_eval.py`:

```python
print(f'[Total {len(dataset)}] run pass: {pass_count}, solve correct: {correct_count}')
print(f'[Total fails {len(error_datas)}] error datas: {error_datas}')
```

Keep this style for CLI-facing evaluation results: concise labels, key values,
and enough context to identify the failing dataset item.

---

## Async Batch Output

The async evaluator logs batch boundaries and summaries. This makes long runs
readable even when individual cases produce large generated-code traces.

Example from `or_llm_eval_async_resilient.py`:

```python
print(f"\n{'='*50}")
print(f"Processing batch {batch_num + 1}/{total_batches} (cases {start_idx + 1}-{end_idx})")
print(f"{'='*50}\n")
```

Example from `or_llm_eval_async_resilient.py`:

```python
print(f"\nBatch {batch_num + 1} Summary:")
print(f"  Processed: {len(processed_batch_results)} cases")
print(f"  Run pass: {batch_pass_count}")
print(f"  Solve correct: {batch_correct_count}")
```

---

## Error Diagnostics

Log enough information to diagnose API and execution failures. Connection errors
include attempt count, model name, error details, timestamp, and retry delay.

Example from `or_llm_eval_async_resilient.py`:

```python
print(f"[Connection Error] Attempt {attempt + 1}/{max_attempts} failed for model {model_name}")
print(f"[Connection Error] Error details: {str(e)}")
print(f"[Connection Error] Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
```

Generated-code execution logs stdout on success and stderr on failure.

Example from `utils.py`:

```python
print("Python code executed successfully, output:\n")
print(result.stdout)
print(f"Python code execution error, error message:\n")
print(result.stderr)
```

---

## Log Files

The shell batch runner is responsible for redirecting script stdout/stderr into
timestamped files under `logs/`.

Example from `run_eval_batch_agent.sh`:

```bash
log_file="logs/eval_${dataset_name}${mode_suffix}_${sanitized_model}_$(date +%Y%m%d_%H%M%S).log"
eval "$cmd" > "$log_file" 2>&1
```

The filename encodes dataset, mode, model, and timestamp. Preserve that shape so
results from different sweeps are easy to compare.

---

## Show-Mode Output

`or_llm_show.py` adds richer terminal rendering for demos. It streams LLM chunks
and prints headers adjusted to terminal width.

Example from `or_llm_show.py`:

```python
print("LLM Output: ", end="", flush=True)
for chunk in response:
    if hasattr(chunk, 'choices') and len(chunk.choices) > 0:
        content = chunk.choices[0].delta.content
        if content:
            print(content, end="", flush=True)
```

Use this pattern only for interactive display. Batch runners should prefer
complete lines and summaries.

---

## Anti-Patterns

- Do not replace batch print summaries with silent return values; logs are the
  primary artifact of evaluation runs.
- Do not print raw environment variables, API keys, or credential dictionaries.
- Do not log only "failed"; include case id, failure category, or stderr.
- Do not add high-frequency character-by-character output to batch mode.
- Do not write logs outside `logs/` unless a CLI flag explicitly requests it.

