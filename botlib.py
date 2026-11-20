"""Pecas comuns dos scripts de cron do bot (games-weekly, free-games, steam-news, twitch-live).

Tudo stdlib. O bot so e usado pela API REST com o token do .env (sem gateway), entao os
scripts convivem com o Muse, que segura a conexao de gateway do mesmo token.
"""
import datetime as dt
import json
import os
import re
import sys
import time
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
        try:
            detail = e.read().decode(errors="replace")[:300]
        except OSError:  # conexao caiu lendo o corpo do erro: o status ja basta
            detail = ""
        raise RuntimeError(f"HTTP {e.code} em {url.split('?')[0]}: {detail}") from None
    except OSError as e:  # DNS, timeout, conexao resetada: mesmo tipo do erro HTTP, para quem chama tratar um so
        raise RuntimeError(f"rede em {url.split('?')[0]}: {e}") from None
    return body if raw else (json.loads(body) if body else None)


def discord(env, method, path, payload=None):
    for attempt in (1, 2):
        try:
            return http(f"https://discord.com/api/v10{path}", data=payload, method=method,
                        headers={"Authorization": f"Bot {env['DISCORD_BOT_TOKEN']}", "User-Agent": DISCORD_UA})
        except RuntimeError as e:
            # 429/5xx do Discord e passageiro: uma nova tentativa evita perder o post ate a proxima rodada.
            # POST de mensagem repetido nao duplica: send() manda nonce + enforce_nonce.
            m = re.match(r"HTTP (429|5\d\d) ", str(e))
            if attempt == 2 or not m:
                raise
            wait = re.search(r'"retry_after": ?([\d.]+)', str(e))
            time.sleep(min(float(wait.group(1)) if wait else 2, 30))


def send(env, channel, embeds, content=None):
    # nonce: se o Discord criou a mensagem mas devolveu 5xx, a nova tentativa recebe a mesma em vez de duplicar
    body = {"embeds": embeds, "allowed_mentions": {"parse": []},
            "nonce": str(int.from_bytes(os.urandom(7))), "enforce_nonce": True}
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
    tmp = f"{p}.{os.getpid()}.tmp"  # por processo: duas rodadas sobrepostas apagavam o .tmp uma da outra
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)


def single_instance(name):
    """Sai (codigo 0) se outra rodada do mesmo script ainda esta viva: cron curto + rede lenta
    sobrepunha rodadas, e a segunda repostava o que a primeira ainda nao tinha gravado no state."""
    import fcntl  # so existe no Linux; os testes rodam tambem no Windows
    os.makedirs(os.path.dirname(state_path(name)), exist_ok=True)
    f = open(state_path(name) + ".lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log(f"{name}: rodada anterior ainda em curso, saindo")
        sys.exit(0)
    return f  # quem chama guarda a referencia; o lock cai com o processo


STEAM_API = "https://api.steampowered.com"


def steam_profiles(key, fc):
    if not key:
        return fc["profiles"]
    try:
        r = http(f"{STEAM_API}/ISteamUser/GetFriendList/v1/?key={key}&steamid={fc['owner']}&relationship=friend")
        return [fc["owner"]] + [f["steamid"] for f in r["friendslist"]["friends"]]
    except Exception as e:
        log(f"GetFriendList falhou ({e}); usando a lista do config")
        return fc["profiles"]


def steam_names(key, ids):
    """Nome de exibicao por steamid. Chave recusada (403 desde 2026-11-13) ou ausente = {} e quem chama
    mostra o id: nome e enfeite, nao pode derrubar o script."""
    names = {}
    try:
        for i in range(0, len(ids) if key else 0, 100):
            r = http(f"{STEAM_API}/ISteamUser/GetPlayerSummaries/v2/?key={key}&steamids={','.join(ids[i:i + 100])}")
            names.update({p["steamid"]: p["personaname"] for p in r["response"]["players"]})
    except Exception as e:
        log(f"GetPlayerSummaries falhou ({e}); seguindo sem nomes")
    return names
