# Source-ZIP fallback: fetch the same public portable release, without Python.
[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'FishStoryPlayer'),
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = '0.4.1',
    [switch]$Launch
)
$ErrorActionPreference = 'Stop'
$taskDestination = Join-Path $InstallRoot $Version
$taskDesktop = Join-Path $taskDestination 'FishStoryPlayer.exe'
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
if (-not (Test-Path -LiteralPath $taskDesktop -PathType Leaf)) {
    if (Test-Path -LiteralPath $taskDestination) {
        Write-Host '目标版本目录已经存在但文件不完整。请保留该目录并通过 -InstallRoot 选择另一个安装位置。'
        exit 1
    }
    $taskStage = Join-Path ([IO.Path]::GetTempPath()) ('fish-story-install-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $taskStage | Out-Null
    $taskArchive = Join-Path $taskStage 'FishStoryPlayer-Windows-x64.zip'
    $taskChecksum = $taskArchive + '.sha256'
    $taskBase = 'https://github.com/nefelibata5136-code/fish-story-player/releases/download/v' + $Version + '/'
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Write-Host ('正在从项目 Release 下载 Windows 便携版 ' + $Version + '，无需安装 Python。')
    Invoke-WebRequest -UseBasicParsing -Uri ($taskBase + 'FishStoryPlayer-Windows-x64.zip.sha256') -OutFile $taskChecksum -TimeoutSec 120
    $taskText = [IO.File]::ReadAllText($taskChecksum)
    if ($taskText -notmatch '\A([a-fA-F0-9]{64})  FishStoryPlayer-Windows-x64\.zip\s*\z') {
        throw 'The release checksum file has an unexpected format.'
    }
    $taskExpected = $Matches[1]
    Invoke-WebRequest -UseBasicParsing -Uri ($taskBase + 'FishStoryPlayer-Windows-x64.zip') -OutFile $taskArchive -TimeoutSec 120
    if ((Get-Item -LiteralPath $taskArchive).Length -gt 100000000) { throw 'The release archive is unexpectedly large.' }
    if ((Get-FileHash -LiteralPath $taskArchive -Algorithm SHA256).Hash -ne $taskExpected) { throw 'Release checksum mismatch; nothing will be launched.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $taskZip = [IO.Compression.ZipFile]::OpenRead($taskArchive)
    try {
        $taskExpandedBytes = [long]0
        foreach ($taskEntry in $taskZip.Entries) {
            $taskEntryName = $taskEntry.FullName.Replace('\', '/')
            if (-not $taskEntryName.StartsWith('FishStoryPlayer-Windows-x64/', [StringComparison]::Ordinal) -or
                $taskEntryName.Split('/') -contains '..' -or
                $taskEntryName.Contains(':')) { throw 'UNSAFE_ARCHIVE_PATH' }
            $taskExpandedBytes += $taskEntry.Length
            if ($taskExpandedBytes -gt 500000000) { throw 'ARCHIVE_EXPANSION_LIMIT' }
            if (($taskEntry.ExternalAttributes -shr 16 -band 0xF000) -eq 0xA000) { throw 'ARCHIVE_SYMLINK' }
        }
    } finally { $taskZip.Dispose() }
    $taskExtract = Join-Path $taskStage 'extracted'
    Expand-Archive -LiteralPath $taskArchive -DestinationPath $taskExtract
    $taskUnpacked = Join-Path $taskExtract 'FishStoryPlayer-Windows-x64'
    if (-not (Test-Path -LiteralPath (Join-Path $taskUnpacked 'fish-story.exe') -PathType Leaf)) { throw 'The release archive does not contain the expected CLI.' }
    if (-not (Test-Path -LiteralPath (Join-Path $taskUnpacked 'FishStoryPlayer.exe') -PathType Leaf)) { throw 'The release archive does not contain the expected desktop program.' }
    # Both move targets are explicitly below the user-selected installation root.
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    $taskRootFull = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\') + '\'
    $taskDestinationFull = [IO.Path]::GetFullPath($taskDestination)
    if (-not $taskDestinationFull.StartsWith($taskRootFull, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid installation target.' }
    Move-Item -LiteralPath $taskUnpacked -Destination $taskDestinationFull
    Remove-Item -LiteralPath $taskArchive, $taskChecksum
    Remove-Item -LiteralPath $taskExtract
    Remove-Item -LiteralPath $taskStage
}
if (-not (Test-Path -LiteralPath (Join-Path $taskDestination 'fish-story.exe') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $taskDestination '_internal') -PathType Container)) {
    throw 'INCOMPLETE_INSTALLED_BUNDLE'
}
Write-Output (Join-Path $taskDestination 'fish-story.exe')
if ($Launch) {
    # This is the interactive game service window, not a background helper.
    & $taskDesktop
}
} catch {
    Write-Host ('便携版 ' + $Version + ' 尚未下载完成，没有启动未校验的程序。')
    Write-Host '请检查 GitHub 网络连接，或从项目 Releases 下载同版本 ZIP 与 SHA256 文件后手动完整解压。'
    Write-Host '如果该候选版本尚未发布，请使用开发者提供的本地便携包；安装器不会退回旧版本。'
    Write-Host '下载入口：https://github.com/nefelibata5136-code/fish-story-player/releases'
    Write-Host '已有程序、剧情和存档会保留。'
    exit 1
}
