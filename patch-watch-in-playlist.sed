# /play com link copiado de dentro de uma playlist (watch?v=XXX&list=PL...&index=N):
# o Muse ignorava o v= e enfileirava a playlist inteira, entao a playlist antiga voltava
# a tocar no lugar da musica pedida. Agora so trata como playlist quando a URL NAO tem
# video id (pagina /playlist?list=..., ou watch sem v=). Para enfileirar a playlist toda,
# use a URL /playlist?list=... .
# Aplicado SOMENTE em dist/services/get-songs.js.
# O '&' e escapado (\&) porque no lado direito do s||| o sed o expande para o match inteiro.
s|if (url.searchParams.get('list')) {|if (url.searchParams.get('list') \&\& !url.searchParams.get('v') \&\& !(url.host === 'youtu.be' \&\& url.pathname.length > 1)) {|
