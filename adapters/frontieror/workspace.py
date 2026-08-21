"""Workspace tools for the FrontierOR adaptation.

OR-LLM-Agent originally receives the whole problem, numbers included, as one
user message: the model can see every value in the statement. FrontierOR
instances are far too large for that (median 206 KB, largest 1.8 GB), so the
data has to live in a file. Giving only a path would leave the model modelling
blind -- strictly less than its original setting -- so it gets tools to inspect
the instance itself.

Semantics and limits are ported from DecisionBrain's WorkspaceToolset so that
both systems reach their data the same way: workspace-relative paths only,
identical caps, head/marker/tail truncation, and a shell that starts in the
workspace root with directory-changing commands refused.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# Ported verbatim from decisionbrain/core/workspace_tools.py so that neither
# system can inspect its instance more cheaply than the other.
TRUNCATION_NOTICE = "\n[truncated]\n"
MAX_OUTPUT_CHARS = 12_000
MAX_READ_BYTES = 1_000_000
SEARCH_MAX_FILES = 200
SEARCH_MAX_FILE_BYTES = 256 * 1024
SEARCH_DEFAULT_RESULTS = 20
SEARCH_MAX_RESULTS = 100
LIST_DEFAULT_ENTRIES = 200
LIST_MAX_ENTRIES = 1_000
SHELL_TIMEOUT_S = 600

DIRECTORY_CHANGE_COMMAND = re.compile(
    r"(?:^|&&|\|\||[;|\n(]|\bthen\b|\bdo\b|\belse\b)"
    r"\s*(?:command\s+|builtin\s+)?"
    r"(?:cd|chdir|pushd|popd|set-location|push-location|pop-location)(?=\s|$)",
    re.IGNORECASE,
)


class WorkspaceToolError(ValueError):
    """A user-facing tool error that is returned to the model rather than raised."""


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    """Keep the head and the tail, drop the middle, and say so.

    The marker is the model's only evidence that a range was not read in full,
    which is why truncation never raises.
    """
    if len(text) <= limit:
        return text, False
    if limit <= len(TRUNCATION_NOTICE) + 20:
        return text[:limit], True
    head_len = (limit - len(TRUNCATION_NOTICE)) // 2
    tail_len = limit - len(TRUNCATION_NOTICE) - head_len
    return f"{text[:head_len]}{TRUNCATION_NOTICE}{text[-tail_len:]}", True


def _format_size(size: int) -> str:
    for unit, scale in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size >= scale:
            return f"{size / scale:.1f} {unit}"
    return f"{size} B"


class Workspace:
    """A per-task directory holding the instance and nothing else.

    The real FrontierOR layout is never exposed: the reference solution sits in
    a sibling directory of the instance, so the agent is given a staged copy and
    is never told where that copy came from.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"workspace root is not a directory: {self.root}")

    # --- path handling -------------------------------------------------------

    def _resolve(self, raw_path: str) -> Path:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise WorkspaceToolError("path must be a non-empty string")
        if "\0" in raw_path:
            raise WorkspaceToolError("path contains a NUL byte")
        path = Path(raw_path)
        if path.is_absolute():
            raise WorkspaceToolError("absolute paths are not allowed")
        target = (self.root / path).resolve(strict=False)
        if target != self.root and self.root not in target.parents:
            raise WorkspaceToolError("path escapes workspace root")
        return target

    def _resolve_existing(self, raw_path: str, *, expected: str) -> Path:
        target = self._resolve(raw_path)
        if not target.exists():
            raise WorkspaceToolError(f"path does not exist: {raw_path}")
        if expected == "file" and not target.is_file():
            raise WorkspaceToolError(f"path is not a file: {raw_path}")
        if expected == "dir" and not target.is_dir():
            raise WorkspaceToolError(f"path is not a directory: {raw_path}")
        return target

    def _display(self, path: Path) -> str:
        return str(path.relative_to(self.root)) if path != self.root else "."

    # --- tools ---------------------------------------------------------------

    def list_files(self, path: str = ".", limit: int | None = None) -> str:
        target = self._resolve_existing(path, expected="dir")
        limit = LIST_DEFAULT_ENTRIES if limit is None else min(int(limit), LIST_MAX_ENTRIES)

        lines: list[str] = []
        for entry in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name)):
            if entry.is_dir():
                lines.append(f"{self._display(entry)}/")
                continue
            size = entry.stat().st_size
            label = f"{self._display(entry)}  ({_format_size(size)})"
            if size > MAX_READ_BYTES:
                # The same hint DecisionBrain gives its own agent: a full read
                # will fail, so the way in is shell.
                label += " [too large for read_file; use shell to extract what you need]"
            lines.append(label)

        if not lines:
            return "(empty directory)"
        text = "\n".join(lines[:limit])
        if len(lines) > limit:
            text += f"\n[{len(lines) - limit} more entries not listed]"
        return _truncate(text, MAX_OUTPUT_CHARS)[0]

    def read_file(
        self,
        path: str,
        max_chars: int | None = None,
        start_line: int | None = None,
        line_count: int | None = None,
    ) -> str:
        target = self._resolve_existing(path, expected="file")
        limit = MAX_OUTPUT_CHARS if max_chars is None else min(int(max_chars), MAX_OUTPUT_CHARS)

        if start_line is None and line_count is None:
            size = target.stat().st_size
            if size > MAX_READ_BYTES:
                raise WorkspaceToolError(
                    f"file too large: {size} bytes; limit is {MAX_READ_BYTES}"
                )
            text = self._read_all(target)
        else:
            text = self._read_line_range(
                target,
                first_line=1 if start_line is None else max(1, int(start_line)),
                line_count=None if line_count is None else max(1, int(line_count)),
            )

        return _truncate(text, limit)[0]

    def _read_all(self, target: Path) -> str:
        raw = target.read_bytes()
        if b"\0" in raw[:4096]:
            raise WorkspaceToolError("file appears to be binary")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceToolError("file is not valid UTF-8 text") from exc

    def _read_line_range(self, target: Path, *, first_line: int, line_count: int | None) -> str:
        """Stream the requested lines so a large file is never loaded in full.

        A single-line JSON file still costs one line's worth of memory, which is
        why 16 of the 65 instances can only be inspected through shell.
        """
        with target.open("rb") as handle:
            if b"\0" in handle.read(4096):
                raise WorkspaceToolError("file appears to be binary")

        selected: list[str] = []
        try:
            with target.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if line_number < first_line:
                        continue
                    if line_count is not None and line_number >= first_line + line_count:
                        break
                    selected.append(line)
        except UnicodeDecodeError as exc:
            raise WorkspaceToolError("file is not valid UTF-8 text") from exc

        if not selected:
            return f"(no lines at or after line {first_line})"
        return "".join(selected)

    def search_file(self, query: str, path: str = ".", max_results: int | None = None) -> str:
        if not isinstance(query, str) or not query:
            raise WorkspaceToolError("query must be a non-empty string")
        target = self._resolve_existing(path, expected="file" if Path(path).suffix else "dir")
        cap = SEARCH_DEFAULT_RESULTS if max_results is None else min(int(max_results), SEARCH_MAX_RESULTS)

        candidates = [target] if target.is_file() else sorted(
            p for p in target.rglob("*") if p.is_file()
        )[:SEARCH_MAX_FILES]

        hits: list[str] = []
        for candidate in candidates:
            if candidate.stat().st_size > SEARCH_MAX_FILE_BYTES:
                continue
            try:
                with candidate.open("r", encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if query in line:
                            hits.append(f"{self._display(candidate)}:{line_number}:{line.rstrip()}")
                            if len(hits) >= cap:
                                break
            except (UnicodeDecodeError, OSError):
                continue
            if len(hits) >= cap:
                break

        if not hits:
            return "(no matches)"
        return _truncate("\n".join(hits), MAX_OUTPUT_CHARS)[0]

    def shell(self, command: str, timeout_s: int = SHELL_TIMEOUT_S) -> str:
        if not isinstance(command, str) or not command.strip():
            raise WorkspaceToolError("command must be a non-empty string")
        if DIRECTORY_CHANGE_COMMAND.search(command):
            raise WorkspaceToolError(
                "directory-changing commands are not allowed; shell already starts in the "
                "workspace root"
            )

        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f"shell error: command exceeded {timeout_s}s and was terminated"

        output = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode != 0:
            output += f"\n[exit code {completed.returncode}]"
        return _truncate(output or "(no output)", MAX_OUTPUT_CHARS)[0]
