# LifeOS collector — connecting another computer

The **hub** is the Mac running LifeOS. Each other computer runs a small
**collector** that reads *its own* ActivityWatch and sends summaries to the hub.

```
 Windows laptop                                 Mac (hub)
 ┌──────────────────────┐   home network     ┌──────────────────────────┐
 │ ActivityWatch        │   token-protected  │ LifeOS API               │
 │   ↓ (local only)     │ ─────────────────▶ │  /api/collect/* only     │
 │ lifeos-collect       │                    │  dashboard: this Mac only│
 └──────────────────────┘                    └──────────────────────────┘
          └── or: daily JSON files ──▶ ~/LifeOS/imports/devices/ (file mode)
```

## What leaves a work computer

The hub marks work devices as **content-free**. The collector classifies activity
on the laptop using the hub's rules and sends only:

| Sent | Never sent |
|---|---|
| start and end time (per activity) | window titles (file names, tickets, customers) |
| category (e.g. *Software*) | websites and URLs (e.g. internal Jira or wiki) |
| generic subcategory (e.g. *Coding*, *Quick hopping*) | app names (internal tools) |
| confidence (low/medium/high) | project or folder names |

The hub enforces this as well: anything else sent from a work device is discarded
before it is stored. Titles are only read on the laptop itself, inside
ActivityWatch's local database. Check what would be sent at any time:

```powershell
cd <collector folder>\backend
uv run lifeos-collect show
```

## Setup

1. **On the Mac (once):** `scripts/install-launchd.sh --lan`. Only the token-protected
   collector endpoints become reachable from the home network. The dashboard stays local.
2. **In the dashboard:** *Sources → Devices → Connect a computer*. Choose
   *Work computer*, copy the token, and download `lifeos-collector.zip`.
3. **On the laptop:**
   - Install [ActivityWatch](https://activitywatch.net/downloads/) and start it.
   - Extract the zip and run:
     ```powershell
     powershell -ExecutionPolicy Bypass -File .\install-collector-windows.ps1 -Hub http://MacBook-Pro-3.local:8765 -Token lfs_…
     ```
   - The script runs `lifeos-collect test` and registers a background task that runs at logon.

## When it can't reach the hub

| Symptom (`lifeos-collect test`) | Cause | Fix |
|---|---|---|
| Hub name doesn't resolve | `.local` names not resolving | Use the Mac's IP address, and reserve it in your router |
| Hub not reachable | Mac asleep or away, different network, or a work VPN routing everything to the company | The collector catches up later (ActivityWatch keeps the data). If the VPN is always on, use file mode |
| Token rejected | Token revoked or regenerated | Create a new token in *Sources → Devices* |

Nothing is lost while the hub is unreachable. On the next successful run, the
collector resends every day since its last success.

## File mode (no network)

```powershell
powershell -ExecutionPolicy Bypass -File .\install-collector-windows.ps1 -ExportDir "$env:USERPROFILE\LifeOS-outbox" -ConfigFile .\lifeos-collector-config-work-laptop.json
```

The config file can be downloaded from the device's row on the hub. Copy or sync
the outbox files into `~/LifeOS/imports/devices/` on the Mac, then click
*Import device files* (or wait for the next sync). Batches are idempotent:
importing the same day twice doesn't double count.
