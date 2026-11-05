"""打「一键部署包」：把 git 里没有、又必须带的东西装在一起。

    python server/deploy/build-bundle.py --server E:\\比邻AI\\server --out dist

## 为什么代码不进包

GitHub 仓库是公开的，服务器上 `git clone` 就能拿到最新代码，没必要把 2.8MB 源码
重复塞进包里。真正**git 里没有**的只有两样：

  · `.env`   —— 含 DeepSeek / DashScope 密钥，永远不能进公开仓库
  · `data/`  —— 账号、聊天记录、wiki、care、病例原件（.gitignore 排除）

## 为什么还要带 zerotier/ 脚本和 env 模板

如果目标机器连不上 GitHub，`git clone` 会失败，那时包里得有脚本可用。
所以包内自带一份部署脚本副本 + 两套 `.env` 模板（云端 API / 本地模型），
配合 `install.sh` 在离线/半离线环境也能起步。

## SQLite 为什么必须用 backup()

服务在跑（WAL 模式），直接拷 `bilin.db` 会漏掉 `-wal` 里还没 checkpoint 的数据，
拿到的是**旧的**甚至不一致的库。`sqlite3.backup()` 才是一致性快照。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tarfile
import time
from pathlib import Path

# 需要拷贝的运行数据（相对 server/）
DATA_ITEMS = ("data", "case_files")

# 打包时要带上的脚本与文档（相对 server/deploy/）
DEPLOY_ITEMS = (
    "deploy.sh",
    "bilin-api.service",
    "backup.sh",
    "backup.ps1",
    "nginx-bilin.conf",
    "Caddyfile",
    "setup-proxy.sh",
    "zerotier",
    "local-models",
    "docker.md",
)

INSTALL_SH = r"""#!/usr/bin/env bash
# 比邻AI · 一键部署（从本包的 install.sh 启动）
#
#   sudo bash install.sh                      # 只部署后端
#   sudo bash install.sh --network <ZT网络ID> # 部署 + 加入 ZeroTier
#
# 逻辑：
#   1. 先把本包里的 .env 与数据就位
#   2. 代码优先从 GitHub 拉；拉不到就用本包内自带的脚本目录
#   3. 有 --network 就走 ZeroTier 那条路
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NETWORK=""
SRC_DIR="${SRC_DIR:-/opt/bilin-src}"
REPO="${REPO:-https://github.com/Cangmo316/-ai.git}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --network) NETWORK="${2:-}"; shift 2 ;;
    --src) SRC_DIR="${2:-}"; shift 2 ;;
    *) echo "未知参数：$1"; exit 1 ;;
  esac
done

log() { echo "  ✓ $*"; }
warn() { echo "  ! $*"; }

[[ $EUID -eq 0 ]] || { echo "请用 root 运行"; exit 1; }

# 1. 取代码
if [[ -d "$SRC_DIR/.git" ]]; then
  log "更新已有代码 $SRC_DIR"
  git -C "$SRC_DIR" fetch --depth 1 origin main && git -C "$SRC_DIR" reset --hard origin/main || warn "更新失败，用现有代码"
else
  if git clone --depth 1 "$REPO" "$SRC_DIR" 2>/dev/null; then
    log "已从 GitHub 拉取代码"
  else
    warn "拉不到 GitHub，用本包自带的脚本目录（只能手工部署，见 zerotier/README.md）"
    mkdir -p "$SRC_DIR/server"
    cp -r "$HERE/zerotier" "$SRC_DIR/server/deploy-zerotier"
    exit 3
  fi
fi

# 2. 配置与数据就位（deploy.sh 会从 SRC_SERVER 迁移数据）
log "放置 .env 与数据"
cp "$HERE/.env" "$SRC_DIR/server/.env"
chmod 600 "$SRC_DIR/server/.env"
mkdir -p "$SRC_DIR/server/data" "$SRC_DIR/server/case_files"
for item in data case_files; do
  if [[ -d "$HERE/$item" ]]; then
    cp -r "$HERE/$item/." "$SRC_DIR/server/$item/"
    log "已放入 $item"
  fi
done

# 3. 部署
if [[ -n "$NETWORK" ]]; then
  log "走 ZeroTier 路径（网络 $NETWORK）"
  bash "$SRC_DIR/server/deploy/zerotier/setup-linux.sh" --network "$NETWORK"
else
  log "走普通路径"
  bash "$SRC_DIR/server/deploy/deploy.sh"
  echo
  warn "后端默认只监听 127.0.0.1，外部访问请二选一："
  warn "  · 跑 ZeroTier：bash $SRC_DIR/server/deploy/zerotier/setup-linux.sh --network <ID>"
  warn "  · 或改 /etc/bilin/bilin.env 的 HOST 为内网 IP，再由防火墙控制访问"
fi
"""


def read_env(server: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    path = server / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def build_runtime_env(env: dict[str, str], token: str, host: str) -> str:
    """生产口径的 .env：只绑本机/内网、强制鉴权。"""
    merged = dict(env)
    merged["HOST"] = host
    merged["LOG_LEVEL"] = "info"
    merged["AUTH_MODE"] = "required"
    merged["API_TOKENS"] = token
    merged["CORS_ORIGINS"] = ""
    lines = [
        "# 比邻AI 生产配置（权限 600）",
        f"# 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        "# HOST：默认 127.0.0.1，由 Nginx/Caddy 或 ZeroTier 脚本改成实际监听地址",
        "# AUTH_MODE=required：接口里有老人健康档案，必须鉴权",
        "",
    ]
    lines += [f"{k}={v}" for k, v in merged.items()]
    return "\n".join(lines) + "\n"


def profile_cloud(env: dict[str, str]) -> str:
    """模板 A：继续用云端 API（DeepSeek + 阿里语音）。"""
    return "\n".join([
        "# .env 模板 A · 云端 API（需要出网）",
        "# 用法：cp env.profile-cloud .env  然后填 LLM_API_KEY / DASHSCOPE_API_KEY",
        "",
        "LLM_PROVIDER=openai_compat",
        "LLM_BASE_URL=https://api.deepseek.com/v1",
        "LLM_API_KEY=",
        "LLM_MODEL=deepseek-chat",
        "",
        "# 语音（可选；不填则语音功能自动降级为不可用，文字对话不受影响）",
        "DASHSCOPE_API_KEY=",
        "BILIN_TTS_PROVIDER=qwen",
        "BILIN_ASR_PROVIDER=qwen",
        "",
        "HOST=127.0.0.1",
        "PORT=8000",
        "LOG_LEVEL=info",
        "DATABASE_URL=sqlite:///data/bilin.db",
        "CORS_ORIGINS=",
        "AUTH_MODE=required",
        "API_TOKENS=",
        "",
    ])


def profile_local() -> str:
    """模板 B：完全本地模型（Ollama + whisper.cpp + Piper），不需要出网。"""
    return "\n".join([
        "# .env 模板 B · 完全本地（不需要出网）",
        "# 前置：ollama create bilin-qwen -f Modelfile  （见 local-models/README.md）",
        "#       whisper.cpp / piper 按 local-models/README.md 安装",
        "",
        "# 对话：本机 Ollama（用我们微调的 Qwen2.5-1.5B）",
        "LLM_PROVIDER=openai_compat",
        "LLM_BASE_URL=http://127.0.0.1:11434/v1",
        "LLM_MODEL=bilin-qwen",
        "LLM_API_KEY=ollama",
        "",
        "# 语音识别：本地 whisper.cpp",
        "BILIN_ASR_PROVIDER=command",
        "BILIN_ASR_CMD=whisper-cli -m /opt/models/ggml-small.bin -f {audio} -l zh -otxt -of {out}",
        "",
        "# 语音合成：本地 Piper",
        "BILIN_TTS_PROVIDER=command",
        "BILIN_TTS_CMD=piper -m /opt/models/zh_CN-huayan-medium.onnx -f {out} < {text}",
        "",
        "# 口型对齐（可选；不配则口型走估算，对话不受影响）",
        "# BILIN_ALIGN_CMD=",
        "",
        "HOST=127.0.0.1",
        "PORT=8000",
        "LOG_LEVEL=info",
        "DATABASE_URL=sqlite:///data/bilin.db",
        "CORS_ORIGINS=",
        "AUTH_MODE=required",
        "API_TOKENS=",
        "",
    ])


def snapshot_sqlite(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default=r"E:\比邻AI\server")
    parser.add_argument("--out", default=r"E:\UI\.uni-shot\upload")
    parser.add_argument("--token", default="", help="不给则自动生成")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = Path(args.server)
    out = Path(args.out)
    stage = out / "bilin-upload"
    archive = out / "bilin-upload.tar.gz"

    if not (server / ".env").exists():
        raise SystemExit("找不到 %s（没有它就没有密钥）" % (server / ".env"))

    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    token = args.token
    if not token:
        import secrets
        token = secrets.token_hex(32)
    print("  接口 token: %s…%s" % (token[:12], token[-4:]))

    env = read_env(server)

    # ① 生产 .env + 两套模板
    (stage / ".env").write_text(build_runtime_env(env, token, args.host), encoding="utf-8", newline="\n")
    (stage / "env.profile-cloud").write_text(profile_cloud(env), encoding="utf-8", newline="\n")
    (stage / "env.profile-local").write_text(profile_local(), encoding="utf-8", newline="\n")
    print("  已生成 .env + 两套模板（云端 API / 完全本地）")

    # ② 部署脚本副本（连不上 GitHub 时可用）
    deploy_src = server / "deploy"
    copied = 0
    for name in DEPLOY_ITEMS:
        src = deploy_src / name
        if not src.exists():
            continue
        dst = stage / "zerotier" / name if name == "zerotier" else stage / name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            copied += len(list(dst.rglob("*")))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
    print("  已带上部署脚本 %d 项" % copied)

    # ③ 数据（SQLite 用一致性快照）
    for name in DATA_ITEMS:
        src = server / name
        if not src.exists():
            continue
        if name == "data":
            target = stage / "data"
            target.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                if item.name.startswith("bilin.db"):
                    continue
                dest = target / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)
            snapshot_sqlite(src / "bilin.db", target / "bilin.db")
            print("  data/ 已打包（数据库用 backup() 快照）")
        else:
            shutil.copytree(src, stage / name, dirs_exist_ok=True)
            print("  %s/ 已打包（%d 项）" % (name, len(list((stage / name).rglob("*")))))

    # ④ install.sh
    install = stage / "install.sh"
    install.write_text(INSTALL_SH, encoding="utf-8", newline="\n")

    # ⑤ 快照自检
    db = stage / "data" / "bilin.db"
    if db.exists():
        conn = sqlite3.connect(db)
        accounts = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn.close()
        print("  快照校验：accounts %d / messages %d" % (accounts, messages))

    # ⑥ 打包（脚本要可执行）
    out.mkdir(parents=True, exist_ok=True)

    def _mode(member: tarfile.TarInfo) -> tarfile.TarInfo:
        """统一权限：.sh 可执行，其余常规。

        ⚠️ 必须用 filter —— `tar.add()` 之后再改 `TarInfo.mode` **不会重写头部**。
        实测过：改完解包出来仍是 rw-rw-rw-，install.sh 没法直接执行。
        """
        member.mode = 0o755 if member.name.endswith(".sh") else 0o644
        return member

    with tarfile.open(archive, "w:gz") as tar:
        for item in sorted(stage.iterdir()):
            tar.add(item, arcname=item.name, filter=_mode)

    meta = {
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "size_mb": round(archive.stat().st_size / 1024 / 1024, 2),
        "token_masked": token[:8] + "…" + token[-4:],
        "host": args.host,
    }
    (out / "bundle-meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n  一键包：%s（%.2f MB）" % (archive, meta["size_mb"]))
    print("  ⚠️ 含老人健康数据与 API 密钥，上传后请删除本机副本")


if __name__ == "__main__":
    main()
