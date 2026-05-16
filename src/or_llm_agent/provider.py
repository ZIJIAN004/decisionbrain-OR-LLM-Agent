from __future__ import annotations

import asyncio
import os
import time
from itertools import zip_longest
from typing import Any

import anthropic
import openai
from dotenv import load_dotenv

from or_llm_agent.redaction import redact_text


Message = dict[str, str]


def is_claude_model(model_name: str) -> bool:
    return model_name.lower().startswith("claude")


def required_env_names(model_name: str) -> tuple[str, ...]:
    if is_claude_model(model_name):
        return ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY")
    return ("OPENAI_API_KEY",)


def query_llm(messages: list[Message], model_name: str = "o3-mini", temperature: float = 0.2) -> str:
    """Call the configured provider using the project's existing dispatch rules."""
    load_dotenv()
    if is_claude_model(model_name):
        response = _anthropic_client().messages.create(
            model=model_name,
            max_tokens=8192,
            temperature=temperature,
            messages=[{"role": "user", "content": build_anthropic_conversation(messages)}],
        )
        return _anthropic_text(response)

    response = _openai_client().chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
    )
    return response.choices[0].message.content or ""


async def async_query_llm(
    messages: list[Message],
    model_name: str = "o3-mini",
    temperature: float = 0.2,
    max_attempts: int = 3,
) -> tuple[bool, str]:
    """Async provider call with the existing connection-error retry behavior."""
    load_dotenv()
    for attempt in range(max_attempts):
        try:
            if is_claude_model(model_name):
                response = await _async_anthropic_client().messages.create(
                    model=model_name,
                    max_tokens=8192,
                    temperature=temperature,
                    messages=[{"role": "user", "content": build_anthropic_conversation(messages)}],
                )
                return True, _anthropic_text(response)

            response = await _async_openai_client().chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
            )
            return True, response.choices[0].message.content or ""

        except (openai.APIConnectionError, anthropic.APIConnectionError) as exc:
            safe_error = redact_text(exc)
            print(f"[Connection Error] Attempt {attempt + 1}/{max_attempts} failed for model {model_name}")
            print(f"[Connection Error] Error details: {safe_error}")
            print(f"[Connection Error] Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            if attempt < max_attempts - 1:
                wait_time = 60 * (attempt + 1)
                print(f"[Connection Error] Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                print(f"[Connection Error] Max attempts ({max_attempts}) reached. Continuing with failure.")
                return False, f"Connection error after {max_attempts} attempts: {safe_error}"

        except Exception as exc:
            safe_error = redact_text(exc)
            print(f"[API Error] Non-connection error occurred with model {model_name}: {safe_error}")
            print(f"[API Error] Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            return False, f"API error: {safe_error}"

    return False, "Unknown error occurred"


def build_anthropic_conversation(messages: list[Message]) -> str:
    system_message = next((message["content"] for message in messages if message["role"] == "system"), "")
    user_messages = [message["content"] for message in messages if message["role"] == "user"]
    assistant_messages = [message["content"] for message in messages if message["role"] == "assistant"]

    conversation = system_message + "\n\n"
    for user_msg, assistant_msg in zip_longest(user_messages, assistant_messages, fillvalue=None):
        if user_msg:
            conversation += f"Human: {user_msg}\n\n"
        if assistant_msg:
            conversation += f"Assistant: {assistant_msg}\n\n"

    if len(user_messages) > len(assistant_messages):
        conversation += f"Human: {user_messages[-1]}\n\n"
    return conversation


def _openai_client() -> openai.OpenAI:
    return openai.OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_API_BASE") or None,
    )


def _async_openai_client() -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_API_BASE") or None,
    )


def _anthropic_key() -> str | None:
    return os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")


def _anthropic_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=_anthropic_key())


def _async_anthropic_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=_anthropic_key())


def _anthropic_text(response: Any) -> str:
    if not response.content:
        return ""
    first = response.content[0]
    return getattr(first, "text", str(first))

