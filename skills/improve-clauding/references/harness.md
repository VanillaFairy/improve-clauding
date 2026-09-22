# Harness differences: Claude Code and Cursor

This plugin reads transcripts from both. They do not record the same things, and in three
cases the same evidence implies **opposite** advice. Read this before writing any finding,
and check every session's `tool` field and `capabilities` block.

Two rules govern everything here:

1. **An aspect that is unobservable for a session's harness may not be used for that
   session.** Not "used with a caveat" - not used.
2. **Absence of a signal is never evidence of health.** A zero that comes from a missing
   record is `unavailable`, not `0`. The script now marks most of these; where it does not,
   you must.

## What each harness records

`capabilities` per session: `usage`, `exact_timing`, `tool_results`, `model`, `cwd`,
`pricing`, `compactions`.

| aspect | Claude Code | Cursor | note |
|---|---|---|---|
| model selection | yes | yes | Cursor records many model families; attribution differs, see below |
| reasoning budget | yes (`efforts`) | **no** | in Cursor the reasoning tier is baked into the model string, so it is a model-selection finding there, never a separate one |
| session length | yes | yes | advice inverts, see below |
| session hygiene | yes | yes | `briefs_in_session` works on both |
| cache continuity | yes | **no** | no usage records; never write this aspect for a Cursor session |
| context loading | yes | **no** | needs per-turn token growth, which Cursor does not record |
| tool output volume | yes | **no** | Cursor records no tool results at all |
| delegation | yes | yes | `Task` is counted as a delegate tool |
| parallelism | yes | yes | from `max_tools_per_message` and the delegation run counters |
| prompt specificity | yes | yes | prompt text is available on both |
| plan discipline | yes | partial | Cursor exposes mode switches, not a plan-mode flag |
| verification | yes | **half** | in Cursor you can see that a test ran, never whether it passed |
| autonomy & permissions | yes | **no** | Cursor records no permission mode and no denials |
| retries & loops | yes | yes | text-based detection works on both |
| reuse & extraction | yes | yes | but `skills_unseen` is confounded, see below |

Six aspects are unusable or half-usable on Cursor. If a Cursor-heavy window yields only
findings from the nine that work, that is the correct outcome, not a thin retro.

## The three inversions

Same evidence, opposite advice. Getting these backwards makes the report actively harmful.

**1. Long sessions.** On per-token billing, a long session re-reads its whole history on
every call, so splitting it saves real money. On a per-request subscription, context size
is roughly free and splitting means re-priming from scratch, so keeping the session can be
cheaper. Decide from the session's `capabilities.usage`: where usage records exist, the
per-token argument holds. Where they do not, do not make a cost argument from session
length at all - make the Human attention or Wall-clock argument if one is there.

**2. Compactions.** Compaction detection keys on Claude Code record shapes, so Cursor
sessions structurally report nothing. `capabilities.compactions` is now false for them and
the script prints `unavailable`. In Claude Code, a compaction count above zero supports
"clear earlier, split the session". In Cursor, summarization is automatic and not a user
lever, so the honest finding is usually that there is nothing for the user to change.

**3. Many short sessions.** On per-token billing with a prompt cache, frequent restarts are
cache-hostile and each one pays a cache write. On per-request billing they cost nothing
extra. Never recommend consolidating sessions on a harness where you cannot see the cache.

## Remedies must name the right mechanism

A `Do instead` that names a command the user's harness does not have is wrong advice, not a
rough edge. Translate before writing.

| intent | Claude Code | Cursor |
|---|---|---|
| drop context between tasks | `/clear` | start a new chat |
| shrink context mid-task | `/compact` | summarize, or start a new chat carrying a short brief |
| abandon a bad path cheaply | `/rewind` | revert the edits and restart the chat from the last good brief |
| change reasoning depth | `/effort` | pick a different model tier; there is no separate effort control |
| pick a cheaper model for routine work | `/model` to a smaller model | pick a cheaper model, or Auto in its cost-optimizing mode |
| keep exploration out of the main context | subagent | subagent |
| see what is loaded at session start | `/context` | inspect the rules and MCP tools in settings |

Where a harness has no equivalent, say so plainly in the item and give the nearest real
action, rather than inventing a command.

## Attribution traps

**Automatic model routing.** When a router picks the model, a model-selection finding is
not a user habit. Nothing in the transcript records whether routing was on, or which
optimization mode was active - a session showing three model strings is indistinguishable
from a user switching models three times. Unless the user's own words show a deliberate
choice, mark such findings as not the user's doing and route them to a proposal, not to a
habit. Never write "you used X" when a router may have chosen X.

**Unpriced models.** `PRICES` covers only the model families with published list prices in
the script. Anything else contributes no dollars and sets `spend.cost_partial`. A cost
finding about an unpriced model has no dollar figure available - give the gain in turns or
minutes instead, and say the dollars are unavailable.

**Cross-harness skill confusion.** `skills_unseen` merges installed skills from both
harnesses into one list. Before calling a skill unused, confirm it was installed for the
harness the window actually used.

**Cursor working directory.** `cwd` is often inferred from a tool argument rather than
recorded, so git correlation frequently fails. Where `capabilities.cwd` is false, outcome
and revert claims are unavailable for that session.

**Cursor interrupts.** These are inferred from a turn-ended error matching "user aborted"
or "cancellation token requested". A non-human cancellation trips the same detector, so
treat a lone interrupt as weak evidence.

## Mixed windows

A window can contain both harnesses. When it does:

- Compute and report the north star separately per harness, and say so. The two forms are
  not comparable.
- Never aggregate a cost figure across harnesses when one side has no usage records; the
  total would silently mean "Claude Code only".
- When the same habit appears on both, write one finding and give the remedy for both
  harnesses in the one `Do instead` sentence.
