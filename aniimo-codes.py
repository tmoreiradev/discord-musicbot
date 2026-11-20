#!/usr/bin/env python3
"""Posta no Discord os codigos de presente novos do Aniimo.

O jogo nao tem API de codigos; as fontes sao dois guias que mantem a lista e separam
ativos de expirados (Mobalytics 403a o urllib, ficou de fora):
  - IGN wiki: tabela com <checkbox copyable> + linha "Reward".
  - GameWith: tabela "Working Codes", codigo num <span class="... font-mono ...">.
So conta o trecho antes do titulo de expirados. Uma fonte fora do ar nao impede a outra;
as duas fora = exit 1. Fonte que responde mas devolve 0 codigos = layout mudou, vai pro log.

Cron a cada hora. state/aniimo-codes.json guarda os codigos ja vistos (minusculos, porque
os sites divergem na caixa); na primeira execucao so registra, sem postar.

Env (.env do repo): DISCORD_BOT_TOKEN, GAMES_CHANNEL_ID (ou NEWS_CHANNEL_ID).
Uso: aniimo-codes.py [--dry-run]
"""
import html
import re
import sys

from botlib import http, load_env, load_state, log, save_state, send, single_instance

IGN = "https://www.ign.com/wikis/aniimo/All_Aniimo_Codes_For_Free_Rewards"
GAMEWITH = "https://gamewith.ai/aniimo/en/articles/how-to-redeem-codes"


def text(s):
    return html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", ", ", s))).strip(" ,\n")


def ign():
    page = http(IGN, raw=True).decode()
    # a tabela vem duas vezes: no DOM e escapada no JSON do Next; desescapar une as duas
    page = page.replace("\\u003c", "<").replace("\\u003e", ">").replace('\\"', '"').replace("\\n", "\n")
    out = {}
    for sec in re.findall(r"All Aniimo Codes.*?(?=Expired Aniimo Codes|$)", page, re.S):
        for code, reward in re.findall(r'<checkbox copyable="true"[^>]*>([^<]+)</checkbox>'
                                       r'.*?Reward\s*</th>\s*<td[^>]*>(.*?)</td>', sec, re.S):
            out.setdefault(code.strip(), text(reward))
    return out


def gamewith():
    page = http(GAMEWITH, raw=True).decode()
    m = re.search(r">Working Codes<.*?(?=>Expired Codes<)", page, re.S)
    out = {}
    for code, rest in re.findall(r'font-mono[^"]*">([^<]+)</span>(.*?)</tr>', m.group(0) if m else "", re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", rest, re.S)
        out.setdefault(text(code), text(tds[-1]) if tds else "")
    return out


def main():
    dry = "--dry-run" in sys.argv
    env = load_env()
    lock = single_instance("aniimo-codes")  # noqa: F841
    found, ok = {}, 0
    for name, fn in (("IGN", ign), ("GameWith", gamewith)):
        try:
            codes = fn()
        except Exception as e:
            log(f"{name}: falhou: {e}")
            continue
        ok += 1
        if not codes:
            log(f"{name}: 0 codigos, layout mudou?")
        for code, reward in codes.items():
            found.setdefault(code.lower(), (code, reward, name))
    if not ok:
        sys.exit(1)

    state = load_state("aniimo-codes")
    seen = set(state or [])
    new = [v for k, v in found.items() if k not in seen]
    if state is None:
        log(f"primeira execucao: {len(found)} codigos registrados sem postar")
    elif new:
        lines = [f"`{code}` — {reward}" if reward else f"`{code}`" for code, reward, _ in new]
        embed = {
            "title": "🎁 Aniimo: código novo" if len(new) == 1 else f"🎁 Aniimo: {len(new)} códigos novos",
            "url": IGN,
            "description": "\n".join(lines) + "\n\nResgate em **Settings › Account › Gift Code Redemption**"
                           " (diferencia maiúsculas; recompensa chega no correio do jogo).",
            "color": 0x7BC67E,
            "footer": {"text": "Fonte: " + ", ".join(sorted({src for _, _, src in new}))},
        }
        log(f"novos: {', '.join(c for c, _, _ in new)}")
        if dry:
            print(embed)
            return
        send(env, env.get("NEWS_CHANNEL_ID") or env["GAMES_CHANNEL_ID"], [embed])
    else:
        log(f"nada novo ({len(found)} ativos)")
    if not dry:
        save_state("aniimo-codes", sorted(seen | set(found)))


if __name__ == "__main__":
    main()

