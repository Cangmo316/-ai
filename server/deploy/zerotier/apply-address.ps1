# 拿到服务器地址后，一条命令把客户端配置全部就位
#
#   powershell -ExecutionPolicy Bypass -File apply-address.ps1 -Address http://10.1.1.50:8000
#
# 它做四件事：
#   1. 规范化地址（补协议、去尾斜杠）
#   2. 探测 /healthz —— 不通就直接告诉你原因，不写坏配置
#   3. 写入客户端三处 env（打包用 / 构建期 token / 开发模式）
#   4. 打印"手机端要不要重打包"的明确结论
#
# 为什么地址要写三处：
#   .env.production         → App 打包时的默认地址
#   .env.production.local   → 打生产包时注入的接口 token（不进仓库）
#   .env.development.local  → H5 预览 / 运行到手机时用
#   少写一处，对应场景就会回落到 127.0.0.1:8000（手机上=手机自己，必挂）。
param(
    [Parameter(Mandatory = $true)][string]$Address,
    [string]$ApiToken = '',
    [switch]$Build
)

$ErrorActionPreference = 'Stop'
function Log  { param($m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn { param($m) Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Die  { param($m) Write-Host "  [X]  $m" -ForegroundColor Red; exit 1 }

$repo = 'E:\比邻AI'
$appDir = Join-Path $repo 'uni-app'
if (-not (Test-Path $appDir)) { Die "找不到 $appDir，请确认路径" }

# ── 1. 规范化 ──────────────────────────────────────────────────
$url = $Address.Trim()
if ($url -notmatch '^https?://') { $url = 'http://' + $url }
$url = $url.TrimEnd('/')
if ($url -match '^http://(127\.|localhost)') {
    Warn "地址是 $url —— 手机上的 127.0.0.1 指手机自己，除非服务就跑在这台手机上，否则一定连不上"
}
Log "目标地址：$url"

# ── 2. 先探测，再写配置 ────────────────────────────────────────
# 为什么不先写：写坏配置后 App 会静默连错地址，比直接报错难查得多。
$reachable = $false
$detail = ''
foreach ($i in 1..3) {
    try {
        $r = Invoke-WebRequest -Uri "$url/healthz" -TimeoutSec 8 -UseBasicParsing
        if ($r.StatusCode -eq 200) {
            $body = $r.Content | ConvertFrom-Json
            $reachable = $true
            $detail = "服务正常（$($body.service) v$($body.version)，模型 $($body.llm.model)）"
            break
        }
        $detail = "HTTP $($r.StatusCode)"
    } catch {
        $detail = $_.Exception.Message
        Start-Sleep -Seconds 2
    }
}
if ($reachable) { Log "健康检查通过：$detail" }
else {
    Warn "健康检查失败：$detail"
    Warn "仍然会写入配置，但请先确认："
    Warn "  · 这台机器/手机是否已加入同一个 ZeroTier 网络"
    Warn "  · 服务器上服务是否在跑（systemctl status bilin-api / schtasks）"
    Warn "  · 服务是否只绑了 ZeroTier 地址（HOST=$url 里的 IP）"
    $answer = Read-Host "  仍要继续写入配置吗？(y/N)"
    if ($answer -ne 'y') { Die "已中止，配置未改动" }
}

# ── 3. 写客户端 env ────────────────────────────────────────────
function Write-EnvFile {
    param([string]$Path, [string]$Content)
    # 必须是 UTF-8 无 BOM：带 BOM 会让 Vite 把第一行变量名读成 "﻿VITE_..."
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
    Log "已写 $([System.IO.Path]::GetFileName($Path))"
}

# .env.production：保留原有注释，只改两行
$prodPath = Join-Path $appDir '.env.production'
if (Test-Path $prodPath) {
    $text = [System.IO.File]::ReadAllText($prodPath, [System.Text.UTF8Encoding]::new($false))
    $text = [regex]::Replace($text, '(?m)^VITE_API_BASE_URL=.*$', "VITE_API_BASE_URL=$url")
    $text = [regex]::Replace($text, '(?m)^VITE_API_TOKEN=.*$', 'VITE_API_TOKEN=')
    Write-EnvFile $prodPath $text
}

# .env.production.local：真实 token，不进仓库
$prodLocal = Join-Path $appDir '.env.production.local'
if ($ApiToken) {
    Write-EnvFile $prodLocal "# 生产构建私密配置（.gitignore 已忽略）`nVITE_API_TOKEN=$ApiToken`n"
} elseif (Test-Path $prodLocal) {
    Warn "没给 -ApiToken，保留已有 .env.production.local"
} else {
    Warn "没给 -ApiToken，服务端若开了 AUTH_MODE=required，打包后会全站 401"
}

# .env.development.local：H5 预览用
# 注意：不给 -ApiToken 时要**保留**原有的 token。
# 否则改地址会把 token 抹掉，表现是"地址对了但全站 401"，
# 很难联想到是改地址这一步弄丢的。
$devLocal = Join-Path $appDir '.env.development.local'
$existingDevToken = ''
if (Test-Path $devLocal) {
    $oldText = [System.IO.File]::ReadAllText($devLocal, [System.Text.UTF8Encoding]::new($false))
    $tokenMatch = [regex]::Match($oldText, '(?m)^VITE_API_TOKEN=(.*)$')
    if ($tokenMatch.Success) { $existingDevToken = $tokenMatch.Groups[1].Value.Trim() }
}
$devLines = "VITE_API_BASE_URL=$url`n"
$devToken = if ($ApiToken) { $ApiToken } else { $existingDevToken }
if ($devToken) { $devLines += "VITE_API_TOKEN=$devToken`n" }
Write-EnvFile $devLocal "# 开发模式私密配置（.gitignore 已忽略）`n$devLines"

# ── 4. 结论 ────────────────────────────────────────────────────
Write-Host ""
Write-Host "================ 配置就位 ================" -ForegroundColor Green
Write-Host ""
Write-Host "  服务器地址： $url"
if ($ApiToken) { Write-Host "  接口 token：  $($ApiToken.Substring(0,[Math]::Min(12,$ApiToken.Length)))…" }
Write-Host ""
Write-Host "  ── 已经装好的 App（不用重打包）──"
Write-Host "    我的 → 服务器地址 → 填 $url → 测试连接 → 保存 → 登录"
Write-Host "    （前提：这个包是带我改动的版本，页面上能看到「服务器地址」这一行）"
Write-Host ""
Write-Host "  ── 要出新的 APK ──"
Write-Host "    HBuilderX → 发行 → 原生App-云打包（env 已配好，直接打即可）"
Write-Host ""

if ($Build) {
    Log "开始构建 H5 以验证配置生效"
    $hx = 'E:\download\HBuilderX.5.26.2026091802\HBuilderX'
    if (-not (Test-Path $hx)) { Die "找不到 HBuilderX：$hx" }
    $out = Join-Path $env:TEMP 'bilin-h5-check'
    if (Test-Path $out) { Remove-Item $out -Recurse -Force }
    $env:UNI_INPUT_DIR = $appDir
    $env:UNI_OUTPUT_DIR = $out
    $env:UNI_PLATFORM = 'h5'
    $env:NODE_ENV = 'production'
    $env:UNI_APPID = '__UNI__193904D'
    $env:NODE_OPTIONS = '--max-old-space-size=3072'
    Push-Location (Join-Path $hx 'plugins\uniapp-cli-vite')
    try {
        & (Join-Path $hx 'plugins\node\node.exe') '.\node_modules\@dcloudio\vite-plugin-uni\bin\uni.js' build -p h5 --logLevel warn
        if ($LASTEXITCODE -ne 0) { Die "构建失败" }
    } finally { Pop-Location }

    $hit = Get-ChildItem $out -Recurse -File -Include *.js -ErrorAction SilentlyContinue |
        Select-String -Pattern ([regex]::Escape(($url -replace '^https?://', ''))) -List | Select-Object -First 1
    if ($hit) { Log "产物中已包含新地址 ✅（$($hit.Filename)）" } else { Warn "产物里没找到新地址，检查 .env 是否被别处覆盖" }
}
