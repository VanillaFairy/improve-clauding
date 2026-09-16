# Proposal destinations

Every proposal routes to exactly one destination. Pick authority first: who should own this
truth? Then pick the mechanism.

| destination | when | materializes as | proposal must contain |
|---|---|---|---|
| habit | user-side behaviour, no tooling can enforce it | a line in the report's "patterns to fix" | the trigger situation, the replacement behaviour, one rewritten example |
| personal-rule | a cross-project preference or standing correction | append to `~/.claude/CLAUDE.md` (Claude) and the user rules in Cursor | exact rule text, <=3 lines, with the WHEN |
| project-rule | a convention for one project | append to `<project>/CLAUDE.md` or `AGENTS.md` or `.cursor/rules/*.mdc` | exact text + target file path |
| skill-patch | an existing skill is wrong, weak, under-triggering, or has an obsolete step | diff against the skill's **source** dir (never a plugin cache) | source path, old text, new text |
| new-skill | a procedure invoked on demand, recurs >=3 times, needs no isolated context | new `SKILL.md` scaffold | name, description with trigger terms, 5-10 line outline |
| new-agent | a procedure that needs isolated context, parallelism, or a different model | agent definition | name, when to dispatch, inputs, expected return shape |
| hook | a mechanical check with no judgment (lint, forbidden command, reminder) | hook entry | event, matcher, command, what it prints |
| tooling | environment friction (build, network, OS) | note for the user | what breaks, what would fix it |
| canonical-doc | a fact about the world that belongs in upstream docs/code | note with target | target artefact, the fact |

Decision rule between rule / skill / agent / hook:
- Rule: a constraint that is always true. No procedure.
- Skill: a procedure, invoked on demand, runs in main context.
- Agent: a procedure that needs its own context window, runs in parallel, or wants another model.
- Hook: no judgment needed; a script can decide.

Source paths for skill patches on this machine:
- Claude plugin sources: read `~/.claude/plugins/known_marketplaces.json` -> `source.path` for
  directory marketplaces (e.g. `c:\work\claude\vanillafairy`, `c:\PMi\src\pmi_claude_plugins`).
  `~/.claude/plugins/cache/**` is overwritten on update; never propose edits there.
- Cursor local plugins: `~/.cursor/plugins/local/<plugin>` may be a copy of a source dir; propose
  against the source and note the copy needs a re-sync.

Never apply a proposal inside the retro. Present each one; the user applies it, or asks for it
to be applied in a separate step.
