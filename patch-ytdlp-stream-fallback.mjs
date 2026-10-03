// Fallback de fonte de audio quando o googlevideo responde 403 na URL recem-extraida.
//
// O caminho normal do Muse e: yt-dlp extrai a URL -> ffmpeg baixa dela. Medido em
// 2026-08-29 no video AiVlM7J_6zw, a URL nao serve no instante 0: o ffmpeg leva 403 em 5 de
// 5 tentativas, e a MESMA URL responde 206 a partir de ~5 s. Sem fonte de audio o player
// fica ocioso e o bot sai do canal sem tocar -- e como o erro chega depois de o stream ja
// ter sido resolvido, nem mensagem de erro aparece.
//
// O patch faz o getStream, ao ver 403 na primeira tentativa, refazer o createReadStream com
// os bytes vindos do proprio yt-dlp (createYtDlpStream), que no mesmo instante 0 funciona
// 3 de 3. Uma tentativa so; qualquer outro erro sobe como antes.
//
// Aplicado por node, e nao por sed como os outros patches, porque troca blocos de varias
// linhas: aqui vale mais a checagem exata do texto de origem do que a economia de
// ferramenta. Cada apply() aborta o build se o trecho de origem nao existir exatamente uma
// vez, que e o que protege contra uma atualizacao da imagem do Muse mudar esse codigo.
import {readFileSync, writeFileSync} from 'fs';

const file = process.argv[2] ?? 'dist/services/player.js';
let source = readFileSync(file, 'utf8');

const apply = (label, from, to) => {
  const occurrences = source.split(from).length - 1;
  if (occurrences !== 1) {
    throw new Error(`patch "${label}": esperava 1 ocorrencia do trecho de origem, achei ${occurrences}`);
  }

  source = source.replace(from, to);
};

// Ancora no fim da linha de import, nao na linha inteira: o Muse 2.11.8 passou a importar
// tambem getSoundCloudMediaSource na mesma linha e o texto completo deixou de bater.
apply('import do createYtDlpStream',
  "YtDlpMediaUnavailableError } from '../utils/yt-dlp.js';",
  "YtDlpMediaUnavailableError } from '../utils/yt-dlp.js';\nimport { createYtDlpStream } from '../utils/ytdlp-stream.js';",
);

apply('helper isForbiddenMediaUrl',
  'const getFfmpegStartupError = (error) => {',
  `// googlevideo negando a URL recem-extraida; o yt-dlp baixando o mesmo video funciona
export const isForbiddenMediaUrl = (error) => {
    const detail = error instanceof Error ? error.message : String(error);
    return /(?:HTTP error|Server returned) 403|403 Forbidden/i.test(detail);
};
const getFfmpegStartupError = (error) => {`,
);

apply('fonte alternativa no getStream',
  `        if (!ffmpegInput) {
            const mediaSource = await (song.source === MediaSource.SoundCloud
                ? getSoundCloudMediaSource(song.url)
                : getYouTubeMediaSource(song.url));
            ffmpegInput = mediaSource.url;
            // Don't cache livestreams or long videos
            const MAX_CACHE_LENGTH_SECONDS = 30 * 60; // 30 minutes
            shouldCacheVideo = !mediaSource.isLive && song.length < MAX_CACHE_LENGTH_SECONDS && !options.seek;`,
  // na segunda tentativa a extracao ja foi feita e falhou so na hora de buscar os bytes:
  // repeti-la custaria ~5 s a mais antes do primeiro pacote de audio, entao o yt-dlp
  // recebe a URL do video direto e o isLive vem da propria musica na fila.
  `        if (!ffmpegInput) {
            const mediaSource = options.viaYtDlpStream ? null : await (song.source === MediaSource.SoundCloud
                ? getSoundCloudMediaSource(song.url)
                : getYouTubeMediaSource(song.url));
            ffmpegInput = mediaSource === null ? createYtDlpStream(song.url) : mediaSource.url;
            // Don't cache livestreams or long videos
            const MAX_CACHE_LENGTH_SECONDS = 30 * 60; // 30 minutes
            const isLive = mediaSource === null ? Boolean(song.isLive) : mediaSource.isLive;
            shouldCacheVideo = !isLive && song.length < MAX_CACHE_LENGTH_SECONDS && !options.seek;`,
);

apply('sem headers e sem reconnect na fonte alternativa',
  `            ffmpegInputOptions.push(...[
                '-reconnect',
                '1',
                '-reconnect_streamed',
                '1',
                '-reconnect_delay_max',
                '5',
            ]);
            const headerOptions = this.buildFfmpegHeaderOptions(mediaSource.headers);
            ffmpegInputOptions.push(...headerOptions);`,
  `            if (!options.viaYtDlpStream) {
                ffmpegInputOptions.push(...[
                    '-reconnect',
                    '1',
                    '-reconnect_streamed',
                    '1',
                    '-reconnect_delay_max',
                    '5',
                ]);
                const headerOptions = this.buildFfmpegHeaderOptions(mediaSource.headers);
                ffmpegInputOptions.push(...headerOptions);
            }`,
);

apply('retry com a fonte alternativa',
  `        catch (error) {
            if (cachedEntry
                && error instanceof FfmpegMediaUnavailableError
                && error.reason === 'invalid-output') {`,
  `        catch (error) {
            if (!cachedEntry && !options.viaYtDlpStream && isForbiddenMediaUrl(error)) {
                console.warn(\`Media URL was refused with HTTP 403 for guild \${this.guildId} (\${getMediaIdentifierForLog(song)}); retrying with yt-dlp as the audio source.\`);
                return this.getStream(song, {...options, viaYtDlpStream: true});
            }
            if (cachedEntry
                && error instanceof FfmpegMediaUnavailableError
                && error.reason === 'invalid-output') {`,
);

writeFileSync(file, source);
console.log('patch-ytdlp-stream-fallback: ok');
