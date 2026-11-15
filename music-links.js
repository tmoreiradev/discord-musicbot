// Links que o Muse nao entende sozinho:
// - links curtos de compartilhamento (spotify.link, link.deezer.com, ...): seguem um redirect HTTP
//   ate o link longo; se a pagina nao redirecionar, o link longo e procurado no HTML;
// - Deezer e Apple Music: viram uma lista de faixas {name, artist, length} pelas APIs publicas
//   (api.deezer.com e itunes.apple.com, sem chave), e o get-songs converte cada faixa em busca no
//   YouTube pelo mesmo caminho do Spotify (spotifyToYouTube).
import shuffle from 'array-shuffle';

const SHORT_LINK_HOSTS = new Set(['spotify.link', 'spotify.app.link', 'link.deezer.com', 'deezer.page.link', 'dzr.page.link']);
const LONG_LINK = /https:\/\/(?:open\.spotify\.com\/(?:intl-[a-z-]+\/)?(?:track|album|playlist|artist)\/[A-Za-z0-9]{22}|www\.deezer\.com\/(?:[a-z]{2}\/)?(?:track|album|playlist)\/\d+)/;
const DEEZER_HOSTS = new Set(['www.deezer.com', 'deezer.com']);
const APPLE_HOSTS = new Set(['music.apple.com', 'itunes.apple.com']);

export const resolveMusicShortLink = async query => {
  let url;
  try {
    url = new URL(query);
  } catch {
    return query;
  }

  if (!SHORT_LINK_HOSTS.has(url.host)) {
    return query;
  }

  const response = await fetch(url, {headers: {'user-agent': 'Mozilla/5.0'}});
  if (LONG_LINK.test(response.url)) {
    return response.url;
  }

  // link invalido redireciona para a home, cujo HTML tem links de outras faixas: so procura sem redirect
  const found = new URL(response.url).host === url.host && LONG_LINK.exec(await response.text());
  if (!found) {
    throw new Error(`não consegui abrir o link curto ${query}`);
  }

  return found[0];
};

export const isOtherMusicLink = url => DEEZER_HOSTS.has(url.host) || APPLE_HOSTS.has(url.host);

const getJson = async url => {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} respondeu ${response.status}`);
  }

  return response.json();
};

const limitTracks = (tracks, limit) => tracks.length > limit ? shuffle(tracks).slice(0, limit) : tracks;

const getDeezerTracks = async url => {
  const match = /\/(track|album|playlist)\/(\d+)/.exec(url.pathname);
  if (!match) {
    throw new Error('link do Deezer não suportado (só faixa, álbum ou playlist)');
  }

  const [, type, id] = match;
  const body = await getJson(`https://api.deezer.com/${type}/${id}`);
  if (body.error) {
    throw new Error(`Deezer: ${body.error.message ?? 'não encontrado'}`);
  }

  const toTrack = track => ({name: track.title, artist: track.artist?.name ?? '', length: track.duration ?? 0});
  if (type === 'track') {
    return [[toTrack(body)], null];
  }

  // shortcut: so a primeira pagina de faixas que a API embute (ate 400 numa playlist); paginar se aparecer playlist maior
  return [body.tracks.data.map(toTrack), {title: body.title, source: body.link}];
};

const getAppleMusicTracks = async url => {
  if (url.pathname.includes('/playlist/')) {
    throw new Error('playlist do Apple Music não tem API pública; mande o link de uma música ou álbum');
  }

  const country = /^\/([a-z]{2})\//.exec(url.pathname)?.[1] ?? 'br';
  const trackId = url.searchParams.get('i') ?? (url.pathname.includes('/song/') ? url.pathname.split('/').pop() : null);
  const albumId = url.pathname.includes('/album/') ? url.pathname.split('/').pop() : null;
  if (!trackId && !albumId) {
    throw new Error('link do Apple Music não suportado (só música ou álbum)');
  }

  const body = await getJson(`https://itunes.apple.com/lookup?id=${trackId ?? albumId}&country=${country}${trackId ? '' : '&entity=song'}`);
  const tracks = body.results
    .filter(result => result.wrapperType === 'track')
    .map(result => ({name: result.trackName, artist: result.artistName, length: Math.round((result.trackTimeMillis ?? 0) / 1000)}));
  if (tracks.length === 0) {
    throw new Error('Apple Music: não encontrado');
  }

  const album = body.results.find(result => result.wrapperType === 'collection');
  return [tracks, trackId ? null : {title: album?.collectionName ?? 'Apple Music', source: url.href}];
};

// Devolve [faixas, playlist|null, total antes do limite]
export const getOtherMusicTracks = async (url, playlistLimit) => {
  const [tracks, playlist] = DEEZER_HOSTS.has(url.host) ? await getDeezerTracks(url) : await getAppleMusicTracks(url);
  return [limitTracks(tracks, playlistLimit), playlist, tracks.length];
};
