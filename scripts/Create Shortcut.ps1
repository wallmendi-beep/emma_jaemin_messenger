param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$Launcher = Join-Path $ProjectRoot "Start Messenger.bat"
if (-not (Test-Path $Launcher)) {
    throw "Launcher not found: $Launcher"
}

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutName = ([char[]](0xC5E0,0xB9C8,0x20,0xC7AC,0xBBFC,0xC774,0x20,0xD611,0xC5C5,0x20,0xBA54,0xC2E0,0xC800) -join '') + ".lnk"
$ShortcutPath = Join-Path $Desktop $ShortcutName
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Launcher
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = "Local Emma-Jaemin collaboration messenger"
$Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
$Shortcut.Save()

if (-not (Test-Path $ShortcutPath)) {
    throw "Shortcut creation failed: $ShortcutPath"
}
Write-Output $ShortcutPath
