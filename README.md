# LifeOS

A local-first, free-to-run personal system that shows where your time goes, measures meaningful progress across the areas of life that matter, coordinates parallel Claude sessions, and suggests when to continue, switch, or rest.

It is a decision-support tool, not surveillance. Collection is visible and easy to pause. Scores show their evidence. Rest never lowers a score. The product spec is in [LifeOS_Product_Requirements.md](LifeOS_Product_Requirements.md).

## Quick start

Requirements: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 20+ with pnpm (or npm).

```bash
scripts/dev.sh            # API on 127.0.0.1:8765, UI on http://localhost:3000
```

Or start each part separately:

```bash
cd backend && uv sync && uv run lifeos          # API (also runs the background ActivityWatch sync)
cd frontend && pnpm install && pnpm dev         # UI
```

Your data goes in `~/LifeOS/` (database: `~/LifeOS/data/lifeos.db`). Set `LIFEOS_HOME` to use a different folder.

### Try it with demo data first

```bash
cd backend
LIFEOS_HOME=~/LifeOS-demo uv run python -m lifeos.demo
LIFEOS_HOME=~/LifeOS-demo LIFEOS_BACKGROUND_SYNC=0 uv run lifeos
```

The demo command refuses to write to a database that already holds activity.

### Run it in the background on your personal Mac

```bash
scripts/install-launchd.sh               # builds the UI, installs two launchd user agents
scripts/install-launchd.sh --uninstall
```

## Several computers

The Mac is the **hub**. Other computers run a small collector that reads their own ActivityWatch and sends summaries to the hub. See [docs/COLLECTOR.md](docs/COLLECTOR.md). For a step-by-step setup of the Windows work laptop (written so an assistant on that machine can follow it), see [docs/WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md).

- `scripts/install-launchd.sh --lan` lets collectors reach the hub over the home network. Only the token-protected `/api/collect/*` endpoints are reachable from other machines. The dashboard and every other endpoint stay Mac-only, and public IP addresses are refused.
- **Work computers are content-free.** Activity is classified on the laptop, and only category, a generic subcategory and times are sent. The hub discards titles, sites, app and project names even if they arrive.
- Offline, asleep, or on a VPN: the collector catches up later. **File mode** writes daily JSON files instead, which the hub picks up from `~/LifeOS/imports/devices/`.
- The timeline shows one lane per computer. Drift detection and episodes are worked out per computer, so parallel activity isn't mixed together.

## Connecting sources

| Source | How | Notes |
|---|---|---|
| **ActivityWatch** (personal Mac) | `brew install --cask activitywatch`, open it, grant Accessibility. LifeOS syncs from `localhost:5600` every 5 min. | Activity only, not proof of progress. Only active (non-AFK) time counts. Browser tabs keep the domain only. Incognito tabs are recorded as "browser in use" with no details. |
| **Claude Code** | Hooks: see [hooks/README.md](hooks/README.md) | Sets each session to generating / ready / waiting / completed automatically. Desktop and browser sessions are tracked manually. |
| **Apple Health** | Export from the iPhone Health app, then upload under *Sources*, or drop the file in `~/LifeOS/imports/apple_health/` | Keeps only workouts, daily steps, exercise and energy, and sleep totals. |
| **Robinhood** | Download the account activity CSV, then upload it or drop it in `~/LifeOS/imports/robinhood/` | No login and no API. Re-importing the same rows is deduplicated. |
| **Logic Pro** | Set the project folders in *Settings* (default `~/Music/Logic`) | Reads file names and timestamps only, never musical content. |
| **Work computers** | *Sources → Devices*. Add as a work device. | Unmonitored by default. Accepts only summaries you type in until you confirm your employer's policy allows monitoring. Window titles are never stored. |
| **Other collectors** | `POST /api/activity/ingest` or upload JSON/CSV | Every event carries a device and source and is deduplicated by `source_key`. |

## How it works

```
backend/lifeos/
  main.py                  FastAPI app, background sync loop (localhost only)
  models.py                SQLAlchemy schema (all datetimes naive UTC)
  services/
    activitywatch.py       AW REST client; AFK filtering; per-day idempotent upsert
    classification.py      deterministic rules → category + confidence
    activity.py            ingestion/dedup, timeline blocks, category totals
    intervals.py           interval math (union/intersect/stretches)
    goals.py               weekly goal progress from evidence
    scoring.py             transparent life score + separate orchestration metric
    recovery.py            adaptive multi-signal break assessment
    orchestrator.py        ranked next-action suggestions with reasons
    sessions.py            Claude session state machine + hook mapping
    imports.py             Apple Health / Robinhood / music / summaries + history
  importers/               pure parsers (streaming Apple Health XML, Robinhood CSV, Logic folders)
frontend/                  Next.js App Router + Mantine UI (Today, Sessions, Tasks, Insights, Sources, Settings)
hooks/lifeos_hook.py       stdlib-only Claude Code hook (non-blocking, always exits 0)
```

**Scoring** (spec §4). There are four dimensions: progress 50%, maintenance 20%, recovery 20%, intentionality 10%. You can change the weights.
- Progress and maintenance come from weekly goals. Each goal is capped at 100%, and goals are averaged within a domain before across domains.
- A dimension with no goals or no data is left out and the remaining weights are renormalized, so it never counts as zero.
- Recovery looks at how long you stay at the screen without a break, how many breaks you take, total screen time, and sleep when Apple Health provides it. Days off score 100%, and logged breaks can only raise the score.
- More screen time never raises the score. A test enforces this.
- Orchestration (`M = 0.30P + 0.25W + 0.20C + 0.15T + 0.10A`) is shown separately and labeled exploratory.

**What you're actually doing.** Each event gets a category and a subcategory (Coding, Terminal / Claude Code, AI assistant, Messaging, Watching videos, Short-form video…).
- Without a browser extension, the site is worked out from window titles.
- On video and social sites, the title decides: a Python tutorial counts as software. Topic keywords are editable under *Settings → What's on screen*.
- Hopping through many short items becomes **Drift**. Staying with one video is **Leisure**.
- The day is grouped into episodes, and short hops are collected as **detours**.
- After about 10 minutes of drift, a gentle prompt asks whether it's a break.
- Lock-screen time is not counted as activity.

**Confidence.**
- High: user-confirmed or recorded (workouts, corrections, check-ins).
- Medium: strong signals from apps or domains.
- Low: weak inference, shown striped on the timeline.

Corrections and exclusions are kept through re-syncs and rule changes.

## Tests

```bash
cd backend && uv run pytest        # 92 tests
cd frontend && pnpm lint           # TypeScript check
```

The tests cover normalization, DST-safe day boundaries, interval math, dedup, re-sync idempotency, carried-over corrections, privacy gates for work devices, scoring invariants, recovery and recommendation rules, the importers, and the API flows.

## Status against the spec's phases

- **Phase 1, foundation (done):** FastAPI and SQLite, devices, categories, rules, ActivityWatch ingestion, timeline, category totals, correction and exclusion, tests.
- **Phase 2 (done):** projects, tasks, milestones, weekly goals, the manual session board with attention indicators, rule-based next action.
- **Phase 3 (done, pending real data):** Apple Health import, Robinhood CSV import, Logic folder signals, work-device summaries, import history.
- **Phase 4 (done):** configurable scores with evidence, recovery engine, 60-second daily review, insights.
- **Phase 5 (partial):** Claude Code hooks are done. Optional Ollama summarization is intentionally not built. The spec says to add it only after the deterministic system has proven itself.

## Open decisions (spec §16)

These currently have safe defaults that you can change in *Settings*:
1. **Claude clients:** Claude Code (hooks) by default. Desktop and browser are manual.
2. **Work devices:** unmonitored, summaries only.
3. **Break style:** adaptive.
4. **Orchestrator autonomy:** suggest only. It never acts on its own.
5. **Weekly goals:** none preset. Set them on *Tasks & goals*, or copy them from last week.

## Privacy

- The API binds to `127.0.0.1` only, and the browser reaches it through the Next.js proxy.
- There are no cloud services, paid APIs or LLM calls.
- Brokerage credentials are never asked for or stored.
- Import errors are logged without the contents of the source file.
- Use *Sources → Your data* to export everything as JSON or delete it by scope.
- The header has a global **pause** switch.
