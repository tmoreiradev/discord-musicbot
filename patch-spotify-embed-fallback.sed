# Playlist do Spotify: desde 2026 o Spotify responde 403 em /v1/playlists/{id}/tracks para
# token de app (client credentials) — metadados vem, faixas nao. Quando isso acontece,
# cai para a pagina publica de embed (ver dist/utils/spotify-embed.js), que devolve a lista
# no mesmo formato que o spotify-web-api-node devolveria.
# Playlists da propria Spotify (editoriais/"This Is", id 37i9...) dao 404 tambem no
# GET /v1/playlists/{id}: o getPlaylist vira null e o titulo sai do embed (2026-11-15).
# Aplicado SOMENTE em dist/services/spotify-api.js.
s|import shuffle from 'array-shuffle';|import shuffle from 'array-shuffle';\nimport { getPlaylistTracksFromEmbed } from '../utils/spotify-embed.js';|
s|this.spotify.getPlaylistTracks(uri.id, { limit: 50 })|this.spotify.getPlaylistTracks(uri.id, { limit: 50 }).catch(async () => ({ body: await getPlaylistTracksFromEmbed(uri.id) }))|
s|await Promise.all(\[this.spotify.getPlaylist(uri.id),|await Promise.all([this.spotify.getPlaylist(uri.id).catch(() => ({ body: null })),|
s|const playlist = { title: playlistResponse.name, source: playlistResponse.href };|const playlist = playlistResponse ? { title: playlistResponse.name, source: playlistResponse.href } : { title: tracksResponse.name ?? 'Playlist do Spotify', source: url };|
