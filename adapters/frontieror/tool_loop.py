"""A tool-calling loop for the modelling step.

OR-LLM-Agent has no tool machinery at all: provider.query_llm (src/or_llm_agent/
provider.py:29) is one completion returning a string, and the repository
contains no tools= argument, no tool_calls handling and no function_call
handling. This loop is therefore an addition, not a configuration, and is kept
outside the upstream files so the boundary of what was added stays visible.

It is used for the first LLM call of a task only -- the step that derives the
mathematical model. Writing the Gurobi code and repairing it afterwards run
exactly as upstream does.

What the loop observes is appended to the caller's message list rather than
discarded. or_llm_agent keeps one list for the whole task (or_llm_eval.py:73-107)
and the later steps read it, so upstream every step could see the numbers, which
were inline in the prompt. Moving the numbers into a file and letting the
observations die with this call would leave the code-writing step with only an
abstract model and no way to know what the fields are actually called.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

import openai

MAX_TOOL_ROUNDS = 10


def _client() -> openai.OpenAI:
    """Same environment variables the upstream provider uses, so switching
    endpoints needs no code change here either."""
    return openai.OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_API_BASE") or None,
    )


def query_llm_with_tools(
    messages: list[dict[str, Any]],
    model_name: str,
    tool_schemas: list[dict[str, Any]],
    call_tool: Callable[[str, str], str],
    temperature: float = 0.2,
    on_call: Callable[[str, str, str], None] | None = None,
) -> str:
    """Run the conversation until the model answers without calling a tool.

    Returns the final assistant text, and appends the tool exchange to
    `messages` in place so the steps that follow keep what was observed.
    `on_call` receives (name, arguments, result) for every tool call so the whole
    exchange can be logged: the log is what makes it checkable afterwards that
    the agent only ever looked at its own workspace.
    """
    client = _client()
    conversation = [dict(m) for m in messages]
    observed = len(conversation)

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=model_name,
            messages=conversation,
            temperature=temperature,
            tools=tool_schemas,
        )
        message = response.choices[0].message
        calls = message.tool_calls or []

        if not calls:
            messages.extend(conversation[observed:])
            return message.content or ""

        conversation.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in calls
                ],
            }
        )

        for call in calls:
            result = call_tool(call.function.name, call.function.arguments)
            if on_call is not None:
                on_call(call.function.name, call.function.arguments, result)
            conversation.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )

    # Out of rounds. Rather than returning whatever half-finished text the last
    # reply held, ask once more with tools withheld so the step still produces a
    # model, and the transcript shows why.
    conversation.append(
        {
            "role": "user",
            "content": (
                f"You have used the {MAX_TOOL_ROUNDS} inspection calls available. "
                "Give the mathematical model now, using what you have learned."
            ),
        }
    )
    final = client.chat.completions.create(
        model=model_name, messages=conversation, temperature=temperature
    )
    messages.extend(conversation[observed:])
    return final.choices[0].message.content or ""
