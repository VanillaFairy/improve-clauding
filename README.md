# improve-clauding

Retro over your recent agent sessions (Claude Code and Cursor). Subject: your own habits.
Agent, tool and model failures are routed to proposals instead of being blamed on you.

Output per retro: axis scores (token efficiency, actionable reusability, wall-clock,
intelligence), up to 10 patterns to fix, up to 5 to endorse, hard-fail flags,
follow-through on the previous retro's recommendations, and a numbered list of proposals
(personal/project rules, skill patches, new skills, agents, hooks). Nothing is applied
automatically.

## Install

Claude Code: the plugin is listed in the `vanillafairy` directory marketplace
(`c:\work\claude\vanillafairy\.claude-plugin\marketplace.json`):

```
/plugin install improve-clauding@vanillafairy
```

Cursor: `~/.cursor/plugins/local/improve-clauding` is a directory junction to this
folder, so both tools read the same files.

## Usage

```
/improve-clauding:improve-clauding
```

That's it. No arguments needed - it covers everything since your last retro.

Optional: a number for the last N sessions (`10`), `--since 2026-09-01`, `--all`, or
lens words to run only one analyst group (`prompts`, `delegation`, `skills`, `endorse`).

## Elaboration

### Layout

```
skills/improve-clauding/
  SKILL.md                 orchestrator (8-step workflow) + token budget
  scripts/inventory.py     deterministic pre-pass: discovery, metrics, flags, state (stdlib Python 3)
  scripts/excerpt.py       bounded window into one turn; the only way to touch a transcript
  references/axes.md       what "improve" means; per-axis signals; tensions; north star
  references/lenses.md     12 lenses in 4 analyst groups; attribution; root-cause step; ranking
  references/destinations.md  rule / skill / agent / hook decision and proposal format
  references/report-template.md
agents/lens-analyst.md     read-only analyst subagent, one per lens group
commands/improve-clauding.md   /improve-clauding:improve-clauding
```

### Inputs

- `~/.claude/projects/**/*.jsonl` (main sessions; `subagents/` counted for delegation)
- `~/.cursor/projects/*/agent-transcripts/*.jsonl` (parser is shape-tolerant; format unverified until first file)
- `~/.claude/CLAUDE.md`, project `CLAUDE.md` / `AGENTS.md` / `.cursor/rules`
- installed skill names under `~/.claude/skills`, `~/.claude/plugins/cache`, `~/.cursor/skills`, `~/.cursor/plugins/local`, `~/.agents/skills`
- git history of session `cwd`s (commits in window, reverts, follow-up fixes)
- `~/.improve-clauding/notes.md` - your own notes between retros (optional, high signal)
- previous reports in `~/.improve-clauding/reports/`

### State

`~/.improve-clauding/state.json` records covered sessions and past retros.
Each pre-pass writes `runs/<timestamp>/` containing `summary.md` (~5 KB),
four disjoint `slice-*.md` files (8-15 KB each), and `inventory.json` (the full record).

```
python skills/improve-clauding/scripts/inventory.py --status
python skills/improve-clauding/scripts/inventory.py --last 10 --no-git
python skills/improve-clauding/scripts/excerpt.py --run-dir <run> --ref 3/12
```

### Token discipline

The retro is judged on its own axis 1, so context is budgeted rather than trusted:

- The shared digest is small (`summary.md`, ~1.5k tokens) and carries no turn detail.
- Turn detail is split into four **disjoint** slices, one per lens group, so four analysts
  cost about what one would - not 4x the same 17k-token digest.
- Transcripts are never read. They run from ~124k to ~1.2M tokens each. `excerpt.py`
  prints a hard-capped window (prompt, tool calls, error bodies) for one turn.
- Slices are capped at 10 sessions x 12 turns; `excerpt.py` at 8000 chars per call,
  15 calls per analyst.
- Whole retro target: under ~50k tokens in the main context.

Token totals are deduplicated by message id: Claude Code writes one JSONL record per
content block and repeats the full `usage` in each, so naive summing inflates output
tokens about 2x.

### Report style

The report is written for a human, so the skill's internal vocabulary stops at the
report boundary. Words like "axis", "attribution", "recurrence" and inventory field
names are banned from the page; findings are stated as sentences a person would say out
loud, each with one real quote and one concrete thing to do differently. Caps: 150 lines,
6 things to fix, 3 to keep. See `references/report-template.md`.

### Measurement caveats the script handles for you

- Spend is estimated from token usage at list prices, because Claude Code's own
  `cost-state` field is almost always absent or zero (2 nonzero records in a 92-session
  corpus, summing to $18 against a real ~$2,400).
- Subagent transcripts are scanned for usage and billed to their parent session. They were
  26% of spend in the first measured window and are invisible in the main transcript.
- Cost is reported as dollars, calls, and average context per call, because spend is
  `calls x context size`. A high cache ratio is explicitly flagged as *not* efficiency.
- Token totals are deduplicated by message id (naive summing inflates them ~2x).
- Prompt quality is scored only on *opening* prompts (session start, or after a 2h+
  break). A terse follow-up inside a live thread is not a bad prompt.
- Permission modes are counted once per turn; mode-switch events are reported separately.
- Committing on a shared branch is judged by the branch recorded at the commit call, not
  at session start.
- Git follow-up fixes only count within 14 days of the session, and capped lists are
  marked as floors rather than counts.
- "Claude Code plan mode" is the IDE mode, not the planning skills; the slices say so.

### Design notes

- Two layers: the script measures, the LLM classifies. Script flags are pointers, not findings.
- Every finding: lens, axis moved, axis cost, attribution, recurrence, quoted evidence.
- Sessions younger than 24h are outcome-pending; no outcome claims for them.
- Prior art borrowed from: florianbuetow/claude-code retrospective (feedback loop, "ask why",
  scoring), netresearch/retro-skill (mechanical pre-pass + LLM, destinations, proposal cap,
  outcome mode), mgsa1/retrospective-skill (zero-information retries, prompt rewrites,
  git correlation), hancengiz/prompt-coach (prompt rubric).
