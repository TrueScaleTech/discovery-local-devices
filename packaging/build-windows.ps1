<#
.SYNOPSIS
    Builds DiscoveryNow.exe, the desktop app as a folder you can zip and hand to someone
    who has no Python installed.

.PARAMETER OutDir
    Where the finished app goes. Defaults to "dist" in the repository. If your
    checkout sits deep inside nested folders, pass a short path such as C:\dn-build:
    Windows stops at 260 characters unless long paths are switched on.
#>
param(
    [string]$OutDir = "dist"
)

# Not "Stop": Windows PowerShell 5.1 would treat any text a tool writes to stderr
# (pip's upgrade notice, say) as a failure. Every step checks its exit code instead.
Set-Location (Resolve-Path "$PSScriptRoot\..")

python -m pip install --quiet -e ".[gui]" pyinstaller
if ($LASTEXITCODE -ne 0) { throw "could not install the build requirements" }

# The icon is drawn in code; write it out as the .ico Windows wants for the .exe.
$icon = Join-Path $env:TEMP "discovery-now.ico"
python -m discovery_now.gui.icons $icon
if ($LASTEXITCODE -ne 0) { throw "could not draw the icon" }

$work = Join-Path $OutDir "work"
python -m PyInstaller packaging\launcher.py `
    --noconfirm --clean --windowed --onedir `
    --name DiscoveryNow `
    --icon $icon `
    --paths src `
    --collect-data discovery_now `
    --distpath $OutDir `
    --workpath $work `
    --specpath $work
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$app = Join-Path $OutDir "DiscoveryNow"
$zip = Join-Path $OutDir "DiscoveryNow-windows.zip"
Compress-Archive -Path $app -DestinationPath $zip -Force -ErrorAction Stop
Write-Host "Built $app"
Write-Host "Zipped to $zip"
