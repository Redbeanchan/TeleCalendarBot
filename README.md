# TeleCalendarBot

Private single-user Telegram reminders and Google Calendar, interpreted locally by Ollama/Qwen. Deterministic Python—not the LLM—owns authorization, dates, persistence, confirmation, and external calls.

## Architecture and material decisions

```text
Telegram long polling -> non-root Python container
  -> authorized-user gate on every message/callback
  -> Ollama JSON -> Pydantic validation -> deterministic rules
  -> SQLite WAL in ./data
  -> Google Calendar OAuth token in ./secrets
Host Ollama binds only to the private 172.30.0.1 Compose bridge
```

Calendar reads are automatic. Writes cannot originate in the message handler: it stores a proposal, and only an authorized inline-button callback atomically claims it. A deterministic Google event ID makes creation retries idempotent. SQLite, not an in-memory scheduler, is authoritative for reminders.

Limitations/choices: `next Wednesday` is the Wednesday in the following Mon–Sun week; `this Wednesday` is in the current week and is rejected if past; bare `next week` is ambiguous. Proactive alerts use one configurable lead time. Telegram provides no send idempotency key, so there is a narrow crash window after Telegram accepts a reminder but before SQLite records success. Google/Telegram remain external services, but there is no hosted LLM, cloud deployment, or paid per-token API.

## Values and files you obtain manually

1. `TELEGRAM_BOT_TOKEN` from **@BotFather**.
2. Your numeric `TELEGRAM_ALLOWED_USER_ID`.
3. A Google OAuth **Desktop app** client file at `secrets/google_credentials.json`.
4. Ollama and local `qwen3:8b`.

Google may require a Cloud Console project to issue API credentials; this does not host the app. Docker/Compose are assumed installed.

## 1. Project setup

```bash
git clone <repository-url> telegram-assistant
cd telegram-assistant
mkdir -p data secrets
cp .env.example .env
chmod 700 data secrets && chmod 600 .env
sudo chown -R 10001:10001 data secrets
```

Edit `.env`. Keep container paths unchanged. UID 10001 is the non-root image user.

### Telegram and user ID

Create a bot using @BotFather `/newbot`. Obtain your ID from @userinfobot, or avoid a third party: message your new bot, run `curl "https://api.telegram.org/bot<TOKEN>/getUpdates"`, and read `message.from.id`. The URL/history contains the token; delete that history entry. Put the integer in `.env`. In a private chat this is also normally the proactive-alert chat ID.

## 2. Install and securely connect Ollama

Use Ollama's official Ubuntu installer, then pull/test Qwen:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:8b
ollama run qwen3:8b 'Return only JSON: {"status":"ok"}'
docker compose create
ip addr show | grep 172.30.0.1
```

Run `sudo systemctl edit ollama` and enter:

```ini
[Service]
Environment="OLLAMA_HOST=172.30.0.1:11434"
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
curl http://172.30.0.1:11434/api/tags
sudo ss -ltnp | grep 11434
```

`ss` must show `172.30.0.1:11434`, never `0.0.0.0`, `[::]`, LAN, or public addresses. The configured URL addresses this fixed bridge gateway directly. Verify container access:

```bash
docker compose run --rm telegram-assistant python -c \
 'import httpx; print(httpx.get("http://172.30.0.1:11434/api/tags").status_code)'
```

If `172.30.0.0/24` conflicts, choose an unused private `/24` in both Compose and `OLLAMA_HOST`, recreate the network, and re-verify. Never fix access by publicly binding Ollama.

Switch models without code changes:

```bash
ollama pull qwen3:4b
sed -i 's/^OLLAMA_MODEL=.*/OLLAMA_MODEL=qwen3:4b/' .env
docker compose restart telegram-assistant
```

Latency varies by quantization/load/thermals; measure rather than inventing a number:

```bash
for p in 'remind me tomorrow at 8pm to pay Amex' 'dinner with Ryan next wed 8pm' \
 "what's on tomorrow?" "okay confirm let's lock in 8pm dinner next wed"; do
 /usr/bin/time -f '%e seconds' curl -s http://172.30.0.1:11434/api/chat \
 -H 'Content-Type: application/json' \
 -d "{\"model\":\"qwen3:8b\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"$p\"}]}" >/dev/null
done
```

## 3. Google API and one-time OAuth

In Google Cloud Console: create/select a project; enable **Google Calendar API**; configure the OAuth consent screen (add yourself as test user if needed); create a **Desktop app** OAuth client; download it as `secrets/google_credentials.json`.

```bash
sudo chown 10001:10001 secrets/google_credentials.json
chmod 600 secrets/google_credentials.json
docker compose --profile tools run --rm --service-ports google-auth
```

Open the printed URL. The loopback-only callback writes persistent `secrets/google_token.json`. For a remote server, first establish `ssh -L 8080:127.0.0.1:8080 user@server`, run the command in that SSH session, and open the URL locally.

```bash
test -s secrets/google_token.json && echo 'token present'
chmod 600 secrets/google_token.json
```

`/secrets` is writable only so refreshed tokens persist. Neither secrets nor `.env` enters Git or the image context.

## 4. Build and operate

```bash
docker compose up -d --build                 # start/build
docker compose ps                            # status
docker compose logs -f telegram-assistant    # logs
docker compose restart telegram-assistant    # restart
docker compose down                          # stop
docker compose up -d                          # start again
git pull && docker compose up -d --build      # update/rebuild
```

`restart: unless-stopped` recovers from crashes, Docker restarts, and reboots. No application port, webhook, nginx, systemd Python service, Docker socket, or external DB exists. `down` does not delete bind-mounted `data/` or `secrets/`.

Try: `remind me tomorrow at 8pm to pay Amex`, `dinner with Ryan next Wed 8pm` (proposal only), `what's on tomorrow?`, and `dinner with Ryan next week` (clarification).

## Safe backup and restore

WAL mode means do not copy only the live DB. Use SQLite's online backup API:

```bash
mkdir -p backups
docker compose exec -T telegram-assistant python -c \
 'import sqlite3; s=sqlite3.connect("/data/assistant.db"); d=sqlite3.connect("/data/assistant.backup.db"); s.backup(d); d.close(); s.close()'
mv data/assistant.backup.db "backups/assistant-$(date -u +%Y%m%dT%H%M%SZ).db"
```

Back up `secrets/` separately to encrypted offline storage. Restore while stopped:

```bash
docker compose down
cp backups/assistant-YYYYMMDDTHHMMSS.db data/assistant.db
rm -f data/assistant.db-wal data/assistant.db-shm
sudo chown 10001:10001 data/assistant.db && chmod 600 data/assistant.db
docker compose up -d
```

## Development and tests

Tests use temporary DBs/mocks and never create real events:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
ruff check app scripts tests
```

## Troubleshooting

* **Ollama refused:** confirm network exists, `ss` shows only `172.30.0.1:11434`, and the container test returns 200.
* **Slow/timeout:** inspect `journalctl -u ollama`, raise `OLLAMA_TIMEOUT_SECONDS`, or select `qwen3:4b`.
* **Bot ignores you:** check the exact numeric ID/logs; unauthorized updates intentionally do nothing.
* **Permission denied:** `sudo chown -R 10001:10001 data secrets` and retain restrictive modes.
* **Google auth failure:** check both JSON files/readability, or rerun OAuth after revocation. Google failure does not kill the bot.
* **Expired proposal:** resend it within `PENDING_ACTION_TTL_MINUTES`; old/duplicate clicks cannot write twice.
* **Past/ambiguous date:** give an explicit future day/time; unsafe guesses are rejected.
* **No proactive alert:** check settings/token and the configured lead window. V1 skips all-day alerts.

## Layout

`app/` contains configuration, persistence, services, handlers, and entrypoint; `scripts/google_auth.py` handles OAuth; `tests/` is isolated; `data/` and `secrets/` are persistent ignored host mounts.
