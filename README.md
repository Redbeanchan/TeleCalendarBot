# TeleCalendarBot — Windows/Conda pilot

This guide runs the entire pilot on one Windows PC:

```text
Telegram -> Python bot in an isolated Conda environment
                     |-> SQLite in data\assistant.db
                     |-> Google Calendar over OAuth
                     `-> Ollama/Qwen on this PC at 127.0.0.1:11434
```

The mini-PC deployment is retired. Do not start another copy of the bot there:
Telegram long polling permits only one active process per bot token.

Conda isolates Python and its packages. Ollama is a separate Windows application
because it needs direct access to the NVIDIA driver/GPU. Project data and secrets
remain inside this repository's ignored `data`, `secrets`, and `.env` paths.

## 1. Items you need

Before starting, obtain:

1. The repository URL: `https://github.com/Redbeanchan/TeleCalendarBot.git`.
2. Your Telegram bot token from the verified **@BotFather** account.
3. Your personal numeric Telegram user ID (not the bot ID).
4. A Google OAuth **Desktop app** JSON credential for a project with Google
   Calendar API enabled.
5. Windows 10/11, an RTX 5070 Ti driver, and internet access.

Never post the token or either Google JSON file in chat, logs, or GitHub.

## 2. Install Git

1. Download **Git for Windows** from <https://git-scm.com/download/win>.
2. Run the installer and accept its defaults.
3. Close and reopen PowerShell.
4. Verify:

```powershell
git --version
```

If the command is not recognized, restart Windows and try again.

## 3. Install Miniconda

1. Open the official Conda Windows installation page:
   <https://docs.conda.io/projects/conda/en/latest/user-guide/install/windows.html>.
2. Download **Miniconda Windows x86_64**.
3. Run the installer.
4. Select **Just Me**.
5. Accept the default install directory.
6. Leave “register Miniconda as the default Python” unchecked; the project uses
   its named environment explicitly.
7. Finish installation.
8. From the Start menu, open **Anaconda Prompt (Miniconda3)**. Use this prompt
   for every command below unless this guide explicitly says otherwise.
9. Verify:

```bat
conda --version
conda list
```

Anaconda Prompt avoids PowerShell activation-policy problems. Advanced users
may run `conda init powershell`, close PowerShell, reopen it, and use PowerShell
instead.

## 4. Install and verify the NVIDIA driver

1. Install the current NVIDIA Game Ready or Studio driver for the RTX 5070 Ti.
2. Restart Windows when requested.
3. Open Anaconda Prompt and run:

```bat
nvidia-smi
```

The output must identify the RTX 5070 Ti. If `nvidia-smi` fails, fix the driver
before installing a model.

## 5. Install Ollama on Windows

Use the official installer at <https://ollama.com/download/windows>, or run the
official command in a normal PowerShell window:

```powershell
irm https://ollama.com/install.ps1 | iex
```

After installation, close and reopen Anaconda Prompt and verify:

```bat
ollama --version
```

Ollama runs outside Conda and exposes its API only on Windows loopback by
default. Do not add a router port-forward or a Windows Firewall inbound rule for
port 11434.

## 6. Download and test the model

Start with Qwen3 14B, which provides substantially better intent extraction than
the tiny model previously used:

```bat
ollama pull qwen3:14b
ollama run qwen3:14b "Return only JSON with a status field whose value is ok."
```

Press `Ctrl+C` after it replies. Check the model and API:

```bat
ollama list
ollama ps
powershell -NoProfile -Command "Invoke-RestMethod http://127.0.0.1:11434/api/tags"
```

During inference, `ollama ps` should show GPU use. If 14B does not fit fully on
the GPU or is unstable, use `ollama pull qwen3:8b` and later set
`OLLAMA_MODEL=qwen3:8b`. Do not choose a model name ending in `:cloud`; this
project is intended to use local inference with no token charges.

## 7. Clone the project

In Anaconda Prompt:

```bat
cd /d "%USERPROFILE%\Documents"
git clone https://github.com/Redbeanchan/TeleCalendarBot.git
cd TeleCalendarBot
```

If the folder already exists, use:

```bat
cd /d "%USERPROFILE%\Documents\TeleCalendarBot"
git pull
```

Confirm you are in the correct folder:

```bat
dir
```

You should see `environment.yml`, `requirements.txt`, `app`, and `scripts`.

## 8. Create the isolated Conda environment

From the repository directory:

```bat
conda env create -f environment.yml
conda activate telecalendarbot
python --version
where python
```

Expected:

* Python reports 3.12.x.
* `where python` lists a path containing `envs\telecalendarbot` first.

This environment contains only Python 3.12, pip, and this project's pinned
packages. Never use `pip install` for this project unless
`telecalendarbot` appears at the beginning of the prompt.

To update the environment after a future `git pull`:

```bat
conda activate telecalendarbot
conda env update -f environment.yml --prune
```

## 9. Create private local directories and configuration

Still in the repository directory:

```bat
if not exist data mkdir data
if not exist secrets mkdir secrets
copy .env.windows.example .env
notepad .env
```

Replace these two placeholder values:

```dotenv
TELEGRAM_BOT_TOKEN=replace-with-botfather-token
TELEGRAM_ALLOWED_USER_ID=123456789
```

Keep the local Windows settings:

```dotenv
TIMEZONE=Asia/Singapore
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:14b
DATABASE_PATH=./data/assistant.db
GOOGLE_CREDENTIALS_PATH=./secrets/google_credentials.json
GOOGLE_TOKEN_PATH=./secrets/google_token.json
```

Save and close Notepad. `.env`, `data`, and `secrets` are Git-ignored.

### Create a Telegram bot/token

If you do not already have one:

1. Open Telegram and message the verified **@BotFather**.
2. Send `/newbot`.
3. Choose a display name and a unique username ending in `bot`.
4. Copy the token into `.env` after `TELEGRAM_BOT_TOKEN=`.

To obtain your numeric user ID, message **@userinfobot**, press Start, and copy
the integer it reports into `TELEGRAM_ALLOWED_USER_ID`. This must be your user
ID, not the bot username or bot ID. Only that user is authorized by the app.

## 10. Put Google OAuth credentials in place

If you already securely backed up `google_credentials.json`, copy it to:

```text
%USERPROFILE%\Documents\TeleCalendarBot\secrets\google_credentials.json
```

Otherwise:

1. Open <https://console.cloud.google.com/> in a browser.
2. Select or create the `TeleCalendarBot` project.
3. Open **APIs & Services -> Library** and enable **Google Calendar API**.
4. Open **Google Auth Platform** and configure Branding/Audience.
5. Select **External** for an ordinary Gmail account.
6. Add your own Google account as a test user.
7. Under Data Access, add the Calendar scope.
8. Under Clients, create an OAuth client of type **Desktop app**.
9. Download its JSON file.
10. Rename it to `google_credentials.json` and move it into the `secrets`
    directory shown above.

Verify without printing the secret:

```bat
if exist secrets\google_credentials.json (echo Google credentials found) else (echo Google credentials MISSING)
```

## 11. Perform one-time Google authorization

Make sure the prompt begins with `(telecalendarbot)`, then run:

```bat
python -m scripts.google_auth --credentials .\secrets\google_credentials.json --token .\secrets\google_token.json
```

1. Copy the full URL printed in the prompt.
2. Open it on this Windows PC.
3. Sign in to the Google account added as a test user.
4. If Google shows its testing/unverified warning, verify it is your own project
   and click **Continue**.
5. Approve Calendar access.
6. Wait for the browser success page and terminal confirmation.

No SSH tunnel is required. The OAuth request advertises and binds the temporary
callback to `127.0.0.1:8080`; it must never advertise `0.0.0.0`. The callback
stops after authorization. Verify:

```bat
if exist secrets\google_token.json (echo Google authorization complete) else (echo Google token MISSING)
```

## 12. Validate configuration before starting

Run all four checks:

```bat
conda activate telecalendarbot
python -c "from app.config import get_settings; s=get_settings(); print('Configuration OK:', s.ollama_model, s.database_path)"
python -c "import httpx; r=httpx.get('http://127.0.0.1:11434/api/tags', timeout=10); print('Ollama HTTP:', r.status_code)"
python -m compileall -q app scripts
python -m pytest -q
```

Expected: configuration prints `qwen3:14b`, Ollama prints `200`, compilation is
silent, and tests pass. Tests mock external services and create no real Calendar
events.

## 13. Start the assistant

Run:

```bat
cd /d "%USERPROFILE%\Documents\TeleCalendarBot"
conda activate telecalendarbot
python -m app.bot
```

Keep this window open. Wait for:

```text
Assistant started with long polling
```

Stop the bot cleanly with `Ctrl+C`. While piloting manually, Windows sleep,
shutdown, logout, closing this window, or exiting the process stops the bot.

## 14. Test each feature in order

In Telegram:

1. Send `/health`; expect `Assistant is running`.
2. Send `remind me in 5 minutes to test Windows`; wait for delivery.
3. Send `what's on tomorrow?`; expect Calendar events or an empty result.
4. Send `dinner with Ryan next Wednesday at 8pm`.
5. Confirm that **Yes**, **No**, and **Update details** appear. Press **No** first
   and verify no event exists.
6. Send it again and press **Update details**. Reply naturally with a correction
   such as `6 October`; verify the revised proposal preserves its title/time.
7. Press **Yes** on the revised proposal and verify one event exists.
8. Press Yes again if possible and verify no duplicate is created.
9. Stop the bot, restart it, and verify a future reminder survives in SQLite.

The bot never exposes schema names such as `date_expression`. Location is
optional. If a follow-up supplies only a missing title, the bot combines it with
the date and time already understood from the preceding message.

If Telegram reports `Conflict`, another copy of the bot is still polling. Stop
the other Python process/container before starting this one.

## 15. Normal daily commands

Start:

```bat
cd /d "%USERPROFILE%\Documents\TeleCalendarBot"
conda activate telecalendarbot
python -m app.bot
```

Stop: press `Ctrl+C`.

Update:

```bat
cd /d "%USERPROFILE%\Documents\TeleCalendarBot"
git pull
conda activate telecalendarbot
conda env update -f environment.yml --prune
python -m app.bot
```

Remove only the isolated Python environment:

```bat
conda deactivate
conda env remove -n telecalendarbot
```

This does not remove Ollama, models, source files, SQLite, or secrets.

## 16. Backups

While the bot is running, create a consistent SQLite backup using SQLite's
backup API—not a blind copy of the WAL database:

```bat
python -c "import sqlite3; s=sqlite3.connect('data/assistant.db'); d=sqlite3.connect('data/assistant.backup.db'); s.backup(d); d.close(); s.close()"
```

Copy `data\assistant.backup.db` and `secrets` to encrypted offline storage.
Treat `.env` and both Google JSON files as secrets.

## 17. Security and cloud migration notes

* Ollama stays on loopback; never expose port 11434 publicly.
* The LLM returns untrusted structured intent and cannot call tools directly.
* Python enforces the Telegram user ID and Calendar confirmations.
* Calendar reads are automatic; every write requires an inline confirmation.
* Do not commit `.env`, `data`, or `secrets`.
* Do not automate Windows startup until the manual pilot is stable.
* For a later cloud migration, keep SQLite and secrets on persistent encrypted
  storage, inject environment values at runtime, and keep the LLM endpoint
  private. The Docker files remain as a migration starting point.

## Troubleshooting

* **`conda` not recognized:** use Anaconda Prompt (Miniconda3), not an old shell.
* **Wrong Python:** activate `telecalendarbot`, then run `where python`.
* **Ollama refused:** start Ollama and check `/api/tags` as shown above.
* **Slow inference:** run `ollama ps`; use `qwen3:8b` if 14B is not GPU-resident.
* **Bot ignores you:** verify your personal numeric Telegram ID in `.env`.
* **Google error:** verify both files under `secrets` and rerun authorization.
* **Port 8080 occupied:** close the previous OAuth helper and retry.
* **Past/ambiguous date:** give a specific future day and time.
