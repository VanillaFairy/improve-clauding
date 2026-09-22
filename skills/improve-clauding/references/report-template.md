# Report: how to write it

File: `~/.improve-clauding/reports/YYYY-MM-DD-retro-NN.md`. Hard limit 150 lines.

The reader is the user, on a Wednesday afternoon, deciding what to change tomorrow.
Not a scoring system. Not another agent.

## The item format

Every item under "Worth fixing" is exactly two lines:

```
- *<Axis>* | *<aspect>* | <N> sessions[ | not your doing: <agent|tool|model|router>]. In <session>, <what happened, with a number>. *Do instead*: <one sentence>. <gain>.
  *You said:* "<quote>" (<date>, <session>)
```

Worked examples:

```
- *Cost* | *model selection* | 6 sessions. In "conan build fixes", Opus ran 41 mechanical
  file reads and renames across 190 calls. *Do instead*: start mechanical sessions on the
  smallest model and only switch up when it is actually wrong. Worth about $60 over a
  window like this one.
  *You said:* "just rename these and rerun the build" (Sep 12, conan build fixes)

- *Cost* | *session hygiene* | 4 sessions. In "byologic triage", one session carried three
  separate briefs over 75 turns with a two-hour gap in the middle. *Do instead*: start a new
  chat when the topic changes, rather than continuing the old one. Worth about $40; that
  session cost $155 across 409 calls.
  *You said:* "ok different thing now - the installer" (Sep 14, byologic triage)

- *Wall-clock* | *parallelism* | 3 sessions. In "spec review", four read-only analyses were
  dispatched one after another when nothing depended on the previous result. *Do instead*:
  dispatch independent read-only work in a single batch. Cuts roughly 25 minutes per run,
  going by the four runs at 5-9 minutes each.
  *You said:* "now do the same for the second file" (Sep 15, spec review)

- *Intelligence* | *model selection* | 2 sessions | not your doing: router. In "auth
  redesign", a cost-tier model was selected for an architecture decision and was corrected
  three times. *Do instead*: pin a strong model explicitly for design work instead of
  leaving the choice automatic. Saves about 6 correction turns per design session.
  *You said:* "no, that breaks the refresh path entirely" (Sep 17, auth redesign)
```

Rules for the format:

- `<Axis>` is one of Cost, Wall-clock, Intelligence, Reliability, Human attention,
  Reusability. `<aspect>` is one of the fifteen in `axes.md`. Both are closed lists and the
  pairing must be legal per the matrix there.
- `<N> sessions` is the distinct-session count. Write `1 session` when it is one; do not
  hide it.
- The `not your doing` marker appears **only** when the cause was not the user. Omit it
  entirely for user habits. When it is present, the sentence must not say "you" did the
  thing - describe what happened instead, and make the `Do instead` a setup change rather
  than a behaviour change.
- `<what happened>` carries a real number from the inventory. When the number is
  unavailable for that harness, give the count you do have and say the rest is unavailable.
  Never write `0` for something that was not recorded.
- The quote line is mandatory. One quote, not three. No item ships without it.
- These two lines are the whole item. No sub-bullets, no extra paragraph.

The bold markers and the axis and aspect labels are deliberate here and are the one
exception to the vocabulary rules below.

## Writing rules

- Plain English. Short sentences. One idea per sentence.
- Write as a person speaking to another person. Describe the work, not the reporting
  process. Say "No big changes since last time", not "No new eligible sessions". Say
  "I cannot tell yet whether you tried this", not "There is no post-retro evidence".
- Never print the internal vocabulary. The words `axis`, `axis moved`, `axis cost`,
  `aspect`, `attribution`, `recurrence`, `lens`, `north star`, `systemic`, `mechanical`,
  `endorsement`, `hard-fail`, `zero-information retry`, `clean_candidate`, `eligible
  sessions`, `coverage window`, `selection cutoff`, `follow-through evidence`, and
  `outcome update` are for thinking, not for the page.
  - The *labels* Cost, Wall-clock, Intelligence, Reliability, Human attention and
    Reusability may appear as the item prefix. The word "axis" may not.
  - The *aspect names* may appear as the item prefix. The word "aspect" may not.
  - "not your doing: agent" is how attribution reaches the page. The word "attribution"
    does not.
  - Outside the item prefix, still say what things mean: "Happened in 5 sessions",
    "You asked again without saying what was wrong", "This one is on Claude, not you".
- Every item needs one real quote and where it came from.
- Say what to do differently, concretely, in one sentence. If there is nothing for the
  user to do, say "Nothing for you to change here" and move on.
- **Always state the expected gain.** Every `Do instead` and every setup item ends with
  what it buys, in the unit the reader feels. Derive it from what the finding already cost
  in this window, and say where the number came from.
  - Prefer dollars where token usage was recorded.
  - Use turns or minutes where it was not, or where the model had no list price. These are
    first-class units, not fallbacks to apologise for.
  - "Worth about $90 over a window like this one - that session cost $155 across 409 calls."
  - "Saves roughly 20 of your turns; you spent 23 on 'continue' alone."
  - "Cuts about 4 hours of waiting, going by the six log-paste turns at 25-80 minutes each."
  - If it genuinely cannot be quantified, write "Hard to price, but it removes <X>" -
    never leave a recommendation with no stated payoff.
- Numbers: round them. "340k tokens", not "339,580". Give a comparison if it helps
  ("a third of the whole window").
- Do not repeat a proposal in two places. Items own the explanation; the action list at the
  end is just short lines with numbers.
- No emoji, no severity icons. Bold appears only in the item format above.

## Structure

```markdown
# Clauding retro NN - YYYY-MM-DD

<2-4 sentences: what this window looked like and the single most useful takeaway.
Write it last. No numbers except the ones that matter.>

Covered: N sessions, DATE to DATE. Skipped N short ones. Previous retro: DATE or "none".

## How it's going

<One row per thing that had evidence this window. Drop a row entirely when the window
could not measure it - do not print a rating with no basis.>

| what | rating | why |
|---|---|---|
| Getting it right first time | N/5 | <short clause> |
| Work that stayed fixed | N/5 | <short clause> |
| Your time spent waiting | N/5 | <short clause> |
| Times you had to step in | N/5 | <short clause> |
| Money spent | N/5 | <$ for the window, and the calls x context that drove it> |
| Reusing what works | N/5 | <short clause> |

<Then, if anything was unmeasurable: one line naming it, e.g. "Money spent: these
transcripts carry no token records, so there is no figure for this window.">

<One sentence on the trend vs the previous retro, or "First retro, so this is the baseline.">

## Worth fixing

<Two-line items in the format above. At most 6, ranked.>

## Worth keeping

### 1. <what you did well, as a plain sentence>

<1-3 sentences, with the payoff in plain numbers.>

You said: "<quote>" (<date>, <short session name>)

Reuse it: <the template, in quotes, with <placeholders>>

## Anything unsafe

<Only if a hard-fail flag fired. One line each, always listed, never ranked away.
Omit the whole section when nothing fired - do not write "none found", because the
tooling does not look for secrets or destructive commands and cannot clear you of them.>

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
too recent to judge, anything the tooling could not see, and which harness the window
came from when it affects the numbers. Two or three lines, not a methodology essay.>
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
   small print, in one line. The same applies to the cost of running the retro itself.

Rule of thumb: at least 4 of 6 items under "Worth fixing", and at least half the setup
list, should be things the user does rather than things the user installs.

Items marked `not your doing` do not count against that ratio, and no more than 2 of the 6
should carry that marker - if more than two do, the window's real story is a tooling story
and the summary should say so instead.

## Length discipline

At most 6 items under "Worth fixing" and 3 under "Worth keeping" in the written report,
even when the analysis found more. Ranking exists so the rest can be dropped. If a finding
cannot be explained in the two-line format, it is two findings or it is not understood yet.
