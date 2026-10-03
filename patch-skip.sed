# /skip: responder ao Discord ANTES de resolver a proxima musica (yt-dlp via WARP
# pode passar dos 3s do timeout de interacao -> "The application did not respond",
# mesmo com o skip funcionando). deferReply mostra "pensando..." e editReply conclui.
# O handler global de erros (dist/bot.js) ja checa interaction.deferred — seguro.
# Aplicado SOMENTE em dist/commands/skip.js.
s|await player.forward(numToSkip);|await interaction.deferReply(); const _skipped = player.getCurrent(); await player.forward(numToSkip);|
s|await interaction.reply({|await interaction.editReply({|
