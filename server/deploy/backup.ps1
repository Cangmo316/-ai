# 比邻AI · 数据备份（Windows）
#
#   powershell -ExecutionPolicy Bypass -File backup.ps1
#   powershell -ExecutionPolicy Bypass -File backup.ps1 -OutDir D:\bilin-backup -Keep 30
#
# 为什么 SQLite 不能直接 copy：
#   服务在跑（WAL 模式），部分提交还在 bilin.db-wal 里。直接 Copy-Item 拿到的是
#   **旧的**数据库；如果拷的瞬间正好 checkpoint，还可能拷到半个事务。
#   必须用 SQLite 的 backup API 做一致性快照 —— 这也是 Linux 版 backup.sh 的做法。
#
# 为什么还要备份 case_files：
#   病例原件（拍照上传的病历、检查单）在数据库里只有路径，文件本身丢了就真没了。
param(
    [string]$DataDir = '',
    [string]$OutDir = '',
    [int]$Keep = 14
)

$ErrorActionPreference = 'Stop'
function Log  { param($m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn { param($m) Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Die  { param($m) Write-Host "  [X]  $m" -ForegroundColor Red; exit 1 }

# 默认布局：C:\bilin\server（setup-windows.ps1 的部署位置）
if (-not $DataDir) { $DataDir = 'C:\bilin\server' }
if (-not (Test-Path $DataDir)) {
    # 退回到本仓库布局，方便开发机直接用
    $guess = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'server'
    if (Test-Path (Join-Path $guess 'data')) {
        $DataDir = $guess
        Warn "没找到 C:\bilin\server，改用仓库内路径：$DataDir"
    } else {
        Die "找不到数据目录，请用 -DataDir 指定（例如 -DataDir C:\bilin\server）"
    }
}

if (-not $OutDir) {
    $OutDir = Join-Path (Split-Path $DataDir -Parent) 'backup'
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$work = Join-Path $OutDir "snapshot-$stamp"
New-Item -ItemType Directory -Force -Path $work | Out-Null

# ── 1. 数据库一致性快照 ─────────────────────────────────────────
$db = Join-Path $DataDir 'data\bilin.db'
$snapDb = Join-Path $work 'bilin.db'
if (-not (Test-Path $db)) {
    Warn "没有 $db，跳过数据库备份"
} else {
    # 用 Python 的 sqlite3.backup()：服务端本来就依赖 Python，不需要额外装工具。
    #
    # 坑：Windows 上 `python` 常常解析到
    #   C:\Users\<u>\AppData\Local\Microsoft\WindowsApps\python.exe
    # 那是应用商店的占位程序 —— 调用它不会正常执行脚本，表现为"备份跑了但没生成库"。
    # 所以这里逐个探测候选路径并**实际执行一次**验证，而不是盲信 `python`。
    function Resolve-Python {
        $candidates = @(
            (Join-Path (Split-Path $DataDir -Parent) '.venv\Scripts\python.exe'),
            (Join-Path $DataDir '.venv\Scripts\python.exe'),
            'python3',
            'python'
        )
        foreach ($cand in $candidates) {
            if (-not $cand) { continue }
            $exe = $cand
            if (-not (Test-Path $exe)) {
                $cmd = Get-Command $cand -ErrorAction SilentlyContinue
                if (-not $cmd) { continue }
                $exe = $cmd.Source
            }
            if ($exe -match 'WindowsApps') { continue }   # 商店占位程序，跳过
            try {
                $probe = & $exe -c "import sqlite3,sys; print(sys.version_info[0])" 2>$null
                if ($LASTEXITCODE -eq 0 -and "$probe".Trim() -match '^3$') { return $exe }
            } catch { }
        }
        return $null
    }

    $python = Resolve-Python
    if (-not $python) {
        Die "找不到可用的 Python 3（已跳过 WindowsApps 占位程序）。请装 Python 3.11+，或指定 -DataDir 指向带 .venv 的部署目录"
    }
    Log "使用 Python：$python"
    $script = @"
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect('file:' + src + '?mode=ro', uri=True)
t = sqlite3.connect(dst)
s.backup(t)
t.close(); s.close()
print('  backup() 完成')
"@
    $tmp = Join-Path $env:TEMP 'bilin_sqlite_backup.py'
    [System.IO.File]::WriteAllText($tmp, $script, [System.Text.UTF8Encoding]::new($false))
    & $python $tmp $db $snapDb
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path $snapDb)) { Die "数据库快照失败" }
    $sizeMb = [Math]::Round((Get-Item $snapDb).Length / 1MB, 2)
    Log "数据库快照 $sizeMb MB"

    # 完整性自检：能打开且能查询，才算备份可用
    $check = @"
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
r = c.execute('PRAGMA integrity_check').fetchone()[0]
n = c.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
print('  integrity=%s accounts=%d' % (r, n))
c.close()
"@
    $tmp2 = Join-Path $env:TEMP 'bilin_sqlite_check.py'
    [System.IO.File]::WriteAllText($tmp2, $check, [System.Text.UTF8Encoding]::new($false))
    & $python $tmp2 $snapDb
    Remove-Item $tmp2 -Force -ErrorAction SilentlyContinue
}

# ── 2. 病例文件与其它运行数据 ───────────────────────────────────
foreach ($name in @('case_files', 'data\wiki', 'data\care', '_voice_samples')) {
    $src = Join-Path $DataDir $name
    if (-not (Test-Path $src)) { continue }
    $dst = Join-Path $work ($name -replace '^data\\', 'data-')
    Copy-Item $src $dst -Recurse -Force
    $count = (Get-ChildItem $dst -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
    Log "$name → $(Split-Path $dst -Leaf)（$count 个文件）"
}

# ── 3. 配置文件（不含密钥则不备份）──────────────────────────────
# 默认**不备份 .env**：里面有 API 密钥，跟数据放一起会扩大泄露面。
# 需要的话手动加 -IncludeEnv（脚本没暴露这个开关，是有意的：密钥请单独保管）。
Warn "未备份 .env（含密钥，请单独保管：服务端 /etc/bilin/bilin.env 或 C:\ProgramData\bilin\bilin.env）"

# ── 4. 压包 ────────────────────────────────────────────────────
$zip = Join-Path $OutDir "bilin-backup-$stamp.zip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($work, $zip)
Remove-Item $work -Recurse -Force
Log "已打包 $zip（$([Math]::Round((Get-Item $zip).Length / 1MB, 2)) MB）"

# ── 5. 轮转：只留最近 N 份 ─────────────────────────────────────
$olds = Get-ChildItem $OutDir -Filter 'bilin-backup-*.zip' | Sort-Object LastWriteTime -Descending | Select-Object -Skip $Keep
foreach ($f in $olds) { Remove-Item $f.FullName -Force; Log "清理旧备份 $($f.Name)" }
$remain = (Get-ChildItem $OutDir -Filter 'bilin-backup-*.zip' | Measure-Object).Count
Log "当前保留 $remain 份（上限 $Keep）"

Write-Host ""
Write-Host "备份完成：$zip" -ForegroundColor Green
Write-Host ""
Write-Host "  挂成每天自动（管理员 PowerShell，以当前用户身份即可）：" -ForegroundColor Cyan
Write-Host "  schtasks /create /tn BilinBackup /tr `"powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`"`" /sc daily /st 03:05 /f"
Write-Host ""
Write-Host "  强烈建议把备份再同步到另一块盘/NAS/网盘 —— 同一块盘坏了备份也一起没。" -ForegroundColor Yellow
Write-Host ""
