from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from or_llm_agent.bwor import (
    default_bwor_dataset,
    default_or_ci_root,
    default_problem_path,
    load_bwor_record,
    load_problem,
    repo_root,
)
from or_llm_agent.code_blocks import extract_python_module, has_build_model_contract
from or_llm_agent.or_ci import VerificationResult, or_ci_command, run_or_ci_verify
from or_llm_agent.prompts import OR_CI_SYSTEM_PROMPT, build_or_ci_prompt
from or_llm_agent.provider import query_llm, required_env_names
from or_llm_agent.redaction import env_status, redact_text


class CLIError(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except CLIError as exc:
        print(redact_text(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def _main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "health":
        return health_command(args)
    if args.command == "generate":
        return generate_command(args)
    if args.command == "verify":
        return verify_command(args)
    if args.command == "pilot":
        return pilot_command(args)
    parser.print_help()
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="or-llm-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("health", help="check local OR-LLM-Agent and OR-CI readiness")
    health.add_argument("--model", default="o3-mini")
    health.add_argument("--live", action="store_true", help="perform a minimal provider request")

    generate = subparsers.add_parser("generate", help="generate an OR-CI build_model submission for a BWOR id")
    generate.add_argument("--bwor-id", required=True)
    generate.add_argument("--model", default="o3-mini")
    generate.add_argument("--out", required=True, type=Path)
    generate.add_argument("--raw", required=True, type=Path)
    generate.add_argument("--dataset", default=default_bwor_dataset(), type=Path)
    generate.add_argument("--or-ci-root", default=default_or_ci_root(), type=Path)

    verify = subparsers.add_parser("verify", help="verify a generated submission with standalone OR-CI")
    verify.add_argument("--problem", required=True, type=Path)
    verify.add_argument("--submission", required=True, type=Path)
    verify.add_argument("--out", required=True, type=Path)

    pilot = subparsers.add_parser("pilot", help="run generate plus OR-CI verify for a BWOR batch")
    pilot.add_argument("--ids", required=True, nargs="+")
    pilot.add_argument("--model", default="o3-mini")
    pilot.add_argument("--artifact-dir", required=True, type=Path)
    pilot.add_argument("--dataset", default=default_bwor_dataset(), type=Path)
    pilot.add_argument("--or-ci-root", default=default_or_ci_root(), type=Path)
    pilot.add_argument("--reuse-submissions", action="store_true")
    return parser


def health_command(args: argparse.Namespace) -> int:
    load_dotenv()
    checks: list[tuple[str, bool, str]] = []

    env_names = required_env_names(args.model)
    if len(env_names) == 1:
        checks.append((env_names[0], os.getenv(env_names[0]) is not None, env_status(*env_names)))
    else:
        checks.append(("Claude provider key", any(os.getenv(name) for name in env_names), env_status(*env_names)))

    checks.append(("OPENAI_API_BASE", True, env_status("OPENAI_API_BASE") if not args.model.lower().startswith("claude") else "not used"))
    checks.append(_check_gurobi())
    checks.append(_check_or_ci_import())
    checks.append(_check_or_ci_cli())
    if args.live:
        checks.append(_check_live_provider(args.model))

    for name, ok, detail in checks:
        label = "OK" if ok else "FAIL"
        print(f"{label} {name}: {redact_text(detail)}")

    return 0 if all(ok for _, ok, _ in checks) else 1


def generate_command(args: argparse.Namespace) -> int:
    result = generate_submission(
        problem_id=args.bwor_id,
        model=args.model,
        out_path=args.out,
        raw_path=args.raw,
        dataset_path=args.dataset,
        or_ci_root=args.or_ci_root,
    )
    print(f"{args.bwor_id}: generation={result['generation_status']}")
    if result["generation_error"]:
        print(redact_text(result["generation_error"]), file=sys.stderr)
    return 0 if result["generation_status"] == "generated" else 1


def verify_command(args: argparse.Namespace) -> int:
    verification = run_or_ci_verify(
        problem_path=args.problem,
        submission_path=args.submission,
        report_path=args.out,
        cwd=repo_root(),
    )
    _print_verification(verification)
    return verification.returncode


def pilot_command(args: argparse.Namespace) -> int:
    artifact_dir = args.artifact_dir.resolve()
    submissions_dir = artifact_dir / "submissions"
    raw_dir = artifact_dir / "raw"
    reports_dir = artifact_dir / "reports"
    submissions_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for problem_id in args.ids:
        submission_path = submissions_dir / f"{problem_id}.py"
        raw_path = raw_dir / f"{problem_id}.txt"
        report_path = reports_dir / f"{problem_id}.json"
        problem_path = default_problem_path(problem_id, args.or_ci_root)

        if args.reuse_submissions and submission_path.exists():
            generation = {
                "generation_status": "reused",
                "generation_error": "",
                "raw_response": raw_path,
                "submission": submission_path,
            }
        else:
            generation = generate_submission(
                problem_id=problem_id,
                model=args.model,
                out_path=submission_path,
                raw_path=raw_path,
                dataset_path=args.dataset,
                or_ci_root=args.or_ci_root,
            )

        verification = run_or_ci_verify(
            problem_path=problem_path,
            submission_path=submission_path,
            report_path=report_path,
            cwd=repo_root(),
        )
        row = build_pilot_row(
            artifact_dir=artifact_dir,
            problem_id=problem_id,
            model=args.model,
            generation=generation,
            verification=verification,
            report_path=report_path,
        )
        rows.append(row)
        print(f"{problem_id}: generation={row['generation_status']} classification={row['classification']}")

    summary = summarize(rows)
    (artifact_dir / "summary.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_markdown_report(artifact_dir / "report.md", args, summary, rows)
    print(f"wrote {artifact_dir / 'report.md'}")
    return 0


def generate_submission(
    *,
    problem_id: str,
    model: str,
    out_path: Path,
    raw_path: Path,
    dataset_path: Path,
    or_ci_root: Path,
) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    record = load_bwor_record(dataset_path, problem_id)
    problem_path = default_problem_path(problem_id, or_ci_root)
    if not problem_path.is_file():
        raise CLIError(f"problem file does not exist: {problem_path}")
    problem = load_problem(problem_path)
    messages = [
        {"role": "system", "content": OR_CI_SYSTEM_PROMPT},
        {"role": "user", "content": build_or_ci_prompt(problem_id, record, problem)},
    ]

    try:
        response = query_llm(messages, model_name=model)
    except Exception as exc:
        error = f"PROVIDER_ERROR: {redact_text(exc)}"
        raw_path.write_text(error + "\n", encoding="utf-8")
        out_path.write_text("# generation failed before Python code was produced\n", encoding="utf-8")
        return _generation_result("failed", error, raw_path, out_path)

    raw_path.write_text(redact_text(response).rstrip() + "\n", encoding="utf-8")
    code = extract_python_module(response)
    if code is None:
        out_path.write_text("# no fenced Python code block found\n", encoding="utf-8")
        return _generation_result("no_python_code", "response did not contain a fenced python code block", raw_path, out_path)

    out_path.write_text(code.rstrip() + "\n", encoding="utf-8")
    if not has_build_model_contract(code):
        return _generation_result("generated_without_build_model", "response did not contain def build_model", raw_path, out_path)
    return _generation_result("generated", "", raw_path, out_path)


def _generation_result(status: str, error: str, raw_path: Path, out_path: Path) -> dict[str, Any]:
    return {
        "generation_status": status,
        "generation_error": redact_text(error),
        "raw_response": raw_path,
        "submission": out_path,
    }


def build_pilot_row(
    *,
    artifact_dir: Path,
    problem_id: str,
    model: str,
    generation: dict[str, Any],
    verification: VerificationResult,
    report_path: Path,
) -> dict[str, Any]:
    return {
        "problem_id": problem_id,
        "model": model,
        "generation_status": generation["generation_status"],
        "generation_error": generation["generation_error"],
        "submission": _relative(generation["submission"], artifact_dir),
        "raw_response": _relative(generation["raw_response"], artifact_dir),
        "report": _relative(report_path, artifact_dir),
        "verify_returncode": verification.returncode,
        "verify_stdout": verification.stdout,
        "verify_stderr": verification.stderr,
        "classification": verification.classification,
        "status": verification.status,
        "failure_check": verification.failure_check,
        "checks": verification.checks,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    classifications: dict[str, int] = {}
    generation_statuses: dict[str, int] = {}
    for row in rows:
        classifications[row["classification"]] = classifications.get(row["classification"], 0) + 1
        generation_statuses[row["generation_status"]] = generation_statuses.get(row["generation_status"], 0) + 1
    return {
        "total": len(rows),
        "classifications": classifications,
        "generation_statuses": generation_statuses,
    }


def write_markdown_report(path: Path, args: argparse.Namespace, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    matrix = [
        "| Problem | Generation | OR-CI Classification | Failure Check | Submission | Report |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        matrix.append(
            f"| {row['problem_id']} | `{row['generation_status']}` | `{row['classification']}` | "
            f"`{row['failure_check'] or '-'}` | `{row['submission']}` | `{row['report']}` |"
        )

    current_result = (
        "BLOCKED: provider generation failed for every requested problem. "
        "See `summary.json` and `raw/*.txt` for sanitized provider errors."
        if summary["generation_statuses"].get("failed") == summary["total"]
        else "COMPLETED: at least one generated or reused submission reached OR-CI verification."
    )

    path.write_text(
        f"""# OR-CI Integration Pilot Report

## Scope

- Producer: `or_llm_agent`
- Verifier: standalone OR-CI CLI through the editable `or-ci` dependency
- Model: `{args.model}`
- Problems: {", ".join(args.ids)}

## Summary

{current_result}

```json
{json.dumps(summary, ensure_ascii=False, indent=2)}
```

## Matrix

{chr(10).join(matrix)}

## Interpretation Notes

- `SUCCESS` means the generated submission passed the configured OR-CI invariants, not full model correctness.
- Semantic failures distinguish which verifier invariant failed first.
- Generation failures are reported separately from OR-CI classifications.
""",
        encoding="utf-8",
    )


def _check_gurobi() -> tuple[str, bool, str]:
    try:
        import gurobipy as gp

        env = gp.Env(empty=True)
        env.setParam("OutputFlag", 0)
        env.start()
        model = gp.Model(env=env)
        model.dispose()
        env.dispose()
        return "Gurobi model creation", True, "available"
    except Exception as exc:
        return "Gurobi model creation", False, redact_text(exc)


def _check_or_ci_import() -> tuple[str, bool, str]:
    try:
        import or_ci.cli  # noqa: F401

        return "or-ci import", True, "available"
    except Exception as exc:
        return "or-ci import", False, redact_text(exc)


def _check_or_ci_cli() -> tuple[str, bool, str]:
    try:
        command, mode = or_ci_command()
        result = subprocess.run([*command, "--help"], capture_output=True, text=True, check=False)
    except OSError as exc:
        return "or-ci CLI", False, redact_text(exc)
    detail = redact_text((result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else "")
    return "or-ci CLI", result.returncode == 0, f"{mode}: {detail or f'returncode={result.returncode}'}"


def _check_live_provider(model: str) -> tuple[str, bool, str]:
    try:
        response = query_llm(
            [
                {"role": "system", "content": "You are a provider health check. Reply briefly."},
                {"role": "user", "content": "Reply with exactly: ok"},
            ],
            model_name=model,
        )
    except Exception as exc:
        return "provider live request", False, redact_text(exc)
    return "provider live request", bool(response.strip()), "response received"


def _print_verification(verification: VerificationResult) -> None:
    if verification.stdout:
        print(verification.stdout, end="" if verification.stdout.endswith("\n") else "\n")
    if verification.stderr:
        print(verification.stderr, file=sys.stderr, end="" if verification.stderr.endswith("\n") else "\n")
    print(f"classification={verification.classification} status={verification.status}")


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
