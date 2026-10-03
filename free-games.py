#!/usr/bin/env python3
"""Posta no Discord os jogos gratis do momento (substitui o bot FreeStuff).

Fontes (todas sem chave):
  - Epic: API da propria loja (preco em R$, data de fim exata).
  - GamerPower: giveaways das demais lojas (Steam, GOG, itch.io, Ubisoft, Prime, IndieGala,
    consoles, mobile...). Itens da Epic sao ignorados aqui porque a fonte oficial ja cobre.
  - PlayStation Blog: post "PlayStation Plus Monthly Games" (jogos do mes do PS Plus Essential).

Roda pelo cron do deploy a cada 30 min. Guarda o que ja postou em state/free-games.json;
na primeira execucao (sem state) so registra o que esta ativo, sem postar, para nao inundar
o canal. Uma mensagem por jogo, como o FreeStuff fazia.

Env (.env do repo): DISCORD_BOT_TOKEN, GAMES_CHANNEL_ID (opcional FREE_CHANNEL_ID).
Uso: free-games.py [--dry-run]
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state", "free-games.json")
TZ = ZoneInfo("America/Sao_Paulo")
UA = "Mozilla/5.0 (discord-bot free-games)"
MESES = {"January": "janeiro", "February": "fevereiro", "March": "março", "April": "abril",
         "May": "maio", "June": "junho", "July": "julho", "August": "agosto",
         "September": "setembro", "October": "outubro", "November": "novembro", "December": "dezembro"}
COLORS = {"Epic Games": 0x2A2A2A, "Steam": 0x1B2838, "GOG": 0x86328A, "itch.io": 0xFA5C5C,
          "PlayStation Plus": 0x0070D1, "Prime Gaming": 0x00A8E1, "Ubisoft": 0x0070FF}


def load_env():
    env = {}
    with open(os.path.join(HERE, ".env")) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith(("GAMES_", "FREE_"))})
    return env


def fetch(url, headers=None, data=None, method=None, raw=False):
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
    return body if raw else (json.loads(body) if body else None)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def resolve_redirect(url):
    """O GamerPower manda para a loja por um 302; queremos o link direto da loja.
    Le o Location sem seguir (algumas lojas 403am o urllib no destino)."""
    try:
        urllib.request.build_opener(_NoRedirect).open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            return e.headers["Location"]
    except Exception:
        pass
    return None


def fmt_end(d):
    return f"<t:{int(d.timestamp())}:d>" if d else None


# ---------- fontes ----------

def epic():
    data = fetch("https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
                 "?locale=pt-BR&country=BR&allowCountries=BR")
    out = []
    for g in data["data"]["Catalog"]["searchStore"]["elements"]:
        offers = [o for p in (g.get("promotions") or {}).get("promotionalOffers") or [] for o in p["promotionalOffers"]]
        price = g["price"]["totalPrice"]
        if not offers or price["discountPrice"] != 0:
            continue
        slug = (g.get("productSlug") or "").split("/")[0] or next(
            (m["pageSlug"] for m in (g.get("catalogNs") or {}).get("mappings") or [] if m.get("pageSlug")), None) or next(
            (m["pageSlug"] for m in g.get("offerMappings") or [] if m.get("pageSlug")), None)
        if not slug:
            continue  # "Mystery Game" sem pagina ainda
        imgs = {i["type"]: i["url"] for i in g.get("keyImages") or []}
        end = dt.datetime.fromisoformat(offers[0]["endDate"].replace("Z", "+00:00"))
        out.append({
            "key": f"epic:{g['id']}:{offers[0]['endDate'][:10]}",
            "store": "Epic Games", "title": g["title"],
            "url": f"https://store.epicgames.com/pt-BR/p/{slug}",
            "price": price["fmtPrice"]["originalPrice"] if price["originalPrice"] else None,
            "end": end,
            "image": imgs.get("OfferImageWide") or imgs.get("DieselStoreFrontWide") or imgs.get("Thumbnail"),
        })
    return out


def gamerpower():
    out = []
    for g in fetch("https://www.gamerpower.com/api/giveaways?type=game"):
        if "Epic Games Store" in g["platforms"] or g.get("status") != "Active":
            continue
        # "Bounty Train (GOG) Giveaway", "Dwarven Realms (Steam) Key Giveaway": a loja vem no parenteses
        m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*(?:Key\s*)?(?:Giveaway)?$", g["title"])
        title, store = (m.group(1), m.group(2)) if m else (g["title"].removesuffix(" Giveaway"), g["platforms"].split(",")[0])
        store = {"itch.io": "itch.io", "itchio": "itch.io", "indiegala": "IndieGala",
                 "mobile": "Android/iOS"}.get(store.lower(), store)
        end = None
        if g.get("end_date") and g["end_date"] != "N/A":
            end = dt.datetime.fromisoformat(g["end_date"]).replace(tzinfo=dt.timezone.utc)
            if end < dt.datetime.now(dt.timezone.utc):
                continue  # o GamerPower demora a marcar como Expired
        worth = g.get("worth")
        out.append({
            "key": f"gp:{g['id']}", "store": store, "title": title,
            "url": g["open_giveaway_url"], "lazy_url": True,
            "price": f"US$ {worth[1:].replace('.', ',')}" if worth and worth.startswith("$") else None,
            "end": end, "image": g.get("image"), "platforms": g["platforms"],
        })
    return out


def psplus():
    root = ET.fromstring(fetch("https://blog.playstation.com/category/ps-plus/feed/", raw=True))
    out = []
    for it in root.iter("item"):
        title = it.findtext("title") or ""
        m = re.match(r"PlayStation Plus Monthly Games for (\w+)\s*[:–-]\s*(.+)", title)
        if not m:
            continue
        pub = dt.datetime.strptime(it.findtext("pubDate")[:25], "%a, %d %b %Y %H:%M:%S").replace(tzinfo=dt.timezone.utc)
        if dt.datetime.now(dt.timezone.utc) - pub > dt.timedelta(days=20):
            continue
        img = None
        for el in it.iter():
            if el.tag.endswith("content") and el.get("url"):
                img = el.get("url")
                break
        if not img:
            enc = it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
            mi = re.search(r'<img[^>]+src="([^"]+)"', enc)
            img = mi.group(1) if mi else None
        out.append({
            "key": f"psplus:{it.findtext('link')}", "store": "PlayStation Plus",
            "title": f"PS Plus de {MESES.get(m.group(1), m.group(1))}",
            "games": [s.strip() for s in re.split(r",\s*", m.group(2))],
            "url": it.findtext("link"), "image": img, "price": None, "end": None,
        })
    return out


# ---------- discord ----------

def embed(item):
    if item["store"] == "PlayStation Plus":
        desc = "\n".join(f"• **{g}**" for g in item["games"])
        desc += "\n\nPara quem assina PS Plus (Essential ou acima): resgate durante o mês e o jogo fica na biblioteca enquanto a assinatura estiver ativa."
        desc += f"\n[Ver no PlayStation Blog]({item['url']})"
    else:
        price = f"~~{item['price']}~~ " if item.get("price") else ""
        end = f" até {fmt_end(item['end'])}" if item.get("end") else ""
        desc = f"{price}**Grátis**{end}\n[Abrir na loja]({item['url']})"
        if item.get("platforms"):
            desc += f"\n-# {item['platforms']}"
    e = {"author": {"name": item["store"]}, "title": item["title"], "url": item["url"],
         "description": desc, "color": COLORS.get(item["store"], 0x9146FF),
         "footer": {"text": "the bot · jogos grátis"}}
    if item.get("image"):
        e["image"] = {"url": item["image"]}
    return e


def post(env, item):
    channel = env.get("FREE_CHANNEL_ID") or env["GAMES_CHANNEL_ID"]
    fetch(f"https://discord.com/api/v10/channels/{channel}/messages", method="POST",
          data=json.dumps({"embeds": [embed(item)], "allowed_mentions": {"parse": []}}).encode(),
          # UA de navegador leva 403 do Cloudflare do Discord; bot tem que se identificar assim
          headers={"Authorization": f"Bot {env['DISCORD_BOT_TOKEN']}", "Content-Type": "application/json",
                   "User-Agent": "DiscordBot (https://github.com/tmoreiradev, 1.0)"})


def main():
    dry = "--dry-run" in sys.argv
    env = load_env()
    items = []
    for name, src in (("epic", epic), ("gamerpower", gamerpower), ("psplus", psplus)):
        try:
            items += src()
        except Exception as e:  # uma fonte fora nao derruba as outras
            print(f"{dt.datetime.now(TZ):%F %T} fonte {name} falhou: {e}", file=sys.stderr)
    first_run = not os.path.exists(STATE)
    seen = {} if first_run else json.load(open(STATE))
    new = [i for i in items if i["key"] not in seen]
    if first_run and not dry:
        print(f"{dt.datetime.now(TZ):%F %T} primeira execucao: {len(new)} itens registrados sem postar")
    for item in (new if dry or not first_run else []):
        if item.pop("lazy_url", False):
            item["url"] = resolve_redirect(item["url"]) or item["url"]
        if dry:
            print(json.dumps(embed(item), ensure_ascii=False, default=str))
            continue
        post(env, item)
        print(f"{dt.datetime.now(TZ):%F %T} postado {item['key']} {item['title']}")
        seen[item["key"]] = dt.datetime.now(TZ).isoformat(timespec="seconds")
        save(seen)  # a cada post: se o proximo falhar, este nao repete na proxima rodada
        time.sleep(1.5)
    if dry:
        return
    for item in new if first_run else []:
        seen[item["key"]] = dt.datetime.now(TZ).isoformat(timespec="seconds")
    save(seen)


def save(seen):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    cutoff = (dt.datetime.now(TZ) - dt.timedelta(days=120)).isoformat()
    with open(STATE + ".tmp", "w") as f:
        json.dump({k: v for k, v in seen.items() if v >= cutoff}, f, indent=1)
    os.replace(STATE + ".tmp", STATE)


if __name__ == "__main__":
    main()
