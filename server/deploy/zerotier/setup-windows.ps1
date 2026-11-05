# 比邻AI · 私有化部署（Windows 服务器 + ZeroTier）
#
#   powershell -ExecutionPolicy Bypass -File setup-windows.ps1 -Network <网络ID>
#
# 适用于「用一台 Windows 常开电脑当服务器」的情况（比如你现有的开发机/家里主机）。
#
# 为什么给 Windows 也写一份：
#   deploy.sh 是 Linux 的（apt + systemd）。Windows 上要换成
#   计划任务 + 手动 venv，两者差异大，所以单独一条路，而不是硬套。
#
# 前置要求：
#   · **必须用管理员 PowerShell 运行**（装 ZeroTier 服务、开防火墙都要）
#   · 机器已经装好 Python 3.11+（推荐 3.13）
param(
    [Parameter(Mandatory = $true)][string]$Network,
    [int]$Port = 8000,
    [string]$RepoUrl = 'https://github.com/Cangmo316/-ai.git',
    [string]$SrcDir = 'C:\bilin-src',
    [string]$DataDir = 'C:\bilin'
)

$ErrorActionPreference = 'Stop'
function Log  { param($m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn { param($m) Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Die  { param($m) Write-Host "  [X]  $m" -ForegroundColor Red; exit 1 }

# ── 0. 管理员检查 ───────────────────────────────────────────────
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Die "请用「管理员身份」打开 PowerShell 再运行"
}

# ── 1. Python ──────────────────────────────────────────────────
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { Die "没找到 python，请先装 Python 3.11+（https://www.python.org/downloads/）" }
$ver = & $python -c "import sys; print('%d.%d' % sys.version_info[:2])"
Log "Python $ver"
if ([version]$ver -lt [version]'3.11') { Die "需要 Python 3.11+，当前 $ver" }

# ── 2. ZeroTier ────────────────────────────────────────────────
$ztService = Get-Service -Name 'ZeroTierOneService' -ErrorAction SilentlyContinue
if (-not $ztService) {
    Log "安装 ZeroTier（需要外网）"
    $msi = Join-Path $env:TEMP 'ZeroTierOne.msi'
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri 'https://download.zerotier.com/dist/ZeroTier%20One.msi' -OutFile $msi -TimeoutSec 300 -UseBasicParsing
    } catch { Die "下载 ZeroTier 失败：$($_.Exception.Message)" }
    Start-Process msiexec.exe -ArgumentList @('/i', $msi, '/qn', '/norestart') -Wait
    Start-Sleep -Seconds 5
    $ztService = Get-Service -Name 'ZeroTierOneService' -ErrorAction SilentlyContinue
    if (-not $ztService) { Die "ZeroTier 安装后仍没有服务，请手动装：https://www.zerotier.com/download/" }
}
if ($ztService.Status -ne 'Running') { Start-Service ZeroTierOneService; Start-Sleep -Seconds 3 }
Log "ZeroTier 服务运行中"

$ztCli = 'C:\ProgramData\ZeroTier\One\zerotier-cli.bat'
if (-not (Test-Path $ztCli)) { Die "没找到 zerotier-cli.bat，ZeroTier 可能装得不完整" }

Log "加入网络 $Network"
& $ztCli join $Network | Out-Null

# ── 3. 等 ZeroTier 地址（需要去控制台授权）────────────────────
Log "等待 ZeroTier 分配地址（最多 180 秒）"
$ztIp = ''
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 3
    $addr = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.InterfaceAlias -match 'ZeroTier' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -First 1
    if ($addr) { $ztIp = $addr.IPAddress; break }
}
if (-not $ztIp) {
    Warn "还没拿到地址。请去 my.zerotier.com → 你的网络 → Members → 勾上这个节点（Auth）"
    & $ztCli listnetworks
    Die "授权后重新运行本脚本"
}
Log "ZeroTier 地址：$ztIp"

# ── 4. 代码 ────────────────────────────────────────────────────
if (Test-Path (Join-Path $SrcDir '.git')) {
    Log "更新代码"
    git -C $SrcDir fetch --depth 1 origin main
    git -C $SrcDir reset --hard origin/main
} else {
    Log "克隆代码到 $SrcDir"
    if (Test-Path $SrcDir) { Remove-Item $SrcDir -Recurse -Force }
    git clone --depth 1 $RepoUrl $SrcDir
}

$serverSrc = Join-Path $SrcDir 'server'
$serverDst = Join-Path $DataDir 'server'
New-Item -ItemType Directory -Force -Path $serverDst | Out-Null

Log "同步代码到 $serverDst"
# 不覆盖 data / case_files（运行数据），其余镜像过去
robocopy $serverSrc $serverDst /MIR /XD .venv __pycache__ data case_files _voice_samples /NFL /NDL /NJH /NJS /NP | Out-Null

# ── 5. 虚拟环境 ────────────────────────────────────────────────
$venv = Join-Path $DataDir '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Log "创建虚拟环境"
    & $python -m venv $venv
}
Log "安装依赖（走阿里云镜像）"
& $venvPy -m pip install --upgrade pip -q -i https://mirrors.aliyun.com/pypi/simple/
& $venvPy -m pip install -r (Join-Path $serverDst 'requirements.txt') -q -i https://mirrors.aliyun.com/pypi/simple/

# ── 6. 配置文件 ────────────────────────────────────────────────
$envDir = 'C:\ProgramData\bilin'
New-Item -ItemType Directory -Force -Path $envDir | Out-Null
$envFile = Join-Path $envDir 'bilin.env'

if (-not (Test-Path $envFile)) {
    $srcEnv = Join-Path $serverDst '.env'
    if (Test-Path $srcEnv) {
        (Get-Content $srcEnv) -replace '^HOST=.*', "HOST=$ztIp" | Set-Content $envFile -Encoding UTF8
    } else {
        Warn "仓库里没有 .env，生成最小配置（密钥要手动填）"
        @(
            'LLM_PROVIDER=auto'
            'LLM_BASE_URL=https://api.deepseek.com/v1'
            'LLM_API_KEY='
            'LLM_MODEL=deepseek-chat'
            "HOST=$ztIp"
            "PORT=$Port"
            'LOG_LEVEL=info'
            'DATABASE_URL=sqlite:///data/bilin.db'
        ) | Set-Content $envFile -Encoding UTF8
    }
}
# 强制：只绑 ZeroTier 地址 + 开鉴权
$content = Get-Content $envFile
$content = $content -replace '^HOST=.*', "HOST=$ztIp"
if (-not ($content | Where-Object { $_ -match '^AUTH_MODE=' })) { $content += 'AUTH_MODE=required' }
if (-not ($content | Where-Object { $_ -match '^API_TOKENS=.+' })) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $token = ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
    $content += "API_TOKENS=$token"
    Warn "已生成接口 token：$token"
}
$content | Set-Content $envFile -Encoding UTF8
$apiToken = (Get-Content $envFile | Where-Object { $_ -match '^API_TOKENS=' } | Select-Object -First 1) -replace '^API_TOKENS=', ''

# 给程序读的 .env（run.py 从这个文件读）
Copy-Item $envFile (Join-Path $serverDst '.env') -Force

# ── 7. 注册为计划任务（开机自启 + 常驻）───────────────────────
$taskName = 'BilinAPI'
$launcher = Join-Path $DataDir 'run-bilin.cmd'
# 用 .cmd 包一层：cmd 的重定向最稳，且避免计划任务直接跑 exe 时工作目录不对
$lines = @(
    '@echo off'
    "cd /d `"$serverDst`""
    "`"$venvPy`" run.py > `"$DataDir\server.log`" 2> `"$DataDir\server.err`""
)
[System.IO.File]::WriteAllLines($launcher, $lines, [System.Text.Encoding]::Default)

schtasks /delete /tn $taskName /f 2>$null | Out-Null
schtasks /create /tn $taskName /tr "`"$launcher`"" /sc onstart /ru SYSTEM /rl HIGHEST /f | Out-Null
Log "已注册计划任务 $taskName（开机自启，以 SYSTEM 运行）"
schtasks /run /tn $taskName | Out-Null
Start-Sleep -Seconds 8

# ── 8. 防火墙：只放 ZeroTier 网段 ──────────────────────────────
$ztPrefix = ($ztIp -split '\.')[0..2] -join '.'
$ruleName = "BilinAPI-$Port"
Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort $Port -RemoteAddress "$ztPrefix.0/24" -Profile Any | Out-Null
Log "防火墙：仅允许 $ztPrefix.0/24 访问 $Port"

# ── 9. 自检 ────────────────────────────────────────────────────
$ok = $false
foreach ($i in 1..15) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest -Uri "http://${ztIp}:$Port/healthz" -TimeoutSec 6 -UseBasicParsing
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}
if ($ok) { Log "healthz 通过" } else {
    Warn "healthz 没通过，看日志：$DataDir\server.err"
    Get-Content (Join-Path $DataDir 'server.err') -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object { "    $_" }
}

Write-Host ""
Write-Host "================ 部署完成 ================" -ForegroundColor Green
Write-Host ""
Write-Host "  服务器地址： http://${ztIp}:$Port"
Write-Host "  接口 token：  $apiToken"
Write-Host ""
Write-Host "  ── 手机上两步 ──"
Write-Host "  1. 装 ZeroTier，加入网络 $Network（并在 my.zerotier.com 勾上手机的 Auth）"
Write-Host "  2. 比邻AI → 我的 → 服务器地址 → 填 http://${ztIp}:$Port → 测试 → 保存"
Write-Host ""
Write-Host "  ── 常用 ──"
Write-Host "  Get-Content $DataDir\server.log -Tail 30 -Wait    # 实时日志"
Write-Host "  schtasks /query /tn $taskName /v /fo LIST        # 看任务状态"
Write-Host ""
