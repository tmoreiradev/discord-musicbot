#!/usr/bin/env python3
"""Avisa no Discord quando um jogo da wishlist do grupo entra em promocao na Steam.

Cron a cada 3 h. So Steam (sem IsThereAnyDeal, que exigiria conta propria):
  - IWishlistService/GetWishlist de cada perfil (dono + amigos da Steam do dono; wishlist
    privada volta vazia);
  - monitora a wishlist do dono inteira + todo jogo que esta na wishlist de min_wishlists
    pessoas (a uniao de todo mundo passa de 700 jogos e viraria spam);
  - preco em R$ pelo appdetails (cc=br, filters=price_overview, 50 por chamada).
Posta quando o jogo entra em desconto ou o preco cai mais durante a mesma promocao; guarda o
menor preco que o bot ja viu de cada jogo (a Steam nao expoe historico). Primeira execucao so
registra as promocoes em andamento, sem postar.

Config: config.json -> "wishlist" (channel, min_wishlists); perfis vem de steam_news.friends.
Uso: wishlist-deals.py [--dry-run]
"""
import sys
import time

from botlib import http, load_config, load_env, load_state, log, now, save_state, send

API = "https://api.steampowered.com"


def profiles(key, fc):
    try:
        r = http(f"{API}/ISteamUser/GetFriendList/v1/?key={key}&steamid={fc['owner']}&relationship=friend")
        return [fc["owner"]] + [f["steamid"] for f in r["friendslist"]["friends"]]
    except Exception as e:
        log(f"GetFriendList falhou ({e}); usando a lista do config")
        return fc["profiles"]


def player_names(key, ids):
    names = {}
    for i in range(0, len(ids), 100):
        r = http(f"{API}/ISteamUser/GetPlayerSummaries/v2/?key={key}&steamids={','.join(ids[i:i + 100])}")
        names.update({p["steamid"]: p["personaname"] for p in r["response"]["players"]})
    return names


def prices(appids):
    out = {}
    for i in range(0, len(appids), 50):
        chunk = appids[i:i + 50]
        r = http(f"https://store.steampowered.com/api/appdetails?appids={','.join(chunk)}&cc=br&filters=price_overview")
        for a, v in r.items():
            if v.get("success") and isinstance(v.get("data"), dict) and v["data"].get("price_overview"):
                out[a] = v["data"]["price_overview"]
        time.sleep(1.5)  # appdetails limita ~200 chamadas / 5 min
    return out


def app_info(appid):
    """Nome e capa. A capa vem do appdetails: jogo recente nao tem o header.jpg no caminho
    antigo (store_item_assets/.../header.jpg), o link certo tem hash e so a API sabe."""
    r = http(f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=br&l=portuguese")
    d = r.get(appid, {}).get("data") or {}
    return d.get("name", appid), d.get("header_image")


def brl(cents):
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main():
    dry = "--dry-run" in sys.argv
    env, cfg = load_env(), load_config()
    wc, fc = cfg["wishlist"], cfg["steam_news"]["friends"]
    key = env["STEAM_API_KEY"]
    channel = wc.get("channel") or env["GAMES_CHANNEL_ID"]
    st = load_state("wishlist-deals")
    first_run = st is None
    st = st or {"sales": {}, "lows": {}}

    ids = profiles(key, fc)
    wishers = {}
    for s in ids:
        try:
            items = http(f"{API}/IWishlistService/GetWishlist/v1/?steamid={s}").get("response", {}).get("items", [])
        except Exception as e:
            log(f"wishlist {s}: falhou ({e})")
            continue
        for it in items:
            wishers.setdefault(str(it["appid"]), []).append(s)
        time.sleep(0.3)
    watch = [a for a, w in wishers.items() if fc["owner"] in w or len(w) >= wc.get("min_wishlists", 2)]
    pr = prices(watch)
    names = player_names(key, ids)
    posted = 0
    for appid, p in pr.items():
        final = p["final"]
        low = st["lows"].get(appid)
        st["lows"][appid] = min(final, low) if low else final
        if not p.get("discount_percent"):
            st["sales"].pop(appid, None)  # promocao acabou: a proxima volta a avisar
            continue
        prev = st["sales"].get(appid)
        if prev is not None and final >= prev:
            continue  # ja avisado nesta promocao
        st["sales"][appid] = final
        if first_run:
            continue
        who = ", ".join(sorted(names.get(s, s) for s in wishers[appid]))
        low_txt = ""
        if low and low < final:
            low_txt = f"\nMenor preço que o bot já viu: {brl(low)}"
        elif low and final < low:
            low_txt = "\n**Menor preço que o bot já viu**"
        name, header = app_info(appid)
        e = {"author": {"name": "Promoção na Steam · wishlist"}, "title": name,
             "url": f"https://store.steampowered.com/app/{appid}/",
             "description": f"~~{p['initial_formatted']}~~ **{p['final_formatted']}** (-{p['discount_percent']}%)"
                            f"{low_txt}\nNa wishlist de: {who}",
             "color": 0x4C6B22,
             "footer": {"text": "Steam · preço no Brasil"}}
        if header:
            e["image"] = {"url": header}
        if dry:
            print(e["title"], "|", e["description"].replace("\n", " | "))
            continue
        send(env, channel, [e])
        posted += 1
        log(f"postado {appid} {e['title']} -{p['discount_percent']}%")
        time.sleep(1.5)
    on_sale = sum(1 for p in pr.values() if p.get("discount_percent"))
    log(f"{len(ids)} perfis, {len(wishers)} jogos em wishlists, {len(watch)} monitorados, {on_sale} em promoção, "
        f"{posted} postados" + (" (primeira execução: só registrado)" if first_run else ""))
    if not dry:
        save_state("wishlist-deals", st)


if __name__ == "__main__":
    main()
