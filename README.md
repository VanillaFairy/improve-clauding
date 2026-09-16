# vf-improve-clauding

Retro over your recent agent sessions (Claude Code and Cursor). Subject: your own habits.
Agent, tool and model failures are routed to proposals instead of being blamed on you.

Output per retro: axis scores (token efficiency, actionable reusability, wall-clock,
intelligence), up to 10 patterns to fix, up to 5 to endorse, hard-fail flags,
follow-through on the previous retro's recommendations, and a numbered list of proposals
(personal/project rules, skill patches, new skills, agents, hooks). Nothing is applied
automatically.

## Layout

```
skills/improve-clauding/
  SKILL.md                 orchestrator (8-step workflow)
  scripts/inventory.py     deterministic pre-pass: discovery, metrics, flags, state (stdlib Python 3)
  references/axes.md       what "improve" means; per-axis signals; tensions; north star
  references/lenses.md     12 lenses in 4 analyst groups; attribution; root-cause step; ranking
  references/destinations.md  rule / skill / agent / hook decision and proposal format
  references/report-template.md
agents/lens-analyst.md     read-only analyst subagent, one per lens group
commands/improve-clauding.md   /vf-improve-clauding:improve-clauding
```

## Inputs

- `~/.claude/projects/**/*.jsonl` (main sessions; `subagents/` counted for delegation)
- `~/.cursor/projects/*/agent-transcripts/*.jsonl` (parser is shape-tolerant; format unverified until first file)
- `~/.claude/CLAUDE.md`, project `CLAUDE.md` / `AGENTS.md` / `.cursor/rules`
- installed skill names under `~/.claude/skills`, `~/.claude/plugins/cache`, `~/.cursor/skills`, `~/.cursor/plugins/local`, `~/.agents/skills`
- git history of session `cwd`s (commits in window, reverts, follow-up fixes)
- `~/.improve-clauding/notes.md` - your own notes between retros (optional, high signal)
- previous reports in `~/.improve-clauding/reports/`

## State

`~/.improve-clauding/state.json` records covered sessions and past retros.
`runs/<timestamp>/` holds `inventory.md` + `inventory.json` per pre-pass.

```
python skills/improve-clauding/scripts/inventory.py --status
python skills/improve-clauding/scripts/inventory.py --last 10 --no-git
```

## Install

Claude Code: the plugin is listed in the `vanillafairy` directory marketplace
(`c:\work\claude\vanillafairy\.claude-plugin\marketplace.json`):

```
/plugin install vf-improve-clauding@vanillafairy
```

Cursor: `~/.cursor/plugins/local/vf-improve-clauding` is a directory junction to this
folder, so both tools read the same files.

## Design notes

- Two layers: the script measures, the LLM classifies. Script flags are pointers, not findings.
- Every finding: lens, axis moved, axis cost, attribution, recurrence, quoted evidence.
- Sessions younger than 24h are outcome-pending; no outcome claims for them.
- Prior art borrowed from: florianbuetow/claude-code retrospective (feedback loop, "ask why",
  scoring), netresearch/retro-skill (mechanical pre-pass + LLM, destinations, proposal cap,
  outcome mode), mgsa1/retrospective-skill (zero-information retries, prompt rewrites,
  git correlation), hancengiz/prompt-coach (prompt rubric).
