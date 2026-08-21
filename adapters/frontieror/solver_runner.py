"""Execute generated Python with enforced Gurobi limits and incumbent checkpoints."""

from __future__ import annotations

import argparse
import ast
import json
import os
import time
from pathlib import Path
from typing import Any


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


class OptimizeTransformer(ast.NodeTransformer):
    def visit_Call(self, node: ast.Call) -> ast.AST:
        node = self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "optimize":
            return ast.copy_location(
                ast.Call(
                    func=ast.Name(id="__frontieror_optimize", ctx=ast.Load()),
                    args=[node.func.value, *node.args],
                    keywords=node.keywords,
                ),
                node,
            )
        return node


def execute(source: str, candidate_path: Path, timeout_s: int) -> None:
    import gurobipy as gp

    attempt = int(os.environ.get("FRONTIEROR_SOLVER_ATTEMPT", "1"))

    def save(
        model: Any,
        *,
        source_kind: str,
        values: list[float] | None = None,
        objective: float | None = None,
        objective_bound: float | None = None,
    ) -> None:
        try:
            if values is None:
                if int(model.SolCount) <= 0:
                    return
                values = list(model.getAttr("X", model.getVars()))
            variables = {
                var.VarName: value
                for var, value in zip(model.getVars(), values)
            }
            payload = {
                "schema_version": "frontieror_raw_candidate_v1",
                "attempt": attempt,
                "captured_at": time.time(),
                "source": source_kind,
                "objective": float(model.ObjVal if objective is None else objective),
                "objective_bound": float(
                    model.ObjBound if objective_bound is None else objective_bound
                ),
                "status": None if source_kind == "incumbent" else int(model.Status),
                "solution_count": None
                if source_kind == "incumbent"
                else int(model.SolCount),
                "variables": variables,
            }
            if candidate_path.is_file():
                previous = json.loads(candidate_path.read_text(encoding="utf-8"))
                payload["previous_attempt"] = previous.get("attempt")
            _atomic_json(candidate_path, payload)
            candidates = candidate_path.parent / "raw_candidates"
            candidates.mkdir(exist_ok=True)
            _atomic_json(candidates / f"attempt-{attempt}.json", payload)
        except (AttributeError, OSError, ValueError, gp.GurobiError):
            return

    def optimize(model: Any, *args: Any, **kwargs: Any) -> Any:
        current = float(model.Params.TimeLimit)
        model.Params.TimeLimit = min(current, float(timeout_s))
        original_callback = args[0] if args else kwargs.pop("callback", None)

        def checkpoint_callback(cb_model: Any, where: int) -> None:
            if original_callback is not None:
                original_callback(cb_model, where)
            if where == gp.GRB.Callback.MIPSOL:
                try:
                    save(
                        cb_model,
                        source_kind="incumbent",
                        values=list(cb_model.cbGetSolution(cb_model.getVars())),
                        objective=float(cb_model.cbGet(gp.GRB.Callback.MIPSOL_OBJ)),
                        objective_bound=float(cb_model.cbGet(gp.GRB.Callback.MIPSOL_OBJBND)),
                    )
                except gp.GurobiError:
                    pass

        result = model.optimize(checkpoint_callback)
        save(model, source_kind="solver_exit")
        return result

    tree = OptimizeTransformer().visit(ast.parse(source, filename="solver.py"))
    ast.fix_missing_locations(tree)
    namespace = {
        "__name__": "__main__",
        "__file__": "solver.py",
        "__frontieror_optimize": optimize,
    }
    exec(compile(tree, "solver.py", "exec"), namespace, namespace)  # noqa: S102


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--timeout", type=int, required=True)
    args = parser.parse_args()
    execute(
        args.source.read_text(encoding="utf-8"),
        args.candidate,
        args.timeout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
