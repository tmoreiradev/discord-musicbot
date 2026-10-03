#!/usr/bin/env python3
"""Popula data/play-stats.json (o contador do /top10) com o historico ja postado no Discord.

O Muse nunca guardou o que tocou; a unica memoria sao os embeds "Tocando agora" que o bot
posta no canal do pedido desde 2026-08-08 (patch-announce.sed). Cada embed = uma execucao;
o mesmo video anunciado de novo em menos de 60 s conta uma vez (mesma regra do play-stats.js).

Rodar com o muse PARADO (o container mantem o arquivo em memoria e sobrescreveria):
  docker compose stop muse && ./backfill-play-stats.py <canal> [<canal>...] && docker compose start muse
Soma ao que ja existir no arquivo, entao rodar duas vezes conta em dobro.
"""
import json
import os
import re
import sys
import time

from botlib import HERE, discord, load_env

GUILD = "<guild-id>"
YT = re.compile(r"\*\*\[(.+?)\]\((https://www\.youtube\.com/watch\?v=([\w-]{11}))\)\*\*")


def main():
    env = load_env()
    me = discord(env, "GET", "/users/@me")["id"]
    plays = []
    for ch in sys.argv[1:]:
        before = ""
        while True:
            batch = discord(env, "GET", f"/channels/{ch}/messages?limit=100{before}")
            if not batch:
                break
            for m in batch:
                if m["author"]["id"] != me:
                    continue
                for e in m.get("embeds", []):
                    if not (e.get("title") or "").startswith("Tocando agora"):
                        continue
                    hit = YT.search(e.get("description") or "")
                    if hit:
                        ts = time.mktime(time.strptime(m["timestamp"][:19], "%Y-%m-%dT%H:%M:%S"))
                        plays.append((ts, hit.group(3), hit.group(1)))
            before = "&before=" + batch[-1]["id"]
            time.sleep(1.2)  # 429 sem isso
    plays.sort()
    path = os.path.join(HERE, "data", "play-stats.json")
    try:
        stats = json.load(open(path))
    except FileNotFoundError:
        stats = {}
    guild = stats.setdefault(GUILD, {})
    last_seen = {}
    counted = 0
    for ts, vid, title in plays:
        if ts - last_seen.get(vid, -1e9) < 60:
            continue
        last_seen[vid] = ts
        e = guild.setdefault(vid, {"title": title, "url": vid, "count": 0, "last": 0})
        e["count"] += 1
        e["last"] = max(e["last"], int(ts * 1000))
        counted += 1
    with open(path + ".tmp", "w") as f:
        json.dump(stats, f)
    os.replace(path + ".tmp", path)
    print(f"{len(plays)} anuncios, {counted} execucoes, {len(guild)} faixas distintas")
    for e in sorted(guild.values(), key=lambda x: -x["count"])[:10]:
        print(f"{e['count']:4d}  {e['title']}")


if __name__ == "__main__":
    main()
