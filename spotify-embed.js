// Spotify stopped serving playlist tracks to app-only (client-credentials) tokens:
// GET /v1/playlists/{id}/tracks answers 403 Forbidden even for a public playlist the
// credential owner created, and the playlist object no longer carries tracks.total.
// The public embed page still ships the track list inside its __NEXT_DATA__ blob, so it
// is used as a fallback. The returned shape mirrors spotify-web-api-node's
// getPlaylistTracks response body so the caller needs no other change.
const findTrackList = value => {
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findTrackList(item);
      if (found) {
        return found;
      }
    }

    return null;
  }

  if (value && typeof value === 'object') {
    if (Array.isArray(value.trackList)) {
      return value.trackList;
    }

    for (const item of Object.values(value)) {
      const found = findTrackList(item);
      if (found) {
        return found;
      }
    }
  }

  return null;
};

export const getPlaylistTracksFromEmbed = async playlistId => {
  const response = await fetch(`https://open.spotify.com/embed/playlist/${playlistId}`, {
    headers: {'user-agent': 'Mozilla/5.0'},
  });

  if (!response.ok) {
    throw new Error(`Spotify embed page for ${playlistId} returned ${response.status}`);
  }

  const html = await response.text();
  const match = /<script id="__NEXT_DATA__" type="application\/json">(.*?)<\/script>/s.exec(html);

  if (!match) {
    throw new Error(`Spotify embed page for ${playlistId} carried no __NEXT_DATA__ block`);
  }

  const trackList = findTrackList(JSON.parse(match[1]));

  if (!trackList || trackList.length === 0) {
    throw new Error(`Spotify embed page for ${playlistId} carried no track list`);
  }

  console.log(`[muse] spotify playlist ${playlistId}: Web API refused the tracks, fell back to the embed page (${trackList.length} tracks)`);

  return {
    items: trackList.map(track => ({
      track: {
        name: track.title,
        artists: [{name: (track.subtitle ?? '').split(',')[0].trim()}],
      },
    })),
    next: null,
  };
};
