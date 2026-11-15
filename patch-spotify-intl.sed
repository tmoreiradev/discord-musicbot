# Link do Spotify com locale (open.spotify.com/intl-pt/track/...): a lib spotify-uri
# nao reconhece o segmento /intl-xx/ e falha com "Could not determine type". Remove o
# segmento da query antes de qualquer parse (a query segue ate spotify-api.js).
# Aplicado SOMENTE em dist/services/get-songs.js.
s|^\( *\)// Test if it's a complete URL$|\1query = query.replace(/(open\\.spotify\\.com\\/)intl-[a-z-]+\\//i, '$1');\n&|
