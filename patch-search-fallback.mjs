// Busca por texto com fallback no yt-dlp logado.
//
// 2026-10-30: "/play rap eduardo" dava "no songs found". A API de dados do YouTube devolve
// totalResults 0 para essa frase (qualquer type/safeSearch/regionCode), enquanto o site acha dezenas
// de videos e "eduardo rap" funciona. yt-dlp sem cookie tambem recebe 0; com o cookie da conta
// secundaria (YT_DLP_COOKIES_PATH) acha. Entao: se a API devolver 0 ids, busca de novo com
// "ytsearch10:" no yt-dlp usando o mesmo jar temporario do Muse. O resto (getVideosByID, ranking)
// segue igual, so muda de onde vem a lista de ids.
//
// Aplicado por node como os outros .mjs: cada trecho tem que existir exatamente uma vez.
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

patch('utils/yt-dlp.js', [
  ['searchYouTubeIDs',
    `export const getExecutable = () => {`,
    `export const searchYouTubeIDs = async (query, limit = 10) => withTemporaryCookies(async (cookiesPath) => {
    const { execFile } = await import('child_process');
    const { promisify } = await import('util');
    const args = ['--flat-playlist', '--print', 'id', ...(cookiesPath ? ['--cookies', cookiesPath] : []), \`ytsearch\${limit}:\${query}\`];
    const { stdout } = await promisify(execFile)(getExecutable(), args, { timeout: 30_000 });
    return stdout.split('\\n').map(line => line.trim()).filter(id => id.length === 11);
});
export const getExecutable = () => {`],
]);

patch('services/youtube-api.js', [
  ['import searchYouTubeIDs',
    `import getYouTubeID from 'get-youtube-id';`,
    `import getYouTubeID from 'get-youtube-id';
import { searchYouTubeIDs } from '../utils/yt-dlp.js';`],
  ['fallback no searchVideoIDs',
    `        return items
            .map(item => item.id.videoId)
            .filter(Boolean);`,
    `        const ids = items
            .map(item => item.id.videoId)
            .filter(Boolean);
        if (ids.length > 0) {
            return ids;
        }
        // a API as vezes devolve 0 para uma frase que o site acha (ver patch-search-fallback.mjs)
        return searchYouTubeIDs(query).catch(error => {
            console.warn(\`[muse] busca yt-dlp falhou para "\${query}"\`, error.message);
            return [];
        });`],
]);
