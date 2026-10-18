#!/usr/bin/env bash
#
# 配 HTTPS（自动申请证书）+ 装反向代理
#
# 用法：
#   sudo bash server/deploy/setup-proxy.sh api.example.com nginx
#   sudo bash server/deploy/setup-proxy.sh api.example.com caddy
#
# 参数：
#   $1 域名（必须已经解析到这台服务器的公网 IP，否则证书签不下来）
#   $2 用哪个反代：nginx（默认）或 caddy

set -Eeuo pipefail

DOMAIN="${1:-}"
KIND="${2:-nginx}"

log()  { printf '\033[32m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\033[33m[警告]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[失败]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "请用 root 执行"
[[ -n "${DOMAIN}" ]] || die "用法：sudo bash $0 <域名> [nginx|caddy]"

# 域名必须已解析到本机，否则 ACME 验证一定失败（这是最常见的失败原因）
log "检查 ${DOMAIN} 是否解析到本机"
PUBLIC_IP=$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || echo "")
DNS_IP=$(getent hosts "${DOMAIN}" 2>/dev/null | awk '{print $1; exit}' || echo "")
if [[ -z "${DNS_IP}" ]]; then
  die "${DOMAIN} 没有解析记录。请先到域名服务商加一条 A 记录指向 ${PUBLIC_IP:-本机公网IP}"
fi
if [[ -n "${PUBLIC_IP}" && "${DNS_IP}" != "${PUBLIC_IP}" ]]; then
  warn "${DOMAIN} 解析到 ${DNS_IP}，但本机公网 IP 是 ${PUBLIC_IP} —— 证书可能签不下来"
  warn "如果用了 CDN/负载均衡则属正常，可继续"
fi
log "解析 OK：${DOMAIN} → ${DNS_IP}"

# 80/443 必须放行
if command -v ufw >/dev/null && ufw status | grep -q active; then
  log "放行 ufw 的 80/443"
  ufw allow 80/tcp  >/dev/null
  ufw allow 443/tcp >/dev/null
fi

TEMPLATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${KIND}" == "caddy" ]]; then
  # ── Caddy：自动 HTTPS，最省事 ────────────────────────────────
  log "安装 Caddy"
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl >/dev/null
  if ! command -v caddy >/dev/null; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    apt-get update -qq
    apt-get install -y -qq caddy >/dev/null
  fi

  log "写入 Caddyfile（域名 ${DOMAIN}）"
  mkdir -p /var/log/caddy
  chown caddy:caddy /var/log/caddy 2>/dev/null || true
  # 用真实域名和邮箱替换模板占位符
  sed -e "s/api\.example\.com/${DOMAIN}/g" \
      -e "s/you@example\.com/admin@${DOMAIN}/g" \
      "${TEMPLATE_DIR}/Caddyfile" > /etc/caddy/Caddyfile

  log "校验并启动"
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null || die "Caddyfile 校验失败"
  systemctl restart caddy
  sleep 5

  if systemctl is-active --quiet caddy; then
    log "Caddy 已启动"
  else
    warn "Caddy 没起来："
    journalctl -u caddy -n 30 --no-pager || true
    die "请检查上面日志（多半是证书申请失败，常见原因是域名没解析或 80 端口被占）"
  fi

else
  # ── Nginx + certbot ─────────────────────────────────────────
  log "安装 Nginx 与 certbot"
  apt-get install -y -qq nginx certbot python3-certbot-nginx >/dev/null

  log "先只用 HTTP 配置（否则证书文件还不存在，nginx 会启动失败）"
  # 这是关键顺序：certbot 需要 80 端口能访问来验证域名，
  # 但 443 那段配置引用的证书文件此时还不存在 ——
  # 直接上完整配置会导致 nginx -t 失败。
  cat > /etc/nginx/sites-available/bilin <<EOF
server {
    listen 80;
    server_name ${DOMAIN};
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  mkdir -p /var/www/html
  ln -sf /etc/nginx/sites-available/bilin /etc/nginx/sites-enabled/bilin
  # 移除默认站点，避免它抢走 80 端口的默认响应
  rm -f /etc/nginx/sites-enabled/default
  nginx -t || die "nginx 配置有问题"
  systemctl reload nginx

  log "申请证书"
  if certbot certonly --nginx -d "${DOMAIN}" --non-interactive --agree-tos \
       --register-unsafely-without-email --keep-until-expiring; then
    log "证书申请成功"
  else
    warn "certbot 申请失败。常见原因：域名未解析、80 端口被占用、或频率限制"
    warn "可手动重试：certbot certonly --nginx -d ${DOMAIN}"
    die "HTTPS 未配置完成"
  fi

  log "换成完整的 HTTPS 配置"
  sed "s/api\.example\.com/${DOMAIN}/g" "${TEMPLATE_DIR}/nginx-bilin.conf" \
      > /etc/nginx/sites-available/bilin
  nginx -t || die "HTTPS 配置校验失败"
  systemctl reload nginx

  # certbot 的续期钩子：续完自动 reload nginx
  if [[ -d /etc/letsencrypt/renewal-hooks/deploy ]]; then
    echo '#!/bin/sh
systemctl reload nginx' > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
    chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
    log "已配置续期后自动 reload"
  fi
fi

# ── 验收 ────────────────────────────────────────────────────────
log "验收（从公网地址访问）"
sleep 2
if curl -fsS --max-time 15 "https://${DOMAIN}/healthz" >/dev/null 2>&1; then
  log "HTTPS 通了："
  curl -s --max-time 10 "https://${DOMAIN}/healthz" | head -c 300; echo
else
  warn "https://${DOMAIN}/healthz 不通"
  warn "排查顺序：1) 后端在不在（systemctl status bilin-api）"
  warn "          2) 反代在不在（systemctl status nginx|caddy）"
  warn "          3) 防火墙 443（ufw status / 云厂商安全组）"
  die "验收失败"
fi

echo
log "全部完成。现在把这个地址填进 App："
echo "   编辑 uni-app/.env.production"
echo "   VITE_API_BASE_URL=https://${DOMAIN}"
echo "   然后重新打包 APK（HBuilderX → 发行 → 云打包）"
