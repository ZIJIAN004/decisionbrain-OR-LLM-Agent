#!/bin/sh
# Verify the sandbox actually holds, by replaying what the agent really did.
#
# The escape commands in section 1 are copied verbatim from the tool transcript
# of the delage2022 run (or-llm-agent-runs/delage2022-test.json, calls
# 3/5/6/9/10/11): outside the sandbox every one of them returned data, and call
# 10 returned the reference objective. Inside it they must return nothing --
# except the task's own instance, which must still be there.
#
# Exit code 0 means every check passed. Anything else means do not rely on it.

set -u

PY=/home/bhz/miniforge3/envs/decisionbrain_baseline/bin/python
ENV_DIR=/home/bhz/miniforge3/envs/decisionbrain_baseline
WS=${WS:-/tmp/sbx-verify/agent}
FAIL=0

mkdir -p "$WS"
echo '{"machine_length": 100, "cost_setup_pattern": 1}' > "$WS/instance.json"

# Gurobi's licence is issued to a user name and resolved with
# getpwuid(geteuid()). With no /etc/passwd in the sandbox the lookup returns
# nothing and the licence is refused ("current user is ''"). Bind a passwd
# holding this user's line only, rather than the host's full user list.
SBX=$(dirname "$WS")/etc
mkdir -p "$SBX"
getent passwd "$(id -u)" > "$SBX/passwd"
getent group  "$(id -g)" > "$SBX/group"

# Ubuntu 24.04 is merged-usr: /bin /lib /lib64 /sbin are symlinks into /usr,
# so bind /usr once and recreate the symlinks rather than binding each.
box() {
    bwrap \
        --ro-bind /usr /usr \
        --symlink usr/bin /bin --symlink usr/sbin /sbin \
        --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
        --ro-bind "$SBX/passwd" /etc/passwd \
        --ro-bind "$SBX/group" /etc/group \
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

# --- 1. the fence: replayed escapes ------------------------------------------
say ''
say '[1] replayed escape attempts'
empty() {
    out=$(box /bin/sh -c "$2" 2>&1)
    if [ -z "$out" ]; then pass "$1"; else bad "$1 -> $(printf '%s' "$out" | head -3 | tr '\n' '|')"; fi
}
only() {
    out=$(box /bin/sh -c "$3" 2>&1 | tr '\n' ' ' | sed 's/ *$//')
    if [ "$out" = "$2" ]; then pass "$1"; else bad "$1 -> $out"; fi
}

# The task's own instance must survive: a fence that hides it too is useless.
# Outside the sandbox this command returns all 65 cases plus the answer tree.
only 'find / for instance json (call 3)' '/work/instance.json' \
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
empty 'earlier runs of this baseline' \
      'ls /home/bhz/baselines/or-llm-agent-runs/ 2>/dev/null'
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
out=$(box /bin/sh -c 'id -un 2>&1')
[ "$out" = "$(id -un)" ] && pass "runs as $out" || bad "identity inside is '$out', expected '$(id -un)'"

out=$(box "$PY" -c "import json;print(json.load(open('instance.json'))['machine_length'])" 2>&1 | tail -1)
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
# Deliberately writes only canaries, never deletes: if the mount table were
# wrong, a delete here would destroy the very data this is meant to protect.
box /bin/sh -c 'touch /home/bhz/CANARY /usr/CANARY /home/bhz/gurobi1302/CANARY 2>/dev/null' >/dev/null 2>&1
leaked=""
for canary in /home/bhz/CANARY /usr/CANARY /home/bhz/gurobi1302/CANARY; do
    [ -e "$canary" ] && leaked="$leaked $canary"
done
if [ -z "$leaked" ]; then
    pass 'writes to ro-bound and unmounted paths did not reach the host'
else
    bad "HOST WAS MODIFIED at:$leaked -- do not use this mount table"
    rm -f $leaked
fi

say ''
if [ "$FAIL" -eq 0 ]; then say "ALL CHECKS PASSED"; else say "$FAIL CHECK(S) FAILED"; fi
exit "$FAIL"
