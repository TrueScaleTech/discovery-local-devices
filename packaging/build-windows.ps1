<#
.SYNOPSIS
    Builds Discovery Now for Windows: the app as a folder, a zip of it, and (when
    Inno Setup is about) an installer.

.PARAMETER OutDir
    Where the finished app goes. Defaults to "dist" in the repository. If your
    checkout sits deep inside nested folders, pass a short path such as C:\dn-build:
    Windows stops at 260 characters unless long paths are switched on.

.PARAMETER NoInstaller
    Build the folder and the zip, and skip the installer even if Inno Setup is
    installed.
#>
param(
    [string]$OutDir = "dist",
    [switch]$NoInstaller
)

# Not "Stop": Windows PowerShell 5.1 would treat any text a tool writes to stderr
# (pip's upgrade notice, say) as a failure. Every step checks its exit code instead.
$repo = Resolve-Path "$PSScriptRoot\.."
Set-Location $repo

python -m pip install --quiet -e ".[gui]" pyinstaller
if ($LASTEXITCODE -ne 0) { throw "could not install the build requirements" }

$version = (python -c "import tomllib,pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])").Trim()
if ($LASTEXITCODE -ne 0 -or -not $version) { throw "could not read the version from pyproject.toml" }
Write-Host "Building Discovery Now $version"

if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }
$OutDir = (Resolve-Path $OutDir).Path

# The icon is drawn in code; write it out as the .ico Windows wants for the .exe.
$icon = Join-Path $OutDir "discovery-now.ico"
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
$zip = Join-Path $OutDir "DiscoveryNow-$version-windows.zip"
Compress-Archive -Path $app -DestinationPath $zip -Force -ErrorAction Stop
Write-Host "Built  $app"
Write-Host "Zipped $zip"

if ($NoInstaller) { return }

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
    foreach ($guess in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $guess) { $iscc = Get-Item $guess; break }
    }
}
if (-not $iscc) {
    Write-Host "Inno Setup not found, so no installer was built."
    Write-Host "Install it from https://jrsoftware.org/isdl.php, or pass -NoInstaller to skip this notice."
    return
}

& $iscc.Source /Qp `
    "/DAppVersion=$version" `
    "/DSourceDir=$app" `
    "/DOutputDir=$OutDir" `
    "/DIconFile=$icon" `
    "$repo\packaging\installer.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "Installer $OutDir\DiscoveryNow-$version-setup.exe"
