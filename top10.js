// /top10: poe na fila as 10 faixas mais tocadas pelo bot neste servidor (ver play-stats.js).
//
// Segue o mesmo caminho do /play (add-query-to-queue.js): descarta fila velha, conecta ou
// recupera a conexao, enfileira e da play se estava parado. Cada faixa e resolvida de novo
// pelo GetSongs a partir da URL guardada, entao titulo/duracao/fonte vem frescos e uma
// faixa que sumiu do YouTube so e pulada.
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __param = (this && this.__param) || function (paramIndex, decorator) {
    return function (target, key) { decorator(target, key, paramIndex); }
};
import { inject, injectable } from 'inversify';
import { SlashCommandBuilder } from '@discordjs/builders';
import shuffle from 'array-shuffle';
import { TYPES } from '../types.js';
import { STATUS } from '../services/player.js';
import { getMemberVoiceChannel, getMostPopularVoiceChannel } from '../utils/channels.js';
import { songLink, topSongs } from '../utils/play-stats.js';
let default_1 = class default_1 {
    constructor(playerManager, getSongs) {
        this.slashCommand = new SlashCommandBuilder()
            .setName('top10')
            .setDescription('adiciona à fila as 10 músicas mais tocadas pelo bot neste servidor')
            .addBooleanOption(option => option
            .setName('embaralhar')
            .setDescription('embaralha as 10 antes de adicionar'));
        this.requiresVC = true;
        this.playerManager = playerManager;
        this.getSongs = getSongs;
    }
    async execute(interaction) {
        const guildId = interaction.guild.id;
        const top = topSongs(guildId, 10);
        if (top.length === 0) {
            throw new Error('ainda não há músicas tocadas para montar o top 10');
        }
        const player = this.playerManager.get(guildId);
        if (player.isQueueStale()) {
            player.resetStaleQueue();
        }
        const [targetVoiceChannel] = getMemberVoiceChannel(interaction.member) ?? getMostPopularVoiceChannel(interaction.guild);
        await interaction.deferReply();
        let resolved = [];
        for (const entry of top) {
            try {
                const [songs] = await this.getSongs.getSongs(songLink(entry.url), 1, false);
                if (songs.length > 0) {
                    resolved.push({ song: songs[0], entry });
                }
            }
            catch (error) {
                console.warn(`[muse] top10: nao resolvi ${entry.url}`, error);
            }
        }
        if (resolved.length === 0) {
            throw new Error('nenhuma das músicas do top 10 está disponível agora');
        }
        if (interaction.options.getBoolean('embaralhar')) {
            resolved = shuffle(resolved);
        }
        const needsConnection = player.voiceConnection === null;
        if (needsConnection) {
            await player.connect(targetVoiceChannel);
        }
        else {
            await player.ensureVoiceConnectionReady();
        }
        for (const { song } of resolved) {
            player.add({
                ...song,
                addedInChannelId: interaction.channel.id,
                requestedBy: interaction.member.user.id,
            });
        }
        if (needsConnection || player.status === STATUS.IDLE) {
            await player.play();
        }
        console.log(`[muse] top10 guild=${guildId} adicionadas=${resolved.length}/${top.length}`);
        // titulo cortado: 10 titulos longos de cover passam do limite de 2000 caracteres
        const short = t => (t.length > 70 ? t.slice(0, 69) + '…' : t).replace(/[[\]]/g, '');
        const lines = resolved.map(({ song, entry }, i) => `\`${String(i + 1).padStart(2)}.\` [${short(song.title)}](<${songLink(song.url)}>) — ${entry.count}×`);
        const missing = top.length - resolved.length;
        await interaction.editReply(`🏆 **Top ${resolved.length} do servidor** adicionado à fila:\n${lines.join('\n')}`
            + (missing > 0 ? `\n-# ${missing} indisponível(is) agora, pulada(s)` : ''));
    }
};
default_1 = __decorate([
    injectable(),
    __param(0, inject(TYPES.Managers.Player)),
    __param(1, inject(TYPES.Services.GetSongs))
], default_1);
export default default_1;
