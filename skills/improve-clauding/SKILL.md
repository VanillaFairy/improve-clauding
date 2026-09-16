---
name: improve-clauding
description: Retrospective over the user's recent agent sessions (Claude Code and Cursor) that separates the user's own habits from agent, tool, and model failures, then reports patterns to fix and patterns to endorse along four axes - token efficiency, actionable reusability, wall-clock time, intelligence optimization - with evidence and concrete proposals (rules, skill patches, new skills, agents, hooks) that are never applied automatically. Use when the user says "retro", "improve-clauding", "review my sessions", "how am I using Claude/Cursor", "what should I extract into a skill", or asks to improve their prompting or agent workflow habits.
disable-model-invocation: true
---

# improve-clauding

Retro over N sessions since the last retro. The user's habits are the subject. Agent, tool,
and model failures are routed to proposals, not blamed on the user.

Read first, in this order: `references/axes.md`, `references/lenses.md`. Read
`references/destinations.md` when writing proposals and `references/report-template.md`
when writing the report.

State and outputs live in `~/.improve-clauding/` (`state.json`, `runs/`, `reports/`,
optional `notes.md` the user appends to between retros).

## Arguments

`improve-clauding [N | --since DATE | --all] [lens words]`

- No argument: sessions not covered by a previous retro.
- `N`: last N sessions. `--since 2026-09-01`: by modification date. `--all`: everything.
- Lens words (e.g. `prompts`, `delegation`, `skills`, `endorse`): run only the matching
  analyst group from lenses.md. Default: all four groups.

## Workflow

Copy this checklist and track it:

```
- [ ] 1 inventory pre-pass (script)
- [ ] 2 read digest, previous report, notes
- [ ] 3 lens analysis (4 analysts, evidence-anchored)
- [ ] 4 root cause + attribution filter
- [ ] 5 rank, cap, score axes
- [ ] 6 follow-through on previous recommendations
- [ ] 7 write report + proposals (nothing applied)
- [ ] 8 commit state, present digest
```

### 1. Inventory pre-pass

Run from this skill's directory (`scripts/inventory.py` is stdlib Python 3; on Windows use
`python`, elsewhere `python3`):

```
python scripts/inventory.py            # since last retro
python scripts/inventory.py --last 10
python scripts/inventory.py --since 2026-09-01
```

It prints the run dir with `inventory.md` (digest) and `inventory.json` (per-turn detail).
If it reports 0 sessions, tell the user and stop. Do not re-implement the parsing in shell
calls; if the script fails, fix the script.

The script measures and flags. It does not classify. Flags (`correction`,
`zero_info_retry`, `nudge`, `frustration`, `praise`, `near_repeat`, `interrupted`) and
the prompt-quality score are heuristics; treat them as pointers to read, not as findings.

### 2. Read context

- `inventory.md` in full.
- Previous report: `python scripts/inventory.py --previous` prints its path. Read it if present.
- `~/.improve-clauding/notes.md` if present (the user's own mid-work notes; highest-signal input).
- `~/.claude/CLAUDE.md` and, for projects that appear in the inventory, their `CLAUDE.md` /
  `AGENTS.md` / `.cursor/rules/`. Needed to distinguish "no rule existed" from "rule ignored".

### 3. Lens analysis

Dispatch four analysts in parallel, one per group in lenses.md (A communication,
B orchestration, C correctness, D endorsement+trend). In Claude Code use the
`lens-analyst` agent from this plugin; in Cursor use a general-purpose subagent with the
same prompt. If subagents are unavailable, run the four groups sequentially yourself.

Each analyst gets: the run dir path, its group letter, the paths of `axes.md` and
`lenses.md`, the previous report path (group D), and the instruction to open session JSONL
files around flagged timestamps for context. Budget: at most 10 sessions read in depth
per analyst, chosen by `attention_score` (A, B, C) or `clean_candidate` (D).

Each analyst returns a list of candidate findings in this shape:

```
- lens: <n. name> | axis moved: <axis> | axis cost: <axis|none> | attribution: user|agent|env|model
  recurrence: <k sessions> [s/t], [s/t]
  evidence: "<quote <=200 chars>" (session <id>, <timestamp>)
  observation: <one sentence, what happened>
  candidate fix: <one sentence>
```

Analysts do not rank and do not write proposals.

### 4. Root cause and attribution

For every candidate: why does it recur, systemic or one-off, which existing strength
addresses it (lenses.md, "Root-cause step"). Drop one-offs unless hard-fail. Merge
duplicates across analysts. Findings attributed to `agent`, `env`, or `model` become
proposals attached to a pattern; they are not listed as user habits.

### 5. Rank and score

score = recurrence x impact on the moved axis. Cap: 10 patterns to fix, 5 to endorse,
all hard-fail flags. Score each axis 1-5 with a one-line reason. Compute the north star
(axes.md). Every claim that quality held or dropped needs a pointer to evidence.

### 6. Follow-through

For each recommendation in the previous report: adopted / partial / not adopted / unknown,
with evidence from this window (a rule now present, a skill now triggering, a pattern's
recurrence count dropping). Unknown is allowed; guessing is not.

### 7. Report and proposals

Write `~/.improve-clauding/reports/YYYY-MM-DD-retro-NN.md` from the template. Proposals
follow destinations.md: destination, target path, exact content. Skill patches target the
source directory, never a plugin cache. Do not apply anything. Do not edit CLAUDE.md,
rules, skills, or hooks during the retro, even if asked to "just do it" - finish the
report, then the user can request application as a separate step.

### 8. Commit and present

```
python scripts/inventory.py --commit --report <report path>
```

Then present to the user: the axis scores with deltas, the top 3 patterns to fix, the
top 2 to endorse, hard-fail flags, and the numbered proposal list. Ask which proposals
to apply. Do not paste the whole report.

## Guardrails

- Evidence or it did not happen: every pattern quotes a real turn with session id and timestamp.
- No generic advice. If a finding would be true of any developer, drop it.
- No recycled observations: a pattern already reported last time is listed under
  follow-through, not as new, unless its cause changed.
- The user's tone is a locator for hot spots, not a finding.
- Sessions younger than 24h are marked outcome-pending; do not claim outcomes for them.
- Cursor transcript format is unverified until the first file appears; if parsing yields
  zero turns for a Cursor file, report it as a gap and continue.
- Reports contain code and paths; keep them under `~/.improve-clauding/`, never in a repo.
