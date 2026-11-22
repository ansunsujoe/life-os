<#
.SYNOPSIS
  Install the LifeOS collector on a Windows computer (runs as your user, no admin).

.EXAMPLE
  # Network mode (home network):
  powershell -ExecutionPolicy Bypass -File .\install-collector-windows.ps1 -Hub http://MacBook-Pro-3.local:8765 -Token lfs_xxx

  # File mode (no network to the hub, e.g. VPN always on):
  powershell -ExecutionPolicy Bypass -File .\install-collector-windows.ps1 -ExportDir "$env:USERPROFILE\LifeOS-outbox" -ConfigFile .\lifeos-collector-config-work-laptop.json

  # Remove the background task (and optionally settings):
  powershell -ExecutionPolicy Bypass -File .\install-collector-windows.ps1 -Uninstall

.NOTES
  For a work device the hub marks it "content-free": activity is classified on this
  computer and ONLY categories and times are sent — never window titles, websites,
  app or project names. Run `uv run lifeos-collect show` to see exactly what is sent.
#>
param(
  [string]$Hub,
  [string]$Token,
  [string]$ExportDir,
  [string]$ConfigFile,
  [int]$EverySeconds = 300,
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName = "LifeOS Collector"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
# Works from the downloaded zip (backend\ next to this script) or a git clone (scripts\..\backend).
$Backend = Join-Path $Root "backend"
if (-not (Test-Path (Join-Path $Backend "pyproject.toml"))) { $Backend = Join-Path (Split-Path -Parent $Root) "backend" }
$DataDir = Join-Path $env:LOCALAPPDATA "LifeOS"
$Log = Join-Path $DataDir "collector.log"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

if ($Uninstall) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Background task removed. Settings remain in $DataDir (delete that folder to remove them)."
  exit 0
}

if (-not (Test-Path (Join-Path $Backend "pyproject.toml"))) {
  throw "Can't find backend\pyproject.toml. Run this script from the extracted lifeos-collector folder or a clone of the repo."
}
if (-not $Hub -and -not $ExportDir) { throw "Pass -Hub <url> -Token <token>, or -ExportDir <folder> for file mode." }

Step "Checking ActivityWatch on this computer"
try {
  $info = Invoke-RestMethod -Uri "http://localhost:5600/api/0/info" -TimeoutSec 3
  Write-Host "ActivityWatch $($info.version) is running."
} catch {
  Write-Host "ActivityWatch isn't running. Install it from https://activitywatch.net/downloads/ (Windows installer)," -ForegroundColor Yellow
  Write-Host "start it once, then re-run this script." -ForegroundColor Yellow
  exit 1
}

Step "Checking uv (Python runner, installs per-user)"
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
  $answer = Read-Host "uv is not installed. Install it now for your user only from astral.sh? (y/n)"
  if ($answer -ne "y") { throw "uv is required. See https://docs.astral.sh/uv/getting-started/installation/" }
  powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
  $uv = Get-Command uv -ErrorAction Stop
}
$UvPath = $uv.Source

Step "Installing collector dependencies (first run downloads Python if needed)"
Push-Location $Backend
& $UvPath sync --no-dev --quiet
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "uv sync failed (a corporate proxy may block downloads)." }

Step "Saving settings"
$setupArgs = @("run", "--no-dev", "lifeos-collect", "setup")
if ($Hub) { $setupArgs += @("--hub", $Hub) }
if ($Token) { $setupArgs += @("--token", $Token) }
if ($ExportDir) { $setupArgs += @("--export-dir", $ExportDir) }
if ($ConfigFile) { $setupArgs += @("--config-file", (Resolve-Path $ConfigFile).Path) }
& $UvPath @setupArgs

Step "Testing every step"
& $UvPath run --no-dev lifeos-collect test
Pop-Location

Step "Registering background task '$TaskName' (starts at logon, every $EverySeconds s)"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$cmd = "Set-Location '$Backend'; & '$UvPath' run --no-dev lifeos-collect run --every $EverySeconds *>> '$Log'"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$cmd`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 3650) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Sends LifeOS activity summaries to your hub" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "`nDone. The collector now runs in the background." -ForegroundColor Green
Write-Host "  See what is sent:   cd `"$Backend`"; uv run lifeos-collect show"
Write-Host "  Log:                $Log"
Write-Host "  Remove:             powershell -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`" -Uninstall"
