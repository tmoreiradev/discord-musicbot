# Adiciona a URL crua do video abaixo do titulo no embed "Tocando agora"
# (dist/utils/build-embed.js), pronta para copiar num /play futuro.
# currentlyPlaying.url pode ser so o ID (11 chars) ou a URL completa.
# Anchor: a linha standalone do titulo no template (a da fila tem outra forma).
s~^\( *\)\*\*\${getSongTitle(currentlyPlaying)}\*\*$~\1**${getSongTitle(currentlyPlaying)}**\n\1${currentlyPlaying.url.length === 11 ? 'https://www.youtube.com/watch?v=' + currentlyPlaying.url : currentlyPlaying.url}~
