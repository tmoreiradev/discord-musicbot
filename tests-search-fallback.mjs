// Teste do patch-search-fallback: a frase que a API devolve vazia tem que achar ids pelo yt-dlp.
// Uso: docker exec muse node /data/tests-search-fallback.mjs [dir do dist]
import assert from 'assert';

const dir = process.argv[2] ?? '/usr/app/dist';
const { searchYouTubeIDs } = await import(`${dir}/utils/yt-dlp.js`);
const ids = await searchYouTubeIDs('rap eduardo');
console.log(ids.length, ids.slice(0, 3));
assert.ok(ids.length > 0, 'ytsearch nao achou nada para "rap eduardo"');
assert.ok(ids.every(id => /^[\w-]{11}$/.test(id)), 'id fora do formato do YouTube');
console.log('OK');
