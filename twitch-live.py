#!/usr/bin/env python3
"""Avisa no Discord quando um canal da Twitch da lista entra ao vivo.

Cron a cada 2 min. Ao entrar ao vivo posta um embed (titulo, jogo, miniatura); enquanto a
live dura, edita a mesma mensagem se titulo/jogo mudarem; quando acaba, edita para
"encerrou" com a duracao. Lista e canal em config.json ("twitch"); credenciais do app
Twitch (as mesmas do IGDB) no .env.

Uso: twitch-live.py [--dry-run]
"""
import datetime as dt
import sys
import urllib.parse

from botlib import discord, http, load_config, load_env, load_state, log, now, save_state, send

LIVE, ENDED = 0x9146FF, 0x4F545C


def app_token(env, st):
    """Token de app vale ~60 dias; guardado no state para nao pedir um a cada 2 min."""
    tok = st.get("_token")
    if tok and tok["expires"] > now().timestamp() + 3600:
        return tok["value"]
    q = urllib.parse.urlencode({"client_id": env["IGDB_CLIENT_ID"], "client_secret": env["IGDB_CLIENT_SECRET"],
                                "grant_type": "client_credentials"})
    r = http("https://id.twitch.tv/oauth2/token?" + q, data=b"", method="POST")
    st["_token"] = {"value": r["access_token"], "expires": now().timestamp() + r["expires_in"]}
    return r["access_token"]


def helix(env, token, path, params):
    q = urllib.parse.urlencode(params, doseq=True)
    return http(f"https://api.twitch.tv/helix/{path}?{q}",
                headers={"Client-ID": env["IGDB_CLIENT_ID"], "Authorization": f"Bearer {token}"})["data"]


def fmt_duration(start):
    mins = int((now() - start).total_seconds() // 60)
    return f"{mins // 60}h{mins % 60:02d}" if mins >= 60 else f"{mins} min"


def live_embed(s, user):
    thumb = s["thumbnail_url"].replace("{width}", "1280").replace("{height}", "720")
    return {
        "author": {"name": f"{s['user_name']} está ao vivo", "url": f"https://www.twitch.tv/{s['user_login']}",
                   "icon_url": user.get("profile_image_url")},
        "title": s["title"] or "(sem título)", "url": f"https://www.twitch.tv/{s['user_login']}",
        "color": LIVE,
        "fields": [{"name": "Jogo", "value": s.get("game_name") or "—", "inline": True},
                   {"name": "Assistindo", "value": str(s.get("viewer_count", 0)), "inline": True}],
        # cache-buster: o Discord guarda a miniatura pela URL
        "image": {"url": f"{thumb}?t={int(now().timestamp())}"},
        "thumbnail": {"url": user.get("profile_image_url")} if user.get("profile_image_url") else None,
        "footer": {"text": "Twitch"},
        "timestamp": s["started_at"],
    }


def main():
    dry = "--dry-run" in sys.argv
    env, cfg = load_env(), load_config()["twitch"]
    channel = env.get("TWITCH_CHANNEL_ID") or cfg["channel"]
    # TWITCH_LOGINS=a,b sobrepoe a lista (teste com um canal que esta ao vivo agora)
    logins = [l.lower() for l in (env["TWITCH_LOGINS"].split(",") if env.get("TWITCH_LOGINS") else cfg["logins"])]
    st = load_state("twitch-live") or {}
    token = app_token(env, st)
    streams = {s["user_login"].lower(): s for s in helix(env, token, "streams", {"user_login": logins})}
    users = {u["login"].lower(): u for u in helix(env, token, "users", {"login": logins})} if streams else {}
    lives = st.setdefault("lives", {})

    for login, s in streams.items():
        e = live_embed(s, users.get(login, {}))
        e = {k: v for k, v in e.items() if v is not None}
        cur = lives.get(login)
        if dry:
            print(login, "AO VIVO", s["title"], "|", s.get("game_name"))
            continue
        if not cur or cur["stream_id"] != s["id"]:
            msg = send(env, channel, [e], content=f"🔴 **{s['user_name']}** está ao vivo na Twitch!")
            lives[login] = {"stream_id": s["id"], "message_id": msg["id"], "started_at": s["started_at"],
                            "title": s["title"], "game": s.get("game_name")}
            log(f"live {login} {s['id']} postada")
        elif (cur["title"], cur["game"]) != (s["title"], s.get("game_name")):
            discord(env, "PATCH", f"/channels/{channel}/messages/{cur['message_id']}", {"embeds": [e]})
            cur.update(title=s["title"], game=s.get("game_name"))
            log(f"live {login} atualizada")

    for login in [l for l in lives if l not in streams]:
        cur = lives.pop(login)
        if dry:
            continue
        start = dt.datetime.fromisoformat(cur["started_at"].replace("Z", "+00:00"))
        name = login
        try:
            msg = discord(env, "GET", f"/channels/{channel}/messages/{cur['message_id']}")
            e = msg["embeds"][0]
            name = e["author"]["name"].removesuffix(" está ao vivo")
            e["author"]["name"] = f"{name} encerrou a live"
            e["color"] = ENDED
            e["fields"] = [f for f in e.get("fields", []) if f["name"] == "Jogo"] + [
                {"name": "Duração", "value": fmt_duration(start), "inline": True}]
            for k in ("image", "thumbnail", "video", "provider", "type"):
                e.pop(k, None)
            if e.get("author", {}).get("icon_url") is None:
                e.get("author", {}).pop("icon_url", None)
            discord(env, "PATCH", f"/channels/{channel}/messages/{cur['message_id']}",
                    {"content": f"⚫ **{name}** encerrou a live ({fmt_duration(start)}).", "embeds": [e]})
        except RuntimeError as err:  # mensagem apagada a mao etc.: so esquece a live
            log(f"nao consegui editar o fim da live de {login}: {err}")
        log(f"live {login} encerrada")

    if not dry:
        save_state("twitch-live", st)


if __name__ == "__main__":
    main()
