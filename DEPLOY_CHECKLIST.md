# Deploy checklist — Render (free tier)

Written 2026-07-21, Milestone 7 session. Verified: `Procfile`'s exact
gunicorn command runs `app.py` cleanly in this sandbox (`GET /` and
`GET /api/jds` both returned real 200s against a live gunicorn process).
Not yet verified: an actual Render deployment (that's your step, from
your own Render account — I have no deploy access from this sandbox).

## 1. What's already in place

- `Procfile`: `web: gunicorn app:app --worker-class=gthread --workers=1
  --threads=8 --timeout=120 --bind=0.0.0.0:$PORT`. `--workers=1` is
  deliberate — see the comment in the file itself. Don't "fix" it to a
  higher worker count without first moving `JobStore`/history to shared
  storage (Redis, or a real DB-backed job table) — right now it would
  silently break job polling under real traffic.
- `gunicorn==23.0.0` added to `requirements.txt`.
- `app.run(...)` is already correctly guarded behind `if __name__ ==
  "__main__":` — gunicorn imports `app` as a module and never executes
  that block, so no double-server conflict.
- `MAX_CONTENT_LENGTH` (25MB) and `MAX_FILES_PER_REQUEST` (80) are
  already enforced server-side, independent of hosting platform.

## 2. Environment variables to set in Render's dashboard

| Variable | Required? | Notes |
|---|---|---|
| `GROQ_API_KEY` | Yes | Primary provider. |
| `GEMINI_API_KEY` | Yes | Failover provider (`call_llm_with_failover`). |
| `AI_PROVIDER` | No (defaults to `groq`) | Set explicitly anyway for clarity. |
| `AI_FALLBACK_PROVIDER` | No (defaults to `gemini`) | Same. |
| `PARSELOOM_HISTORY_DB_PATH` | No, but read Section 3 first | Where `runs.db` lives — see below. |

Do **not** commit `.env` — it already isn't (confirmed gitignored). Set
these as real Render environment variables instead.

## 3. The known, already-documented free-tier disk risk (Milestone 4)

Render's free web service tier does not guarantee persistent disk across
redeploys/cold restarts. Two things are affected:

- **In-memory `JobStore`** (live, in-progress jobs) — always lost on any
  restart, by design (`REBUILD_PLAN.md`'s locked "in-memory is enough"
  decision). A job that's mid-batch when the process restarts is gone;
  the user has to re-run it. This is accepted, not a bug to fix here.
- **`instance/parseloom_runs.db`** (persisted run history) — *may* be
  wiped on a cold restart depending on Render's exact free-tier behavior
  on the day. Mitigation already built (Milestone 4): every result view
  has a "Download as Excel (.xlsx)" button, independent of whether
  server-side history survives.

If Render offers a small persistent disk add-on and you want history to
genuinely survive, mount it and set `PARSELOOM_HISTORY_DB_PATH` to a path
on that disk. Otherwise, leave it unset (defaults to `instance/` relative
to the app) and treat history as best-effort, per the already-accepted
Milestone 4 decision.

## 4. Steps

1. In Render: New → Web Service → connect the `ParseLoom` GitHub repo.
2. Build command: `pip install -r requirements.txt`
3. Start command: leave blank (Render reads `Procfile` automatically) or
   explicitly paste the `web:` line from `Procfile` if Render's UI asks.
4. Set the environment variables from Section 2.
5. Deploy. Once live, smoke-test manually:
   - Load the root URL — the JD dropdown should populate (`/api/jds`
     works).
   - Upload 2-3 real resumes, confirm the progress bar moves and a
     shortlist renders.
   - Open a candidate's detail page, confirm "Back to results" closes the
     tab.
   - Download the Excel export, confirm it opens.
6. If anything 500s, check Render's log stream — every error path in this
   app logs real detail server-side and returns only a generic message to
   the browser (Milestone 7's own audit target), so the real cause will
   be in the log, not the browser response.

## 5. Not done as of this checklist

- No load test has been run against Render's actual infrastructure
  (its own timeout/proxy behavior, cold-start latency, etc.) — only
  local/sandbox load testing has been done (see `MILESTONE_LOG.md`'s
  Milestone 8 entry). Worth a real smoke run with several resumes right
  after first deploy, before considering it demo-ready.
