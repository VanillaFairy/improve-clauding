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
  - "axis moved: tokens" -> "This cost you about $N."
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
- **Always state the expected gain.** Every "Do instead" and every setup item ends with what
  it buys, in the unit the reader feels: dollars, turns, or minutes of waiting. Derive it
  from what the finding already cost in this window, and say where the number came from.
  - "Worth about $90 over a window like this one - that session cost $155 across 409 calls."
  - "Saves roughly 20 of your turns; you spent 23 on 'continue' alone."
  - "Cuts about 4 hours of waiting, going by the six log-paste turns at 25-80 minutes each."
  - If it genuinely cannot be quantified, write "Hard to price, but it removes <X>" -
    never leave a recommendation with no stated payoff.
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
| Money spent | N/5 | <$ for the window, and the calls x context that drove it> |
| Reusing what works | N/5 | <short clause> |

<One sentence on the trend vs the previous retro, or "First retro, so this is the baseline.">

## Worth fixing

### 1. <the finding as a plain sentence>

<2-4 sentences: what happens, how often, and why it happens. Name who it's on -
you, Claude, or the tools - in normal words.>

*You said:* "<quote>" (<date>, <short session name>)

*Do instead:* <one sentence>

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

1. Add a rule to <path> so <plain outcome>. Saves <gain>. (from #1)
2. ...

Say which numbers you want.

## Small print

<Only what changes how to read the above: counts that are floors not totals, sessions
too recent to judge, anything the tooling could not see. Two or three lines, not a
methodology essay.>
```

## What to keep when trimming

This is a retro about **habits** - what the user does, and could do differently tomorrow.
Tooling is secondary. When ranking, and when cutting to the caps:

1. Keep habits first: how tasks are briefed, when work is split, when autonomy is granted,
   when evidence is demanded, when a session should have ended.
2. Keep a tooling item only when it is the direct cause of a habit's cost, and write it as
   the habit ("you became the build system") rather than as a configuration task.
3. Push pure configuration and plugin-maintenance work to the end of the setup list, or
   drop it. A missing trigger phrase in a skill is not a retro finding; repeatedly working
   around a missing trigger is.
4. Never spend a "Worth fixing" slot on a bug in this retro's own tooling. Those go in the
   small print, in one line.

Rule of thumb: at least 4 of 6 items under "Worth fixing", and at least half the setup
list, should be things the user does rather than things the user installs.

## Length discipline

At most 6 items under "Worth fixing" and 3 under "Worth keeping" in the written report,
even when the analysis found more. Ranking exists so the rest can be dropped. If a
finding cannot be explained in four sentences, it is two findings or it is not understood
yet.
