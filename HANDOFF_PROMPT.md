# HANDOFF_PROMPT.md

Paste this into a new AI tool the moment you switch models mid-build.

---

I'm mid-build on a 4-5 hour hackathon project (InternLoom AI Dev track —
a resume shortlisting engine in Python). Before doing anything else, read
`PROJECT_CONTEXT.md` and `TASKS.md` in the repo root. They contain the
architecture, the exact data models, the four Tricky Part design
decisions (already locked, don't re-derive them), the scoring formula,
and exactly which milestones are done vs. pending.

Do not propose a different architecture, library choice, or scoring
approach. These were decided deliberately for a basics-level Python user
under a hard time limit — treat them as fixed. Pick up exactly where
`TASKS.md` says we left off. Run `git log --oneline -10` for more state
if needed.

Current blocker / what I need from you right now:
`<fill this in fresh each time>`

If you need more context than these files give you, ask ONE specific
question rather than guessing and rewriting things.

---

## Model waterfall (same as last night, reproduced here for convenience)

1. Primary driver — Claude in Antigravity (100%) or the separately paid
   Claude subscription. Stay on one for architecture/debugging.
2. Codex in Antigravity (100%) — mechanical, low-judgment stretches:
   writing the skill vocabulary list, boilerplate dataclasses, the
   README.
3. Gemini in Antigravity (67%, spend deliberately) — save for one
   moment that actually needs a huge context window, e.g. reviewing many
   parsed resumes at once for a pattern you're missing.
4. Free Claude account — pure emergency fallback, never a starting
   point.

Switch on a hard usage-limit message, not on "this feels slow."
