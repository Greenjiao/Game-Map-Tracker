param(
    [switch]$SkipInstall,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Invoke-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 @args
    } else {
        & python @args
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE"
    }
}

function Copy-DirectoryFresh($Source, $Destination) {
    if (Test-Path $Destination) {
        Remove-Item -Recurse -Force $Destination
    }
    Copy-Item $Source -Destination $Destination -Recurse -Force
}

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "build"
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "dist\GMT-N"
    Remove-Item -Force -ErrorAction SilentlyContinue "dist\updater.exe"
}

if (-not $SkipInstall) {
    Invoke-Python -m pip install -r requirements.txt pyinstaller
}

Invoke-Python -m PyInstaller --noconfirm GMT-N.spec
Invoke-Python -m PyInstaller --noconfirm GMT-N-Updater.spec

$Dist = Join-Path $Root "dist\GMT-N"
if (-not (Test-Path $Dist)) {
    throw "PyInstaller did not create $Dist"
}

$UpdaterExe = Join-Path $Root "dist\updater.exe"
if (-not (Test-Path $UpdaterExe)) {
    throw "PyInstaller did not create $UpdaterExe"
}
Copy-Item $UpdaterExe -Destination (Join-Path $Dist "updater.exe") -Force

foreach ($file in @("big_map.png", "README.md")) {
    if (Test-Path $file) {
        Copy-Item $file -Destination $Dist -Force
    }
}

Invoke-Python "scripts/write_default_config.py" (Join-Path $Dist "config.json")

if (Test-Path "routes") {
    Copy-DirectoryFresh "routes" (Join-Path $Dist "routes")
}

$ToolsDist = Join-Path $Dist "tools"
New-Item -ItemType Directory -Force -Path $ToolsDist | Out-Null
foreach ($folder in @("points_all", "points_get", "points_icon")) {
    $source = Join-Path "tools" $folder
    if (Test-Path $source) {
        Copy-DirectoryFresh $source (Join-Path $ToolsDist $folder)
    }
}

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $Dist\GMT-N.exe"
Write-Host "  $Dist\updater.exe"
Write-Host ""
Write-Host "Ship the whole dist\GMT-N folder, not the exe by itself."
