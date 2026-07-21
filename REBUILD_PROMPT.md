FRESH SESSION PROMPT — paste this whole thing as your first message

---

You're picking up an existing project called ParseLoom (InternLoom Resume
Shortlisting Engine), located at the folder root you have access to. This
is a from-scratch rebuild of its backend and frontend logic — not a patch,
not incremental fixes. Read this entire prompt before touching anything.

## 0. Read these files first, in this order, before doing anything else

1. `PROJECT_CONTEXT.md` — full architecture, the "Four Tricky Parts,"
   scoring formula.
2. `DESIGN_DECISIONS.md` — why specific implementation choices were made.
3. `WEB_APP_PLAN.md` — the original web-app design (Bonus A).
4. `SESSION_HANDOFF.md` — what was done in the most recent working
   session, and known-fragile things.
5. `RELIABILITY_SCALE_ANALYSIS.md` — a root-cause analysis written after
   the current build kept breaking under real use. This is the most
   important file. It contains confirmed bugs, traced through actual code
   and a live log, not speculation. Do not treat anything in it as
   optional context — every issue in it must be designed around, not
   rediscovered the hard way a second time.

Do not start writing a plan or any code until you've read all five.

## 1. What this rebuild is and is not

**Rebuild:** the entire backend (Flask app, resume parsing, LLM
extraction pipeline, scoring, shortlisting, all Python under `src/` and
`app.py`/`main.py`) and the entire frontend *logic* (JS wiring, state
management, API calls, routing between pages, error/loading states) —
from scratch, cleanly, with the accumulated knowledge of what broke and
why.

**Not a rebuild — leave untouched for now:** the visual UI/UX design
(the existing CSS, layout, color palette, Fable-authored markup
structure/visual styling). Do not redesign, restyle, or reflow anything
visually in this phase. If the existing frontend logic requires HTML
structure changes to work correctly (e.g. adding a real progress bar
element, a distinct error-state banner), add the minimum structural
markup needed and leave it visually unstyled/basic — a follow-up phase
will handle making the whole UI trendy, animated, and interactive once
the underlying system is proven correct. Say so explicitly in your plan
so it's clear which parts are temporary/unstyled by design.

## 2. Known issues you must design around (do not rediscover these)

These are confirmed, not hypothetical — read `RELIABILITY_SCALE_ANALYSIS.md`
for full detail on each, but at minimum:

1. **Silent LLM failure disguised as bad data.** When the extraction LLM
   call fails (rate limit, bad key, timeout, bad JSON), the old code
   caught the error and silently returned empty fields, which then scored
   as a legitimate `0`. The UI could not tell "the AI provider is down"
   apart from "this resume is genuinely low-signal." The rebuild must
   make these two states visually and structurally distinct everywhere —
   in the data model, the API response, and the UI — from day one, not as
   an afterthought.
2. **No timing instrumentation.** It was impossible to tell, from logs,
   where time was going per resume (PDF extraction, OCR, LLM call,
   retries). The rebuild must log structured timing
   (`resume_id, stage, duration_ms`) for every stage of every resume, from
   the first version, not bolted on later.
3. **Fixed 4-worker concurrency cap regardless of batch size**, meaning
   40 resumes ran as 10 sequential rounds of 4 — not a real scaling
   strategy. Concurrency needs to be a deliberately tuned, documented
   number based on the actual provider rate limit, not an arbitrary
   constant.
4. **Fully synchronous `/api/run`** — the whole HTTP request blocks until
   every resume finishes, with no progress feedback, no partial results,
   no cancel, and real risk of hitting a reverse-proxy timeout in
   production (this app is intended for deployment, e.g. Render — assume
   it needs to survive a real host's default request timeout, don't
   assume local dev conditions are representative).
5. **`MAX_FILES_PER_REQUEST = 20`** was an arbitrary cap that blocked a
   real 40-resume test run. Whatever cap (if any) the rebuild uses must
   be a deliberate, justified number, and batches larger than any
   practical single-request limit must be handled via chunking/queuing
   transparently to the user, not by making them manually split uploads.
6. **Cross-tab state bug.** The "view full candidate details" page opens
   in a new tab and needs to read the results of the run that opened it.
   The original implementation assumed `sessionStorage` clones into a new
   tab reliably — it does not, notably in Safari. A subsequent fix moved
   to `localStorage`, which fixed data availability but not the actual
   desired behavior: "Back to results" should return the user to the
   *original* browser tab (e.g. via `window.close()`, since the detail
   tab is opener-owned), not re-render an equivalent page in the same
   tab. Design the navigation/state model deliberately around this from
   the start, including a documented fallback for when a tab isn't
   opener-owned.
7. **No extraction-accuracy verification exists.** All existing automated
   tests cover pure scoring/normalization math, never whether the LLM
   actually extracts correct fields from a real resume. The rebuild needs
   a real fixture-based accuracy test suite from the start (see Section 4).
8. **Retry/backoff design was never load-tested against a real rate
   limit.** The exponential backoff and retry count in the LLM client
   were written from reasoning, not from an actual measured rate-limit
   ceiling for the provider in use. Verify the real published
   requests-per-minute limit for whatever provider/model you use, and
   design concurrency and backoff around that measured number, not a
   guess.

## 3. Non-negotiable process requirement: plan before code

Because getting the LLM extraction pipeline wrong costs real time and
quota to re-diagnose, do not write implementation code for the pipeline
(or anything else) until you have produced and shared a complete,
detailed technical and execution plan, broken into small, independently
achievable milestones. Each milestone in the plan must specify:

- **Goal** — what this milestone proves works, in one sentence.
- **Inputs needed** — what data, fixtures, credentials, or prior
  milestone output this depends on.
- **Implementation scope** — what gets built, explicitly bounded (call
  out what is *not* included, to prevent scope creep into later
  milestones).
- **Tests required to close this milestone**, covering, wherever
  applicable to that milestone:
  - Unit tests (pure logic — scoring, normalization, parsing helpers).
  - Integration tests (real component-to-component calls, e.g. a real
    PDF through the full extraction pipeline).
  - LLM-pipeline-specific tests: a real call against the actual provider
    with a known-good fixture resume, a deliberately-broken-input test
    (e.g. malformed PDF, empty PDF, prompt-injection-style resume
    content) and a simulated-failure test (mocked 429/500/timeout) to
    prove the failure path is now visibly distinct, not silent.
  - Load/concurrency tests — simulate a real batch (e.g. 40 resumes) and
    confirm behavior matches the plan's stated concurrency/timeout
    design, not just "it eventually finished."
  - Security/vulnerability checks — input validation on uploads (file
    type/size/count), injection resistance in the LLM prompt path
    (resume content must never be treated as instructions — this existed
    before, verify it explicitly with a test case), secret handling (API
    keys never reach logs, error messages, or the browser — this existed
    before too, verify explicitly), and dependency vulnerability scanning.
  - Code health checks — linting, type checking if applicable, and a
    check that no dead/duplicate logic was introduced (the original
    codebase had a documented duplication between `main.py` and `app.py`
    for `parse_one_resume` — decide deliberately in your plan whether the
    rebuild removes that duplication via a shared module, and say so).
- **Exit criteria** — the specific, checkable condition that means this
  milestone is actually done (not "looks done," a concrete pass/fail).

Do not proceed to writing code for a milestone until its predecessor's
exit criteria are met and verified, not assumed.

## 3a. Mandatory persistent milestone log — `MILESTONE_LOG.md`

Create one file, `MILESTONE_LOG.md`, at the start of this work. This file
is **append-only for the rest of this project**: every future edit adds a
new dated entry underneath the existing ones. Never delete, rewrite, or
summarize-away a previous entry to make room for a new one — the full
history across every milestone must stay readable end to end, in every
future session, forever. This is the single most important process rule
in this prompt — the plan document describes intent, this log documents
what actually happened, including everything that went wrong along the
way, so nothing has to be rediscovered twice.

**When to write an entry:** only once every test required to close a
milestone (per Section 3) actually passes — not before, not as a draft
mid-work. If problems came up and were fixed during that milestone, the
entry written at the end must still capture the full story of what broke
and how it was resolved, not just the final clean state. If a milestone
turns out to require multiple attempts (a test fails, code gets reworked,
tests are re-run), the final entry for that milestone must include that
whole arc — don't write it as if it succeeded on the first try if it
didn't.

**Required structure for each entry:**

```
## Milestone <N>: <name> — <date>

### Goal
(restate the one-sentence goal from the plan)

### What was done
(concrete summary of what was built/changed)

### Problems faced
(everything that went wrong during implementation or testing — be
specific: what broke, what the actual error/symptom was, not a vague
"had some issues")

### Test failures and how they were resolved
(for each failing test: what was expected, what actually happened, root
cause, and the exact fix applied — this is the part most worth writing
carefully, it's what prevents re-diagnosing the same bug in a future
milestone)

### Final test results
(list every test category run for this milestone and its pass/fail
status — should all be passing by the time this entry is written)

### Notes for future milestones
(anything a future session needs to know before building on top of this
work — assumptions made, things deliberately deferred, edge cases
handled a specific way for a specific reason)

### Recurring-risk issues
(anything here that plausibly resurfaces later — e.g. a rate limit
pattern, a browser-specific storage quirk, a timing issue — stated
explicitly along with the exact solution that resolved it this time, so
a future session facing the same symptom finds the answer here instead
of re-deriving it)
```

**Mandatory reading rule:** before starting any new milestone, and at the
start of every new session regardless of which milestone is active,
reading `MILESTONE_LOG.md` in full, alongside the technical/execution
plan and the five files listed in Section 0, is required — not optional,
not "skim if there's time." This is how continuity survives across
sessions on a project with no single continuous conversation.

## 4. Specifically for the LLM/extraction pipeline

Because this is the part that has broken repeatedly, before writing any
pipeline code, your plan must show a clear, explicit understanding of:

- The full request/response contract with the LLM provider(s) in use,
  including exact error modes (what a rate limit response looks like,
  what a malformed response looks like, what a timeout looks like) and
  how each maps to a distinct, visible state in the data model — not a
  single generic "Partial" bucket.
- A real measured (not assumed) rate limit for the provider/model
  combination you choose, and a concurrency/backoff design that is
  provably safe against it, with a test that simulates hitting that limit
  and confirms graceful, visible degradation rather than a silent wall of
  zeros.
- A small (5–10 resume) fixture set with manually verified expected
  extracted values (name, skills, CGPA, at minimum), checked into the
  repo, with an automated test that runs real extraction against them and
  reports per-field accuracy — this is how "is the data actually correct"
  gets answered going forward instead of eyeballed from screenshots.
- A explicit decision, stated in the plan, on caching (e.g. by content
  hash) to avoid burning LLM quota re-processing the same resume during
  development/testing.

If, once you've read the existing code and the analysis doc, you believe
any of the above is more complex than it looks, or you're not fully
confident in an approach before writing pipeline code, stop and ask
clarifying questions rather than proceeding on an assumption. Getting
this pipeline wrong again is expensive — there is no time pressure on
this project anymore, so there is no reason to guess instead of asking.

## 5. Definition of done for this whole rebuild (before UI/UX phase starts)

Every button, function, resume upload, and feature must be independently
verified working and producing correct output — not just "the happy path
demo works." Concretely, before this phase is considered complete:

- A batch of at least 40 real resumes runs successfully end to end within
  a stated, tested time budget, with visible progress feedback throughout.
- A simulated full-provider-outage run (e.g. via a deliberately invalid
  API key) produces a clearly labeled, non-zero-score-looking failure
  state across the whole batch — not a wall of `0`s that looks like real
  output.
- The fixture-based accuracy test suite passes at an explicitly stated
  accuracy bar you're comfortable defending to a judge.
- Every existing known bug in Section 2 has a corresponding passing test
  that would have caught it, not just a manual confirmation that it no
  longer reproduces.
- Full test suite (unit + integration + the above) is green, and you can
  state, with evidence, what each test category actually covers.

Only once all of the above is true does the UI/UX redesign phase begin —
that phase is explicitly out of scope for this prompt and will be scoped
separately once this is done. There is no deadline pressure on this
project anymore: prioritize correctness, thoroughness, and something
genuinely resume-worthy over speed.

## 6. When the UI/UX phase eventually starts (not now — reference only)

This is out of scope until Section 5's definition of done is fully met,
but is included here so the intent is known in advance and doesn't need
re-explaining in a later prompt:

- Draw component and interaction ideas from: reactbits.dev
  (https://reactbits.dev/get-started/index), 21st.dev
  (https://21st.dev/community/components/week/2026-W29), Aceternity UI
  (https://ui.aceternity.com/components), Dribbble
  (https://dribbble.com/) for visual/layout inspiration, motion.dev
  (https://motion.dev/) for animation patterns, and Magic UI
  (https://magicui.design/docs/components).
- Pick **one** consistent design language/component set from those
  sources and commit to it for the whole app — do not mix components
  from multiple libraries inconsistently across pages. The decision of
  which one gets made explicitly at that time, not guessed at now.
- For color palette, there is a reference collection of ~29 palette
  swatches to choose from — this was shared as an image in a prior
  session and does not carry over automatically. When this phase starts,
  ask the user to re-share that palette collection image before picking
  one, rather than inventing a palette from scratch. Pick one cohesive
  palette from it — one deliberate choice, not several competing
  palettes across the app.
- The interactivity, motion, and "trendy" feel of the rebuilt UI must
  come from the component libraries above, not from custom-built
  animation from scratch — use what those libraries already provide.
- This phase still needs the same discipline as the rest of this
  document: a plan before implementation, and `MILESTONE_LOG.md` entries
  for whatever milestones this phase gets broken into.

## 7. Before you start

Confirm you've read all five files in Section 0, then present your
milestone-by-milestone plan (per Section 3's required structure) for
review before writing any code. Ask now if anything above is ambiguous.
