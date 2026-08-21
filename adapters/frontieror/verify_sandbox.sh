#!/bin/sh
# Verify the sandbox actually holds, by replaying what the agent really did.
#
# The escape commands below are copied verbatim from the tool transcript of the
# delage2022 run (or-llm-agent-runs/delage2022-test.json, calls 3/5/6/9/10/11):
# outside the sandbox every one of them returned data, and call 10 returned the
# reference objective. Inside it they must all return nothing.
#
# Exit code 0 means every check passed. Anything else means do not rely on it.

set -u

PY=/home/bhz/miniforge3/envs/decisionbrain_baseline/bin/python
ENV_DIR=/home/bhz/miniforge3/envs/decisionbrain_baseline
WS=${WS:-/tmp/sbx-verify/agent}
FAIL=0

mkdir -p "$WS"
echo '{"machine_length": 100, "cost_setup_pattern": 1}' > "$WS/instance.json"

# Ubuntu 24.04 is merged-usr: /bin /lib /lib64 /sbin are symlinks into /usr,
# so bind /usr once and recreate the symlinks rather than binding each.
box() {
    bwrap \
        --ro-bind /usr /usr \
        --symlink usr/bin /bin --symlink usr/sbin /sbin \
        --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
        --ro-bind /etc/resolv.conf /etc/resolv.conf \
        --ro-bind /etc/ssl /etc/ssl \
        --ro-bind-try /etc/ca-certificates /etc/ca-certificates \
        --ro-bind "$ENV_DIR" "$ENV_DIR" \
        --ro-bind /home/bhz/gurobi1302 /home/bhz/gurobi1302 \
        --ro-bind /home/bhz/gurobi.lic /home/bhz/gurobi.lic \
        --bind "$WS" /work \
        --tmpfs /tmp --proc /proc --dev /dev \
        --unshare-pid --unshare-ipc --unshare-uts \
        --die-with-parent --new-session \
        --chdir /work \
        -- "$@"
}

say()  { printf '%s\n' "$*"; }
pass() { printf '  PASS  %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; FAIL=$((FAIL+1)); }

# --- 0. does it start at all -------------------------------------------------
say ''
say '[0] bwrap starts'
if out=$(box /bin/sh -c 'echo alive' 2>&1) && [ "$out" = alive ]; then
    pass 'bwrap runs a command'
else
    bad "bwrap will not start: $out"
    say ''
    say 'STOP. Unprivileged user namespaces are probably blocked'
    say '(kernel.apparmor_restrict_unprivileged_userns=1). Use Landlock instead.'
    exit 2
fi

# --- 1. the fence: replayed escapes must return nothing -----------------------
say ''
say '[1] replayed escape attempts (must all be empty)'
empty() {
    label=$1; shift
    out=$(box /bin/sh -c "$1" 2>&1)
    if [ -z "$out" ]; then pass "$label"; else bad "$label -> $(printf '%s' "$out" | head -3 | tr '\n' '|')"; fi
}
empty 'find / for instance json (transcript call 3)' \
      'find / -name "*.json" -path "*instance*" 2>/dev/null'
empty 'find /home/bhz for delage (call 5)' \
      'find /home/bhz -iname "*delage*" 2>/dev/null'
empty 'ls the answer directory (call 6)' \
      'ls /home/bhz/FrontierOR_all/delage2022/ 2>/dev/null'
empty 'cat the hidden checker (call 9)' \
      'cat "/home/bhz/Decision Brain/benchmarks/frontieror/delage2022/hidden/feasibility_check.py" 2>/dev/null'
empty 'cat the reference solution (call 10)' \
      'cat /home/bhz/FrontierOR_all/delage2022/gurobi_solution/large_solution_3.json 2>/dev/null'
empty 'cat the reference gurobi code' \
      'cat "/home/bhz/Decision Brain/benchmarks/frontieror/knueven2020/hidden/gurobi_code.py" 2>/dev/null'
empty 'the other tree (call 11)' \
      'ls /home/bhz/FrontierOR_large/ 2>/dev/null'
empty 'the sibling baseline artifacts' \
      'ls /home/bhz/baselines/OptiMUS-v2/data/frontieror/ 2>/dev/null'
empty 'python open(), not just shell' \
      "$PY -c \"print(open('/home/bhz/FrontierOR_all/delage2022/gurobi_solution/large_solution_3.json').read())\" 2>/dev/null"

# --- 2. no route back out ----------------------------------------------------
say ''
say '[2] no route back out'
out=$(box /bin/sh -c 'ls / 2>&1' | tr '\n' ' ')
case "$out" in
    *FrontierOR*|*Decision*) bad "root listing leaks: $out" ;;
    *) pass "root contains only: $out" ;;
esac
out=$(box /bin/sh -c 'cat /proc/self/mountinfo 2>/dev/null | grep -c FrontierOR')
[ "$out" = 0 ] && pass 'no FrontierOR mount in the namespace' || bad "mountinfo shows $out"

# --- 3. the work still works -------------------------------------------------
say ''
say '[3] the sandbox does not break the task'
out=$(box "$PY" -c "import json;print(json.load(open('instance.json'))['machine_length'])" 2>&1)
[ "$out" = 100 ] && pass 'reads instance.json by relative path' || bad "instance.json: $out"

out=$(box "$PY" -c "
import gurobipy as gp
m = gp.Model('t'); x = m.addVar(ub=3); m.setObjective(x, gp.GRB.MAXIMIZE)
m.setParam('OutputFlag', 0); m.optimize(); print(round(m.objVal))
" 2>&1 | tail -1)
[ "$out" = 3 ] && pass 'gurobipy licenses and solves' || bad "gurobi: $out"

out=$(box "$PY" -c "
import socket; s=socket.create_connection(('api.deepseek.com',443),10); s.close(); print('net')
" 2>&1 | tail -1)
[ "$out" = net ] && pass 'network reaches the LLM endpoint' || bad "network: $out"

box /bin/sh -c 'echo written > out.txt' >/dev/null 2>&1
[ -f "$WS/out.txt" ] && pass 'writes land in the workspace' || bad 'workspace write did not persist'
rm -f "$WS/out.txt"

# --- 4. the host is untouched ------------------------------------------------
say ''
say '[4] the host is untouched'
box /bin/sh -c 'rm -rf /home/bhz/FrontierOR_all 2>/dev/null; touch /home/bhz/CANARY 2>/dev/null' >/dev/null 2>&1
if [ -d /home/bhz/FrontierOR_all ] && [ ! -e /home/bhz/CANARY ]; then
    pass 'a destructive command inside changed nothing outside'
else
    bad 'HOST WAS MODIFIED -- do not use this mount table'
fi

say ''
if [ "$FAIL" -eq 0 ]; then say "ALL CHECKS PASSED"; else say "$FAIL CHECK(S) FAILED"; fi
exit "$FAIL"
