# 微调环境变量（所有 ML 命令先 dot-source 这个文件）
#
#     . E:\比邻AI\ml\env.ps1
#
# 为什么需要它：pip 缓存、HuggingFace/ModelScope 模型缓存、临时解包目录
# 默认全在 C 盘（C 只剩 20GB 左右）。torch 轮子 2.4GB + 模型 3GB + 解包临时空间，
# 一个不小心就把系统盘撑爆。这里全部重定向到 E 盘（剩 700GB）。

$MlRoot = 'E:\比邻AI\ml'
$Cache  = Join-Path $MlRoot '.cache'

foreach ($d in @(
    $Cache,
    (Join-Path $Cache 'pip'),
    (Join-Path $Cache 'huggingface'),
    (Join-Path $Cache 'modelscope'),
    (Join-Path $Cache 'tmp'),
    (Join-Path $MlRoot 'wheels'),
    (Join-Path $MlRoot 'models'),
    (Join-Path $MlRoot 'out')
)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}

# pip：包缓存与临时解包
$env:PIP_CACHE_DIR = Join-Path $Cache 'pip'
$env:TMP  = Join-Path $Cache 'tmp'
$env:TEMP = Join-Path $Cache 'tmp'

# 模型下载缓存（HuggingFace 不通，实际走 ModelScope，但两个都指过去）
$env:HF_HOME = Join-Path $Cache 'huggingface'
$env:MODELSCOPE_CACHE = Join-Path $Cache 'modelscope'

# 训练时的离线友好设置
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
$env:TRANSFORMERS_NO_ADVISORY_WARNINGS = '1'
$env:TOKENIZERS_PARALLELISM = 'false'

# 国内镜像（pip 装小包用）
$env:ML_PIP_INDEX = 'https://mirrors.aliyun.com/pypi/simple/'

$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = 'E:\比邻AI\server'
