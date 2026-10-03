// Teste do /radio sem Discord: comando real do container DI, interaction e player falsos.
// Uso: cp tests-radio.mjs data/test-radio.mjs &&
//      docker exec -e DATABASE_URL=file:/data/db.sqlite muse node /data/test-radio.mjs
const {default: container} = await import('file:///usr/app/dist/inversify.config.js');
const {TYPES} = await import('file:///usr/app/dist/types.js');

const cmd = container.getAll(TYPES.Command).find(c => c.slashCommand.name === 'radio');
if (!cmd) throw new Error('comando radio nao registrado');

const added = [];
cmd.playerManager = {get: () => ({
  voiceConnection: {}, status: 'PLAYING',
  isQueueStale: () => false, resetStaleQueue() {},
  getCurrent: () => null, getQueue: () => [],
  ensureVoiceConnectionReady: async () => {}, connect: async () => {}, play: async () => {},
  add: song => added.push(song),
})};

let reply = '';
const t0 = Date.now();
await cmd.execute({
  guild: {id: '<guild-id>', channels: {cache: new Map()}},
  channel: {id: 'test'},
  // type 2 = ChannelType.GuildVoice
  member: {user: {id: 'test'}, voice: {channel: {id: 'v', type: 2, members: []}}},
  options: {getInteger: () => null},
  deferReply: async () => {},
  editReply: async r => { reply = r; },
});
console.log(`ok em ${((Date.now() - t0) / 1000).toFixed(1)} s, ${added.length} enfileiradas`);
console.log(reply);
process.exit(added.length >= 5 ? 0 : 1);
