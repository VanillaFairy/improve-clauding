---
name: improve-clauding
description: Retrospective over the user's recent agent sessions (Claude Code and Cursor) that separates the user's own habits from agent, tool, and model failures, then reports patterns to fix and patterns to endorse along six axes - cost, wall-clock, intelligence, reliability, human attention, reusability - with evidence and concrete proposals (rules, skill patches, new skills, agents, hooks) that are never applied automatically. Use when the user says "retro", "improve-clauding", "review my sessions", "how am I using Claude/Cursor", "what should I extract into a skill", or asks to improve their prompting or agent workflow habits.
disable-model-invocation: true
---

# improve-clauding

Retro over N sessions since the last retro. The user's habits are the subject. Agent, tool,
model, and automatic-routing failures are routed to proposals, not blamed on the user.

Read first, in this order: `references/axes.md`, `references/lenses.md`,
`references/harness.md`. Read `references/destinations.md` when writing proposals and
`references/report-template.md` when writing the report.

Findings are classified on two closed lists: six axes (the outcome that got worse) and
fifteen aspects (the lever that moved it), both defined in `axes.md`. Claude Code and
Cursor do not record the same things, and three signals imply opposite advice on the two;
`harness.md` is not optional reading.

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

It prints the run dir and the size of each file it wrote:

- `summary.md` - totals and the session table. Shared. Read this.
- `slice-{a,b,c,d}-*.md` - per-lens-group turn detail, disjoint. Each analyst reads one.
- `inventory.json` - the full record. Never read whole; `excerpt.py` indexes it.

If it reports 0 sessions, tell the user and stop. Do not re-implement the parsing in shell
calls; if the script fails, fix the script.

Before continuing, check whether the selected material is genuinely newer than the previous
retro. A copied, resumed, or re-indexed session is not new when its useful turns were already
reviewed. If an old session has only a later outcome, mention that outcome separately; do not
count the session again or use its old turns to judge whether the user followed later advice.
Evidence of follow-through must be newer than the advice.

If no new work remains after this check, tell the user: "No big changes since last time."
Add one plain sentence about any important later outcome, then stop. Do not write or commit
another report.

The script measures and flags. It does not classify. Flags (`correction`,
`zero_info_retry`, `nudge`, `frustration`, `praise`, `near_repeat`, `interrupted`) and
the prompt-quality score are heuristics; treat them as pointers to read, not as findings.

### 2. Read context

- `summary.md`. Not the slices - the analysts own those - and not `inventory.json`.
- Previous report: `python scripts/inventory.py --previous` prints its path. Read it if present.
- `~/.improve-clauding/notes.md` if present (the user's own mid-work notes; highest-signal input).
- `~/.claude/CLAUDE.md` and, for projects that appear in the inventory, their `CLAUDE.md` /
  `AGENTS.md` / `.cursor/rules/`. Needed to distinguish "no rule existed" from "rule ignored".

### 3. Lens analysis

Dispatch four analysts in parallel, one per group in lenses.md (A communication,
B orchestration, C correctness, D endorsement+trend). In Claude Code use the
`lens-analyst` agent from this plugin; in Cursor use a general-purpose subagent with the
same prompt. If subagents are unavailable, run the four groups sequentially yourself.

Each analyst gets exactly: its group letter, the path of its own slice file, the path of
`summary.md`, the paths of `axes.md`, `lenses.md` and `harness.md`, and the run dir (for
`excerpt.py`). Nothing else. Do not paste slice contents into the prompt; pass paths.

Context budget per analyst, enforced in the agent definition:

- its slice (~3k tokens) + `summary.md` (~1.5k) + `axes.md` + `lenses.md` + `harness.md` (~4.5k)
- at most 15 `excerpt.py` calls, default cap 8000 chars each

Never read a session `.jsonl` directly. The median transcript here is ~124k tokens and the
largest is ~1.2M; one such read wrecks the retro. `excerpt.py` gives a bounded window:

```
python scripts/excerpt.py --run-dir <run dir> --ref 3/12 --ref 5/0
python scripts/excerpt.py --run-dir <run dir> --ref 3/12 --context 1
```

Each analyst returns a list of candidate findings in this shape:

```
- lens: <n. name> | axis: <axis> | aspect: <aspect> | attribution: user|agent|env|model|router
  harness: claude-code|cursor|both
  sessions: <k distinct> [s/t], [s/t]
  evidence: "<quote <=200 chars>" (session <id>, <timestamp>)
  observation: <one sentence, what happened, with a number>
  candidate fix: <one sentence, naming the mechanism that exists on that harness>
```

Axis and aspect come from the closed lists in `axes.md` and the pairing must be legal per
its matrix. Reject any finding that invents a term, pairs illegally, or uses an aspect that
`harness.md` marks unobservable for that session's harness - send it back rather than
repairing it yourself, since the analyst saw the evidence and you did not.

Analysts do not rank and do not write proposals.

### 4. Root cause and attribution

For every candidate: why does it recur, systemic or one-off, which existing strength
addresses it (lenses.md, "Root-cause step"). Drop one-offs unless hard-fail. Merge
duplicates across analysts. Findings attributed to `agent`, `env`, `model`, or `router`
become proposals attached to a pattern; they are not listed as user habits. When such a
finding does reach the report, it carries the `not your doing` marker and its sentence must
not say the user did the thing.

### 5. Rank and score

score = sessions x impact x severity, where sessions is the distinct-session count (not the
occurrence count), impact is the dollars, turns, or waiting time saved per occurrence on
the named axis, and severity is 1 normally and higher for data loss, a shared-branch
commit, a force push, or a bypassed hook. Cap: 10 patterns to fix, 5 to endorse.

Hard-fail flags are reported regardless of score and are never ranked away. Risk is this
severity multiplier, not an axis of its own.

Score an axis 1-5 with a one-line reason **only when this window had evidence for it**. An
axis the window could not measure gets no rating and no row - say it was unmeasurable
instead. Guessing a rating to fill the table is the same error as guessing a finding.

Compute the north star in the form `axes.md` specifies for the harness, and never compare
the two forms against each other. Every claim that quality held or dropped needs a pointer
to evidence.

### 6. Follow-through

For each recommendation in the previous report: adopted / partial / not adopted / unknown,
with evidence from this window (a rule now present, a skill now triggering, a pattern's
recurrence count dropping). Unknown is allowed; guessing is not.

### 7. Report and proposals

Write `~/.improve-clauding/reports/YYYY-MM-DD-retro-NN.md` following
`references/report-template.md` exactly, including its writing rules.

The report is for a human reader, so the internal vocabulary of this skill stops here.
Do not write "axis", "aspect", "attribution", "recurrence", "lens", "north star",
"hard-fail", "zero-information retry" or field names from the inventory in the report.
Translate them into plain sentences. Cap: 150 lines, 6 items to fix, 3 to keep. Rank and
drop the rest; do not append everything you found.

One deliberate exception: each "Worth fixing" item opens with its axis and aspect **labels**
and its session count, in the two-line format `report-template.md` specifies. The labels
are allowed on the page; the words "axis" and "aspect" are not. Attribution reaches the
page only as the `not your doing: <cause>` marker, and only when the cause was not the user.

Two standing requirements from the user, on top of the template:

- Every recommendation states its expected gain in dollars, turns, or waiting time, derived
  from what the finding cost in this window. Turns and minutes are first-class units, not
  apologies: use them whenever token usage was not recorded or the model had no list price.
- Habits come first. Tooling is secondary: keep a tooling item only where it directly caused
  a habit's cost, and write it as the habit. See "What to keep when trimming".

Proposals follow destinations.md and are listed once, at the end, one line each. Skill
patches target the source directory, never a plugin cache. Do not apply anything. Do not
edit CLAUDE.md, rules, skills, or hooks during the retro, even if asked to "just do it" -
finish the report, then the user can request application as a separate step.

Before saving, reread the draft as the user: if a sentence needs the skill's own
terminology to parse, rewrite it.

Use language that a person would use in a normal work conversation. Never expose process
terms such as "eligible sessions", "coverage window", "selection cutoff", "follow-through
evidence", or "outcome update". Describe what happened instead:

- "No big changes since last time", not "No new eligible sessions."
- "I cannot tell yet whether you tried this", not "There is no post-retro evidence."
- "An older task needed one later cleanup", not "A covered session has a new outcome."

### 8. Commit and present

```
python scripts/inventory.py --commit --report <report path>
```

Then tell the user, in plain sentences and under 15 lines: the one thing most worth
changing, the next two after it, the best thing they did, anything unsafe, and the
numbered list of things you can set up. Link the report path. Do not paste the report.

## Token budget

The retro is judged on the same Cost axis it reports, so it stays cheap. Measured on a
20-session window:

| stage | cost |
|---|---|
| orchestrator: `summary.md` + references + template | ~5k tokens |
| each analyst: slice + summary + 3 references | ~9k tokens |
| each analyst: up to 15 excerpts at 8k chars | up to ~30k tokens |
| 4 analysts in parallel | ~28k shared + excerpt usage, in their own contexts |
| orchestrator: 4 finding lists back | ~6k tokens |

The whole retro should land under ~50k tokens in the main context. If a window is so large
that `summary.md` exceeds ~10k tokens, split the retro by date range instead of raising
budgets. Slices are capped at 10 sessions and 12 turns per session by the script; raise
`SESSIONS_PER_SLICE` / `TURNS_PER_SESSION` in `inventory.py` only deliberately.

## Guardrails

- Evidence or it did not happen: every pattern quotes a real turn with session id and timestamp.
- No generic advice. If a finding would be true of any developer, drop it.
- No recycled observations: a pattern already reported last time is listed under
  follow-through, not as new, unless its cause changed.
- The user's tone is a locator for hot spots, not a finding.
- Capped lists are floors, not counts. The inventory inspects at most 10 commits per
  session and marks truncated lists with `+` or "capped". Never present a cap as a
  measurement ("10 follow-up fixes, the highest in the window" is a bug, not a finding).
- A shared-branch commit flag comes from the branch recorded at the commit call. If a
  session started on `master` and moved to a feature branch, that is not a violation.
- Sessions younger than 24h are marked outcome-pending; do not claim outcomes for them.
- Cursor transcripts record prompts, assistant messages, tool calls, and failed turns. They
  do not currently record token usage, exact assistant timing, or tool results. Treat those
  values as unavailable, never as zero. If parsing yields zero turns, report the gap and
  continue.
- Absence of a signal is never evidence of health. A field reading `unavailable` means
  unmeasured. Cursor sessions report no compactions because the records do not exist, not
  because the context was healthy, and the script marks this through
  `capabilities.compactions`. The same applies to `capabilities.usage`, `exact_timing`,
  `tool_results`, `cwd` and `pricing`.
- Check `spend.cost_partial` before quoting any dollar figure. Models with no entry in
  `PRICES` contribute no dollars and are listed in `spend.unpriced_families`; the total
  then means "everything except those". Never price an unknown model by analogy.
- Three signals invert between harnesses - long sessions, compactions, and many short
  sessions. See `harness.md` before turning any of them into advice; the wrong way round is
  worse than silence.
- A remedy must name a mechanism the session's harness actually has. `/clear`, `/compact`,
  `/rewind` and `/effort` do not exist in Cursor; `harness.md` carries the translations.
- When a model may have been chosen automatically rather than by the user, attribute it to
  `router` and write it as a setup change. Nothing in the transcript distinguishes a router
  choice from a deliberate one, so "you used model X" is not a safe sentence.
- The script detects only three unsafe patterns: `--no-verify`, force push, and commits on
  a shared branch. It has no secret detection and no destructive-command detection. Never
  report that a window was clean on those.
- Reports contain code and paths; keep them under `~/.improve-clauding/`, never in a repo.
- Token counts come from `usage` records deduplicated by message id; one API message is
  written as several JSONL records that each repeat the full usage. Do not re-derive token
  totals by summing records yourself - you will inflate them roughly 2x.
