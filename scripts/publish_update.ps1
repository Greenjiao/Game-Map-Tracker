param(
    [string]$Version = "",
    [string]$Notes = "",
    [ValidateSet("", "update", "test")]
    [string]$Channel = "",
    [switch]$PromptUpdate,
    [switch]$ForceUpdatePrompt,
    [ValidateSet("", "normal", "notice", "disabled")]
    [string]$AppStatus = "",
    [string]$AppStatusMessage = "",
    [switch]$AppNoticeForcePrompt,
    [string]$MinSupportedVersion = "",
    [string]$MinSupportedVersionMessage = "",
    [string]$BaseUrl = "",
    [string]$CommitMessage = "",
    [switch]$SkipBuild,
    [switch]$SkipPush
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$ErrorMessage
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage，退出码：$LASTEXITCODE"
    }
}

function Invoke-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 @args
    } else {
        & python @args
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Python 命令执行失败，退出码：$LASTEXITCODE"
    }
}

function Read-RequiredText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prompt
    )

    while ($true) {
        $value = (Read-Host $Prompt).Trim()
        if ($value) {
            return $value
        }
        Write-Host "此项不能为空，请重新输入。"
    }
}

function Read-YesNo {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prompt,
        [Parameter(Mandatory = $true)]
        [bool]$DefaultYes
    )

    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $value = (Read-Host "$Prompt $suffix").Trim().ToLowerInvariant()
        if (-not $value) {
            return $DefaultYes
        }
        if ($value -in @("y", "yes")) {
            return $true
        }
        if ($value -in @("n", "no")) {
            return $false
        }
        Write-Host "请输入 y 或 n。"
    }
}

function Read-ReleaseChannel {
    while ($true) {
        $value = (Read-Host "发布到正式通道还是测试通道？[update/test，默认 update]").Trim().ToLowerInvariant()
        if (-not $value) {
            return "update"
        }
        if ($value -in @("update", "test")) {
            return $value
        }
        Write-Host "请输入 update 或 test。"
    }
}

function Read-AppStatus {
    while ($true) {
        $value = (Read-Host "启动公告状态？[normal/notice/disabled，默认 normal]").Trim().ToLowerInvariant()
        if (-not $value) {
            return "normal"
        }
        if ($value -in @("normal", "notice", "disabled")) {
            return $value
        }
        Write-Host "请输入 normal、notice 或 disabled。"
    }
}

function Show-GitPreview {
    param(
        [string]$Pathspec = "docs/update",
        [int]$Limit = 40
    )

    $changes = @(& git status --short -- $Pathspec)
    $count = $changes.Count
    Write-Host ""
    Write-Host "当前暂存变更摘要："
    Write-Host "  路径：$Pathspec"
    Write-Host "  文件数：$count"
    if ($count -gt 0) {
        Write-Host "  前 $([Math]::Min($Limit, $count)) 个文件："
        $changes | Select-Object -First $Limit | ForEach-Object {
            Write-Host "    $_"
        }
        if ($count -gt $Limit) {
            Write-Host "    ... 还有 $($count - $Limit) 个文件未显示"
            Write-Host "    如需完整列表，请运行：git status --short -- $Pathspec"
        }
    }
    Write-Host "  如需统计信息，请手动运行：git diff --cached --stat -- $Pathspec"
}

if (-not $Channel.Trim()) {
    $Channel = Read-ReleaseChannel
} else {
    $Channel = $Channel.Trim().ToLowerInvariant()
}

$GiteeRawDocsRoot = "https://gitee.com/qingjiao123/Game-Map-Tracker/raw/main/docs"
$GitHubPagesRoot = "https://greenjiao.github.io/Game-Map-Tracker"
$ReleasePathspec = "docs/$Channel"
$DefaultResourceBaseUrl = "$GiteeRawDocsRoot/$Channel/"
if (-not $BaseUrl.Trim()) {
    $BaseUrl = $DefaultResourceBaseUrl
} else {
    $BaseUrl = $BaseUrl.Trim()
    if (-not $BaseUrl.EndsWith("/")) {
        $BaseUrl = "$BaseUrl/"
    }
}

if (-not $Version.Trim()) {
    $Version = Read-RequiredText "请输入发布版本号，例如 0.1.1"
} else {
    $Version = $Version.Trim()
}

if (-not $Notes.Trim()) {
    $Notes = Read-RequiredText "请输入更新说明"
} else {
    $Notes = $Notes.Trim()
}

$UsePromptUpdate = $false
if ($PSBoundParameters.ContainsKey("PromptUpdate")) {
    $UsePromptUpdate = [bool]$PromptUpdate
} else {
    $UsePromptUpdate = Read-YesNo "是否启动后弹窗提示更新？" $false
}

$UseForceUpdatePrompt = $false
if ($PSBoundParameters.ContainsKey("ForceUpdatePrompt")) {
    $UseForceUpdatePrompt = [bool]$ForceUpdatePrompt
} else {
    $UseForceUpdatePrompt = Read-YesNo "是否强制启动弹窗提示？" $false
}
if ($UseForceUpdatePrompt) {
    $UsePromptUpdate = $true
}

if (-not $AppStatus.Trim()) {
    $AppStatus = Read-AppStatus
} else {
    $AppStatus = $AppStatus.Trim().ToLowerInvariant()
}

if (-not $AppStatusMessage.Trim()) {
    if ($AppStatus -in @("notice", "disabled")) {
        $AppStatusMessage = Read-RequiredText "请输入公告/禁用说明"
    } else {
        $AppStatusMessage = ""
    }
} else {
    $AppStatusMessage = $AppStatusMessage.Trim()
}

$UseAppNoticeForcePrompt = $false
if ($PSBoundParameters.ContainsKey("AppNoticeForcePrompt")) {
    $UseAppNoticeForcePrompt = [bool]$AppNoticeForcePrompt
} elseif ($AppStatus -eq "notice") {
    $UseAppNoticeForcePrompt = Read-YesNo "是否每次启动都弹出公告？" $false
}
if ($AppStatus -ne "notice") {
    $UseAppNoticeForcePrompt = $false
}

if (-not $MinSupportedVersion.Trim()) {
    if (Read-YesNo "是否设置最低可用版本（低于此版本强制更新）？" $false) {
        $MinSupportedVersion = Read-RequiredText "请输入最低可用版本号，例如 0.1.2"
    } else {
        $MinSupportedVersion = ""
    }
} else {
    $MinSupportedVersion = $MinSupportedVersion.Trim()
}

if ($MinSupportedVersion -and -not $MinSupportedVersionMessage.Trim()) {
    $inputMinVersionMessage = (Read-Host "请输入低版本强制更新说明，直接回车使用默认文案").Trim()
    $MinSupportedVersionMessage = $inputMinVersionMessage
} else {
    $MinSupportedVersionMessage = $MinSupportedVersionMessage.Trim()
}

$ShouldBuild = $true
if ($PSBoundParameters.ContainsKey("SkipBuild")) {
    $ShouldBuild = -not [bool]$SkipBuild
} else {
    $ShouldBuild = Read-YesNo "是否重新打包？" $true
}

$ShouldCommitAndPush = $true
if ($PSBoundParameters.ContainsKey("SkipPush")) {
    $ShouldCommitAndPush = -not [bool]$SkipPush
} else {
    $ShouldCommitAndPush = Read-YesNo "是否提交并推送？" $true
}

if (-not $CommitMessage.Trim()) {
    $defaultCommitMessage = "Publish GMT-N $Version update"
    if ($ShouldCommitAndPush) {
        $inputCommitMessage = (Read-Host "请输入提交信息，直接回车使用默认值：$defaultCommitMessage").Trim()
        $CommitMessage = if ($inputCommitMessage) { $inputCommitMessage } else { $defaultCommitMessage }
    } else {
        $CommitMessage = $defaultCommitMessage
    }
} else {
    $CommitMessage = $CommitMessage.Trim()
}

Write-Host ""
Write-Host "发布参数："
Write-Host "  版本号：$Version"
Write-Host "  更新说明：$Notes"
Write-Host "  启动弹窗：$UsePromptUpdate"
Write-Host "  强制弹窗：$UseForceUpdatePrompt"
Write-Host "  应用状态：$AppStatus"
if ($AppStatusMessage) {
    Write-Host "  状态说明：$AppStatusMessage"
}
Write-Host "  公告每次弹出：$UseAppNoticeForcePrompt"
if ($MinSupportedVersion) {
    Write-Host "  最低可用版本：$MinSupportedVersion"
    if ($MinSupportedVersionMessage) {
        Write-Host "  低版本更新说明：$MinSupportedVersionMessage"
    }
}
Write-Host "  重新打包：$ShouldBuild"
Write-Host "  提交推送：$ShouldCommitAndPush"
Write-Host "  发布通道：$Channel"
Write-Host "  发布目录：$ReleasePathspec"
Write-Host "  资源 URL 前缀：$BaseUrl"
Write-Host ""

if ($ShouldBuild) {
    Write-Host "开始打包..."
    Invoke-CheckedCommand `
        -Command { & powershell -ExecutionPolicy Bypass -File "scripts/build_windows.ps1" -Clean -Channel $Channel } `
        -ErrorMessage "打包失败"
} elseif (-not (Test-Path "dist\GMT-N")) {
    throw "已选择跳过打包，但 dist\GMT-N 不存在。"
}

$UpdateDir = Join-Path $Root $ReleasePathspec
$DistDir = Join-Path $Root "dist\GMT-N"
$ManifestPath = Join-Path $UpdateDir "app-manifest.json"

if (-not (Test-Path $DistDir)) {
    throw "发布目录不存在：$DistDir"
}

Write-Host "重建 $ReleasePathspec..."
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $UpdateDir
New-Item -ItemType Directory -Force $UpdateDir | Out-Null
Copy-Item (Join-Path $DistDir "*") $UpdateDir -Recurse -Force
$PublishedConverter = Join-Path $UpdateDir "tools\json_txt_converter.exe"
if (Test-Path $PublishedConverter) {
    Remove-Item -Force $PublishedConverter
}
$PublishedPointsIconIndex = Join-Path $UpdateDir "tools\points_icon\icons.json"
if (Test-Path $PublishedPointsIconIndex) {
    $InternalPointsIconRoot = Join-Path $UpdateDir "_internal\tools\points_icon"
    New-Item -ItemType Directory -Force -Path $InternalPointsIconRoot | Out-Null
    Copy-Item $PublishedPointsIconIndex -Destination (Join-Path $InternalPointsIconRoot "icons.json") -Force
}

$PublishedMapsRoot = Join-Path $UpdateDir "maps"
$PublishedMapImages = @()
if (Test-Path $PublishedMapsRoot) {
    $PublishedMapImages = @(Get-ChildItem -Recurse -File -Path $PublishedMapsRoot -Include *.png, *.jpg, *.jpeg, *.webp -ErrorAction SilentlyContinue)
}
if ($PublishedMapImages.Count -eq 0) {
    throw "$ReleasePathspec\maps 不含任何地图图片，发布会让客户端拿到空 maps 目录。请检查 dist\GMT-N\maps（很可能未重新打包，或 build_windows.ps1 拷贝步骤失败）。"
}

Write-Host "生成更新清单..."
$manifestArgs = @(
    "scripts/generate_update_manifest.py",
    "dist/GMT-N",
    "--version", $Version,
    "--base-url", $BaseUrl,
    "--notes", $Notes,
    "--app-status", $AppStatus,
    "-o", $ManifestPath
)
if ($AppStatusMessage) {
    $manifestArgs += @("--app-status-message", $AppStatusMessage)
}
if ($UseAppNoticeForcePrompt) {
    $manifestArgs += "--app-notice-force-prompt"
}
if ($MinSupportedVersion) {
    $manifestArgs += @("--min-supported-version", $MinSupportedVersion)
}
if ($MinSupportedVersion -and $MinSupportedVersionMessage) {
    $manifestArgs += @("--min-supported-version-message", $MinSupportedVersionMessage)
}
if ($UsePromptUpdate) {
    $manifestArgs += "--prompt-update"
}
if ($UseForceUpdatePrompt) {
    $manifestArgs += "--force-update-prompt"
}

$AnnotationsRoot = Join-Path $UpdateDir "annotations"
if (Test-Path $AnnotationsRoot) {
    $AnnotationFiles = @(Get-ChildItem -Recurse -File -Path $AnnotationsRoot -Filter *.json -ErrorAction SilentlyContinue)
    foreach ($file in $AnnotationFiles) {
        $rel = ($file.FullName.Substring($UpdateDir.Length).TrimStart('\', '/')) -replace '\\', '/'
        $manifestArgs += @("--include", $rel)
        Write-Host "  发布 annotations: $rel"
    }
}

$PointsIconRoot = Join-Path $UpdateDir "tools/points_icon"
if (Test-Path $PointsIconRoot) {
    $PointsIconFiles = @(
        Get-ChildItem -File -Path $PointsIconRoot -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension.ToLowerInvariant() -in @(".json", ".png") }
    )
    foreach ($file in $PointsIconFiles) {
        $rel = ($file.FullName.Substring($UpdateDir.Length).TrimStart('\', '/')) -replace '\\', '/'
        $manifestArgs += @("--include", $rel)
        Write-Host "  发布 points_icon: $rel"
    }
}

Invoke-Python @manifestArgs

Write-Host "暂存 $ReleasePathspec..."
Invoke-CheckedCommand -Command { & git add $ReleasePathspec } -ErrorMessage "git add 失败"

Show-GitPreview -Pathspec $ReleasePathspec -Limit 40

& git diff --cached --quiet -- $ReleasePathspec
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "$ReleasePathspec 没有新的暂存变更，本次不提交。"
    exit 0
}

if (-not $ShouldCommitAndPush) {
    Write-Host ""
    Write-Host "已完成生成和暂存，按你的选择不提交推送。"
    exit 0
}

$confirmed = Read-YesNo "确认提交并推送以上暂存变更？" $true
if (-not $confirmed) {
    Write-Host "已取消提交推送，变更仍保留在暂存区。"
    exit 0
}

Write-Host "提交更新包..."
Invoke-CheckedCommand -Command { & git commit -m $CommitMessage -- $ReleasePathspec } -ErrorMessage "git commit 失败"

Write-Host "推送到 GitHub..."
Invoke-CheckedCommand -Command { & git push } -ErrorMessage "git push 失败"

Write-Host ""
Write-Host "更新发布完成。"
Write-Host "GitHub Pages Manifest 地址：$GitHubPagesRoot/$Channel/app-manifest.json"
Write-Host "Gitee Manifest 地址：$GiteeRawDocsRoot/$Channel/app-manifest.json"
Write-Host "旧客户端资源 URL 前缀：$BaseUrl"
