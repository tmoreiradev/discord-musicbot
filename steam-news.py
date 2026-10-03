#!/usr/bin/env python3
"""Posta no Discord as notas de atualizacao dos jogos da lista (anuncios oficiais da Steam).

Cron a cada 30 min. Fonte: ISteamNews/GetNewsForApp (sem chave), so o feed
steam_community_announcements (o do proprio estudio; os outros feeds sao sites de noticia).
Entra um anuncio quando ele tem a tag "patchnotes" ou o titulo parece atualizacao
(update/patch/hotfix/changelog/...); promocao, bundle, collab e trilha sonora ficam de fora.
Com "mode": "all" no config o jogo posta todo anuncio oficial.

Alem da lista fixa, "friends" no config da os perfis Steam do grupo: a cada 6 h o script le
os jogos das ultimas 2 semanas de cada um e passa a monitorar o que min_players jogaram
(auto_apps no state; sai depois de 30 dias sem ninguem jogar).

Jogo novo no config.json (ou auto-adicionado) e registrado em silencio na primeira vez que aparece, para nao
despejar o historico dele no canal.

Uso: steam-news.py [--dry-run]
"""
import datetime as dt
import html
import re
import sys
import time

from botlib import http, load_config, load_env, load_state, log, now, save_state, send

UPDATE_RE = re.compile(r"\b(update|patch|hotfix|changelog|release notes|notas|atualiza\w*|version|v\d+\.\d+"
                       r"|season|temporada|expansion|dlc|1\.0|early access)\b", re.I)
SKIP_RE = re.compile(r"\b(sale|bundle|discount|collab|soundtrack|ost|merch|youtooz|giveaway|% off)\b", re.I)
MAX_AGE = dt.timedelta(days=3)
FRIENDS_EVERY = dt.timedelta(hours=6)
DROP_AFTER = dt.timedelta(days=30)


def clean(text, limit=350):
    text = re.sub(r"\{STEAM_CLAN_IMAGE\}\S*|https?://\S+", "", text)
    text = re.sub(r"\[/?[a-z0-9*]+(=[^\]]*)?\]", " ", text)  # bbcode
    text = re.sub(r"<[^>]+>", " ", html.unescape(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def header_image(appid):
    # a primeira imagem do texto costuma ser um banner antigo reaproveitado (o changelog do
    # Palworld 1.0.5 abria com o banner do Feybreak de 2024); a capa da loja e sempre atual.
    # Jogo recente tem a capa num caminho com hash que so o appdetails informa.
    try:
        d = http(f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=br").get(str(appid), {}).get("data") or {}
        if d.get("header_image"):
            return d["header_image"]
    except Exception:
        pass
    return f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"


def wanted(item, mode):
    if mode == "all":
        return True
    if "patchnotes" in (item.get("tags") or []):
        return True
    t = item["title"]
    return bool(UPDATE_RE.search(t)) and not SKIP_RE.search(t)


STEAM_API = "https://api.steampowered.com"


def recent_games_xml(profile):
    """Sem chave: jogos das ultimas 2 semanas pelo XML publico do perfil. Perfil ou detalhes
    de jogo privados = vazio."""
    x = http(f"https://steamcommunity.com/profiles/{profile}/?xml=1", raw=True).decode("utf-8", "replace")
    name = re.search(r"<steamID><!\[CDATA\[(.*?)\]\]>", x)
    games = re.findall(r"<gameName><!\[CDATA\[(.*?)\]\]></gameName>.*?<gameLink><!\[CDATA\[.*?/app/(\d+)", x, re.S)
    return (name.group(1) if name else profile), {appid: g for g, appid in games}


def friend_profiles(key, fc):
    """Com chave: a lista de amigos do dono vem da API a cada passada (amigo novo entra sozinho).
    Sem chave, ou se a API recusar, fica a lista fixa do config."""
    if key and fc.get("owner"):
        try:
            r = http(f"{STEAM_API}/ISteamUser/GetFriendList/v1/?key={key}&steamid={fc['owner']}&relationship=friend")
            return [fc["owner"]] + [f["steamid"] for f in r["friendslist"]["friends"]]
        except Exception as e:
            log(f"GetFriendList falhou ({e}); usando a lista do config")
    return fc["profiles"]


def recent_games_api(key, profiles):
    """GetRecentlyPlayedGames (ultimas 2 semanas) por perfil + nomes por GetPlayerSummaries."""
    names = {}
    for i in range(0, len(profiles), 100):
        r = http(f"{STEAM_API}/ISteamUser/GetPlayerSummaries/v2/?key={key}&steamids={','.join(profiles[i:i + 100])}")
        names.update({p["steamid"]: p["personaname"] for p in r["response"]["players"]})
    for p in profiles:
        try:
            r = http(f"{STEAM_API}/IPlayerService/GetRecentlyPlayedGames/v1/?key={key}&steamid={p}")
        except Exception as e:  # perfil privado responde 401/500 em alguns casos
            log(f"perfil {p}: falhou ({e})")
            continue
        games = r.get("response", {}).get("games", [])
        yield names.get(p, p), {str(g["appid"]): g.get("name", str(g["appid"])) for g in games}
        time.sleep(0.3)


def refresh_friends(cfg, st, key):
    """A cada FRIENDS_EVERY entra no monitoramento todo jogo que min_players perfis jogaram nas
    ultimas 2 semanas; sai o auto-adicionado que ninguem joga ha DROP_AFTER."""
    fc = cfg.get("friends")
    last = st.get("friends_checked")
    if not fc or (last and now() - dt.datetime.fromisoformat(last) < FRIENDS_EVERY):
        return
    players = {}
    names = {}
    profiles = friend_profiles(key, fc)

    def xml_each():
        for p in profiles:
            try:
                yield recent_games_xml(p)
            except Exception as e:
                log(f"perfil {p}: falhou ({e})")
            time.sleep(0.5)

    for who, games in (recent_games_api(key, profiles) if key else xml_each()):
        for appid, g in games.items():
            players.setdefault(appid, set()).add(who)
            names[appid] = g
    log(f"amigos: {len(profiles)} perfis lidos ({'API' if key else 'XML'}), {len(players)} jogos recentes")
    auto = st.setdefault("auto_apps", {})
    for appid, who in players.items():
        # "ignore": apps que nao sao jogo (Wallpaper Engine etc.) ou que ninguem quer no canal
        if appid in cfg["apps"] or appid in fc.get("ignore", []) or len(who) < fc.get("min_players", 2):
            if appid in auto:
                auto[appid]["last_seen"] = now().isoformat(timespec="seconds")
            continue
        if appid not in auto:
            log(f"auto: {names[appid]} ({appid}) entrou, jogado por {', '.join(sorted(who))}")
            auto[appid] = {"name": names[appid], "added": now().isoformat(timespec="seconds")}
        auto[appid].update(last_seen=now().isoformat(timespec="seconds"), players=sorted(who))
    for appid in [a for a, v in auto.items() if now() - dt.datetime.fromisoformat(v["last_seen"]) > DROP_AFTER]:
        log(f"auto: {auto[appid]['name']} ({appid}) saiu, ninguem joga ha {DROP_AFTER.days} dias")
        del auto[appid]
    st["friends_checked"] = now().isoformat(timespec="seconds")


def main():
    dry = "--dry-run" in sys.argv
    env, cfg = load_env(), load_config()["steam_news"]
    channel = env.get("NEWS_CHANNEL_ID") or cfg.get("channel") or env["GAMES_CHANNEL_ID"]
    st = load_state("steam-news") or {"apps": [], "seen": {}}
    refresh_friends(cfg, st, env.get("STEAM_API_KEY"))
    apps = {**{a: v["name"] for a, v in st.get("auto_apps", {}).items()}, **cfg["apps"]}
    for appid, game in apps.items():
        mode = "patch"
        if isinstance(game, dict):
            game, mode = game["name"], game.get("mode", "patch")
        try:
            items = http("https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
                         f"?appid={appid}&count=10&feeds=steam_community_announcements")["appnews"]["newsitems"]
        except Exception as e:  # um jogo fora nao derruba os outros
            log(f"{game}: falhou ({e})")
            continue
        seeding = appid not in st["apps"]
        for it in sorted(items, key=lambda i: i["date"]):
            if it["gid"] in st["seen"]:
                continue
            fresh = now() - dt.datetime.fromtimestamp(it["date"], dt.timezone.utc) < MAX_AGE
            if not seeding and fresh and wanted(it, mode):
                e = {"author": {"name": game}, "title": it["title"][:256], "url": it["url"],
                     "description": clean(it.get("contents", "")), "color": 0x1B2838,
                     "image": {"url": header_image(appid)},
                     "footer": {"text": "Steam · anúncio oficial"},
                     "timestamp": dt.datetime.fromtimestamp(it["date"], dt.timezone.utc).isoformat()}
                if dry:
                    print(game, "|", it["title"])
                    continue
                send(env, channel, [e])
                log(f"postado {game}: {it['title']}")
            elif dry:
                print(game, "| (ignorado)", it["title"], "| seed" if seeding else "")
            st["seen"][it["gid"]] = now().isoformat(timespec="seconds")
        if seeding:
            st["apps"].append(appid)
            log(f"{game}: registrado sem postar ({len(items)} anúncios)")
    cutoff = (now() - dt.timedelta(days=180)).isoformat()
    st["seen"] = {k: v for k, v in st["seen"].items() if v >= cutoff}
    if not dry:
        save_state("steam-news", st)


if __name__ == "__main__":
    main()
