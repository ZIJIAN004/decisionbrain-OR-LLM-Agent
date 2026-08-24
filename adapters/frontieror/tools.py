"""Tool schemas and dispatch for the workspace tools.

The descriptions are close ports of DecisionBrain's, including the guidance
about large or single-line JSON files, because what a model can find out about
its instance depends as much on how the tool is described as on what it does.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from .workspace import (
    LIST_DEFAULT_ENTRIES,
    MAX_OUTPUT_CHARS,
    MAX_READ_BYTES,
    SEARCH_MAX_FILE_BYTES,
    SEARCH_MAX_FILES,
    Workspace,
    WorkspaceToolError,
)


def schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write UTF-8 text to a file inside the workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Workspace-relative file path."},
                        "content": {"type": "string", "description": "Complete file contents."},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_python",
                "description": "Execute a workspace-local .py script in the task sandbox and return stdout/stderr.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Workspace-relative .py script path."},
                        "timeout_s": {"type": "integer", "minimum": 1, "maximum": 600},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": (
                    "List the contents of a directory in the working directory. Each file is "
                    f"shown with its size; default {LIST_DEFAULT_ENTRIES} entries."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Optional directory relative to the working directory; defaults to .",
                        },
                        "limit": {"type": "integer", "minimum": 1},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": (
                    "Read a UTF-8 text file from the working directory. Full-file reads larger "
                    f"than {MAX_READ_BYTES} bytes fail; do not use them for large files. Every "
                    f"response is capped at {MAX_OUTPUT_CHARS} characters and max_chars can only "
                    "lower that cap. Past the cap the result is the head of the range, the marker "
                    "[truncated], then the tail: the middle is dropped and no error is raised, so "
                    "treat that marker as proof the range was not fully read. For a multi-line "
                    "large file, request start_line and line_count, and retry with a smaller "
                    "line_count while the marker keeps appearing. For a large or single-line JSON "
                    "file, use shell to extract only the relevant fields."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path relative to the working directory."},
                        "max_chars": {"type": "integer", "minimum": 1},
                        "start_line": {"type": "integer", "minimum": 1},
                        "line_count": {"type": "integer", "minimum": 1},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_file",
                "description": (
                    "Read-only literal text search in UTF-8 files under the working directory. "
                    "Returns matching path, 1-based line number, and line text. Case-sensitive, "
                    f"no regex. Skips files larger than {SEARCH_MAX_FILE_BYTES} bytes and scans at "
                    f"most {SEARCH_MAX_FILES} files."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Non-empty literal text to find."},
                        "path": {"type": "string", "description": "Optional file or directory; defaults to ."},
                        "max_results": {"type": "integer", "minimum": 1},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shell",
                "description": (
                    "Run a shell command starting in the working directory. Use it to extract "
                    "specific fields from a large or single-line JSON file, for example with "
                    "python -c. Directory-changing commands are refused because the shell already "
                    f"starts in the working directory. Output is capped at {MAX_OUTPUT_CHARS} "
                    "characters."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command to run."},
                    },
                    "required": ["command"],
                },
            },
        },
    ]


def dispatcher(workspace: Workspace) -> Callable[[str, str], str]:
    """Bind the tool names to one workspace.

    Tool errors come back to the model as text rather than raising: a refused
    path or a too-large file is information the model should act on, not a crash.
    """
    handlers = {
        "write_file": workspace.write_file,
        "run_python": workspace.run_python,
        "list_files": workspace.list_files,
        "read_file": workspace.read_file,
        "search_file": workspace.search_file,
        "shell": workspace.shell,
    }

    def call(name: str, arguments: str) -> str:
        handler = handlers.get(name)
        if handler is None:
            return f"error: unknown tool {name!r}"
        try:
            kwargs = json.loads(arguments) if arguments and arguments.strip() else {}
        except json.JSONDecodeError as exc:
            return f"error: arguments were not valid JSON ({exc})"
        if not isinstance(kwargs, dict):
            return "error: arguments must be a JSON object"
        try:
            return handler(**kwargs)
        except WorkspaceToolError as exc:
            return f"{name} error: {exc}"
        except TypeError as exc:
            return f"{name} error: bad arguments ({exc})"

    return call
