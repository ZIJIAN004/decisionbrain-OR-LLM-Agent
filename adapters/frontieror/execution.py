"""Adapter-owned execution of generated solver code."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from utils import extract_best_objective

from . import config
from .sandbox import SandboxUnavailable
from .sandbox import command as sandbox_command


def build_executor(workspace: Path):
    attempt = 0
    runner_source = Path(__file__).with_name("solver_runner.py")

    def execute(text_content: str) -> tuple[bool, str]:
        nonlocal attempt
        blocks = re.findall(r"```python\s*([\s\S]*?)```", text_content)
        if not blocks:
            return False, "No Python code blocks found"
        source = next((block.strip() for block in blocks if block.strip()), "")
        if not source:
            return False, "No valid code blocks found"

        attempt += 1
        source_path = workspace / "solver.py"
        runner_path = workspace / ".frontieror_solver_runner.py"
        candidate_path = workspace / "raw_candidate.json"
        source_path.write_text(source, encoding="utf-8")
        shutil.copy2(runner_source, runner_path)

        argv = [
            sys.executable,
            "/work/.frontieror_solver_runner.py" if sys.platform == "linux" else str(runner_path),
            "/work/solver.py" if sys.platform == "linux" else str(source_path),
            "/work/raw_candidate.json" if sys.platform == "linux" else str(candidate_path),
            "--timeout",
            str(config.SOLVER_TIMEOUT_SECONDS),
        ]
        env = os.environ.copy()
        env["FRONTIEROR_SOLVER_ATTEMPT"] = str(attempt)
        try:
            completed = subprocess.run(
                sandbox_command(workspace, argv),
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=config.SOLVER_TIMEOUT_SECONDS + 60,
                check=False,
                env=env,
            )
        except SandboxUnavailable as exc:
            return False, str(exc)
        except subprocess.TimeoutExpired:
            return False, f"solver process exceeded {config.SOLVER_TIMEOUT_SECONDS + 60}s"

        output = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode != 0:
            return False, output[-12_000:]
        objective = extract_best_objective(completed.stdout or "")
        if objective is None and candidate_path.is_file():
            import json

            objective = json.loads(candidate_path.read_text(encoding="utf-8")).get("objective")
        return True, str(objective)

    return execute
