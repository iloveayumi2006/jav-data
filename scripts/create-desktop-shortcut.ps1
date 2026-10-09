$ErrorActionPreference = 'Stop'
$javRoot = Split-Path -Parent $PSScriptRoot
$javExe = (Resolve-Path -LiteralPath (Join-Path $javRoot 'portable\jav-data\jav-data.exe')).Path
$javDesktop = [Environment]::GetFolderPath('DesktopDirectory')
$javShortcutPath = Join-Path $javDesktop 'jav-data.lnk'
$javShell = New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $javShortcutPath) {
    $javExisting = $javShell.CreateShortcut($javShortcutPath)
    if ($javExisting.TargetPath -ne $javExe) {
        $javShortcutPath = Join-Path $javDesktop 'jav-data Data+.lnk'
    }
}
$javShortcut = $javShell.CreateShortcut($javShortcutPath)
$javShortcut.TargetPath = $javExe
$javShortcut.WorkingDirectory = Split-Path -Parent $javExe
$javShortcut.IconLocation = "$javExe,0"
$javShortcut.Description = 'jav-data portable desktop scraper'
$javShortcut.Save()
Write-Output "Desktop shortcut: $javShortcutPath"
