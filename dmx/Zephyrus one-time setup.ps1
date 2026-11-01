# Zephyrus one-time setup (Nov 1): ONE start icon + node starts at login + Wake-on-LAN on the wired adapter.
# Run in PowerShell as Administrator. Old DMX shortcuts are MOVED to C:\NeyDMX\old shortcuts (not deleted).
$bat = 'C:\NeyDMX\Start DMX Node.bat'
$desk = [Environment]::GetFolderPath('Desktop')
$old = 'C:\NeyDMX\old shortcuts'; New-Item -ItemType Directory -Force $old | Out-Null
Get-ChildItem $desk -Filter *.lnk | Where-Object { $_.Name -match 'DMX' } | Move-Item -Destination $old -Force
$ws = New-Object -ComObject WScript.Shell
foreach ($p in @("$desk\Start Light Node.lnk", "$([Environment]::GetFolderPath('Startup'))\Start Light Node.lnk")) {
  $s = $ws.CreateShortcut($p); $s.TargetPath = $bat; $s.WorkingDirectory = 'C:\NeyDMX'; $s.Save() }
$a = Get-NetAdapter | Where-Object MacAddress -eq '00-E0-4C-68-10-5B'
Set-NetAdapterPowerManagement -Name $a.Name -WakeOnMagicPacket Enabled
Set-NetAdapterAdvancedProperty -Name $a.Name -DisplayName 'Wake on Magic Packet' -DisplayValue 'Enabled' -ErrorAction SilentlyContinue
powercfg /deviceenablewake "$($a.InterfaceDescription)"
"Done: one icon (Start Light Node), auto-start at login, Wake-on-LAN on $($a.Name)"
