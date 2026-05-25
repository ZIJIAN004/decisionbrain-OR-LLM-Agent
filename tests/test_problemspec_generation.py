from __future__ import annotations

import json
import threading
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from or_llm_agent.cli import CapabilityAgentResult, FidelityReviewAgentResult, ProblemSpecAgentResult, main
from or_llm_agent.or_ci import VerificationResult
from or_llm_agent.prompts import build_problem_metadata_template, build_problem_spec_prompt, build_statement_capability_prompt


class ProblemSpecGenerationTests(unittest.TestCase):
    def test_classify_statement_writes_capability_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            capability_path = root / "spec" / "capability.json"
            raw_path = root / "raw" / "capability.txt"
            statement_path.write_text("Maximize profit subject to capacity.", encoding="utf-8")
            payload = _supported_capability("linear production planning")

            with patch("or_llm_agent.cli._run_capability_agent", return_value=_capability_agent_result(root, payload)):
                exit_code = main(
                    [
                        "classify-statement",
                        "--mode",
                        "agent",
                        "--statement-file",
                        str(statement_path),
                        "--problem-id",
                        "CASE-001",
                        "--out",
                        str(capability_path),
                        "--raw",
                        str(raw_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            report = json.loads(capability_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "supported")
            self.assertEqual(report["capability_generation_status"], "classified")
            self.assertEqual(report["problem_family"], "linear production planning")
            self.assertIn('"status": "supported"', raw_path.read_text(encoding="utf-8"))

    def test_capability_prompt_documents_blocking_semantics(self) -> None:
        prompt = build_statement_capability_prompt("CASE-001", "Goal programming with symbolic c_j.")

        self.assertIn("needs_human", prompt)
        self.assertIn("unsupported", prompt)
        self.assertIn("symbolic coefficients", prompt)
        self.assertIn("goal-programming", prompt)
        self.assertIn("Do not generate a ProblemSpec", prompt)

    def test_problem_spec_prompt_documents_constraint_relaxation_schema(self) -> None:
        prompt = build_problem_spec_prompt("CASE-001", "A capacity-constrained LP.")

        self.assertIn('"paths": [', prompt)
        self.assertIn('"instance.<resource_or_requirement_field>"', prompt)
        self.assertIn('"factor": 1.2', prompt)
        self.assertIn("do not use `path`, `amount`, or `direction`", prompt)
        self.assertIn("Preserve primitive statement quantities", prompt)
        self.assertIn("profit and transport cost", prompt)

    def test_problem_metadata_template_uses_requested_problem_id(self) -> None:
        template = json.loads(build_problem_metadata_template("CASE-123"))

        self.assertEqual(template["id"], "CASE-123")
        self.assertEqual(template["problem_type"], "LP")
        self.assertIn("cost_scaling", template["metamorphic"])
        relaxation = template["metamorphic"]["constraint_relaxation"]["relaxations"][0]
        self.assertIn("paths", relaxation)
        self.assertIn("factor", relaxation)

    def test_generate_accepts_explicit_problem_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            problem_path = root / "problem.json"
            statement_path = root / "problem.txt"
            submission_path = root / "submission.py"
            raw_path = root / "raw.txt"
            problem_path.write_text(json.dumps(_valid_problem()), encoding="utf-8")
            statement_path.write_text("Explicit statement context.", encoding="utf-8")

            def fake_query(messages, model_name):
                self.assertEqual(model_name, "mock-model")
                self.assertIn("Explicit statement context.", messages[1]["content"])
                return "```python\nimport gurobipy as gp\n\ndef build_model(data: dict):\n    return gp.Model()\n```"

            with patch("or_llm_agent.cli.query_llm", fake_query):
                exit_code = main(
                    [
                        "generate",
                        "--mode",
                        "api",
                        "--problem",
                        str(problem_path),
                        "--statement-file",
                        str(statement_path),
                        "--model",
                        "mock-model",
                        "--out",
                        str(submission_path),
                        "--raw",
                        str(raw_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("def build_model", submission_path.read_text(encoding="utf-8"))
            self.assertIn("def build_model", raw_path.read_text(encoding="utf-8"))

    def test_spec_writes_problem_raw_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            problem_path = root / "spec" / "problem.json"
            raw_path = root / "raw" / "spec.txt"
            status_path = root / "spec" / "status.json"
            statement_path.write_text("Minimize one production cost.", encoding="utf-8")

            with patch("or_llm_agent.cli._run_problem_spec_agent", return_value=_agent_result(root, _valid_problem())):
                exit_code = main(
                    [
                        "spec",
                        "--mode",
                        "agent",
                        "--statement-file",
                        str(statement_path),
                        "--problem-id",
                        "CASE-001",
                        "--out",
                        str(problem_path),
                        "--raw",
                        str(raw_path),
                        "--status",
                        str(status_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(problem_path.read_text(encoding="utf-8"))["id"], "CASE-001")
            self.assertIn('"id": "CASE-001"', raw_path.read_text(encoding="utf-8"))
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["spec_generation_status"], "generated")
            self.assertEqual(status["spec_validation_status"], "passed")
            self.assertEqual(status["validation_returncode"], 0)
            self.assertEqual(status["spec_attempt_count"], 1)
            self.assertEqual(status["spec_repair_status"], "not_needed")

    def test_spec_repairs_metadata_after_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            problem_path = root / "spec" / "problem.json"
            raw_path = root / "raw" / "spec.txt"
            status_path = root / "spec" / "status.json"
            statement_path.write_text("Maximize profit subject to capacity.", encoding="utf-8")
            calls = []

            def fake_run(**kwargs):
                calls.append(kwargs)
                payload = _invalid_constraint_relaxation_problem() if len(calls) == 1 else _valid_problem()
                return _agent_result(root, payload)

            with patch("or_llm_agent.cli._run_problem_spec_agent", fake_run):
                exit_code = main(
                    [
                        "spec",
                        "--mode",
                        "agent",
                        "--statement-file",
                        str(statement_path),
                        "--problem-id",
                        "CASE-001",
                        "--out",
                        str(problem_path),
                        "--raw",
                        str(raw_path),
                        "--status",
                        str(status_path),
                        "--max-repair-attempts",
                        "2",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0]["attempt"], 1)
            self.assertEqual(calls[1]["attempt"], 2)
            self.assertIn("paths must be a non-empty list", calls[1]["repair_error"])
            self.assertEqual(json.loads(problem_path.read_text(encoding="utf-8"))["id"], "CASE-001")
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["spec_validation_status"], "passed")
            self.assertEqual(status["spec_attempt_count"], 2)
            self.assertEqual(status["spec_repair_status"], "repaired")
            self.assertEqual(status["spec_attempts"][0]["spec_validation_status"], "failed")
            self.assertEqual(status["spec_attempts"][1]["spec_validation_status"], "passed")
            self.assertTrue((root / "raw" / "spec-attempt-1.txt").exists())
            self.assertTrue((root / "raw" / "spec-attempt-2.txt").exists())

    def test_solve_stops_before_model_generation_when_spec_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            artifact_dir = root / "run"
            statement_path.write_text("This statement will yield an invalid spec.", encoding="utf-8")

            invalid_problem = {
                "id": "CASE-FAIL",
                "problem_type": "LP",
                "metamorphic": {
                    "cost_scaling": {
                        "coefficient_paths": ["instance.price"],
                        "factors": [2.0],
                    }
                },
            }

            with (
                patch("or_llm_agent.cli._run_capability_agent", return_value=_capability_agent_result(root, _supported_capability())),
                patch("or_llm_agent.cli._run_problem_spec_agent", return_value=_agent_result(root, invalid_problem)),
                patch("or_llm_agent.cli.generate_agent_submission") as generate_agent_submission,
            ):
                exit_code = main(
                    [
                        "solve",
                        "--mode",
                        "agent",
                        "--statement-file",
                        str(statement_path),
                        "--problem-id",
                        "CASE-FAIL",
                        "--artifact-dir",
                        str(artifact_dir),
                    ]
                )

            self.assertEqual(exit_code, 1)
            generate_agent_submission.assert_not_called()
            summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["capability_status"], "supported")
            self.assertEqual(summary["spec_generation_status"], "generated")
            self.assertEqual(summary["spec_validation_status"], "failed")
            self.assertEqual(summary["spec_repair_status"], "failed")
            self.assertEqual(summary["spec_fidelity_status"], "not_reviewed")
            self.assertEqual(summary["spec_fidelity_review"], "spec/fidelity-review.md")
            self.assertEqual(summary["spec_fidelity_report"], "spec/fidelity-review.json")
            self.assertEqual(summary["spec_fidelity_gate_status"], "blocked_spec_invalid")
            self.assertEqual(summary["model_generation_status"], "skipped")
            self.assertFalse((artifact_dir / "submissions" / "CASE-FAIL.py").exists())
            review = (artifact_dir / "spec" / "fidelity-review.md").read_text(encoding="utf-8")
            self.assertIn("Fidelity status: `not_reviewed`", review)
            self.assertIn("Fidelity gate: `blocked_spec_invalid`", review)
            self.assertIn("OR-CI result is interpreted", review)
            report = json.loads((artifact_dir / "spec" / "fidelity-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["gate_status"], "blocked_spec_invalid")
            self.assertEqual(report["automatic_checks"][0]["status"], "FAIL")

    def test_solve_stops_before_problem_spec_when_capability_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            artifact_dir = root / "run"
            statement_path.write_text("Minimize cost and cholesterol as a goal programming model.", encoding="utf-8")
            capability = {
                "status": "unsupported",
                "problem_family": "goal programming",
                "supported_features": [],
                "unsupported_features": ["multi-objective goal-programming semantics"],
                "missing_information": [],
                "recommended_next_action": "extend_schema_or_verifier",
                "confidence": 0.94,
                "review_note": "Current ProblemSpec lacks goal-programming support.",
            }

            with (
                patch("or_llm_agent.cli._run_capability_agent", return_value=_capability_agent_result(root, capability)),
                patch("or_llm_agent.cli._run_problem_spec_agent") as run_problem_spec_agent,
                patch("or_llm_agent.cli.generate_agent_submission") as generate_agent_submission,
            ):
                exit_code = main(
                    [
                        "solve",
                        "--mode",
                        "agent",
                        "--statement-file",
                        str(statement_path),
                        "--problem-id",
                        "CASE-GOAL",
                        "--artifact-dir",
                        str(artifact_dir),
                    ]
                )

            self.assertEqual(exit_code, 1)
            run_problem_spec_agent.assert_not_called()
            generate_agent_submission.assert_not_called()
            summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["capability_status"], "unsupported")
            self.assertEqual(summary["problem_family"], "goal programming")
            self.assertEqual(summary["spec_generation_status"], "skipped")
            self.assertEqual(summary["spec_validation_status"], "skipped")
            self.assertEqual(summary["model_generation_status"], "skipped")
            self.assertEqual(summary["classification"], "blocked_capability")
            report = json.loads((artifact_dir / "spec" / "fidelity-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["gate_status"], "blocked_capability")
            self.assertIn("unsupported_feature", [flag["code"] for flag in report["risk_flags"]])
            self.assertTrue((artifact_dir / "spec" / "capability.json").exists())

    def test_solve_stops_before_problem_spec_when_capability_needs_human(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            artifact_dir = root / "run"
            statement_path.write_text("Use trucks with symbolic costs c_j.", encoding="utf-8")
            capability = {
                "status": "needs_human",
                "problem_family": "assignment",
                "supported_features": ["linear assignment structure"],
                "unsupported_features": [],
                "missing_information": ["numeric truck costs c_j are not provided"],
                "recommended_next_action": "ask_human",
                "confidence": 0.9,
                "review_note": "Symbolic objective coefficients require clarification.",
            }

            with (
                patch("or_llm_agent.cli._run_capability_agent", return_value=_capability_agent_result(root, capability)),
                patch("or_llm_agent.cli._run_problem_spec_agent") as run_problem_spec_agent,
            ):
                exit_code = main(
                    [
                        "solve",
                        "--mode",
                        "agent",
                        "--statement-file",
                        str(statement_path),
                        "--problem-id",
                        "CASE-SYMBOLIC",
                        "--artifact-dir",
                        str(artifact_dir),
                    ]
                )

            self.assertEqual(exit_code, 1)
            run_problem_spec_agent.assert_not_called()
            summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["capability_status"], "needs_human")
            self.assertEqual(summary["capability_missing_information"], ["numeric truck costs c_j are not provided"])
            self.assertEqual(summary["classification"], "blocked_capability")

    def test_solve_writes_spec_fidelity_review_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            artifact_dir = root / "run"
            statement_path.write_text("Minimize one production cost.", encoding="utf-8")

            def fake_generate_agent_submission(inputs, paths, args):
                paths.submission_path.parent.mkdir(parents=True, exist_ok=True)
                paths.raw_path.parent.mkdir(parents=True, exist_ok=True)
                paths.submission_path.write_text("def build_model(data):\n    return None\n", encoding="utf-8")
                paths.raw_path.write_text("generated model", encoding="utf-8")
                return {
                    "generation_status": "generated",
                    "generation_error": "",
                    "raw_response": paths.raw_path,
                    "submission": paths.submission_path,
                    "generation_mode": "agent",
                    "agent_returncode": 0,
                    "agent_timed_out": False,
                }

            verification = VerificationResult(
                returncode=0,
                stdout="",
                stderr="",
                report={"classification": "SUCCESS", "status": "PASS", "checks": []},
            )

            with (
                patch("or_llm_agent.cli._run_capability_agent", return_value=_capability_agent_result(root, _supported_capability())),
                patch("or_llm_agent.cli._run_problem_spec_agent", return_value=_agent_result(root, _valid_problem())),
                patch("or_llm_agent.cli.generate_agent_submission", fake_generate_agent_submission),
                patch("or_llm_agent.cli.run_or_ci_verify", return_value=verification),
            ):
                exit_code = main(
                    [
                        "solve",
                        "--mode",
                        "agent",
                        "--statement-file",
                        str(statement_path),
                        "--problem-id",
                        "CASE-001",
                        "--artifact-dir",
                        str(artifact_dir),
                    ]
                )

            self.assertEqual(exit_code, 0)
            summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["capability_status"], "supported")
            self.assertEqual(summary["spec_validation_status"], "passed")
            self.assertEqual(summary["spec_repair_status"], "not_needed")
            self.assertEqual(summary["model_generation_status"], "generated")
            self.assertEqual(summary["verification_status"], "PASS")
            self.assertEqual(summary["classification"], "SUCCESS")
            self.assertEqual(summary["spec_fidelity_status"], "not_reviewed")
            self.assertEqual(summary["spec_fidelity_review"], "spec/fidelity-review.md")
            self.assertEqual(summary["spec_fidelity_report"], "spec/fidelity-review.json")
            self.assertEqual(summary["spec_fidelity_gate_status"], "manual_review_required")
            review = (artifact_dir / "spec" / "fidelity-review.md").read_text(encoding="utf-8")
            self.assertIn("Model generation: `generated`", review)
            self.assertIn("Verification: `PASS`", review)
            self.assertIn("Fidelity status: `not_reviewed`", review)
            self.assertIn("Fidelity gate: `manual_review_required`", review)
            report = json.loads((artifact_dir / "spec" / "fidelity-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["gate_status"], "manual_review_required")
            self.assertEqual(report["automatic_checks"][1]["status"], "PASS")

    def test_solve_batch_writes_aggregate_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statements_dir = root / "statements"
            statements_dir.mkdir()
            for problem_id in ("CASE-001", "CASE-002"):
                (statements_dir / f"{problem_id}.txt").write_text(f"Statement for {problem_id}.", encoding="utf-8")
            artifact_dir = root / "batch"

            def fake_run(**kwargs):
                return _agent_result(root, _valid_problem(kwargs["problem_id"]))

            def fake_generate_agent_submission(inputs, paths, args):
                paths.submission_path.parent.mkdir(parents=True, exist_ok=True)
                paths.raw_path.parent.mkdir(parents=True, exist_ok=True)
                paths.submission_path.write_text("def build_model(data):\n    return None\n", encoding="utf-8")
                paths.raw_path.write_text("generated model", encoding="utf-8")
                return {
                    "generation_status": "generated",
                    "generation_error": "",
                    "raw_response": paths.raw_path,
                    "submission": paths.submission_path,
                    "generation_mode": "agent",
                    "agent_returncode": 0,
                    "agent_timed_out": False,
                }

            verification = VerificationResult(
                returncode=0,
                stdout="",
                stderr="",
                report={"classification": "SUCCESS", "status": "PASS", "checks": []},
            )

            with (
                patch("or_llm_agent.cli._run_capability_agent", return_value=_capability_agent_result(root, _supported_capability())),
                patch("or_llm_agent.cli._run_problem_spec_agent", fake_run),
                patch("or_llm_agent.cli.generate_agent_submission", fake_generate_agent_submission),
                patch("or_llm_agent.cli.run_or_ci_verify", return_value=verification),
            ):
                exit_code = main(
                    [
                        "solve-batch",
                        "--mode",
                        "agent",
                        "--ids",
                        "CASE-001",
                        "CASE-002",
                        "--statements-dir",
                        str(statements_dir),
                        "--artifact-dir",
                        str(artifact_dir),
                    ]
                )

            self.assertEqual(exit_code, 0)
            batch = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(batch["summary"]["total"], 2)
            self.assertEqual(batch["summary"]["succeeded"], 2)
            self.assertEqual(batch["summary"]["capability_statuses"]["supported"], 2)
            self.assertEqual(batch["summary"]["spec_fidelity_statuses"]["not_reviewed"], 2)
            self.assertEqual(batch["summary"]["spec_fidelity_gate_statuses"]["manual_review_required"], 2)
            self.assertEqual(len(batch["rows"]), 2)
            self.assertTrue((artifact_dir / "report.md").exists())
            self.assertTrue((artifact_dir / "CASE-001" / "spec" / "fidelity-review.json").exists())

    def test_solve_batch_preserves_serial_behavior_with_concurrency_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statements_dir = root / "statements"
            statements_dir.mkdir()
            for problem_id in ("CASE-001", "CASE-002"):
                (statements_dir / f"{problem_id}.txt").write_text(f"Statement for {problem_id}.", encoding="utf-8")
            artifact_dir = root / "batch"
            calls: list[str] = []

            def fake_solve(solve_args):
                calls.append(solve_args.problem_id)
                _write_minimal_case_summary(solve_args.artifact_dir, solve_args.problem_id)
                return 0

            with patch("or_llm_agent.cli.solve_command", fake_solve):
                exit_code = main(
                    [
                        "solve-batch",
                        "--mode",
                        "agent",
                        "--ids",
                        "CASE-001",
                        "CASE-002",
                        "--statements-dir",
                        str(statements_dir),
                        "--artifact-dir",
                        str(artifact_dir),
                        "--agent-concurrency",
                        "1",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(calls, ["CASE-001", "CASE-002"])
            batch = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual([row["problem_id"] for row in batch["rows"]], ["CASE-001", "CASE-002"])

    def test_solve_batch_runs_cases_concurrently_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statements_dir = root / "statements"
            statements_dir.mkdir()
            for problem_id in ("CASE-001", "CASE-002"):
                (statements_dir / f"{problem_id}.txt").write_text(f"Statement for {problem_id}.", encoding="utf-8")
            artifact_dir = root / "batch"
            barrier = threading.Barrier(2, timeout=5)
            seen: set[str] = set()
            lock = threading.Lock()

            def fake_run(**kwargs):
                with lock:
                    seen.add(kwargs["problem_id"])
                barrier.wait()
                return _agent_result(root, _valid_problem(kwargs["problem_id"]))

            verification = VerificationResult(
                returncode=0,
                stdout="",
                stderr="",
                report={"classification": "SUCCESS", "status": "PASS", "checks": []},
            )

            with (
                patch("or_llm_agent.cli._run_capability_agent", return_value=_capability_agent_result(root, _supported_capability())),
                patch("or_llm_agent.cli._run_problem_spec_agent", fake_run),
                patch("or_llm_agent.cli.generate_agent_submission", _fake_generate_agent_submission),
                patch("or_llm_agent.cli.run_or_ci_verify", return_value=verification),
            ):
                exit_code = main(
                    [
                        "solve-batch",
                        "--mode",
                        "agent",
                        "--ids",
                        "CASE-001",
                        "CASE-002",
                        "--statements-dir",
                        str(statements_dir),
                        "--artifact-dir",
                        str(artifact_dir),
                        "--agent-concurrency",
                        "2",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(seen, {"CASE-001", "CASE-002"})

    def test_solve_batch_handles_larger_concurrent_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statements_dir = root / "statements"
            statements_dir.mkdir()
            problem_ids = [f"CASE-{index:03d}" for index in range(1, 13)]
            for problem_id in problem_ids:
                (statements_dir / f"{problem_id}.txt").write_text(f"Statement for {problem_id}.", encoding="utf-8")
            artifact_dir = root / "batch"
            barrier = threading.Barrier(4, timeout=5)
            active_workers = 0
            max_active_workers = 0
            lock = threading.Lock()

            def fake_solve(solve_args):
                nonlocal active_workers, max_active_workers
                with lock:
                    active_workers += 1
                    max_active_workers = max(max_active_workers, active_workers)
                try:
                    barrier.wait()
                    _write_minimal_case_summary(solve_args.artifact_dir, solve_args.problem_id)
                    return 0
                finally:
                    with lock:
                        active_workers -= 1

            with patch("or_llm_agent.cli.solve_command", fake_solve):
                exit_code = main(
                    [
                        "solve-batch",
                        "--mode",
                        "agent",
                        "--ids",
                        *problem_ids,
                        "--statements-dir",
                        str(statements_dir),
                        "--artifact-dir",
                        str(artifact_dir),
                        "--agent-concurrency",
                        "4",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(max_active_workers, 4)
            batch = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(batch["summary"]["total"], 12)
            self.assertEqual(batch["summary"]["succeeded"], 12)
            self.assertEqual([row["problem_id"] for row in batch["rows"]], problem_ids)

    def test_solve_batch_rejects_invalid_agent_concurrency_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_dir = root / "batch"

            with patch("or_llm_agent.cli.solve_command") as solve_command:
                exit_code = main(
                    [
                        "solve-batch",
                        "--mode",
                        "agent",
                        "--ids",
                        "CASE-001",
                        "--artifact-dir",
                        str(artifact_dir),
                        "--agent-concurrency",
                        "0",
                    ]
                )

            self.assertEqual(exit_code, 1)
            solve_command.assert_not_called()
            self.assertFalse((artifact_dir / "summary.json").exists())

    def test_solve_batch_rejects_duplicate_ids_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_dir = root / "batch"

            with patch("or_llm_agent.cli.solve_command") as solve_command:
                exit_code = main(
                    [
                        "solve-batch",
                        "--mode",
                        "agent",
                        "--ids",
                        "CASE-001",
                        "CASE-001",
                        "--artifact-dir",
                        str(artifact_dir),
                    ]
                )

            self.assertEqual(exit_code, 1)
            solve_command.assert_not_called()
            self.assertFalse((artifact_dir / "summary.json").exists())

    def test_solve_batch_preserves_input_order_when_workers_finish_out_of_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statements_dir = root / "statements"
            statements_dir.mkdir()
            for problem_id in ("CASE-SLOW", "CASE-FAST"):
                (statements_dir / f"{problem_id}.txt").write_text(f"Statement for {problem_id}.", encoding="utf-8")
            artifact_dir = root / "batch"

            def fake_solve(solve_args):
                if solve_args.problem_id == "CASE-SLOW":
                    time.sleep(0.2)
                _write_minimal_case_summary(solve_args.artifact_dir, solve_args.problem_id)
                return 0

            with patch("or_llm_agent.cli.solve_command", fake_solve):
                exit_code = main(
                    [
                        "solve-batch",
                        "--mode",
                        "agent",
                        "--ids",
                        "CASE-SLOW",
                        "CASE-FAST",
                        "--statements-dir",
                        str(statements_dir),
                        "--artifact-dir",
                        str(artifact_dir),
                        "--agent-concurrency",
                        "2",
                    ]
                )

            self.assertEqual(exit_code, 0)
            batch = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual([row["problem_id"] for row in batch["rows"]], ["CASE-SLOW", "CASE-FAST"])

    def test_solve_batch_records_case_exception_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statements_dir = root / "statements"
            statements_dir.mkdir()
            for problem_id in ("CASE-FAIL", "CASE-OK"):
                (statements_dir / f"{problem_id}.txt").write_text(f"Statement for {problem_id}.", encoding="utf-8")
            artifact_dir = root / "batch"

            def fake_solve(solve_args):
                if solve_args.problem_id == "CASE-FAIL":
                    raise RuntimeError("synthetic failure")
                _write_minimal_case_summary(solve_args.artifact_dir, solve_args.problem_id)
                return 0

            with patch("or_llm_agent.cli.solve_command", fake_solve):
                exit_code = main(
                    [
                        "solve-batch",
                        "--mode",
                        "agent",
                        "--ids",
                        "CASE-FAIL",
                        "CASE-OK",
                        "--statements-dir",
                        str(statements_dir),
                        "--artifact-dir",
                        str(artifact_dir),
                        "--agent-concurrency",
                        "2",
                    ]
                )

            self.assertEqual(exit_code, 1)
            batch = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            row_by_id = {row["problem_id"]: row for row in batch["rows"]}
            self.assertEqual(row_by_id["CASE-FAIL"]["exit_code"], 1)
            self.assertIn("RuntimeError", row_by_id["CASE-FAIL"]["batch_error"])
            self.assertEqual(row_by_id["CASE-OK"]["exit_code"], 0)

    def test_review_fidelity_accepts_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            artifact_dir = root / "run"
            _write_solved_case(root, statement_path, artifact_dir)

            exit_code = main(
                [
                    "review-fidelity",
                    "--artifact-dir",
                    str(artifact_dir),
                    "--status",
                    "accepted",
                    "--reviewer",
                    "unit-test",
                    "--note",
                    "Numbers and constraints match the statement.",
                    "--evidence",
                    "manual checklist",
                ]
            )

            self.assertEqual(exit_code, 0)
            summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["spec_fidelity_status"], "accepted")
            self.assertEqual(summary["spec_fidelity_gate_status"], "accepted")
            self.assertEqual(summary["spec_fidelity_reviewed_by"], "unit-test")
            report = json.loads((artifact_dir / "spec" / "fidelity-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["fidelity_status"], "accepted")
            self.assertEqual(report["gate_status"], "accepted")
            self.assertEqual(report["review"]["status"], "accepted")
            self.assertEqual(report["automatic_checks"][2]["status"], "PASS")
            review = (artifact_dir / "spec" / "fidelity-review.md").read_text(encoding="utf-8")
            self.assertIn("## Review Decision", review)
            self.assertIn("Status: `accepted`", review)

    def test_review_fidelity_agent_accepts_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            artifact_dir = root / "run"
            _write_solved_case(root, statement_path, artifact_dir)

            payload = {
                "status": "accepted",
                "confidence": 0.92,
                "issues": [],
                "review_note": "Source statement and generated spec match.",
                "evidence": ["objective and price field match"],
            }
            with patch(
                "or_llm_agent.cli._run_fidelity_review_agent",
                return_value=_review_agent_result(root, payload),
            ):
                exit_code = main(["review-fidelity", "--mode", "agent", "--artifact-dir", str(artifact_dir)])

            self.assertEqual(exit_code, 0)
            summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["spec_fidelity_status"], "llm_accepted")
            self.assertEqual(summary["spec_fidelity_gate_status"], "llm_accepted")
            self.assertEqual(summary["spec_fidelity_review_mode"], "agent")
            self.assertEqual(summary["spec_fidelity_confidence"], 0.92)
            self.assertEqual(summary["spec_fidelity_issue_count"], 0)
            report = json.loads((artifact_dir / "spec" / "fidelity-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["review"]["reviewer"], "codex-agent")
            self.assertEqual(report["automatic_checks"][2]["status"], "PASS")

    def test_review_fidelity_agent_rejects_no_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            artifact_dir = root / "run"
            _write_solved_case(root, statement_path, artifact_dir)

            result = FidelityReviewAgentResult(
                raw_text="not json",
                returncode=0,
                timed_out=False,
                events_path=root / "review-events.jsonl",
                last_message_path=root / "review-last-message.md",
                stderr="",
            )
            with patch("or_llm_agent.cli._run_fidelity_review_agent", return_value=result):
                exit_code = main(["review-fidelity", "--mode", "agent", "--artifact-dir", str(artifact_dir)])

            self.assertEqual(exit_code, 0)
            summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["spec_fidelity_status"], "llm_rejected")
            self.assertEqual(summary["spec_fidelity_gate_status"], "llm_rejected")
            self.assertIn("did not return a JSON object", summary["spec_fidelity_review_note"])
            report = json.loads((artifact_dir / "spec" / "fidelity-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["automatic_checks"][2]["status"], "FAIL")

    def test_review_fidelity_rejects_case_even_when_verification_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            artifact_dir = root / "run"
            _write_solved_case(root, statement_path, artifact_dir, verification=VerificationResult(1, "", "", None))

            exit_code = main(
                [
                    "review-fidelity",
                    "--artifact-dir",
                    str(artifact_dir),
                    "--status",
                    "rejected",
                    "--reviewer",
                    "unit-test",
                    "--note",
                    "Verification did not pass.",
                ]
            )

            self.assertEqual(exit_code, 0)
            summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["spec_fidelity_status"], "rejected")
            self.assertEqual(summary["spec_fidelity_gate_status"], "rejected")
            report = json.loads((artifact_dir / "spec" / "fidelity-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["automatic_checks"][2]["status"], "FAIL")

    def test_review_fidelity_does_not_accept_failed_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            artifact_dir = root / "run"
            _write_solved_case(root, statement_path, artifact_dir, verification=VerificationResult(1, "", "", None))

            exit_code = main(
                [
                    "review-fidelity",
                    "--artifact-dir",
                    str(artifact_dir),
                    "--status",
                    "accepted",
                    "--reviewer",
                    "unit-test",
                    "--note",
                    "Should fail.",
                ]
            )

            self.assertEqual(exit_code, 1)
            summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["spec_fidelity_status"], "not_reviewed")
            self.assertEqual(summary["spec_fidelity_gate_status"], "manual_review_required")

    def test_review_fidelity_batch_updates_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_dir = root / "batch"
            statements_dir = artifact_dir / "statements"
            statements_dir.mkdir(parents=True)
            for problem_id in ("CASE-001", "CASE-002"):
                _write_solved_case(
                    root,
                    statements_dir / f"{problem_id}.txt",
                    artifact_dir / problem_id,
                    problem_id=problem_id,
                )
            rows = [
                {
                    "problem_id": problem_id,
                    "exit_code": 0,
                    "artifact_dir": problem_id,
                    "statement_file": f"statements/{problem_id}.txt",
                    "spec_validation_status": "passed",
                    "spec_attempt_count": 1,
                    "spec_repair_status": "not_needed",
                    "model_generation_status": "generated",
                    "verification_status": "PASS",
                    "classification": "SUCCESS",
                    "spec_fidelity_status": "not_reviewed",
                    "spec_fidelity_gate_status": "manual_review_required",
                }
                for problem_id in ("CASE-001", "CASE-002")
            ]
            (artifact_dir / "summary.json").write_text(
                json.dumps({"summary": {"total": 2}, "rows": rows}, indent=2) + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "review-fidelity-batch",
                    "--artifact-dir",
                    str(artifact_dir),
                    "--status",
                    "accepted",
                    "--reviewer",
                    "unit-test",
                    "--note",
                    "Manual batch review accepted.",
                ]
            )

            self.assertEqual(exit_code, 0)
            batch = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(batch["summary"]["spec_fidelity_statuses"]["accepted"], 2)
            self.assertEqual(batch["summary"]["spec_fidelity_gate_statuses"]["accepted"], 2)
            self.assertEqual(batch["rows"][0]["spec_fidelity_status"], "accepted")
            self.assertIn("accepted", (artifact_dir / "report.md").read_text(encoding="utf-8"))

    def test_resolve_fidelity_repairs_rejected_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            artifact_dir = root / "run"
            resolution_dir = root / "resolved"
            _write_solved_case(root, statement_path, artifact_dir, verification=_verification_with_objective(10.0))
            main(
                [
                    "review-fidelity",
                    "--artifact-dir",
                    str(artifact_dir),
                    "--status",
                    "rejected",
                    "--reviewer",
                    "unit-test",
                    "--note",
                    "Missing action in generated spec.",
                ]
            )
            repair_calls = []

            def fake_run(**kwargs):
                repair_calls.append(kwargs)
                return _agent_result(root, _valid_problem(kwargs["problem_id"]))

            accepted_review = {
                "status": "accepted",
                "confidence": 0.91,
                "issues": [],
                "review_note": "Repaired spec now matches the statement.",
                "evidence": ["missing action restored"],
            }
            with (
                patch("or_llm_agent.cli._run_problem_spec_agent", fake_run),
                patch("or_llm_agent.cli.generate_agent_submission", _fake_generate_agent_submission),
                patch("or_llm_agent.cli.run_or_ci_verify", _fake_verify_with_objective(10.0)),
                patch("or_llm_agent.cli._run_fidelity_review_agent", return_value=_review_agent_result(root, accepted_review)),
            ):
                exit_code = main(
                    [
                        "resolve-fidelity",
                        "--artifact-dir",
                        str(artifact_dir),
                        "--resolution-dir",
                        str(resolution_dir),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(repair_calls)
            self.assertIn("Missing action", repair_calls[0]["repair_error"])
            source_summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(source_summary["fidelity_resolution_status"], "repaired_accepted")
            self.assertEqual(source_summary["fidelity_resolution_repaired_fidelity_status"], "llm_accepted")
            self.assertEqual(source_summary["fidelity_resolution_impact_classification"], "not_needed")
            repaired_summary = json.loads((resolution_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(repaired_summary["spec_repair_status"], "repaired")
            self.assertEqual(repaired_summary["spec_fidelity_status"], "llm_accepted")
            resolution = json.loads((resolution_dir / "fidelity-resolution.json").read_text(encoding="utf-8"))
            self.assertEqual(resolution["resolution_status"], "repaired_accepted")

    def test_resolve_fidelity_classifies_harmless_equivalent_when_review_still_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            statement_path = root / "problem.txt"
            artifact_dir = root / "run"
            resolution_dir = root / "resolved"
            _write_solved_case(root, statement_path, artifact_dir, verification=_verification_with_objective(10.0))
            main(
                [
                    "review-fidelity",
                    "--artifact-dir",
                    str(artifact_dir),
                    "--status",
                    "rejected",
                    "--reviewer",
                    "unit-test",
                    "--note",
                    "Missing dominated terminal action.",
                ]
            )
            rejected_review = {
                "status": "rejected",
                "confidence": 0.8,
                "issues": [{"severity": "minor", "field": "action_space", "message": "still incomplete"}],
                "review_note": "Residual action-space issue remains.",
                "evidence": [],
            }
            with (
                patch("or_llm_agent.cli._run_problem_spec_agent", return_value=_agent_result(root, _valid_problem())),
                patch("or_llm_agent.cli.generate_agent_submission", _fake_generate_agent_submission),
                patch("or_llm_agent.cli.run_or_ci_verify", _fake_verify_with_objective(10.0)),
                patch("or_llm_agent.cli._run_fidelity_review_agent", return_value=_review_agent_result(root, rejected_review)),
            ):
                exit_code = main(
                    [
                        "resolve-fidelity",
                        "--artifact-dir",
                        str(artifact_dir),
                        "--resolution-dir",
                        str(resolution_dir),
                    ]
                )

            self.assertEqual(exit_code, 0)
            source_summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(source_summary["fidelity_resolution_status"], "residual_harmless_equivalent")
            self.assertEqual(source_summary["fidelity_resolution_impact_classification"], "harmless_equivalent")
            resolution = json.loads((resolution_dir / "fidelity-resolution.json").read_text(encoding="utf-8"))
            self.assertEqual(resolution["impact_analysis"]["classification"], "harmless_equivalent")
            self.assertEqual(resolution["repaired_fidelity_status"], "llm_rejected")

    def test_resolve_fidelity_batch_processes_only_rejected_cases_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_dir = root / "batch"
            statements_dir = artifact_dir / "statements"
            statements_dir.mkdir(parents=True)
            for problem_id in ("CASE-001", "CASE-002"):
                _write_solved_case(
                    root,
                    statements_dir / f"{problem_id}.txt",
                    artifact_dir / problem_id,
                    problem_id=problem_id,
                    verification=_verification_with_objective(10.0),
                )
            main(
                [
                    "review-fidelity",
                    "--artifact-dir",
                    str(artifact_dir / "CASE-001"),
                    "--status",
                    "rejected",
                    "--reviewer",
                    "unit-test",
                    "--note",
                    "Needs repair.",
                ]
            )
            main(
                [
                    "review-fidelity",
                    "--artifact-dir",
                    str(artifact_dir / "CASE-002"),
                    "--status",
                    "accepted",
                    "--reviewer",
                    "unit-test",
                    "--note",
                    "Accepted.",
                ]
            )
            rows = [
                {
                    "problem_id": problem_id,
                    "exit_code": 0,
                    "artifact_dir": problem_id,
                    "statement_file": f"statements/{problem_id}.txt",
                    "spec_validation_status": "passed",
                    "spec_attempt_count": 1,
                    "spec_repair_status": "not_needed",
                    "model_generation_status": "generated",
                    "verification_status": "PASS",
                    "classification": "SUCCESS",
                    "spec_fidelity_status": "rejected" if problem_id == "CASE-001" else "accepted",
                    "spec_fidelity_gate_status": "rejected" if problem_id == "CASE-001" else "accepted",
                }
                for problem_id in ("CASE-001", "CASE-002")
            ]
            (artifact_dir / "summary.json").write_text(
                json.dumps({"summary": {"total": 2}, "rows": rows}, indent=2) + "\n",
                encoding="utf-8",
            )
            accepted_review = {
                "status": "accepted",
                "confidence": 0.9,
                "issues": [],
                "review_note": "Resolved.",
                "evidence": [],
            }
            with (
                patch("or_llm_agent.cli._run_problem_spec_agent", return_value=_agent_result(root, _valid_problem("CASE-001"))),
                patch("or_llm_agent.cli.generate_agent_submission", _fake_generate_agent_submission),
                patch("or_llm_agent.cli.run_or_ci_verify", _fake_verify_with_objective(10.0)),
                patch("or_llm_agent.cli._run_fidelity_review_agent", return_value=_review_agent_result(root, accepted_review)),
            ):
                exit_code = main(["resolve-fidelity-batch", "--artifact-dir", str(artifact_dir)])

            self.assertEqual(exit_code, 0)
            resolution_summary = json.loads((artifact_dir / "fidelity-resolution-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(resolution_summary["summary"]["total"], 1)
            self.assertEqual(resolution_summary["rows"][0]["problem_id"], "CASE-001")
            batch = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
            row_by_id = {row["problem_id"]: row for row in batch["rows"]}
            self.assertEqual(row_by_id["CASE-001"]["fidelity_resolution_status"], "repaired_accepted")
            self.assertNotIn("fidelity_resolution_status", row_by_id["CASE-002"])


def _agent_result(root: Path, payload: dict) -> ProblemSpecAgentResult:
    return ProblemSpecAgentResult(
        raw_text=json.dumps(payload, indent=2),
        returncode=0,
        timed_out=False,
        events_path=root / "events.jsonl",
        last_message_path=root / "last-message.md",
        stderr="",
    )


def _review_agent_result(root: Path, payload: dict) -> FidelityReviewAgentResult:
    return FidelityReviewAgentResult(
        raw_text=json.dumps(payload, indent=2),
        returncode=0,
        timed_out=False,
        events_path=root / "review-events.jsonl",
        last_message_path=root / "review-last-message.md",
        stderr="",
    )


def _capability_agent_result(root: Path, payload: dict) -> CapabilityAgentResult:
    return CapabilityAgentResult(
        raw_text=json.dumps(payload, indent=2),
        returncode=0,
        timed_out=False,
        events_path=root / "capability-events.jsonl",
        last_message_path=root / "capability-last-message.md",
        stderr="",
    )


def _supported_capability(problem_family: str = "linear programming") -> dict:
    return {
        "status": "supported",
        "problem_family": problem_family,
        "supported_features": ["single-objective linear model with numeric data"],
        "unsupported_features": [],
        "missing_information": [],
        "recommended_next_action": "continue_to_problemspec",
        "confidence": 0.95,
        "review_note": "Statement is within current OR-CI LP/MILP support.",
    }


def _fake_generate_agent_submission(inputs, paths, args):
    paths.submission_path.parent.mkdir(parents=True, exist_ok=True)
    paths.raw_path.parent.mkdir(parents=True, exist_ok=True)
    paths.submission_path.write_text("def build_model(data):\n    return None\n", encoding="utf-8")
    paths.raw_path.write_text("generated model", encoding="utf-8")
    return {
        "generation_status": "generated",
        "generation_error": "",
        "raw_response": paths.raw_path,
        "submission": paths.submission_path,
        "generation_mode": "agent",
        "agent_returncode": 0,
        "agent_timed_out": False,
    }


def _verification_with_objective(objective: float) -> VerificationResult:
    return VerificationResult(
        returncode=0,
        stdout="",
        stderr="",
        report={
            "classification": "SUCCESS",
            "status": "PASS",
            "checks": [
                {
                    "name": "original_solver_status",
                    "status": "PASS",
                    "details": {"objective_value": objective},
                }
            ],
        },
    )


def _fake_verify_with_objective(objective: float):
    verification = _verification_with_objective(objective)

    def fake_verify(problem_path, submission_path, report_path, cwd):
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(verification.report, indent=2) + "\n", encoding="utf-8")
        return verification

    return fake_verify


def _write_solved_case(
    root: Path,
    statement_path: Path,
    artifact_dir: Path,
    *,
    problem_id: str = "CASE-001",
    verification: VerificationResult | None = None,
) -> None:
    statement_path.parent.mkdir(parents=True, exist_ok=True)
    statement_path.write_text(f"Statement for {problem_id}.", encoding="utf-8")
    verification = verification or VerificationResult(
        returncode=0,
        stdout="",
        stderr="",
        report={"classification": "SUCCESS", "status": "PASS", "checks": []},
    )

    def fake_verify(problem_path, submission_path, report_path, cwd):
        if verification.report is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(verification.report, indent=2) + "\n", encoding="utf-8")
        return verification

    with (
        patch("or_llm_agent.cli._run_capability_agent", return_value=_capability_agent_result(root, _supported_capability())),
        patch("or_llm_agent.cli._run_problem_spec_agent", return_value=_agent_result(root, _valid_problem(problem_id))),
        patch("or_llm_agent.cli.generate_agent_submission", _fake_generate_agent_submission),
        patch("or_llm_agent.cli.run_or_ci_verify", fake_verify),
    ):
        exit_code = main(
            [
                "solve",
                "--mode",
                "agent",
                "--statement-file",
                str(statement_path),
                "--problem-id",
                problem_id,
                "--artifact-dir",
                str(artifact_dir),
            ]
        )
    expected = 0 if verification.returncode == 0 else 1
    if exit_code != expected:
        raise AssertionError(f"unexpected solve exit code: {exit_code}")


def _write_minimal_case_summary(artifact_dir: Path, problem_id: str) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "summary.json").write_text(
        json.dumps(
            {
                "problem_id": problem_id,
                "capability_status": "supported",
                "capability_generation_status": "classified",
                "problem_family": "linear programming",
                "spec_validation_status": "passed",
                "spec_attempt_count": 1,
                "spec_repair_status": "not_needed",
                "model_generation_status": "generated",
                "verification_status": "PASS",
                "classification": "SUCCESS",
                "spec_fidelity_status": "not_reviewed",
                "spec_fidelity_gate_status": "manual_review_required",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _valid_problem(problem_id: str = "CASE-001") -> dict:
    return {
        "id": problem_id,
        "problem_type": "LP",
        "instance": {"price": 4.0},
        "metamorphic": {
            "cost_scaling": {
                "coefficient_paths": ["instance.price"],
                "factors": [2.0],
                "tolerance_abs": 1e-6,
                "tolerance_rel": 1e-6,
            }
        },
    }


def _invalid_constraint_relaxation_problem() -> dict:
    problem = _valid_problem()
    problem["metamorphic"]["constraint_relaxation"] = {
        "relaxations": [
            {
                "path": "instance.capacity",
                "direction": "increase",
                "amount": 1.0,
                "objective_relation": "non_decrease",
            }
        ],
        "tolerance_abs": 1e-6,
        "tolerance_rel": 1e-6,
    }
    return problem


if __name__ == "__main__":
    unittest.main()
