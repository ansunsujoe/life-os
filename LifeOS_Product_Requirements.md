# LifeOS --- Personal Productivity & Life-Balance System

## Product requirements and implementation handoff

**Document purpose:** Give an implementation agent (Claude) a
sufficiently complete product and technical specification to build the
first usable version of LifeOS.

**Status:** Requirements baseline / implementation handoff\
**Primary user:** One software developer who works across multiple
computers, uses Claude heavily, trades stocks, produces music, learns
new skills, exercises, and wants to remain intentional about faith,
recovery, and life outside work.

------------------------------------------------------------------------

# 1. Product vision

Build a mostly automated, local-first personal system that helps the
user understand how they spend time, measure meaningful progress across
important areas of life, coordinate parallel work (especially multiple
Claude sessions), and recognize when to change tasks or take a break.

LifeOS should answer five questions:

1.  **What am I actually spending my time on?**
2.  **Am I making meaningful progress in the areas that matter?**
3.  **When several Claude sessions or projects are running, what is the
    best next action?**
4.  **Am I using waiting time well without fragmenting my attention?**
5.  **Would I benefit more from continuing, switching tasks, or
    recovering?**

The product is not a surveillance system, a time-tracking scoreboard, or
a machine that maximizes screen time. It is a personal decision-support
tool that helps the user make intentional choices and maintain a
sustainable balance.

## Product principles

-   **Local-first and privacy-first.** Keep raw activity, personal
    reflections, and sensitive data on the user's personal machine
    wherever practical.
-   **Free to operate.** No subscriptions, paid hosted services, paid
    LLM APIs, or required cloud infrastructure. Prefer open-source
    software and deterministic local processing.
-   **Automate collection, not meaning.** Collect objective signals
    automatically where possible, but ask the user to confirm subjective
    outcomes that cannot be inferred reliably.
-   **Measure outcomes, not appearances.** An app being open does not
    prove productive work. A profitable trade does not necessarily mean
    a good trading decision.
-   **Balance matters.** Professional output is important, but so are
    health, faith, music, learning, relationships, and recovery.
-   **Never reward burnout.** Rest should not lower the score. More
    screen time, more open Claude sessions, or more task switching must
    not automatically count as better performance.
-   **Suggestions, not coercion.** The system recommends the next
    action; the user remains in control.
-   **Transparent scoring.** The user should be able to see why a score
    or recommendation was produced and correct misclassified activity.
-   **Start simple.** Build a dependable activity timeline and a small
    set of useful workflows before adding sophisticated AI.

# 2. User context and operating environment

## Devices

-   Personal Mac --- intended to host the main LifeOS service, database,
    and dashboard.
-   Work Mac.
-   Work Windows computer.
-   Apple Watch, with health/activity data available through the Apple
    Health ecosystem.

Work computers may have corporate security restrictions. Do not install
monitoring, synchronization, or automation software on either work
device unless the user confirms that it is permitted. If installation is
not allowed, support manual imports or user-provided aggregate summaries
instead.

## Applications and services

-   **AI-assisted development:** Claude, potentially Claude Code, Claude
    Desktop, and/or Claude in a browser. Exact mix is to be confirmed.
-   **Trading:** Robinhood.
-   **Music production:** Logic Pro.
-   **Development tools:** IDEs, terminals, browsers, local tools, and
    project-specific applications.
-   **Learning:** Browser-based documentation, courses, tutorials,
    books, and other learning resources.
-   **Faith:** Bible reading, prayer, Christian service/actions, church,
    and community.
-   **Exercise and recovery:** Apple Watch / Apple Health data and
    manual check-ins.

## Important constraints

-   No paid API keys or hosted LLM dependencies.
-   No unofficial Robinhood API integration and no storing brokerage
    credentials.
-   Do not capture source code, screenshots, browser contents, brokerage
    details, or other sensitive work information from corporate devices.
-   No continuous screenshot recording by default.
-   All monitoring must be visible, configurable, and easy to disable.
-   Do not assume Claude Desktop or browser session states can be
    automatically detected. Support manual status updates and deeper
    integration only where a supported interface exists.

# 3. Core product experience

The main dashboard should make it easy to understand the day and decide
what to do next.

## 3.1 Dashboard

Show:

-   Today's activity timeline, grouped into meaningful categories.
-   Time spent by category and device, with confidence indicators.
-   Progress toward weekly goals.
-   Meaningful milestones completed today and this week.
-   Current Claude sessions and their states.
-   A suggested next action, with a short explanation.
-   Recovery indicators and break suggestions when warranted.
-   A lightweight daily review entry point.
-   A clear distinction between observed activity, inferred activity,
    and user-confirmed progress.

The dashboard should not present a single opaque score as the whole
truth. Show component scores and evidence.

## 3.2 Main life domains

Initial domains:

1.  Software development / professional work.
2.  Trading.
3.  Music production.
4.  Learning.
5.  Faith and Christian action.
6.  Physical health / exercise.
7.  Recovery, relationships, and offline life.

Allow the user to edit categories, goals, weights, and classification
rules without changing code.

# 4. Measurement and scoring

## 4.1 Scoring philosophy

LifeOS measures intentional, meaningful progress and sustainable
balance---not raw hours.

Examples:

-   Development: verified task or milestone progress, not simply time in
    VS Code.
-   Trading: process quality, risk discipline, and adherence to a
    plan---not profit and loss alone.
-   Music: composition, arrangement, sound-design, mixing, or export
    milestones---not simply Logic Pro being open.
-   Learning: retained understanding and practical application---not
    video duration.
-   Faith: intentional practice and lived action---not how long a Bible
    app is open.
-   Health: meaningful movement, exercise, and recovery---not maximizing
    activity rings at all costs.

## 4.2 Initial high-level score model

Use the following as a configurable starting point, not a permanent
truth:

  ------------------------------------------------------------------------
  Dimension                           Initial weight What it represents
  --------------------- ---------------------------- ---------------------
  Meaningful progress                            50% Progress toward goals
                                                     in work, trading,
                                                     music, and learning

  Physical and                                   20% Exercise,
  spiritual maintenance                              health-supporting
                                                     routines,
                                                     Scripture/prayer, and
                                                     intentional practice

  Recovery and life                              20% Breaks,
  balance                                            sleep-supporting
                                                     behavior, offline
                                                     time, and sustainable
                                                     pacing

  Intentionality                                 10% Whether time was
                                                     spent deliberately
                                                     and aligned with
                                                     chosen priorities
  ------------------------------------------------------------------------

The weights must be editable. Do not penalize a user for having a day
when one domain is not relevant. Use weekly goals and rolling windows so
the score does not demand that every domain receive attention every day.

## 4.3 Daily and weekly views

Provide: - A daily overview that describes what happened, without making
a missed day feel like failure. - A rolling weekly score and domain
breakdown. - Weekly goal progress. - Trends over time. - A way to
inspect the evidence behind every score.

Do not use negative streaks, missed-day penalties, shame-based
notifications, or unlimited rewards for overachievement. Cap credit
where appropriate so overworking one domain cannot overwhelm the balance
model.

## 4.4 Confidence and evidence

Every automatically inferred event should carry a confidence level:

-   **High:** explicit user confirmation, an imported workout, or a
    clearly recorded event.
-   **Medium:** a strong application or project signal, such as active
    Logic Pro usage or a project file modification.
-   **Low:** weak inference, such as an educational-looking browser tab.

Low-confidence activity should be labeled as inferred and may be
confirmed during the daily review. Users must be able to correct
categories and exclude events.

## 4.5 Separate productivity from orchestration

Keep two concepts distinct:

-   **Productivity:** meaningful progress and outcomes.
-   **Work orchestration:** how effectively the user coordinates
    attention, parallel tasks, waiting time, and context switches.

Orchestration can contribute modestly to professional-work insights, but
it must not become a proxy for total productivity.

A possible exploratory orchestration formula is:

`M = 0.30P + 0.25W + 0.20C + 0.15T + 0.10A`

Where: - `P` = parallel progress (useful progress across independent
tasks), - `W` = waiting-time utilization, - `C` = effective context
switching, - `T` = task completion, - `A` = attention management.

Treat this formula as a starting hypothesis. Validate it with real use
and keep it configurable. Do not reward opening more sessions or
switching frequently.

# 5. Activity collection and integrations

## 5.1 ActivityWatch

Use [ActivityWatch](https://activitywatch.net/) as the primary optional
automatic computer-activity collector.

Potential coverage: - App/window usage. - Active versus idle time. -
Broad application categories. - Device-level activity.

Install on the personal Mac first. Add work devices only after the user
confirms corporate policy permits it.

ActivityWatch data is evidence of computer activity, not proof of
meaningful progress. It should not independently award full progress
credit.

Potential reference: ActivityWatch project documentation and its current
synchronization options. Verify the current supported version and
compatibility before selecting a sync design. Do not assume an `aw-sync`
workflow is supported without checking.

## 5.2 Multi-device architecture

Preferred initial architecture: - Personal Mac hosts the local API,
SQLite database, and dashboard. - Each permitted computer runs a local
collector. - Collectors send only the minimum required metadata. - Every
event includes a device identifier and source. - Deduplicate events
during ingestion.

For work devices, transmit only privacy-preserving aggregate metadata
where approved (for example, category duration and idle time). Do not
transmit source code, screenshots, sensitive window titles, document
contents, or application data.

[Syncthing](https://syncthing.net/) may be evaluated for free
peer-to-peer file synchronization, but it is optional. Verify security,
compatibility, and organizational permission before using it. Do not
make it a required dependency.

Fallbacks: - Manual CSV/JSON import. - User-entered work summaries. - A
local-only collector that never syncs raw data.

## 5.3 Apple Watch / Apple Health

Apple HealthKit is the supported Apple health-data ecosystem: [Apple
HealthKit
documentation](https://developer.apple.com/documentation/healthkit).

Initial implementation: - Support importing an Apple Health export from
the iPhone. - Parse the exported XML locally in Python. - Extract only
useful summary data, such as workouts, activity, and sleep where
available and authorized. - Normalize timestamps and units. - Avoid
collecting more health information than necessary.

Future enhancement: - A small native iOS companion using HealthKit for
more automated access, if the user chooses to build it.

Do not infer fatigue or health status from heart rate alone. Treat watch
signals as context, not medical conclusions.

## 5.4 Robinhood

Initial implementation: - Support importing user-downloaded Robinhood
account/activity CSV reports. - Provide a clear import workflow and a
dedicated local import folder, such as `LifeOS/imports/robinhood/`. -
Deduplicate imported records. - Track transaction and position-related
events only to the extent the export provides them. - Keep financial
data local and out of any optional LLM prompts.

Do not: - Use unofficial APIs. - Ask for or store Robinhood login
credentials. - Automate brokerage actions. - Treat profit and loss as
the sole measure of trading quality.

Trading evaluation should focus on process where the user can provide
it: - Did the trade follow the user's plan? - Was risk sized
appropriately? - Was the entry/exit reason recorded? - Were rules
followed? - Was the time spent researching or monitoring intentional?

Transaction history cannot reveal all of these. Include optional manual
trade notes and a lightweight post-session review. Make it explicit when
data is unavailable.

## 5.5 Logic Pro and music projects

Initial signals: - ActivityWatch application usage. - Project-directory
file creation/modification timestamps. - Project saves, exports, and
other file-system events where observable. - Optional manual milestones.

Do not parse the musical content of projects in the first version.

Possible milestones: - Sketch created. - Motif or section developed. -
Arrangement extended. - Orchestration pass completed. - Sound design
completed. - Mix revision completed. - Bounce/export produced.

Time in Logic Pro is context, not proof of creative progress.

## 5.6 Learning

Use application/browser activity as a weak signal, with optional user
confirmation.

A short learning checkpoint can ask: - What did you learn? - Can you
explain it in your own words? - Did you apply it to a project or
problem?

Support manual entries and links/notes. Do not assume that a browser tab
or long video session equals learning.

## 5.7 Faith and Christian action

Faith tracking should be intentionally lightweight and user-controlled.

Possible optional check-ins: - Scripture reading or study. - Prayer. -
Encouraging or serving someone. - Other intentional Christian action. -
Church or community involvement.

Do not turn faith into a competitive point system or infer spiritual
commitment from device usage. The purpose is reflection and
intentionality, not surveillance or a religious productivity contest.

## 5.8 Screenshots and OCR

Not required for the MVP.

If considered later: - Explicit opt-in only. - Local processing only. -
Selected applications/windows only. - Clear pause/disable control. -
Exclude brokerage apps, password managers, private communications, and
sensitive work applications by default. - Never silently record or
upload screen contents.

# 6. Claude session management and multitasking

This is a major product feature.

The user may have several Claude sessions working on different tasks or
projects. LifeOS should help track which sessions need attention and
identify useful work to do while another session is generating.

## 6.1 Claude session model

Track sessions independently with fields such as:

-   Session ID (if a supported integration exposes one).
-   Project.
-   Task or objective.
-   Device.
-   Tool/client type (Claude Code, Desktop, browser, or other).
-   State.
-   Start time.
-   Last interaction time.
-   Expected next action.
-   Whether user attention is needed.
-   Optional notes.

Suggested states: - `Generating` - `Ready` - `Blocked` - `Waiting` -
`Paused` - `Completed`

The user must be able to create and update a session manually. Do not
require an integration to use the session manager.

## 6.2 Integration levels

Implement in stages:

**Level 1 --- Activity inference** - Use ActivityWatch to detect broad
use of Claude-related applications. - This does not reliably identify
individual sessions or their true state. - Clearly label this
information as inferred.

**Level 2 --- Manual session registration (MVP target)** - Provide a
quick UI, menu-bar action, or shortcut to register a session with
project, task, and state. - Make state changes fast (ideally one or two
interactions). - Allow the user to mark a session as needing
attention. - Show all active sessions in one dashboard.

**Level 3 --- Claude Code lifecycle integration** - Investigate
supported Claude Code hooks/events, such as tool-use lifecycle and
stop/notification events, using current official documentation:
https://docs.claude.com/en/docs/claude-code/hooks - Where supported, use
local hook scripts to update LifeOS session state. - Keep hook behavior
small, reliable, and non-blocking. - Do not assume Claude Desktop or
browser sessions expose equivalent hooks. Use manual updates unless a
documented integration exists.

## 6.3 Useful concurrency

Reward useful parallel work, not the number of open sessions.

Good example: - Session A is generating. - The user reviews a completed
result from Session B. - The user makes progress on a separate music or
learning task while Session A runs.

Bad signals to avoid rewarding: - Opening many sessions without
progressing. - Switching every few minutes without completing useful
work. - Keeping sessions open that are blocked or abandoned. -
Multitasking so aggressively that quality falls.

Provide a view of: - Sessions currently generating. - Sessions ready for
review. - Sessions blocked or waiting. - Sessions that have been idle
for a long time. - The best next action based on priority and context.

# 7. Task and goal management

## 7.1 Tasks

A task should support: - Title and description. - Domain/category. -
Project. - Priority. - Estimated effort or duration. - Mental demand
(low / medium / high). - Status. - Due date, if applicable. - Next
concrete action. - Milestones. - Optional dependencies or blockers.

## 7.2 Milestones and momentum

Large tasks should be decomposed into achievable milestones.

The system should: - Give credit for verified intermediate progress. -
Show the next small action. - Detect possible stagnation (for example, a
long period without a milestone or repeated failed attempts, when
evidence exists). - Suggest reducing scope, asking Claude to explain a
failure, trying a different approach, switching to a different kind of
task, or taking a break. - Recognize progress after a difficult period.

Do not label the user as lazy or unproductive. Avoid guilt-based
messaging and negative streaks.

## 7.3 Weekly goals

Prefer weekly goals to rigid daily quotas.

Examples: - Make progress on a particular software project. - Complete a
music arrangement milestone. - Practice or study a chosen skill. -
Exercise a chosen number of times. - Maintain a realistic faith
practice. - Protect recovery and offline time.

Goals should be adjustable and should not require every domain to be
active every day.

# 8. Recovery engine and adaptive breaks

Breaks should be adaptive rather than governed by a rigid Pomodoro
timer.

Potential signals: - Time since the last meaningful break. - Length of
uninterrupted active computer use. - Excessive application/context
switching. - Repeated failed attempts or rework. - Long periods of
intense interaction. - Watch movement/activity trends. - User-reported
energy or fatigue.

Use multiple signals together where possible. A single signal should
rarely trigger a strong conclusion. Do not interrupt deep work
arbitrarily.

Suggested break types: - **Microbreak:** 2--5 minutes. - **Short
break:** 5--15 minutes. - **Long break:** 20--40 minutes. - **Deep
recovery:** 1+ hour or an intentional stop for the day.

Recommendations should be contextual: - Stretch or walk briefly. - Rest
eyes. - Get water. - Step away from the screen. - Take a longer offline
break. - Stop work for the day when appropriate.

Rules: - Breaks never reduce productivity or balance scores. - Recovery
may improve the recovery/balance dimension. - Do not imply that heart
rate or watch data diagnoses fatigue. - Let the user dismiss, snooze, or
disable suggestions. - Learn from user feedback over time, but do not
silently change important scoring rules.

# 9. Next-action orchestrator

The orchestrator recommends what the user should do next. It does not
automatically take over the user's work.

Inputs may include: - Task priorities and deadlines. - Claude sessions
that need attention. - Which sessions are generating or waiting. - Task
mental demand. - Recent activity and context switches. - User-reported
energy. - Time available. - Weekly goals and neglected domains. -
Recovery signals. - The value of taking a break.

Possible recommendations: - Review output from a Claude session that is
ready. - Continue a high-priority task. - Do a short independent task
while another session generates. - Switch to a lower-cognitive-load
task. - Work on music or learning when it is a sensible change of
context. - Record a trading note or end a trading session. - Take a
break. - Stop for the day.

Every recommendation should include a brief reason, such as: - "This
Claude session is ready for review." - "Your current task appears
stalled; try a smaller milestone." - "You have been at the screen for a
long stretch with little movement." - "You have not made progress on
this weekly goal yet." - "A short, low-demand task fits the time
available."

The user chooses whether to follow the recommendation. Do not
automatically switch applications, execute trades, or modify projects.

# 10. Daily review

Provide a very short daily review, designed to take about 60 seconds.

Possible prompts: - Did you spend intentional time on Scripture or
prayer? - What did you learn today? - Did you make meaningful progress
on music? - Was there a meaningful Christian action or act of service? -
How was your energy today? (for example, 1--5) - Is there anything
important the activity tracker misunderstood? - Optional freeform note.

Do not force every prompt every day. Allow skipping. The review should
help fill gaps in automatically collected data, not become another
chore.

# 11. Technical architecture

## 11.1 Recommended initial stack

-   **Frontend:** Next.js App Router, React, Mantine, and TypeScript.
-   **Backend:** Python + FastAPI.
-   **Database:** SQLite for the initial single-user local deployment.
-   **Collectors/importers:** Python scripts and ActivityWatch
    integration.
-   **Classification:** Configurable deterministic rules first.
-   **Optional local AI:** Ollama, only if already available and useful.
    No required hosted model or paid API.
-   **Scheduling:** macOS `launchd` and platform-appropriate scheduled
    tasks where needed.
-   **Deployment:** Local services on the personal Mac. No cloud
    deployment required for the MVP.

The user is comfortable with Next.js, React, Mantine, Python, FastAPI,
and local LLM workflows. Prefer a maintainable implementation over
unnecessary abstractions.

## 11.2 Architectural modules

1.  **Activity Collector**
    -   Ingests ActivityWatch events and supported local signals.
    -   Normalizes event formats.
    -   Tracks source, device, and confidence.
2.  **Session Manager**
    -   Manages Claude sessions and their states.
    -   Supports manual registration and future hooks.
3.  **Goal Manager**
    -   Manages domains, projects, tasks, milestones, and weekly goals.
4.  **Scoring Engine**
    -   Computes transparent daily/weekly measures from evidence and
        confirmations.
    -   Keeps productivity and orchestration distinct.
5.  **Recovery Engine**
    -   Evaluates break/recovery signals and creates recommendations.
6.  **Orchestrator**
    -   Ranks possible next actions and explains its recommendation.
7.  **Import/Integration Layer**
    -   Handles Apple Health exports, Robinhood CSVs, and music project
        signals.
8.  **Dashboard and Review UI**
    -   Presents the timeline, goals, sessions, scores, and daily
        review.

## 11.3 Suggested data model

Use a practical schema and evolve it as implementation reveals needs.
Suggested entities:

-   `devices`
-   `activity_events`
-   `activity_categories`
-   `projects`
-   `tasks`
-   `task_milestones`
-   `weekly_goals`
-   `claude_sessions`
-   `health_metrics`
-   `trading_events`
-   `trading_notes`
-   `music_sessions`
-   `daily_reviews`
-   `recommendations`
-   `user_settings`
-   `imports` / `imported_records`

A normalized activity event could include:

``` json
{
  "start_time": "ISO-8601 timestamp",
  "end_time": "ISO-8601 timestamp",
  "category": "software | trading | music | learning | faith | health | recovery | other",
  "activity": "descriptive activity label",
  "source": "activitywatch | apple_health | robinhood_csv | manual | filesystem | claude_hook",
  "device_id": "device identifier",
  "confidence": "high | medium | low",
  "evidence": {}
}
```

Store timestamps consistently (prefer UTC internally) and display them
in the user's local timezone. Preserve source identifiers to support
deduplication and auditing.

## 11.4 API and service expectations

Design clean endpoints for: - Activity ingestion and querying. -
Category/rule configuration. - Devices. - Projects, tasks, milestones,
and goals. - Claude session creation and state updates. - Health and
trading imports. - Daily reviews. - Score calculation and score
explanations. - Recommendations and user feedback.

Keep scoring logic in a testable service/module, not embedded in
frontend components.

## 11.5 Local-first security

-   Bind local services to localhost by default.
-   Do not expose the API to the public internet.
-   Avoid storing secrets unless strictly necessary.
-   Do not store brokerage credentials.
-   Keep financial and health records out of optional LLM context.
-   Provide data export and deletion.
-   Make collection status visible.
-   Support per-device and per-source disable controls.
-   Log import failures without dumping sensitive source contents.

# 12. User interface requirements

The interface should be clear, fast, and useful during a busy workday.

Suggested main navigation: - **Today** --- timeline, score breakdown,
recommendation, daily review. - **Sessions** --- Claude session board. -
**Tasks** --- projects, tasks, milestones, weekly goals. - **Insights**
--- trends, domain balance, orchestration, recovery. - **Sources** ---
devices, collectors, imports, integrations, privacy controls. -
**Settings** --- categories, weights, schedules, thresholds, and
preferences.

Important UI behavior: - Show confidence and source labels on inferred
activity. - Make correction of a category easy. - Make session-state
updates quick. - Show why a recommendation was made. - Keep the daily
review short. - Do not use alarming colors or shame-oriented copy for
ordinary missed goals. - Make pause/disable controls easy to find.

# 13. MVP scope and implementation sequence

Build in increments. The first version should be useful even before all
integrations exist.

## Phase 0 --- Confirm environment and policies

Before installing anything: - Confirm whether ActivityWatch is allowed
on each work computer. - Confirm which Claude clients are used. -
Confirm whether local background services are acceptable on the personal
Mac. - Confirm preferred break behavior and orchestrator autonomy. -
Inspect current ActivityWatch and Claude Code documentation rather than
relying on assumptions.

## Phase 1 --- Local foundation and activity timeline

1.  Create the repository and project structure.
2.  Set up FastAPI and SQLite.
3.  Define devices, activity events, categories, and source metadata.
4.  Integrate ActivityWatch on the personal Mac.
5.  Implement deterministic category rules.
6.  Build a basic dashboard timeline and category summary.
7.  Add correction and exclusion of events.
8.  Add tests for normalization, time calculations, and deduplication.

**Exit criterion:** The user can see a reasonably accurate local
timeline and correct its classifications.

## Phase 2 --- Tasks, goals, and Claude session manager

1.  Add projects, tasks, and milestones.
2.  Add weekly goals.
3.  Build the manual Claude session manager.
4.  Add session states and attention-needed indicators.
5.  Build the Sessions view.
6.  Add a simple next-action recommendation based on explicit rules.

**Exit criterion:** The user can track multiple Claude sessions and see
which one needs attention and what task to do next.

## Phase 3 --- Additional devices and personal data imports

1.  Add work-device collectors only if approved.
2.  Otherwise add manual summary/import workflows.
3.  Add Apple Health export import.
4.  Add Robinhood CSV import and deduplication.
5.  Add Logic Pro project-directory signals.
6.  Add import history and error handling.

**Exit criterion:** Useful cross-domain signals are available without
violating work policies or requiring paid services.

## Phase 4 --- Scoring and recovery

1.  Implement configurable daily and weekly scoring.
2.  Keep productivity, orchestration, and recovery indicators separate.
3.  Add score explanations and evidence inspection.
4.  Add adaptive break recommendations.
5.  Add the daily review.
6.  Add weekly insights and goal progress.

**Exit criterion:** Scores are explainable, correctable, and do not
reward overwork.

## Phase 5 --- Claude Code hooks and smarter orchestration

1.  Investigate supported Claude Code hooks.
2.  Add optional local hook scripts.
3.  Improve session state automation.
4.  Improve next-action ranking using explicit rules.
5.  Optionally evaluate local Ollama for summarization/classification
    only after the deterministic system works.

**Exit criterion:** Claude Code sessions update with less manual effort,
and recommendations are useful without taking control away from the
user.

# 14. Acceptance criteria

The MVP is successful when:

-   The user can run LifeOS locally without a paid service.
-   Activity from the personal Mac appears in a timeline.
-   Events are categorized with visible confidence and source
    information.
-   The user can correct or exclude events.
-   The user can create tasks, milestones, and weekly goals.
-   The user can register multiple Claude sessions and update their
    states quickly.
-   The dashboard identifies sessions that are ready, blocked, or
    waiting for attention.
-   The system can suggest a reasonable next task or break and explain
    why.
-   Daily and weekly scores are transparent and configurable.
-   Rest does not reduce the score.
-   Trading performance is not judged by P&L alone.
-   Faith is not inferred from device activity or reduced to a
    competitive score.
-   Health data is imported only with user consent and is not treated as
    medical diagnosis.
-   No corporate device is monitored without explicit permission.
-   No brokerage credentials or unofficial brokerage API are used.
-   The system remains useful when optional integrations are
    unavailable.

# 15. Explicit non-goals

Do not build these into the initial product:

-   A public SaaS or multi-user platform.
-   Cloud-hosted databases or paid infrastructure.
-   Paid LLM API dependencies.
-   Automatic trading or brokerage control.
-   Continuous screen recording or default screenshot OCR.
-   Collection of source code or sensitive work content.
-   A system that automatically changes tasks or takes actions without
    approval.
-   A rigid Pomodoro timer as the primary recovery mechanism.
-   A leaderboard, streak game, or guilt-based productivity score.
-   A complex AI agent before the underlying data is reliable.

# 16. Open decisions to confirm with the user

Do not block the local foundation on every answer. Use safe defaults and
make these configurable.

1.  **Claude usage:** Claude Code, Desktop, browser, or a mixture?
2.  **Work-device permissions:** Can approved personal utilities be
    installed on the work Mac/Windows machine, or must those devices
    remain unmonitored?
3.  **Break style:** Adaptive recommendations, flexible intervals, or
    alerts only after excessive continuous work?
4.  **Orchestrator autonomy:** Suggest the next task; organize a queue
    but require approval; or proactively manage reminders/tasks while
    still requiring approval for consequential actions?
5.  **Initial category and weekly-goal targets:** Let the user configure
    these during onboarding rather than hard-code assumptions.

# 17. Instructions to the implementation agent

Build this as a practical personal tool, not as an elaborate theoretical
platform.

Recommended working approach:

1.  Inspect the current environment and verify relevant external
    integration documentation.
2.  Propose a concrete repository structure and implementation plan.
3.  Implement Phase 1 end-to-end before adding every integration.
4.  Keep the application runnable after each phase.
5.  Add tests for data normalization, time aggregation, scoring,
    deduplication, and recommendation rules.
6.  Use deterministic rules for the core product. LLMs are optional
    helpers, not a dependency.
7.  Keep the system local-first and free to operate.
8.  Make uncertain inferences visible and correctable.
9.  Never silently collect sensitive information or install software on
    corporate devices.
10. At each milestone, summarize what works, what remains, and how to
    run it.

**First implementation task:** Build the local LifeOS foundation:
FastAPI + SQLite, ActivityWatch ingestion on the personal Mac,
configurable activity categories, and a basic Next.js/Mantine dashboard
showing today's timeline and category totals. Do not begin with AI
agents, health imports, brokerage integrations, or automatic screen
capture.
