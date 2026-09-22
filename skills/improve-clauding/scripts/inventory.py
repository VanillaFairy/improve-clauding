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

READ_ONLY_TOOLS = {
    "Read", "ReadFile", "Grep", "rg", "Glob", "LS", "WebFetch", "WebSearch",
    "ToolSearch", "GetDynamicTools", "ReadLints", "NotebookRead",
}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace", "ApplyPatch"}
DELEGATE_TOOLS = {"Agent", "Task", "Subagent", "Workflow", "SendMessage"}
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
    r"task-notification|attached_files|system_notification|open_and_recently_viewed_files|user_info|rules)>.*?</\1>\s*",
    re.S | re.I,
)
CURSOR_QUERY_RE = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.S | re.I)
CURSOR_TIMESTAMP_RE = re.compile(r"<timestamp>\s*(.*?)\s*</timestamp>", re.S | re.I)
CURSOR_SLASH_RE = re.compile(r"^\s*(/[\w:.\-]+)\b")
MODEL_DATE_SUFFIX_RE = re.compile(r"-\d{6,8}$")
BIG_TOOL_OUTPUT_CHARS = 10000   # a tool result at or above this is a context dump

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


def cursor_timestamp(text):
    """Parse Cursor's user-facing timestamp tag into UTC."""
    match = CURSOR_TIMESTAMP_RE.search(text or "")
    if not match:
        return None
    raw = match.group(1).strip()
    zoned = re.fullmatch(r"(.+?)\s+\(UTC([+-])(\d{1,2})(?::(\d{2}))?\)", raw)
    if not zoned:
        return parse_ts(raw)
    local = None
    for form in ("%A, %b %d, %Y, %I:%M %p", "%A, %B %d, %Y, %I:%M %p",
                 "%b %d, %Y, %I:%M %p", "%B %d, %Y, %I:%M %p"):
        try:
            local = dt.datetime.strptime(zoned.group(1), form)
            break
        except ValueError:
            pass
    if local is None:
        return None
    minutes = int(zoned.group(3)) * 60 + int(zoned.group(4) or 0)
    if zoned.group(2) == "-":
        minutes = -minutes
    return local.replace(tzinfo=dt.timezone(dt.timedelta(minutes=minutes))).astimezone(dt.timezone.utc)


def normalize_prompt(text, tool):
    """Remove IDE context wrappers while preserving the user's words."""
    text = text or ""
    if tool == "cursor":
        queries = [q.strip() for q in CURSOR_QUERY_RE.findall(text) if q.strip()]
        if queries:
            return "\n\n".join(queries)
        text = CURSOR_TIMESTAMP_RE.sub("", text)
    return INJECTED_TAG_RE.sub("", text).strip()


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


def short_model(model):
    """claude-opus-4-1-20250805 -> claude-opus-4-1; keeps the table narrow."""
    return MODEL_DATE_SUFFIX_RE.sub("", str(model or "").strip()) or "-"


def top_key(counts):
    """Most common key of a {value: count} mapping, or None when empty."""
    return Counter(counts or {}).most_common(1)[0][0] if counts else None


def short_chars(n):
    """41234 -> '41k'. '?' when the transcript does not record the size."""
    if n is None:
        return "?"
    return f"{round(n / 1000)}k" if n >= 1000 else str(n)


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
            subs = [str(p) for p in sub_dir.rglob("*.jsonl")] if sub_dir.is_dir() else []
            out.append({"tool": "claude", "path": str(f), "session_id": sid, "project_slug": proj.name,
                        "subagent_files": len(subs), "subagent_paths": subs})
    return out


def scan_usage(paths):
    """Token usage from transcripts we do not otherwise analyze (subagents).

    Subagent work is real spend billed to the parent session, so leaving it out
    makes delegation look free. Deduplicated by message id like the main pass.
    """
    by_fam = defaultdict(lambda: Counter())
    calls = 0
    for p in paths:
        seen = set()
        try:
            fh = open(p, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") != "assistant":
                    continue
                m = o.get("message")
                if not isinstance(m, dict):
                    continue
                mid = m.get("id")
                if mid is not None:
                    if mid in seen:
                        continue
                    seen.add(mid)
                u = m.get("usage")
                if not isinstance(u, dict):
                    continue
                calls += 1
                by_fam[usage_family_key(m.get("model"))].update({
                    "in": u.get("input_tokens", 0) or 0,
                    "out": u.get("output_tokens", 0) or 0,
                    "cache_write": u.get("cache_creation_input_tokens", 0) or 0,
                    "cache_read": u.get("cache_read_input_tokens", 0) or 0,
                })
    return {k: dict(v) for k, v in by_fam.items()}, calls


def discover_cursor():
    out = []
    if not CURSOR_PROJECTS.is_dir():
        return out
    for proj in CURSOR_PROJECTS.iterdir():
        if not proj.is_dir():
            continue
        tdir = proj / "agent-transcripts"
        if not tdir.is_dir():
            continue
        # Current Cursor builds put each main transcript in
        # agent-transcripts/<session-id>/<session-id>.jsonl. Keep the direct
        # pattern for older builds.
        files = {
            f.stem: f
            for f in list(tdir.glob("*.jsonl")) + list(tdir.glob("*/*.jsonl"))
        }
        for f in files.values():
            sub_dir = f.parent / "subagents"
            subs = [str(p) for p in sub_dir.glob("*.jsonl")] if sub_dir.is_dir() else []
            out.append({
                "tool": "cursor",
                "path": str(f),
                "session_id": f.stem,
                "project_slug": proj.name,
                "subagent_files": len(subs),
                "subagent_paths": subs,
            })
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
            "version": None, "entrypoint": None, "cwd": None, "git_branch": None, "branches": Counter(),
            "permission_mode_changes": Counter(), "models": Counter(), "usage_by_family": defaultdict(Counter),
            "efforts": Counter(), "skills_attributed": Counter(), "compactions": 0, "hook_errors": 0,
            "denials": Counter(), "refusals": 0, "system_subtypes": Counter(), "turn_durations_ms": [],
            "turn_errors": Counter(), "bad_lines": 0, "lines": 0}
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
            if rec.get("gitBranch"):
                misc["branches"][rec["gitBranch"]] += 1
                if not misc["git_branch"]:
                    misc["git_branch"] = rec["gitBranch"]
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
                # a mode-change event, not a turn; kept separate so the two never mix
                misc["permission_mode_changes"][str(rec.get("permissionMode"))] += 1
                continue
            if t == "cost-state":
                misc["cost_state"] = rec
                continue
            if t == "turn_ended":
                if rec.get("status") == "error":
                    error = str(rec.get("error") or "unknown Cursor turn error")
                    misc["turn_errors"][error] += 1
                    if re.search(r"user aborted|cancellation token requested", error, re.I):
                        events.append({"kind": "interrupt", "ts": ts})
                    else:
                        events.append({"kind": "turn_error", "ts": ts, "error": error})
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
                if meta.get("tool") == "cursor" and ts is None:
                    ts = cursor_timestamp(text)
                tool_results = [b for b in blocks if b.get("type") == "tool_result"]
                if tool_results:
                    for b in tool_results:
                        rtxt, _ = text_of(b.get("content"))
                        events.append({"kind": "tool_result", "ts": ts, "tool_use_id": b.get("tool_use_id"),
                                       "is_error": bool(b.get("is_error")), "chars": len(rtxt),
                                       "sidechain": bool(rec.get("isSidechain"))})
                    continue
                text = normalize_prompt(text, meta.get("tool"))
                if INTERRUPT_RE.search(text):
                    events.append({"kind": "interrupt", "ts": ts})
                    continue
                m = SLASH_RE.search(text)
                if not m and meta.get("tool") == "cursor":
                    m = CURSOR_SLASH_RE.search(text)
                if m:
                    events.append({"kind": "slash", "ts": ts, "command": m.group(1)})
                    continue
                if is_human_prompt(rec, text, blocks):
                    # count the mode once per human turn, not once per tool result
                    if rec.get("permissionMode"):
                        misc["permission_modes"][str(rec["permissionMode"])] += 1
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
                if usage:
                    misc["usage_by_family"][usage_family_key(msg.get("model"))].update({
                        "in": usage.get("input_tokens", 0) or 0,
                        "out": usage.get("output_tokens", 0) or 0,
                        "cache_write": usage.get("cache_creation_input_tokens", 0) or 0,
                        "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
                        "calls": 1,
                    })
                thinking_chars = sum(len(b.get("thinking", "") or "") for b in blocks if b.get("type") == "thinking")
                text_chars = sum(len(b.get("text", "") or "") for b in blocks if b.get("type") == "text")
                tool_uses = []
                for b in blocks:
                    if b.get("type") == "tool_use":
                        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                        name = b.get("name")
                        if name == "CallDynamicTool" and inp.get("toolName"):
                            name = inp["toolName"]
                        target = (inp.get("file_path") or inp.get("path") or inp.get("pattern") or
                                  inp.get("command") or inp.get("url") or inp.get("skill") or
                                  inp.get("description") or inp.get("toolName") or "")
                        if not misc["cwd"]:
                            candidate = inp.get("working_directory") or inp.get("target_directory")
                            if candidate and os.path.isdir(candidate):
                                misc["cwd"] = candidate
                        tool_uses.append({"id": b.get("id"), "name": name, "target": short(str(target), 200),
                                          "input_hash": sha(json.dumps(inp, sort_keys=True, default=str))})
                events.append({"kind": "assistant", "ts": ts, "model": msg.get("model"),
                               "in": usage.get("input_tokens", 0) or 0,
                               "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
                               "cache_create": usage.get("cache_creation_input_tokens", 0) or 0,
                               "out": usage.get("output_tokens", 0) or 0,
                               "thinking_chars": thinking_chars, "text_chars": text_chars,
                               "tool_uses": tool_uses, "stop_reason": msg.get("stop_reason"),
                               "sidechain": bool(rec.get("isSidechain")), "effort": rec.get("effort"),
                               "msg_id": mid, "first_of_msg": first_of_msg, "branch": rec.get("gitBranch")})
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
    timing_available = bool(prompts and any(e.get("ts") for e in assistants))
    usage_available = meta["tool"] != "cursor" or bool(misc["usage_by_family"])
    tool_results_available = meta["tool"] != "cursor" or bool(results)
    compactions_available = meta["tool"] != "cursor"
    # active duration: sum of inter-event gaps, ignoring idle gaps over 60 min
    active_sec = (sum(min((b - a_).total_seconds(), 3600)
                      for a_, b in zip(tss, tss[1:])
                      if (b - a_).total_seconds() < 3600)
                  if timing_available else None)

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
        parallel_delegations = 0
        seq_delegation_runs = 0
        prev_single_delegate = False
        max_tools_per_msg = 0
        multi_tool_msgs = 0
        tool_result_chars = 0
        big_tool_outputs = 0
        edits = Counter()
        commits = 0
        commit_branches = set()
        no_verify = 0
        force_push = 0
        skills = Counter()
        plan_mode = 0
        interrupts = 0
        turn_failures = 0
        turn_failure_reasons = Counter()
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
                    if tu["name"] in ("EnterPlanMode", "ExitPlanMode", "SwitchMode"):
                        plan_mode += 1
                    if tu["name"] in SHELL_TOOLS:
                        cmd = tu["target"]
                        if GIT_COMMIT_RE.search(cmd):
                            commits += 1
                            # branch as of this record, not as of session start
                            if e.get("branch"):
                                commit_branches.add(e["branch"])
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
                # batching: one message carrying several tools is a parallel batch
                max_tools_per_msg = max(max_tools_per_msg, len(names))
                if len(names) > 1:
                    multi_tool_msgs += 1
                n_delegates = sum(1 for nm in names if nm in DELEGATE_TOOLS)
                if n_delegates > 1:
                    parallel_delegations += n_delegates
                is_single_delegate = n_delegates == 1
                if is_single_delegate and prev_single_delegate:
                    seq_delegation_runs += 1
                prev_single_delegate = is_single_delegate
            elif e["kind"] == "tool_result":
                tool_result_chars += e.get("chars", 0) or 0
                if (e.get("chars", 0) or 0) >= BIG_TOOL_OUTPUT_CHARS:
                    big_tool_outputs += 1
            elif e["kind"] == "interrupt":
                interrupts += 1
            elif e["kind"] == "turn_error":
                turn_failures += 1
                turn_failure_reasons[e["error"]] += 1
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
            "parallel_delegations": parallel_delegations, "sequential_delegation_runs": seq_delegation_runs,
            "max_tools_per_message": max_tools_per_msg, "multi_tool_messages": multi_tool_msgs,
            "tool_result_chars": tool_result_chars if tool_results_available else None,
            "big_tool_outputs": big_tool_outputs if tool_results_available else None,
            "edit_churn_files": churn_files[:5], "commits": commits, "commit_branches": sorted(commit_branches),
            "no_verify": no_verify, "force_push": force_push,
            "turn_failures": turn_failures, "turn_failure_reasons": dict(turn_failure_reasons),
            "skills": dict(skills), "slash": slashes, "plan_mode_tools": plan_mode,
            "tokens": {"in": tok_in, "out": tok_out, "cache_read": cache_r, "cache_create": cache_c},
            "thinking_chars": thinking,
        })
    for t in turns:
        del t["text_full"]
    # A terse follow-up inside a live thread is not a bad prompt - the context is
    # already there. Only opening prompts are scored as task briefs: the first turn
    # of the session, or one the user came back to after a break.
    for n, t in enumerate(turns):
        prompt_gap = None
        if n:
            previous_ts, current_ts = parse_ts(turns[n - 1]["ts"]), parse_ts(t["ts"])
            if previous_ts and current_ts:
                prompt_gap = (current_ts - previous_ts).total_seconds()
        t["is_opener"] = (n == 0 or
                          (turns[n - 1]["human_wait_seconds"] or 0) >= OPENER_GAP_SEC or
                          (not timing_available and (prompt_gap or 0) >= OPENER_GAP_SEC))
    openers = [t for t in turns if t["is_opener"]]

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
    agent_secs = sum(t["agent_seconds"] or 0 for t in turns) if timing_available else None
    human_secs = (sum(t["human_wait_seconds"] or 0 for t in turns
                      if (t["human_wait_seconds"] or 0) < 3600)
                  if timing_available else None)
    long_gaps = (sum(1 for t in turns if (t["human_wait_seconds"] or 0) >= 1800)
                 if timing_available else None)
    slash_cmds = Counter(c for t in turns for c in t["slash"])
    skill_tools = Counter()
    for t in turns:
        skill_tools.update(t["skills"])
    plan_used = misc["modes"].get("plan", 0) > 0 or any(t["plan_mode_tools"] for t in turns)
    title = next((v for k, v in misc["titles"] if k == "custom-title"), None) or next((v for k, v in misc["titles"]), None)
    first_prompt = turns[0]["text"] if turns else ""
    cs = misc["cost_state"] or {}
    age_h = (now - end).total_seconds() / 3600 if end else None

    # Spend. cost-state is mostly absent or zero in practice, so the estimate below is
    # the number to use; the reported one is kept only for comparison.
    main_fam = {k: dict(v) for k, v in misc["usage_by_family"].items()}
    sub_fam, sub_calls = scan_usage(meta.get("subagent_paths") or [])
    main_calls = sum(v.get("calls", 0) for v in main_fam.values())
    combined = defaultdict(Counter)
    for src in (main_fam, sub_fam):
        for fam, u in src.items():
            combined[fam].update({k: v for k, v in u.items() if k != "calls"})
    combined = {k: dict(v) for k, v in combined.items()}
    cost_main, unpriced_main = estimate_cost(main_fam)
    cost_sub, unpriced_sub = estimate_cost(sub_fam)
    unpriced = Counter(unpriced_main)
    unpriced.update(unpriced_sub)
    cost_partial = bool(unpriced)
    ctx_read = sum(u.get("cache_read", 0) + u.get("in", 0) for u in combined.values())
    all_calls = main_calls + sub_calls
    spend = {
        "available": usage_available,
        "est_cost_usd": round(cost_main + cost_sub, 2),
        "est_cost_main_usd": cost_main,
        "est_cost_subagents_usd": cost_sub,
        "cost_partial": cost_partial,
        "unpriced_families": sorted(unpriced),
        "unpriced_tokens": sum(unpriced.values()),
        "api_calls": all_calls, "api_calls_main": main_calls, "api_calls_subagents": sub_calls,
        "context_read_tokens": ctx_read,
        "avg_context_per_call": round(ctx_read / all_calls) if all_calls else 0,
        "subagent_usage": {k: v for k, v in sub_fam.items()},
        "reported_cost_usd": cs.get("totalCostUSD"),
    }
    avg_q = round(sum(t["quality"]["score"] for t in openers) / len(openers), 2) if openers else None

    mech = {
        "tool_errors": n_err,
        "corrections": flags["correction"],
        "zero_info_retries": flags["zero_info_retry"],
        "nudges": flags["nudge"],
        "frustration_turns": flags["frustration"],
        "praise_turns": flags["praise"],
        "interrupts": sum(1 for e in events if e["kind"] == "interrupt"),
        "turn_failures": sum(t["turn_failures"] for t in turns),
        "turn_failure_reasons": dict(misc["turn_errors"]),
        "re_read_turns": sum(1 for t in turns if t["re_reads"]),
        "sequential_readonly_runs": sum(t["sequential_readonly_runs"] for t in turns),
        "max_tools_per_message": max([t["max_tools_per_message"] for t in turns] or [0]),
        "multi_tool_messages": sum(t["multi_tool_messages"] for t in turns),
        "tool_output_chars": (sum(t["tool_result_chars"] or 0 for t in turns)
                              if tool_results_available else None),
        "big_tool_outputs": (sum(t["big_tool_outputs"] or 0 for t in turns)
                             if tool_results_available else None),
        "edit_churn_files": sorted({f for t in turns for f in t["edit_churn_files"]})[:8],
        "delegations": sum(t["delegations"] for t in turns),
        "parallel_delegations": sum(t["parallel_delegations"] for t in turns),
        "sequential_delegation_runs": sum(t["sequential_delegation_runs"] for t in turns),
        "subagent_files": meta.get("subagent_files", 0),
        "commits": sum(t["commits"] for t in turns),
        "no_verify": sum(t["no_verify"] for t in turns),
        "force_push": sum(t["force_push"] for t in turns),
        "commit_branches": sorted({b for t in turns for b in t["commit_branches"]}),
        "on_main_with_commits": any(b in ("main", "master", "trunk", "develop")
                                    for t in turns for b in t["commit_branches"]),
        "denials": dict(misc["denials"]),
        "compactions": misc["compactions"],
        "hook_errors": misc["hook_errors"],
        "refusals": misc["refusals"],
        "plan_mode_used": plan_used,
        "openers": len(openers),
        # 2+ means the session carried more than one separate brief
        "briefs_in_session": sum(1 for t in turns if t.get("is_opener")),
        "low_quality_openers": sum(1 for t in openers if t["quality"]["score"] <= 1 and not t["flags"]["nudge"]),
    }
    # heuristic attention score: how much this session deserves LLM reading
    attention = (mech["corrections"] * 2 + mech["zero_info_retries"] * 3 + mech["frustration_turns"] * 4 +
                 mech["interrupts"] * 2 + mech["turn_failures"] * 2 +
                 min(mech["tool_errors"], 10) + mech["nudges"] +
                 len(mech["edit_churn_files"]) * 2 + mech["no_verify"] * 5 + mech["force_push"] * 5)
    # good-pattern candidates: few turns, no corrections, edits/commits happened, praise or clean end
    clean = (len(turns) >= 2 and mech["corrections"] == 0 and mech["zero_info_retries"] == 0 and
             mech["frustration_turns"] == 0 and mech["turn_failures"] == 0 and
             (sum(tool_counter[t] for t in EDIT_TOOLS) > 0 or mech["commits"] > 0))

    return {
        "tool": meta["tool"], "session_id": meta["session_id"], "project_slug": meta["project_slug"], "path": meta["path"],
        "title": title, "first_prompt": short(first_prompt, 160), "cwd": misc["cwd"],
        "git_branch": misc["branches"].most_common(1)[0][0] if misc["branches"] else None,
        "branches": dict(misc["branches"]),
        "entrypoint": misc["entrypoint"], "app_version": misc["version"],
        "start": iso(start), "end": iso(end), "age_hours": round(age_h, 1) if age_h is not None else None,
        "outcome_pending": bool(age_h is not None and age_h < 24),
        "duration_min": round(active_sec / 60, 1) if active_sec is not None else None,
        "span_hours": round((end - start).total_seconds() / 3600, 1) if (start and end) else None,
        "human_turns": len(turns), "assistant_msgs": len(assistants),
        "tokens": tok, "cache_ratio": cache_ratio, "thinking_chars": sum(t["thinking_chars"] for t in turns),
        "spend": spend, "usage_by_family": combined,
        "cost_usd": cs.get("totalCostUSD"), "lines_added": cs.get("totalLinesAdded"), "lines_removed": cs.get("totalLinesRemoved"),
        "api_ms": cs.get("totalAPIDuration"), "tool_ms": cs.get("totalToolDuration"),
        "agent_active_sec": agent_secs, "human_wait_sec": human_secs, "long_gaps": long_gaps,
        "models": dict(misc["models"]), "efforts": dict(misc["efforts"]),
        "permission_modes": dict(misc["permission_modes"]),
        "permission_mode_changes": dict(misc["permission_mode_changes"]),
        "tools": dict(tool_counter.most_common(15)),
        "skills_attributed": dict(misc["skills_attributed"].most_common(10)), "skill_tool_calls": dict(skill_tools),
        "slash_commands": dict(slash_cmds),
        "avg_prompt_quality": avg_q,
        "mechanical": mech, "attention_score": attention, "clean_candidate": clean,
        "capabilities": {
            "usage": usage_available,
            "exact_timing": timing_available,
            "tool_results": tool_results_available,
            # compaction markers are Claude-Code record shapes; Cursor emits none,
            # so a 0 there means "not recorded", not "context never compacted"
            "compactions": compactions_available,
            "pricing": not cost_partial,
            "model": bool(misc["models"]),
            "cwd": bool(misc["cwd"]),
        },
        "parse": {"lines": misc["lines"], "bad_lines": misc["bad_lines"], "format": meta["tool"]},
        "turns": turns,
    }


# ----------------------------------------------------------------------------
# git correlation (outcome lens)
# ----------------------------------------------------------------------------

# Public list prices per million tokens: input, output, cache write, cache read.
# Used only to turn token counts into a number you can feel. Adjust if your plan differs;
# the retro compares runs, so consistency matters more than exactness.
PRICES = {
    "opus":   (15.0, 75.0, 18.75, 1.50),
    "sonnet": (3.0, 15.0, 3.75, 0.30),
    "haiku":  (0.80, 4.0, 1.0, 0.08),
}


def model_family(model):
    """Priced family for a model string, or None when we have no list price.

    Composer, GPT, Grok, Gemini and Fable are not in PRICES. Falling back to a
    default family would bill them at that family's rate and hide the gap.
    """
    m = (model or "").lower()
    for k in PRICES:
        if k in m:
            return k
    return None


def usage_family_key(model):
    """Bucket key for usage: the priced family, else the raw model string."""
    return model_family(model) or (str(model).strip() if model else "unknown")


def estimate_cost(usage_by_family):
    """usage_by_family: {family: {'in','out','cache_write','cache_read'}}.

    Returns (usd, unpriced) where unpriced maps each skipped bucket key to the
    token count it held. Unpriced buckets contribute nothing to the total; no
    price is guessed for them.
    """
    total = 0.0
    unpriced = {}
    for fam, u in usage_by_family.items():
        price = PRICES.get(fam)
        if price is None:
            tokens = sum(u.get(k, 0) or 0 for k in ("in", "out", "cache_write", "cache_read"))
            unpriced[fam] = unpriced.get(fam, 0) + tokens
            continue
        pi, po, pw, pr = price
        total += (u.get("in", 0) * pi + u.get("out", 0) * po
                  + u.get("cache_write", 0) * pw + u.get("cache_read", 0) * pr) / 1e6
    return round(total, 2), unpriced


GIT_SCAN_LIMIT = 10        # commits inspected per session; lists are labelled when hit
FOLLOW_UP_DAYS = 14        # how long after a session a "fix" commit still counts as its tail


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
    # follow-ups are only meaningful for a while after the session; without an upper
    # bound every long-lived file collects unrelated "fix" commits forever
    end_dt = parse_ts(until)
    horizon = iso(end_dt + dt.timedelta(days=FOLLOW_UP_DAYS)) if end_dt else None
    log = git(cwd, "log", "--all", f"--since={since}", f"--until={until}", "--format=%h%x09%s", "--no-merges")
    commits = [l.split("\t", 1) for l in log.splitlines() if l.strip()]
    out = {"commits_in_window": [{"hash": h, "subject": short(s, 90)} for h, s in commits[:GIT_SCAN_LIMIT]],
           "commits_total": len(commits),
           "commits_truncated": len(commits) > GIT_SCAN_LIMIT,
           "follow_up_window_days": FOLLOW_UP_DAYS}
    reverted, fixups = [], []
    seen_fixups = set()
    for h, s in commits[:GIT_SCAN_LIMIT]:
        if git(cwd, "log", "--all", f"--since={until}", f"--grep=This reverts commit {h}", "--format=%h").strip():
            reverted.append(h)
        files = [f for f in git(cwd, "show", "--name-only", "--format=", h).splitlines() if f.strip()]
        if not files:
            continue
        args = ["log", "--all", f"--since={until}", "--format=%h%x09%s", "--no-merges", "-i", "-E",
                "--grep=fix|revert|hotfix|regress|oops"]
        if horizon:
            args.append(f"--until={horizon}")
        after = git(cwd, *args, "--", *files[:10])
        for l in after.splitlines()[:5]:
            fh, fs = l.split("\t", 1)
            if fh in seen_fixups:
                continue  # one later fix touching several of these files is one fix
            seen_fixups.add(fh)
            fixups.append({"hash": fh, "subject": short(fs, 90), "after": h})
    out["reverted"] = reverted
    out["follow_up_fixes"] = fixups[:GIT_SCAN_LIMIT]
    out["follow_up_truncated"] = len(fixups) > GIT_SCAN_LIMIT
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
OPENER_GAP_SEC = 7200      # a prompt after this much silence starts a fresh brief


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
    coverage = s.get("coverage", {})
    timing_note = (f"; exact timing unavailable for {coverage.get('timing_unknown', 0)} session(s)"
                   if coverage.get("timing_unknown") else "")
    if coverage.get("timing_unknown") == s["sessions"] and s["sessions"]:
        L.append(f"- human turns {s['human_turns']}, assistant msgs {s['assistant_msgs']}; exact timing unavailable")
    else:
        L.append(f"- human turns {s['human_turns']}, assistant msgs {s['assistant_msgs']}, measured active session time {s['duration_min']} min, agent-active {s['agent_active_min']} min, human-wait {s['human_wait_min']} min{timing_note}")
    sp = s["spend"]
    usage_note = (f"; excludes {coverage.get('usage_unknown', 0)} session(s) without usage records"
                  if coverage.get("usage_unknown") else "")
    if coverage.get("usage_unknown") == s["sessions"] and s["sessions"]:
        L.append("- SPEND: unavailable because these transcripts contain no token-usage records")
        L.append("- API-call count, context size, and token totals are also unavailable")
    else:
        L.append(f"- SPEND (list-price estimate from available usage): ${sp['est_cost_usd']:,.2f} total = ${sp['est_cost_main_usd']:,.2f} main + ${sp['est_cost_subagents_usd']:,.2f} subagents{usage_note}")
        L.append(f"- measured API calls {fmt_int(sp['api_calls'])} ({fmt_int(sp['api_calls_main'])} main + {fmt_int(sp['api_calls_subagents'])} subagent), each re-reading {fmt_int(sp['avg_context_per_call'])} tokens of context on average")
        L.append(f"- measured context re-read across all calls: {fmt_int(sp['context_read_tokens'])} tokens. This, not output, is where the money goes.")
        L.append(f"- measured output {fmt_int(s['tokens']['out'])}, cache_create {fmt_int(s['tokens']['cache_create'])}, uncached in {fmt_int(s['tokens']['in'])} (main sessions only)")
    if s.get("unpriced_models"):
        L.append(f"- COST PARTIAL: no list price for {', '.join(s['unpriced_models'])}; "
                 "those tokens are excluded from every dollar figure")
    if coverage.get("usage_unknown", 0) < s["sessions"]:
        L.append("  Do NOT read a high cache ratio as efficiency: it means each call was cheap per token,")
        L.append("  not that there were few calls or small contexts. Cost = calls x context size.")
        if isinstance(s.get("cost_usd"), (int, float)):
            L.append(f"  (Claude Code's own cost-state field reports ${s['cost_usd']:.2f}; it is usually absent or zero - ignore it.)")
    m = s["mechanical"]
    L.append(f"- corrections {m['corrections']}, zero-info retries {m['zero_info_retries']}, nudges {m['nudges']}, frustration turns {m['frustration_turns']}, praise turns {m['praise_turns']}, interrupts {m['interrupts']}, failed agent turns {m['turn_failures']}")
    result_note = (f"; tool-result status unavailable for {coverage.get('tool_results_unknown', 0)} session(s)"
                   if coverage.get("tool_results_unknown") else "")
    compactions_unknown = coverage.get("compactions_unknown", 0)
    if s["sessions"] and compactions_unknown == s["sessions"]:
        compactions_txt = "compactions unavailable for these transcripts (no compaction records in this format)"
    elif compactions_unknown:
        compactions_txt = f"compactions {m['compactions']} (unavailable for {compactions_unknown} session(s))"
    else:
        compactions_txt = f"compactions {m['compactions']}"
    L.append(f"- measured tool errors {m['tool_errors']}, re-read turns {m['re_read_turns']}, sequential read-only runs {m['sequential_readonly_runs']}, {compactions_txt}, denials {m['denials']}{result_note}")
    if s["sessions"] and coverage.get("tool_results_unknown", 0) == s["sessions"]:
        L.append("- tool-output size unavailable for these transcripts")
    else:
        L.append(f"- measured tool output {fmt_int(m['tool_output_chars'])} chars, of which {m['big_tool_outputs']} single results >= {fmt_int(BIG_TOOL_OUTPUT_CHARS)} chars{result_note}")
    L.append(f"- tool batching: largest single message held {m['max_tools_per_message']} tool calls; {m['multi_tool_messages']} messages carried more than one")
    L.append(f"- delegations {m['delegations']} ({m['parallel_delegations']} in parallel batches, {m['sequential_delegation_runs']} sequential run-ons; subagent files {m['subagent_files']}), commits {m['commits']}, --no-verify {m['no_verify']}, force-push {m['force_push']}, sessions committing on a shared branch {m['on_main_with_commits']}")
    L.append(f"- sessions using an IDE plan mode {m['plan_mode_sessions']} (planning *skills* are in the list below)")
    L.append(f"- opening prompts {m['openers']} of {s['human_turns']} turns; average brief quality {s['avg_prompt_quality']} / 5; thin briefs {m['low_quality_openers']}")
    L.append("  (quality is scored only on opening prompts - a terse follow-up inside a live thread is not a bad prompt)")
    L.append("")
    L.append("## Models and effort")
    L.append("- models (full string x assistant messages): " + (", ".join(f"{k} {v}" for k, v in s.get("models", {}).items()) or "-"))
    L.append("- effort levels: " + (", ".join(f"{k} {v}" for k, v in s.get("efforts", {}).items()) or "-"))
    L.append("  (an empty effort list means the transcript never records one, not that effort was default)")
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
    for k, session_count, occurrences in inv["repeated_openers"][:15]:
        L.append(f"- {session_count} sessions, {occurrences} times: {k}")
    if not inv["repeated_openers"]:
        L.append("- none")
    L.append("")
    L.append("## Sessions (sorted by attention score)")
    L.append("")
    L.append("`model`/`effort` are the most common value in that session, release-date suffix stripped. "
             "`briefs` is how many separate task briefs the session carried (2+ = more than one job in one thread).")
    L.append("")
    L.append("| # | tool | model | effort | when | min | turns | briefs | est $ | calls | corr | 0-info | nudge | frust | errs | deleg | attn | clean | title / first prompt |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n, x in enumerate(inv["sessions"]):
        mm = x["mechanical"]
        xsp = x.get("spend", {})
        caps = x.get("capabilities", {})
        when = (x["start"] or "")[:16].replace("T", " ")
        title = short(x["title"] or x["first_prompt"], 70)
        duration = x["duration_min"] if caps.get("exact_timing", True) else "-"
        cost = f"{xsp.get('est_cost_usd', 0):,.0f}" if caps.get("usage", True) else "-"
        if xsp.get("cost_partial"):
            cost += "*"
        calls = fmt_int(xsp.get("api_calls", 0)) if caps.get("usage", True) else "-"
        errors = mm["tool_errors"] if caps.get("tool_results", True) else "-"
        model = short_model(top_key(x.get("models"))) if x.get("models") else "-"
        effort = top_key(x.get("efforts")) or "-"
        briefs = mm.get("briefs_in_session", "-")
        L.append(f"| {n} | {x['tool']} | {model} | {effort} | {when} | {duration} | {x['human_turns']} | {briefs} | {cost} | {calls} | {mm['corrections']} | {mm['zero_info_retries']} | {mm['nudges']} | {mm['frustration_turns']} | {errors} | {mm['delegations']} | {x['attention_score']} | {'y' if x['clean_candidate'] else ''} | {title} |")
    if any(x.get("spend", {}).get("cost_partial") for x in inv["sessions"]):
        L.append("")
        L.append("`*` on est $ = that session ran an unpriced model; its tokens are not in the figure.")
    L.append("")
    L.append("## Clean sessions (endorsement candidates)")
    for n, x in enumerate(inv["sessions"]):
        if x["clean_candidate"]:
            caps = x.get("capabilities", {})
            timing = f"{x['duration_min']} min" if caps.get("exact_timing", True) else "exact time unavailable"
            output = f"out {fmt_int(x['tokens']['out'])}" if caps.get("usage", True) else "token use unavailable"
            L.append(f"- [{n}] {x['tool']} {x['human_turns']} turns, {timing}, {output}: {short(x['title'] or x['first_prompt'], 90)}")
    L.append("")
    if inv["git"]:
        L.append("## Git outcome signals")
        L.append(f"Only the first {GIT_SCAN_LIMIT} commits per session are inspected, and a "
                 f"\"fix\" commit counts as a follow-up only within {FOLLOW_UP_DAYS} days. "
                 "`+` means the list hit that cap - it is a floor, not a count.")
        for n, g in inv["git"].items():
            x = inv["sessions"][int(n)]
            nf = len(g["follow_up_fixes"])
            L.append(f"- [{n}] {short(x['title'] or x['first_prompt'], 60)}: commits {g['commits_total']}"
                     f"{' (only first ' + str(GIT_SCAN_LIMIT) + ' inspected)' if g['commits_truncated'] else ''}"
                     f", reverted {g['reverted'] or 'none'}, follow-up fixes {nf}{'+' if g.get('follow_up_truncated') else ''}")
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
            L.append("Per turn: `t<i> <ts> OPEN|cont [flags] q<score> <missing context elements> : prompt`.")
            L.append("`missing` lists what the prompt lacked: path, error, code, criteria, intent.")
            L.append("`OPEN` = an opening prompt (session start, or after a 2h+ break); judge these as task")
            L.append("briefs. `cont` = a follow-up inside a live thread - terse is fine there, so only call it")
            L.append("out if it is a retry that never says what went wrong.")
        elif group == "b":
            L.append("Per turn: agent seconds, human wait, assistant msgs, tools, delegations, sequential read-only runs.")
            L.append("`deleg N/Ppar/Sseq`: N delegate calls, P of them issued in a parallel batch, S consecutive")
            L.append("single-delegate messages. `maxT` is the most tools one message carried, `multiT` how many")
            L.append("messages carried more than one - low values with high turn counts mean no batching.")
        elif group == "c":
            L.append("Per turn: tool errors by tool, commits, churned files, hard-fail flags. Git outcome per session.")
            L.append(f"`out` is total tool-result characters for the turn; `big` counts single results >= {fmt_int(BIG_TOOL_OUTPUT_CHARS)} chars. `?` = not recorded.")
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
            caps = x.get("capabilities", {})
            L.append(f"## [{n}] {x['tool']} {x['session_id']} - {short(x['title'] or x['first_prompt'], 70)}")
            unavailable = [label for key, label in (
                ("usage", "cost and token use"),
                ("exact_timing", "exact timing"),
                ("tool_results", "tool-result and tool-error status"),
            ) if not caps.get(key, True)]
            if unavailable:
                L.append(f"- transcript does not record: {', '.join(unavailable)}")
            L.append(f"- models: {x.get('models') or 'none recorded'}; efforts: {x.get('efforts') or 'none recorded'}")
            if group == "a":
                L.append(f"- {x['human_turns']} turns ({mm['openers']} opening), avg brief quality {x['avg_prompt_quality']}/5, corrections {mm['corrections']}, retries with no new info {mm['zero_info_retries']}")
                L.append(f"- rule files in force: {', '.join(rule_files(x['cwd'])) or 'none found'}")
            elif group == "b":
                xsp = x.get("spend", {})
                if caps.get("exact_timing", True):
                    L.append(f"- span {x.get('span_hours')} h, active {x['duration_min']} min, agent-active {round((x['agent_active_sec'] or 0)/60)} min, human-wait {round((x['human_wait_sec'] or 0)/60)} min, long gaps {x['long_gaps']}")
                else:
                    L.append(f"- prompt span {x.get('span_hours')} h; active time and waiting time unavailable")
                if caps.get("usage", True):
                    partial = (f"; PARTIAL - no list price for {', '.join(xsp.get('unpriced_families', []))}"
                               if xsp.get("cost_partial") else "")
                    L.append(f"- est ${xsp.get('est_cost_usd', 0):,.2f} (${xsp.get('est_cost_subagents_usd', 0):,.2f} of it in subagents) over {fmt_int(xsp.get('api_calls', 0))} calls, avg context per call {fmt_int(xsp.get('avg_context_per_call', 0))} tokens{partial}")
                else:
                    L.append("- cost, API-call count, and context size unavailable")
                compactions = mm["compactions"] if caps.get("compactions", True) else "unavailable"
                L.append(f"- delegations {mm['delegations']} ({mm['parallel_delegations']} in parallel batches, {mm['sequential_delegation_runs']} sequential run-ons; subagent files {mm['subagent_files']}), sequential read-only runs {mm['sequential_readonly_runs']}, max tools per message {mm['max_tools_per_message']}, multi-tool messages {mm['multi_tool_messages']}, briefs in session {mm['briefs_in_session']}, compactions {compactions}")
                L.append(f"- IDE plan mode used: {mm['plan_mode_used']} (this is NOT planning skills - check `skills attributed` in summary.md before claiming the user never plans)")
                L.append(f"- permission mode per turn: {x['permission_modes'] or 'none recorded'}; mode-switch events during the session: {x.get('permission_mode_changes') or 'none'}")
                L.append(f"- tools: {x['tools']}")
            elif group == "c":
                tool_errors = mm["tool_errors"] if caps.get("tool_results", True) else "unavailable"
                tool_out = (f"{short_chars(mm['tool_output_chars'])} chars in tool output, {mm['big_tool_outputs']} results >= {fmt_int(BIG_TOOL_OUTPUT_CHARS)} chars"
                            if caps.get("tool_results", True) else "tool-output size unavailable")
                L.append(f"- tool errors {tool_errors}, {tool_out}, failed agent turns {mm['turn_failures']}, denials {mm['denials']}, commits {mm['commits']}, churned files {mm['edit_churn_files'] or 'none'}, lines +{x['lines_added']}/-{x['lines_removed']}")
                L.append(f"- branches seen: {x.get('branches') or 'none'}; commits were made on: {mm.get('commit_branches') or 'none'}")
                L.append(f"- hard-fail: --no-verify {mm['no_verify']}, force-push {mm['force_push']}, committed on a shared branch {mm['on_main_with_commits']}")
                L.append(f"- skills attributed: {x['skills_attributed'] or 'none'}")
                g = inv.get("git", {}).get(str(n))
                if g:
                    L.append(f"- git: {g['commits_total']} commits in window {[c['hash'] for c in g['commits_in_window']]}"
                             f"{' (only first ' + str(GIT_SCAN_LIMIT) + ' inspected)' if g['commits_truncated'] else ''}")
                    L.append(f"- git: reverted {g['reverted'] or 'none'}; follow-up fixes within {g['follow_up_window_days']} days "
                             f"{[f['hash'] for f in g['follow_up_fixes']] or 'none'}{' (capped - floor, not a count)' if g.get('follow_up_truncated') else ''}")
                if x["outcome_pending"]:
                    L.append("- OUTCOME PENDING (<24h old): do not claim outcomes for this session")
            else:
                xsp = x.get("spend", {})
                timing = f"active {x['duration_min']} min" if caps.get("exact_timing", True) else "exact time unavailable"
                cost = (f"est ${xsp.get('est_cost_usd', 0):,.2f} over {fmt_int(xsp.get('api_calls', 0))} calls"
                        if caps.get("usage", True) else "cost unavailable")
                L.append(f"- {x['human_turns']} turns, {timing}, {cost}, praise {mm['praise_turns']}, corrections {mm['corrections']}, clean {x['clean_candidate']}")
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
                    L.append(f"  - t{t['i']} {t['ts']} {'OPEN' if t.get('is_opener') else 'cont'} [{f}] q{q['score']} missing:{missing} : {short(t['text'], 240)}")
                elif group == "b":
                    agent = t["agent_seconds"] if caps.get("exact_timing", True) else "?"
                    wait = t["human_wait_seconds"] if caps.get("exact_timing", True) else "?"
                    L.append(f"  - t{t['i']} {t['ts']} [{f}] agent {agent}s wait {wait}s msgs {t['assistant_msgs']} deleg {t['delegations']}/{t['parallel_delegations']}par/{t['sequential_delegation_runs']}seq seqRO {t['sequential_readonly_runs']} maxT {t['max_tools_per_message']} multiT {t['multi_tool_messages']} tools {t['tools']} : {short(t['text'], 80)}")
                elif group == "c":
                    errors = t["tool_errors"] if caps.get("tool_results", True) else "?"
                    big = f" big {t['big_tool_outputs']}" if t.get("big_tool_outputs") else ""
                    L.append(f"  - t{t['i']} {t['ts']} [{f}] errs {errors}{' ' + str(t['error_tools']) if t['error_tools'] else ''} out {short_chars(t['tool_result_chars'])}{big} turn-fail {t['turn_failures']} commits {t['commits']} churn {t['edit_churn_files'] or '-'} tools {t['tools']} : {short(t['text'], 120)}")
                else:
                    agent = t["agent_seconds"] if caps.get("exact_timing", True) else "?"
                    output = t["tokens"]["out"] if caps.get("usage", True) else "?"
                    L.append(f"  - t{t['i']} {t['ts']} [{f}] q{t['quality']['score']} agent {agent}s msgs {t['assistant_msgs']} out {output} deleg {t['delegations']} : {short(t['text'], 200)}")
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
    mech_keys = ["tool_errors", "turn_failures", "corrections", "zero_info_retries", "nudges", "frustration_turns", "praise_turns", "interrupts",
                 "re_read_turns", "sequential_readonly_runs", "compactions", "delegations", "subagent_files", "commits", "no_verify",
                 "force_push", "openers", "low_quality_openers", "multi_tool_messages", "parallel_delegations",
                 "sequential_delegation_runs", "tool_output_chars", "big_tool_outputs", "briefs_in_session"]
    mech = {k: sum((s.get("mechanical", {}).get(k, 0) or 0) for s in sessions) for k in mech_keys}
    mech["max_tools_per_message"] = max([(s.get("mechanical", {}).get("max_tools_per_message") or 0) for s in sessions] or [0])
    mech["multi_brief_sessions"] = sum(1 for s in sessions if (s.get("mechanical", {}).get("briefs_in_session") or 0) >= 2)
    mech["denials"] = sum(sum(s.get("mechanical", {}).get("denials", {}).values()) for s in sessions)
    mech["plan_mode_sessions"] = sum(1 for s in sessions if s.get("mechanical", {}).get("plan_mode_used"))
    mech["on_main_with_commits"] = sum(1 for s in sessions if s.get("mechanical", {}).get("on_main_with_commits"))
    tools = Counter()
    skills_attr = Counter()
    skill_calls = Counter()
    slashes = Counter()
    models = Counter()
    efforts = Counter()
    # an opener repeated inside one session is a retry loop; repeated across
    # sessions it is a habit worth turning into a skill - count them separately
    opener_hits = Counter()
    opener_sessions = defaultdict(set)
    for n, s in enumerate(sessions):
        tools.update(s.get("tools", {}))
        skills_attr.update(s.get("skills_attributed", {}))
        skill_calls.update(s.get("skill_tool_calls", {}))
        slashes.update(s.get("slash_commands", {}))
        models.update(s.get("models", {}))
        efforts.update(s.get("efforts", {}))
        for t in s.get("turns", []):
            words = re.findall(r"\w+", t["text"].lower())[:4]
            if len(words) >= 3 and not t["flags"]["nudge"]:
                key = " ".join(words)
                opener_hits[key] += 1
                opener_sessions[key].add(n)
    repeated_openers = sorted(
        ((k, len(opener_sessions[k]), v) for k, v in opener_hits.items() if len(opener_sessions[k]) >= 2),
        key=lambda r: (-r[1], -r[2], r[0]),
    )[:30]
    q_vals = [s["avg_prompt_quality"] for s in sessions if s.get("avg_prompt_quality") is not None]
    costs = [s["cost_usd"] for s in sessions if isinstance(s.get("cost_usd"), (int, float))]
    sp_keys = ("est_cost_usd", "est_cost_main_usd", "est_cost_subagents_usd", "api_calls",
               "api_calls_main", "api_calls_subagents", "context_read_tokens")
    spend_tot = {k: round(sum((s.get("spend", {}).get(k, 0) or 0) for s in sessions), 2) for k in sp_keys}
    spend_tot["avg_context_per_call"] = (round(spend_tot["context_read_tokens"] / spend_tot["api_calls"])
                                         if spend_tot["api_calls"] else 0)
    coverage = {
        "usage_unknown": sum(1 for s in sessions if not s.get("capabilities", {}).get("usage", True)),
        "timing_unknown": sum(1 for s in sessions if not s.get("capabilities", {}).get("exact_timing", True)),
        "tool_results_unknown": sum(1 for s in sessions if not s.get("capabilities", {}).get("tool_results", True)),
        "compactions_unknown": sum(1 for s in sessions if not s.get("capabilities", {}).get("compactions", True)),
        "pricing_partial": sum(1 for s in sessions if not s.get("capabilities", {}).get("pricing", True)),
    }
    unpriced_models = sorted({m for s in sessions for m in s.get("spend", {}).get("unpriced_families", [])})
    summary = {
        "sessions": len(sessions), "by_tool": dict(Counter(s["tool"] for s in sessions)), "skipped_trivial": skipped,
        "human_turns": sum(s.get("human_turns", 0) for s in sessions), "assistant_msgs": sum(s.get("assistant_msgs", 0) for s in sessions),
        "duration_min": round(sum(s.get("duration_min") or 0 for s in sessions)),
        "agent_active_min": round(sum(s.get("agent_active_sec") or 0 for s in sessions) / 60),
        "human_wait_min": round(sum(s.get("human_wait_sec") or 0 for s in sessions) / 60),
        "tokens": {k: agg(k) for k in ("in", "out", "cache_read", "cache_create")},
        "spend": spend_tot,
        "cost_usd": sum(costs) if costs else None,
        "mechanical": mech, "tools": dict(tools.most_common(20)),
        "skills_attributed": dict(skills_attr.most_common(20)), "skill_tool_calls": dict(skill_calls.most_common(20)),
        "slash_commands": dict(slashes.most_common(20)),
        "models": dict(models.most_common(20)), "efforts": dict(efforts.most_common(20)),
        "avg_prompt_quality": round(sum(q_vals) / len(q_vals), 2) if q_vals else None,
        "coverage": coverage, "unpriced_models": unpriced_models,
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
        "summary": summary, "repeated_openers": repeated_openers,
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
