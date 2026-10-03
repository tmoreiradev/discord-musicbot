# Traducao pt-BR dos textos visiveis do Muse (aplicado sobre dist/ no build).
# Se um pattern deixar de casar apos update do upstream, o texto volta em ingles
# silenciosamente — rodar: docker exec muse grep -rn "u betcha" dist/ para auditar.

# --- respostas dos comandos (frases completas primeiro, prefixo generico depois)
s|u betcha, stopped|parado, fila limpa e desconectado|g
s|u betcha, disconnected|desconectado|g
s|u betcha, ||g
s|the stop-and-go light is now red|pausado|g
s|the stop-and-go light is now green|voltando a tocar|g
s|clearer than a field after a fresh harvest|fila limpa|g
# _skipped vem do patch-skip.sed (capturado antes do forward)
s~content: 'keep \\'er movin\\''~content: _skipped ? `pulando **${_skipped.title}**` : 'pulando'~

# --- add-query-to-queue.js (mensagens do /play)
# titulo vira hyperlink; <> na URL suprime o preview/unfurl do Discord
s~\*\*\${firstSong.title}\*\*~[**${firstSong.title}**](<${firstSong.url.length === 11 ? 'https://www.youtube.com/watch?v=' + firstSong.url : firstSong.url}>)~g
s|added to the${addToFrontOfQueue ? ' front of the' : ''} queue|adicionada à${addToFrontOfQueue ? ' frente da' : ''} fila|g
s|and ${newSongs.length - 1} other songs were added to the queue|e mais ${newSongs.length - 1} músicas foram adicionadas à fila|g
s|and current track skipped|e a faixa atual foi pulada|g
s|resuming playback|retomando a reprodução|g

# --- build-embed.js (embeds de Now Playing / fila)
s|Now Playing|Tocando agora|g
s|'Paused'|'Pausado'|g
s|Requested by:|Pedido por:|g
s|Source: |Fonte: |g
s|Up next:|A seguir:|g
s|'In queue'|'Na fila'|g
s|'Total length'|'Duração total'|g
s|'Page'|'Página'|g
s|} out of ${maxQueuePage}|} de ${maxQueuePage}|g
s|'1 song'|'1 música'|g
s|} songs|} músicas|g
s|(loop on)|(repetição ligada)|g
s|Queued songs|Fila de espera|g
s|'live'|'ao vivo'|g

# --- prefixo de erro
s|ope: |erro: |g

# --- patch: titulo do "Tocando agora" ganha posicao na fila (x de y).
# Depende das traducoes acima ja aplicadas na mesma linha; player.queue e
# player.queuePosition sao internos do Player (dist/services/player.js) — auditar em update.
s|? 'Tocando agora' : 'Pausado')|? `Tocando agora (${player.queuePosition + 1} de ${player.queue.length})` : 'Pausado')|
