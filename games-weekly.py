#!/usr/bin/env python3
"""Posta no Discord os lancamentos de jogos da semana (segunda a domingo), via IGDB.

Roda pelo cron do deploy toda segunda 10:00 (TZ da maquina = America/Sao_Paulo).
Usa o token do proprio bot so pela API REST (sem gateway), entao a mensagem sai como
"the bot" sem mexer no Muse.

Env (lidas do .env do repo): DISCORD_BOT_TOKEN, IGDB_CLIENT_ID, IGDB_CLIENT_SECRET,
GAMES_CHANNEL_ID. Opcionais: GAMES_LIMIT (padrao 15).

Uso: games-weekly.py            posta a semana corrente
     games-weekly.py --dry-run  imprime o JSON em vez de postar
     games-weekly.py --week-of 2026-10-05   outra semana (qualquer dia dela)
"""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo("America/Sao_Paulo")
UA = "discord-bot games-weekly (+https://github.com/tmoreiradev)"

# Plataformas IGDB consideradas e o rotulo mostrado.
PLATFORMS = {
    6: "PC", 167: "PS5", 48: "PS4", 169: "Xbox Series", 49: "Xbox One",
    508: "Switch 2", 130: "Switch",
}
# game_type do IGDB que contam como "jogo": main, remake, remaster, expanded game, port.
GAME_TYPES = {0, 8, 9, 10, 11}

# Lojas: (dominio da URL, rotulo, plataformas que ela vende). Ordem = ordem dos links.
# So entra o link da loja de uma plataforma que lanca nesta semana: um port para
# Switch 2 nao deve mostrar o link da Steam de um jogo que saiu no PC ha anos.
STORES = [
    ("store.steampowered.com", "Steam", {"PC"}),
    ("epicgames.com", "Epic", {"PC"}),
    ("gog.com", "GOG", {"PC"}),
    ("playstation.com", "PS Store", {"PS5", "PS4"}),
    ("xbox.com", "Xbox", {"Xbox Series", "Xbox One"}),
    ("microsoft.com", "Xbox", {"Xbox Series", "Xbox One"}),
    ("nintendo.com", "Nintendo", {"Switch 2", "Switch"}),
]


def load_env():
    env = {}
    with open(os.path.join(HERE, ".env")) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k in env or k.startswith(("IGDB_", "GAMES_"))})
    return env


def http(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} em {url}: {e.read().decode(errors='replace')[:500]}")


def twitch_token(cid, secret):
    q = urllib.parse.urlencode({"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"})
    return http("https://id.twitch.tv/oauth2/token?" + q, data=b"", method="POST")["access_token"]


def igdb(cid, token, endpoint, query):
    return http(f"https://api.igdb.com/v4/{endpoint}", data=query.encode(),
                headers={"Client-ID": cid, "Authorization": f"Bearer {token}"}, method="POST")


def week_bounds(day):
    start = dt.datetime.combine(day - dt.timedelta(days=day.weekday()), dt.time(), TZ)
    return start, start + dt.timedelta(days=7)


def store_links(game, platforms):
    """Casa pelo dominio da URL, nao pelo nome da fonte: o nome engana
    ("Disney_Epic_Mickey" na URL da Steam virava link "Epic")."""
    urls = []
    for ext in game.get("external_games") or []:
        src = (ext.get("external_game_source") or {}).get("name", "").lower()
        if ext.get("url"):
            urls.append(ext["url"])
        elif "steam" in src and ext.get("uid"):
            urls.append(f"https://store.steampowered.com/app/{ext['uid']}")
    urls += [w.get("url", "") for w in game.get("websites") or []]
    found = {}
    for domain, label, plats in STORES:
        if label in found or not plats & platforms:
            continue
        for url in urls:
            host = urllib.parse.urlsplit(url).hostname or ""
            if host == domain or host.endswith("." + domain):
                found[label] = url
                break
    return found


def collect(cid, token, start, end):
    fields = ("date,platform,game.name,game.slug,game.url,game.hypes,game.game_type,"
              "game.parent_game,game.external_games.url,game.external_games.uid,"
              "game.external_games.external_game_source.name,game.websites.url,game.websites.type.type")
    plats = ",".join(map(str, PLATFORMS))
    games = {}
    offset = 0
    while True:
        rows = igdb(cid, token, "release_dates",
                    f"fields {fields}; where date >= {int(start.timestamp())} & date < {int(end.timestamp())}"
                    f" & platform = ({plats}); limit 500; offset {offset};")
        for r in rows:
            g = r.get("game")
            if not isinstance(g, dict) or g.get("game_type", 0) not in GAME_TYPES:
                continue
            e = games.setdefault(g["id"], {"game": g, "platforms": set(), "date": r["date"]})
            e["platforms"].add(PLATFORMS[r["platform"]])
            e["date"] = min(e["date"], r["date"])
        if len(rows) < 500:
            break
        offset += 500
    return sorted(games.values(), key=lambda e: (-(e["game"].get("hypes") or 0), e["date"]))


def build_embeds(entries, start, end, limit):
    dias = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
    top = [e for e in entries if (e["game"].get("hypes") or 0) > 0][:limit] or entries[:limit]
    top.sort(key=lambda e: (e["date"], -(e["game"].get("hypes") or 0)))
    lines = []
    for e in top:
        g = e["game"]
        d = dt.datetime.fromtimestamp(e["date"], TZ)
        order = list(PLATFORMS.values())
        plats = ", ".join(sorted(e["platforms"], key=order.index))
        links = store_links(g, e["platforms"])
        link_txt = " · ".join(f"[{k}]({v})" for k, v in links.items()) or f"[IGDB]({g.get('url')})"
        lines.append(f"**{g['name']}** — {dias[d.weekday()]} {d:%d/%m}\n{plats} · {link_txt}")
    last = end - dt.timedelta(days=1)
    title = f"🎮 Lançamentos da semana — {start:%d/%m} a {last:%d/%m}"
    if not lines:
        return [{"title": title, "description": "Nenhum lançamento relevante nesta semana.", "color": 0x9146FF}]
    embeds, chunk = [], ""
    for ln in lines:
        if len(chunk) + len(ln) + 2 > 3900:
            embeds.append(chunk)
            chunk = ""
        chunk += ln + "\n\n"
    embeds.append(chunk)
    out = [{"description": c.strip(), "color": 0x9146FF} for c in embeds]
    out[0]["title"] = title
    out[-1]["footer"] = {"text": f"Top {len(top)} por hype no IGDB · {len(entries)} lançamentos no total"}
    return out


def main():
    args = sys.argv[1:]
    env = load_env()
    day = dt.datetime.now(TZ).date()
    if "--week-of" in args:
        day = dt.date.fromisoformat(args[args.index("--week-of") + 1])
    start, end = week_bounds(day)
    cid = env["IGDB_CLIENT_ID"]
    token = twitch_token(cid, env["IGDB_CLIENT_SECRET"])
    entries = collect(cid, token, start, end)
    payload = {"embeds": build_embeds(entries, start, end, int(env.get("GAMES_LIMIT", "15"))),
               "allowed_mentions": {"parse": []}}
    if "--dry-run" in args:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    msg = http(f"https://discord.com/api/v10/channels/{env['GAMES_CHANNEL_ID']}/messages",
               data=json.dumps(payload).encode(), method="POST",
               headers={"Authorization": f"Bot {env['DISCORD_BOT_TOKEN']}", "Content-Type": "application/json"})
    print(f"{dt.datetime.now(TZ):%F %T} postado msg={msg['id']} jogos={len(entries)}")


if __name__ == "__main__":
    main()
