# Error Handling

> How errors are represented, retried, and surfaced in this project.

---

## Overview

The project uses simple return values and printed diagnostics instead of custom
exception hierarchies. Most agent and executor functions return tuples such as
`(success, result)` or `(success, result, messages)`. Exceptions are reserved for
unexpected local failures, parser failures, and SDK errors that cannot be handled
inside the immediate retry loop.

---

## Return-Value Pattern

Executors return failure data instead of raising for normal generated-code
failures. This lets the calling agent append the failure to the conversation and
ask the model to repair the code.

Example from `utils.py`:

```python
if not python_code_blocks:
    print("No Python code blocks found.")
    return False, "No Python code blocks found"

if result.returncode == 0:
    best_obj = extract_best_objective(result.stdout)
    return True, str(best_obj)
else:
    return False, result.stderr
```

Example from `or_llm_eval_async_resilient.py`:

```python
success, gurobi_code = await async_query_llm(messages, model_name)
if not success:
    print(f"LLM生成Gurobi代码失败: {gurobi_code}")
    return False, f"CODE_GEN_ERROR: {gurobi_code}", ""
```

---

## LLM Retry Pattern

Code execution errors are fed back into the same conversation. Preserve the
assistant message before adding the user repair request; this gives the LLM both
the code it wrote and the concrete execution failure.

Example from `or_llm_eval.py`:

```python
messages.append({"role": "assistant", "content": gurobi_code})
messages.append({"role": "user", "content": f"Code execution encountered an error, error message is as follows:\n{error_msg}\nPlease fix the code and provide the complete executable code again."})

gurobi_code = query_llm(messages, model_name)
```

Example from `or_llm_eval_async_resilient.py`:

```python
messages.append({"role": "assistant", "content": gurobi_code})
messages.append({"role": "user", "content": ERROR_FIX_PROMPT_TEMPLATE.format(error_msg=error_msg)})

success, gurobi_code = await async_query_llm(messages, model_name)
```

---

## API Error Handling

The async evaluator retries only connection errors. Other SDK exceptions return
immediately because they usually indicate request shape, credentials, or model
configuration problems.

Example from `or_llm_eval_async_resilient.py`:

```python
except (openai.APIConnectionError, anthropic.APIConnectionError) as e:
    print(f"[Connection Error] Attempt {attempt + 1}/{max_attempts} failed for model {model_name}")
    if attempt < max_attempts - 1:
        wait_time = 60 * (attempt + 1)
        await asyncio.sleep(wait_time)
    else:
        return False, f"Connection error after {max_attempts} attempts: {str(e)}"

except Exception as e:
    return False, f"API error: {str(e)}"
```

Keep this distinction. Retrying malformed requests wastes quota and slows batch
runs.

---

## Dataset Parse Handling

Dataset loaders tolerate bad JSONL records by warning and continuing. This is
appropriate for benchmark sweeps where a single malformed line should not abort
the whole run.

Example from `or_llm_eval.py`:

```python
try:
    item = json.loads(line)
    dataset[str(dataset_item['id'])] = dataset_item
except json.JSONDecodeError as e:
    print(f"Warning: Could not parse line {line_num}: {line}")
    continue
```

## Timeouts

Use timeouts around untrusted generated code and MCP calls. Async subprocesses
use `asyncio.wait_for`; MCP uses `signal.alarm`.

Example from `or_llm_eval_async_resilient.py`:

```python
stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
```

Example from `MCP/mcp_server.py`:

```python
signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(timeout)
```

---

## Anti-Patterns

- Do not raise on ordinary generated-code failure; return the stderr so the agent
  can request a repair.
- Do not retry every exception from the LLM SDK. Only connection failures are
  retried in the async evaluator.
- Do not swallow task exceptions in batch mode without recording a failure reason.
- Do not remove the timeout cleanup paths around subprocess and MCP execution.
- Do not print API keys, base URLs with embedded secrets, or full environment data.
