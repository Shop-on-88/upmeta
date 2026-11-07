#!/bin/bash
# UP META 데모봇 자동 적용: GitHub(Shop-on-88/upmeta)의 app/ 파일을 서버에 반영 (1분마다 확인)
# UP META 폴더(/root/upmeta/demo-bot)만 건드림 - 다른 사업 파일과 무관
set -u
D=/root/upmeta/demo-bot
X=/root/upmeta/.deploy
R=$X/repo
LOG=$X/deploy.log
OWNER=2103748907
SVC=upmeta-demo-bot
export GIT_TERMINAL_PROMPT=0
exec 9>$X/lock; flock -n 9 || exit 0
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
notify() {
  local tok; tok=$(grep -E '^BOT_TOKEN=' $D/.env | head -1 | cut -d= -f2- | tr -d '"'"'"'\r')
  [ -n "$tok" ] && curl -s -m 15 "https://api.telegram.org/bot$tok/sendMessage" \
    --data-urlencode "chat_id=$OWNER" --data-urlencode "text=$1" >/dev/null 2>&1
}

cd "$R" || exit 0
git fetch -q origin main 2>>"$LOG" || exit 0
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && [ "${1:-}" != "--force" ] && exit 0
git reset -q --hard origin/main
MSG=$(git log -1 --pretty=%s)

# 이 파일(deploy.sh)도 저장소 최신으로 교체 (다음 실행부터 적용)
cmp -s "$R/deploy.sh" "$X/deploy.sh" || cp "$R/deploy.sh" "$X/deploy.sh"

changed=()
while IFS= read -r f; do
  cmp -s "app/$f" "$D/$f" || changed+=("$f")
done < <(cd app && find . -type f ! -path '*/__pycache__/*' | sed 's#^\./##' | sort)
[ ${#changed[@]} -eq 0 ] && { log "no app change ($MSG)"; exit 0; }

PY=$D/venv/bin/python; [ -x "$PY" ] || PY=python3
for f in "${changed[@]}"; do
  case "$f" in *.py)
    if ! "$PY" -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" "app/$f" 2>>"$LOG"; then
      log "FAIL syntax $f ($MSG)"; notify "❌ UP META 데모봇 업데이트 중단 (파일 오류: $f) - 기존 버전 그대로 동작 중"; exit 0
    fi;;
  esac
done
BK=$D/backup/auto_$(date +%Y%m%d%H%M%S); mkdir -p "$BK"; : > "$BK/.new"
for f in "${changed[@]}"; do
  if [ -f "$D/$f" ]; then mkdir -p "$BK/$(dirname "$f")"; cp -p "$D/$f" "$BK/$f"; else echo "$f" >> "$BK/.new"; fi
  mkdir -p "$D/$(dirname "$f")"; cp "app/$f" "$D/$f"
done
systemctl restart $SVC; sleep 8
if systemctl is-active -q $SVC; then
  log "OK ${changed[*]} ($MSG)"; notify "✅ UP META 데모봇 업데이트 완료
$MSG"
else
  for f in "${changed[@]}"; do [ -f "$BK/$f" ] && cp -p "$BK/$f" "$D/$f"; done
  while IFS= read -r f; do [ -n "$f" ] && rm -f "$D/$f"; done < "$BK/.new"
  systemctl restart $SVC
  ERR=$(journalctl -u $SVC -n 8 --no-pager -o cat | tail -c 600)
  log "ROLLBACK ${changed[*]} ($MSG)"; notify "⚠️ UP META 데모봇 새 버전이 안 켜져서 원래대로 되돌렸어요
$MSG
$ERR"
fi
