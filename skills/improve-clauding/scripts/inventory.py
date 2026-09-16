#!/usr/bin/env python3
"""
inventory.py - deterministic pre-pass for the improve-clauding retro.

Discovers agent session transcripts (Claude Code + Cursor), selects the ones
not yet covered by a previous retro, extracts per-session metrics and
mechanical friction/success signals, and writes:

  <run-dir>/inventory.json   full machine-readable record (nobody reads it whole)
  <run-dir>/summary.md       small shared digest: totals + session table
  <run-dir>/slice-a-communication.md   per-lens-group slices, disjoint, bounded
  <run-dir>/slice-b-orchestration.md
  <run-dir>/slice-c-correctness.md
  <run-dir>/slice-d-endorsement.md

Each analyst reads summary.md + its own slice. Nothing reads a raw transcript;
use excerpt.py for bounded windows around a flagged turn.

The script never classifies. It only measures and flags. Stdlib only.

Usage
  python inventory.py                     # sessions since last retro
  python inventory.py --last 10           # last 10 sessions (by mtime)
  python inventory.py --since 2026-09-01  # sessions modified on/after date
  python inventory.py --all
  python inventory.py --status            # show state, exit
  python inventory.py --commit --report PATH   # record a finished retro
  python inventory.py --previous          # print path of previous report

Options
  --home DIR          override state/report home (default ~/.improve-clauding)
  --roots DIR ...     extra transcript roots (dirs scanned recursively)
  --min-turns N       skip sessions with fewer human turns (default 2)
  --no-git            skip git correlation
  --quiet
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

HOME = Path.home()
DEFAULT_APP_HOME = HOME / ".improve-clauding"
CLAUDE_PROJECTS = HOME / ".claude" / "projects"
CURSOR_PROJECTS = HOME / ".cursor" / "projects"

READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch", "ToolSearch", "NotebookRead"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace"}
DELEGATE_TOOLS = {"Agent", "Task", "Workflow", "SendMessage"}
SHELL_TOOLS = {"Bash", "PowerShell", "Shell"}

CORRECTION_RE = re.compile(
    r"\b(no[,.!]|nope|wrong|not what i|that'?s not|don'?t|do not|stop|undo|revert|instead|"
    r"i said|i told you|again[.!?]|try again|once more|still (doesn'?t|does not|not|broken|fail\w*|wrong)|actually|"
    r"you (ignored|missed|broke)|why did you|not like that|"
    r"this is (bullshit|nonsense|wrong)|bullshit|wtf|ffs|ridiculous|seriously\?)",
    re.I,
)
FRUSTRATION_RE = re.compile(
    r"\b(bullshit|wtf|ffs|damn|jesus|ridiculous|are you (kidding|serious)|i told you|how many times|"
    r"for the last time|useless|garbage)\b|!{2,}|\?{2,}",
    re.I,
)
NUDGE_RE = re.compile(r"^\s*(y|yes|ok|okay|go|go on|go ahead|continue|proceed|next|do it|sure|yep|please continue|carry on|k)\s*[.!]?\s*$", re.I)
PRAISE_RE = re.compile(r"\b(perfect|great|excellent|nice|good job|well done|exactly|that'?s it|works|thanks|thank you|love it)\b", re.I)
PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\.{0,2}/|\b)[\w\-. ]+[\\/][\w\-. \\/]+\.\w{1,6}\b|\b\w[\w\-]*\.(?:cpp|h|hpp|py|ts|tsx|js|mjs|md|json|yaml|yml|cmake|txt|qml|ui|toml)\b")
ERROR_RE = re.compile(r"\b(error|exception|traceback|failed|failure|assert|segfault|crash|undefined reference|LNK\d{4}|C\d{4}:)\b", re.I)
CRITERIA_RE = re.compile(r"\b(should|must|expect(ed|s)?|verify|make sure|ensure|until|done when|acceptance|test(s)? pass|passes|criteria)\b", re.I)
INTENT_RE = re.compile(r"\b(i want|i need|goal|so that|because|the point is|purpose|we should|let'?s|implement|fix|add|remove|refactor|investigate|review|explain|why|how)\b", re.I)
INTERRUPT_RE = re.compile(r"\[Request interrupted by user", re.I)
SLASH_RE = re.compile(r"<command-name>\s*(/[\w:.\-]+)\s*</command-name>")
INJECTED_TAG_RE = re.compile(
    r"<(ide_opened_file|ide_selection|system-reminder|local-command-stdout|local-command-stderr|command-message|command-args|"
    r"task-notification|attached_files|system_notification)>.*?</\1>\s*",
    re.S | re.I,
)
GIT_COMMIT_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?commit\b")
NO_VERIFY_RE = re.compile(r"--no-verify\b")
FORCE_PUSH_RE = re.compile(r"\bgit\s+push\b[^\n]*\s(--force|-f)\b")


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def parse_ts(v):
    """Return aware UTC datetime from ISO string or epoch (s or ms)."""
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            if v > 1e12:
                v = v / 1000.0
            return dt.datetime.fromtimestamp(v, tz=dt.timezone.utc)
        s = str(v).strip()
        if s.isdigit():
            return parse_ts(int(s))
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception:
        return None


def iso(d):
    return d.isoformat(timespec="seconds") if d else None


def mtime(p: Path):
    return dt.datetime.fromtimestamp(p.stat().st_mtime, tz=dt.timezone.utc)


def short(s, n=220):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "\u2026"


def sha(s):
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:10]


def text_of(content):
    """Flatten message content (str or block list) to (text, blocks)."""
    if isinstance(content, str):
        return content, []
    if isinstance(content, list):
        parts, blocks = [], []
        for b in content:
            if isinstance(b, dict):
                blocks.append(b)
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(parts), blocks
    return "", []


def prompt_quality(text):
    """Cheap, transparent heuristics. Returns dict of booleans + score 0-5."""
    t = text or ""
    q = {
        "has_path": bool(PATH_RE.search(t)),
        "has_error_text": bool(ERROR_RE.search(t)),
        "has_code": "```" in t or bool(re.search(r"`[^`\n]{3,}`", t)),
        "has_criteria": bool(CRITERIA_RE.search(t)),
        "has_intent": bool(INTENT_RE.search(t)),
        "length": len(t),
    }
    score = sum([q["has_path"], q["has_error_text"] or q["has_code"], q["has_criteria"], q["has_intent"], q["length"] >= 80])
    q["score"] = score
    return q


def similarity(a, b):
    """Jaccard over word sets; good enough to flag near-repeat prompts."""
    wa, wb = set(re.findall(r"\w+", a.lower())), set(re.findall(r"\w+", b.lower()))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


# ----------------------------------------------------------------------------
# discovery
# ----------------------------------------------------------------------------

def discover_claude():
    out = []
    if not CLAUDE_PROJECTS.is_dir():
        return out
    for proj in CLAUDE_PROJECTS.iterdir():
        if not proj.is_dir():
            continue
        for f in proj.glob("*.jsonl"):
            sid = f.stem
            sub_dir = proj / sid / "subagents"
            n_sub = len(list(sub_dir.rglob("*.jsonl"))) if sub_dir.is_dir() else 0
            out.append({"tool": "claude", "path": str(f), "session_id": sid, "project_slug": proj.name, "subagent_files": n_sub})
    return out


def discover_cursor():
    out = []
    if not CURSOR_PROJECTS.is_dir():
        return out
    for proj in CURSOR_PROJECTS.iterdir():
        tdir = proj / "agent-transcripts"
        if not tdir.is_dir():
            continue
        for f in tdir.glob("*.jsonl"):
            out.append({"tool": "cursor", "path": str(f), "session_id": f.stem, "project_slug": proj.name, "subagent_files": 0})
    return out


def discover_extra(roots):
    out = []
    for r in roots or []:
        for f in Path(r).rglob("*.jsonl"):
            if "subagents" in f.parts:
                continue
            out.append({"tool": "unknown", "path": str(f), "session_id": f.stem, "project_slug": f.parent.name, "subagent_files": 0})
    return out


# ----------------------------------------------------------------------------
# parsing
# ----------------------------------------------------------------------------

def is_human_prompt(rec, text, blocks):
    if rec.get("isMeta"):
        return False
    if rec.get("isSidechain"):
        return False
    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return False
    if any(b.get("type") == "tool_result" for b in blocks):
        return False
    if isinstance(rec.get("message", {}).get("content"), str):
        s = text.lstrip()
        if s.startswith("<") and not SLASH_RE.search(s):
            return False  # system-injected (<local-command-stdout>, <system-reminder>, ...)
    if not text.strip():
        return False
    return True


def parse_session(meta):
    """Parse one transcript into a normalized event list, tolerant of both
    Claude Code and (unverified) Cursor shapes."""
    path = Path(meta["path"])
    events = []  # dicts: kind, ts, ...
    # One API message is written as several JSONL records (one per content block),
    # each repeating the full usage. Count usage once per message id.
    seen_msg_ids = set()
    misc = {"titles": [], "modes": Counter(), "permission_modes": Counter(), "cost_state": None,
            "version": None, "entrypoint": None, "cwd": None, "git_branch": None, "models": Counter(),
            "efforts": Counter(), "skills_attributed": Counter(), "compactions": 0, "hook_errors": 0,
            "denials": Counter(), "refusals": 0, "system_subtypes": Counter(), "turn_durations_ms": [],
            "bad_lines": 0, "lines": 0}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            misc["lines"] += 1
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                misc["bad_lines"] += 1
                continue
            if not isinstance(rec, dict):
                continue
            t = rec.get("type") or rec.get("role")
            ts = parse_ts(rec.get("timestamp") or rec.get("createdAt") or rec.get("ts") or rec.get("time"))
            for k in ("cwd", "version", "entrypoint"):
                if rec.get(k) and not misc.get(k):
                    misc[k] = rec.get(k)
            if rec.get("gitBranch") and not misc["git_branch"]:
                misc["git_branch"] = rec.get("gitBranch")
            if rec.get("attributionSkill"):
                misc["skills_attributed"][rec["attributionSkill"]] += 1
            if rec.get("isCompactSummary") or t in ("summary", "compact_boundary"):
                misc["compactions"] += 1
            if rec.get("toolDenialKind"):
                misc["denials"][rec["toolDenialKind"]] += 1
            if rec.get("effort"):
                misc["efforts"][str(rec["effort"])] += 1

            if t in ("custom-title", "ai-title"):
                title = rec.get("customTitle") or rec.get("aiTitle")
                if title:
                    misc["titles"].append((t, title))
                continue
            if t == "mode":
                misc["modes"][str(rec.get("mode"))] += 1
                continue
            if t == "permission-mode":
                misc["permission_modes"][str(rec.get("permissionMode"))] += 1
                continue
            if t == "cost-state":
                misc["cost_state"] = rec
                continue
            if t == "system":
                st = rec.get("subtype")
                misc["system_subtypes"][st] += 1
                if st == "turn_duration" and isinstance(rec.get("durationMs"), (int, float)):
                    misc["turn_durations_ms"].append(rec["durationMs"])
                if rec.get("hookErrors"):
                    misc["hook_errors"] += len(rec["hookErrors"])
                if st and "refusal" in st:
                    misc["refusals"] += 1
                if st and "compact" in st:
                    misc["compactions"] += 1
                continue

            msg = rec.get("message") if isinstance(rec.get("message"), dict) else rec
            role = msg.get("role") or t
            content = msg.get("content")
            if content is None and "text" in rec:
                content = rec.get("text")
            text, blocks = text_of(content)

            if role == "user" or t == "user":
                if rec.get("permissionMode"):
                    misc["permission_modes"][str(rec["permissionMode"])] += 1
                tool_results = [b for b in blocks if b.get("type") == "tool_result"]
                if tool_results:
                    for b in tool_results:
                        rtxt, _ = text_of(b.get("content"))
                        events.append({"kind": "tool_result", "ts": ts, "tool_use_id": b.get("tool_use_id"),
                                       "is_error": bool(b.get("is_error")), "chars": len(rtxt),
                                       "sidechain": bool(rec.get("isSidechain"))})
                    continue
                if INTERRUPT_RE.search(text):
                    events.append({"kind": "interrupt", "ts": ts})
                    continue
                m = SLASH_RE.search(text)
                if m:
                    events.append({"kind": "slash", "ts": ts, "command": m.group(1)})
                    continue
                text = INJECTED_TAG_RE.sub("", text)
                if is_human_prompt(rec, text, blocks):
                    events.append({"kind": "prompt", "ts": ts, "text": text, "uuid": rec.get("uuid"),
                                   "has_image": any(b.get("type") in ("image", "document") for b in blocks)})
                continue

            if role == "assistant" or t == "assistant":
                if msg.get("model"):
                    misc["models"][msg["model"]] += 1
                mid = msg.get("id")
                first_of_msg = mid is None or mid not in seen_msg_ids
                if mid is not None:
                    seen_msg_ids.add(mid)
                usage = msg.get("usage") if (first_of_msg and isinstance(msg.get("usage"), dict)) else {}
                thinking_chars = sum(len(b.get("thinking", "") or "") for b in blocks if b.get("type") == "thinking")
                text_chars = sum(len(b.get("text", "") or "") for b in blocks if b.get("type") == "text")
                tool_uses = []
                for b in blocks:
                    if b.get("type") == "tool_use":
                        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                        target = inp.get("file_path") or inp.get("path") or inp.get("pattern") or inp.get("command") or inp.get("url") or inp.get("skill") or inp.get("description") or ""
                        tool_uses.append({"id": b.get("id"), "name": b.get("name"), "target": short(str(target), 200),
                                          "input_hash": sha(json.dumps(inp, sort_keys=True, default=str))})
                events.append({"kind": "assistant", "ts": ts, "model": msg.get("model"),
                               "in": usage.get("input_tokens", 0) or 0,
                               "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
                               "cache_create": usage.get("cache_creation_input_tokens", 0) or 0,
                               "out": usage.get("output_tokens", 0) or 0,
                               "thinking_chars": thinking_chars, "text_chars": text_chars,
                               "tool_uses": tool_uses, "stop_reason": msg.get("stop_reason"),
                               "sidechain": bool(rec.get("isSidechain")), "effort": rec.get("effort"),
                               "msg_id": mid, "first_of_msg": first_of_msg})
                continue
    return events, misc


# ----------------------------------------------------------------------------
# analysis
# ----------------------------------------------------------------------------

def analyze(meta, events, misc, now):
    prompts = [e for e in events if e["kind"] == "prompt"]
    assistants = [e for e in events if e["kind"] == "assistant" and not e.get("sidechain") and e.get("first_of_msg", True)]
    results = [e for e in events if e["kind"] == "tool_result"]
    result_by_id = {r["tool_use_id"]: r for r in results if r.get("tool_use_id")}
    tss = sorted(e["ts"] for e in events if e.get("ts"))
    start, end = (tss[0], tss[-1]) if tss else (None, None)
    # active duration: sum of inter-event gaps, ignoring idle gaps over 60 min
    active_sec = sum(min((b - a_).total_seconds(), 3600) for a_, b in zip(tss, tss[1:]) if (b - a_).total_seconds() < 3600)

    # ---- turns: each human prompt owns everything until the next human prompt
    turns = []
    idx_prompt = [i for i, e in enumerate(events) if e["kind"] == "prompt"]
    for n, i in enumerate(idx_prompt):
        j = idx_prompt[n + 1] if n + 1 < len(idx_prompt) else len(events)
        seg = events[i + 1: j]
        p = events[i]
        tools = Counter()
        targets = Counter()
        errors = 0
        err_tools = Counter()
        tok_in = tok_out = cache_r = cache_c = 0
        thinking = 0
        single_ro_seq = 0  # consecutive assistant turns with exactly one read-only tool
        prev_single_ro = False
        delegations = 0
        edits = Counter()
        commits = 0
        no_verify = 0
        force_push = 0
        skills = Counter()
        plan_mode = 0
        interrupts = 0
        slashes = []
        last_assistant_ts = None
        for e in seg:
            if e["kind"] == "assistant":
                last_assistant_ts = e["ts"] or last_assistant_ts
                tok_in += e["in"]; tok_out += e["out"]; cache_r += e["cache_read"]; cache_c += e["cache_create"]
                thinking += e["thinking_chars"]
                names = [tu["name"] for tu in e["tool_uses"]]
                for tu in e["tool_uses"]:
                    tools[tu["name"]] += 1
                    if tu["name"] in READ_ONLY_TOOLS | EDIT_TOOLS:
                        targets[(tu["name"], tu["target"])] += 1
                    if tu["name"] in EDIT_TOOLS:
                        edits[tu["target"]] += 1
                    if tu["name"] in DELEGATE_TOOLS:
                        delegations += 1
                    if tu["name"] == "Skill":
                        skills[tu["target"]] += 1
                    if tu["name"] in ("EnterPlanMode", "ExitPlanMode"):
                        plan_mode += 1
                    if tu["name"] in SHELL_TOOLS:
                        cmd = tu["target"]
                        if GIT_COMMIT_RE.search(cmd):
                            commits += 1
                        if NO_VERIFY_RE.search(cmd):
                            no_verify += 1
                        if FORCE_PUSH_RE.search(cmd):
                            force_push += 1
                    r = result_by_id.get(tu["id"])
                    if r and r["is_error"]:
                        errors += 1
                        err_tools[tu["name"]] += 1
                is_single_ro = len(names) == 1 and names[0] in READ_ONLY_TOOLS
                if is_single_ro and prev_single_ro:
                    single_ro_seq += 1
                prev_single_ro = is_single_ro
            elif e["kind"] == "interrupt":
                interrupts += 1
            elif e["kind"] == "slash":
                slashes.append(e["command"])
        # timing
        next_prompt_ts = events[j]["ts"] if j < len(events) and events[j].get("ts") else None
        agent_seconds = (last_assistant_ts - p["ts"]).total_seconds() if (last_assistant_ts and p["ts"]) else None
        human_wait = (next_prompt_ts - last_assistant_ts).total_seconds() if (next_prompt_ts and last_assistant_ts) else None
        text = p["text"]
        q = prompt_quality(text)
        prev_text = turns[-1]["text_full"] if turns else ""
        sim = similarity(text, prev_text) if prev_text else 0.0
        is_corr = bool(CORRECTION_RE.search(text))
        is_nudge = bool(NUDGE_RE.match(text))
        letters = re.sub(r"[^A-Za-z]", "", text)
        shouting = len(letters) >= 6 and letters.isupper()
        is_frust = bool(FRUSTRATION_RE.search(text)) or shouting
        is_praise = bool(PRAISE_RE.search(text)) and not is_corr
        # zero-information retry: short, near-repeat or correction with no new evidence
        zero_info = (is_corr or sim >= 0.5) and not (q["has_path"] or q["has_error_text"] or q["has_code"]) and q["length"] < 160 and not is_nudge
        re_reads = sum(1 for (nm, tg), c in targets.items() if nm == "Read" and c >= 2)
        churn_files = [tg for tg, c in edits.items() if c >= 3]
        turns.append({
            "i": n, "ts": iso(p["ts"]), "text": short(text, 300), "text_full": text, "chars": len(text),
            "has_image": p.get("has_image", False),
            "flags": {"correction": is_corr, "nudge": is_nudge, "frustration": is_frust, "praise": is_praise,
                      "zero_info_retry": zero_info, "near_repeat": sim >= 0.5, "interrupted": interrupts > 0},
            "quality": q,
            "agent_seconds": round(agent_seconds) if agent_seconds is not None else None,
            "human_wait_seconds": round(human_wait) if human_wait is not None else None,
            "assistant_msgs": sum(1 for e in seg if e["kind"] == "assistant" and e.get("first_of_msg", True)),
            "tools": dict(tools.most_common(12)), "tool_errors": errors, "error_tools": dict(err_tools),
            "re_reads": re_reads, "sequential_readonly_runs": single_ro_seq, "delegations": delegations,
            "edit_churn_files": churn_files[:5], "commits": commits, "no_verify": no_verify, "force_push": force_push,
            "skills": dict(skills), "slash": slashes, "plan_mode_tools": plan_mode,
            "tokens": {"in": tok_in, "out": tok_out, "cache_read": cache_r, "cache_create": cache_c},
            "thinking_chars": thinking,
        })
    for t in turns:
        del t["text_full"]

    # ---- session-level aggregates
    tok = {k: sum(t["tokens"][k] for t in turns) for k in ("in", "out", "cache_read", "cache_create")}
    total_ctx = tok["in"] + tok["cache_read"] + tok["cache_create"]
    cache_ratio = round(tok["cache_read"] / total_ctx, 3) if total_ctx else None
    tool_counter = Counter()
    for t in turns:
        tool_counter.update(t["tools"])
    n_err = sum(t["tool_errors"] for t in turns)
    flags = Counter()
    for t in turns:
        for k, v in t["flags"].items():
            if v:
                flags[k] += 1
    agent_secs = sum(t["agent_seconds"] or 0 for t in turns)
    human_secs = sum(t["human_wait_seconds"] or 0 for t in turns if (t["human_wait_seconds"] or 0) < 3600)
    long_gaps = sum(1 for t in turns if (t["human_wait_seconds"] or 0) >= 1800)
    slash_cmds = Counter(c for t in turns for c in t["slash"])
    skill_tools = Counter()
    for t in turns:
        skill_tools.update(t["skills"])
    plan_used = misc["modes"].get("plan", 0) > 0 or any(t["plan_mode_tools"] for t in turns)
    title = next((v for k, v in misc["titles"] if k == "custom-title"), None) or next((v for k, v in misc["titles"]), None)
    first_prompt = turns[0]["text"] if turns else ""
    cs = misc["cost_state"] or {}
    age_h = (now - end).total_seconds() / 3600 if end else None
    avg_q = round(sum(t["quality"]["score"] for t in turns) / len(turns), 2) if turns else None

    mech = {
        "tool_errors": n_err,
        "corrections": flags["correction"],
        "zero_info_retries": flags["zero_info_retry"],
        "nudges": flags["nudge"],
        "frustration_turns": flags["frustration"],
        "praise_turns": flags["praise"],
        "interrupts": sum(1 for e in events if e["kind"] == "interrupt"),
        "re_read_turns": sum(1 for t in turns if t["re_reads"]),
        "sequential_readonly_runs": sum(t["sequential_readonly_runs"] for t in turns),
        "edit_churn_files": sorted({f for t in turns for f in t["edit_churn_files"]})[:8],
        "delegations": sum(t["delegations"] for t in turns),
        "subagent_files": meta.get("subagent_files", 0),
        "commits": sum(t["commits"] for t in turns),
        "no_verify": sum(t["no_verify"] for t in turns),
        "force_push": sum(t["force_push"] for t in turns),
        "on_main_with_commits": bool(misc["git_branch"] in ("main", "master") and sum(t["commits"] for t in turns)),
        "denials": dict(misc["denials"]),
        "compactions": misc["compactions"],
        "hook_errors": misc["hook_errors"],
        "refusals": misc["refusals"],
        "plan_mode_used": plan_used,
        "low_quality_prompts": sum(1 for t in turns if t["quality"]["score"] <= 1 and not t["flags"]["nudge"] and t["chars"] > 0),
    }
    # heuristic attention score: how much this session deserves LLM reading
    attention = (mech["corrections"] * 2 + mech["zero_info_retries"] * 3 + mech["frustration_turns"] * 4 +
                 mech["interrupts"] * 2 + min(mech["tool_errors"], 10) + mech["nudges"] +
                 len(mech["edit_churn_files"]) * 2 + mech["no_verify"] * 5 + mech["force_push"] * 5)
    # good-pattern candidates: few turns, no corrections, edits/commits happened, praise or clean end
    clean = (len(turns) >= 2 and mech["corrections"] == 0 and mech["zero_info_retries"] == 0 and
             mech["frustration_turns"] == 0 and (sum(tool_counter[t] for t in EDIT_TOOLS) > 0 or mech["commits"] > 0))

    return {
        "tool": meta["tool"], "session_id": meta["session_id"], "project_slug": meta["project_slug"], "path": meta["path"],
        "title": title, "first_prompt": short(first_prompt, 160), "cwd": misc["cwd"], "git_branch": misc["git_branch"],
        "entrypoint": misc["entrypoint"], "app_version": misc["version"],
        "start": iso(start), "end": iso(end), "age_hours": round(age_h, 1) if age_h is not None else None,
        "outcome_pending": bool(age_h is not None and age_h < 24),
        "duration_min": round(active_sec / 60, 1) if tss else None,
        "span_hours": round((end - start).total_seconds() / 3600, 1) if (start and end) else None,
        "human_turns": len(turns), "assistant_msgs": len(assistants),
        "tokens": tok, "cache_ratio": cache_ratio, "thinking_chars": sum(t["thinking_chars"] for t in turns),
        "cost_usd": cs.get("totalCostUSD"), "lines_added": cs.get("totalLinesAdded"), "lines_removed": cs.get("totalLinesRemoved"),
        "api_ms": cs.get("totalAPIDuration"), "tool_ms": cs.get("totalToolDuration"),
        "agent_active_sec": agent_secs, "human_wait_sec": human_secs, "long_gaps": long_gaps,
        "models": dict(misc["models"]), "efforts": dict(misc["efforts"]), "permission_modes": dict(misc["permission_modes"]),
        "tools": dict(tool_counter.most_common(15)),
        "skills_attributed": dict(misc["skills_attributed"].most_common(10)), "skill_tool_calls": dict(skill_tools),
        "slash_commands": dict(slash_cmds),
        "avg_prompt_quality": avg_q,
        "mechanical": mech, "attention_score": attention, "clean_candidate": clean,
        "parse": {"lines": misc["lines"], "bad_lines": misc["bad_lines"], "format": "claude" if meta["tool"] == "claude" else "unverified"},
        "turns": turns,
    }


# ----------------------------------------------------------------------------
# git correlation (outcome lens)
# ----------------------------------------------------------------------------

def git(cwd, *args, timeout=15):
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def git_correlate(sess):
    cwd = sess.get("cwd")
    if not cwd or not os.path.isdir(cwd) or not sess.get("start"):
        return None
    if not git(cwd, "rev-parse", "--is-inside-work-tree").strip():
        return None
    since, until = sess["start"], sess["end"]
    log = git(cwd, "log", "--all", f"--since={since}", f"--until={until}", "--format=%h%x09%s", "--no-merges")
    commits = [l.split("\t", 1) for l in log.splitlines() if l.strip()]
    out = {"commits_in_window": [{"hash": h, "subject": short(s, 90)} for h, s in commits[:10]]}
    reverted, fixups = [], []
    for h, s in commits[:10]:
        if git(cwd, "log", "--all", f"--since={until}", f"--grep=This reverts commit {h}", "--format=%h").strip():
            reverted.append(h)
        files = git(cwd, "show", "--name-only", "--format=", h).split()
        if files:
            after = git(cwd, "log", "--all", f"--since={until}", "--format=%h%x09%s", "--no-merges", "-i", "-E", "--grep=fix|revert|hotfix|regress|oops", "--", *files[:10])
            for l in after.splitlines()[:5]:
                fh, fs = l.split("\t", 1)
                fixups.append({"hash": fh, "subject": short(fs, 90), "after": h})
    out["reverted"] = reverted
    out["follow_up_fixes"] = fixups[:10]
    return out


# ----------------------------------------------------------------------------
# state
# ----------------------------------------------------------------------------

def load_state(app_home: Path):
    p = app_home / "state.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"retros": [], "covered": {}}


def save_state(app_home: Path, state):
    app_home.mkdir(parents=True, exist_ok=True)
    (app_home / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------------
# outputs: one small shared summary + four disjoint per-group slices
# ----------------------------------------------------------------------------

SLICES = {
    "a": ("communication", "A - prompt quality, instruction persistence, task decomposition"),
    "b": ("orchestration", "B - delegation, wall-clock, session hygiene"),
    "c": ("correctness", "C - verification, outcome, skill usage, safety"),
    "d": ("endorsement", "D - endorsement and trend"),
}
TURNS_PER_SESSION = 12
SESSIONS_PER_SLICE = 10


def fmt_int(n):
    return f"{n:,}" if isinstance(n, (int, float)) and n is not None else "-"


def rule_files(cwd):
    """Rule/convention files that exist for a session's project, for lens 2."""
    out = []
    g = HOME / ".claude" / "CLAUDE.md"
    if g.is_file():
        out.append(str(g))
    if cwd and os.path.isdir(cwd):
        for name in ("CLAUDE.md", "AGENTS.md", "CLAUDE.local.md", ".cursor/rules"):
            p = Path(cwd) / name
            if p.exists():
                out.append(str(p))
    return out


def write_summary(run_dir: Path, inv):
    L = []
    s = inv["summary"]
    L.append(f"# improve-clauding summary - {inv['generated_at']}")
    L.append("")
    L.append(f"Selection: {inv['selection']}  |  sessions: {s['sessions']} (claude {s['by_tool'].get('claude',0)}, cursor {s['by_tool'].get('cursor',0)}, other {s['by_tool'].get('unknown',0)})  |  skipped trivial: {s['skipped_trivial']}")
    L.append(f"Previous retro: {inv['previous_retro'] or 'none'}  |  notes file: {inv['notes_path'] or 'none'}")
    L.append("")
    L.append("## Totals")
    L.append(f"- human turns {s['human_turns']}, assistant msgs {s['assistant_msgs']}, active session time {s['duration_min']} min (idle gaps >60 min excluded), agent-active {s['agent_active_min']} min, human-wait {s['human_wait_min']} min")
    L.append(f"- tokens: out {fmt_int(s['tokens']['out'])}, cache_read {fmt_int(s['tokens']['cache_read'])}, cache_create {fmt_int(s['tokens']['cache_create'])}, uncached in {fmt_int(s['tokens']['in'])}; cost (reported) ${s['cost_usd']:.2f}" if isinstance(s.get('cost_usd'), (int, float)) else f"- tokens: out {fmt_int(s['tokens']['out'])}, cache_read {fmt_int(s['tokens']['cache_read'])}, cache_create {fmt_int(s['tokens']['cache_create'])}")
    m = s["mechanical"]
    L.append(f"- corrections {m['corrections']}, zero-info retries {m['zero_info_retries']}, nudges {m['nudges']}, frustration turns {m['frustration_turns']}, praise turns {m['praise_turns']}, interrupts {m['interrupts']}")
    L.append(f"- tool errors {m['tool_errors']}, re-read turns {m['re_read_turns']}, sequential read-only runs {m['sequential_readonly_runs']}, compactions {m['compactions']}, denials {m['denials']}")
    L.append(f"- delegations {m['delegations']} (subagent files {m['subagent_files']}), plan-mode sessions {m['plan_mode_sessions']}, commits {m['commits']}, --no-verify {m['no_verify']}, force-push {m['force_push']}, commits on main {m['on_main_with_commits']}")
    L.append(f"- avg prompt quality {s['avg_prompt_quality']} / 5, low-quality prompts {m['low_quality_prompts']}")
    L.append("")
    L.append("## Tool mix")
    L.append(", ".join(f"{k} {v}" for k, v in s["tools"].items()) or "-")
    L.append("")
    L.append("## Skills / commands seen")
    L.append("- attributed skills: " + (", ".join(f"{k} {v}" for k, v in s["skills_attributed"].items()) or "-"))
    L.append("- Skill tool calls: " + (", ".join(f"{k} {v}" for k, v in s["skill_tool_calls"].items()) or "-"))
    L.append("- slash commands: " + (", ".join(f"{k} {v}" for k, v in s["slash_commands"].items()) or "-"))
    L.append("- installed but unseen (skills dir names): " + (", ".join(inv["skills_unseen"][:40]) or "-"))
    L.append("")
    L.append("## Repeated prompt openers (>=2 sessions)")
    for k, v in inv["repeated_openers"][:15]:
        L.append(f"- x{v}: {k}")
    if not inv["repeated_openers"]:
        L.append("- none")
    L.append("")
    L.append("## Sessions (sorted by attention score)")
    L.append("")
    L.append("| # | tool | when | min | turns | out tok | corr | 0-info | nudge | frust | errs | deleg | plan | attn | clean | title / first prompt |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n, x in enumerate(inv["sessions"]):
        mm = x["mechanical"]
        when = (x["start"] or "")[:16].replace("T", " ")
        title = short(x["title"] or x["first_prompt"], 70)
        L.append(f"| {n} | {x['tool']} | {when} | {x['duration_min'] or '-'} | {x['human_turns']} | {fmt_int(x['tokens']['out'])} | {mm['corrections']} | {mm['zero_info_retries']} | {mm['nudges']} | {mm['frustration_turns']} | {mm['tool_errors']} | {mm['delegations']} | {'y' if mm['plan_mode_used'] else ''} | {x['attention_score']} | {'y' if x['clean_candidate'] else ''} | {title} |")
    L.append("")
    L.append("## Clean sessions (endorsement candidates)")
    for n, x in enumerate(inv["sessions"]):
        if x["clean_candidate"]:
            L.append(f"- [{n}] {x['tool']} {x['human_turns']} turns, {x['duration_min']} min, out {fmt_int(x['tokens']['out'])}: {short(x['title'] or x['first_prompt'], 90)}")
    L.append("")
    if inv["git"]:
        L.append("## Git outcome signals")
        for n, g in inv["git"].items():
            x = inv["sessions"][int(n)]
            L.append(f"- [{n}] {short(x['title'] or x['first_prompt'], 60)}: commits {len(g['commits_in_window'])}, reverted {g['reverted'] or 'none'}, follow-up fixes {len(g['follow_up_fixes'])}")
        L.append("")
    L.append("Per-turn detail is NOT here. Each lens group has its own slice file in this")
    L.append("directory; read only yours. For a bounded window around one turn, run")
    L.append("`python scripts/excerpt.py --run-dir <this dir> --ref <session#>/<turn#>`.")
    (run_dir / "summary.md").write_text("\n".join(L), encoding="utf-8")


def _slice_header(group, run_dir, inv):
    name, title = SLICES[group]
    L = [f"# improve-clauding slice {group.upper()} - {name}", "",
         f"Lens group {title}. Generated {inv['generated_at']}.", "",
         f"Shared context: `{run_dir / 'summary.md'}` (read it once; totals and the session table live there).",
         f"This file holds only the turns relevant to group {group.upper()}, at most {TURNS_PER_SESSION} per session,",
         f"for at most {SESSIONS_PER_SLICE} sessions. Session numbers `[n]` match summary.md.", "",
         "To see what actually happened in a turn, do NOT read the transcript - it can be over",
         "1M tokens. Run:", "",
         f"    python scripts/excerpt.py --run-dir \"{run_dir}\" --ref <n>/<t>", "",
         "It prints a bounded window (prompt, tool calls, errors) for that turn.", ""]
    return L


def _pick_sessions(inv, group):
    ss = list(enumerate(inv["sessions"]))
    if group == "d":
        ss.sort(key=lambda p: (not p[1].get("clean_candidate"),
                               -(p[1].get("mechanical", {}).get("praise_turns", 0)),
                               p[1].get("attention_score", 0)))
    return ss[:SESSIONS_PER_SLICE]


def _pick_turns(x, group):
    ts = x.get("turns", [])
    if group == "a":
        sel = [t for t in ts if any(t["flags"][k] for k in ("correction", "zero_info_retry", "near_repeat", "frustration"))
               or (t["quality"]["score"] <= 1 and not t["flags"]["nudge"])]
    elif group == "b":
        sel = [t for t in ts if t["flags"]["nudge"] or t["flags"]["interrupted"] or t["delegations"]
               or t["sequential_readonly_runs"] or (t["agent_seconds"] or 0) >= 180
               or (t["human_wait_seconds"] or 0) >= 900]
    elif group == "c":
        sel = [t for t in ts if t["tool_errors"] or t["commits"] or t["edit_churn_files"]
               or t["flags"]["praise"] or t["no_verify"] or t["force_push"]]
    else:
        sel = [t for t in ts if t["flags"]["praise"] or not any(t["flags"].values())]
    return (sel or ts)[:TURNS_PER_SESSION], len(sel or ts)


def write_slices(run_dir: Path, inv):
    for group in SLICES:
        L = _slice_header(group, run_dir, inv)
        if group == "a":
            L.append("Per turn: `t<i> <ts> [flags] q<score> <missing context elements> : prompt`.")
            L.append("`missing` lists what the prompt lacked: path, error, code, criteria, intent.")
        elif group == "b":
            L.append("Per turn: agent seconds, human wait, assistant msgs, tools, delegations, sequential read-only runs.")
        elif group == "c":
            L.append("Per turn: tool errors by tool, commits, churned files, hard-fail flags. Git outcome per session.")
        else:
            L.append("Clean and praised sessions first. Per turn: quality, timing, tokens, prompt.")
        L.append("")
        if group == "d" and inv.get("previous_retro"):
            L.append(f"Previous report (read it, build the follow-through table): `{inv['previous_retro']['report']}`")
            L.append("")
        if group == "c" and inv.get("skills_unseen"):
            L.append("Installed skills unseen in this window: " + ", ".join(inv["skills_unseen"][:40]))
            L.append("")
        for n, x in _pick_sessions(inv, group):
            if x.get("error"):
                L.append(f"## [{n}] PARSE ERROR {x['session_id']}: {x['error']}")
                continue
            turns, total = _pick_turns(x, group)
            mm = x["mechanical"]
            L.append(f"## [{n}] {x['tool']} {x['session_id']} - {short(x['title'] or x['first_prompt'], 70)}")
            if group == "a":
                L.append(f"- {x['human_turns']} turns, avg quality {x['avg_prompt_quality']}/5, corrections {mm['corrections']}, zero-info retries {mm['zero_info_retries']}")
                L.append(f"- rule files in force: {', '.join(rule_files(x['cwd'])) or 'none found'}")
            elif group == "b":
                L.append(f"- span {x.get('span_hours')} h, active {x['duration_min']} min, agent-active {round((x['agent_active_sec'] or 0)/60)} min, human-wait {round((x['human_wait_sec'] or 0)/60)} min, long gaps {x['long_gaps']}")
                L.append(f"- delegations {mm['delegations']} (subagent files {mm['subagent_files']}), sequential read-only runs {mm['sequential_readonly_runs']}, compactions {mm['compactions']}, plan mode {mm['plan_mode_used']}")
                L.append(f"- tools: {x['tools']}")
            elif group == "c":
                L.append(f"- tool errors {mm['tool_errors']}, denials {mm['denials']}, commits {mm['commits']}, churned files {mm['edit_churn_files'] or 'none'}, lines +{x['lines_added']}/-{x['lines_removed']}")
                L.append(f"- hard-fail: --no-verify {mm['no_verify']}, force-push {mm['force_push']}, commits on {x['git_branch']} {mm['on_main_with_commits']}")
                L.append(f"- skills attributed: {x['skills_attributed'] or 'none'}")
                g = inv.get("git", {}).get(str(n))
                if g:
                    L.append(f"- git: commits {[c['hash'] for c in g['commits_in_window']]}, reverted {g['reverted'] or 'none'}, follow-up fixes {[f['hash'] for f in g['follow_up_fixes']] or 'none'}")
                if x["outcome_pending"]:
                    L.append("- OUTCOME PENDING (<24h old): do not claim outcomes for this session")
            else:
                L.append(f"- {x['human_turns']} turns, active {x['duration_min']} min, out {fmt_int(x['tokens']['out'])} tok, cache ratio {x['cache_ratio']}, praise {mm['praise_turns']}, corrections {mm['corrections']}, clean {x['clean_candidate']}")
                L.append(f"- delegations {mm['delegations']}, commits {mm['commits']}, lines +{x['lines_added']}/-{x['lines_removed']}, skills {x['skills_attributed'] or 'none'}")
            if total > len(turns):
                L.append(f"- showing {len(turns)} of {total} relevant turns (excerpt.py for the rest)")
            for t in turns:
                f = ",".join(k for k, v in t["flags"].items() if v) or "-"
                if group == "a":
                    q = t["quality"]
                    missing = ",".join(k for k in ("path", "error", "code", "criteria", "intent")
                                       if not q.get({"path": "has_path", "error": "has_error_text", "code": "has_code",
                                                     "criteria": "has_criteria", "intent": "has_intent"}[k])) or "-"
                    L.append(f"  - t{t['i']} {t['ts']} [{f}] q{q['score']} missing:{missing} : {short(t['text'], 240)}")
                elif group == "b":
                    L.append(f"  - t{t['i']} {t['ts']} [{f}] agent {t['agent_seconds']}s wait {t['human_wait_seconds']}s msgs {t['assistant_msgs']} deleg {t['delegations']} seqRO {t['sequential_readonly_runs']} tools {t['tools']} : {short(t['text'], 80)}")
                elif group == "c":
                    L.append(f"  - t{t['i']} {t['ts']} [{f}] errs {t['tool_errors']}{' ' + str(t['error_tools']) if t['error_tools'] else ''} commits {t['commits']} churn {t['edit_churn_files'] or '-'} tools {t['tools']} : {short(t['text'], 120)}")
                else:
                    L.append(f"  - t{t['i']} {t['ts']} [{f}] q{t['quality']['score']} agent {t['agent_seconds']}s msgs {t['assistant_msgs']} out {t['tokens']['out']} deleg {t['delegations']} : {short(t['text'], 200)}")
            L.append("")
        name = SLICES[group][0]
        (run_dir / f"slice-{group}-{name}.md").write_text("\n".join(L), encoding="utf-8")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def installed_skill_names():
    names = set()
    pats = [HOME / ".claude" / "skills" / "*" / "SKILL.md",
            HOME / ".claude" / "plugins" / "cache" / "*" / "*" / "*" / "skills" / "*" / "SKILL.md",
            HOME / ".cursor" / "skills" / "*" / "SKILL.md",
            HOME / ".cursor" / "plugins" / "local" / "*" / "skills" / "*" / "SKILL.md",
            HOME / ".agents" / "skills" / "*" / "SKILL.md"]
    for p in pats:
        for f in glob.glob(str(p)):
            names.add(Path(f).parent.name)
    return sorted(names)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", default=str(DEFAULT_APP_HOME))
    ap.add_argument("--roots", nargs="*", default=[])
    sel = ap.add_mutually_exclusive_group()
    sel.add_argument("--last", type=int)
    sel.add_argument("--since")
    sel.add_argument("--all", action="store_true")
    ap.add_argument("--min-turns", type=int, default=2)
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--previous", action="store_true")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--report")
    ap.add_argument("--run-dir", help="use this run dir (with --commit) instead of the latest")
    a = ap.parse_args(argv)

    app_home = Path(a.home)
    state = load_state(app_home)
    now = dt.datetime.now(dt.timezone.utc)

    if a.status:
        print(json.dumps({"home": str(app_home), "retros": state["retros"], "covered_sessions": len(state["covered"])}, indent=2))
        return 0
    if a.previous:
        print(state["retros"][-1]["report"] if state["retros"] else "")
        return 0
    if a.commit:
        if not a.report or not Path(a.report).is_file():
            print("--commit needs --report PATH to an existing report file", file=sys.stderr)
            return 2
        runs = sorted((app_home / "runs").glob("*")) if (app_home / "runs").is_dir() else []
        run_dir = Path(a.run_dir) if a.run_dir else (runs[-1] if runs else None)
        if not run_dir or not (run_dir / "inventory.json").is_file():
            print("no inventory run found to commit", file=sys.stderr)
            return 2
        inv = json.loads((run_dir / "inventory.json").read_text(encoding="utf-8"))
        ids = [f"{s['tool']}:{s['session_id']}" for s in inv["sessions"]]
        for i in ids:
            state["covered"][i] = now.isoformat(timespec="seconds")
        state["retros"].append({"at": now.isoformat(timespec="seconds"), "report": str(Path(a.report).resolve()),
                                "run_dir": str(run_dir), "sessions": len(ids)})
        save_state(app_home, state)
        print(f"recorded retro #{len(state['retros'])}: {len(ids)} sessions covered; state at {app_home / 'state.json'}")
        return 0

    # ---- discovery
    metas = discover_claude() + discover_cursor() + discover_extra(a.roots)
    for m in metas:
        m["mtime"] = mtime(Path(m["path"]))
    metas.sort(key=lambda m: m["mtime"])

    last_retro_at = parse_ts(state["retros"][-1]["at"]) if state["retros"] else None
    if a.all:
        selection = "all"
        chosen = metas
    elif a.last:
        selection = f"last {a.last}"
        chosen = metas[-a.last:]
    elif a.since:
        d = parse_ts(a.since)
        selection = f"since {a.since}"
        chosen = [m for m in metas if d and m["mtime"] >= d]
    else:
        covered = set(state["covered"].keys())
        chosen = [m for m in metas if f"{m['tool']}:{m['session_id']}" not in covered and (not last_retro_at or m["mtime"] >= last_retro_at - dt.timedelta(days=1))]
        selection = f"since last retro ({iso(last_retro_at) or 'never'}), uncovered"

    # ---- parse + analyze
    sessions, skipped = [], 0
    for m in chosen:
        try:
            events, misc = parse_session(m)
            s = analyze(m, events, misc, now)
        except Exception as ex:  # never let one broken file kill the run
            sessions.append({"tool": m["tool"], "session_id": m["session_id"], "path": m["path"], "error": repr(ex),
                             "human_turns": 0, "mechanical": {}, "turns": [], "attention_score": 0, "clean_candidate": False,
                             "tokens": {"in": 0, "out": 0, "cache_read": 0, "cache_create": 0}, "title": "PARSE ERROR", "first_prompt": "",
                             "start": None, "end": None, "duration_min": None, "project_slug": m["project_slug"]})
            continue
        if s["human_turns"] < a.min_turns:
            skipped += 1
            continue
        sessions.append(s)
    sessions.sort(key=lambda s: (-s.get("attention_score", 0), s.get("start") or ""))

    # ---- cross-session aggregates
    def agg(key):
        return sum((s.get("tokens", {}).get(key, 0) or 0) for s in sessions)
    mech_keys = ["tool_errors", "corrections", "zero_info_retries", "nudges", "frustration_turns", "praise_turns", "interrupts",
                 "re_read_turns", "sequential_readonly_runs", "compactions", "delegations", "subagent_files", "commits", "no_verify",
                 "force_push", "low_quality_prompts"]
    mech = {k: sum((s.get("mechanical", {}).get(k, 0) or 0) for s in sessions) for k in mech_keys}
    mech["denials"] = sum(sum(s.get("mechanical", {}).get("denials", {}).values()) for s in sessions)
    mech["plan_mode_sessions"] = sum(1 for s in sessions if s.get("mechanical", {}).get("plan_mode_used"))
    mech["on_main_with_commits"] = sum(1 for s in sessions if s.get("mechanical", {}).get("on_main_with_commits"))
    tools = Counter()
    skills_attr = Counter()
    skill_calls = Counter()
    slashes = Counter()
    openers = Counter()
    for s in sessions:
        tools.update(s.get("tools", {}))
        skills_attr.update(s.get("skills_attributed", {}))
        skill_calls.update(s.get("skill_tool_calls", {}))
        slashes.update(s.get("slash_commands", {}))
        for t in s.get("turns", []):
            words = re.findall(r"\w+", t["text"].lower())[:4]
            if len(words) >= 3 and not t["flags"]["nudge"]:
                openers[" ".join(words)] += 1
    q_vals = [s["avg_prompt_quality"] for s in sessions if s.get("avg_prompt_quality") is not None]
    costs = [s["cost_usd"] for s in sessions if isinstance(s.get("cost_usd"), (int, float))]
    summary = {
        "sessions": len(sessions), "by_tool": dict(Counter(s["tool"] for s in sessions)), "skipped_trivial": skipped,
        "human_turns": sum(s.get("human_turns", 0) for s in sessions), "assistant_msgs": sum(s.get("assistant_msgs", 0) for s in sessions),
        "duration_min": round(sum(s.get("duration_min") or 0 for s in sessions)),
        "agent_active_min": round(sum(s.get("agent_active_sec") or 0 for s in sessions) / 60),
        "human_wait_min": round(sum(s.get("human_wait_sec") or 0 for s in sessions) / 60),
        "tokens": {k: agg(k) for k in ("in", "out", "cache_read", "cache_create")},
        "cost_usd": sum(costs) if costs else None,
        "mechanical": mech, "tools": dict(tools.most_common(20)),
        "skills_attributed": dict(skills_attr.most_common(20)), "skill_tool_calls": dict(skill_calls.most_common(20)),
        "slash_commands": dict(slashes.most_common(20)),
        "avg_prompt_quality": round(sum(q_vals) / len(q_vals), 2) if q_vals else None,
    }
    seen_skill_tokens = set()
    for k in list(skills_attr) + list(skill_calls) + list(slashes):
        seen_skill_tokens.add(k.split(":")[-1].lstrip("/"))
    skills_unseen = [n for n in installed_skill_names() if n not in seen_skill_tokens]

    # ---- git correlation
    gitinfo = {}
    if not a.no_git:
        for n, s in enumerate(sessions):
            if s.get("error"):
                continue
            g = git_correlate(s)
            if g and (g["commits_in_window"] or g["follow_up_fixes"]):
                gitinfo[str(n)] = g

    notes = app_home / "notes.md"
    inv = {
        "generated_at": now.isoformat(timespec="seconds"), "selection": selection,
        "previous_retro": state["retros"][-1] if state["retros"] else None,
        "notes_path": str(notes) if notes.is_file() else None,
        "summary": summary, "repeated_openers": [(k, v) for k, v in openers.most_common(30) if v >= 2],
        "skills_unseen": skills_unseen, "git": gitinfo, "sessions": sessions,
    }
    run_dir = app_home / "runs" / now.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "inventory.json").write_text(json.dumps(inv, indent=1, default=str), encoding="utf-8")
    write_summary(run_dir, inv)
    write_slices(run_dir, inv)
    if not a.quiet:
        print(f"sessions: {len(sessions)} ({selection}); skipped trivial: {skipped}")
        print(f"run dir: {run_dir}")
        for p in sorted(run_dir.glob("*.md")):
            print(f"  {p.name:34} {p.stat().st_size // 1024:>4} KB")
        print(f"  {'inventory.json':34} {(run_dir / 'inventory.json').stat().st_size // 1024:>4} KB  (full record; use excerpt.py, do not read whole)")
        if notes.is_file():
            print(f"notes:   {notes}")
        if state["retros"]:
            print(f"previous report: {state['retros'][-1]['report']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
