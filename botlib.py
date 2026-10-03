"""Pecas comuns dos scripts de cron do bot (games-weekly, free-games, steam-news, twitch-live).

Tudo stdlib. O bot so e usado pela API REST com o token do .env (sem gateway), entao os
scripts convivem com o Muse, que segura a conexao de gateway do mesmo token.
"""
import datetime as dt
import json
import os
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo("America/Sao_Paulo")
UA = "Mozilla/5.0 (discord-bot cron)"
# Discord devolve 403 (Cloudflare) para UA de navegador; bot tem que se identificar assim
DISCORD_UA = "DiscordBot (https://github.com/tmoreiradev, 1.0)"


def now():
    return dt.datetime.now(TZ)


def log(msg):
    print(f"{now():%F %T} {msg}", flush=True)


def load_env():
    env = {}
    with open(os.path.join(HERE, ".env")) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith(("GAMES_", "FREE_", "TWITCH_", "NEWS_"))})
    return env


def load_config():
    with open(os.path.join(HERE, "config.json")) as f:
        return json.load(f)


def http(url, data=None, headers=None, method=None, raw=False):
    if isinstance(data, (dict, list)):
        data = json.dumps(data).encode()
        headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} em {url.split('?')[0]}: {e.read().decode(errors='replace')[:300]}") from None
    return body if raw else (json.loads(body) if body else None)


def discord(env, method, path, payload=None):
    return http(f"https://discord.com/api/v10{path}", data=payload, method=method,
                headers={"Authorization": f"Bot {env['DISCORD_BOT_TOKEN']}", "User-Agent": DISCORD_UA})


def send(env, channel, embeds, content=None):
    body = {"embeds": embeds, "allowed_mentions": {"parse": []}}
    if content:
        body["content"] = content
    return discord(env, "POST", f"/channels/{channel}/messages", body)


def state_path(name):
    return os.path.join(HERE, "state", f"{name}.json")


def load_state(name):
    """None quando ainda nao existe (primeira execucao)."""
    try:
        with open(state_path(name)) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_state(name, data):
    p = state_path(name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(p + ".tmp", p)
