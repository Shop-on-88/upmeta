#!/bin/bash
# UP META 데모봇 자동 적용 설정 (처음 한 번만 실행)
# 이후 Claude가 GitHub(Shop-on-88/upmeta)에 올리면 1분 안에 서버에 자동 적용됩니다. UP META 폴더만 건드립니다.
set -e
X=/root/upmeta/.deploy
mkdir -p $X
command -v git >/dev/null || apt-get install -y git
if [ -d $X/repo/.git ]; then git -C $X/repo fetch -q origin main && git -C $X/repo reset -q --hard origin/main
else rm -rf $X/repo; git clone -q https://github.com/Shop-on-88/upmeta.git $X/repo; fi
cp $X/repo/deploy.sh $X/deploy.sh && chmod +x $X/deploy.sh
cat > /etc/systemd/system/upmeta-deploy.service <<S
[Unit]
Description=UP META auto deploy (GitHub Shop-on-88/upmeta)
[Service]
Type=oneshot
ExecStart=/bin/bash /root/upmeta/.deploy/deploy.sh
S
cat > /etc/systemd/system/upmeta-deploy.timer <<S
[Unit]
Description=UP META auto deploy every minute
[Timer]
OnBootSec=60
OnUnitActiveSec=60
[Install]
WantedBy=timers.target
S
systemctl daemon-reload
systemctl enable --now upmeta-deploy.timer >/dev/null
grep -q '^OWNER_IDS=' /root/upmeta/demo-bot/.env 2>/dev/null || echo 'OWNER_IDS=2103748907' >> /root/upmeta/demo-bot/.env
bash $X/deploy.sh --force
tail -2 $X/deploy.log 2>/dev/null
echo "✅ 자동 적용 설정 완료 - 앞으로는 이 작업 필요 없어요"
