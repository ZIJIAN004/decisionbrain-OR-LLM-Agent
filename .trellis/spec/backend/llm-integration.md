# LLM Integration

> Client setup, message format, model dispatch, and prompt conventions.

---

## Overview

The project integrates OpenAI-compatible chat models and Anthropic Claude models.
The sync evaluator initializes module-level clients in `or_llm_eval.py`; the async
evaluator initializes async clients in `or_llm_eval_async_resilient.py`.

The canonical conversation format inside the project is OpenAI chat messages:
`list[{"role": "...", "content": "..."}]`. Claude calls convert this format into
a single Anthropic user message containing a formatted conversation transcript.

---

## Client Initialization

Load credentials with `python-dotenv` and environment variables. The OpenAI client
optionally uses `OPENAI_API_BASE`; the Anthropic client uses `CLAUDE_API_KEY`.

Example from `or_llm_eval.py`:

```python
load_dotenv()

openai_api_data = dict(
    api_key = os.getenv("OPENAI_API_KEY"),
    base_url = os.getenv("OPENAI_API_BASE")
)

anthropic_api_data = dict(
    api_key = os.getenv("CLAUDE_API_KEY"),
)
```

Example from `or_llm_eval.py`:

```python
openai_client = openai.OpenAI(
    api_key=openai_api_data['api_key'],
    base_url=openai_api_data['base_url'] if openai_api_data['base_url'] else None
)

anthropic_client = anthropic.Anthropic(
    api_key=anthropic_api_data['api_key']
)
```

The async evaluator mirrors this with `openai.AsyncOpenAI` and
`anthropic.AsyncAnthropic`.

---

## Model Dispatch

Model names beginning with `claude` are routed to Anthropic. Everything else uses
the OpenAI-compatible chat completions API. Preserve this prefix-based dispatch
unless the CLI contract changes.

Example from `or_llm_eval.py`:

```python
if model_name.lower().startswith("claude"):
    response = anthropic_client.messages.create(
        model=model_name,
        max_tokens=8192,
        temperature=temperature,
        messages=[{"role": "user", "content": conversation}]
    )
    return response.content[0].text
else:
    response = openai_client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature
    )
```

## Message Format

Build conversations as ordered role/content dictionaries. Add assistant outputs
before follow-up user repair prompts so the LLM has state.

Example from `or_llm_eval.py`:

```python
messages = [
    {"role": "system", "content": (
        "You are an operations research expert. Based on the optimization problem provided by the user, construct a mathematical model."
    )},
    {"role": "user", "content": user_question}
]

math_model = query_llm(messages, model_name)
messages.append({"role": "assistant", "content": validate_math_model})
```

Claude conversion preserves the same logical order.

Example from `or_llm_eval.py`:

```python
system_message = next((m["content"] for m in messages if m["role"] == "system"), "")
user_messages = [m["content"] for m in messages if m["role"] == "user"]
assistant_messages = [m["content"] for m in messages if m["role"] == "assistant"]

for user_msg, asst_msg in zip_longest(user_messages, assistant_messages, fillvalue=None):
    if user_msg:
        conversation += f"Human: {user_msg}\n\n"
```

---

## Prompt Constants

The async evaluator centralizes repeated prompts as constants. Use that style for
new reusable prompts rather than duplicating long strings in multiple functions.

Example from `or_llm_eval_async_resilient.py`:

```python
ERROR_FIX_PROMPT_TEMPLATE = (
    "代码执行出现错误，错误信息如下:\n{error_msg}\n请修复代码并重新提供完整的可执行代码。"
)
```

Example from `or_llm_eval_async_resilient.py`:

```python
messages.append({"role": "user", "content": ERROR_FIX_PROMPT_TEMPLATE.format(error_msg=error_msg)})
```

---

## Anti-Patterns

- Do not bypass `query_llm` or `async_query_llm` from agent code; those functions
  encode dispatch and error behavior.
- Do not pass Anthropic messages directly in new call sites while the rest of the
  project uses OpenAI-style role/content messages.
- Do not hard-code API keys or provider base URLs.
- Do not duplicate long prompt strings across sync and async paths when a named
  constant would keep retry behavior aligned.
- Do not change default temperature casually; current call sites default to `0.2`.
