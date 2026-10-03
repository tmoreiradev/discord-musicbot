# Playlist do Spotify: desde 2026 o Spotify responde 403 em /v1/playlists/{id}/tracks para
# token de app (client credentials) — metadados vem, faixas nao. Quando isso acontece,
# cai para a pagina publica de embed (ver dist/utils/spotify-embed.js), que devolve a lista
# no mesmo formato que o spotify-web-api-node devolveria.
# Aplicado SOMENTE em dist/services/spotify-api.js.
s|import shuffle from 'array-shuffle';|import shuffle from 'array-shuffle';\nimport { getPlaylistTracksFromEmbed } from '../utils/spotify-embed.js';|
s|this.spotify.getPlaylistTracks(uri.id, { limit: 50 })|this.spotify.getPlaylistTracks(uri.id, { limit: 50 }).catch(async () => ({ body: await getPlaylistTracksFromEmbed(uri.id) }))|
