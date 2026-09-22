#!/usr/bin/env python3
"""
excerpt.py - bounded window into one turn of one session.

Session transcripts run from ~100k to over 1M tokens. Never read one directly.
This prints only the requested turn: the user's prompt in full, then each
assistant step as a compact line (thinking size, text head, tool name + target,
tool result status with a truncated error body).

Usage
  python excerpt.py --run-dir DIR --ref 3/12 [--ref 5/0 ...]
  python excerpt.py --run-dir DIR --session <session-id> --turn 12
  python excerpt.py --run-dir DIR --ref 3/12 --context 1     # also the turns either side
  python excerpt.py --run-dir DIR --ref 3/12 --max-chars 12000

Refs are `<session#>/<turn#>` as printed in the slice files. Total output is
capped (default 8000 chars across all refs) so a single call can never blow the
context window.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import inventory as inv_mod

TOOL_TARGET_CHARS = 160
ERROR_BODY_CHARS = 400
RESULT_HEAD_CHARS = 0  # successful results are summarized by size only


def load_inventory(run_dir: Path):
    p = run_dir / "inventory.json"
    if not p.is_file():
        sys.exit(f"no inventory.json in {run_dir}")
    return json.loads(p.read_text(encoding="utf-8"))


def resolve(inv, ref):
    """ref -> (index, session dict, turn index)"""
    try:
        sn, tn = ref.split("/")
        sn, tn = int(sn), int(tn)
    except Exception:
        sys.exit(f"bad --ref {ref!r}; expected <session#>/<turn#>")
    if sn < 0 or sn >= len(inv["sessions"]):
        sys.exit(f"session #{sn} out of range (0..{len(inv['sessions']) - 1})")
    return sn, inv["sessions"][sn], tn


def by_session_id(inv, sid, turn):
    for n, s in enumerate(inv["sessions"]):
        if s["session_id"] == sid or s["session_id"].startswith(sid):
            return n, s, turn
    sys.exit(f"session id {sid!r} not in this run")


def render(sn, sess, turn_idx, context, budget):
    """Return list of lines for one turn window, staying inside budget chars."""
    path = Path(sess["path"])
    if not path.is_file():
        return [f"[{sn}/{turn_idx}] transcript missing: {path}"]
    meta = {"path": str(path), "tool": sess["tool"], "session_id": sess["session_id"],
            "project_slug": sess["project_slug"], "subagent_files": 0}
    events, _ = inv_mod.parse_session(meta)
    capabilities = sess.get("capabilities", {})
    prompt_idx = [i for i, e in enumerate(events) if e["kind"] == "prompt"]
    lo, hi = turn_idx - context, turn_idx + context
    out, used = [], 0

    def emit(line):
        nonlocal used
        if used + len(line) + 1 > budget:
            return False
        out.append(line)
        used += len(line) + 1
        return True

    emit(f"=== [{sn}/{turn_idx}] {sess['tool']} {sess['session_id']} ({sess['project_slug']}) ===")
    emit(f"cwd {sess['cwd']} | branch {sess['git_branch']} | models {sess['models']}")
    for n in range(max(0, lo), min(len(prompt_idx) - 1, hi) + 1):
        i = prompt_idx[n]
        j = prompt_idx[n + 1] if n + 1 < len(prompt_idx) else len(events)
        p = events[i]
        marker = ">>>" if n == turn_idx else "---"
        if not emit(""):
            break
        if not emit(f"{marker} turn {n} @ {inv_mod.iso(p['ts'])}"):
            break
        if not emit("USER: " + inv_mod.short(p["text"], 1600)):
            break
        results = {e["tool_use_id"]: e for e in events[i:j] if e["kind"] == "tool_result"}
        for e in events[i + 1:j]:
            if e["kind"] == "interrupt":
                emit("  [interrupted by user]")
                continue
            if e["kind"] == "turn_error":
                emit(f"  [agent turn failed: {inv_mod.short(e['error'], ERROR_BODY_CHARS)}]")
                continue
            if e["kind"] != "assistant":
                continue
            # several records share one message id; only the first carries usage
            if e.get("first_of_msg", True):
                bits = []
                if e["thinking_chars"]:
                    bits.append(f"thinking {e['thinking_chars']}c")
                bits.append(f"out {e['out']}tok" if capabilities.get("usage", True) else "token use unavailable")
                if e.get("effort"):
                    bits.append(f"effort {e['effort']}")
                if not emit(f"  A {inv_mod.iso(e['ts'])} [{', '.join(bits)}]"):
                    return out
            for tu in e["tool_uses"]:
                r = results.get(tu["id"])
                if not capabilities.get("tool_results", True):
                    status = "result not recorded"
                elif r is None:
                    status = "no result"
                elif r["is_error"]:
                    status = f"ERROR {r['chars']}c"
                else:
                    status = f"ok {r['chars']}c"
                if not emit(f"    TOOL {tu['name']}({inv_mod.short(tu['target'], TOOL_TARGET_CHARS)}) -> {status}"):
                    return out
    if used >= budget - 200:
        out.append(f"[truncated at {budget} chars; narrow the ref or raise --max-chars]")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--ref", action="append", default=[])
    ap.add_argument("--session")
    ap.add_argument("--turn", type=int)
    ap.add_argument("--context", type=int, default=0, help="also show N turns either side")
    ap.add_argument("--max-chars", type=int, default=8000, help="hard cap on total output")
    a = ap.parse_args(argv)

    run_dir = Path(a.run_dir)
    inv = load_inventory(run_dir)
    targets = [resolve(inv, r) for r in a.ref]
    if a.session is not None:
        if a.turn is None:
            sys.exit("--session needs --turn")
        targets.append(by_session_id(inv, a.session, a.turn))
    if not targets:
        sys.exit("give at least one --ref or --session/--turn")

    per = max(1200, a.max_chars // len(targets))
    for sn, sess, tn in targets:
        print("\n".join(render(sn, sess, tn, a.context, per)))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
