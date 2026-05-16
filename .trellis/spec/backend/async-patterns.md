# Async Patterns

> Async client usage, retries, subprocess execution, and batch evaluation.

---

## Overview

`or_llm_eval_async_resilient.py` is the canonical async implementation. It does
not wrap the sync evaluator. It has async SDK clients, async LLM dispatch, async
generated-code subprocess execution, and batched concurrent dataset processing.

Keep async changes in this module unless a helper is truly reusable by sync code.

---

## Async Clients

Use async SDK clients at module scope, mirroring the sync client setup.

Example from `or_llm_eval_async_resilient.py`:

```python
openai_client = openai.AsyncOpenAI(
    api_key=openai_api_data['api_key'],
    base_url=openai_api_data['base_url'] if openai_api_data['base_url'] else None
)

anthropic_client = anthropic.AsyncAnthropic(
    api_key=anthropic_api_data['api_key']
)
```

Do not call sync clients from async functions. That blocks the event loop and
defeats the batch runner.

---

## Async LLM Query Pattern

`async_query_llm` returns `(success, result)` rather than raising after all retry
attempts. Connection errors are retried with linear minute-scale backoff; other
errors return immediately.

Example from `or_llm_eval_async_resilient.py`:

```python
for attempt in range(max_attempts):
    try:
        response = await openai_client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=temperature
        )
        return True, response.choices[0].message.content
```

Example from `or_llm_eval_async_resilient.py`:

```python
except (openai.APIConnectionError, anthropic.APIConnectionError) as e:
    if attempt < max_attempts - 1:
        wait_time = 60 * (attempt + 1)
        await asyncio.sleep(wait_time)
    else:
        return False, f"Connection error after {max_attempts} attempts: {str(e)}"
```

---

## Async Subprocess Execution

Generated code must run in a child Python process. The async implementation uses
`asyncio.create_subprocess_exec` and caps runtime with `asyncio.wait_for`.

Example from `or_llm_eval_async_resilient.py`:

```python
proc = await asyncio.create_subprocess_exec(
    sys.executable,
    temp_file_path,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE
)

stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
```

Timeouts kill the subprocess and return a normal failure tuple.

Example from `or_llm_eval_async_resilient.py`:

```python
except asyncio.TimeoutError:
    try:
        proc.kill()
        await proc.wait()
    except:
        pass
    return False, "Code execution timeout (60 seconds) - possible infinite loop"
```

---

## Batch Concurrency

Batch processing is controlled manually. The runner converts dataset items to a
list, slices fixed-size batches, creates coroutine objects, and awaits them with
`asyncio.gather`.

Example from `or_llm_eval_async_resilient.py`:

```python
batch_size = 50
for batch_num in range(total_batches):
    start_idx = batch_num * batch_size
    end_idx = min(start_idx + batch_size, len(dataset_items))
    batch_items = dataset_items[start_idx:end_idx]
```

Example from `or_llm_eval_async_resilient.py`:

```python
tasks = []
for i, d in batch_items:
    task = process_single_case(i, d, args)
    tasks.append(task)

batch_results = await asyncio.gather(*tasks, return_exceptions=True)
```

Keep `return_exceptions=True`; the following loop records failed task ids without
aborting the whole batch. The async agent should continue separating math-model
generation, code generation/execution, and optional debug repair.

---

## Anti-Patterns

- Do not use `time.sleep` in async functions; use `await asyncio.sleep`.
- Do not call `subprocess.run` from async generated-code execution.
- Do not remove `return_exceptions=True` unless the runner is redesigned to record
  partial batch progress another way.
- Do not increase `batch_size` without considering provider rate limits and Gurobi
  subprocess load.
- Do not let timeout cleanup skip temp-file cleanup in the surrounding `finally`.
