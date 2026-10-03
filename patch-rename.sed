# Renomeia comandos: /queue -> /playlist e /shuffle -> /embaralhar (pedido do usuario,
# 2026-08-08) e traduz as descricoes/opcoes que aparecem no seletor do Discord.
# Aplicado SOMENTE em dist/commands/queue.js e dist/commands/shuffle.js.
# Os nomes sao re-registrados no Discord a cada boot do bot.
s|.setName('queue')|.setName('playlist')|
s|.setDescription('show the current queue')|.setDescription('mostra a fila atual')|
s|.setDescription('page of queue to show \[default: 1\]')|.setDescription('página da fila a mostrar [padrão: 1]')|
s|.setDescription('how many items to display per page \[default: 10, max: 30\]')|.setDescription('itens por página [padrão: 10, máx: 30]')|
s|.setName('shuffle')|.setName('embaralhar')|
s|.setDescription('shuffle the current queue')|.setDescription('embaralha a fila atual')|
