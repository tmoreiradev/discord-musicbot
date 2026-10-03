// Fonte de audio alternativa: em vez de entregar a URL do googlevideo ao ffmpeg, deixa o
// proprio yt-dlp buscar os bytes e escrever em stdout.
//
// Existe porque a URL recem-extraida nem sempre serve na hora: medido em 2026-08-29 no
// video AiVlM7J_6zw, o ffmpeg pedindo no instante 0 leva HTTP 403 (5 de 5 tentativas),
// enquanto a MESMA URL responde 206 a partir de ~5 s depois da extracao. O yt-dlp baixando
// o mesmo video no instante 0 funciona sempre (3 de 3), porque trata a corrida internamente.
// So aparece em video cuja URL sai pelo cliente WEB_EMBEDDED_PLAYER.
import {spawn} from 'child_process';

const YT_DLP_ARGS = [
  '-f', 'bestaudio/best',
  '-S', 'proto:https',
  '--no-playlist',
  '--no-warnings',
  '--no-cache-dir',
  '-o', '-',
];

const getExecutable = () => process.env.YT_DLP_PATH?.trim()
  || process.env.MUSE_BUNDLED_YT_DLP_PATH?.trim()
  || 'yt-dlp';

export const createYtDlpStream = videoUrl => {
  const child = spawn(getExecutable(), [...YT_DLP_ARGS, videoUrl], {stdio: ['ignore', 'pipe', 'pipe']});
  const {stdout} = child;

  // so o fim do stderr interessa: e de la que sai a linha de ERROR quando o download falha
  let stderrTail = '';
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', chunk => {
    stderrTail = (stderrTail + chunk).slice(-2000);
  });

  const failStream = error => {
    if (!stdout.readableEnded && !stdout.destroyed) {
      stdout.destroy(error);
    }
  };

  child.on('error', error => {
    failStream(error);
  });

  child.on('close', code => {
    // saida != 0 depois de o stream ter terminado e o SIGPIPE de quando o ffmpeg fecha a
    // entrada; nesse caso o audio ja saiu inteiro e failStream nao faz nada, de proposito.
    if (code !== 0) {
      const lastLine = stderrTail.trim().split('\n').pop() ?? '';
      failStream(new Error(`yt-dlp exited with code ${code}${lastLine ? `: ${lastLine}` : ''}`));
    }
  });

  // se quem consome desiste (skip, stop, troca de musica), nao deixa o yt-dlp orfao
  stdout.on('close', () => {
    if (child.exitCode === null && child.signalCode === null) {
      child.kill('SIGKILL');
    }
  });

  return stdout;
};

export default createYtDlpStream;
