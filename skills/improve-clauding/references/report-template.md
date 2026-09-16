# Report: how to write it

File: `~/.improve-clauding/reports/YYYY-MM-DD-retro-NN.md`. Hard limit 150 lines.

The reader is the user, on a Wednesday afternoon, deciding what to change tomorrow.
Not a scoring system. Not another agent.

## Writing rules

- Plain English. Short sentences. One idea per sentence.
- Never print the internal vocabulary. The words `axis`, `axis moved`, `axis cost`,
  `attribution`, `recurrence`, `lens`, `north star`, `systemic`, `mechanical`,
  `endorsement`, `hard-fail`, `zero-information retry`, `clean_candidate` are for
  thinking, not for the page. Say what they mean instead:
  - "axis moved: tokens" -> "This wastes tokens."
  - "attribution: agent" -> "This one is on Claude, not you."
  - "attribution: user" -> "This one is a habit worth changing."
  - "recurrence: 5 sessions" -> "Happened in 5 sessions."
  - "zero-information retry" -> "You asked again without saying what was wrong."
- No metadata bullets under a heading. Write prose, then the evidence line.
- Say the finding in the heading, as a sentence a human would say out loud.
  Good: "A bug got 'fixed' five times in five weeks because nobody wrote a test."
  Bad: "Verification gap in regression-prone bug class (intelligence axis)."
- Every item needs one real quote and where it came from. One quote, not three.
- Say what to do differently, concretely, in one sentence. If there is nothing for the
  user to do, say "Nothing for you to change here" and move on.
- Numbers: round them. "340k tokens", not "339,580". Give a comparison if it helps
  ("a third of the whole window").
- Do not repeat a proposal in two places. Patterns own the explanation; the action list
  at the end is just short lines with numbers.
- No emoji, no bold-per-bullet, no severity icons.

## Structure

```markdown
# Clauding retro NN - YYYY-MM-DD

<2-4 sentences: what this window looked like and the single most useful takeaway.
Write it last. No numbers except the ones that matter.>

Covered: N sessions, DATE to DATE. Skipped N short ones. Previous retro: DATE or "none".

## How it's going

| what | rating | why |
|---|---|---|
| Getting it right first time | N/5 | <short clause> |
| Your time spent waiting | N/5 | <short clause> |
| Token waste | N/5 | <short clause> |
| Reusing what works | N/5 | <short clause> |

<One sentence on the trend vs the previous retro, or "First retro, so this is the baseline.">

## Worth fixing

### 1. <the finding as a plain sentence>

<2-4 sentences: what happens, how often, and why it happens. Name who it's on -
you, Claude, or the tools - in normal words.>

You said: "<quote>" (<date>, <short session name>)

Do instead: <one sentence>

### 2. ...

## Worth keeping

### 1. <what you did well, as a plain sentence>

<1-3 sentences, with the payoff in plain numbers.>

You said: "<quote>" (<date>, <short session name>)

Reuse it: <the template, in quotes, with <placeholders>>

## Last time's suggestions

<Table only if a previous retro exists: what was suggested, whether it happened,
how you can tell. Otherwise one line: "First retro - nothing to check yet.">

## What I can set up for you

<Numbered list. One line each: what it is, which file it touches, which finding it
came from. Nothing has been changed yet.>

1. Add a rule to <path> so <plain outcome>. (from #1)
2. ...

Say which numbers you want.

## Small print

<Only what changes how to read the above: counts that are floors not totals, sessions
too recent to judge, anything the tooling could not see. Two or three lines, not a
methodology essay.>
```

## Length discipline

At most 6 items under "Worth fixing" and 3 under "Worth keeping" in the written report,
even when the analysis found more. Ranking exists so the rest can be dropped. If a
finding cannot be explained in four sentences, it is two findings or it is not understood
yet.
