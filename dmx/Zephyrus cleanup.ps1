# Zephyrus cleanup -- ONE light node, ONE icon. Nothing is deleted: extra copies are MOVED to
#   Downloads\_to_delete (NeyDMX cleanup <date>)   -- look through it, then delete it yourself.
# Run: right-click this file > Run with PowerShell (no admin needed).

$ErrorActionPreference = 'Continue'
$me    = $env:USERPROFILE
$real  = 'C:\NeyDMX'
$desk  = [Environment]::GetFolderPath('Desktop')
$start = [Environment]::GetFolderPath('Startup')
$stamp = Get-Date -Format 'yyyy-MM-dd'
$flag  = Join-Path $me "Downloads\_to_delete (NeyDMX cleanup $stamp)"
$moved = New-Object System.Collections.ArrayList

Write-Host ''
Write-Host 'Zephyrus cleanup -- keeping C:\NeyDMX, tidying everything else' -ForegroundColor Cyan

if (-not (Test-Path "$real\app\dmx_node.py") -or -not (Test-Path "$real\Start DMX Node.bat")) {
    Write-Host "C:\NeyDMX is missing its node -- stopping, nothing was moved. Tell Claude." -ForegroundColor Red
    Read-Host 'Press Enter to close'; exit
}
New-Item -ItemType Directory -Force $flag | Out-Null

function Flag($path) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    $leaf = Split-Path $path -Leaf
    $dest = Join-Path $flag $leaf
    $i = 1
    while (Test-Path -LiteralPath $dest) { $dest = Join-Path $flag ("{0} ({1})" -f $leaf, $i); $i++ }
    try {
        Move-Item -LiteralPath $path -Destination $dest -ErrorAction Stop
        [void]$moved.Add($path)
        Write-Host "  moved: $path"
    } catch { Write-Host "  could not move (in use?): $path" -ForegroundColor Yellow }
}

# 1) Old copies of the node, zips, stray hub files and extra DMX shortcuts in the usual places
$places = @("$me\Downloads", $desk, "$me\Desktop", "$me\Documents", "$me\OneDrive\Desktop", "$me\OneDrive\Documents") |
          Select-Object -Unique
foreach ($pl in $places) {
    if (-not (Test-Path -LiteralPath $pl)) { continue }
    Get-ChildItem -LiteralPath $pl -Force -ErrorAction SilentlyContinue | Where-Object {
        $n = $_.Name
        ($n -match '^NeyDMX') -or
        ($n -match '^dmx_node.*\.py$') -or
        ($n -match '^Start DMX Node') -or
        ($n -match '^CDM.*WHQL') -or                               # FTDI driver installer (driver stays installed)
        ($n -in @('hue_hub.py', 'hub_relay.py')) -or               # these run on the Mac, not here
        (($n -match '\.(lnk|url)$') -and ($n -match 'DMX|Light Node') -and ($n -ne 'Start Light Node.lnk'))
    } | ForEach-Object { if ($_.FullName -notlike "$real*") { Flag $_.FullName } }
}

# 2) Leftovers inside C:\NeyDMX (the node itself, its config and backups stay)
foreach ($p in @("$real\old shortcuts", "$real\Install (run once).bat", "$real\Start with Windows (optional).bat",
                 "$real\Zephyrus one-time setup.ps1", "$real\app\dmx_node.new")) { Flag $p }
Get-ChildItem -LiteralPath $real -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '\.bak' } | ForEach-Object { Flag $_.FullName }

# 3) Extra startup entries (keep exactly one)
Get-ChildItem -LiteralPath $start -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'DMX|Light Node' -and $_.Name -ne 'Start Light Node.lnk' } |
    ForEach-Object { Flag $_.FullName }

# 4) The ONE icon (desktop) + the ONE auto-start, both pointing at C:\NeyDMX
$ws = New-Object -ComObject WScript.Shell
foreach ($lnkPath in @("$desk\Start Light Node.lnk", "$start\Start Light Node.lnk")) {
    $l = $ws.CreateShortcut($lnkPath)
    $l.TargetPath = "$real\Start DMX Node.bat"
    $l.WorkingDirectory = $real
    $l.Description = 'Ney light node (drives the Enttec). Auto-updates from the Mac hub.'
    $l.IconLocation = "$env:SystemRoot\System32\shell32.dll,43"
    $l.Save()
}

# 5) Report
$report = Join-Path $flag 'what was moved.txt'
@("NeyDMX cleanup $stamp", "Kept: C:\NeyDMX (node + config + calibration backups)",
  "Icon: Desktop\Start Light Node  (also starts with Windows)", '', 'Moved here:') + $moved |
    Set-Content -LiteralPath $report -Encoding UTF8

Write-Host ''
Write-Host ("Done. Moved {0} item(s) to:" -f $moved.Count) -ForegroundColor Green
Write-Host "  $flag"
Write-Host 'From now on: the ONLY way to start the lights is the "Start Light Node" icon on the desktop.' -ForegroundColor Green
Write-Host ''
$go = Read-Host 'Start the light node now? (y/n)'
if ($go -match '^[yY]') { Start-Process -FilePath "$real\Start DMX Node.bat" -WorkingDirectory $real }
