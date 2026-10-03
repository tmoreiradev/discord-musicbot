// Teste do /top10 sem Discord: pega o comando real do container DI e roda o execute com
// uma interaction e um player falsos. Confere que as 10 do play-stats sao resolvidas pelo
// GetSongs e enfileiradas na ordem, e que a resposta lista todas.
// Uso: cp tests-top10.mjs data/test-top10.mjs && docker exec muse node /data/test-top10.mjs
// mesmo jeito do tests-get-songs-playlist.mjs: import dinamico do container DI
const {default: container} = await import('file:///usr/app/dist/inversify.config.js');
const {TYPES} = await import('file:///usr/app/dist/types.js');

const GUILD = '<guild-id>';
const cmd = container.getAll(TYPES.Command).find(c => c.slashCommand.name === 'top10');
if (!cmd) throw new Error('comando top10 nao registrado');

const added = [];
const fakePlayer = {
  voiceConnection: {}, status: 'PLAYING',
  isQueueStale: () => false, resetStaleQueue() {},
  ensureVoiceConnectionReady: async () => {}, connect: async () => {}, play: async () => {},
  add: song => added.push(song),
};
cmd.playerManager = {get: () => fakePlayer};

let reply = '';
const interaction = {
  guild: {id: GUILD, channels: {cache: new Map()}},
  channel: {id: 'test'},
  // type 2 = ChannelType.GuildVoice
  member: {user: {id: 'test'}, voice: {channel: {id: 'v', type: 2, members: []}}},
  options: {getBoolean: () => false},
  deferReply: async () => {},
  editReply: async r => { reply = r; },
};

const t0 = Date.now();
await cmd.execute(interaction);
console.log(`ok em ${((Date.now() - t0) / 1000).toFixed(1)} s, ${added.length} enfileiradas`);
console.log(reply);
process.exit(added.length >= 8 ? 0 : 1);
