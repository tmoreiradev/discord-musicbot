// Contagem de execucoes por servidor, para o /top10.
//
// Guardado em JSON no volume /data (o Muse nao registra historico nenhum: a tabela do
// Prisma so tem settings/favoritos/cache). Uma execucao = uma faixa que comecou do inicio
// (playWithAttempt); resume, seek e loop da faixa atual nao contam. Mesma faixa de novo em
// menos de 60 s nao conta (retentativa de stream depois de 403 nao vira "duas execucoes").
import fs from 'fs';

const FILE = process.env.PLAY_STATS_PATH || '/data/play-stats.json';
const DEDUPE_MS = 60_000;
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
    if (now - entry.last < DEDUPE_MS) {
      return;
    }

    entry.count++;
    entry.last = now;
    entry.title = song.title;
    save();
  } catch (error) {
    console.warn('[muse] play-stats: falha ao registrar', error);
  }
};

export const topSongs = (guildId, n = 10) => Object.values(load()[guildId] ?? {})
  .sort((a, b) => b.count - a.count || b.last - a.last)
  .slice(0, n);

// as n faixas distintas tocadas mais recentemente (para o /radio)
export const recentSongs = (guildId, n = 3) => Object.values(load()[guildId] ?? {})
  .sort((a, b) => b.last - a.last)
  .slice(0, n);
