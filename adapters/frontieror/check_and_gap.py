"""Compute OR-LLM-Agent gaps from an existing FrontierOR checker report."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path

def objective(path: Path):
    try:
        value=json.loads(path.read_text(encoding="utf-8")).get("objective_value")
        return float(value) if isinstance(value,(int,float)) and math.isfinite(float(value)) else None
    except (OSError, ValueError, TypeError):
        return None

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--candidate-root",type=Path,required=True)
    p.add_argument("--instance-root",type=Path,required=True)
    p.add_argument("--checker-report",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--index",type=Path)
    a=p.parse_args()
    cases={}
    if a.index and a.index.is_file():
        raw=json.loads(a.index.read_text(encoding="utf-8")); cases=raw.get("cases",raw) if isinstance(raw,dict) else {}
    checked={}
    for line in a.checker_report.read_text(encoding="utf-8").splitlines():
        item=json.loads(line); checked[item["paper_id"]]=item
    rows=[]; gaps=[]
    for pid in sorted(checked):
        prior=checked[pid]; candidate=a.candidate_root/pid/"solution.json"
        if prior.get("outcome") != "feasible":
            rows.append({"paper_id":pid,"outcome":prior.get("outcome"),"error":prior.get("error")}); continue
        refs=sorted((a.instance_root/pid/"gurobi_solution").glob("large_solution_*.json"))
        ref=refs[0] if refs else None
        co,ro=objective(candidate),objective(ref) if ref else None
        row={"paper_id":pid,"outcome":"feasible","candidate_objective":co,"reference_objective":ro,"gap":None}
        case=cases.get(pid,{}) if isinstance(cases,dict) else {}
        if co is not None and ro not in (None,0):
            direction=case.get("objective_direction","minimize") if isinstance(case,dict) else "minimize"
            row["gap"]=(co-ro)/abs(ro) if direction!="maximize" else (ro-co)/abs(ro)
            gaps.append(row["gap"])
        rows.append(row)
    summary={"count":len(rows),"gap_count":len(gaps),"average_gap":sum(gaps)/len(gaps) if gaps else None,"rows":rows}
    a.output.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:summary[k] for k in ("count","gap_count","average_gap")},ensure_ascii=False))

if __name__=="__main__": main()
