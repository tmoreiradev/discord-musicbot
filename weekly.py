"""Ranking semanal: o que o pessoal mais jogou.

Amostragem a cada 5 min (sobrevive a restart sem perder mais que uma amostra): cada membro com
"Jogando X" no perfil soma 5 min ao jogo X (fora os de IGNORE). Precisa da Presence Intent ligada
no portal. Acumula em state/weekly.json e posta segunda >= 10h no canal de config.json ->
"weekly": {"channel": ...}; depois zera.
"""
import discord
from discord.ext import tasks

from botlib import load_config, load_state, log, now, save_state

CHANNEL = int(load_config()["weekly"]["channel"])
STEP = 5
# "Jogando" que nao e jogo.
IGNORE = {"Wallpaper Engine"}


def hm(minutes):
    return f"{minutes // 60}h{minutes % 60:02d}"


def blank():
    return {"week": now().strftime("%G-W%V"), "games": {}}


@tasks.loop(minutes=STEP)
async def sample(bot):
    st = load_state("weekly") or blank()
    for g in bot.guilds:
        for m in g.members:
            if m.bot:
                continue
            for a in m.activities:
                if a.type == discord.ActivityType.playing and a.name and a.name not in IGNORE:
                    game = st["games"].setdefault(a.name, {})
                    game[str(m.id)] = game.get(str(m.id), 0) + STEP
    # semana virou e ja passou de segunda 10h (se o bot estava fora na segunda, posta quando voltar)
    if st["week"] != now().strftime("%G-W%V") and not (now().weekday() == 0 and now().hour < 10):
        await report(bot, st)
        st = blank()
    save_state("weekly", st)


async def report(bot, st):
    ch = bot.get_channel(CHANNEL)
    if not ch:
        return
    games = sorted(((n, p) for n, p in st["games"].items() if n not in IGNORE),
                   key=lambda x: -sum(x[1].values()))[:10]
    medal = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
    e = discord.Embed(title=f"📊 Resumo da semana ({st['week']})", color=0xF1C40F)
    e.add_field(name="🎮 Mais jogados", inline=False, value="\n".join(
        f"{medal[i]} **{discord.utils.escape_markdown(n)}** · {hm(sum(p.values()))} · {len(p)} "
        f"{'pessoa' if len(p) == 1 else 'pessoas'}" for i, (n, p) in enumerate(games)) or "nenhum jogo detectado")
    await ch.send(embed=e)
    log(f"weekly: resumo {st['week']} postado")


async def setup(bot):
    @sample.before_loop
    async def _wait():
        await bot.wait_until_ready()
    sample.start(bot)
