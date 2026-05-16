# Code Execution

> Extracting, running, timing out, and parsing LLM-generated Python code.

---

## Overview

The core agent asks the LLM to return a fenced Python code block, writes that code
to a temporary file, runs it in a child Python process, captures stdout/stderr,
and parses the Gurobi objective from stdout.

This subprocess boundary is important. Generated code is untrusted and may import
Gurobi, build large models, fail with syntax errors, or hang. Do not replace this
with in-process `exec`.

---

## Code Block Extraction

Generated code is extracted only from fenced Python blocks. Missing and empty
blocks are normal model-output failures and return failure tuples.

Example from `utils.py`:

```python
python_code_blocks = re.findall(r'```python\s*([\s\S]*?)```', text_content)

if not python_code_blocks:
    print("No Python code blocks found.")
    return False, "No Python code blocks found"
```

Example from `utils.py`:

```python
for code_block in python_code_blocks:
    code_block = code_block.strip()
    if not code_block:
        print("Found an empty Python code block, skipped.")
        continue
```

Prompts in the agent explicitly request this format. Keep prompt and parser
changes aligned.

---

## Sync Subprocess Pattern

The sync executor writes each code block to a temporary `.py` file and runs it
with the current Python interpreter. `check=False` is intentional because stderr
is returned to the LLM repair loop.

Example from `utils.py`:

```python
with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp_file:
    tmp_file.write(code_block)
    temp_file_path = tmp_file.name

result = subprocess.run([sys.executable, temp_file_path], capture_output=True, text=True, check=False)
```

Temporary files are removed in `finally`.

Example from `utils.py`:

```python
finally:
    if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
        os.remove(temp_file_path)
```

---

## Async Subprocess Pattern

The async evaluator mirrors the temp-file pattern but uses an async subprocess and
a 60-second timeout.

Example from `or_llm_eval_async_resilient.py`:

```python
proc = await asyncio.create_subprocess_exec(
    sys.executable,
    temp_file_path,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE
)
```

Example from `or_llm_eval_async_resilient.py`:

```python
stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
```

When adding execution options, implement them in both sync and async paths only
when both paths need the behavior.

---

## Objective Parsing

Objective extraction is centralized in `utils.py`. It detects infeasible models
first, then searches common Gurobi result strings.

Example from `utils.py`:

```python
if "Model is infeasible" in output_text:
    return None

match = re.search(r'Best objective\s+([\d.e+-]+)', output_text)
if not match:
    match = re.search(r'Optimal objective\s+([\d.e+-]+)', output_text)
```

Execution success with no parsed objective returns `True, "None"`, which the
agent treats as a possible no-solution signal.

Example from `or_llm_eval.py`:

```python
if is_solve_success:
    if not is_number_string(result):
        print('!![No available solution warning]!!')
        messages.append({"role": "user", "content": (
            "The current model resulted in *no feasible solution*."
        )})
```

---

## Anti-Patterns

- Do not use `exec`, `eval`, or import generated code as a module.
- Do not remove temp-file cleanup.
- Do not raise on nonzero generated-code exit; return stderr to the repair loop.
- Do not parse objectives in entry-point scripts; extend `extract_best_objective`.
- Do not assume all successful Gurobi runs print `Best objective`; current parsing
  also handles `Optimal objective` and `Optimal cost`.
