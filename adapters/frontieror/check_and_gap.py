"""Run FrontierOR hidden checkers and compute gaps for OR solutions."""
from __future__ import annotations
import argparse, json, math, subprocess, tempfile
from pathlib import Path

def obj(path: Path):
    try:
        value=json.loads(path.read_text(encoding='utf-8')).get('objective_value')
        return float(value) if isinstance(value,(int,float)) and math.isfinite(float(value)) else None
    except (OSError,ValueError,TypeError): return None

def main():
    p=argparse.ArgumentParser(); p.add_argument('--candidate-root',type=Path,required=True); p.add_argument('--task-root',type=Path,required=True); p.add_argument('--instance-root',type=Path,required=True); p.add_argument('--index',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--timeout',type=int,default=120)
    a=p.parse_args(); index=json.loads(a.index.read_text()); cases=index.get('cases',index); rows=[]; gaps=[]
    for pid,case in sorted(cases.items()):
        c=a.candidate_root/pid/'solution.json'; task=a.task_root/pid; idx=case.get('instance_index') if isinstance(case,dict) else None; inst=a.instance_root/pid/f'large_instance_{idx}.json' if idx is not None else None; checker=task/'hidden'/'feasibility_check.py'; ref= a.instance_root/pid/'gurobi_solution'/f'large_solution_{idx}.json' if idx is not None else None
        if not c.is_file(): rows.append({'paper_id':pid,'outcome':'missing_candidate'}); continue
        if not inst or not inst.is_file(): rows.append({'paper_id':pid,'outcome':'checker_execution_error','error':'instance missing'}); continue
        with tempfile.TemporaryDirectory(prefix='or-frontieror-check-') as td:
            result=Path(td)/'result.json'; cmd=['python3',str(checker),'--instance_path',str(inst),'--solution_path',str(c),'--result_path',str(result)]
            try: proc=subprocess.run(cmd,capture_output=True,text=True,timeout=a.timeout,check=False)
            except subprocess.TimeoutExpired: rows.append({'paper_id':pid,'outcome':'checker_timeout'}); continue
            if proc.returncode!=0 or not result.is_file(): rows.append({'paper_id':pid,'outcome':'checker_execution_error','stderr':proc.stderr[-1000:]}); continue
            check=json.loads(result.read_text()); feasible=check.get('feasible') is True; row={'paper_id':pid,'outcome':'feasible' if feasible else 'infeasible','checker_result':check}
            co,ro=obj(c),obj(ref) if ref else None; row.update(candidate_objective=co,reference_objective=ro,gap=None)
            if feasible and co is not None and ro not in (None,0):
                direction=case.get('objective_direction','minimize'); row['gap']=((co-ro)/abs(ro)) if direction!='maximize' else ((ro-co)/abs(ro)); gaps.append(row['gap'])
            rows.append(row)
    summary={'count':len(rows),'gap_count':len(gaps),'average_gap':sum(gaps)/len(gaps) if gaps else None,'rows':rows}; a.output.write_text(json.dumps(summary,ensure_ascii=False,indent=2)); print(json.dumps({k:summary[k] for k in ('count','gap_count','average_gap')}))

if __name__=='__main__': main()
