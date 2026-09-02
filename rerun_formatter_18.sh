#!/usr/bin/env bash
#
# 重跑 18 个受旧版 result adapter 影响的失败实例的「结果转换」环节。
#
# 背景
# ----
# commit 8453ff0 (2026-08-24 14:37) 之前，result adapter 让 formatter LLM 直接手写
# solution.json；之后改为强制写 convert_solution.py 并执行，从 raw_candidate.json
# 程序化提取。主跑 20260823-091234Z 在该 commit 之前，用的是旧版。
#
# 旧版会「安静地抄错」：result_adapter.json 记 status=formatted / schema_valid=true，
# 但解本身是空的、字段错的或抄漏的。schema_valid 之所以恒真，是因为
# solution_schema.json 是字段描述字典而非 JSON Schema，jsonschema.validate 对
# 未知关键字一律不校验（result_adapter.py:136）。因此这类实例从未触发过任何重试。
#
# 已抽样核实：从 raw_candidate.json 的原始变量重建业务解后跑官方 hidden checker，
# 12 个里 11 个实际可行（唯一例外 huisman2005 是真建模缺陷，solver.py:373-398 在没有
# 覆盖列时静默跳过车-乘务衔接约束）。所以现有 41/65 是被低估的下界。
#
# 范围
# ----
# 只跑「当前不可行 + 旧版 formatter + 有候选解」的实例。判据是 workspace 里有没有
# convert_solution.py（新版必然产出该文件），不靠运行记录推断。
#
#   剔除 barnhart2000 / bertsimas2024 / rahmaniani2020：budget-control 重跑时求解器和
#     formatter 都是新版，不存在转换问题。
#   剔除 castro2021 / knueven2020 / levin2017 / taninmis2022：没有 raw_candidate.json，
#     无解可转。
#   剔除 41 个已 feasible 的：转换出错只会让实例失败，不会把不可行变可行。
#     （代价是这些实例的 gap 可能仍失真，那是另一个指标的问题。）
#
# 不重跑求解器。raw_candidate.json 原样保留，只重做变量 -> 业务解这一步。
#
# 跑完之后还要重跑 hidden checker 才能拿到修正后的可行率。
#
set -euo pipefail

RUN=${RUN:-/home/bhz/baselines/or-llm-agent-runs/20260823-091234Z}
OUT=${OUT:-/home/bhz/baselines/or-llm-agent-runs/formatter-rerun-$(date -u +%Y%m%d-%H%M%S)Z}
REPO=${REPO:-/home/bhz/baselines/OR-LLM-Agent}
PY=${PY:-/home/bhz/miniforge3/envs/decisionbrain_baseline/bin/python}
MODEL=${MODEL:-deepseek-v4-flash}
JOBS=${JOBS:-6}
TIMEOUT=${TIMEOUT:-1200}

IDS="bertsimas2022 bierwirth2017 bollapragada2001 bragin2022 bront2009 byeon2022 \
carvalho1999 earl2005 freling2003 gualandi2012 huisman2005 kobayashi2021 \
laporte2003 roberti2015 rostami2021 wangk2020 zetina2019 zhang2025"

if [ ! -d "$RUN/workspaces" ]; then
    echo "workspaces not found: $RUN/workspaces" >&2
    exit 1
fi

mkdir -p "$OUT"
echo "[$(date -Is)] run=$RUN"
echo "[$(date -Is)] out=$OUT"
echo "[$(date -Is)] instances=$(echo $IDS | wc -w)"

# 1) 备份会被原地覆盖的产物。
#    adapt() 会重写 solution.json / solution_schema.json / result_adapter.json，
#    不备份就再也复现不出原始 41/65 那组数。
echo "[$(date -Is)] backing up pre-rerun artifacts"
cd "$RUN"
find workspaces -maxdepth 2 \
     \( -name 'solution*.json' -o -name 'result_adapter.json' \
        -o -name 'convert_solution.py' -o -name 'solution_compact.txt' \) -print0 \
  | tar czf "$OUT/pre-rerun-artifacts.tgz" --null -T -
echo "[$(date -Is)] backup written: $(du -h "$OUT/pre-rerun-artifacts.tgz" | cut -f1)"

# 2) 重跑 formatter。
#    ADAPTER_WORKSPACE_ROOT 必须设：adapt() 用的是 config.WORKSPACE_ROOT / paper_id，
#    不接受 workspace 参数，默认会指向 or-llm-agent-runs/workspaces（另一个旧目录）。
#    --only 也是必须的：retry_adapters 的默认选择逻辑是「没有 solution.json 才重试」，
#    而这 18 个都有 solution.json，只是内容错的，所以当初一个都没被选中。
export ADAPTER_WORKSPACE_ROOT="$RUN/workspaces"
cd "$REPO"
echo "[$(date -Is)] starting formatter rerun"
"$PY" -m adapters.frontieror.retry_adapters \
  --repo "$REPO" \
  --workspace-root "$RUN/workspaces" \
  --output-root "$OUT" \
  --model "$MODEL" \
  --jobs "$JOBS" \
  --timeout "$TIMEOUT" \
  --only $IDS

echo "[$(date -Is)] formatter rerun finished"
echo
echo "下一步：重跑 hidden checker 得到修正后的可行率，再重做配对统计。"
echo "本次输出：$OUT/report.jsonl"
