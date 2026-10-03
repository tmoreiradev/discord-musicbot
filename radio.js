// /radio: poe na fila musicas parecidas com as ultimas que o bot tocou neste servidor.
//
// "Parecidas" = o Mix do YouTube (lista RD<id>) de cada uma das 3 ultimas faixas tocadas
// (play-stats.js), lido pelo yt-dlp em modo flat (~2 s por mix, sai pelo mesmo proxy WARP do
// resto). As listas sao intercaladas e filtradas: fora o que tocou nas ultimas 50 execucoes,
// o que ja esta na fila, video com mais de 10 min (compilacao) e titulo quase igual a outro
// ja escolhido (o Mix traz muito clipe/letra/ao vivo da MESMA musica). Cada escolhida e
// resolvida pelo GetSongs, igual ao /play.
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __param = (this && this.__param) || function (paramIndex, decorator) {
    return function (target, key) { decorator(target, key, paramIndex); }
};
import { execFile } from 'child_process';
import { promisify } from 'util';
import { inject, injectable } from 'inversify';
import { SlashCommandBuilder } from '@discordjs/builders';
import { TYPES } from '../types.js';
import { STATUS } from '../services/player.js';
import { getMemberVoiceChannel, getMostPopularVoiceChannel } from '../utils/channels.js';
import { getExecutable } from '../utils/yt-dlp.js';
import { recentSongs, songLink } from '../utils/play-stats.js';
const run = promisify(execFile);
const SEEDS = 3;
const MAX_SECONDS = 600;
// palavras "de verdade" do titulo, sem o ruido tipico de video de musica
const NOISE = new Set(['official', 'oficial', 'video', 'clipe', 'clip', 'lyrics', 'letra', 'legendado', 'traducao',
    'tradução', 'audio', 'áudio', 'live', 'ao', 'vivo', 'hd', 'remastered', 'feat', 'ft', 'cover', 'music', 'musica', 'música']);
const words = title => new Set(title.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
    .split(/[^a-z0-9]+/).filter(w => w.length > 2 && !NOISE.has(w)));
const similar = (a, b) => {
    let common = 0;
    for (const w of a) {
        if (b.has(w)) {
            common++;
        }
    }
    return common / Math.max(1, Math.min(a.size, b.size)) >= 0.6;
};
const mixOf = async (videoId) => {
    const { stdout } = await run(getExecutable(), ['--flat-playlist', '-J', '--playlist-end', '30',
        `https://www.youtube.com/watch?v=${videoId}&list=RD${videoId}`], { timeout: 40_000, maxBuffer: 16 * 1024 * 1024 });
    return (JSON.parse(stdout).entries ?? []).filter(e => e.id && e.id.length === 11);
};
let default_1 = class default_1 {
    constructor(playerManager, getSongs) {
        this.slashCommand = new SlashCommandBuilder()
            .setName('radio')
            .setDescription('adiciona à fila músicas parecidas com as últimas que tocaram')
            .addIntegerOption(option => option
            .setName('quantidade')
            .setDescription('quantas músicas adicionar [padrão: 10]')
            .setMinValue(3)
            .setMaxValue(25));
        this.requiresVC = true;
        this.playerManager = playerManager;
        this.getSongs = getSongs;
    }
    async execute(interaction) {
        const guildId = interaction.guild.id;
        const wanted = interaction.options.getInteger('quantidade') ?? 10;
        const seeds = recentSongs(guildId, SEEDS).filter(s => s.url.length === 11);
        if (seeds.length === 0) {
            throw new Error('ainda não tocou nenhuma música do YouTube para servir de base');
        }
        const player = this.playerManager.get(guildId);
        if (player.isQueueStale()) {
            player.resetStaleQueue();
        }
        const [targetVoiceChannel] = getMemberVoiceChannel(interaction.member) ?? getMostPopularVoiceChannel(interaction.guild);
        await interaction.deferReply();
        const mixes = await Promise.all(seeds.map(s => mixOf(s.url).catch(error => {
            console.warn(`[muse] radio: mix de ${s.url} falhou`, error.message);
            return [];
        })));
        const exclude = new Set(recentSongs(guildId, 50).map(s => s.url));
        for (const s of [player.getCurrent(), ...player.getQueue()]) {
            if (s?.url) {
                exclude.add(s.url);
            }
        }
        const chosenWords = seeds.map(s => words(s.title));
        const picks = [];
        for (let i = 0; picks.length < wanted * 2 && mixes.some(m => i < m.length); i++) {
            for (const mix of mixes) {
                const e = mix[i];
                if (!e || exclude.has(e.id) || (e.duration && e.duration > MAX_SECONDS)) {
                    continue;
                }
                const w = words(e.title ?? '');
                if (chosenWords.some(c => similar(c, w))) {
                    continue;
                }
                exclude.add(e.id);
                chosenWords.push(w);
                picks.push(e.id);
            }
        }
        const resolved = [];
        for (const id of picks) {
            if (resolved.length >= wanted) {
                break;
            }
            try {
                const [songs] = await this.getSongs.getSongs(songLink(id), 1, false);
                if (songs.length > 0 && !songs[0].isLive && songs[0].length <= MAX_SECONDS) {
                    resolved.push(songs[0]);
                }
            }
            catch (error) {
                console.warn(`[muse] radio: nao resolvi ${id}`, error.message);
            }
        }
        if (resolved.length === 0) {
            throw new Error('não achei músicas parecidas agora, tente de novo em instantes');
        }
        const needsConnection = player.voiceConnection === null;
        if (needsConnection) {
            await player.connect(targetVoiceChannel);
        }
        else {
            await player.ensureVoiceConnectionReady();
        }
        for (const song of resolved) {
            player.add({
                ...song,
                addedInChannelId: interaction.channel.id,
                requestedBy: interaction.member.user.id,
            });
        }
        if (needsConnection || player.status === STATUS.IDLE) {
            await player.play();
        }
        console.log(`[muse] radio guild=${guildId} seeds=${seeds.map(s => s.url).join(',')} adicionadas=${resolved.length}`);
        const short = t => (t.length > 60 ? t.slice(0, 59) + '…' : t).replace(/[[\]]/g, '');
        const lines = resolved.map((song, i) => `\`${String(i + 1).padStart(2)}.\` [${short(song.title)}](<${songLink(song.url)}>)`);
        await interaction.editReply(`📻 **Rádio** — ${resolved.length} parecidas com ${seeds.map(s => `*${short(s.title)}*`).join(', ')}:\n${lines.join('\n')}`.slice(0, 2000));
    }
};
default_1 = __decorate([
    injectable(),
    __param(0, inject(TYPES.Managers.Player)),
    __param(1, inject(TYPES.Services.GetSongs))
], default_1);
export default default_1;
