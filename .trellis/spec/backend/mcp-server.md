# MCP Server

> FastMCP wrapper conventions for exposing the OR-LLM agent as a tool.

---

## Overview

`MCP/mcp_server.py` is a thin stdio MCP server. It exposes one tool,
`get_operation_research_problem_answer`, which calls the synchronous
`or_llm_agent`, captures all printed output, and returns that output as the tool
response.

Keep the MCP layer small. Core model prompting, code generation, and execution
belong in the root agent modules and `utils.py`.

---

## Import Path Setup

Because the project has a flat layout and no package namespace, the MCP server
adds the repository root to `sys.path` before importing `or_llm_eval`.

Example from `MCP/mcp_server.py`:

```python
import sys
import os
# Add parent directory to Python path to find or_llm_eval module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP
from or_llm_eval import or_llm_agent
```

Do not move this path setup into `or_llm_eval.py`; it is an adapter concern.

---

## Server and Tool Definition

The server name is `or_llm_agent`. Tool arguments are plain Python types so
FastMCP can expose them through the stdio transport.

Example from `MCP/mcp_server.py`:

```python
mcp = FastMCP("or_llm_agent")

@mcp.tool()
def get_operation_research_problem_answer(user_question: str, timeout: int = 600) -> str:
    """
    Use the agent to solve the optimization problem.
    """
```

The module runs the MCP server when invoked directly.

Example from `MCP/mcp_server.py`:

```python
if __name__ == "__main__":
    mcp.run()
```

Use `uv run python MCP/mcp_server.py` when manually checking server startup.

---

## Stdout Capture

The sync agent is print-heavy. The MCP tool captures stdout into a string and
returns it, instead of letting prints leak to the MCP protocol stream.

Example from `MCP/mcp_server.py`:

```python
buffer2 = io.StringIO()
with redirect_stdout(buffer2):
    or_llm_agent(user_question)
return buffer2.getvalue()
```

This is the key adapter behavior. If the agent return value changes later, keep
stdout capture unless the core agent is redesigned to return structured data.

---

## Timeout Handling

The MCP wrapper uses `signal.SIGALRM` to cap wall-clock runtime. The alarm is
always cleared in `finally`.

Example from `MCP/mcp_server.py`:

```python
def timeout_handler(signum, frame):
    raise TimeoutError(f"Operation timed out after {timeout} seconds")

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(timeout)
```

Example from `MCP/mcp_server.py`:

```python
except TimeoutError as e:
    return f"Error: {str(e)}"
finally:
    signal.alarm(0)
```

Be aware that `signal.alarm` is Unix-oriented and process-global. Do not reuse it
inside async batch code.

---

## Tool Response Contract

The current tool returns a plain string containing the agent transcript:
mathematical model, generated Gurobi code, execution output, and final result.
It does not return JSON.

This matches the code in `MCP/mcp_server.py`:

```python
def get_operation_research_problem_answer(user_question: str, timeout: int = 600) -> str:
    ...
    return buffer2.getvalue()
```

Only change this to structured output if the client contract is updated at the
same time.

---

## Anti-Patterns

- Do not write tool output directly with `print`; capture and return it.
- Do not duplicate `or_llm_agent` logic inside the MCP server.
- Do not add async batch execution to this sync MCP wrapper without redesigning
  timeout and subprocess behavior.
- Do not return partial stdout after non-timeout exceptions unless the exception
  handling contract is explicitly changed.
- Do not add more path mutation than the existing repository-root insertion.

