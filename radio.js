// /radio <estilo> [quantidade]: poe musicas na fila conforme o estilo escolhido.
//
// - Estilos de genero (rock, rap, anime): sorteia faixas de playlists curadas. As do Deezer sao
//   editoriais, atualizadas pelos editores (lidas pela API publica, sem chave); cada faixa vira
//   uma busca "artista - titulo" no YouTube pelo yt-dlp (ytsearch, nao gasta cota da API do
//   Google), escolhendo o resultado com a duracao mais proxima da do Deezer. Anime dublado nao
//   existe no Deezer, entao esse le playlists do YouTube direto.
// - "top": as mais tocadas pelo bot neste servidor (play-stats.js). Substitui o antigo /top10.
// - "meu-top": o mesmo, contando so as faixas que quem chamou pediu (2026-10-11; historico
//   inicial tirado dos "Tocando agora ... Pedido por" do #playlist desde 2026-08-09).
// - "parecidas": o Mix do YouTube (lista RD<id>) de cada uma das 3 ultimas faixas tocadas,
//   intercalados.
//
// Filtros comuns (menos no "top"): fora o que o /radio ja serviu neste servidor nas ultimas 24 h
// (/data/radio-served.json, 2026-10-11: pedir o mesmo estilo de novo no dia traz outras), o que tocou nas ultimas 50 execucoes, o que ja esta na
// fila, video com mais de 10 min (compilacao), titulo quase igual a outro ja escolhido (o Mix traz
// clipe/letra/ao vivo da MESMA musica) e artista repetido: no maximo uma por artista (no anime,
// uma por anime), contando os das sementes do "parecidas" (2026-10-03). Cada escolhida e resolvida
// pelo GetSongs, igual ao /play.
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
import shuffle from 'array-shuffle';
import { TYPES } from '../types.js';
import { STATUS } from '../services/player.js';
import { getMemberVoiceChannel, getMostPopularVoiceChannel } from '../utils/channels.js';
import { getExecutable } from '../utils/yt-dlp.js';
import fs from 'fs';
import { recentSongs, songLink, topSongs } from '../utils/play-stats.js';
const run = promisify(execFile);
const SEEDS = 3;
const MAX_SECONDS = 600;
const SERVED_FILE = '/data/radio-served.json';
const SERVED_MS = 24 * 60 * 60_000;
// guild -> {chave: timestamp}; chave = id do YouTube ou "q:<busca>" (faixa do Deezer, evita buscar de novo)
const served = (() => {
    try {
        return JSON.parse(fs.readFileSync(SERVED_FILE, 'utf8'));
    }
    catch {
        return {};
    }
})();
const servedKeys = guildId => {
    const now = Date.now();
    const guild = served[guildId] ??= {};
    for (const [key, at] of Object.entries(guild)) {
        if (now - at > SERVED_MS) {
            delete guild[key];
        }
    }
    return Object.keys(guild);
};
const markServed = (guildId, keys) => {
    const now = Date.now();
    for (const key of keys) {
        served[guildId][key] = now;
    }
    try {
        fs.writeFileSync(SERVED_FILE, JSON.stringify(served));
    }
    catch (error) {
        console.warn('[muse] radio: falha ao gravar radio-served', error.message);
    }
};
const queryKey = c => (c.query ? 'q:' + c.query.toLowerCase() : null);
// ids de playlist: Deezer = editoriais escolhidas em 2026-10-03 (api.deezer.com/playlist/<id>),
// YouTube = playlists publicas. Trocar uma fonte = editar aqui e rebuild.
const GENRES = {
    'rock-br': { label: '🎸 rock nacional', deezer: ['9268271502', '9268293682', '11532710604'] },
    'rock-intl': { label: '🎸 rock internacional', deezer: ['752286631', '13693489781', '1202660313'] },
    'anime-br': { label: '🎌 abertura/encerramento de anime (pt-BR)', youtube: ['PLZ1dJqY6KWOU9pTYHxMbRmve-iAj4rBjY', 'PLaizWT6kFii27iZ1lrF1VyxU5cAZzbu1w', 'PLhGkb7SHCVo9rDNhbRJnieWdhvUUzQzBI', 'PL-MZiM_3IYctHh_Lb1H6X1WDRpiwW1u8S'] },
    'anime-jp': { label: '🎌 abertura/encerramento de anime (japonês)', deezer: ['5206929684', '9016993522', '11225266244'] },
    'rap-br': { label: '🎤 rap nacional', deezer: ['1114532087', '11881565941', '10191249702'] },
    'rap-intl': { label: '🎤 rap internacional', deezer: ['1677006641', '1996494362', '7274678124'] },
    // 2026-10-11: Top K-Pop, k-pop party, 3a e 2a geracao (editor K-Pop do Deezer)
    // block = artistKey de quem nao entra (pedido do dono: sem BTS, nem os solos dos integrantes)
    'kpop': { label: '🇰🇷 k-pop', deezer: ['4096400722', '7482846624', '11012274682', '10738561582'],
        block: ['bts', 'jungkook', 'jimin', 'v', 'rm', 'suga', 'agustd', 'jhope', 'jin'] },
    // Emo Essentials, is it emo?, Pop Punk Essentials (editor Rock do Deezer) + Emo Brasil 2000 (usuario)
    'emo': { label: '🖤 emo / pop punk', deezer: ['7780640082', '10415648522', '861202821', '8764605462'] },
};
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
const artistKey = name => name.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
    .split(/\s+(?:ft\.?|feat\.?|featuring|&|x)\s+|,/)[0].replace(/[^\p{L}\p{N}]+/gu, '');
// artista = o que vem antes de " - " no titulo ("Taylor Swift - Style"), que tambem cobre canal de
// gravadora (HollywoodRecordsVEVO postando "Miley Cyrus - The Climb"); sem isso, o canal sem
// " - Topic"/VEVO. Participacoes (ft./feat./&/,/x) saem: "Maroon 5 ft. Cardi B" conta como Maroon 5.
const artistOf = (title, channel) => {
    const dash = title.indexOf(' - ');
    return artistKey(dash > 0 ? title.slice(0, dash) : (channel ?? '').replace(/ - topic$/i, '').replace(/vevo$/i, ''));
};
const ytdlpJson = async (args) => {
    const { stdout } = await run(getExecutable(), ['--flat-playlist', '-J', ...args], { timeout: 60_000, maxBuffer: 32 * 1024 * 1024 });
    return (JSON.parse(stdout).entries ?? []).filter(e => e.id && e.id.length === 11);
};
const mixOf = videoId => ytdlpJson(['--playlist-end', '50', `https://www.youtube.com/watch?v=${videoId}&list=RD${videoId}`]);
const deezerTracks = async (playlistId) => {
    const response = await fetch(`https://api.deezer.com/playlist/${playlistId}`, { signal: AbortSignal.timeout(15_000) });
    const data = await response.json();
    return (data.tracks?.data ?? []).map(t => ({
        query: `${t.artist.name} - ${t.title_short}`,
        artist: artistKey(t.artist.name),
        duration: t.duration,
        title: `${t.artist.name} - ${t.title_short}`,
    }));
};
// o resultado de busca com a duracao mais proxima da faixa do Deezer (evita versao ao vivo/estendida)
const searchYouTube = async (track) => {
    const entries = await ytdlpJson([`ytsearch3:${track.query}`]);
    const fits = entries.filter(e => !e.duration || e.duration <= MAX_SECONDS);
    fits.sort((a, b) => Math.abs((a.duration ?? 0) - track.duration) - Math.abs((b.duration ?? 0) - track.duration));
    return fits[0]?.id;
};
const settle = (promise, label) => promise.catch(error => {
    console.warn(`[muse] radio: ${label} falhou`, error.message);
    return [];
});
let default_1 = class default_1 {
    constructor(playerManager, getSongs) {
        this.slashCommand = new SlashCommandBuilder()
            .setName('radio')
            .setDescription('adiciona à fila músicas de um estilo, as mais tocadas ou parecidas com as últimas')
            .addStringOption(option => option
            .setName('estilo')
            .setDescription('o que tocar')
            .setRequired(true)
            .addChoices(...Object.entries(GENRES).map(([value, g]) => ({ name: g.label, value })), { name: '🏆 mais tocadas do servidor', value: 'top' }, { name: '👤 meu top (as que eu mais pedi)', value: 'meu-top' }, { name: '📻 parecidas com as últimas que tocaram', value: 'parecidas' }))
            .addIntegerOption(option => option
            .setName('quantidade')
            .setDescription('quantas músicas adicionar [padrão: 10]')
            .setMinValue(3)
            .setMaxValue(25));
        this.requiresVC = true;
        this.playerManager = playerManager;
        this.getSongs = getSongs;
    }
    async resolveId(id) {
        try {
            const [songs] = await this.getSongs.getSongs(songLink(id), 1, false);
            if (songs.length > 0 && !songs[0].isLive && songs[0].length <= MAX_SECONDS) {
                return songs[0];
            }
        }
        catch (error) {
            console.warn(`[muse] radio: nao resolvi ${id}`, error.message);
        }
        return null;
    }
    // candidatos ja em ordem de preferencia -> ate `wanted` musicas resolvidas, aplicando os filtros
    async pick(candidates, wanted, exclude, usedArtists, chosenWords) {
        const resolved = [];
        for (let i = 0; i < candidates.length && resolved.length < wanted; i += 4) {
            const batch = [];
            for (const c of candidates.slice(i, i + 4)) {
                const w = words(c.title ?? '');
                if ((c.id && exclude.has(c.id)) || exclude.has(queryKey(c)) || (c.duration && c.duration > MAX_SECONDS)
                    || (c.artist && usedArtists.has(c.artist)) || chosenWords.some(x => similar(x, w))) {
                    continue;
                }
                // reserva antes de resolver: o lote corre em paralelo
                if (c.artist) {
                    usedArtists.add(c.artist);
                }
                chosenWords.push(w);
                batch.push((async () => {
                    const id = c.id ?? await searchYouTube(c).catch(() => undefined);
                    if (!id || exclude.has(id)) {
                        return null;
                    }
                    exclude.add(id);
                    const song = await this.resolveId(id);
                    if (song) {
                        song.servedKeys = [id, queryKey(c)].filter(Boolean);
                    }
                    return song;
                })());
            }
            for (const song of await Promise.all(batch)) {
                if (song && resolved.length < wanted) {
                    resolved.push(song);
                }
            }
        }
        return resolved;
    }
    async execute(interaction) {
        const guildId = interaction.guild.id;
        const style = interaction.options.getString('estilo') ?? 'parecidas';
        const wanted = interaction.options.getInteger('quantidade') ?? 10;
        const seeds = recentSongs(guildId, SEEDS).filter(s => s.url.length === 11);
        if (style === 'parecidas' && seeds.length === 0) {
            throw new Error('ainda não tocou nenhuma música do YouTube para servir de base');
        }
        const player = this.playerManager.get(guildId);
        if (player.isQueueStale()) {
            player.resetStaleQueue();
        }
        const [targetVoiceChannel] = getMemberVoiceChannel(interaction.member) ?? getMostPopularVoiceChannel(interaction.guild);
        await interaction.deferReply();
        const isTop = style === 'top' || style === 'meu-top';
        const exclude = new Set(isTop ? [] : [...recentSongs(guildId, 50).map(s => s.url), ...servedKeys(guildId)]);
        for (const s of [player.getCurrent(), ...player.getQueue()]) {
            if (s?.url) {
                exclude.add(s.url);
            }
        }
        let resolved;
        let header;
        if (isTop) {
            const mine = style === 'meu-top';
            const top = topSongs(guildId, wanted, mine ? interaction.member.user.id : null);
            if (top.length === 0) {
                throw new Error(mine ? 'ainda não tenho nenhuma música pedida por você' : 'ainda não há músicas tocadas para montar o top');
            }
            resolved = (await Promise.all(top.filter(e => !exclude.has(e.url)).map(e => this.resolveId(e.url)))).filter(Boolean);
            header = mine ? `🏆 **Top ${resolved.length} de ${interaction.member.displayName}**` : `🏆 **Top ${resolved.length} do servidor**`;
        }
        else if (style === 'parecidas') {
            const mixes = await Promise.all(seeds.map(s => settle(mixOf(s.url), `mix de ${s.url}`)));
            // intercala os mixes: 1o de cada, 2o de cada...
            const candidates = [];
            for (let i = 0; mixes.some(m => i < m.length); i++) {
                for (const mix of mixes) {
                    const e = mix[i];
                    if (e) {
                        candidates.push({ id: e.id, title: e.title, duration: e.duration, artist: artistOf(e.title ?? '', e.channel) });
                    }
                }
            }
            const usedArtists = new Set(seeds.map(s => artistOf(s.title, '')).filter(Boolean));
            resolved = await this.pick(candidates, wanted, exclude, usedArtists, seeds.map(s => words(s.title)));
            const short = t => (t.length > 60 ? t.slice(0, 59) + '…' : t).replace(/[[\]]/g, '');
            header = `📻 **Rádio** — ${resolved.length} parecidas com ${seeds.map(s => `*${short(s.title)}*`).join(', ')}`;
        }
        else {
            const genre = GENRES[style];
            if (!genre) {
                throw new Error(`estilo desconhecido: ${style}`);
            }
            const lists = await Promise.all([
                ...(genre.deezer ?? []).map(id => settle(deezerTracks(id), `deezer ${id}`)),
                ...(genre.youtube ?? []).map(id => settle(ytdlpJson([`https://www.youtube.com/playlist?list=${id}`]), `playlist ${id}`)
                    .then(entries => entries.map(e => ({ id: e.id, title: e.title, duration: e.duration, artist: artistOf(e.title ?? '', e.channel) })))),
            ]);
            // a mesma faixa em duas playlists conta uma vez so
            const seen = new Set();
            const candidates = shuffle(lists.flat()).filter(c => !genre.block?.includes(c.artist)).filter(c => {
                const key = c.id ?? c.query.toLowerCase();
                return seen.has(key) ? false : (seen.add(key), true);
            });
            resolved = await this.pick(candidates, wanted, exclude, new Set(), []);
            header = `📻 **Rádio ${genre.label}**`;
        }
        if (resolved.length === 0) {
            throw new Error('não consegui montar a rádio agora, tente de novo em instantes');
        }
        if (!isTop) {
            markServed(guildId, resolved.flatMap(song => song.servedKeys ?? []));
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
                fromRadio: true,
            });
        }
        // PAUSED sem audioPlayer = parou por erro de playback, nao por /pause: sem isso a
        // radio so enfileirava e nada tocava (2026-10-03)
        const stalled = player.status === STATUS.PAUSED && !player.audioPlayer;
        if (needsConnection || player.status === STATUS.IDLE || stalled) {
            await player.play();
        }
        console.log(`[muse] radio guild=${guildId} estilo=${style} adicionadas=${resolved.length}/${wanted}`);
        const short = t => (t.length > 60 ? t.slice(0, 59) + '…' : t).replace(/[[\]]/g, '');
        const lines = resolved.map((song, i) => `\`${String(i + 1).padStart(2)}.\` [${short(song.title)}](<${songLink(song.url)}>)`);
        await interaction.editReply(`${header} — ${resolved.length} adicionada(s) à fila:\n${lines.join('\n')}`.slice(0, 2000));
    }
};
default_1 = __decorate([
    injectable(),
    __param(0, inject(TYPES.Managers.Player)),
    __param(1, inject(TYPES.Services.GetSongs))
], default_1);
export default default_1;
