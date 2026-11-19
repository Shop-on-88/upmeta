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

# 홈페이지 추가 페이지: 저장소 site/ 폴더 -> /var/www/upmeta (새 파일 추가·변경만, 기존 파일 삭제 없음)
W=/var/www/upmeta
if [ -d "$R/site" ] && [ -d "$W" ]; then
  while IFS= read -r f; do
    cmp -s "site/$f" "$W/$f" && continue
    mkdir -p "$W/$(dirname "$f")" && cp "site/$f" "$W/$f" && chmod 644 "$W/$f" && log "SITE $f ($MSG)"
  done < <(cd site && find . -type f | sed 's#^\./##' | sort)
fi

# ----- 업무 보드: 저장소 board/ -> /root/upmeta/board (UP META 폴더 안, 다른 사업과 무관)
BD=/root/upmeta/board
BHOST=board.upmeta.online
BCONF=/etc/nginx/conf.d/upmeta-board.conf
BPORT=18473
BSVC=upmeta-board
if [ -d "$R/board" ] && [ ! -f $X/board.skip ]; then
  mkdir -p $BD; bch=0; bok=1
  python3 -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" board/app.py 2>>"$LOG" || bok=0
  if [ $bok = 1 ] && [ ! -f /etc/systemd/system/$BSVC.service ]; then
    if ss -ltn 2>/dev/null | grep -q ":$BPORT "; then
      bok=0; touch $X/board.skip; log "BOARD port $BPORT busy"; notify "⚠️ UP META 업무 보드를 켜지 못했어요 (포트 $BPORT 사용 중)"
    else
      cat > /etc/systemd/system/$BSVC.service <<S
[Unit]
Description=UP META task board ($BHOST)
After=network-online.target
[Service]
WorkingDirectory=$BD
EnvironmentFile=-$D/.env
Environment=PORT=$BPORT BOARD_URL=https://$BHOST PYTHONUNBUFFERED=1
ExecStart=/usr/bin/env python3 $BD/app.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
S
      systemctl daemon-reload; systemctl enable -q $BSVC; bch=1
    fi
  fi
  if [ $bok = 1 ]; then
    mkdir -p $BD/prev
    [ -f $BD/chat_id ] || echo "-5467374222" > $BD/chat_id   # 업무 보드 알림을 받는 텔레그램 그룹
    for f in app.py index.html; do
      cmp -s "board/$f" "$BD/$f" && continue
      [ -f "$BD/$f" ] && cp -p "$BD/$f" "$BD/prev/$f"
      cp "board/$f" "$BD/$f"; bch=1
    done
    if [ $bch = 1 ]; then
      systemctl restart $BSVC; sleep 4
      if systemctl is-active -q $BSVC; then
        log "BOARD OK ($MSG)"; notify "✅ UP META 업무 보드 업데이트 완료
$MSG"
      else
        for f in app.py index.html; do [ -f "$BD/prev/$f" ] && cp -p "$BD/prev/$f" "$BD/$f"; done
        systemctl restart $BSVC
        log "BOARD ROLLBACK ($MSG)"; notify "⚠️ UP META 업무 보드 새 버전이 안 켜져서 원래대로 되돌렸어요
$(journalctl -u $BSVC -n 6 --no-pager -o cat | tail -c 500)"
      fi
    fi
    # 접속 주소 연결 (새 설정 파일 하나만 추가 — 기존 홈페이지·다른 사업 설정은 건드리지 않음)
    if [ ! -f "$BCONF" ] && command -v nginx >/dev/null && [ -d /etc/nginx/conf.d ]; then
      cat > "$BCONF" <<'S'
server {
    listen 80;
    listen [::]:80;
    server_name board.upmeta.online;
    client_max_body_size 1m;
    location / {
        proxy_pass http://127.0.0.1:18473;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 1h;
    }
}
S
      if nginx -t >>"$LOG" 2>&1; then systemctl reload nginx; log "BOARD nginx OK"
      else rm -f "$BCONF"; log "BOARD nginx FAIL"; notify "⚠️ UP META 업무 보드 주소 연결 설정에 실패했어요 (기존 사이트는 그대로)"; fi
    fi
    # HTTPS 인증서: 도메인이 서버로 연결되면 자동 발급 (10분마다 확인, 발급되면 꺼짐)
    cmp -s board/cert.sh $X/board-cert.sh || { cp board/cert.sh $X/board-cert.sh; chmod +x $X/board-cert.sh; }
    if [ -f "$BCONF" ] && [ ! -d /etc/letsencrypt/live/$BHOST ] && [ ! -f /etc/systemd/system/upmeta-board-cert.timer ]; then
      cat > /etc/systemd/system/upmeta-board-cert.service <<S
[Unit]
Description=UP META task board certificate
[Service]
Type=oneshot
ExecStart=/bin/bash $X/board-cert.sh
S
      cat > /etc/systemd/system/upmeta-board-cert.timer <<S
[Unit]
Description=UP META task board certificate check
[Timer]
OnBootSec=120
OnUnitActiveSec=600
[Install]
WantedBy=timers.target
S
      systemctl daemon-reload; systemctl enable -q --now upmeta-board-cert.timer
      /bin/bash $X/board-cert.sh
    fi
  fi
fi

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
