# discord-musicbot

Self-hosted [Muse](https://github.com/museofficial/muse) Discord music bot, with a few patches
applied at image build time, plus a [wireproxy](https://github.com/whyvl/wireproxy)
sidecar that routes YouTube traffic through a Cloudflare WARP tunnel so the bot works from a
datacenter IP without tripping YouTube's "Sign in to confirm you're not a bot" check.

The same bot token also drives two small cron scripts (plain Python, stdlib only, REST API
only — no second gateway connection, Muse is untouched): a weekly post with the game releases
of the week, and a post for every free-game giveaway.

Both containers use `network_mode: host`; the proxy listens on `127.0.0.1:25344` (SOCKS5) and
`127.0.0.1:25345` (HTTP). Any other service on the same host can reuse the tunnel. Images build
on x86_64 and aarch64.

## Layout

| File | What it does |
|---|---|
| `docker-compose.yml` | `wireproxy` (WARP tunnel) + `muse` (the bot). |
| `Dockerfile.muse` | Muse image + `deno` (yt-dlp needs it for YouTube's JS challenges) + yt-dlp **nightly** + `yt-dlp.conf` + the patches below. |
| `Dockerfile.wireproxy` | Downloads the official wireproxy release for the host architecture. |
| `yt-dlp.conf` | Installed as `/etc/yt-dlp.conf`: adds the `web_embedded` player client as a fallback for videos that bot-check the default clients. |
| `patch-*.sed`, `patch-*.mjs`, `l10n.sed`, `spotify-embed.js`, `ytdlp-stream.js` | Patches applied to Muse's compiled `dist/` at build time (see the comments in each file). |
| `tests-*.mjs` | Node tests for the patched modules. |
| `games-weekly.py` | Cron job: posts the week's game releases (from [IGDB](https://api-docs.igdb.com/)), top N by hype, with platforms and direct store links. |
| `free-games.py` | Cron job: posts free-game giveaways — Epic (store API), every other store via [GamerPower](https://www.gamerpower.com/api-read), and the monthly PlayStation Plus games (PlayStation Blog RSS). |
| `warp-watchdog.sh` | Cron job: if YouTube starts bot-checking the WARP exit IP, registers a new free WARP identity with `wgcf` and restarts the proxy. |
| `refresh-cookies.sh` | Optional cron job that keeps a YouTube cookie jar alive by letting another yt-dlp instance rewrite it. Only needed if you use cookies (disabled by default). |

Patches, in short: `/skip` defers the reply (avoids the 3 s interaction timeout); "now playing" is
announced in the text channel of the request; `/queue` → `/playlist`, `/shuffle` → `/embaralhar`;
a `watch?v=…&list=…` link plays only the video; one log line per `/play`; Spotify playlists fall
back to the embed page when the Web API returns 403 for app tokens; pt-BR strings; raw video URL
in the embed; a stale-queue fix and a yt-dlp stream fallback.

## Setup

1. Create the WARP profile with [wgcf](https://github.com/ViRb3/wgcf) and write
   `warp/wireproxy.conf` (WireGuard section from `wgcf-profile.conf`, plus the two listeners):

   ```ini
   [Socks5]
   BindAddress = 127.0.0.1:25344

   [http]
   BindAddress = 127.0.0.1:25345
   ```

2. `cp .env.example .env` and fill in:

   | Variable | Purpose |
   |---|---|
   | `DISCORD_BOT_TOKEN` | Bot token from the Discord developer portal. |
   | `GOOGLE_CLOUD_API` | YouTube Data API key (search). |
   | `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Optional, for Spotify links. |
   | `IGDB_CLIENT_ID` / `IGDB_CLIENT_SECRET` | For `games-weekly.py`: a Twitch application from dev.twitch.tv (client credentials). |
   | `GAMES_CHANNEL_ID` | Text channel for both game posts (`FREE_CHANNEL_ID` overrides it for giveaways). The bot needs View, Send and Embed Links there. |

3. `docker compose up -d --build`.
4. Cron:

   ```cron
   */10 * * * * /path/to/warp-watchdog.sh
   0 10 * * 1   /path/to/games-weekly.py          # Monday 10:00, releases Mon–Sun
   */30 * * * * /path/to/free-games.py
   ```

   Both Python scripts take `--dry-run` (print the embeds instead of posting);
   `games-weekly.py --week-of YYYY-MM-DD` picks another week. `free-games.py` remembers what it
   already posted in `state/free-games.json`; its **first run only records** the giveaways
   that are already active, so a new channel is not flooded.

`.env`, `warp/`, `data/` and `state/` are gitignored.

## Gotchas

- **yt-dlp must track the nightly channel.** Since mid-2026 the stable release cannot download
  YouTube audio for music/licensed content (no adaptive format without a PO token; the one
  client that returns one gets HTTP 403). `Dockerfile.muse` installs `--pre yt-dlp[default]`
  and `patch-ytdlp-nightly.sed` keeps Muse's own auto-update on the nightly channel too.
- **Some videos bot-check every default client regardless of IP.** Test a control video
  before blaming the tunnel; `yt-dlp.conf` falls back to `web_embedded`, which still works.
- **yt-dlp and ffmpeg must both go through the proxy.** googlevideo URLs are bound to the IP
  that requested them; proxying only the extractor breaks every play. The `*_PROXY` variables
  in the compose file cover both.
- **A googlevideo URL can 403 in the first seconds after extraction** and serve fine right
  after; that is YouTube, not the proxy.
- WARP's exit IP occasionally gets bot-checked under bursts; the watchdog rotates the identity.
  Its test video must extract **without** cookies, or it rotates every run.
- `FROM muse:latest` is not pinned: a rebuild can pull a new Muse, and the `.mjs` patches abort
  the build when an anchor no longer matches (on purpose — better a failed build than a patch
  in the wrong place).
- Discord answers **403** to REST calls with a browser `User-Agent`; use `DiscordBot (url, version)`.
- Store links in `games-weekly.py` are matched by URL domain, and only for the platforms
  releasing that week (a Switch 2 port does not get the old Steam link).
- `docker logs muse` may hang; read the container's JSON log file directly if that happens.
