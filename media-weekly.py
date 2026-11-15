#!/usr/bin/env python3
"""Posta no Discord os lancamentos da semana de filmes, series, animes e mangas.

Um post por categoria, no mesmo canal do games-weekly (GAMES_CHANNEL_ID). Cron do deploy
toda segunda logo depois do games-weekly.

Fontes:
  filmes/series  TMDB (regiao BR, pt-BR), env TMDB_TOKEN = "API Read Access Token" (v4)
  animes/mangas  AniList GraphQL, sem chave
  episodios      animes que exibiram na semana PASSADA (AniList) -> serie no TMDB -> IMDb id -> nota e
                 votos por episodio no GraphQL publico do site do IMDb (sem chave, nao oficial)

Nao ha fonte estruturada de lancamentos de manga no Brasil (Panini/JBC/NewPOP nao publicam
calendario legivel), entao "mangas" sao os em alta na AniList.

Uso: media-weekly.py [filmes|series|animes|mangas|mangas-novos|episodios|episodios-series ...] [--dry-run] [--week-of AAAA-MM-DD]
     sem categoria = todas menos episodios* (cron proprio na quarta)
"""
import datetime as dt
import io
import json
import re
import statistics
import sys
import textwrap
import urllib.parse
import uuid

from botlib import DISCORD_UA, TZ, http, load_env, load_state, log, save_state, send

LIMIT = 10
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
TMDB_IMG = "https://image.tmdb.org/t/p/w342"


def week_bounds(day):
    start = dt.datetime.combine(day - dt.timedelta(days=day.weekday()), dt.time(), TZ)
    return start, start + dt.timedelta(days=7)


def dia(d):
    return f"{DIAS[d.weekday()]} {d:%d/%m}"


def tmdb(env, path, **params):
    q = urllib.parse.urlencode({"language": "pt-BR", **params})
    return http(f"https://api.themoviedb.org/3{path}?{q}",
                headers={"Authorization": f"Bearer {env['TMDB_TOKEN']}", "Accept": "application/json"})


def tmdb_detalhes(env, kind, tid):
    """Ficha + provedores + videos (+ datas de lancamento no filme) numa chamada so."""
    extra = "videos,watch/providers" + (",release_dates" if kind == "movie" else "")
    return tmdb(env, f"/{kind}/{tid}", append_to_response=extra, include_video_language="pt,en,null")


def onde_assistir(det):
    """Assinatura no Brasil; sem assinatura, aluguel/compra; sem nada, None."""
    br = det.get("watch/providers", {}).get("results", {}).get("BR", {})
    def nomes(k):  # tira canal de revenda e variante do mesmo servico ("Paramount Plus Premium")
        out = []
        for p in br.get(k, []):
            nome = p["provider_name"]
            if "channel" not in nome.lower() and not any(nome.startswith(o) for o in out):
                out.append(nome)
        return out
    if nomes("flatrate"):
        return ", ".join(nomes("flatrate")[:2])
    aluguel = nomes("rent") or nomes("buy")
    return f"aluguel: {', '.join(aluguel[:2])}" if aluguel else None


def trailer(det):
    """Trailer mais recente no YouTube, preferindo o dublado/legendado em portugues."""
    vids = [v for v in det.get("videos", {}).get("results", []) if v["site"] == "YouTube" and v["type"] == "Trailer"]
    vids.sort(key=lambda v: v.get("published_at", ""), reverse=True)
    vids.sort(key=lambda v: v.get("iso_639_1") != "pt")  # sort estavel: pt primeiro, mais recente dentro
    return f"https://www.youtube.com/watch?v={vids[0]['key']}" if vids else None


# generos de serie que o TMDB nao traduz para pt-BR
GENEROS_TV_PT = {"Sci-Fi & Fantasy": "Ficção e Fantasia", "Action & Adventure": "Ação e Aventura",
                 "War & Politics": "Guerra e Política", "Kids": "Infantil"}


def generos(nomes):
    return ", ".join(GENEROS_TV_PT.get(g, g) for g in nomes[:2])


def filmes(env, start, end):
    last = (end - dt.timedelta(days=1)).date()
    found = {}
    # 3 = cinema amplo, 2 = limitado, 4 = digital; nessa ordem para o circuito grande vir antes do
    # filme de festival que so tem popularidade global. region=BR filtra pela data brasileira.
    for tipo, label in (("3", "cinema"), ("2", "cinema"), ("4", "digital")):
        res = tmdb(env, "/discover/movie", region="BR", sort_by="popularity.desc",
                   with_release_type=tipo, **{"release_date.gte": start.date(), "release_date.lte": last})
        for m in res["results"]:
            # relancamento (Jogos Vorazes de 2012 voltando ao cinema) nao e estreia
            if m.get("release_date", "") >= (start.date() - dt.timedelta(days=365)).isoformat():
                found.setdefault(m["id"], {**m, "onde": label})
    cinema = [m for m in found.values() if m["onde"] == "cinema"][:6]
    top = (cinema + [m for m in found.values() if m["onde"] != "cinema"])[:LIMIT]
    out = []
    for m in top:
        det = tmdb_detalhes(env, "movie", m["id"])
        datas = [r["release_date"][:10] for c in det["release_dates"]["results"] if c["iso_3166_1"] == "BR"
                 for r in c["release_dates"] if start.date().isoformat() <= r["release_date"][:10] <= last.isoformat()]
        d = dt.date.fromisoformat(min(datas) if datas else m["release_date"])
        onde = "cinema" if m["onde"] == "cinema" else (onde_assistir(det) or "digital")
        out.append({"nome": det["title"], "data": d, "img": det.get("poster_path"), "trailer": trailer(det),
                    "extra": " · ".join([onde, generos([g["name"] for g in det.get("genres", [])])]).strip(" ·"),
                    "url": f"https://www.themoviedb.org/movie/{m['id']}"})
    return out


# talk show, reality, novela, jornal e infantil: tem episodio todo dia e lotava o topo de popularidade
SEM_DIARIOS = "10767|10764|10766|10763|10762"
PAISES_SERIE_NOVA = {"US", "GB", "CA", "BR", "JP", "KR", "ES", "FR", "DE", "AU"}


def series(env, start, end):
    """Series novas e temporadas novas com estreia na semana.

    Entra quem tem streaming no Brasil, ou serie nova (temporada 1) de pais relevante, que muitas vezes
    ainda nao tem provedor cadastrado no TMDB na semana de estreia (VisionQuest, Crystal Lake).
    """
    last = (end - dt.timedelta(days=1)).date()
    out = []
    # ponytail: ~300 chamadas de detalhe (~1 min); cabe no cron semanal
    for page in range(1, 16):
        res = tmdb(env, "/discover/tv", sort_by="popularity.desc", page=page, without_genres=SEM_DIARIOS,
                   **{"air_date.gte": start.date(), "air_date.lte": last})
        for s in res["results"]:
            det = tmdb_detalhes(env, "tv", s["id"])
            # air_date da temporada = data do episodio 1; pega tambem temporada lancada inteira de uma vez
            for temp in det.get("seasons", []):
                if temp.get("season_number", 0) < 1 or not temp.get("air_date"):
                    continue
                d = dt.date.fromisoformat(temp["air_date"])
                if not start.date() <= d <= last:
                    continue
                n = temp["season_number"]
                onde = onde_assistir(det)
                if not onde and not (n == 1 and set(det.get("origin_country", [])) & PAISES_SERIE_NOVA):
                    break
                onde = onde or ", ".join(x["name"] for x in det.get("networks", [])[:1])
                partes = ["série nova" if n == 1 else f"temporada {n}", onde,
                          generos([g["name"] for g in det.get("genres", [])])]
                out.append({"nome": det["name"], "data": d, "img": det.get("poster_path"), "trailer": trailer(det),
                            "extra": " · ".join(filter(None, partes)), "pop": s["popularity"],
                            "url": f"https://www.themoviedb.org/tv/{s['id']}"})
                break
        if page >= res.get("total_pages", 1):
            break
    top = sorted(out, key=lambda e: -e["pop"])[:LIMIT]
    return sorted(top, key=lambda e: e["data"])


def anilist(query, **variables):
    return http("https://graphql.anilist.co", data={"query": query, "variables": variables})["data"]


def titulo(m):
    return m["title"]["english"] or m["title"]["romaji"]


GENEROS_PT = {
    "Action": "Ação", "Adventure": "Aventura", "Comedy": "Comédia", "Drama": "Drama", "Ecchi": "Ecchi",
    "Fantasy": "Fantasia", "Horror": "Terror", "Mahou Shoujo": "Mahou Shoujo", "Mecha": "Mecha",
    "Music": "Música", "Mystery": "Mistério", "Psychological": "Psicológico", "Romance": "Romance",
    "Sci-Fi": "Ficção científica", "Slice of Life": "Slice of Life", "Sports": "Esportes",
    "Supernatural": "Sobrenatural", "Thriller": "Suspense",
}
STREAMS = ("Crunchyroll", "Netflix", "Disney Plus", "Amazon Prime Video", "Max", "HIDIVE")


def generos_anilist(m):
    return generos([GENEROS_PT.get(g, g) for g in m.get("genres") or []])


def exibidos(start, end):
    """Primeiro episodio de cada anime (TV/ONA, sem adulto) exibido no intervalo, por id da AniList."""
    q = """query($a:Int,$b:Int,$p:Int){Page(page:$p,perPage:50){pageInfo{hasNextPage}
      airingSchedules(airingAt_greater:$a,airingAt_lesser:$b,sort:TIME){episode airingAt
      media{id isAdult siteUrl format popularity trending genres title{romaji english} coverImage{large}
      bannerImage trailer{id site} externalLinks{site type}}}}}"""
    por_id, page = {}, 1
    while True:
        pg = anilist(q, a=int(start.timestamp()) - 1, b=int(end.timestamp()), p=page)["Page"]
        for s in pg["airingSchedules"]:
            m = s["media"]
            if m["isAdult"] or m["format"] not in ("TV", "TV_SHORT", "ONA"):
                continue
            por_id.setdefault(m["id"], {**s, "media": m})
        if not pg["pageInfo"]["hasNextPage"]:
            break
        page += 1
    return por_id


def animes(env, start, end):
    """Estreias (episodio 1) primeiro, completado pelos mais em alta que tem episodio na semana."""
    por_id = exibidos(start, end)
    rank = sorted(por_id.values(), key=lambda s: (s["episode"] != 1, -(s["media"]["trending"] or 0),
                                                   -(s["media"]["popularity"] or 0)))[:LIMIT]
    out = []
    for s in rank:
        m = s["media"]
        quando = dt.datetime.fromtimestamp(s["airingAt"], TZ)
        streams = [l["site"] for l in m.get("externalLinks") or [] if l["type"] == "STREAMING" and l["site"] in STREAMS]
        t = m.get("trailer") or {}
        out.append({"nome": titulo(m), "data": quando.date(), "hora": f"{quando:%H:%M}",
                    "extra": " · ".join(filter(None, ["estreia" if s["episode"] == 1 else f"ep {s['episode']}",
                                                      ", ".join(dict.fromkeys(streams)), generos_anilist(m)])),
                    "trailer": f"https://www.youtube.com/watch?v={t['id']}" if t.get("site") == "youtube" else None,
                    "img": m["coverImage"]["large"], "url": m["siteUrl"], "estreia": s["episode"] == 1})
    return sorted(out, key=lambda e: (not e["estreia"], e["data"], e["hora"]))


def _mangas(filtro):
    q = """{Page(perPage:%d){media(type:MANGA,sort:TRENDING_DESC,isAdult:false,countryOfOrigin:"JP"%s){siteUrl
      genres startDate{month year} title{romaji english} coverImage{large}}}}""" % (LIMIT, filtro)
    return anilist(q)["Page"]["media"]


def mangas(env, start, end):
    return [{"nome": titulo(m), "data": None, "img": m["coverImage"]["large"], "url": m["siteUrl"],
             "extra": generos_anilist(m)} for m in _mangas("")]


def mangas_novos(env, start, end):
    """Series que comecaram nos ultimos 4 meses e ja estao em alta."""
    desde = int(f"{start.date() - dt.timedelta(days=120):%Y%m%d}")
    return [{"nome": titulo(m), "data": None, "img": m["coverImage"]["large"], "url": m["siteUrl"],
             "extra": " · ".join(filter(None, [f"desde {m['startDate']['month']:02d}/{m['startDate']['year']}"
                                               if m["startDate"]["month"] else None, generos_anilist(m)]))}
            for m in _mangas(f",startDate_greater:{desde}")]


MIN_VOTOS = 50
# Ordem pela media bayesiana do IMDb Top 250: (v*R + m*C) / (v + m), C = mediana da semana. Abaixo de ~100 votos
# a nota de episodio e inflada e instavel (Detective Is Already Dead S2: 6.1 com 108 votos, 9.2 com 58 na semana
# seguinte); m=200 escolhido simulando 4 semanas (09-21 a 10-12/2026): mantem o top com quem tem milhares de votos
# e ainda deixa entrar episodio de nicho com nota bem acima da media.
PESO_VOTOS = 200
CANDIDATOS = 60  # animes mais populares da semana consultados no IMDb; abaixo disso nao junta 50 votos
# filtro de data no servidor: sem ele, episodio futuro so com o ano ("Episode #3.11", 2026) vem antes no sort
IMDB_EPS = """query($id:ID!){title(id:$id){episodes{episodes(first:20,sort:{by:RELEASE_DATE,order:DESC},
  filter:{releasedOnOrAfter:{year:%d,month:%d,day:%d},releasedOnOrBefore:{year:%d,month:%d,day:%d}}){edges{node{
  id titleText{text} releaseDate{year month day} ratingsSummary{aggregateRating voteCount} primaryImage{url}
  series{displayableEpisodeNumber{displayableSeason{text} episodeNumber{text}}}}}}}}}"""


def imdb_episodios(tid, start, end):
    """Episodios da serie com data do IMDb dentro da semana."""
    a, b = start.date(), end.date() - dt.timedelta(days=1)
    q = IMDB_EPS % (a.year, a.month, a.day, b.year, b.month, b.day)
    r = http("https://caching.graphql.imdb.com/", data={"query": q, "variables": {"id": tid}},
             headers={"x-imdb-client-name": "imdb-web-next-localized", "Accept-Language": "en-US"})
    eps = ((r["data"]["title"] or {}).get("episodes") or {}).get("episodes") or {"edges": []}
    out = []
    for e in eps["edges"]:
        d = e["node"].get("releaseDate") or {}
        if d.get("day") and start.date() <= dt.date(d["year"], d["month"], d["day"]) < end.date():
            out.append({**e["node"], "data": dt.date(d["year"], d["month"], d["day"])})
    return out


def imdb_candidatos(env, m):
    """Series do IMDb que podem ser este anime: TMDB (so animacao) e a busca do proprio IMDb.

    Titulos inteiros primeiro, depois os pedacos entre ':' e ' - ' ("JoJo no Kimyou na Bouken: Steel Ball
    Run - 2nd & 3rd STAGE" -> "Steel Ball Run"), porque continuacao costuma ser titulo separado no IMDb.
    """
    nomes = [n for n in (m["title"]["english"], m["title"]["romaji"]) if n]
    nomes += [p for n in nomes for p in re.split(r"\s*(?::| - )\s*", n) if len(p) > 3]
    for nome in dict.fromkeys(nomes):
        hit = next((r for r in tmdb(env, "/search/tv", query=nome)["results"] if 16 in r.get("genre_ids", [])), None)
        if hit:
            yield tmdb(env, f"/tv/{hit['id']}/external_ids").get("imdb_id")
        sug = http(f"https://v3.sg.media-imdb.com/suggestion/x/{urllib.parse.quote(nome[:150])}.json")  # limite 200
        yield from (s["id"] for s in sug.get("d", []) if s.get("qid") in ("tvSeries", "tvMiniSeries"))


def episodios_do_anime(env, m, cache, start, end):
    """Episodios do anime na semana. Vale a primeira serie candidata que tem episodio na semana, o que
    tambem descarta casamento errado; a escolhida fica no cache (state/anime-imdb.json, chave = id AniList)."""
    key = str(m["id"])
    if cache.get(key) and (eps := imdb_episodios(cache[key], start, end)):
        return eps
    for tid in dict.fromkeys(filter(None, imdb_candidatos(env, m))):
        if tid != cache.get(key) and (eps := imdb_episodios(tid, start, end)):
            cache[key] = tid
            return eps
    return []


def ranking_episodios(series, min_votos, peso, temporada):
    """series: [(nome, episodios do IMDb na semana, imagem reserva, campos extras da entrada)]. Melhor episodio
    de cada serie com min_votos, nota ponderada (C = mediana de todas as notas da semana), top LIMIT.

    temporada=False no anime: a temporada do IMDb nao bate com a da AniList (Link Click "Season 3" e T4 no IMDb).
    """
    out, notas = [], []
    for nome, eps, img_reserva, info in series:
        notas += [n["ratingsSummary"]["aggregateRating"] for n in eps if n["ratingsSummary"]["aggregateRating"]]
        melhor = None
        for n in eps:
            r = n["ratingsSummary"]
            if (r["voteCount"] or 0) >= min_votos and (not melhor or r["aggregateRating"] > melhor["nota"]):
                num = (n.get("series") or {}).get("displayableEpisodeNumber") or {}
                ep, temp = (num.get("episodeNumber") or {}).get("text"), (num.get("displayableSeason") or {}).get("text")
                nome_ep = n["titleText"]["text"]
                img = (n.get("primaryImage") or {}).get("url")
                melhor = {**info, "nome": nome, "data": n["data"], "nota": r["aggregateRating"], "votos": r["voteCount"],
                          "ep": f"T{temp} · EP {ep}" if temporada and temp and temp.isdigit() else ep and f"EP {ep}",
                          "ep_nome": None if nome_ep.startswith("Episode #") else nome_ep,
                          "url": f"https://www.imdb.com/title/{n['id']}/",
                          "img": img.replace("._V1_.", "._V1_UX1000_.") if img else img_reserva}
        if melhor:
            out.append(melhor)
    if not out:
        return []
    # a ponderada e o numero grande e a ordem; a nota crua do IMDb vai junto, menor
    c = statistics.median(notas)
    for e in out:
        e["ponderada"] = round((e["votos"] * e["nota"] + peso * c) / (e["votos"] + peso), 1)
    return sorted(out, key=lambda e: (-e["ponderada"], -e["votos"]))[:LIMIT]


def episodios(env, start, end):
    """Melhores episodios de anime da semana (AniList -> IMDb)."""
    # a data do IMDb e a do Japao/China; folga de 1 dia na AniList para nao perder quem exibe na virada
    por_id = exibidos(start - dt.timedelta(days=1), end + dt.timedelta(days=1))
    cache = load_state("anime-imdb") or {}
    series = []
    for s in sorted(por_id.values(), key=lambda s: -(s["media"]["popularity"] or 0))[:CANDIDATOS]:
        m = s["media"]
        streams = [l["site"] for l in m.get("externalLinks") or [] if l["type"] == "STREAMING" and l["site"] in STREAMS]
        try:
            series.append((titulo(m), episodios_do_anime(env, m, cache, start, end),
                           m["bannerImage"] or m["coverImage"]["large"], {"onde": ", ".join(dict.fromkeys(streams))}))
        except Exception as e:
            log(f"episodios: {titulo(m)}: {e}")
    save_state("anime-imdb", cache)
    return ranking_episodios(series, MIN_VOTOS, PESO_VOTOS, temporada=False)


# Series ocidentais juntam bem mais votos que anime; mesma calibracao em 4 semanas (09-21 a 10-12/2026):
# abaixo de 100 votos sobra novela turca 9.6/37 e wrestling 9.8/55; m=500 deixa Diplomata/Slow Horses/Ted Lasso
# no topo e ainda sobe serie menor com nota alta (Outlander: Blood of My Blood 8.7/235).
MIN_VOTOS_SERIES = 100
PESO_VOTOS_SERIES = 500


def episodios_series(env, start, end):
    """Melhores episodios de serie da semana (TMDB, sem animacao nem diarios -> imdb_id direto)."""
    last = (end - dt.timedelta(days=1)).date()
    series, vistos = [], set()
    for page in range(1, 5):  # ~80 mais populares com episodio na semana; abaixo disso ninguem junta 100 votos
        res = tmdb(env, "/discover/tv", sort_by="popularity.desc", page=page, without_genres=SEM_DIARIOS + "|16",
                   **{"air_date.gte": start.date(), "air_date.lte": last})
        for s in res["results"]:
            try:
                tid = tmdb(env, f"/tv/{s['id']}/external_ids").get("imdb_id")
                if tid and tid not in vistos:
                    vistos.add(tid)
                    series.append((s["name"], imdb_episodios(tid, start, end),
                                   s.get("backdrop_path") and "https://image.tmdb.org/t/p/w780" + s["backdrop_path"],
                                   {"tmdb": s["id"]}))
            except Exception as e:
                log(f"episodios-series: {s['name']}: {e}")
        if page >= res.get("total_pages", 1):
            break
    top = ranking_episodios(series, MIN_VOTOS_SERIES, PESO_VOTOS_SERIES, temporada=True)
    for e in top:  # provedor so dos 10 que entram: uma chamada a mais por serie
        try:
            e["onde"] = onde_assistir(tmdb(env, f"/tv/{e['tmdb']}", append_to_response="watch/providers"))
        except Exception as ex:
            log(f"episodios-series: provedor de {e['nome']}: {ex}")
    return top


CATEGORIAS = {
    # nome: (funcao, emoji+titulo, cor, rodape)
    "filmes": (filmes, "🎬 Filmes da semana", 0x01B4E4, "Estreias no Brasil · TMDB"),
    "series": (series, "📺 Séries da semana", 0x01B4E4, "Séries novas e temporadas novas · TMDB"),
    "animes": (animes, "🍥 Animes da semana", 0x02A9FF, "Estreias e episódios em alta · horário de Brasília · AniList"),
    "mangas": (mangas, "📚 Mangás em alta", 0x02A9FF, "Mais comentados da semana · AniList"),
    "mangas-novos": (mangas_novos, "🆕 Mangás novos em alta", 0x02A9FF, "Séries iniciadas nos últimos 4 meses · AniList"),
    "episodios": (episodios, "🏆 Top episódios de anime", 0xF5C518,
                  f"⭐ nota ponderada pelos votos (fórmula do IMDb Top 250) · mín. {MIN_VOTOS} avaliações no IMDb · o melhor episódio de cada anime"),
    "episodios-series": (episodios_series, "🏆 Top episódios de séries", 0xF5C518,
                         f"⭐ nota ponderada pelos votos (fórmula do IMDb Top 250) · mín. {MIN_VOTOS_SERIES} avaliações no IMDb · o melhor episódio de cada série"),
}


def poster_url(e):
    if not e["img"]:
        return None
    return e["img"] if e["img"].startswith("http") else TMDB_IMG + e["img"]


BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def baixar_cobrindo(url, W, H):
    """Baixa a imagem e recorta pelo centro na proporcao W:H antes de redimensionar."""
    from PIL import Image
    p = Image.open(io.BytesIO(http(url, raw=True))).convert("RGB")
    pw, ph = p.size
    if pw / ph > W / H:
        nw = int(ph * W / H)
        p = p.crop(((pw - nw) // 2, 0, (pw + nw) // 2, ph))
    else:
        nh = int(pw * H / W)
        p = p.crop((0, (ph - nh) // 2, pw, (ph + nh) // 2))
    return p.resize((W, H), Image.LANCZOS)


def collage(entries):
    """Mosaico 5 colunas com as capas numeradas na ordem da lista. Devolve JPEG em bytes."""
    from PIL import Image, ImageDraw, ImageFont
    W, H, GAP = 240, 360, 8
    COLS = min(5, len(entries))
    rows = (len(entries) + COLS - 1) // COLS
    img = Image.new("RGB", (COLS * W + (COLS + 1) * GAP, rows * H + (rows + 1) * GAP), (43, 45, 49))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(BOLD, 46)
    for i, e in enumerate(entries):
        x, y = GAP + (i % COLS) * (W + GAP), GAP + (i // COLS) * (H + GAP)
        try:
            img.paste(baixar_cobrindo(poster_url(e), W, H), (x, y))
        except Exception:  # sem capa: bloco cinza com o nome
            draw.rectangle((x, y, x + W, y + H), fill=(64, 66, 73))
            draw.multiline_text((x + 12, y + H // 2), textwrap.fill(e["nome"], 16), font=font, fill=(220, 221, 222))
        draw.rounded_rectangle((x + 8, y + 8, x + 78, y + 68), 12, fill=(0, 0, 0))
        draw.text((x + 43, y + 38), str(i + 1), font=font, fill=(255, 255, 255), anchor="mm")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def bandas(entries):
    """Uma faixa por episodio: arte escurecendo para a direita, nome a esquerda, nota grande a direita."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = 1000, 170
    OURO, BRANCO, CINZA = (245, 197, 24), (255, 255, 255), (200, 200, 205)
    img = Image.new("RGB", (W, H * len(entries)), (20, 20, 24))
    draw = ImageDraw.Draw(img)
    # embed mostra a imagem a ~40 %: abaixo de 24 px o texto some
    f_nota, f_nome, f_num, f_peq = (ImageFont.truetype(BOLD, s) for s in (92, 40, 26, 24))
    preto = Image.new("RGB", (W, H))
    # mascara horizontal: arte limpa ate 40 % da largura, preto a partir de 75 % (fundo da nota)
    sombra = Image.linear_gradient("L").rotate(90).resize((W, H)).point(
        lambda v: max(0, min(255, (v - 102) * 255 // 90)))
    for i, e in enumerate(entries):
        y = i * H
        try:
            arte = Image.blend(baixar_cobrindo(e["img"], W, H), preto, 0.2)
            img.paste(Image.composite(preto, arte, sombra), (0, y))
        except Exception:  # sem arte: faixa lisa
            draw.rectangle((0, y, W, y + H), fill=(40, 42, 48))
        meio = y + H // 2
        podio = [OURO, (192, 192, 200), (205, 127, 50)][i] if i < 3 else None  # ouro, prata, bronze
        draw.ellipse((22, meio - 26, 74, meio + 26), fill=podio, outline=podio or BRANCO, width=3)
        draw.text((48, meio), f"{i + 1:02d}", font=f_num, fill=(0, 0, 0) if podio else BRANCO, anchor="mm")
        nome = e["nome"]
        while draw.textlength(nome, font=f_nome) > 580:  # para antes da estrela
            nome = nome[:-2].rstrip() + "…"
        draw.text((96, meio - 6), nome, font=f_nome, fill=BRANCO, anchor="lm", stroke_width=3, stroke_fill=(0, 0, 0))
        draw.text((98, meio + 34), f"IMDb {e['nota']:.1f} · {e['votos']:,} votos".replace(",", "."), font=f_peq,
                  fill=CINZA, anchor="lm", stroke_width=2, stroke_fill=(0, 0, 0))
        if e.get("onde"):
            draw.text((98, y + 16), e["onde"].split(",")[0].upper(), font=f_peq, fill=OURO, anchor="lt",
                      stroke_width=2, stroke_fill=(0, 0, 0))
        nota = f"{e['ponderada']:.1f}"
        draw.text((W - 70, meio + 4), nota, font=f_nota, fill=BRANCO, anchor="rm")
        x_estrela = W - 70 - draw.textlength(nota, font=f_nota) - 14
        draw.text((x_estrela, meio + 4), "★", font=f_nome, fill=OURO, anchor="rm")
        draw.text((W - 20, meio + 24), "/10", font=f_peq, fill=CINZA, anchor="rm")
        if e.get("ep"):
            draw.text((W - 20, y + 12), e["ep"], font=f_peq, fill=CINZA, anchor="rt")
        if e.get("ep_nome"):
            draw.text((W - 20, y + H - 10), textwrap.shorten(e["ep_nome"], 30, placeholder="…"),
                      font=f_peq, fill=OURO, anchor="rb")
        draw.line((0, y + H - 1, W, y + H - 1), fill=(0, 0, 0), width=2)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def build_embed(cat, entries, start, end):
    _, nome, cor, rodape = CATEGORIAS[cat]
    last = end - dt.timedelta(days=1)
    emb = {"title": f"{nome} · {start:%d/%m} a {last:%d/%m}", "color": cor, "footer": {"text": rodape}}
    if not entries:
        emb["description"] = "Nada relevante nesta semana."
        return emb
    linhas = []
    if cat.startswith("episodios"):
        for i, e in enumerate(entries, 1):
            pos = "🥇🥈🥉"[i - 1] if i <= 3 else f"`{i:>2}`"
            ep = " · ".join(filter(None, [e["ep"] and e["ep"].replace(" · EP ", "E").replace("EP ", "ep "),  # T4E8 / ep 3
                                          e["ep_nome"] and f"*{textwrap.shorten(e['ep_nome'], 40, placeholder='…')}*"]))
            linhas.append(f"{pos} **[{textwrap.shorten(e['nome'], 45, placeholder='…')}]({e['url']})**"
                          + (f" — {ep}" if ep else "")
                          + f"\n-# ⭐ **{e['ponderada']}** · IMDb {e['nota']:.1f} ({e['votos']:,} votos)".replace(",", ".")
                          + f" · {dia(e['data'])}" + (f" · 📺 {e['onde']}" if e.get("onde") else ""))
        emb["description"] = "\n".join(linhas)
        emb["image"] = {"url": "attachment://capas.jpg"}
        return emb
    for i, e in enumerate(entries, 1):
        quando = f" `{dia(e['data'])}{' ' + e['hora'] if e.get('hora') else ''}`" if e["data"] else ""
        nome_curto = e["nome"] if len(e["nome"]) <= 50 else e["nome"][:48] + "…"
        detalhe = " · ".join(filter(None, [e["extra"], f"[▶ trailer]({e['trailer']})" if e.get("trailer") else None]))
        linhas.append(f"`{i:>2}`{quando} **[{nome_curto}]({e['url']})**" + (f"\n-# {detalhe}" if detalhe else ""))
    emb["description"] = "\n".join(linhas)
    emb["image"] = {"url": "attachment://capas.jpg"}
    return emb


def post_with_image(env, embed, jpeg):
    boundary = uuid.uuid4().hex
    payload = json.dumps({"embeds": [embed], "allowed_mentions": {"parse": []},
                          "attachments": [{"id": 0, "filename": "capas.jpg"}]})
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
            f"Content-Type: application/json\r\n\r\n{payload}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"capas.jpg\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n").encode() + jpeg + f"\r\n--{boundary}--\r\n".encode()
    return http(f"https://discord.com/api/v10/channels/{env['GAMES_CHANNEL_ID']}/messages", data=body, method="POST",
                headers={"Authorization": f"Bot {env['DISCORD_BOT_TOKEN']}", "User-Agent": DISCORD_UA,
                         "Content-Type": f"multipart/form-data; boundary={boundary}"})


def main():
    args = sys.argv[1:]
    env = load_env()
    day = dt.datetime.now(TZ).date()
    if "--week-of" in args:
        day = dt.date.fromisoformat(args[args.index("--week-of") + 1])
    start, end = week_bounds(day)
    # episodios tem cron proprio na quarta: na segunda o episodio de domingo ainda nao juntou votos
    cats = [a for a in args if a in CATEGORIAS] or [c for c in CATEGORIAS if not c.startswith("episodios")]
    falhou = False
    for cat in cats:
        if (cat in ("filmes", "series") or cat.startswith("episodios")) and not env.get("TMDB_TOKEN"):
            log(f"{cat}: sem TMDB_TOKEN no .env, pulado")
            continue
        # episodios olha a semana que acabou: nota so existe depois que o episodio exibe
        ini, fim = (start - dt.timedelta(days=7), start) if cat.startswith("episodios") else (start, end)
        try:
            entries = CATEGORIAS[cat][0](env, ini, fim)
            embed = build_embed(cat, entries, ini, fim)
            # embed mostra imagem em ate ~400x300: 10 faixas viram miniatura ilegivel, 4 cabem (lista segue com 10)
            jpeg = (bandas(entries[:4]) if cat.startswith("episodios") else collage(entries)) if entries else None
            if "--dry-run" in args:
                print(json.dumps(embed, ensure_ascii=False, indent=2))
                if jpeg:
                    open(f"/tmp/media-weekly-{cat}.jpg", "wb").write(jpeg)
                continue
            msg = post_with_image(env, embed, jpeg) if jpeg else send(env, env["GAMES_CHANNEL_ID"], [embed])
            log(f"{cat}: postado msg={msg['id']} itens={len(entries)}")
        except Exception as e:  # uma fonte fora do ar nao derruba as outras categorias
            log(f"{cat}: ERRO {e}")
            falhou = True
    sys.exit(1 if falhou else 0)


if __name__ == "__main__":
    main()
