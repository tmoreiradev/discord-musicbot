// /top10 (2026-10-02): conta cada faixa que comeca a tocar e registra o comando novo.
//
// - player.js: depois do startTrackingPosition(0) do playWithAttempt (faixa nova saindo do
//   inicio; resume/seek/loop passam por outros caminhos) chama recordPlay (play-stats.js).
// - inversify.config.js: importa e registra commands/radio.js junto dos outros. O /top10
//   virou o estilo "top" do /radio em 2026-10-03 e o comando proprio saiu.
//
// Mesmo esquema dos outros .mjs: cada trecho de origem tem que existir exatamente uma vez,
// senao o build aborta (protege contra o FROM muse:latest mudar o codigo por baixo).
import {readFileSync, writeFileSync} from 'fs';

const playerFile = process.argv[2] ?? 'dist/services/player.js';
const inversifyFile = process.argv[3] ?? 'dist/inversify.config.js';

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
  ['import do play-stats',
    `import { buildPlayingMessageEmbed } from '../utils/build-embed.js';`,
    `import { buildPlayingMessageEmbed } from '../utils/build-embed.js';
import { recordPlay } from '../utils/play-stats.js';`,
  ],

  ['conta a execucao',
    `            this.nowPlayingQueueEntryVersion = currentQueueEntryVersion;
            this.startTrackingPosition(0);`,
    `            this.nowPlayingQueueEntryVersion = currentQueueEntryVersion;
            this.startTrackingPosition(0);
            recordPlay(this.guildId, currentSong);`,
  ],
]);

patch(inversifyFile, [
  ['import do radio',
    `import Volume from './commands/volume.js';`,
    `import Volume from './commands/volume.js';
import Radio from './commands/radio.js';`,
  ],

  // desde o Muse 2.12.0 a lista termina em Help, nao em Volume
  ['registra o radio',
    `    Help,
].forEach(command => {`,
    `    Help,
    Radio,
].forEach(command => {`,
  ],
]);
