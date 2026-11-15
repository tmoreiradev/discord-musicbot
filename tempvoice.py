"""Salas de voz temporarias: entrar em "➕" cria uma sala propria e move a pessoa
para la; a sala some quando esvazia. Quem criou pode renomear/limitar/mover gente na sala dela.

Precisa de Manage Channels + Move Members no cargo do bot. O canal criador e criado pelo bot
na categoria de config.json -> "tempvoice": {"category": <id da categoria de voz>}.
Salas criadas ficam em state/tempvoice.json para a limpeza sobreviver a restart.
"""
import discord

from botlib import load_config, load_state, log, save_state

CATEGORY = int(load_config()["tempvoice"]["category"])
CREATOR = "➕"


def rooms():
    return set(load_state("tempvoice") or [])


def save(ids):
    save_state("tempvoice", sorted(ids))


def room_name(m):
    game = next((a.name for a in m.activities if a.type == discord.ActivityType.playing and a.name), None)
    return f"🎮 {game}" if game else f"🔊 Sala de {m.display_name}"


async def on_voice_state_update(m, before, after):
    ids = rooms()
    if before.channel and before.channel.id in ids and not before.channel.members:
        await before.channel.delete(reason="sala temporária vazia")
        ids.discard(before.channel.id)
        save(ids)
    if after.channel and after.channel.name == CREATOR and after.channel.category_id == CATEGORY and not m.bot:
        ch = await after.channel.category.create_voice_channel(
            room_name(m), reason=f"sala temporária de {m}",
            overwrites={**after.channel.category.overwrites,
                        m: discord.PermissionOverwrite(manage_channels=True, move_members=True, connect=True)})
        ids.add(ch.id)
        save(ids)
        await m.move_to(ch)
        log(f"tempvoice: {ch.name} para {m}")


async def on_ready_sweep(bot):
    """Cria o canal criador se faltar e apaga salas que esvaziaram com o bot fora."""
    cat = bot.get_channel(CATEGORY)
    if not cat:
        log("tempvoice: categoria não encontrada")
        return
    if not any(c.name == CREATOR for c in cat.voice_channels):
        await cat.create_voice_channel(CREATOR, reason="canal criador de salas temporárias")
        log("tempvoice: canal criador criado")
    ids = rooms()
    for cid in list(ids):
        ch = bot.get_channel(cid)
        if ch is None or not ch.members:
            if ch:
                await ch.delete(reason="sala temporária vazia")
            ids.discard(cid)
    save(ids)


async def setup(bot):
    bot.add_listener(on_voice_state_update, "on_voice_state_update")

    async def ready():
        try:
            await on_ready_sweep(bot)
        except discord.HTTPException as e:
            log(f"tempvoice: {e}")
    bot.add_listener(ready, "on_ready")

