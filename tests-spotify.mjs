// Test: the Spotify credentials resolve a public playlist into queueable tracks.
// The YouTube search is stubbed so the run doesn't hammer the API/WARP tunnel.
//   docker exec muse node /data/test-spotify.mjs <spotify-url>
const {default: container} = await import('file:///usr/app/dist/inversify.config.js');
const {TYPES} = await import('file:///usr/app/dist/types.js');
const getSongs = container.get(TYPES.Services.GetSongs);

if (!getSongs.spotifyAPI) {
  console.log('FAIL: spotifyAPI not wired — credentials missing from the container env');
  process.exit(1);
}

// ThirdParty fires the client-credentials grant from its constructor without awaiting it,
// so grab a token explicitly instead of racing that.
// ThirdParty fires the client-credentials grant from its constructor without awaiting it,
// and it is NOT bound as a singleton — so token the very client SpotifyAPI holds, not a
// fresh ThirdParty of our own.
const auth = await getSongs.spotifyAPI.spotify.clientCredentialsGrant();
getSongs.spotifyAPI.spotify.setAccessToken(auth.body.access_token);
console.log(`token ok, expires_in=${auth.body.expires_in}s`);

getSongs.youtubeAPI = {
  async search(query) {
    return [{title: query, url: 'dQw4w9WgXcQ', source: 0, length: 200}];
  },
};

const url = process.argv[2] ?? 'https://open.spotify.com/playlist/3yzQ9A2cW1jLGf4wF9kHgL';
const [songs, extraMsg] = await getSongs.getSongs(url, 50, false);

console.log(`songs=${songs.length} extraMsg="${extraMsg}"`);
for (const song of songs.slice(0, 5)) {
  console.log(` - ${song.title}`);
}

console.log(songs.length > 0 ? 'PASS' : 'FAIL');
process.exit(songs.length > 0 ? 0 : 1);
