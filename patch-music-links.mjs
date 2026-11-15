// Duas melhorias no caminho "link de servico de musica -> busca no YouTube":
//
// 1. Escolha do video pela duracao. O Muse buscava "titulo" "artista" no YouTube e pegava o
//    primeiro resultado, que muitas vezes e versao ao vivo/estendida (2026-10-25: "Teoria do Caos"
//    do Pecaos saiu um video de 11:02). Agora a faixa vem com a duracao do Spotify/Deezer/Apple e o
//    search() ranqueia os 10 resultados com o rankAudioFallbackCandidates do proprio Muse (titulo e
//    artista batendo, sem cover/live/remix inesperado, duracao a +-25%, prefere canal "- Topic" e
//    "official audio"). Sem candidato aprovado, fica o primeiro resultado como antes.
// 2. Links curtos (spotify.link, link.deezer.com) e links do Deezer e Apple Music, via
//    utils/music-links.js.
//
// Aplicado por node pelo mesmo motivo do patch-stale-queue: cada trecho tem que existir
// exatamente uma vez, senao o build aborta (protege contra atualizacao da imagem do Muse).
import {readFileSync, writeFileSync} from 'fs';

const dir = process.argv[2] ?? 'dist';

const patch = (file, edits) => {
  let source = readFileSync(`${dir}/${file}`, 'utf8');

  for (const [label, from, to] of edits) {
    const occurrences = source.split(from).length - 1;
    if (occurrences !== 1) {
      throw new Error(`patch "${label}" em ${file}: esperava 1 ocorrencia do trecho de origem, achei ${occurrences}`);
    }

    source = source.replace(from, to);
  }

  writeFileSync(`${dir}/${file}`, source);
};

patch('services/spotify-api.js', [
  ['duracao da faixa do Spotify',
    `            artist: track.artists[0].name,
        };`,
    `            artist: track.artists[0].name,
            length: Math.round((track.duration_ms ?? 0) / 1000),
        };`],
]);

patch('services/youtube-api.js', [
  ['search ranqueado pela faixa original',
    `    async search(query, shouldSplitChapters) {
        const ids = await this.searchVideoIDs(query);
        if (ids.length === 0) {
            return [];
        }
        const videos = await this.getVideosByID(ids);
        const firstVideo = ids
            .map(id => videos.find(video => video.id === id))
            .find(Boolean);`,
    `    async search(query, shouldSplitChapters, original) {
        const ids = await this.searchVideoIDs(query);
        if (ids.length === 0) {
            return [];
        }
        const videos = await this.getVideosByID(ids);
        const ordered = ids
            .map(id => videos.find(video => video.id === id))
            .filter(Boolean);
        // faixa vinda do Spotify/Deezer/Apple: prefere o resultado com titulo, versao e duracao compativeis
        const best = original?.length > 0
            ? rankAudioFallbackCandidates({ ...original, url: '' }, ordered.flatMap(video => this.getMetadataFromVideo({ video, shouldSplitChapters: false }))).at(0)
            : undefined;
        const firstVideo = (best && ordered.find(video => video.id === best.url)) ?? ordered.at(0);`],
]);

patch('services/get-songs.js', [
  ['import music-links',
    `import * as spotifyURI from 'spotify-uri';`,
    `import * as spotifyURI from 'spotify-uri';
import { resolveMusicShortLink, isOtherMusicLink, getOtherMusicTracks } from '../utils/music-links.js';`],
  ['resolve link curto antes de tudo',
    `        query = query.replace(/(open\\.spotify\\.com\\/)intl-`,
    `        query = await resolveMusicShortLink(query);
        query = query.replace(/(open\\.spotify\\.com\\/)intl-`],
  ['ramo Deezer/Apple Music',
    `        else {
            const song = await this.httpLiveStream(query);`,
    `        else if (isOtherMusicLink(url)) {
            const [tracks, playlist, totalSongs] = await getOtherMusicTracks(url, playlistLimit);
            const [convertedSongs, nSongsNotFound] = await this.spotifyToYouTube(tracks, shouldSplitChapters, playlist);
            const notes = [];
            if (totalSongs > playlistLimit) {
                notes.push(\`amostra aleatória de \${playlistLimit} músicas\`);
            }
            if (nSongsNotFound !== 0) {
                notes.push(\`\${nSongsNotFound} não encontrada(s) no YouTube\`);
            }
            extraMsg = notes.join(' e ');
            newSongs.push(...convertedSongs);
        }
        else {
            const song = await this.httpLiveStream(query);`],
  ['busca passa a faixa original',
    `this.youtubeAPI.search(\`"\${track.name}" "\${track.artist}"\`, shouldSplitChapters)`,
    `this.youtubeAPI.search(\`"\${track.name}" "\${track.artist}"\`, shouldSplitChapters, { title: track.name, artist: track.artist, length: track.length ?? 0 })`],
]);
