from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from or_llm_agent.redaction import redact_text


@dataclass
class VerificationResult:
    returncode: int
    stdout: str
    stderr: str
    report: dict[str, Any] | None

    @property
    def classification(self) -> str:
        if self.report:
            return str(self.report.get("classification", "UNKNOWN"))
        return "VERIFY_COMMAND_FAILED"

    @property
    def status(self) -> str:
        if self.report:
            return str(self.report.get("status", "FAIL"))
        return "FAIL"

    @property
    def failure_check(self) -> str:
        if not self.report:
            return ""
        failures = self.report.get("failures") or []
        if not failures:
            return ""
        return str(failures[0].get("check", ""))

    @property
    def checks(self) -> list[str]:
        if not self.report:
            return []
        return [
            f"{check.get('name', 'unknown')}:{check.get('status', 'UNKNOWN')}"
            for check in self.report.get("checks", [])
        ]


def run_or_ci_verify(
    *,
    problem_path: Path,
    submission_path: Path,
    report_path: Path,
    cwd: Path | None = None,
) -> VerificationResult:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    command, _ = or_ci_command()
    result = subprocess.run(
        [
            *command,
            "verify",
            "--problem",
            str(problem_path),
            "--submission",
            str(submission_path),
            "--out",
            str(report_path),
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )

    report = None
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))

    return VerificationResult(
        returncode=result.returncode,
        stdout=redact_text(result.stdout),
        stderr=redact_text(result.stderr),
        report=report,
    )


def or_ci_command() -> tuple[list[str], str]:
    executable = shutil.which("or-ci")
    if executable:
        return [executable], "console script"
    return [sys.executable, "-m", "or_ci.cli"], "python module fallback"
