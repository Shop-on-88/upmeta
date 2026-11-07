# UP META (Shop-on-88/upmeta)

UP META 데모봇(@metaupdemo_bot) 코드. `app/` 파일을 main에 올리면 서버(/root/upmeta/demo-bot)가 1분 안에 자동 적용합니다.

- 적용: `/root/upmeta/.deploy/deploy.sh` (systemd 타이머 `upmeta-deploy.timer`, 1분마다)
- 실패하면 자동으로 이전 버전으로 되돌리고 사장님 텔레그램으로 알림
- 다른 사업(B2, 베스트여행사, 이지코리아) 파일은 건드리지 않음
- 스티커·이모지 파일(assets/)과 .env 는 서버에만 있음 (저장소에 올리지 않음)
