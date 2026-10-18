#!/usr/bin/env bash
#
# 比邻AI 后端一键部署（Ubuntu / Debian）
#
# 用法（在服务器上，仓库根目录执行）：
#   sudo bash server/deploy/deploy.sh
#
# 它做这些事：
#   1. 检查环境（Python 版本、是否已在正确目录）
#   2. 建系统用户 bilin（不给登录 shell，最小权限）
#   3. 代码放到 /opt/bilin，建 venv 装依赖
#   4. 建数据目录并**从旧位置迁移已有数据**（账号、聊天记录、病例文件）
#   5. 生成 /etc/bilin/bilin.env（密钥 600 权限）
#   6. 装 systemd 服务并启动
#   7. 自检（/healthz 能否通）
#
# 不装 Nginx/Caddy —— 反向代理单独做（见 README.md），
# 因为那一步涉及域名，必须人工确认。

set -Eeuo pipefail

APP_USER="bilin"
APP_DIR="/opt/bilin"
DATA_DIR="/opt/bilin/server"
ENV_DIR="/etc/bilin"
ENV_FILE="${ENV_DIR}/bilin.env"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_SERVER="${REPO_ROOT}/server"

log()  { printf '\033[32m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\033[33m[警告]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[失败]\033[0m %s\n' "$*" >&2; exit 1; }

# ── 0. 前置检查 ──────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "请用 root 执行：sudo bash server/deploy/deploy.sh"
[[ -d "${SRC_SERVER}" ]] || die "找不到 ${SRC_SERVER}，请在仓库根目录执行"
command -v python3 >/dev/null || die "没装 python3"

# 代码里用了 match 语句（Python 3.10+），3.11 起更稳
PY_VER=$(python3 -c 'import sys; print("%d%02d" % sys.version_info[:2])')
if (( PY_VER < 311 )); then
  die "需要 Python 3.11+，当前是 $(python3 -V 2>&1)。先装新版：apt install python3.11 python3.11-venv"
fi
log "Python $(python3 -V 2>&1) 满足要求"

# ── 1. 系统依赖 ──────────────────────────────────────────────────
log "安装系统依赖"
apt-get update -qq
# python3-venv 必需；其余是编译/证书相关
apt-get install -y -qq python3-venv python3-dev build-essential curl ca-certificates >/dev/null
log "系统依赖就绪"

# ── 2. 系统用户 ──────────────────────────────────────────────────
if id -u "${APP_USER}" >/dev/null 2>&1; then
  log "用户 ${APP_USER} 已存在"
else
  log "创建系统用户 ${APP_USER}（不可登录）"
  # --no-create-home：它不需要 home 目录；--shell /usr/sbin/nologin：禁止登录
  useradd --system --no-create-home --shell /usr/sbin/nologin "${APP_USER}"
fi

# ── 3. 代码 ──────────────────────────────────────────────────────
log "部署代码到 ${APP_DIR}"
mkdir -p "${APP_DIR}"
# 用 rsync 而不是 cp：能保留已有数据目录不被覆盖，且支持增量
if command -v rsync >/dev/null; then
  # --exclude 的东西：
  #   .venv        本地虚拟环境，服务器要重建（平台不同）
  #   data         运行数据，单独迁移（见第 4 步）
  #   case_files   病例文件，单独迁移
  #   __pycache__  无意义
  rsync -a --delete \
    --exclude '.venv' --exclude 'data' --exclude 'case_files' \
    --exclude '__pycache__' --exclude '*.pyc' --exclude '_voice_samples' \
    "${SRC_SERVER}/" "${APP_DIR}/server/"
else
  warn "没有 rsync，改用 cp（不删旧文件，可能留残留）"
  mkdir -p "${APP_DIR}/server"
  cp -r "${SRC_SERVER}/." "${APP_DIR}/server/"
  rm -rf "${APP_DIR}/server/.venv"
fi

# 静态目录：main.py 会按 is_dir() 判断是否挂载 /family 与 /uni-app/api
# 不存在只是不挂载，不会崩；但如果 H5 也要从这台机器提供，就把它带上
if [[ -d "${REPO_ROOT}/uni-app" ]]; then
  mkdir -p "${APP_DIR}/uni-app"
  rsync -a --delete \
    --exclude 'node_modules' --exclude 'unpackage' --exclude '__pycache__' \
    "${REPO_ROOT}/uni-app/" "${APP_DIR}/uni-app/" 2>/dev/null || \
    cp -r "${REPO_ROOT}/uni-app/." "${APP_DIR}/uni-app/"
  log "已带上 uni-app（供 /uni-app/api 静态挂载）"
fi

# ── 4. 数据迁移（只补不覆盖，防止把线上数据冲掉）──────────────────
log "准备数据目录"
mkdir -p "${DATA_DIR}/data" "${DATA_DIR}/case_files" "${DATA_DIR}/_voice_samples"

migrate_dir() {
  local name="$1"
  if [[ -d "${SRC_SERVER}/${name}" ]] && [[ -n "$(ls -A "${SRC_SERVER}/${name}" 2>/dev/null || true)" ]]; then
    if [[ -n "$(ls -A "${DATA_DIR}/${name}" 2>/dev/null || true)" ]]; then
      warn "${name} 目标已非空，跳过迁移（避免覆盖线上数据）"
    else
      log "迁移 ${name}"
      cp -r "${SRC_SERVER}/${name}/." "${DATA_DIR}/${name}/"
    fi
  fi
}
migrate_dir data
migrate_dir case_files
migrate_dir _voice_samples

# ── 5. 虚拟环境 ──────────────────────────────────────────────────
if [[ ! -x "${DATA_DIR}/.venv/bin/python" ]]; then
  log "创建虚拟环境并安装依赖"
  python3 -m venv "${DATA_DIR}/.venv"
  "${DATA_DIR}/.venv/bin/pip" install --upgrade pip -q
  "${DATA_DIR}/.venv/bin/pip" install -r "${DATA_DIR}/requirements.txt" -q
else
  log "虚拟环境已存在，更新依赖"
  "${DATA_DIR}/.venv/bin/pip" install -r "${DATA_DIR}/requirements.txt" -q
fi
log "依赖安装完成"

# ── 6. 配置与密钥 ────────────────────────────────────────────────
mkdir -p "${ENV_DIR}"
if [[ -f "${ENV_FILE}" ]]; then
  log "${ENV_FILE} 已存在，保留原内容（不覆盖密钥）"
else
  log "生成 ${ENV_FILE}"
  # 从仓库里的 .env 复制，但强制改掉三个对外/安全相关的值：
  #   HOST=127.0.0.1   后端不直接暴露公网，只让 Nginx/Caddy 转发
  #   CORS_ORIGINS     不要留 *
  #   LOG_LEVEL        生产用 info
  if [[ -f "${SRC_SERVER}/.env" ]]; then
    sed -e 's/^HOST=.*/HOST=127.0.0.1/' \
        -e 's/^LOG_LEVEL=.*/LOG_LEVEL=info/' \
        "${SRC_SERVER}/.env" > "${ENV_FILE}"
  else
    # 仓库里没有 .env（.gitignore 忽略它）时，生成一份最小可用的
    cat > "${ENV_FILE}" <<'EOF'
LLM_PROVIDER=auto
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=
LLM_MODEL=deepseek-chat
HOST=127.0.0.1
PORT=8000
CORS_ORIGINS=*
LOG_LEVEL=info
DATABASE_URL=sqlite:///data/bilin.db
BILIN_TTS_PROVIDER=qwen
EOF
  fi
  chmod 600 "${ENV_FILE}"
  warn "请立刻编辑 ${ENV_FILE} 填好 LLM_API_KEY / DASHSCOPE_API_KEY，并收紧 CORS_ORIGINS"
fi

# 权限：代码归 root（进程只读），数据目录归 bilin（可写）
chown -R root:root "${APP_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${DATA_DIR}/data" "${DATA_DIR}/case_files" "${DATA_DIR}/_voice_samples"
chmod 600 "${ENV_FILE}"
log "权限已设置"

# ── 7. systemd ───────────────────────────────────────────────────
log "安装 systemd 服务"
cp "${DATA_DIR}/deploy/bilin-api.service" /etc/systemd/system/bilin-api.service
systemctl daemon-reload
systemctl enable bilin-api >/dev/null 2>&1 || true
systemctl restart bilin-api
sleep 3

# ── 8. 自检 ──────────────────────────────────────────────────────
log "自检"
if ! systemctl is-active --quiet bilin-api; then
  warn "服务没起来，最近日志："
  journalctl -u bilin-api -n 40 --no-pager || true
  die "启动失败，请看上面的日志"
fi

# 等端口真正可用（uvicorn 启动有一两秒延迟）
for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then break; fi
  sleep 1
done

if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
  log "健康检查通过："
  curl -s http://127.0.0.1:8000/healthz | head -c 400; echo
  echo
  log "部署完成。接下来做反向代理与 HTTPS（见 server/deploy/README.md）"
  echo "   systemctl status bilin-api      # 看状态"
  echo "   journalctl -u bilin-api -f      # 看日志"
else
  warn "健康检查失败，最近日志："
  journalctl -u bilin-api -n 40 --no-pager || true
  die "服务起来了但接口不通，请检查 ${ENV_FILE}"
fi
