# Auto-update do Muse usa "pip install --upgrade yt-dlp[default]", ou seja, o canal
# STABLE. Em 2026-08-18 o stable (2026.07.04) parou de baixar audio do YouTube: so o
# cliente android_vr ainda devolve URL de formato adaptativo e o googlevideo responde
# HTTP 403 nesse cliente para a maior parte do conteudo (musica/licenciado); os demais
# clientes nao devolvem formato nenhum sem PO token. O nightly ja tem o contorno.
# Este patch poe --pre nos argumentos do pip para o auto-update seguir o canal nightly.
s/^\( *\)'yt-dlp\[default\]',/\1'--pre',\n\1'yt-dlp[default]',/
