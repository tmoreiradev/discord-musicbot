# Log de uma linha por /play: guarda a query crua, quantas faixas ela virou e como estava
# a fila. Sem isso nao da para saber, depois do fato, se um "a playlist voltou" veio de um
# link com &list= ou de outra causa. Aplicado SOMENTE em dist/services/add-query-to-queue.js.
# Os colchetes do destructuring sao escapados (\[ \]) — em regex seriam classe de caractere.
s|let \[newSongs, extraMsg\] = await this.getSongs.getSongs(query, playlistLimit, shouldSplitChapters);|let [newSongs, extraMsg] = await this.getSongs.getSongs(query, playlistLimit, shouldSplitChapters); console.log('[muse] addToQueue guild=' + guildId + ' query=' + query + ' songs=' + newSongs.length + ' queueSize=' + player.queueSize() + ' wasPlaying=' + wasPlayingSong);|
