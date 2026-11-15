// Contagem de execucoes por servidor, para o /top10.
//
// Guardado em JSON no volume /data (o Muse nao registra historico nenhum: a tabela do
// Prisma so tem settings/favoritos/cache). Uma execucao = uma faixa que comecou do inicio
// (playWithAttempt); resume, seek e loop da faixa atual nao contam. A mesma faixa so conta
// de novo depois de 6 h (antes era 60 s e um /loop-queue de uma faixa so chegou a 34
// "execucoes" numa noite); faixas enfileiradas pelo /radio so atualizam `last` (sementes do
// /radio parecidas e filtro de recentes), nao contam (o top se realimentava).
import fs from 'fs';

const FILE = process.env.PLAY_STATS_PATH || '/data/play-stats.json';
const DEDUPE_MS = 6 * 60 * 60_000;
const TOP_MIN_COUNT = 2;
let stats = null;

const load = () => {
  if (stats === null) {
    try {
      stats = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    } catch {
      stats = {};
    }
  }

  return stats;
};

const save = () => {
  fs.writeFileSync(FILE + '.tmp', JSON.stringify(stats));
  fs.renameSync(FILE + '.tmp', FILE);
};

export const songLink = url => (url.length === 11 ? 'https://www.youtube.com/watch?v=' + url : url);

export const recordPlay = (guildId, song) => {
  try {
    if (!song || song.isLive || !song.url) {
      return;
    }

    const guild = load()[guildId] ??= {};
    const entry = guild[song.url] ??= {title: song.title, url: song.url, count: 0, last: 0};
    const now = Date.now();
    // last = ultima vez que tocou (semente do /radio parecidas); counted = ultima que contou
    if (!song.fromRadio && now - (entry.counted ?? entry.last) >= DEDUPE_MS) {
      entry.count++;
      entry.counted = now;
    }

    // por usuario (estilo "meu-top" do /radio): mesma regra de 6 h, contada para quem pediu
    const user = song.requestedBy;
    if (user && !song.fromRadio) {
      const mine = (entry.users ??= {})[user] ??= {count: 0, counted: 0};
      if (now - mine.counted >= DEDUPE_MS) {
        mine.count++;
        mine.counted = now;
      }
    }

    entry.last = now;
    entry.title = song.title;
    save();
  } catch (error) {
    console.warn('[muse] play-stats: falha ao registrar', error);
  }
};

// faixa com 1 execucao nao e "top": o resto da lista virava desempate por recencia
// userId: so as execucoes de faixas que esse usuario pediu
export const topSongs = (guildId, n = 10, userId = null) => Object.values(load()[guildId] ?? {})
  .map(e => ({...e, count: userId ? e.users?.[userId]?.count ?? 0 : e.count}))
  // por usuario o historico e curto: 1 pedido ja entra (empate = mais recente)
  .filter(e => e.count >= (userId ? 1 : TOP_MIN_COUNT))
  .sort((a, b) => b.count - a.count || b.last - a.last)
  .slice(0, n);

// as n faixas distintas tocadas mais recentemente (para o /radio)
export const recentSongs = (guildId, n = 3) => Object.values(load()[guildId] ?? {})
  .sort((a, b) => b.last - a.last)
  .slice(0, n);
