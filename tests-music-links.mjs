// Teste: links de Spotify (com /intl-xx/), Deezer, Apple Music e links curtos viram faixas do
// YouTube com duracao proxima da original. Busca de verdade no YouTube (~100 unidades de cota
// por faixa), por isso playlistLimit 2.
//   docker exec -e DATABASE_URL=file:/data/db.sqlite muse node /data/tests-music-links.mjs [url ...]
// (sem o DATABASE_URL o cache do YouTube falha e toda busca vira "nao encontrada")
const {default: container} = await import('file:///usr/app/dist/inversify.config.js');
const {TYPES} = await import('file:///usr/app/dist/types.js');
const getSongs = container.get(TYPES.Services.GetSongs);

const auth = await getSongs.spotifyAPI.spotify.clientCredentialsGrant();
getSongs.spotifyAPI.spotify.setAccessToken(auth.body.access_token);

const fmt = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
const urls = process.argv.length > 2 ? process.argv.slice(2) : [
  'https://open.spotify.com/intl-pt/track/7hpvBLbZeVTw7dxdq0mc1J?si=b79f292d7be141d0',
  'https://www.deezer.com/br/track/3135556',
  'https://www.deezer.com/album/302127',
  'https://music.apple.com/br/album/daft-punk/877651699?i=877651737',
  'https://music.apple.com/br/playlist/x/pl.u-abc',
  'https://spotify.link/abc123XYZ',
];

let failed = 0;
for (const url of urls) {
  try {
    const [songs, extraMsg] = await getSongs.getSongs(url, 2, false);
    console.log(`OK   ${url}\n     ${songs.length} faixa(s)${extraMsg ? ` — ${extraMsg}` : ''}`);
    failed += songs.length === 0 ? 1 : 0;
    for (const s of songs) {
      console.log(`     - ${s.title} | ${s.artist} | ${fmt(s.length)} | ${s.url}`);
    }
  } catch (error) {
    console.log(`ERRO ${url}\n     ${error.message}`);
    failed += /playlist do Apple|link curto/.test(error.message) ? 0 : 1;
  }
}

console.log(failed ? `FAIL (${failed})` : 'PASS');
process.exit(failed ? 1 : 0);
