// Descarta a fila quando o bot ficou fora do canal de voz por muito tempo.
//
// A fila do Muse vive so em memoria e sobrevive a saida do canal: a faixa que estava
// tocando continua sendo a "atual" indefinidamente. O /play seguinte ve
// getCurrentQueueEntryId() !== null, entra no ramo connect() + play() e RETOMA essa faixa,
// enfileirando a musica pedida atras dela.
//
// Medido em 2026-08-29: as 03:26 tocou
// "Digimon: Abertura 1 - Herois Digitais" (AiVlM7J_6zw) e o bot foi desconectado no meio
// (channel_id null, ready -> disconnected -> destroyed, "Playback buffer failed after
// playback began: Premature close"). As 21:53, 18h depois, um /play de
// "musica propaganda amoeba" logou wasPlaying=true e o que saiu no canal foi o Digimon de
// novo -- a busca tinha acertado, o primeiro resultado era o comercial da Amoeba.
//
// O patch marca o instante da desconexao e, no /play, zera a fila se o bot estiver fora do
// canal ha mais que STALE_QUEUE_MINUTES (padrao 30; 0 desliga o comportamento). Uma queda
// curta de rede continua retomando a fila como antes -- o corte e por tempo justamente para
// nao destruir uma playlist longa por causa de um blip.
//
// Aplicado por node, e nao por sed, pelo mesmo motivo do patch-ytdlp-stream-fallback:
// troca blocos de varias linhas e cada apply() aborta o build se o trecho de origem nao
// existir exatamente uma vez, que e o que protege contra uma atualizacao da imagem do Muse.
import {readFileSync, writeFileSync} from 'fs';

const playerFile = process.argv[2] ?? 'dist/services/player.js';
const addQueryFile = process.argv[3] ?? 'dist/services/add-query-to-queue.js';

const patch = (file, edits) => {
  let source = readFileSync(file, 'utf8');

  for (const [label, from, to] of edits) {
    const occurrences = source.split(from).length - 1;
    if (occurrences !== 1) {
      throw new Error(`patch "${label}" em ${file}: esperava 1 ocorrencia do trecho de origem, achei ${occurrences}`);
    }

    source = source.replace(from, to);
  }

  writeFileSync(file, source);
};

patch(playerFile, [
  ['campo disconnectedAt',
    `        this.disconnectTimer = null;
        this.channelToSpeakingUsers = new Map();`,
    `        this.disconnectTimer = null;
        // instante da ultima saida do canal de voz; null enquanto conectado (ver isQueueStale)
        this.disconnectedAt = null;
        this.channelToSpeakingUsers = new Map();`,
  ],

  ['marca a saida do canal',
    `        this.voiceActivitySessionGeneration++;
        if (this.voiceConnection) {
            if (this.status === STATUS.PLAYING) {`,
    `        this.voiceActivitySessionGeneration++;
        if (this.voiceConnection) {
            this.disconnectedAt = Date.now();
            if (this.status === STATUS.PLAYING) {`,
  ],

  // connect() chama disconnect() antes de entrar aqui quando ja havia conexao, entao a
  // marca so pode ser limpa depois disso, e nao no topo do metodo.
  // no Muse 2.11.8 o join vive dentro do laco de connectWithRetries(), um nivel mais fundo
  ['limpa a marca ao reconectar',
    `            this.voiceConnection = voiceConnection;
            this.currentChannel = channel;`,
    `            this.voiceConnection = voiceConnection;
            this.disconnectedAt = null;
            this.currentChannel = channel;`,
  ],

  ['metodos isQueueStale / resetStaleQueue',
    `    stop() {
        this.disconnect();`,
    `    staleQueueTimeoutMs() {
        const minutes = Number.parseInt(process.env.STALE_QUEUE_MINUTES ?? '30', 10);
        return Number.isFinite(minutes) && minutes >= 0 ? minutes * 60 * 1000 : 30 * 60 * 1000;
    }
    // true quando o bot esta fora do canal ha tempo demais e ainda carrega uma faixa atual:
    // retomar essa faixa e o que fazia o /play tocar outra musica que nao a pedida.
    isQueueStale() {
        const timeoutMs = this.staleQueueTimeoutMs();
        return timeoutMs > 0
            && this.voiceConnection === null
            && this.disconnectedAt !== null
            && this.getCurrent() !== null
            && Date.now() - this.disconnectedAt >= timeoutMs;
    }
    resetStaleQueue() {
        const idleMinutes = Math.round((Date.now() - this.disconnectedAt) / 60000);
        console.log('[muse] fila descartada por inatividade guild=' + this.guildId + ' idleMinutes=' + idleMinutes + ' queueSize=' + this.queue.length);
        this.queuePosition = 0;
        this.queue = [];
        this.currentQueueEntryVersion++;
        this.disconnectedAt = null;
        this.status = STATUS.PAUSED;
        this.loopCurrentSong = false;
        this.loopCurrentQueue = false;
        this.nowPlaying = null;
        this.positionInSeconds = 0;
    }
    stop() {
        this.disconnect();`,
  ],
]);

patch(addQueryFile, [
  // antes de getCurrentQueueEntryId(), que e o que decide entre retomar e comecar do zero
  ['descarte da fila velha no /play',
    `        const player = this.playerManager.get(guildId);
        const currentQueueEntryId = player.getCurrentQueueEntryId();`,
    `        const player = this.playerManager.get(guildId);
        if (player.isQueueStale()) {
            player.resetStaleQueue();
        }
        const currentQueueEntryId = player.getCurrentQueueEntryId();`,
  ],
]);

console.log('patch-stale-queue: ok');
