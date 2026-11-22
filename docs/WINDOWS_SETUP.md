# Connect the Windows work laptop to LifeOS

**For:** the AI assistant (Claude) helping the user on their Windows work laptop.
**Goal:** run the LifeOS collector on this laptop so it sends **categories and times only**
to the user's LifeOS hub (their personal Mac) on the home network.

Work through the steps in order. Every step has a check. If a check fails, use the
troubleshooting table, and stop and ask the user whenever a step says **ASK**.

---

## Hard rules (read first)

This is a **company-managed computer**. Company information must never leave it.

1. **Never send or store content.** The device is registered on the hub as content-free,
   so the collector classifies activity on this laptop and sends only: start/end time,
   category, a generic subcategory (e.g. "Coding"), and confidence. Do **not** modify the
   collector, its settings, or the hub to send window titles, URLs, domains, app names,
   file or project names.
2. **Do not install the LifeOS Claude Code hooks** (`hooks/lifeos_hook.py`) on this
   laptop, and do not edit `~/.claude/settings.json` for LifeOS. They would send working
   folders and project names.
3. **The token is a secret.** The user gives it to you in chat. Pass it only as a
   command-line argument to the installer. Never write it into a repo file, commit it,
   or put it in logs or docs.
4. **No admin rights, no system changes.** Everything installs per-user. Don't change
   execution policy machine-wide, firewall rules, proxy settings, or security software.
5. **ASK before installing anything** (ActivityWatch, uv). The user has confirmed their
   employer allows personal tools like ActivityWatch on this laptop, but confirm before
   each install anyway.

---

## Values you need

| Value | Where it comes from |
|---|---|
| Hub URL | `http://192.168.1.142:8765` (the Mac's home-network address). Alternative: `http://MacBook-Pro-3.local:8765` |
| Token | **ASK the user.** It starts with `lfs_`. If they don't have one: on the Mac, open the LifeOS dashboard → Sources → Computers → "Work laptop (Windows)" → ⋯ → New token |
| Device id on the hub | `work-laptop` (already registered as a content-free work device) |

Preconditions for the whole setup:
- the laptop and the Mac are on the same home Wi-Fi;
- the Mac is awake;
- **the work VPN is disconnected** for setup (it usually blocks home-network traffic).

---

## Step 1: Check that the hub is reachable

```powershell
Invoke-RestMethod http://192.168.1.142:8765/api/health
```

**Expected:** `status` = `ok`.

If this times out, see *Troubleshooting → hub not reachable* before going further.
Nothing else will work until this passes.

## Step 2: ActivityWatch

Check whether it's already running:

```powershell
Invoke-RestMethod http://localhost:5600/api/0/info
```

- **If you get JSON back** (with a `version`), go to Step 3.
- **If it fails: ASK the user** for permission to install ActivityWatch, then either:
  - winget, if available: run `winget search activitywatch` first, then `winget install --id <the Id it lists>`; **or**
  - have the user download the Windows installer from https://activitywatch.net/downloads/ and run it.

Then start ActivityWatch (Start menu → ActivityWatch). It runs from the system tray.
Wait about 30 seconds, then re-run the check above until it returns JSON.

Also confirm the watchers are running:

```powershell
(Invoke-RestMethod http://localhost:5600/api/0/buckets/).PSObject.Properties.Value | Select-Object id, type
```

**Expected:** an `afkstatus` bucket and a `currentwindow` bucket.

## Step 3: Get the collector code

Use **one** of these:

**A. From this repo** (if it's already cloned on the laptop):
```powershell
cd <path-to-clone>\life-os
git pull
```
The installer is `scripts\install-collector-windows.ps1`.

**B. From the hub** (no GitHub access needed):
```powershell
cd $env:USERPROFILE
Invoke-WebRequest http://192.168.1.142:8765/api/collect/package -OutFile lifeos-collector.zip
Expand-Archive lifeos-collector.zip -DestinationPath . -Force
cd lifeos-collector
```
The installer is `.\install-collector-windows.ps1`. The package contains only program
code: no data, no tokens.

## Step 4: Run the installer

From the folder that contains the installer (replace `<TOKEN>` with the user's token):

```powershell
# Option A (repo clone):
powershell -ExecutionPolicy Bypass -File .\scripts\install-collector-windows.ps1 -Hub http://192.168.1.142:8765 -Token <TOKEN>

# Option B (downloaded package):
powershell -ExecutionPolicy Bypass -File .\install-collector-windows.ps1 -Hub http://192.168.1.142:8765 -Token <TOKEN>
```

What the installer does:
1. Checks that ActivityWatch is running.
2. Checks for `uv`, a per-user Python runner. If it's missing, it asks `Install it now…? (y/n)`.
   **ASK the user before answering `y`.**
3. Runs `uv sync`, which downloads Python and the dependencies into the project folder.
4. Saves settings to `%LOCALAPPDATA%\LifeOS\collector.json`.
5. Runs `lifeos-collect test` (see Step 5).
6. Registers a per-user Scheduled Task, **"LifeOS Collector"**, that starts at logon and
   syncs every 5 minutes, then starts it.

## Step 5: Verify

The installer's test output should show every line as `[OK]`:

```
  [OK] Settings file
  [OK] ActivityWatch running
  [OK] Window watcher present
  [OK] Hub name resolves
  [OK] Hub reachable — HTTP 200
  [OK] Token accepted — device 'work-laptop' — content-free (categories and times only)
  [OK] Collection enabled
```

**The `Token accepted` line must say `content-free`.** If it says `full detail`, stop
and **ASK** the user: the device is mis-registered on the hub. Don't continue.

Then show the user exactly what is sent. The `backend` folder is under the repo clone
or under the extracted `lifeos-collector` folder:

```powershell
cd <collector folder>\backend
uv run lifeos-collect show
```

Every event must contain only: `aw_event_id`, `piece`, `start_time`, `end_time`,
`category`, `subcategory`, `confidence`, and `evidence.afk_filtered`. If any title,
URL, domain, app or project name appears, **stop and tell the user**.

Run one sync by hand:

```powershell
uv run lifeos-collect run --once
```

**Expected:** `{"status": "ok", ... "batches": N, "events": M}`.

Confirm the background task is running:

```powershell
Get-ScheduledTask -TaskName "LifeOS Collector" | Select-Object TaskName, State
Get-Content "$env:LOCALAPPDATA\LifeOS\collector.log" -Tail 5
```

Last, tell the user to check the Mac's dashboard (Sources → Computers). The laptop
should show **online**, and the Today timeline should have a second lane.

---

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Step 1 times out | VPN on, different network, Mac asleep, or a router that isolates devices (guest Wi-Fi) | Ask the user to disconnect the VPN, confirm both are on the same non-guest Wi-Fi, and wake the Mac. Retry. |
| `MacBook-Pro-3.local` doesn't resolve | `.local` names are blocked on many work laptops | Use `http://192.168.1.142:8765` (already the default here). |
| IP worked before but fails now | The router gave the Mac a new address | Ask the user for the Mac's current IP (on the Mac: `ipconfig getifaddr en0`). Re-run `uv run lifeos-collect setup --hub http://<new-ip>:8765`. Suggest reserving the IP in the router. |
| `running scripts is disabled on this system` even with `-ExecutionPolicy Bypass` | Group Policy enforces signed scripts | Don't try to bypass company policy. Run the installer's steps by hand: `cd backend`, `uv sync --no-dev`, `uv run --no-dev lifeos-collect setup --hub … --token …`, `uv run --no-dev lifeos-collect test`, then `uv run --no-dev lifeos-collect run --every 300` in a terminal the user keeps open. **ASK** before creating any scheduled task by hand. |
| uv install or `uv sync` fails (proxy/TLS errors) | Corporate proxy blocks downloads | Stop and tell the user. Don't change proxy or certificate settings. |
| `[!!] Token accepted — Unknown or revoked device token` | Token mistyped, or replaced by a newer one | Ask the user for a fresh token, then `uv run lifeos-collect setup --token <new>`. |
| Status `paused` | Collection is paused on the hub | Nothing to fix here. The user resumes it from the Mac dashboard header. |
| Status `offline` in the log | Hub unreachable right now (VPN, Mac asleep, away from home) | Expected and harmless. ActivityWatch keeps the data locally and the collector catches up on the next successful run. |
| The VPN is effectively always on | No route to the home network | Switch to **file mode**. The collector writes daily JSON files that the user copies to the Mac's `~/LifeOS/imports/devices/`. See `docs/COLLECTOR.md` → "File mode". Needs the offline config file from the dashboard (Computers → ⋯ → Offline config). |

## Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File <installer path> -Uninstall
Remove-Item -Recurse "$env:LOCALAPPDATA\LifeOS"   # settings and log (optional)
```

Then, on the Mac dashboard: Computers → ⋯ → Revoke token.
