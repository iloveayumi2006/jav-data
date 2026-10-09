param(
    [string]$OutputDirectory = 'portable\jav-data',
    [switch]$Fresh
)
$ErrorActionPreference = 'Stop'
$javRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $javRoot
$javPortable = [System.IO.Path]::GetFullPath((Join-Path $javRoot $OutputDirectory))
if (-not $javPortable.StartsWith((Join-Path $javRoot 'portable') + '\')) {
    throw 'Build output must be inside the project portable folder'
}
if ($Fresh -and (Test-Path -LiteralPath $javPortable)) {
    throw 'A fresh build requires a new output directory; existing data will not be deleted'
}
$javPython = Join-Path $javRoot '.venv\Scripts\python.exe'
& $javPython -m PyInstaller --noconfirm --clean --windowed --onedir --name jav-data `
    --icon 'src/jav_data/assets/app.ico' --add-data 'src/jav_data/assets;jav_data/assets' `
    --paths src --add-data 'alembic.ini;.' --add-data 'migrations;migrations' `
    --collect-submodules jav_data --collect-submodules sqlalchemy.dialects.sqlite `
    --exclude-module playwright --exclude-module tkinter --exclude-module PySide6.QtQml `
    scripts/desktop_entry.py
if ($LASTEXITCODE -ne 0) { throw 'Portable build failed' }
# Qt on supported Windows uses the OS ICU API. A different ICU from PATH may
# expose version-suffixed symbols and break QtCore at startup when bundled.
foreach ($javIcuName in @('icuuc.dll', 'icudt78.dll')) {
    $javIcu = Join-Path $javRoot "dist\jav-data\_internal\$javIcuName"
    if (Test-Path -LiteralPath $javIcu) { Remove-Item -LiteralPath $javIcu -Force }
}
Copy-Item -LiteralPath 'config.example.toml' -Destination 'dist/jav-data/config.toml' -Force
Copy-Item -LiteralPath 'docs/portable-desktop.md' -Destination 'dist/jav-data/README.md' -Force
New-Item -ItemType Directory -Path $javPortable -Force | Out-Null
# Replace only application binaries. Never remove personal data or configuration.
Copy-Item -LiteralPath 'dist/jav-data/jav-data.exe' -Destination $javPortable -Force
Copy-Item -LiteralPath 'dist/jav-data/_internal' -Destination $javPortable -Recurse -Force
# Remove stale conflicting DLLs from a previous build too.
foreach ($javIcuName in @('icuuc.dll', 'icudt78.dll')) {
    $javIcu = Join-Path $javPortable "_internal\$javIcuName"
    if (Test-Path -LiteralPath $javIcu) { Remove-Item -LiteralPath $javIcu -Force }
}
Copy-Item -LiteralPath 'dist/jav-data/README.md' -Destination $javPortable -Force
if (-not (Test-Path -LiteralPath "$javPortable\config.toml")) {
    Copy-Item -LiteralPath 'config.example.toml' -Destination "$javPortable\config.toml"
}
Write-Output "Portable application: $javPortable\jav-data.exe"
