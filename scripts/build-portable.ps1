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
# Tools on PATH (for example Poppler) can ship same-named OpenSSL DLLs with
# different provider/config requirements. Bundle the pair belonging to _ssl.pyd.
$javSslDirectory = & $javPython -c 'from pathlib import Path; import _ssl; print(Path(_ssl.__file__).parent)'
if ($LASTEXITCODE -ne 0) { throw 'Could not locate the Python SSL runtime' }
foreach ($javSslName in @('libssl-3-x64.dll', 'libcrypto-3-x64.dll')) {
    $javSslSource = Join-Path $javSslDirectory $javSslName
    if (-not (Test-Path -LiteralPath $javSslSource -PathType Leaf)) {
        throw "Required Python SSL runtime is missing: $javSslName"
    }
    Copy-Item -LiteralPath $javSslSource -Destination 'dist/jav-data/_internal' -Force
}
# The managed development runtime's ssl.py loads this adjacent public CA-policy
# resource. Preserve that policy in the frozen layout; ordinary Python has none.
$javSslPolicy = & $javPython -c 'from pathlib import Path; import ssl; print(Path(ssl.__file__).with_name("codex-rejected-cas.pem"))'
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the Python SSL resources' }
if (Test-Path -LiteralPath $javSslPolicy -PathType Leaf) {
    Copy-Item -LiteralPath $javSslPolicy -Destination 'dist/jav-data/_internal' -Force
}
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
