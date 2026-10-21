# 带执行策略绕过的运行器：设置 ML 环境变量后执行 python 脚本
#
# 用法（从任意 PowerShell 调用）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File E:\比邻AI\ml\run.ps1 scripts\train_lora.py
#
# 为什么不直接 dot-source env.ps1：默认执行策略不许跑未签名脚本，
# 而 dot-source 失败时变量是"静悄悄没设上"，很坑。
$ErrorActionPreference = 'Stop'
$MlRoot = 'E:\比邻AI\ml'
$Py = Join-Path $MlRoot '.venv\Scripts\python.exe'
$EnvFile = Join-Path $MlRoot '.env.ml'

# 建立目录（放在 E 盘）
foreach ($d in @(
    (Join-Path $MlRoot '.cache\pip'),
    (Join-Path $MlRoot '.cache\tmp'),
    (Join-Path $MlRoot '.cache\huggingface'),
    (Join-Path $MlRoot '.cache\modelscope'),
    (Join-Path $MlRoot 'models'),
    (Join-Path $MlRoot 'out'),
    (Join-Path $MlRoot 'wheels')
)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}

# 逐行加载 KEY=VALUE（纯 cmdlet，不受执行策略限制）
if (Test-Path $EnvFile) {
    Get-Content $EnvFile -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
            $i = $line.IndexOf('=')
            $k = $line.Substring(0, $i).Trim()
            $v = $line.Substring($i + 1).Trim()
            Set-Item -Path ("Env:" + $k) -Value $v
        }
    }
}

if ($args.Count -eq 0) {
    Write-Host "  用法: run.ps1 <script.py> [args...]"
    Write-Host "  pip 缓存: $env:PIP_CACHE_DIR"
    Write-Host "  模型缓存: $env:MODELSCOPE_CACHE"
    exit 0
}

$script = $args[0]
$rest = @()
if ($args.Count -gt 1) { $rest = $args[1..($args.Count - 1)] }

Push-Location $MlRoot
try {
    & $Py $script @rest
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
