# What "improve" means

Improve = more correct outcomes per unit of cost, where cost is money, elapsed time, and
the user's own attention.

Every finding names **exactly one axis** and **exactly one aspect**, both from the closed
lists below. An axis is the outcome that got worse. An aspect is the lever that moved it.
If a finding seems to need two of either, it is two findings, or it is not understood yet.

Both lists are closed. Do not invent an axis, an aspect, or a synonym. `subagents`,
`context health`, `throughput`, and `effort` are not members; use `delegation`,
the relevant context aspect, and `reasoning budget` instead.

## The six axes

Each axis owns a primary evidence field. When two axes both look plausible, the axis that
owns the number you are actually quoting wins.

| axis | it means | primary evidence | what would disprove a finding on it |
|---|---|---|---|
| Cost | money or quota per completed task | `spend.est_cost_usd`, `spend.api_calls`, `spend.avg_context_per_call` | recompute from `usage_by_family`; unavailable where `capabilities.usage` is false |
| Wall-clock | elapsed minutes per task | `agent_active_sec`, `turns[].agent_seconds`, `tool_ms`, `human_wait_sec` | the durations, where `capabilities.exact_timing` is true |
| Intelligence | the attempt was wrong, and it was caught in-session | corrections following an edit turn, `turns[].quality`, `models`, `efforts` | the correction turns; no correction means the attempt stood |
| Reliability | it was accepted without proof, or it came back later | `git.follow_up_fixes`, `git.reverted`, praise turns with no preceding test or build call | the git record, where `capabilities.cwd` resolved |
| Human attention | how many times the user had to intervene | `mechanical.nudges`, `interrupts`, `human_turns` per episode | the nudge and interrupt counts |
| Reusability | a recurring composite action was never extracted | `repeated_openers` (session-distinct), repeated tool sequences, `skills_unseen` | the session count; under two distinct sessions there is no pattern |

### Tie-breaks, settled

These four collisions are the ones that actually occur. Apply them mechanically.

- **Cost beats everything when the evidence is a dollar figure.** If the sentence you are
  about to write contains `$`, the axis is Cost.
- **Wall-clock owns minutes; Human attention owns counts of user turns.** A forty-minute
  wait is Wall-clock. Twenty "continue" turns is Human attention, even when they happened
  inside the same forty minutes.
- **Intelligence is caught in-session; Reliability is accepted then reopened.** A wrong
  edit the user corrected on the next turn is Intelligence. A task marked done that needed
  a fix three days later is Reliability.
- **Reusability needs two distinct sessions.** One occurrence of a repeated-looking action
  is never Reusability. `repeated_openers` now reports a session count; use it, not the
  occurrence count.

### Axis 1 - Cost

Goal: less money per completed task.

**The cost model, because it is counter-intuitive.** Every API call re-sends the whole
conversation, so spend is dominated by context re-read, not by what the model writes:

    cost ~ number of API calls x size of the context at each call

`spend.est_cost_usd` already sums every per-call usage record. Do not multiply it by call
count, session count, or anything else - that inflates the figure by orders of magnitude.
The two levers behind the headline are `spend.api_calls` and `spend.avg_context_per_call`.

In the first real window measured here, cache reads were 86% of spend and output tokens
were a rounding error. Two consequences:

- **A high cache ratio is not efficiency.** It means each call was cheap *per token*. It
  says nothing about how many calls happened or how big the context was. Never rate this
  axis well because the cache ratio is high; `[cache_ratio]` is a diagnostic, not a score.
- **A long session is expensive even when it looks calm.** A 40-turn session re-reads its
  whole history on every one of hundreds of calls. This is true on per-token billing and
  false on per-request billing - see `harness.md` before writing the advice.

Quote dollars in the report; tokens mean nothing to a reader.

**Partial pricing.** `model_family()` returns `None` for any model with no list price in
`PRICES`. Those tokens are excluded from every dollar figure and the session is marked
`spend.cost_partial` with `spend.unpriced_families`. When a session is cost-partial, say so
rather than quoting the total as if it were complete. Never price an unknown model by
analogy to a known one.

Signals: `spend.est_cost_usd`, `spend.est_cost_subagents_usd` (subagent spend is invisible
in the main transcript), `spend.api_calls`, `spend.avg_context_per_call`,
`mechanical.re_read_turns`, `mechanical.zero_info_retries`, `mechanical.compactions`,
`mechanical.tool_output_chars`, `human_turns`, `span_hours`, and tokens spent in turns that
were later corrected or reverted.

Caveat: one API message is written as several JSONL records that each repeat the full
`usage`, so the inventory deduplicates by message id - never count records yourself. Claude
Code's own `cost-state` field is usually absent or zero; ignore it and use the estimate,
which uses public list prices from `PRICES` in `inventory.py`. Treat it as an order of
magnitude and as a basis for comparison between retros.

### Axis 2 - Wall-clock

Goal: fewer elapsed minutes per task. Three clocks; the fixes differ.

- **Agent clock** `[agent_active_sec, turns[].agent_seconds]`: read-only tool runs that ran
  one after another when they could have been one batch
  `[sequential_readonly_runs, max_tools_per_message, multi_tool_messages]`; subagent work
  dispatched one at a time `[sequential_delegation_runs vs parallel_delegations]`; long
  single-context runs where a fan-out would have been faster; retries after tool errors.
- **Tool clock** `[tool_ms]`: build, test, and configure waits. The fix is caching or a
  narrower target, not prompting. Note `tool_ms` comes from `cost-state` and is usually
  absent; when it is, say the tool clock is unmeasured rather than zero.
- **Human clock** `[human_wait_sec, long_gaps]`: time between the agent finishing and the
  user answering. This measures elapsed time only. The *number* of interventions belongs to
  Human attention.

### Axis 3 - Intelligence

The agent had the right context, the right reasoning budget, and the right decomposition
for the difficulty of the task, so the first attempt was correct.

Signals: first-attempt success (turns with edits or commits and no following correction);
`mechanical.corrections`; `mechanical.plan_mode_used` against `lines_added`;
`turns[].quality` (intent stated, path given, failing output included); `models` and
`efforts` per session.

Over-thinking a trivial task costs Cost; under-thinking a hard one costs Intelligence.

**The counterfactual limit.** "A better model would have got this right" is not provable
from one transcript. Only write a model-selection finding on this axis when the transcript
shows the agent had the context, tried, and was still wrong - not merely that a small model
was used on a task you consider hard. Absent that, the finding belongs on Cost (capability
paid for and not needed) or nowhere.

### Axis 4 - Reliability

Did the change actually work, and was that demonstrated?

Signals: praise turns not preceded by a test or build tool call; `git.follow_up_fixes`;
`git.reverted`; a later session fixing an earlier "completed" task. Only for sessions with
`outcome_pending == false`.

Where `capabilities.cwd` is false the git record is unavailable, and the half of this axis
that depends on it cannot be evidenced. Say so; do not substitute impressions.

### Axis 5 - Human attention

How much babysitting the work required. Counts, not minutes.

Signals: `mechanical.nudges` (turns spent saying "continue" or "yes" - autonomy not granted
up front, or the agent stopped when it should not have); `interrupts`; `human_turns` per
episode; `mechanical.denials`.

This is the axis most under the user's control and the one they feel most directly.

### Axis 6 - Reusability

Any composite action that recurs gets extracted once and reused.

Signals: `repeated_openers` (now session-distinct: use the session count, not the
occurrence count); the same correction in two or more sessions; repeated tool-call
sequences such as configure, build, test, read log `[turns[].tools]`; repeated setup
preambles at session start; `skills_unseen` (extracted assets that never fire); skills that
fire and are then corrected.

Metric: session count x turns saved per occurrence. Extract when payback is under about
three occurrences. Destination follows `destinations.md`.

This axis is what every proposal type in `destinations.md` hangs off. A finding whose fix
is "make this a skill, rule, agent, or hook" belongs here, even when the saving will show
up on Cost or Wall-clock later.

Caveat: `skills_unseen` is built from a single merged glob across `~/.claude/skills`,
plugin caches, `~/.cursor/skills`, `~/.cursor/plugins/local`, and `~/.agents/skills`. A
skill installed for one harness will read as "unseen" in a window from the other. Check the
harness before calling a skill unused.

## The aspects

Closed list. One per finding. The primary axis is where the aspect normally lands; the
allowed column is the only permitted alternative. Any other pairing is illegal - re-file it.

| aspect | primary axis | also allowed | main evidence |
|---|---|---|---|
| model selection | Cost | Intelligence, Wall-clock | `models` |
| reasoning budget | Cost | Intelligence | `efforts` |
| session length | Cost | Wall-clock | `human_turns`, `span_hours`, `api_calls` |
| session hygiene | Cost | Intelligence | `briefs_in_session` >= 2 |
| cache continuity | Cost | Wall-clock | `tokens.cache_read` / `cache_create`, gaps |
| context loading | Cost | Intelligence | `turns[].quality.has_path`, cache_create growth |
| tool output volume | Cost | Intelligence | `tool_output_chars`, `big_tool_outputs` |
| delegation | Wall-clock | Cost, Human attention | `delegations`, `subagent_files` |
| parallelism | Wall-clock | Cost | `max_tools_per_message`, `multi_tool_messages`, `parallel_delegations`, `sequential_delegation_runs`, `sequential_readonly_runs` |
| prompt specificity | Intelligence | Cost, Human attention | `turns[].quality`, `low_quality_prompts` |
| plan discipline | Intelligence | Reliability, Cost | `plan_mode_used`, `modes`, `lines_added` |
| verification | Reliability | Human attention | praise with no preceding test or build |
| autonomy & permissions | Human attention | Reliability | `permission_modes`, `denials` |
| retries & loops | Cost | Human attention, Wall-clock | `zero_info_retries`, `near_repeat`, `tool_errors` |
| reuse & extraction | Reusability | - | `repeated_openers`, `skills_unseen` |

Two aspects are near neighbours and are separated by rule, not by judgement:

- **session length vs session hygiene.** Length is how big the session got. Hygiene is
  whether it carried more than one brief, measured by `briefs_in_session >= 2`. A short
  session can fail hygiene; a long single-topic session passes it.
- **delegation vs parallelism.** Delegation is whether work was handed off at all.
  Parallelism is whether concurrent work ran concurrently. Four subagents dispatched one
  after another is parallelism, not delegation.

**Before using any aspect, check `harness.md`.** Six of the fifteen are dead or half-dead
on Cursor transcripts, and three of them invert the correct advice between harnesses. An
aspect that is unobservable for a session's harness may not be used for that session, and
absence of a signal is never evidence of health.

## Severity, and the hard-fail channel

Risk is not an axis. It is a severity multiplier applied at ranking, and it never converts
a one-off into a droppable finding.

Severity is above 1 when the episode involved data loss, a commit on a shared branch, a
force push, a bypassed hook, a secret in a prompt, or a destructive shell command.

**Hard-fail flags bypass ranking entirely and are always reported**, regardless of
recurrence, score, or the caps in the report template:

`--no-verify` `[mechanical.no_verify]`, force push `[mechanical.force_push]`, commits on
main or master `[mechanical.on_main_with_commits]`.

Note what is *not* detected: the script has no secret-detection regex and no general
destructive-command regex. Only the three git patterns above exist. Do not claim a clean
bill of health on secrets or destructive commands; that ground is simply unobserved.

## Tensions - state them in every retro

- **Cost vs Intelligence.** More context and more reasoning cost money. "Cut cost" must
  show that quality held.
- **Cost vs Wall-clock.** Parallel subagents cut elapsed time and multiply tokens.
- **Reusability vs everything.** Extraction costs a session now to save later, and the
  saving is in future sessions you have no evidence for yet. Only recommend it above the
  two-session threshold, and price it as expected rather than measured.
- **Human attention vs Reliability.** Granting autonomy saves turns and removes correction
  points. Show where autonomy was safe and where it produced a revert.

## North star

Track per retro and report the delta.

- Where token usage is available: correct episodes / (user turns + normalized tokens).
- Where it is not: correct episodes / user turns.

These two numbers are not comparable with each other. Never compare a Cursor window's
north star against a Claude Code window's, and say which form you used.
