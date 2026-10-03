#!/usr/bin/env bash
# Vigia do túnel WARP (cron */10): se o YouTube estiver bot-checando o IP de saída,
# rotaciona a identidade wgcf (conta nova, grátis) e reinicia o wireproxy.
# Efeito colateral raro: a rotação derruba a música em reprodução (o stream passa pelo
# túnel) — aceitável, já que sem rotação nada novo tocaria de qualquer forma.
# Log: warp/watchdog.log
set -u
cd "$(dirname "$0")"
LOG=warp/watchdog.log
TEST_URL="https://www.youtube.com/watch?v=dQw4w9WgXcQ"   # 2026-10-01: jNQXAC9IVRw passou a exigir login sem cookie e rotacionava a cada 10 min desde 25/09

# sem o muse rodando não há como (nem por que) testar
docker inspect -f '{{.State.Running}}' muse 2>/dev/null | grep -q true || exit 0

check() {
  docker exec muse /opt/yt-dlp/bin/yt-dlp --simulate --no-playlist --print title "$TEST_URL" >/dev/null 2>&1
}

check && exit 0
sleep 15   # erro transitório (rede, YouTube 5xx) não deve rotacionar
check && exit 0

echo "$(date -Is) bloqueado — rotacionando identidade WARP" >> "$LOG"
cd warp
rm -f wgcf-account.toml
[ -x ./wgcf ] || { curl -sL -o wgcf https://github.com/ViRb3/wgcf/releases/download/v2.2.32/wgcf_2.2.32_linux_$(dpkg --print-architecture) && chmod +x wgcf; }
./wgcf register --accept-tos >/dev/null 2>&1 && ./wgcf generate >/dev/null 2>&1
chmod 600 wgcf-account.toml wgcf-profile.conf
cd ..
docker compose restart wireproxy >/dev/null 2>&1
sleep 5
if check; then
  IP=$(curl -s --max-time 10 --socks5-hostname 127.0.0.1:25344 https://ipinfo.io/json | grep -o '"ip": "[^"]*"')
  echo "$(date -Is) rotação OK ($IP)" >> "$LOG"
else
  echo "$(date -Is) AINDA bloqueado após rotação — intervenção manual (see README)" >> "$LOG"
fi
