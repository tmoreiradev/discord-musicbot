#!/usr/bin/env bash
# Mantem o jar de cookies do YouTube vivo (cron 4/4h).
#
# Por que isto existe: o Google rotaciona __Secure-1PSIDTS/3PSIDTS a cada uso e
# invalida os valores antigos. O yt-dlp so regrava o arquivo quando recebe
# --cookies apontando para um arquivo em que ele pode escrever. O Muse
# (withTemporaryCookies) copia o jar para um temporario e descarta -- ou seja,
# nunca refresca o original. Sem este script o jar morre sozinho em horas/dias e
# toda faixa passa a falhar com "Sign in to confirm you're not a bot".
#
# O container video-downloader monta o jar read-write, entao e ele quem faz o
# refresh; o resultado volta para o jar canonico do musicbot.
set -u
cd "$(dirname "$0")"

JAR=data/cookies.txt                                   # canonico (Muse)
VD=/path/to/another/yt-dlp/cookies.txt       # copia read-write (refresher)
LOG=warp/cookies-refresh.log
TEST=https://www.youtube.com/watch?v=dQw4w9WgXcQ

docker inspect -f '{{.State.Running}}' video-downloader 2>/dev/null | grep -q true || exit 0

cp "$JAR" "$VD" && chmod 600 "$VD"
if docker exec video-downloader sh -lc "yt-dlp --cookies /app/cookies.txt --simulate --print title '$TEST'" >/dev/null 2>&1; then
  cp "$VD" "$JAR" && chmod 600 "$JAR"
  echo "$(date -Is) refresh OK" >> "$LOG"
else
  echo "$(date -Is) FALHOU - jar provavelmente expirado; re-exportar do browser (see README)" >> "$LOG"
fi
