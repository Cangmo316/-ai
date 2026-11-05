#!/usr/bin/env bash
# 比邻AI · 私有化部署（Linux 服务器 + ZeroTier）
#
#   sudo bash setup-linux.sh --network <ZeroTier网络ID>
#
# 它做这些事：
#   1. 装 ZeroTier 并加入你的网络，等它拿到 10.x.x.x 地址
#   2. 装系统依赖（git / python3-venv / rsync）
#   3. 拉代码（公开仓库）→ 跑已有的 deploy/deploy.sh（建用户、venv、systemd、数据迁移）
#   4. 把后端**只绑定到 ZeroTier 地址**，公网端口一个都不开
#   5. 防火墙只放行 ZeroTier 网段访问 8000
#   6. 打印「手机上要填的地址」
#
# 为什么只绑 ZeroTier 地址：
#   绑 0.0.0.0 会让同网段的任何设备（含公网，如果误开了端口）都能访问，
#   里面有老人的健康档案、病例、聊天记录 —— 属于敏感个人信息。
#   只绑 ZeroTier 虚拟网卡后，**只有加入同一网络的成员**才能连上。
set -Eeuo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; NC=$'\033[0m'
log()  { echo "${GRN}  ✓${NC} $*"; }
warn() { echo "${YEL}  !${NC} $*"; }
die()  { echo "${RED}  ✗${NC} $*" >&2; exit 1; }

NETWORK=""
PORT="8000"
REPO="${REPO:-https://github.com/Cangmo316/-ai.git}"
SRC_DIR="${SRC_DIR:-/opt/bilin-src}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --network) NETWORK="${2:-}"; shift 2 ;;
    --port)    PORT="${2:-}";    shift 2 ;;
    *) die "未知参数：$1（用法：--network <网络ID> [--port 8000]）" ;;
  esac
done

[[ -n "$NETWORK" ]] || die "必须给 --network <你的 ZeroTier 网络ID>（16 位十六进制）"
[[ $EUID -eq 0 ]] || die "请用 root 跑：sudo bash setup-linux.sh --network $NETWORK"

# ── 1. 基础依赖 ──────────────────────────────────────────────────
log "安装系统依赖"
if command -v apt-get >/dev/null; then
  apt-get update -qq
  apt-get install -y -qq curl ca-certificates gnupg git rsync python3-venv python3-dev build-essential
elif command -v dnf >/dev/null; then
  dnf install -y -q curl ca-certificates git rsync python3 python3-devel gcc make
else
  die "只支持 apt / dnf 系发行版（Ubuntu / Debian / Alibaba Cloud Linux / Rocky）"
fi

# ── 2. 装 ZeroTier ───────────────────────────────────────────────
if ! command -v zerotier-cli >/dev/null; then
  log "安装 ZeroTier"
  curl -fsSL https://install.zerotier.com | bash || die "ZeroTier 安装失败（检查外网/源）"
else
  log "ZeroTier 已安装"
fi

log "加入网络 $NETWORK"
zerotier-cli join "$NETWORK" || warn "join 返回非 0（可能已在网络中）"

# ── 3. 等 ZeroTier 分配地址 + 网络管理员授权 ─────────────────────
# 注意：join 之后必须去 my.zerotier.com 把这个节点勾上 Auth，
# 否则永远拿不到地址。这里最多等 180 秒，超时就明确提示。
log "等待 ZeroTier 分配地址（最多 180 秒）"
ZT_IP=""
for _ in $(seq 1 60); do
  ZT_IP="$(ip -4 addr show 2>/dev/null | grep -oE '10\.[0-9]+\.[0-9]+\.[0-9]+' | grep -v '^10\.0\.2\.' | head -n1 || true)"
  [[ -n "$ZT_IP" ]] && break
  sleep 3
done
if [[ -z "$ZT_IP" ]]; then
  echo
  warn "还没拿到 ZeroTier 地址。请去 my.zerotier.com："
  warn "  Networks → 你的网络 → Members → 勾选刚出现的节点（Auth）"
  warn "  必要的话在 Members 里给它固定一个 IP（Advanced → Managed IPs）"
  warn "授权后重新跑本脚本即可。"
  echo
  zerotier-cli listnetworks || true
  exit 2
fi
log "ZeroTier 地址：$ZT_IP"

# ── 4. 拉代码 ───────────────────────────────────────────────────
log "拉取代码到 $SRC_DIR"
if [[ -d "$SRC_DIR/.git" ]]; then
  git -C "$SRC_DIR" fetch --depth 1 origin main && git -C "$SRC_DIR" reset --hard origin/main
else
  rm -rf "$SRC_DIR"
  git clone --depth 1 "$REPO" "$SRC_DIR"
fi

# ── 5. 复用已有部署脚本 ─────────────────────────────────────────
# deploy.sh 会建 bilin 用户、venv、装依赖、迁数据、装 systemd、跑自检。
# 上云那次卡的 pip 源问题它已经修好（默认走阿里云镜像）。
log "执行主部署脚本"
bash "$SRC_DIR/server/deploy/deploy.sh"

# ── 6. 把后端绑定到 ZeroTier 地址 ───────────────────────────────
ENV_FILE=/etc/bilin/bilin.env
[[ -f "$ENV_FILE" ]] || die "没找到 $ENV_FILE（deploy.sh 可能失败了，先看 systemctl status bilin-api）"

# 只绑 ZeroTier 地址：公网即使误开端口也连不上
sed -i "s|^HOST=.*|HOST=$ZT_IP|" "$ENV_FILE"
grep -q "^HOST=" "$ENV_FILE" || echo "HOST=$ZT_IP" >> "$ENV_FILE"
log "后端将只监听 $ZT_IP:$PORT（公网不可达）"

# ── 7. 鉴权（deploy.sh 已写，缺则补）────────────────────────────
grep -q '^AUTH_MODE=' "$ENV_FILE" || echo "AUTH_MODE=required" >> "$ENV_FILE"
if ! grep -qE '^API_TOKENS=.+' "$ENV_FILE"; then
  TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  echo "API_TOKENS=$TOKEN" >> "$ENV_FILE"
  warn "已生成接口 token（App 端需要，见下方输出）"
fi
chmod 600 "$ENV_FILE"
API_TOKEN="$(grep -E '^API_TOKENS=' "$ENV_FILE" | cut -d= -f2- | cut -d, -f1)"

# ── 8. 防火墙：只放 ZeroTier 网段 ───────────────────────────────
ZT_NET="$(echo "$ZT_IP" | awk -F. '{print $1"."$2"."$3".0/24"}')"
if command -v ufw >/dev/null; then
  log "配置 ufw：仅允许 $ZT_NET 访问 $PORT"
  ufw allow 22/tcp >/dev/null 2>&1 || true
  ufw allow from "$ZT_NET" to any port "$PORT" proto tcp >/dev/null 2>&1 || true
  ufw --force enable >/dev/null 2>&1 || true
elif command -v firewall-cmd >/dev/null; then
  log "配置 firewalld：仅允许 $ZT_NET 访问 $PORT"
  firewall-cmd --permanent --add-service=ssh >/dev/null 2>&1 || true
  firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=$ZT_NET port port=$PORT protocol=tcp accept" >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
else
  warn "没有 ufw/firewalld，请自行确保公网不暴露 $PORT"
fi

# ── 9. 重启并自检 ───────────────────────────────────────────────
log "重启服务"
systemctl restart bilin-api
sleep 3
systemctl is-active --quiet bilin-api || { systemctl status bilin-api --no-pager -l | tail -n 20; die "服务没起来"; }

log "本机自检"
if command -v curl >/dev/null; then
  curl -fsS "http://$ZT_IP:$PORT/healthz" >/dev/null && log "healthz 通过" || warn "healthz 未通过，看日志：journalctl -u bilin-api -n 50"
fi

cat <<EOF

${GRN}================ 部署完成 ================${NC}

  服务器 ZeroTier 地址： ${GRN}http://$ZT_IP:$PORT${NC}
  接口 token：          ${GRN}$API_TOKEN${NC}

  ── 手机上要做的两步 ──
  1. 装 ZeroTier 客户端，加入网络：${GRN}$NETWORK${NC}
     （装完要在 my.zerotier.com 里把这个手机节点也勾上 Auth）
  2. 打开比邻AI → 我的 → 服务器地址 → 填 http://$ZT_IP:$PORT
     → 测试连接 → 保存 → 登录

  ── 常用命令 ──
  systemctl status bilin-api      # 看状态
  journalctl -u bilin-api -f      # 看日志
  zerotier-cli listnetworks       # 看 ZeroTier 状态

  ── 备份（务必配，私有化没有异地容灾）──
  bash $SRC_DIR/server/deploy/backup.sh   # 先手动跑一次确认可用
  然后加进 crontab，例如每天 3:05：
  5 3 * * * bash $SRC_DIR/server/deploy/backup.sh

EOF
