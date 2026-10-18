#!/usr/bin/env bash
#
# 备份比邻AI 的运行数据
#
# 用法：
#   sudo bash server/deploy/backup.sh [备份目录]
#   默认备份到 /var/backups/bilin
#
# ⚠️ 为什么不能直接 cp bilin.db：
#    SQLite 在写入过程中，磁盘上的文件可能是"半新半旧"的状态，
#    直接复制会得到**损坏的数据库**。必须用 `sqlite3 .backup`（在线备份，
#    会自动处理锁与一致性），或用 VACUUM INTO。
#    这个脚本优先用 .backup，没有 sqlite3 命令时退回 VACUUM INTO。
set -Eeuo pipefail

DATA_DIR="/opt/bilin/server"
BACKUP_ROOT="${1:-/var/backups/bilin}"
STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="${BACKUP_ROOT}/${STAMP}"
KEEP_DAYS="${BILIN_BACKUP_KEEP_DAYS:-14}"

log()  { printf '\033[32m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\033[33m[警告]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[失败]\033[0m %s\n' "$*" >&2; exit 1; }

[[ -d "${DATA_DIR}" ]] || die "找不到 ${DATA_DIR}"

mkdir -p "${TARGET}"

# ── 1. 数据库（在线安全备份）─────────────────────────────────────
DB="${DATA_DIR}/data/bilin.db"
if [[ -f "${DB}" ]]; then
  log "备份数据库"
  if command -v sqlite3 >/dev/null; then
    sqlite3 "${DB}" ".backup '${TARGET}/bilin.db'"
  else
    warn "没装 sqlite3，改用 VACUUM INTO（效果相同）"
    warn "建议装一下：apt install sqlite3（后续备份更快）"
    "${DATA_DIR}/.venv/bin/python" - "${DB}" "${TARGET}/bilin.db" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
con = sqlite3.connect(src)
# VACUUM INTO 生成一个干净、一致的副本
con.execute("VACUUM INTO ?", (dst,))
con.close()
PY
  fi
  # 立即验证备份是否真的可用 —— 备份不验证等于没备份
  if command -v sqlite3 >/dev/null; then
    ok=$(sqlite3 "${TARGET}/bilin.db" "PRAGMA integrity_check;" || echo "fail")
    [[ "${ok}" == "ok" ]] || die "备份出来的数据库损坏（integrity_check=${ok}）"
    accounts=$(sqlite3 "${TARGET}/bilin.db" "SELECT COUNT(*) FROM accounts;" 2>/dev/null || echo "?")
    log "数据库备份校验通过（integrity_check=ok，账号 ${accounts} 个）"
  fi
else
  warn "没有找到 ${DB}，跳过数据库"
fi

# ── 2. 模型配置（含明文 API KEY，权限要收紧）───────────────────────
if [[ -f "${DATA_DIR}/data/llm_overrides.json" ]]; then
  cp "${DATA_DIR}/data/llm_overrides.json" "${TARGET}/"
  chmod 600 "${TARGET}/llm_overrides.json"
  log "已备份 llm_overrides.json（含密钥，权限 600）"
fi

# ── 3. 病例文件 ──────────────────────────────────────────────────
if [[ -d "${DATA_DIR}/case_files" ]] && [[ -n "$(ls -A "${DATA_DIR}/case_files" 2>/dev/null || true)" ]]; then
  tar -czf "${TARGET}/case_files.tar.gz" -C "${DATA_DIR}" case_files
  log "已备份病例文件（$(tar -tzf "${TARGET}/case_files.tar.gz" | wc -l) 个文件）"
fi

# ── 4. 配置（密钥单独标记）───────────────────────────────────────
if [[ -f /etc/bilin/bilin.env ]]; then
  cp /etc/bilin/bilin.env "${TARGET}/bilin.env"
  chmod 600 "${TARGET}/bilin.env"
  log "已备份 bilin.env（含密钥，权限 600）"
fi

# ── 5. 清理旧备份 ────────────────────────────────────────────────
if [[ -d "${BACKUP_ROOT}" ]]; then
  find "${BACKUP_ROOT}" -maxdepth 1 -type d -mtime +"${KEEP_DAYS}" -exec rm -rf {} \; 2>/dev/null || true
fi

SIZE=$(du -sh "${TARGET}" | cut -f1)
log "备份完成：${TARGET}（${SIZE}）"
echo
echo "建议加到 crontab 每天凌晨 3 点自动备份："
echo "  sudo crontab -e"
echo "  0 3 * * * bash /opt/bilin/server/deploy/backup.sh >/var/log/bilin-backup.log 2>&1"
echo
echo "⚠️ 备份里含明文 API KEY 与健康数据，记得："
echo "   1. 定期把备份拷到别的机器（本机备份救不了硬盘损坏）"
echo "   2. 不要把这些备份放进公开的网盘/仓库"
