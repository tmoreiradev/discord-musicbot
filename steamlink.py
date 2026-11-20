"""Link da Steam colado no chat: responde com preco em R$, desconto, nota do Metacritic, analises mais uteis (positiva e negativa), OpenCritic, Famitsu, HowLongToBeat,
pt-BR/multiplayer/jogando agora, menor preco (IsThereAnyDeal), Game Pass/PS Plus e quem do grupo tem ou quer o jogo.
O card nativo da Steam na mensagem original e suprimido (precisa Manage Messages), entao a resposta
traz tambem a descricao e a imagem e fica sendo o unico card.

"Do grupo" = dono + amigos Steam dele (mesma lista do wishlist-deals). Biblioteca de cada perfil
via GetOwnedGames e wishlist via GetWishlist (perfil privado fica de fora), em cache de 24 h em
state/steam-owned.json; catalogos de assinatura em state/subscriptions.json, mesmo ciclo.
"""
import asyncio
import html
import json
import re
import time
import urllib.parse

import discord
from discord.ext import tasks

from botlib import STEAM_API, http, load_config, load_env, load_state, log, save_state, steam_names, steam_profiles

LINK = re.compile(r"store\.steampowered\.com/app/(\d+)")
URL = re.compile(r"https?://\S+")
KEY = load_env().get("STEAM_API_KEY")
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
ITAD_KEY = load_env().get("ITAD_KEY")
FRIENDS = load_config()["steam_news"]["friends"]


def norm(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())


def refresh_owned():
    ids = steam_profiles(KEY, FRIENDS)
    owned, wish = {}, {}
    for s in ids:
        try:
            r = http(f"{STEAM_API}/IPlayerService/GetOwnedGames/v1/?key={KEY}&steamid={s}&include_played_free_games=1") if KEY else {}
            games = r.get("response", {}).get("games")
            if games:
                owned[s] = [g["appid"] for g in games]
        except Exception as e:
            log(f"GetOwnedGames {s}: {e}")
        try:  # wishlist privada volta vazia
            items = http(f"{STEAM_API}/IWishlistService/GetWishlist/v1/?steamid={s}").get("response", {}).get("items")
            if items:
                wish[s] = [i["appid"] for i in items]
        except Exception as e:
            log(f"GetWishlist {s}: {e}")
    # chave recusada = nenhuma biblioteca e nenhum nome: mantem o ultimo dado bom em vez de gravar vazio
    prev = load_state("steam-owned") or {}
    st = {"ts": time.time(), "owned": owned or prev.get("owned", {}), "wish": wish,
          "names": {**prev.get("names", {}), **steam_names(KEY, list(set(owned) | set(wish)))}}
    save_state("steam-owned", st)
    log(f"steam-owned: {len(owned)}/{len(ids)} bibliotecas e {len(wish)} wishlists públicas")
    return st


def refresh_subs():
    """Catalogos de assinatura, titulos normalizados para casar com o nome da Steam (so titulo identico).
    Game Pass: listas publicas do catalogo BR (sigls) + nomes em ingles no displaycatalog.
    PS Plus: a pagina pt-br monta a lista por JS; a en-us traz em HTML. ponytail: catalogo dos EUA como
    aproximacao do BR (quase igual); trocar se a pagina pt-br voltar a ter a lista estatica."""
    subs = {}
    for label, sid in (("Game Pass PC", "fdd9e2a7-0fee-49f6-ad69-4354098401ff"),
                       ("Game Pass console", "f6f1f99f-9b49-4ccd-b3bf-4d9767a77f5e")):
        ids = [x["id"] for x in http(f"https://catalog.gamepass.com/sigls/v2?id={sid}&language=en-us&market=BR")[1:]]
        for i in range(0, len(ids), 100):
            r = http("https://displaycatalog.mp.microsoft.com/v7.0/products?market=BR&languages=en-us&bigIds="
                     + ",".join(ids[i:i + 100]))
            for p in r["Products"]:
                subs.setdefault(norm(p["LocalizedProperties"][0]["ProductTitle"]), []).append(label)
    page = http("https://www.playstation.com/en-us/ps-plus/games/", headers={"User-Agent": BROWSER_UA}, raw=True).decode()
    for t in re.findall(r'module-name="PS Plus Games List" data-dtm-label="([^"]+)"', page):
        subs.setdefault(norm(html.unescape(t)), []).append("PS Plus")
    save_state("subscriptions", {"ts": time.time(), "titles": subs})
    log(f"subscriptions: {len(subs)} títulos")


def lowest_price(appid):
    """Menor preco historico no Brasil pelo IsThereAnyDeal (todas as lojas). Precisa ITAD_KEY no .env."""
    if not ITAD_KEY:
        return None
    g = http(f"https://api.isthereanydeal.com/games/lookup/v1?key={ITAD_KEY}&appid={appid}")
    if not g.get("found"):
        return None
    r = http(f"https://api.isthereanydeal.com/games/historylow/v1?key={ITAD_KEY}&country=BR", data=[g["game"]["id"]])
    low = r[0].get("low") if r else None
    if not low:
        return None
    when = time.strftime("%m/%Y", time.strptime(low["timestamp"][:10], "%Y-%m-%d"))
    amount = f"{low['price']['amount']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"menor: R$ {amount} (−{low['cut']}%, {low['shop']['name']}, {when})"


def group_info(d, appid):
    """pt-BR, multiplayer e jogadores agora numa linha so (dados do appdetails + 1 chamada)."""
    langs = d.get("supported_languages") or ""
    m = re.search(r"Português \(Brasil\)(<strong>\*</strong>)?", langs)
    parts = ["🇧🇷 texto + áudio" if m and m.group(1) else "🇧🇷 texto" if m else "sem pt-BR"]
    cats = {c["id"] for c in d.get("categories") or []}
    modes = [label for label, ids in (("co-op online", {38}), ("co-op local", {39, 24}), ("PvP online", {36}),
                                       ("crossplay", {27})) if cats & ids]
    if not modes and cats & {1, 9, 49}:
        modes = ["multiplayer"]
    parts.append(", ".join(modes) if modes else "só single-player")
    try:
        n = http(f"{STEAM_API}/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={appid}")["response"]["player_count"]
        parts.append(f"{n:,}".replace(",", ".") + " jogando agora")
    except Exception:
        pass  # jogo nao lancado devolve 404
    return " · ".join(parts)


def metacritic(name):
    """Nota da critica no Metacritic. Busca pelo nome e so aceita titulo identico, para nao trazer a nota de outro jogo."""
    q = urllib.parse.quote(name, safe="")
    items = http(f"https://backend.metacritic.com/finder/metacritic/search/{q}/web?mcoTypeId=13&limit=5")["data"]["items"]
    it = next((i for i in items if norm(i["title"]) == norm(name)), None)
    if not it:
        return None
    s = http(f"https://backend.metacritic.com/games/metacritic/{it['slug']}/web?componentName=product")["data"]["item"]
    s = s.get("criticScoreSummary") or {}
    if not s.get("score"):
        return None
    return f"[{s['score']}/100]({'https://www.metacritic.com/game/' + it['slug'] + '/'}) ({s['reviewCount']} críticas)"


def top_reviews(appid):
    """Analise positiva e negativa mais uteis da Steam no ultimo ano (filter=all ordena por votos de util).
    Prefere pt-BR, cai para ingles; language=all traz qualquer idioma (japones, chines) e nao serve ao grupo."""
    out = []
    for kind, icon in (("positive", "👍"), ("negative", "👎")):
        for lang in ("brazilian", "english"):
            r = http(f"https://store.steampowered.com/appreviews/{appid}?json=1&language={lang}&purchase_type=all"
                     f"&filter=all&day_range=365&review_type={kind}&num_per_page=1").get("reviews")
            if r:
                break
        if not r:
            continue
        r = r[0]
        # analise da Steam vem em BBCode ([h1], [b], [url=...])
        text = " ".join(re.sub(r"\[/?[a-z0-9*]+(=[^\]]*)?\]", "", html.unescape(r["review"])).split())
        text = text[:300] + ("…" if len(text) > 300 else "")
        link = f"https://steamcommunity.com/profiles/{r['author']['steamid']}/recommended/{appid}/"
        out.append(f"{icon} {text}\n-# {r['votes_up']} acharam útil · [ver na Steam]({link})")
    return "\n".join(out) or None


def hltb(hid, name):
    """Tempos do HowLongToBeat. Com o id do Wikidata le a pagina do jogo; sem ele (jogo recem-lancado) usa a busca
    do site, que pede um token de /api/search/site/init, e so aceita titulo identico. Pagina e busca recusam o UA do bot."""
    if hid:
        page = http(f"https://howlongtobeat.com/game/{hid}", headers={"User-Agent": BROWSER_UA}, raw=True).decode()
        data = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S).group(1)
        g = json.loads(data)["props"]["pageProps"]["game"]["data"]["game"][0]
    else:
        h = {"User-Agent": BROWSER_UA, "Referer": "https://howlongtobeat.com/"}
        token = http(f"https://howlongtobeat.com/api/search/site/init?t={int(time.time() * 1000)}", headers=h)["token"]
        body = {"searchType": "games", "searchTerms": name.split(), "searchPage": 1, "size": 5,
                "searchOptions": {"games": {"userId": 0, "platform": "", "sortCategory": "popular",
                                            "rangeCategory": "main", "rangeTime": {"min": None, "max": None},
                                            "gameplay": {"perspective": "", "flow": "", "genre": "", "difficulty": ""},
                                            "rangeYear": {"min": "", "max": ""}, "modifier": ""},
                                  "users": {"sortCategory": "postcount"}, "lists": {"sortCategory": "follows"},
                                  "filter": "", "sort": 0, "randomizer": 0}, "useCache": True}
        found = http("https://howlongtobeat.com/api/search/site", data=body, headers={**h, "x-auth-token": token})["data"]
        g = next((x for x in found if norm(x["game_name"]) == norm(name)), None)
        if not g:
            return None
    times = [(label, g[k]) for label, k in (("História", "comp_main"), ("+extras", "comp_plus"), ("100%", "comp_100"))
             if g.get(k)]
    if not times:
        return None
    fmt = lambda s: f"{round(s / 1800) / 2:g}".replace(".", ",") + " h"
    return f"[{' · '.join(f'{label} {fmt(s)}' for label, s in times)}](https://howlongtobeat.com/game/{g['game_id']})"


def scores(appid, name):
    """OpenCritic, Famitsu e HowLongToBeat, achados pelo Steam app id (nunca pelo nome: "Elden Ring" casaria com
    o filme). Wikidata da a nota do OpenCritic, o id do HLTB e o artigo da Wikipedia em ingles; a Famitsu so existe
    no wikitext do artigo (parametro Fam do template Video game reviews). Cache de 24 h por appid, inclusive o
    "nao achou", porque a Wikipedia devolve 429 com poucas requisicoes seguidas; com erro nao grava o cache."""
    cache = load_state("game-scores") or {}
    hit = cache.get(appid)
    if hit and time.time() - hit["ts"] < 86400:
        return hit["v"]
    q = """SELECT ?score ?art ?hltb ?oc WHERE { ?item wdt:P1733 "%s" .
      OPTIONAL { ?item p:P444 ?st . ?st ps:P444 ?score ; pq:P447 wd:Q21039459 . }
      OPTIONAL { ?item wdt:P2816 ?hltb }
      OPTIONAL { ?item wdt:P2864 ?oc }
      OPTIONAL { ?art schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . } }""" % appid
    rows = http("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q))["results"]["bindings"]
    first = lambda k: next((r[k]["value"] for r in rows if k in r), None)
    v, ok = {}, True
    oc = sorted({r["score"]["value"] for r in rows if "score" in r})
    if any(s.endswith("/100") for s in oc):
        pct = next((s for s in oc if s.endswith("%")), None)
        score = next(s for s in oc if s.endswith("/100"))
        ocid = first("oc")
        link = f"[{score}](https://opencritic.com/game/{ocid}/-)" if ocid else score
        v["OpenCritic"] = link + (f" ({pct} recomendam)" if pct else "")
    art = first("art")
    if art:
        try:
            wt = http("https://en.wikipedia.org/w/api.php?action=parse&prop=wikitext&format=json&formatversion=2&page="
                      + urllib.parse.quote(urllib.parse.unquote(art.rsplit("/", 1)[1])))["parse"]["wikitext"]
            # "Fam = 38/40" ou as quatro notas soltas "Fam = 10/10, 10/10, 10/10, 9/10"
            m = re.search(r"\|\s*Fam\s*=([^<|}\n]*)", wt)
            raw = m.group(1) if m else ""
            total, tens = re.search(r"\d+/40", raw), re.findall(r"(\d+)/10", raw)
            fam = total.group(0) if total else f"{sum(map(int, tens[:4]))}/40" if len(tens) >= 4 else None
            if fam:
                v["Famitsu"] = f"[{fam}]({art})"
        except Exception as x:
            log(f"steamlink famitsu {appid}: {x}")
            ok = False
    try:
        if t := hltb(first("hltb"), name):
            v["HowLongToBeat"] = t
    except Exception as x:
        log(f"steamlink hltb {appid}: {x}")
        ok = False
    if ok:
        cache[appid] = {"ts": time.time(), "v": v}
        save_state("game-scores", cache)
    return v


def preview(appid):
    result = http(f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=br&l=brazilian")
    d = result.get(str(appid), {})
    if not d.get("success"):
        return None
    d = d["data"]
    po = d.get("price_overview")
    if d.get("is_free"):
        price = "Grátis"
    elif po:
        price = po["final_formatted"] + (f" (−{po['discount_percent']}%, era {po['initial_formatted']})"
                                         if po["discount_percent"] else "")
    else:
        price = "sem preço na loja BR"
    rd = d.get("release_date") or {}
    released = (rd.get("date") or "a definir") + (" (em breve)" if rd.get("coming_soon") else "")
    rv = http(f"https://store.steampowered.com/appreviews/{appid}?json=1&language=all&purchase_type=all"
              f"&num_per_page=0&l=brazilian").get("query_summary", {})
    n = rv.get("total_reviews", 0)
    reviews = rv.get("review_score_desc") or "sem análises"
    if n:
        reviews += f" ({n:,}".replace(",", ".") + f" · {round(100 * rv['total_positive'] / n)}% positivas)"
    st = load_state("steam-owned") or {"owned": {}, "names": {}}
    who = lambda lists: sorted(st["names"].get(s, s) for s, apps in lists.items() if int(appid) in apps)
    owners, wishers = who(st["owned"]), who(st.get("wish", {}))

    def safe(title, fn, *args):
        try:
            return fn(*args)
        except Exception as x:
            log(f"steamlink {title} {appid}: {x}")
    subs = ((load_state("subscriptions") or {}).get("titles") or {}).get(norm(d["name"]))
    low = safe("itad", lowest_price, appid)
    price += "".join(f"\n-# {x}" for x in (low, subs and "incluso no " + ", ".join(subs)) if x)
    e = discord.Embed(title=d["name"], url=f"https://store.steampowered.com/app/{appid}/", color=0x1B2838,
                      description=html.unescape(d.get("short_description") or "")[:500] or None)
    e.add_field(name="Preço", value=price)
    e.add_field(name="Análises", value=reviews)
    e.add_field(name="Lançamento", value=released)
    e.add_field(name="Info", value=safe("info", group_info, d, appid) or "—", inline=False)
    extra = safe("scores", scores, appid, d["name"]) or {}
    # Metacritic | OpenCritic | Famitsu na mesma linha; HLTB e analises ocupam a largura toda
    for title, v in (("Metacritic", safe("Metacritic", metacritic, d["name"])), ("OpenCritic", extra.get("OpenCritic")),
                     ("Famitsu", extra.get("Famitsu")), ("HowLongToBeat", extra.get("HowLongToBeat")),
                     ("Análises mais úteis", safe("reviews", top_reviews, appid))):
        if v:
            e.add_field(name=title, value=v[:1024], inline=title in ("Metacritic", "OpenCritic", "Famitsu"))
    e.add_field(name=f"Quem tem ({len(owners)})", value=", ".join(owners)[:1000] or "ninguém do grupo")
    if wishers:
        e.add_field(name=f"Na wishlist ({len(wishers)})", value=", ".join(wishers)[:1000])
    if d.get("header_image"):
        e.set_image(url=d["header_image"])
    return e


async def on_message(m):
    if m.author.bot or not m.guild:
        return
    sent = False
    for appid in list(dict.fromkeys(LINK.findall(m.content)))[:3]:
        try:
            e = await asyncio.to_thread(preview, appid)
        except Exception as x:
            log(f"steamlink {appid}: {x}")
            continue
        if e:
            await m.channel.send(embed=e)
            sent = True
    # suprimir esconde TODOS os embeds da mensagem: so quando todo link nela e da Steam
    if sent and all(LINK.search(u) for u in URL.findall(m.content)):
        try:
            await m.edit(suppress=True)
        except discord.HTTPException as x:
            log(f"steamlink suprimir embed: {x}")


@tasks.loop(hours=24)
async def owned_loop():
    try:
        await asyncio.to_thread(refresh_owned)
    except Exception as e:
        log(f"steam-owned: {e}")
    try:
        await asyncio.to_thread(refresh_subs)
    except Exception as e:
        log(f"subscriptions: {e}")


async def setup(bot):
    if not KEY:  # previa, preco e wishlist nao pedem chave; so "quem tem" fica com o ultimo dado gravado
        log("steamlink: sem STEAM_API_KEY, bibliotecas ficam com o ultimo dado")
    bot.add_listener(on_message, "on_message")
    owned_loop.start()
