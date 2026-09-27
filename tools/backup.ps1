# 注意：本文件必须保存为「UTF-8 带 BOM」。
# Windows PowerShell 5.1 会把无 BOM 的 UTF-8 当 ANSI(GBK) 解码，导致中文注释与
# 字符串错乱、脚本无法解析执行（实测：无 BOM 报 7 处语法错误，带 BOM 为 0）。
# 若编辑器保存时去掉了 BOM，请加回。
<#
.SYNOPSIS
  比邻AI 仓库备份：推送本地裸镜像 + 生成不可变 bundle 快照

.DESCRIPTION
  两步备份策略：

    1) 推送 localmirror（默认 D:\backup\bilin-ai.git）—— 增量，日常用。
       刻意不使用 --mirror 推送：镜像推送会把本地的删除、强推同步过去，
       备份会跟着源一起坏掉。这里只做普通推送，仅允许快进。

    2) 生成 git bundle 单文件快照 —— 不可变，可直接拷到 U 盘 / 网盘 / 另一台机器。
       即使源仓库被误删或历史被改写，已生成的快照依然可以完整还原。

  快照默认保留最近 20 份，更旧的自动清理。

.PARAMETER SkipPush
  只生成快照，不推镜像。

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\backup.ps1

.EXAMPLE
  还原（二选一）：
  git clone D:\backup\bilin-ai.git  E:\restore\bilin-ai
  git clone D:\backup\bundles\bilin-ai-20260927-120000.bundle  E:\restore\bilin-ai
#>
[CmdletBinding()]
param(
    [string]$RepoPath  = '',
    [string]$MirrorDir = 'D:\backup\bilin-ai.git',
    [string]$BundleDir = 'D:\backup\bundles',
    [int]$Keep = 20,
    [switch]$SkipPush
)

$ErrorActionPreference = 'Stop'

if (-not $RepoPath) { $RepoPath = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path }
if (-not (Test-Path (Join-Path $RepoPath '.git'))) { throw "不是 git 仓库：$RepoPath" }

function Resolve-GitExe {
    <#
      定位 git.exe：按「PATH -> 常见安装位置 -> Codex 运行时缓存」顺序查找。
      本机未独立安装 Git for Windows，可用的 git 来自 Codex 运行时自带的副本，
      且不在系统/用户 PATH 中 —— 计划任务环境下 Get-Command git 会落空，故显式查找。
    #>
    $onPath = Get-Command git -CommandType Application -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }

    $candidates = @(
        (Join-Path $env:ProgramFiles 'Git\cmd\git.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Git\cmd\git.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe'),
        (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe')
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }

    $rtRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes'
    if (Test-Path -LiteralPath $rtRoot) {
        $hit = Get-ChildItem -LiteralPath $rtRoot -Recurse -Filter 'git.exe' -ErrorAction SilentlyContinue |
               Where-Object { $_.Directory.Name -eq 'cmd' } |
               Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }

    throw '未找到 git.exe：PATH 与常见安装位置均无。请安装 Git for Windows，或把 git.exe 所在目录加入 PATH。'
}

$script:GitExe = Resolve-GitExe

function Invoke-Git {
    <#
      跑一条 git 命令，返回 stdout + stderr 的行数组；退出码非 0 时抛出。

      为什么用 System.Diagnostics.Process 而不是 & git：
      Windows PowerShell 5.1 下原生命令的 stderr 会被 PowerShell 接管 ——
      $ErrorActionPreference='Stop' 时直接抛终止性错误；改成 'Continue' 也不行，
      因为 `2>文件` 写进文件的是 PowerShell 自己格式化后的错误文本
      （含 At line / CategoryInfo），而不是 git 的原始 stderr。
      直接用 Process 取 stdout/stderr 可绕开这层，退出码也更可靠。
    #>
    param([string]$WorkDir, [string[]]$GitArgs)

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName  = $script:GitExe
    $psi.Arguments = ((@('-C', $WorkDir) + $GitArgs) | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join ' '
    $psi.UseShellExecute        = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.CreateNoWindow         = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding  = [System.Text.Encoding]::UTF8

    $proc   = [System.Diagnostics.Process]::Start($psi)
    # 先异步读 stdout，避免两个管道互相填满导致死锁
    $soTask = $proc.StandardOutput.ReadToEndAsync()
    $se     = $proc.StandardError.ReadToEnd()
    $so     = $soTask.GetAwaiter().GetResult()
    $proc.WaitForExit()
    $code = $proc.ExitCode

    $outText = ''
    $errText = ''
    if ($so) { $outText = $so.Trim() }
    if ($se) { $errText = $se.Trim() }

    if ($code -ne 0) {
        throw ('git ' + ($GitArgs -join ' ') + ' 失败（exit ' + $code + '）:' +
               [Environment]::NewLine + $errText)
    }

    $lines = @()
    if ($outText) { $lines += @($outText -split "`r?`n" | Where-Object { $_.Trim() -ne '' }) }
    if ($errText) { $lines += @($errText -split "`r?`n" | Where-Object { $_.Trim() -ne '' }) }
    return $lines
}

$head   = ((Invoke-Git -WorkDir $RepoPath -GitArgs @('rev-parse', '--short', 'HEAD')) -join '').Trim()
$branch = ((Invoke-Git -WorkDir $RepoPath -GitArgs @('rev-parse', '--abbrev-ref', 'HEAD')) -join '').Trim()
Write-Host "git    : $script:GitExe"
Write-Host "仓库   : $RepoPath"
Write-Host "分支   : $branch   HEAD $head"
Write-Host ''

if (-not $SkipPush) {
    Write-Host "[1/2] 推送到裸镜像 $MirrorDir"
    if (Test-Path $MirrorDir) {
        $remotes = (Invoke-Git -WorkDir $RepoPath -GitArgs @('remote')) -join ' '
        if ($remotes -notmatch 'localmirror') {
            Invoke-Git -WorkDir $RepoPath -GitArgs @('remote', 'add', 'localmirror', $MirrorDir) | Out-Null
            Write-Host '      已添加远端 localmirror'
        }
        foreach ($l in (Invoke-Git -WorkDir $RepoPath -GitArgs @('push', 'localmirror', $branch))) {
            Write-Host "      $l"
        }
        $remoteHead = ((Invoke-Git -WorkDir $MirrorDir -GitArgs @('rev-parse', '--short', $branch)) -join '').Trim()
        Write-Host "      镜像端 HEAD $remoteHead"
    }
    else {
        Write-Host "      跳过：裸镜像不存在（$MirrorDir）"
        Write-Host '      初始化：git clone --mirror E:\比邻AI D:\backup\bilin-ai.git'
    }
    Write-Host ''
}

Write-Host '[2/2] 生成 bundle 快照'
New-Item -ItemType Directory -Path $BundleDir -Force | Out-Null
$bundleDirFull = (Resolve-Path $BundleDir).Path
$bundle = Join-Path $bundleDirFull ('bilin-ai-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.bundle')
Invoke-Git -WorkDir $RepoPath -GitArgs @('bundle', 'create', $bundle, '--all') | Out-Null
$bundleMB = [math]::Round((Get-Item $bundle).Length / 1MB, 2)
Write-Host "      完成 $bundleMB MB"
Write-Host ''

$all = @(Get-ChildItem -LiteralPath $bundleDirFull -Filter 'bilin-ai-*.bundle' |
         Sort-Object LastWriteTime -Descending)
if ($all.Count -gt $Keep) {
    $drop = @($all | Select-Object -Skip $Keep)
    foreach ($f in $drop) {
        if ($f.DirectoryName -ne $bundleDirFull) { throw "路径校验失败，拒绝删除：$($f.FullName)" }
    }
    $drop | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
    Write-Host ("      清理旧快照 {0} 份，保留最近 {1} 份" -f $drop.Count, $Keep)
}
$sumMB = [math]::Round((($all | Measure-Object -Property Length -Sum).Sum) / 1MB, 2)
Write-Host ("当前快照 {0} 份，合计 {1} MB" -f $all.Count, $sumMB)