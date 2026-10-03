# Corrige o destino do anuncio automatico de "Tocando agora" (dist/services/player.js).
#
# Problema 1: this.currentChannel e o canal de VOZ (setado em joinVoiceChannel), entao o
# anuncio de troca natural ia para o chat embutido do canal de voz, nao para o #playlist.
# Fix: usar addedInChannelId da musica atual (o canal de texto onde o /play foi dado),
# com fallback para o chat de voz se o fetch falhar (ex.: sem permissao de ver o canal).
#
# Problema 2: advancePastUnplayableTrack (faixa bloqueada por copyright/410) troca de
# musica sem anunciar. Fix: replicar o anuncio apos o play(), com try/catch para nunca
# derrubar o player por falha de anuncio.
#
# Nota: o bot precisa de "Ver canal" + "Enviar mensagens" no canal de texto de destino —
# respostas de comando sao webhook e nao precisam, mas channel.send() precisa.

/async advancePastUnplayableTrack/,/async tryAgeRestrictedAudioFallback/ s~await this.play();~await this.play(); try { const s = await getGuildSettings(this.guildId); const cs = this.getCurrent(); if (s.autoAnnounceNextSong \&\& this.currentChannel \&\& cs) { const ch = (cs.addedInChannelId ? await this.currentChannel.guild.channels.fetch(cs.addedInChannelId).catch(() => null) : null) || this.currentChannel; await ch.send({ embeds: [buildPlayingMessageEmbed(this)] }).catch(() => null); } } catch {}~

s~await this.currentChannel.send({~const _annCh = (currentSong.addedInChannelId ? await this.currentChannel.guild.channels.fetch(currentSong.addedInChannelId).catch(() => null) : null) || this.currentChannel; await _annCh.send({~
