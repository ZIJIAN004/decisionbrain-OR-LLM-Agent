from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
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
from or_llm_agent.codex_agent import CodexAgentOptions, CodexAgentPaths, build_agent_paths, neutral_work_dir, run_codex_agent
from or_llm_agent.json_blocks import extract_json_object
from or_llm_agent.or_ci import SpecValidationResult, VerificationResult, or_ci_command, run_or_ci_validate_spec, run_or_ci_verify
from or_llm_agent.prompts import OR_CI_SYSTEM_PROMPT, PROBLEM_SPEC_SYSTEM_PROMPT, build_or_ci_prompt, build_problem_spec_prompt
from or_llm_agent.provider import query_llm, required_env_names
from or_llm_agent.redaction import env_status, redact_text


class CLIError(Exception):
    pass


@dataclass(frozen=True)
class GenerationInputs:
    problem_id: str
    record: dict[str, Any]
    problem_path: Path
    problem: dict[str, Any]


@dataclass(frozen=True)
class ProblemSpecAgentResult:
    raw_text: str
    returncode: int
    timed_out: bool
    events_path: Path
    last_message_path: Path
    stderr: str


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
    if args.command == "spec":
        return spec_command(args)
    if args.command == "generate":
        return generate_command(args)
    if args.command == "verify":
        return verify_command(args)
    if args.command == "pilot":
        return pilot_command(args)
    if args.command == "solve":
        return solve_command(args)
    if args.command == "solve-batch":
        return solve_batch_command(args)
    if args.command == "review-fidelity":
        return review_fidelity_command(args)
    if args.command == "review-fidelity-batch":
        return review_fidelity_batch_command(args)
    parser.print_help()
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="or-llm-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("health", help="check local OR-LLM-Agent and OR-CI readiness")
    health.add_argument("--model", default="o3-mini")
    health.add_argument("--live", action="store_true", help="perform a minimal provider request")
    health.add_argument("--agent", action="store_true", help="check Codex agent-mode readiness")

    spec = subparsers.add_parser("spec", help="generate and validate an OR-CI problem metadata spec")
    spec.add_argument("--mode", choices=("agent",), default="agent")
    spec.add_argument("--statement-file", required=True, type=Path)
    spec.add_argument("--problem-id", required=True)
    spec.add_argument("--out", required=True, type=Path)
    spec.add_argument("--raw", required=True, type=Path)
    spec.add_argument("--status", type=Path, help="status JSON path; defaults to the spec output directory")
    spec.add_argument("--artifact-dir", type=Path, help="agent-mode artifact root; defaults to spec output directory")
    spec.add_argument("--or-ci-root", default=default_or_ci_root(), type=Path)
    _add_agent_options(spec)

    generate = subparsers.add_parser("generate", help="generate an OR-CI build_model submission")
    generate_source = generate.add_mutually_exclusive_group(required=True)
    generate_source.add_argument("--bwor-id")
    generate_source.add_argument("--problem", type=Path)
    generate.add_argument("--statement-file", type=Path, help="natural-language statement for explicit --problem runs")
    generate.add_argument("--model", default="o3-mini")
    generate.add_argument("--mode", choices=("api", "agent"), default="api")
    generate.add_argument("--out", required=True, type=Path)
    generate.add_argument("--raw", required=True, type=Path)
    generate.add_argument("--artifact-dir", type=Path, help="agent-mode artifact root; defaults to raw output parent")
    generate.add_argument("--dataset", default=default_bwor_dataset(), type=Path)
    generate.add_argument("--or-ci-root", default=default_or_ci_root(), type=Path)
    _add_agent_options(generate)

    verify = subparsers.add_parser("verify", help="verify a generated submission with standalone OR-CI")
    verify.add_argument("--problem", required=True, type=Path)
    verify.add_argument("--submission", required=True, type=Path)
    verify.add_argument("--out", required=True, type=Path)

    pilot = subparsers.add_parser("pilot", help="run generate plus OR-CI verify for a BWOR batch")
    pilot.add_argument("--ids", required=True, nargs="+")
    pilot.add_argument("--model", default="o3-mini")
    pilot.add_argument("--mode", choices=("api", "agent"), default="api")
    pilot.add_argument("--artifact-dir", required=True, type=Path)
    pilot.add_argument("--dataset", default=default_bwor_dataset(), type=Path)
    pilot.add_argument("--or-ci-root", default=default_or_ci_root(), type=Path)
    pilot.add_argument("--reuse-submissions", action="store_true")
    _add_agent_options(pilot)

    solve = subparsers.add_parser("solve", help="run statement-to-spec-to-model-to-OR-CI verification")
    solve.add_argument("--mode", choices=("agent",), default="agent")
    solve.add_argument("--statement-file", required=True, type=Path)
    solve.add_argument("--problem-id", required=True)
    solve.add_argument("--artifact-dir", required=True, type=Path)
    solve.add_argument("--model", default="o3-mini")
    solve.add_argument("--or-ci-root", default=default_or_ci_root(), type=Path)
    _add_agent_options(solve)

    solve_batch = subparsers.add_parser("solve-batch", help="run statement-to-spec-to-model solves for a batch")
    solve_batch.add_argument("--mode", choices=("agent",), default="agent")
    solve_batch.add_argument("--ids", required=True, nargs="+")
    solve_batch.add_argument("--artifact-dir", required=True, type=Path)
    solve_batch.add_argument("--statements-dir", type=Path, help="directory containing <problem-id>.txt statement files")
    solve_batch.add_argument("--dataset", default=default_bwor_dataset(), type=Path)
    solve_batch.add_argument("--model", default="o3-mini")
    solve_batch.add_argument("--or-ci-root", default=default_or_ci_root(), type=Path)
    _add_agent_options(solve_batch)

    review = subparsers.add_parser("review-fidelity", help="record a manual source-statement fidelity review")
    review.add_argument("--artifact-dir", required=True, type=Path, help="single solve artifact directory")
    review.add_argument("--status", required=True, choices=("accepted", "rejected"))
    review.add_argument("--reviewer", required=True)
    review.add_argument("--note", required=True)
    review.add_argument("--evidence", action="append", default=[])

    review_batch = subparsers.add_parser("review-fidelity-batch", help="record fidelity reviews for a solve-batch")
    review_batch.add_argument("--artifact-dir", required=True, type=Path, help="solve-batch artifact directory")
    review_batch.add_argument("--ids", nargs="+")
    review_batch.add_argument("--status", required=True, choices=("accepted", "rejected"))
    review_batch.add_argument("--reviewer", required=True)
    review_batch.add_argument("--note", required=True)
    review_batch.add_argument("--evidence", action="append", default=[])
    return parser


def _add_agent_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codex-model", help="agent mode: model for nested codex exec")
    parser.add_argument("--codex-sandbox", default="workspace-write", choices=("read-only", "workspace-write", "danger-full-access"))
    parser.add_argument("--codex-approval", default="never", choices=("untrusted", "on-failure", "on-request", "never"))
    parser.add_argument("--max-repair-attempts", default=3, type=int)
    parser.add_argument("--codex-timeout-seconds", default=900, type=int, help="agent mode: timeout for one nested codex exec run; <=0 disables")


def health_command(args: argparse.Namespace) -> int:
    load_dotenv()
    checks: list[tuple[str, bool, str]] = []

    if args.agent:
        checks.append(_check_codex_cli())
        checks.append(_check_codex_exec())
    else:
        env_names = required_env_names(args.model)
        if len(env_names) == 1:
            checks.append((env_names[0], bool(os.getenv(env_names[0])), env_status(*env_names)))
        else:
            checks.append(("Claude provider key", any(os.getenv(name) for name in env_names), env_status(*env_names)))
        checks.append(("OPENAI_API_BASE", True, env_status("OPENAI_API_BASE") if not args.model.lower().startswith("claude") else "not used"))

    checks.append(_check_gurobi())
    checks.append(_check_or_ci_import())
    checks.append(_check_or_ci_cli())
    if args.live and not args.agent:
        checks.append(_check_live_provider(args.model))

    for name, ok, detail in checks:
        label = "OK" if ok else "FAIL"
        print(f"{label} {name}: {redact_text(detail)}")

    return 0 if all(ok for _, ok, _ in checks) else 1


def spec_command(args: argparse.Namespace) -> int:
    statement = _read_statement(args.statement_file)
    status_path = args.status or _default_spec_status_path(args.out)
    artifact_dir = args.artifact_dir or args.out.parent
    result = generate_problem_spec(
        problem_id=args.problem_id,
        statement=statement,
        out_path=args.out,
        raw_path=args.raw,
        status_path=status_path,
        artifact_dir=artifact_dir,
        args=args,
    )
    print(
        f"{args.problem_id}: spec_generation={result['spec_generation_status']} "
        f"spec_validation={result['spec_validation_status']}"
    )
    if result.get("generation_error"):
        print(redact_text(str(result["generation_error"])), file=sys.stderr)
    if result.get("validation_stderr"):
        print(redact_text(str(result["validation_stderr"])), file=sys.stderr)
    return 0 if _spec_is_ready(result) else 1


def generate_command(args: argparse.Namespace) -> int:
    inputs = _generation_inputs_from_args(args)
    if args.mode == "agent":
        paths = build_agent_paths(
            problem_id=inputs.problem_id,
            artifact_root=(args.artifact_dir or args.raw.parent),
            submission_path=args.out,
            raw_path=args.raw,
        )
        result = generate_agent_submission(
            inputs=inputs,
            paths=paths,
            args=args,
        )
        verification = run_or_ci_verify(
            problem_path=inputs.problem_path,
            submission_path=paths.submission_path,
            report_path=paths.report_path,
            cwd=repo_root(),
        )
        print(f"{inputs.problem_id}: final_classification={verification.classification} status={verification.status}")
    else:
        result = generate_submission(
            inputs=inputs,
            model=args.model,
            out_path=args.out,
            raw_path=args.raw,
        )
    print(f"{inputs.problem_id}: generation={result['generation_status']}")
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
        inputs = _bwor_generation_inputs(problem_id, args.dataset, args.or_ci_root)

        if args.reuse_submissions and submission_path.exists():
            generation = {
                "generation_status": "reused",
                "generation_error": "",
                "raw_response": raw_path,
                "submission": submission_path,
                "generation_mode": args.mode,
                "agent_returncode": None,
            }
        elif args.mode == "agent":
            generation = generate_agent_submission(
                inputs=inputs,
                paths=build_agent_paths(
                    problem_id=problem_id,
                    artifact_root=artifact_dir,
                    submission_path=submission_path,
                    raw_path=raw_path,
                    report_path=report_path,
                ),
                args=args,
            )
        else:
            generation = generate_submission(
                inputs=inputs,
                model=args.model,
                out_path=submission_path,
                raw_path=raw_path,
            )

        verification = run_or_ci_verify(
            problem_path=inputs.problem_path,
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


def solve_command(args: argparse.Namespace) -> int:
    artifact_dir = args.artifact_dir.resolve()
    spec_dir = artifact_dir / "spec"
    submissions_dir = artifact_dir / "submissions"
    raw_dir = artifact_dir / "raw"
    reports_dir = artifact_dir / "reports"
    for directory in (spec_dir, submissions_dir, raw_dir, reports_dir, artifact_dir / "sessions"):
        directory.mkdir(parents=True, exist_ok=True)

    statement = _read_statement(args.statement_file)
    problem_path = spec_dir / "problem.json"
    spec_raw_path = raw_dir / "spec.txt"
    spec_status_path = spec_dir / "status.json"
    spec_fidelity_review_path = spec_dir / "fidelity-review.md"
    spec_fidelity_report_path = spec_dir / "fidelity-review.json"
    spec_result = generate_problem_spec(
        problem_id=args.problem_id,
        statement=statement,
        out_path=problem_path,
        raw_path=spec_raw_path,
        status_path=spec_status_path,
        artifact_dir=artifact_dir,
        args=args,
    )

    summary: dict[str, Any] = {
        "problem_id": args.problem_id,
        "statement_file": str(args.statement_file),
        "spec": _relative(problem_path, artifact_dir),
        "spec_raw": _relative(spec_raw_path, artifact_dir),
        "spec_status": _relative(spec_status_path, artifact_dir),
        "spec_generation_status": spec_result["spec_generation_status"],
        "spec_validation_status": spec_result["spec_validation_status"],
        "spec_generation_error": spec_result.get("generation_error", ""),
        "spec_validation_returncode": spec_result.get("validation_returncode"),
        "spec_attempt_count": spec_result.get("spec_attempt_count", 1),
        "spec_repair_status": spec_result.get("spec_repair_status", "not_needed"),
        "spec_fidelity_status": "not_reviewed",
        "spec_fidelity_review": _relative(spec_fidelity_review_path, artifact_dir),
        "spec_fidelity_report": _relative(spec_fidelity_report_path, artifact_dir),
        "model_generation_status": "skipped",
        "verification_status": "skipped",
        "classification": "skipped",
    }

    if not _spec_is_ready(spec_result):
        summary["reason"] = "spec validation failed; model generation skipped"
        _write_spec_fidelity_review(
            spec_fidelity_review_path,
            report_path=spec_fidelity_report_path,
            summary=summary,
            statement=statement,
            problem_path=problem_path,
        )
        _write_summary(artifact_dir / "summary.json", summary)
        print(f"{args.problem_id}: spec_validation={summary['spec_validation_status']} model_generation=skipped")
        return 1

    inputs = GenerationInputs(
        problem_id=args.problem_id,
        record={"id": args.problem_id, "en_question": statement},
        problem_path=problem_path,
        problem=load_problem(problem_path),
    )
    submission_path = submissions_dir / f"{args.problem_id}.py"
    model_raw_path = raw_dir / f"{args.problem_id}.txt"
    report_path = reports_dir / f"{args.problem_id}.json"
    generation = generate_agent_submission(
        inputs=inputs,
        paths=build_agent_paths(
            problem_id=args.problem_id,
            artifact_root=artifact_dir,
            submission_path=submission_path,
            raw_path=model_raw_path,
            report_path=report_path,
        ),
        args=args,
    )
    verification = run_or_ci_verify(
        problem_path=problem_path,
        submission_path=submission_path,
        report_path=report_path,
        cwd=repo_root(),
    )
    summary.update(
        {
            "submission": _relative(submission_path, artifact_dir),
            "model_raw": _relative(model_raw_path, artifact_dir),
            "report": _relative(report_path, artifact_dir),
            "model_generation_status": generation["generation_status"],
            "model_generation_error": generation["generation_error"],
            "verification_status": verification.status,
            "classification": verification.classification,
            "verification_note": "passed generated spec" if verification.status == "PASS" else "failed generated spec",
            "verify_returncode": verification.returncode,
            "verify_stdout": verification.stdout,
            "verify_stderr": verification.stderr,
        }
    )
    _write_spec_fidelity_review(
        spec_fidelity_review_path,
        report_path=spec_fidelity_report_path,
        summary=summary,
        statement=statement,
        problem_path=problem_path,
    )
    _write_summary(artifact_dir / "summary.json", summary)
    print(
        f"{args.problem_id}: spec_validation={summary['spec_validation_status']} "
        f"model_generation={summary['model_generation_status']} verification={summary['verification_status']} "
        f"classification={summary['classification']}"
    )
    return 0 if generation["generation_status"] == "generated" and verification.returncode == 0 else 1


def solve_batch_command(args: argparse.Namespace) -> int:
    artifact_dir = args.artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for problem_id in args.ids:
        statement_path = _batch_statement_file(args, artifact_dir, problem_id)
        case_dir = artifact_dir / problem_id
        solve_args = argparse.Namespace(**vars(args))
        solve_args.command = "solve"
        solve_args.problem_id = problem_id
        solve_args.statement_file = statement_path
        solve_args.artifact_dir = case_dir
        exit_code = solve_command(solve_args)
        row = _solve_batch_row(
            problem_id=problem_id,
            exit_code=exit_code,
            artifact_dir=artifact_dir,
            case_dir=case_dir,
            statement_path=statement_path,
        )
        rows.append(row)

    summary = summarize_solve_batch(rows)
    payload = {"summary": summary, "rows": rows}
    _write_summary(artifact_dir / "summary.json", payload)
    write_solve_batch_report(artifact_dir / "report.md", args, summary, rows)
    print(f"wrote {artifact_dir / 'report.md'}")
    return 0 if all(row["exit_code"] == 0 for row in rows) else 1


def review_fidelity_command(args: argparse.Namespace) -> int:
    artifact_dir = args.artifact_dir.resolve()
    review = _review_payload(args)
    summary = apply_fidelity_review(artifact_dir=artifact_dir, review=review)
    print(
        f"{summary['problem_id']}: spec_fidelity_status={summary['spec_fidelity_status']} "
        f"gate={summary['spec_fidelity_gate_status']}"
    )
    return 0


def review_fidelity_batch_command(args: argparse.Namespace) -> int:
    artifact_dir = args.artifact_dir.resolve()
    ids = args.ids or _batch_ids_from_summary(artifact_dir)
    review = _review_payload(args)
    for problem_id in ids:
        apply_fidelity_review(artifact_dir=artifact_dir / problem_id, review=review)

    rows = [
        _solve_batch_row(
            problem_id=problem_id,
            exit_code=_case_exit_code(artifact_dir / problem_id),
            artifact_dir=artifact_dir,
            case_dir=artifact_dir / problem_id,
            statement_path=artifact_dir / "statements" / f"{problem_id}.txt",
        )
        for problem_id in ids
    ]
    summary = summarize_solve_batch(rows)
    payload = {"summary": summary, "rows": rows}
    _write_summary(artifact_dir / "summary.json", payload)
    report_args = argparse.Namespace(ids=ids, mode="agent")
    write_solve_batch_report(artifact_dir / "report.md", report_args, summary, rows)
    print(f"reviewed {len(ids)} case(s); wrote {artifact_dir / 'report.md'}")
    return 0


def generate_problem_spec(
    *,
    problem_id: str,
    statement: str,
    out_path: Path,
    raw_path: Path,
    status_path: Path,
    artifact_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.parent.mkdir(parents=True, exist_ok=True)

    max_attempts = 1 + max(args.max_repair_attempts, 0)
    attempts: list[dict[str, Any]] = []
    previous_problem: dict[str, Any] | None = None
    previous_response = ""
    repair_error = ""

    for attempt in range(1, max_attempts + 1):
        agent_result = _run_problem_spec_agent(
            problem_id=problem_id,
            statement=statement,
            artifact_dir=artifact_dir.resolve(),
            args=args,
            attempt=attempt,
            previous_problem=previous_problem,
            previous_response=previous_response,
            repair_error=repair_error,
        )
        raw_text = redact_text(agent_result.raw_text).rstrip() + "\n"
        attempt_raw_path = _spec_attempt_raw_path(raw_path, attempt)
        attempt_raw_path.write_text(raw_text, encoding="utf-8")
        raw_path.write_text(raw_text, encoding="utf-8")

        attempt_payload: dict[str, Any] = {
            "attempt": attempt,
            "mode": args.mode,
            "spec_generation_status": "generated",
            "spec_validation_status": "skipped",
            "generation_error": "",
            "raw_response": str(attempt_raw_path),
            "agent_returncode": agent_result.returncode,
            "agent_timed_out": agent_result.timed_out,
            "codex_events": str(agent_result.events_path),
            "last_message": str(agent_result.last_message_path),
            "agent_stderr": redact_text(agent_result.stderr),
            "repair_input_error": repair_error if attempt > 1 else "",
        }

        problem = extract_json_object(agent_result.raw_text)
        if problem is None:
            out_path.write_text("{}\n", encoding="utf-8")
            generation_error = "response did not contain one JSON object"
            attempt_payload.update(
                {
                    "spec_generation_status": "no_json",
                    "generation_error": generation_error,
                }
            )
            attempts.append(attempt_payload)
            previous_problem = None
            previous_response = raw_text
            repair_error = generation_error
            continue

        out_path.write_text(json.dumps(problem, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        validation = run_or_ci_validate_spec(problem_path=out_path, cwd=repo_root())
        attempt_payload.update(_spec_validation_payload(validation))
        attempts.append(attempt_payload)
        if validation.status == "passed":
            break

        previous_problem = problem
        previous_response = raw_text
        repair_error = _format_spec_repair_error(validation)

    final_attempt = attempts[-1]
    payload: dict[str, Any] = {
        "problem_id": problem_id,
        "mode": args.mode,
        "spec_generation_status": final_attempt["spec_generation_status"],
        "spec_validation_status": final_attempt["spec_validation_status"],
        "generation_error": final_attempt["generation_error"],
        "raw_response": str(raw_path),
        "problem": str(out_path),
        "status": str(status_path),
        "agent_returncode": final_attempt["agent_returncode"],
        "agent_timed_out": final_attempt["agent_timed_out"],
        "codex_events": final_attempt["codex_events"],
        "last_message": final_attempt["last_message"],
        "agent_stderr": final_attempt["agent_stderr"],
        "spec_attempt_count": len(attempts),
        "spec_repair_status": _spec_repair_status(attempts),
        "spec_attempts": attempts,
    }
    for key in ("validation_returncode", "validation_stdout", "validation_stderr"):
        if key in final_attempt:
            payload[key] = final_attempt[key]
    _write_summary(status_path, payload)
    return payload


def generate_submission(
    *,
    inputs: GenerationInputs,
    model: str,
    out_path: Path,
    raw_path: Path,
) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    messages = [
        {"role": "system", "content": OR_CI_SYSTEM_PROMPT},
        {"role": "user", "content": build_or_ci_prompt(inputs.problem_id, inputs.record, inputs.problem)},
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


def generate_agent_submission(
    *,
    inputs: GenerationInputs,
    paths: CodexAgentPaths,
    args: argparse.Namespace,
) -> dict[str, Any]:
    result = run_codex_agent(
        problem_id=inputs.problem_id,
        record=inputs.record,
        problem=inputs.problem,
        problem_path=inputs.problem_path.resolve(),
        paths=paths,
        options=CodexAgentOptions(
            codex_model=args.codex_model,
            codex_sandbox=args.codex_sandbox,
            codex_approval=args.codex_approval,
            max_repair_attempts=args.max_repair_attempts,
            timeout_seconds=args.codex_timeout_seconds,
        ),
        verify_command=or_ci_command()[0],
    )

    if not paths.submission_path.exists():
        error = f"codex exec did not write submission; returncode={result.returncode}"
        paths.submission_path.write_text("# agent mode did not produce a submission\n", encoding="utf-8")
        status = "agent_failed"
    else:
        code = paths.submission_path.read_text(encoding="utf-8")
        if has_build_model_contract(code):
            status = "generated"
            error = "" if result.returncode == 0 else f"codex exec returned nonzero status: {result.returncode}"
        else:
            status = "generated_without_build_model"
            error = "agent submission did not contain def build_model"

    payload = _generation_result(status, error, paths.raw_path, paths.submission_path)
    payload.update(
        {
            "generation_mode": "agent",
            "agent_returncode": result.returncode,
            "agent_timed_out": result.timed_out,
            "agent_status": paths.status_path,
            "last_message": paths.last_message_path,
            "codex_events": paths.events_path,
        }
    )
    return payload


def _generation_result(status: str, error: str, raw_path: Path, out_path: Path) -> dict[str, Any]:
    return {
        "generation_status": status,
        "generation_error": redact_text(error),
        "raw_response": raw_path,
        "submission": out_path,
        "generation_mode": "api",
        "agent_returncode": None,
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
        "generation_mode": generation.get("generation_mode", "api"),
        "generation_status": generation["generation_status"],
        "generation_error": generation["generation_error"],
        "submission": _relative(generation["submission"], artifact_dir),
        "raw_response": _relative(generation["raw_response"], artifact_dir),
        "report": _relative(report_path, artifact_dir),
        "agent_returncode": generation.get("agent_returncode"),
        "agent_timed_out": generation.get("agent_timed_out"),
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
    generation_modes: dict[str, int] = {}
    for row in rows:
        classifications[row["classification"]] = classifications.get(row["classification"], 0) + 1
        generation_statuses[row["generation_status"]] = generation_statuses.get(row["generation_status"], 0) + 1
        generation_modes[row.get("generation_mode", "api")] = generation_modes.get(row.get("generation_mode", "api"), 0) + 1
    return {
        "total": len(rows),
        "classifications": classifications,
        "generation_statuses": generation_statuses,
        "generation_modes": generation_modes,
    }


def summarize_solve_batch(rows: list[dict[str, Any]]) -> dict[str, Any]:
    classifications: dict[str, int] = {}
    spec_statuses: dict[str, int] = {}
    model_statuses: dict[str, int] = {}
    fidelity_statuses: dict[str, int] = {}
    fidelity_gate_statuses: dict[str, int] = {}
    exit_codes: dict[str, int] = {}
    for row in rows:
        classifications[row["classification"]] = classifications.get(row["classification"], 0) + 1
        spec_statuses[row["spec_validation_status"]] = spec_statuses.get(row["spec_validation_status"], 0) + 1
        model_statuses[row["model_generation_status"]] = model_statuses.get(row["model_generation_status"], 0) + 1
        fidelity_status = row.get("spec_fidelity_status", "unknown")
        fidelity_statuses[fidelity_status] = fidelity_statuses.get(fidelity_status, 0) + 1
        gate = row.get("spec_fidelity_gate_status", "unknown")
        fidelity_gate_statuses[gate] = fidelity_gate_statuses.get(gate, 0) + 1
        exit_key = str(row["exit_code"])
        exit_codes[exit_key] = exit_codes.get(exit_key, 0) + 1
    return {
        "total": len(rows),
        "succeeded": sum(1 for row in rows if row["exit_code"] == 0),
        "failed": sum(1 for row in rows if row["exit_code"] != 0),
        "classifications": classifications,
        "spec_validation_statuses": spec_statuses,
        "model_generation_statuses": model_statuses,
        "spec_fidelity_statuses": fidelity_statuses,
        "spec_fidelity_gate_statuses": fidelity_gate_statuses,
        "exit_codes": exit_codes,
    }


def write_markdown_report(path: Path, args: argparse.Namespace, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    matrix = [
        "| Problem | Mode | Generation | Agent RC | OR-CI Classification | Failure Check | Submission | Report |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    for row in rows:
        matrix.append(
            f"| {row['problem_id']} | `{row.get('generation_mode', 'api')}` | `{row['generation_status']}` | "
            f"`{row.get('agent_returncode') if row.get('agent_returncode') is not None else '-'}` | `{row['classification']}` | "
            f"`{row['failure_check'] or '-'}` | `{row['submission']}` | `{row['report']}` |"
        )

    any_generated = any(row["generation_status"] in {"generated", "reused"} for row in rows)
    if any_generated:
        current_result = "COMPLETED: at least one generated or reused submission reached OR-CI verification."
    elif summary["generation_statuses"].get("failed") == summary["total"]:
        current_result = (
            "BLOCKED: provider generation failed for every requested problem. "
            "See `summary.json` and `raw/*.txt` for sanitized provider errors."
        )
    else:
        current_result = (
            "BLOCKED: generation did not produce a valid submission for any requested problem. "
            "See `summary.json` and the raw or agent status artifacts for details."
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


def write_solve_batch_report(path: Path, args: argparse.Namespace, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    matrix = [
        "| Problem | Exit | Spec Validation | Attempts | Repair | Model Generation | Verification | Classification | Fidelity | Gate | Artifact |",
        "|---|---:|---|---:|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        matrix.append(
            f"| {row['problem_id']} | `{row['exit_code']}` | `{row['spec_validation_status']}` | "
            f"`{row['spec_attempt_count']}` | `{row['spec_repair_status']}` | "
            f"`{row['model_generation_status']}` | `{row['verification_status']}` | "
            f"`{row['classification']}` | `{row.get('spec_fidelity_status', 'unknown')}` | "
            f"`{row.get('spec_fidelity_gate_status', 'unknown')}` | "
            f"`{row['artifact_dir']}` |"
        )

    path.write_text(
        f"""# Statement-Only Solve Batch Report

## Scope

- Producer: `or_llm_agent solve-batch --mode {args.mode}`
- Problems: {", ".join(args.ids)}
- Source: `--statements-dir` if supplied, otherwise `--dataset`

## Summary

```json
{json.dumps(summary, ensure_ascii=False, indent=2)}
```

## Matrix

{chr(10).join(matrix)}

## Interpretation Notes

- `classification=SUCCESS` means the generated submission passed OR-CI checks against the generated spec.
- `spec_fidelity_gate_status=manual_review_required` means source-statement fidelity has not been certified.
- `spec_fidelity_gate_status=accepted` means a reviewer accepted source-statement fidelity for this run artifact.
- `spec_fidelity_gate_status=rejected` means a reviewer rejected source-statement fidelity for this run artifact.
- Inspect each case's `spec/fidelity-review.md` and `spec/fidelity-review.json` before treating generated specs as benchmark metadata.
""",
        encoding="utf-8",
    )


def _batch_statement_file(args: argparse.Namespace, artifact_dir: Path, problem_id: str) -> Path:
    if args.statements_dir:
        candidate = args.statements_dir / f"{problem_id}.txt"
        if candidate.is_file():
            return candidate

    record = load_bwor_record(args.dataset, problem_id)
    statement = record.get("en_question") or record.get("cn_question")
    if not isinstance(statement, str) or not statement.strip():
        raise CLIError(f"no statement text found for {problem_id} in {args.dataset}")
    statement_path = artifact_dir / "statements" / f"{problem_id}.txt"
    statement_path.parent.mkdir(parents=True, exist_ok=True)
    statement_path.write_text(statement.strip() + "\n", encoding="utf-8")
    return statement_path


def _solve_batch_row(
    *,
    problem_id: str,
    exit_code: int,
    artifact_dir: Path,
    case_dir: Path,
    statement_path: Path,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "problem_id": problem_id,
        "exit_code": exit_code,
        "artifact_dir": _relative(case_dir, artifact_dir),
        "statement_file": _relative(statement_path, artifact_dir),
        "spec_validation_status": "missing_summary",
        "spec_attempt_count": 0,
        "spec_repair_status": "missing_summary",
        "model_generation_status": "missing_summary",
        "verification_status": "missing_summary",
        "classification": "missing_summary",
    }
    summary_path = case_dir / "summary.json"
    if not summary_path.is_file():
        return row
    case_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    for key in (
        "spec_validation_status",
        "spec_attempt_count",
        "spec_repair_status",
        "spec_fidelity_status",
        "spec_fidelity_gate_status",
        "spec_fidelity_reviewed_at",
        "spec_fidelity_reviewed_by",
        "model_generation_status",
        "verification_status",
        "classification",
        "spec",
        "spec_fidelity_review",
        "spec_fidelity_report",
        "submission",
        "report",
    ):
        if key in case_summary:
            row[key] = case_summary[key]
    return row


def apply_fidelity_review(*, artifact_dir: Path, review: dict[str, Any]) -> dict[str, Any]:
    summary_path = artifact_dir / "summary.json"
    if not summary_path.is_file():
        raise CLIError(f"solve summary does not exist: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise CLIError(f"solve summary must be a JSON object: {summary_path}")
    if review["status"] == "accepted":
        _ensure_acceptance_is_allowed(summary, artifact_dir)

    review_path = _artifact_path(artifact_dir, summary.get("spec_fidelity_review"), "spec/fidelity-review.md")
    report_path = _artifact_path(artifact_dir, summary.get("spec_fidelity_report"), "spec/fidelity-review.json")
    report = _read_json_object(report_path)
    report.update(
        {
            "problem_id": summary.get("problem_id"),
            "fidelity_status": review["status"],
            "gate_status": review["status"],
            "review": review,
        }
    )
    _update_source_fidelity_check(report, review)

    summary.update(
        {
            "spec_fidelity_status": review["status"],
            "spec_fidelity_gate_status": review["status"],
            "spec_fidelity_reviewed_at": review["reviewed_at"],
            "spec_fidelity_reviewed_by": review["reviewer"],
            "spec_fidelity_review_note": review["note"],
            "spec_fidelity_evidence": review["evidence"],
        }
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_reviewed_fidelity_markdown(review_path, summary=summary, report=report, artifact_dir=artifact_dir)
    _write_summary(summary_path, summary)
    return summary


def _review_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "mode": "manual",
        "status": args.status,
        "reviewer": args.reviewer,
        "note": args.note,
        "evidence": list(args.evidence or []),
        "reviewed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _ensure_acceptance_is_allowed(summary: dict[str, Any], artifact_dir: Path) -> None:
    if summary.get("spec_validation_status") != "passed":
        raise CLIError("cannot accept fidelity review when spec validation did not pass")
    if summary.get("verification_status") != "PASS":
        raise CLIError("cannot accept fidelity review when OR-CI verification did not pass")
    problem_path = _artifact_path(artifact_dir, summary.get("spec"), "spec/problem.json")
    if not problem_path.is_file():
        raise CLIError(f"cannot accept fidelity review without generated spec: {problem_path}")


def _update_source_fidelity_check(report: dict[str, Any], review: dict[str, Any]) -> None:
    checks = report.get("automatic_checks")
    if not isinstance(checks, list):
        checks = []
    status = "PASS" if review["status"] == "accepted" else "FAIL"
    detail = f"manual review {review['status']}: {review['note']}"
    for check in checks:
        if isinstance(check, dict) and check.get("name") == "source_statement_fidelity":
            check["status"] = status
            check["detail"] = detail
            break
    else:
        checks.append({"name": "source_statement_fidelity", "status": status, "detail": detail})
    report["automatic_checks"] = checks


def _write_reviewed_fidelity_markdown(
    path: Path,
    *,
    summary: dict[str, Any],
    report: dict[str, Any],
    artifact_dir: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    statement = _read_optional_text(_artifact_path(artifact_dir, summary.get("statement_file"), "statement.txt"))
    if not statement:
        statement = str(report.get("statement_excerpt", "")).strip()
    statement_excerpt = statement.replace("\r\n", "\n").strip()
    if len(statement_excerpt) > 800:
        statement_excerpt = statement_excerpt[:797].rstrip() + "..."
    check_lines = [
        f"- `{check.get('status', 'UNKNOWN')}` {check.get('name', 'unknown')}: {check.get('detail', '')}"
        for check in report.get("automatic_checks", [])
        if isinstance(check, dict)
    ]
    risk_lines = [
        f"- `{flag.get('severity', 'unknown')}` {flag.get('code', 'unknown')}: {flag.get('message', '')}"
        for flag in report.get("risk_flags", [])
        if isinstance(flag, dict)
    ] or ["- None detected by automatic checks."]
    review = report.get("review") if isinstance(report.get("review"), dict) else {}
    evidence_lines = [f"- {item}" for item in review.get("evidence", [])] or ["- None recorded."]

    path.write_text(
        f"""# ProblemSpec Fidelity Review

## Run

- Problem: `{summary.get('problem_id', 'unknown')}`
- Statement file: `{summary.get('statement_file', '')}`
- Generated spec: `{summary.get('spec', '')}`
- Spec raw output: `{summary.get('spec_raw', '')}`
- Spec generation: `{summary.get('spec_generation_status', '')}`
- Spec validation: `{summary.get('spec_validation_status', '')}`
- Model generation: `{summary.get('model_generation_status', '')}`
- Verification: `{summary.get('verification_status', '')}`
- Classification: `{summary.get('classification', '')}`
- Fidelity status: `{summary.get('spec_fidelity_status', '')}`
- Fidelity gate: `{summary.get('spec_fidelity_gate_status', '')}`
- Structured report: `{summary.get('spec_fidelity_report', '')}`

## Review Decision

- Status: `{review.get('status', 'unknown')}`
- Reviewer: `{review.get('reviewer', '')}`
- Reviewed at: `{review.get('reviewed_at', '')}`
- Note: {review.get('note', '')}

## Evidence

{chr(10).join(evidence_lines)}

## Statement Excerpt

```text
{statement_excerpt}
```

## Automatic Checks

{chr(10).join(check_lines)}

## Risk Flags

{chr(10).join(risk_lines)}
""",
        encoding="utf-8",
    )


def _artifact_path(artifact_dir: Path, value: Any, fallback: str) -> Path:
    if isinstance(value, str) and value:
        path = Path(value)
        return path if path.is_absolute() else artifact_dir / path
    return artifact_dir / fallback


def _read_optional_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _batch_ids_from_summary(artifact_dir: Path) -> list[str]:
    summary_path = artifact_dir / "summary.json"
    if not summary_path.is_file():
        raise CLIError(f"batch summary does not exist: {summary_path}")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise CLIError(f"batch summary contains no rows: {summary_path}")
    ids = [str(row.get("problem_id")) for row in rows if isinstance(row, dict) and row.get("problem_id")]
    if not ids:
        raise CLIError(f"batch summary contains no problem ids: {summary_path}")
    return ids


def _case_exit_code(case_dir: Path) -> int:
    summary = _read_json_object(case_dir / "summary.json")
    if summary.get("model_generation_status") == "generated" and summary.get("verification_status") == "PASS":
        return 0
    return 1


def _generation_inputs_from_args(args: argparse.Namespace) -> GenerationInputs:
    if args.problem:
        return _problem_generation_inputs(args.problem, args.statement_file)
    return _bwor_generation_inputs(args.bwor_id, args.dataset, args.or_ci_root)


def _bwor_generation_inputs(problem_id: str, dataset_path: Path, or_ci_root: Path) -> GenerationInputs:
    problem_path = default_problem_path(problem_id, or_ci_root)
    if not problem_path.is_file():
        raise CLIError(f"problem file does not exist: {problem_path}")
    return GenerationInputs(
        problem_id=problem_id,
        record=load_bwor_record(dataset_path, problem_id),
        problem_path=problem_path,
        problem=load_problem(problem_path),
    )


def _problem_generation_inputs(problem_path: Path, statement_file: Path | None) -> GenerationInputs:
    if not problem_path.is_file():
        raise CLIError(f"problem file does not exist: {problem_path}")
    problem = load_problem(problem_path)
    problem_id = str(problem.get("id") or problem_path.stem)
    statement = _read_statement(statement_file) if statement_file else ""
    return GenerationInputs(
        problem_id=problem_id,
        record={"id": problem_id, "en_question": statement},
        problem_path=problem_path,
        problem=problem,
    )


def _read_statement(path: Path) -> str:
    if not path.is_file():
        raise CLIError(f"statement file does not exist: {path}")
    return path.read_text(encoding="utf-8").strip()


def _default_spec_status_path(out_path: Path) -> Path:
    return out_path.parent / "status.json"


def _run_problem_spec_agent(
    *,
    problem_id: str,
    statement: str,
    artifact_dir: Path,
    args: argparse.Namespace,
    attempt: int = 1,
    previous_problem: dict[str, Any] | None = None,
    previous_response: str = "",
    repair_error: str = "",
) -> ProblemSpecAgentResult:
    session_name = f"{problem_id}-spec" if attempt == 1 else f"{problem_id}-spec-repair-{attempt - 1}"
    session_dir = artifact_dir / "sessions" / session_name
    events_path = session_dir / "codex-events.jsonl"
    last_message_path = session_dir / "last-message.md"
    work_dir = neutral_work_dir(artifact_dir, session_name)
    for path in (artifact_dir, session_dir, work_dir):
        path.mkdir(parents=True, exist_ok=True)

    command = [
        "codex",
        "-a",
        args.codex_approval,
        "exec",
        "--json",
        "-C",
        str(work_dir),
        "--add-dir",
        str(artifact_dir),
        "--skip-git-repo-check",
        "-s",
        args.codex_sandbox,
        "-o",
        str(last_message_path),
    ]
    if args.codex_model:
        command.extend(["-m", args.codex_model])
    command.append("-")

    timed_out = False
    try:
        result = subprocess.run(
            command,
            input=_build_problem_spec_agent_prompt(
                problem_id,
                statement,
                previous_problem=previous_problem,
                previous_response=previous_response,
                repair_error=repair_error,
            ),
            capture_output=True,
            text=True,
            check=False,
            timeout=args.codex_timeout_seconds if args.codex_timeout_seconds and args.codex_timeout_seconds > 0 else None,
        )
        returncode = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        stdout = _coerce_timeout_stream(exc.stdout)
        stderr = _coerce_timeout_stream(exc.stderr)
        timeout_message = f"codex exec timed out after {args.codex_timeout_seconds} seconds"
        stderr = f"{stderr.rstrip()}\n{timeout_message}\n" if stderr else timeout_message + "\n"

    events_path.write_text(redact_text(stdout), encoding="utf-8")
    if last_message_path.exists():
        raw_text = last_message_path.read_text(encoding="utf-8")
    else:
        raw_text = stdout
        last_message_path.write_text(raw_text, encoding="utf-8")
    return ProblemSpecAgentResult(
        raw_text=raw_text,
        returncode=returncode,
        timed_out=timed_out,
        events_path=events_path,
        last_message_path=last_message_path,
        stderr=redact_text(stderr),
    )


def _build_problem_spec_agent_prompt(
    problem_id: str,
    statement: str,
    *,
    previous_problem: dict[str, Any] | None = None,
    previous_response: str = "",
    repair_error: str = "",
) -> str:
    repair_context = _build_problem_spec_repair_context(
        previous_problem=previous_problem,
        previous_response=previous_response,
        repair_error=repair_error,
    )
    return f"""{PROBLEM_SPEC_SYSTEM_PROMPT}

You are running as a nested Codex agent for OR-LLM-Agent `spec --mode agent`.
Do not edit repository source files. Return the generated problem metadata as
your final answer.

{build_problem_spec_prompt(problem_id, statement)}
{repair_context}

Start now. Complete the workflow without asking for confirmation.
"""


def _build_problem_spec_repair_context(
    *,
    previous_problem: dict[str, Any] | None,
    previous_response: str,
    repair_error: str,
) -> str:
    if not repair_error:
        return ""

    previous = ""
    if previous_problem is not None:
        previous = json.dumps(previous_problem, ensure_ascii=False, indent=2)
    elif previous_response:
        previous = previous_response.strip()
    if len(previous) > 4000:
        previous = previous[:3997].rstrip() + "..."

    return f"""

Previous generated metadata failed OR-CI validation. Repair it now.

Validation or extraction error:
```text
{repair_error.strip()}
```

Previous generated content:
```json
{previous}
```

Return a complete corrected metadata JSON object. Do not return a patch.
"""


def _spec_validation_payload(validation: SpecValidationResult) -> dict[str, Any]:
    return {
        "spec_validation_status": validation.status,
        "validation_returncode": validation.returncode,
        "validation_stdout": validation.stdout,
        "validation_stderr": validation.stderr,
    }


def _spec_attempt_raw_path(raw_path: Path, attempt: int) -> Path:
    return raw_path.with_name(f"{raw_path.stem}-attempt-{attempt}{raw_path.suffix}")


def _format_spec_repair_error(validation: SpecValidationResult) -> str:
    detail = validation.stderr.strip() or validation.stdout.strip()
    if detail:
        return detail
    return f"or-ci validate-spec failed with returncode={validation.returncode}"


def _spec_repair_status(attempts: list[dict[str, Any]]) -> str:
    if not attempts:
        return "failed"
    ready = (
        attempts[-1].get("spec_generation_status") == "generated"
        and attempts[-1].get("spec_validation_status") == "passed"
    )
    if not ready:
        return "failed"
    return "not_needed" if len(attempts) == 1 else "repaired"


def _spec_is_ready(result: dict[str, Any]) -> bool:
    return result.get("spec_generation_status") == "generated" and result.get("spec_validation_status") == "passed"


def _write_spec_fidelity_review(
    path: Path,
    *,
    report_path: Path,
    summary: dict[str, Any],
    statement: str,
    problem_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fidelity = _build_spec_fidelity_payload(summary=summary, statement=statement, problem_path=problem_path)
    summary["spec_fidelity_gate_status"] = fidelity["gate_status"]
    summary["spec_fidelity_risk_flags"] = [flag["code"] for flag in fidelity["risk_flags"]]
    report_path.write_text(json.dumps(fidelity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    statement_excerpt = statement.replace("\r\n", "\n").strip()
    if len(statement_excerpt) > 800:
        statement_excerpt = statement_excerpt[:797].rstrip() + "..."
    check_lines = [
        f"- `{check['status']}` {check['name']}: {check['detail']}"
        for check in fidelity["automatic_checks"]
    ]
    risk_lines = [
        f"- `{flag['severity']}` {flag['code']}: {flag['message']}"
        for flag in fidelity["risk_flags"]
    ] or ["- None detected by automatic checks."]

    path.write_text(
        f"""# ProblemSpec Fidelity Review

## Run

- Problem: `{summary['problem_id']}`
- Statement file: `{summary['statement_file']}`
- Generated spec: `{summary['spec']}`
- Spec raw output: `{summary['spec_raw']}`
- Spec generation: `{summary['spec_generation_status']}`
- Spec validation: `{summary['spec_validation_status']}`
- Model generation: `{summary['model_generation_status']}`
- Verification: `{summary['verification_status']}`
- Classification: `{summary['classification']}`
- Fidelity status: `{summary['spec_fidelity_status']}`
- Fidelity gate: `{summary['spec_fidelity_gate_status']}`
- Structured report: `{summary['spec_fidelity_report']}`

## Statement Excerpt

```text
{statement_excerpt}
```

## Automatic Checks

{chr(10).join(check_lines)}

## Risk Flags

{chr(10).join(risk_lines)}

## Manual Checklist

- [ ] Sets and indices in `instance` match the statement.
- [ ] Parameters and numeric values in `instance` match the statement.
- [ ] Objective direction and coefficients match the statement.
- [ ] Constraint families and bounds match the statement.
- [ ] Metamorphic checks touch objective and constraint data paths, where available.
- [ ] OR-CI result is interpreted as verification against the generated spec, not proof of original-statement correctness.

## Reviewer Note

TODO
""",
        encoding="utf-8",
    )


def _build_spec_fidelity_payload(*, summary: dict[str, Any], statement: str, problem_path: Path) -> dict[str, Any]:
    problem = _read_json_object(problem_path)
    gate_status = "manual_review_required" if summary.get("spec_validation_status") == "passed" else "blocked_spec_invalid"
    automatic_checks = [
        {
            "name": "or_ci_spec_validation",
            "status": "PASS" if summary.get("spec_validation_status") == "passed" else "FAIL",
            "detail": f"spec_validation_status={summary.get('spec_validation_status')}",
        },
        {
            "name": "model_verified_against_generated_spec",
            "status": _fidelity_check_status(summary.get("verification_status")),
            "detail": f"verification_status={summary.get('verification_status')}",
        },
        {
            "name": "source_statement_fidelity",
            "status": "PENDING",
            "detail": "manual review is required before treating generated spec as ground truth",
        },
    ]
    return {
        "problem_id": summary["problem_id"],
        "gate_status": gate_status,
        "fidelity_status": summary["spec_fidelity_status"],
        "statement_file": summary["statement_file"],
        "statement_excerpt": statement[:800],
        "spec": summary["spec"],
        "spec_validation_status": summary["spec_validation_status"],
        "model_generation_status": summary["model_generation_status"],
        "verification_status": summary["verification_status"],
        "classification": summary["classification"],
        "automatic_checks": automatic_checks,
        "risk_flags": _spec_fidelity_risk_flags(problem),
        "manual_checklist": [
            "sets and indices match the statement",
            "numeric parameters match the statement",
            "objective direction and coefficients match the statement",
            "constraint families and bounds match the statement",
            "metamorphic paths touch objective and constraint data paths where available",
            "OR-CI result is interpreted only against the generated spec",
        ],
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _fidelity_check_status(verification_status: Any) -> str:
    if verification_status == "PASS":
        return "PASS"
    if verification_status == "skipped":
        return "SKIP"
    return "FAIL"


def _spec_fidelity_risk_flags(problem: dict[str, Any]) -> list[dict[str, str]]:
    instance = problem.get("instance") if isinstance(problem.get("instance"), dict) else {}
    metamorphic = problem.get("metamorphic") if isinstance(problem.get("metamorphic"), dict) else {}
    cost_scaling = metamorphic.get("cost_scaling") if isinstance(metamorphic.get("cost_scaling"), dict) else {}
    coefficient_paths = cost_scaling.get("coefficient_paths") if isinstance(cost_scaling.get("coefficient_paths"), list) else []
    searchable = " ".join([*(_flatten_keys(instance)), *(str(path) for path in coefficient_paths)]).lower()
    flags: list[dict[str, str]] = []
    has_profit = "profit" in searchable or "revenue" in searchable
    has_cost = "cost" in searchable or "price" in searchable
    has_derived_net = "net" in searchable or "benefit" in searchable
    if has_derived_net and not (has_profit and has_cost):
        flags.append(
            {
                "code": "derived_objective_without_primitives",
                "severity": "warning",
                "message": "objective data appears derived; preserve primitive profit/revenue and cost fields when available",
            }
        )
    if "constraint_relaxation" not in metamorphic:
        flags.append(
            {
                "code": "no_constraint_relaxation",
                "severity": "warning",
                "message": "metadata has no configured constraint relaxation check",
            }
        )
    return flags


def _flatten_keys(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        keys: list[str] = []
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            keys.append(child)
            keys.extend(_flatten_keys(item, child))
        return keys
    if isinstance(value, list):
        keys = []
        for index, item in enumerate(value):
            keys.extend(_flatten_keys(item, f"{prefix}[{index}]"))
        return keys
    return []


def _write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _coerce_timeout_stream(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


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


def _check_codex_cli() -> tuple[str, bool, str]:
    return _check_command("Codex CLI", ["codex", "--help"])


def _check_codex_exec() -> tuple[str, bool, str]:
    return _check_command("Codex exec", ["codex", "exec", "--help"])


def _check_command(name: str, command: list[str]) -> tuple[str, bool, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        return name, False, redact_text(exc)
    detail = (result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else ""
    return name, result.returncode == 0, redact_text(detail or f"returncode={result.returncode}")


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
