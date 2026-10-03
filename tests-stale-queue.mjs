import Player from '/usr/app/dist/services/player.js';

const p = new Player(null, 'g1', null);
const assert = (label, cond) => {
  if (!cond) {
    console.log('FAIL ' + label);
    process.exitCode = 1;
  } else {
    console.log('ok   ' + label);
  }
};

assert('fila vazia nao e stale', p.isQueueStale() === false);
p.queue = [{title: 'x'}];
p.queuePosition = 0;
assert('conectado nunca e stale (disconnectedAt null)', p.isQueueStale() === false);
p.disconnectedAt = Date.now() - (5 * 60 * 1000);
assert('5 min fora nao e stale', p.isQueueStale() === false);
p.disconnectedAt = Date.now() - (18 * 60 * 60 * 1000);
assert('18 h fora e stale', p.isQueueStale() === true);
p.resetStaleQueue();
assert('reset esvazia a fila', p.queue.length === 0 && p.getCurrent() === null);
assert('reset limpa a marca', p.disconnectedAt === null && p.isQueueStale() === false);
process.env.STALE_QUEUE_MINUTES = '0';
p.queue = [{title: 'x'}];
p.disconnectedAt = Date.now() - (18 * 60 * 60 * 1000);
assert('STALE_QUEUE_MINUTES=0 desliga', p.isQueueStale() === false);
