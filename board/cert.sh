#!/bin/bash
# UP META 업무 보드(board.upmeta.online) HTTPS 인증서 자동 발급
# 도메인이 이 서버로 연결될 때까지 10분마다 확인하고, 발급되면 스스로 꺼짐. 업무 보드 설정 파일만 건드림.
set -u
X=/root/upmeta/.deploy
D=/root/upmeta/demo-bot
BD=/root/upmeta/board
BHOST=board.upmeta.online
BCONF=/etc/nginx/conf.d/upmeta-board.conf
LOG=$X/deploy.log
OWNER=2103748907
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
notify() {
  local tok; tok=$(grep -E '^BOT_TOKEN=' $D/.env | head -1 | cut -d= -f2- | tr -d '"'"'"'\r')
  [ -n "$tok" ] && curl -s -m 15 "https://api.telegram.org/bot$tok/sendMessage" \
    --data-urlencode "chat_id=$OWNER" --data-urlencode "text=$1" >/dev/null 2>&1
}
[ -f "$BCONF" ] || exit 0
if [ -d /etc/letsencrypt/live/$BHOST ]; then systemctl disable -q --now upmeta-board-cert.timer; exit 0; fi
command -v certbot >/dev/null || exit 0
ip=$(getent ahostsv4 $BHOST | awk 'NR==1{print $1}')
me=$(getent ahostsv4 upmeta.online | awk 'NR==1{print $1}')
[ -n "$ip" ] && [ "$ip" = "$me" ] || exit 0
cp -p "$BCONF" $X/board.conf.bak
if certbot --nginx -n -d $BHOST --redirect >>"$LOG" 2>&1 && nginx -t >>"$LOG" 2>&1; then
  systemctl reload nginx; log "BOARD cert OK"
  code=$(cat $BD/setup_code 2>/dev/null)
  notify "✅ UP META 업무 보드 주소가 열렸어요
https://$BHOST${code:+
처음 들어가서 관리자 계정을 만들 때 쓰는 설정 코드: $code}"
  systemctl disable -q --now upmeta-board-cert.timer
else
  cp -p $X/board.conf.bak "$BCONF"; nginx -t >>"$LOG" 2>&1 && systemctl reload nginx
  log "BOARD cert FAIL"
fi
