# O Discord exige 1..100 caracteres em name e value de cada choice do autocomplete. O Muse
# monta "YouTube: <titulo>" / "Spotify: 💿 <album> - <artista>" sem cortar nem checar vazio,
# e um unico item fora da faixa derruba a resposta INTEIRA com
#   DiscordAPIError[50035] data.choices[N].name[BASE_TYPE_BAD_LENGTH]
# (visto em 2026-08-29 na busca "abertura digimon"), deixando o /play sem sugestao nenhuma.
# Trata os dois lados do limite no ultimo ponto antes do respond: corta o que passa de 100 e
# descarta o que ficaria vazio. O limite conta code points e .slice conta unidades UTF-16,
# entao emoji fora do BMP (o 💿 do Spotify) contaria dobrado: corta com Array.from.
s|^\( *\)await interaction.respond(suggestions);|\1const clampChoice = (text) => {\n\1    const chars = Array.from(String(text ?? ""));\n\1    return chars.length > 100 ? chars.slice(0, 99).join("") + "\\u2026" : chars.join("");\n\1};\n\1await interaction.respond(suggestions\n\1    .map(choice => ({\n\1        ...choice,\n\1        name: clampChoice(choice.name),\n\1        value: clampChoice(choice.value),\n\1    }))\n\1    .filter(choice => choice.name.length > 0 \&\& choice.value.length > 0));|
