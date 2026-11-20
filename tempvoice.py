"""Salas de voz temporarias: entrar em "➕" cria uma sala propria e move a pessoa
para la; a sala some quando esvazia. Quem criou pode renomear/limitar/mover gente na sala dela.

Precisa de Manage Channels + Move Members no cargo do bot. O canal criador e criado pelo bot
na categoria de config.json -> "tempvoice": {"category": <id da categoria de voz>}.
Salas criadas ficam em state/tempvoice.json para a limpeza sobreviver a restart.
"""
import asyncio

import discord

from botlib import load_config, load_state, log, save_state

CATEGORY = int(load_config()["tempvoice"]["category"])
CREATOR = "➕"
# o cliente do Discord as vezes devolve a pessoa ao ➕ logo depois do move (11/11 e 15/11:
# 3 a 9 salas em segundos); sala recem-criada vazia espera antes de sumir
GRACE = 30


_rooms = None


def rooms():
    """Copia do conjunto em memoria. O arquivo so e lido no boot: antes era aberto a cada evento de voz
    do servidor (mute, mudo, troca de canal), e so este processo escreve nele."""
    global _rooms
    if _rooms is None:
        _rooms = set(load_state("tempvoice") or [])
    return set(_rooms)


def save(ids):
    global _rooms
    _rooms = set(ids)
    save_state("tempvoice", sorted(ids))


def room_name(m):
    game = next((a.name for a in m.activities if a.type == discord.ActivityType.playing and a.name), None)
    return f"🎮 {game}" if game else f"🔊 Sala de {m.display_name}"


async def drop_if_empty(ch):
    age = (discord.utils.utcnow() - ch.created_at).total_seconds()
    if age < GRACE:
        await asyncio.sleep(GRACE - age)
        ch = ch.guild.get_channel(ch.id)
    ids = rooms()
    if ch and ch.id in ids and not ch.members:
        await ch.delete(reason="sala temporária vazia")
        ids.discard(ch.id)
        save(ids)


async def on_voice_state_update(m, before, after):
    if before.channel and before.channel.id in rooms() and not before.channel.members:
        asyncio.create_task(drop_if_empty(before.channel))
    if after.channel and after.channel.name == CREATOR and after.channel.category_id == CATEGORY and not m.bot:
        ids = rooms()
        ch = next((c for c in after.channel.category.voice_channels
                   if c.id in ids and c.overwrites_for(m).manage_channels), None)
        if ch is None:
            ch = await after.channel.category.create_voice_channel(
                room_name(m), reason=f"sala temporária de {m}",
                overwrites={**after.channel.category.overwrites,
                            m: discord.PermissionOverwrite(manage_channels=True, move_members=True, connect=True)})
            ids.add(ch.id)
            save(ids)
            log(f"tempvoice: {ch.name} para {m}")
        else:
            log(f"tempvoice: {m} voltou ao ➕, de volta para {ch.name}")
        await asyncio.sleep(1)
        await m.move_to(ch)


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

