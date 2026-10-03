// Test: a YouTube URL that carries BOTH a video id and &list= must queue the single
// video, not expand the whole playlist. Run inside the muse container:
//   docker exec muse node /data/test-getsongs.mjs
// get-songs.js cannot be imported directly (circular import through inversify.config
// leaves it in the TDZ), so pull the real instance out of the DI container instead.
const {default: container} = await import('file:///usr/app/dist/inversify.config.js');
const {TYPES} = await import('file:///usr/app/dist/types.js');
const getSongs = container.get(TYPES.Services.GetSongs);

const calls = [];
const youtubeAPI = {
  async getPlaylist(id) {
    calls.push(['playlist', id]);
    return [{title: 'playlist-track-1'}, {title: 'playlist-track-2'}];
  },
  async getVideo(url) {
    calls.push(['video', url]);
    return [{title: 'single-video'}];
  },
  async search(query) {
    calls.push(['search', query]);
    return [{title: 'search-result'}];
  },
};

getSongs.youtubeAPI = youtubeAPI;
getSongs.spotifyAPI = undefined;

const cases = [
  ['https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLxxxx&index=7', 'video'],
  ['https://youtu.be/dQw4w9WgXcQ?list=PLxxxx', 'video'],
  ['https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDAMVMdQw4w9WgXcQ', 'video'],
  ['https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'video'],
  ['https://www.youtube.com/playlist?list=PLxxxx', 'playlist'],
  ['https://youtube.com/playlist?list=PLxxxx', 'playlist'],
];

let failed = 0;
for (const [url, expected] of cases) {
  calls.length = 0;
  await getSongs.getSongs(url, 50, false);
  const got = calls[0]?.[0];
  const ok = got === expected;
  if (!ok) {
    failed++;
  }

  console.log(`${ok ? 'PASS' : 'FAIL'} ${url} -> ${got} (expected ${expected})`);
}

console.log(failed === 0 ? 'ALL PASS' : `${failed} FAILED`);
process.exit(failed === 0 ? 0 : 1);
