#!/usr/bin/env python3
"""Eventos do servidor (substitui a Loritta): cargo automatico na entrada e log de
entrada/saida/troca de apelido e de mensagem apagada no canal de log.

Unico script do bot que fica conectado ao gateway (o resto e cron por REST). Divide o token
com o Muse: o Discord aceita varias sessoes do mesmo bot e entrega os eventos a todas.
Precisa das intents "Server Members" e "Message Content" ligadas no portal, do bot com View
nos canais privados (senao nao recebe as mensagens deles) e do cargo do bot acima do autorole,
com Manage Roles. Roda no container `events` do compose (repo montado em /app).

config.json -> "events": {"channel": <id do #log>, "autorole": <id do cargo>}

Os outros recursos que precisam do gateway sao modulos com setup(bot):
steamlink (previa de link da Steam), weekly (ranking semanal), tempvoice (salas temporarias).
Comandos de barra sao GLOBAIS: o Muse registra os dele por servidor e, no boot, zera os globais;
sync_commands recoloca os nossos em ate 5 min.
"""
import logging

import discord
from discord.ext import commands, tasks

import steamlink
import tempvoice
import weekly
from botlib import load_config, load_env, log

cfg = load_config()["events"]
CHANNEL, AUTOROLE = int(cfg["channel"]), int(cfg.get("autorole") or 0)
NO_PING = discord.AllowedMentions.none()

intents = discord.Intents.none()
intents.guilds = True
intents.members = True
intents.guild_messages = True
intents.message_content = True
intents.voice_states = True
intents.presences = True
# ponytail: o conteudo de mensagem apagada vem do cache em memoria; o que foi postado antes do ultimo
# restart sai so como "nao disponivel". Persistir em disco se isso incomodar.
client = commands.Bot(command_prefix=commands.when_mentioned, intents=intents, max_messages=5000,
                      help_command=None)


@client.event
async def on_command_error(ctx, error):
    pass  # sem comandos de texto; mencao ao bot nao e erro


@tasks.loop(minutes=5)
async def sync_commands():
    have = {c.name for c in await client.tree.fetch_commands()}
    if not {c.name for c in client.tree.get_commands()} <= have:
        await client.tree.sync()
        log("comandos globais registrados")


async def setup_hook():
    for mod in (steamlink, weekly, tempvoice):
        await mod.setup(client)
    sync_commands.before_loop(client.wait_until_ready)
    sync_commands.start()
client.setup_hook = setup_hook


async def post(guild, **kw):
    ch = guild.get_channel(CHANNEL)
    if ch:
        await ch.send(allowed_mentions=NO_PING, **kw)


@client.listen()
async def on_ready():
    log(f"conectado como {client.user} em {len(client.guilds)} servidor(es)")


@client.listen()
async def on_member_join(m):
    log(f"entrou: {m} ({m.id})")
    if AUTOROLE and not m.bot and (role := m.guild.get_role(AUTOROLE)):
        try:
            await m.add_roles(role, reason="autorole na entrada")
        except discord.HTTPException as e:
            log(f"autorole falhou para {m}: {e}")
    await post(m.guild, content=f"👉 {m.mention} entrou no servidor!")


@client.listen()
async def on_member_remove(m):
    log(f"saiu: {m} ({m.id})")
    await post(m.guild, content=f"👈 {discord.utils.escape_markdown(m.display_name)} saiu do servidor...")


@client.listen()
async def on_member_update(before, after):
    if before.nick == after.nick:
        return
    log(f"apelido: {after} {before.nick!r} -> {after.nick!r}")
    e = discord.Embed(title=f"📝 Apelido de {discord.utils.escape_markdown(after.name)} alterado", color=0x2ECC71,
                      timestamp=discord.utils.utcnow())
    e.set_author(name=f"@{after.name}", icon_url=after.display_avatar.url)
    e.add_field(name="Antigo", value=f"`{before.nick or 'sem apelido'}`")
    e.add_field(name="Novo", value=f"`{after.nick or 'sem apelido'}`")
    e.set_footer(text=f"ID do usuário: {after.id}")
    await post(after.guild, embed=e)


@client.listen()
async def on_raw_message_delete(p):
    if not p.guild_id or p.channel_id == CHANNEL:
        return
    m, guild = p.cached_message, client.get_guild(p.guild_id)
    if m and (m.author.bot or m.webhook_id):
        return
    e = discord.Embed(title="🗑️ Mensagem apagada", color=0xE74C3C, timestamp=discord.utils.utcnow())
    e.add_field(name="Canal", value=f"<#{p.channel_id}>")
    if m:
        log(f"apagada: {m.author} em #{m.channel}")
        e.set_author(name=f"@{m.author.name}", icon_url=m.author.display_avatar.url)
        e.description = (m.content or "*sem texto*")[:4000]
        if m.attachments:
            e.add_field(name="Anexos", value="\n".join(a.filename for a in m.attachments)[:1000])
        e.set_footer(text=f"ID do usuário: {m.author.id}")
    else:
        log(f"apagada (fora do cache): {p.message_id} em {p.channel_id}")
        e.description = "*conteúdo não disponível (mensagem anterior ao último restart do bot)*"
        e.set_footer(text=f"ID da mensagem: {p.message_id}")
    await post(guild, embed=e)


# so WARNING+ do discord.py: sem isso, excecao dentro de listener some sem deixar rastro
client.run(load_env()["DISCORD_BOT_TOKEN"], log_level=logging.WARNING)

