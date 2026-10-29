# Source checkout launcher. The portable ZIP does not require PowerShell or Python.
[CmdletBinding()]
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
$taskPortable = Join-Path $taskRoot 'FishStoryPlayer.exe'

function Test-TaskPython {
    param([string]$Executable, [string[]]$Arguments)
    $ErrorActionPreference = 'Continue'
    & $Executable @Arguments *> $null
    return ($LASTEXITCODE -eq 0)
}

try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    if (Test-Path -LiteralPath $taskPortable -PathType Leaf) {
        if ($CheckOnly) { Write-Output '便携版已就绪：无需安装 Python。'; exit 0 }
        & $taskPortable
        exit $LASTEXITCODE
    }
    if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'pyproject.toml') -PathType Leaf)) {
        Write-Host '便携包没有完整解压，找不到 FishStoryPlayer.exe。'
        Write-Host '请重新解压整个 ZIP，保留 _internal 文件夹，再双击 FishStoryPlayer.exe。'
        Write-Host '存档保存在用户目录的 .fish-story-player，重新解压程序不会删除存档。'
        exit 1
    }
    if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
        $taskCommand = $null
        foreach ($taskCandidate in @('py', 'python')) {
            if (-not (Get-Command $taskCandidate -ErrorAction SilentlyContinue)) { continue }
            $taskArguments = @()
            if ($taskCandidate -eq 'py') { $taskArguments += '-3' }
            $taskArguments += @('-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)')
            if (Test-TaskPython -Executable $taskCandidate -Arguments $taskArguments) { $taskCommand = $taskCandidate; break }
        }
        if (-not $taskCommand) {
            Write-Host '本机没有可用的 Python 3.10 或更新版本。'
            Write-Host '推荐使用 Windows 便携包：完整解压后双击 FishStoryPlayer.exe，无需 Python。'
            Write-Host '下载入口：https://github.com/nefelibata5136-code/fish-story-player/releases'
            Write-Host '请确认下载版本包含 README 所述的《底特律》入口；当前候选版尚未发布时请使用随交付提供的本地 ZIP。'
            exit 1
        }
        if ($CheckOnly) { Write-Output '源码环境可准备：发现 Python 3.10+，尚未创建虚拟环境。'; exit 0 }
        Write-Host '首次启动：正在创建本项目独立环境，不会修改其他 Python 项目。'
        $taskArguments = @()
        if ($taskCommand -eq 'py') { $taskArguments += '-3' }
        $taskArguments += @('-m', 'venv', (Join-Path $taskRoot '.venv'))
        & $taskCommand @taskArguments *> $null
        if ($LASTEXITCODE -ne 0) { throw 'ENVIRONMENT_PREPARATION_FAILED' }
    }
    if (-not (Test-TaskPython -Executable $taskPython -Arguments @('-c', 'import fish_story, requests, mcp'))) {
        if ($CheckOnly) { Write-Output 'Python 环境存在，首次启动仍需联网安装项目依赖。'; exit 0 }
        Write-Host '首次启动：正在安装项目依赖，需要连接 Python 包下载服务。'
        & $taskPython -m pip install -e $taskRoot *> $null
        if ($LASTEXITCODE -ne 0) { throw 'DEPENDENCY_INSTALL_FAILED' }
    }
    if ($CheckOnly) { Write-Output '源码环境已就绪。'; exit 0 }
    Push-Location -LiteralPath $taskRoot
    try {
        & $taskPython -m fish_story.desktop
        if ($LASTEXITCODE -ne 0) { throw 'APPLICATION_START_FAILED' }
    } finally { Pop-Location }
} catch {
    Write-Host '启动未完成。请检查网络连接、目录写入权限和便携包是否完整。'
    Write-Host '源码首次安装依赖失败时，可重新双击 start.cmd 重试；也可使用不依赖 Python 的 Windows 便携包。'
    Write-Host '已有存档不会因重新启动或重新解压程序而删除。详细步骤见 README.md。'
    exit 1
}
