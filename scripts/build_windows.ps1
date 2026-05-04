param(
    [ValidateSet("update", "test")]
    [string]$Channel = "update",
    [switch]$SkipInstall,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$AppInfoPath = Join-Path $Root "ui_island\app\app_info.py"
$OriginalAppInfo = Get-Content -Raw -Encoding UTF8 $AppInfoPath

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Set-AppInfoChannelForBuild {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("update", "test")]
        [string]$BuildChannel
    )

    $pattern = '(?m)^APP_UPDATE_CHANNEL = "[^"]+"$'
    if ($OriginalAppInfo -notmatch $pattern) {
        throw "ui_island/app/app_info.py is missing APP_UPDATE_CHANNEL; cannot inject release channel."
    }
    $replacement = 'APP_UPDATE_CHANNEL = "' + $BuildChannel + '"'
    $content = [regex]::Replace($OriginalAppInfo, $pattern, $replacement, 1)
    Write-Utf8NoBom -Path $AppInfoPath -Content $content
}

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

try {
    Set-AppInfoChannelForBuild -BuildChannel $Channel

    if ($Clean) {
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "build"
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "dist\GMT-N"
        Remove-Item -Force -ErrorAction SilentlyContinue "dist\updater.exe"
        Remove-Item -Force -ErrorAction SilentlyContinue "dist\json_txt_converter.exe"
    }

    if (-not $SkipInstall) {
        Invoke-Python -m pip install -r requirements.txt pyinstaller
    }

    Invoke-Python -m PyInstaller --noconfirm packaging/GMT-N.spec
    Invoke-Python -m PyInstaller --noconfirm packaging/GMT-N-Updater.spec
    Invoke-Python -m PyInstaller --noconfirm packaging/JSON-TXT-Converter.spec

    $Dist = Join-Path $Root "dist\GMT-N"
    if (-not (Test-Path $Dist)) {
        throw "PyInstaller did not create $Dist"
    }

    $UpdaterExe = Join-Path $Root "dist\updater.exe"
    if (-not (Test-Path $UpdaterExe)) {
        throw "PyInstaller did not create $UpdaterExe"
    }
    Copy-Item $UpdaterExe -Destination (Join-Path $Dist "updater.exe") -Force

    $ConverterExe = Join-Path $Root "dist\json_txt_converter.exe"
    if (-not (Test-Path $ConverterExe)) {
        throw "PyInstaller did not create $ConverterExe"
    }

    foreach ($file in @("README.md")) {
        if (Test-Path $file) {
            Copy-Item $file -Destination $Dist -Force
        }
    }

    $MapsDist = Join-Path $Dist "maps"
    New-Item -ItemType Directory -Force -Path $MapsDist | Out-Null
    $MapsReadme = Join-Path $Root "maps\README.md"
    if (Test-Path $MapsReadme) {
        Copy-Item $MapsReadme -Destination $MapsDist -Force
    }
    $BundledMapSource = Join-Path $Root "maps\卡洛西亚大陆"
    $BundledMapDist = Join-Path $MapsDist "卡洛西亚大陆"
    foreach ($mapFile in @("big_map_new.png")) {
        $source = Join-Path $BundledMapSource $mapFile
        if (Test-Path $source) {
            New-Item -ItemType Directory -Force -Path $BundledMapDist | Out-Null
            Copy-Item $source -Destination $BundledMapDist -Force
        }
    }

    Invoke-Python "scripts/write_default_config.py" (Join-Path $Dist "config.json")

    if (Test-Path "routes") {
        Copy-DirectoryFresh "routes" (Join-Path $Dist "routes")
    }

    if (Test-Path "annotations") {
        Copy-DirectoryFresh "annotations" (Join-Path $Dist "annotations")
    }

    $ToolsDist = Join-Path $Dist "tools"
    New-Item -ItemType Directory -Force -Path $ToolsDist | Out-Null
    foreach ($folder in @("points_get", "points_icon")) {
        $source = Join-Path "tools" $folder
        if (Test-Path $source) {
            Copy-DirectoryFresh $source (Join-Path $ToolsDist $folder)
        }
    }
    Copy-Item $ConverterExe -Destination (Join-Path $ToolsDist "json_txt_converter.exe") -Force

    Write-Host ""
    Write-Host "Build complete:"
    Write-Host "  Channel: $Channel"
    Write-Host "  $Dist\GMT-N.exe"
    Write-Host "  $Dist\updater.exe"
    Write-Host "  $Dist\tools\json_txt_converter.exe"
    Write-Host ""
    Write-Host "Ship the whole dist\GMT-N folder, not the exe by itself."
} finally {
    Write-Utf8NoBom -Path $AppInfoPath -Content $OriginalAppInfo
}
