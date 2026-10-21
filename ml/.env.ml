# 微调环境的 KEY=VALUE 配置（纯文本，不依赖脚本执行策略）
#
# 为什么要这个文件：PowerShell 默认执行策略不许 dot-source 未签名 .ps1，
# 而 dot-source 失败的表现是"变量静悄悄没设上"，很难发现。
# 这个文件由调用方用 cmdlet 逐行 Set-Item，纯 cmdlet 不受执行策略限制。
#
# 为什么全部指向 E 盘：pip 缓存 / 模型缓存 / 解包临时目录默认都在 C 盘
# （C 只剩 20GB 左右）。torch 2.4GB + 模型 3GB + 解包临时空间，
# 很容易把系统盘撑爆。E 盘还剩 700GB。
PIP_CACHE_DIR=E:\比邻AI\ml\.cache\pip
TMP=E:\比邻AI\ml\.cache\tmp
TEMP=E:\比邻AI\ml\.cache\tmp
HF_HOME=E:\比邻AI\ml\.cache\huggingface
MODELSCOPE_CACHE=E:\比邻AI\ml\.cache\modelscope
HF_HUB_DISABLE_SYMLINKS_WARNING=1
TRANSFORMERS_NO_ADVISORY_WARNINGS=1
TOKENIZERS_PARALLELISM=false
PYTHONIOENCODING=utf-8
PYTHONPATH=E:\比邻AI\server
ML_PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/
