# sadhana-tracker-telegram-bot

A Telegram bot for tracking daily sadhana (spiritual practice) progress. The bot stores logs in a SQLite database and can show charts or interact with a simple virtual assistant.

## Setup

1. Install Python 3.11 or newer.
2. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the repository root and set at least your bot token:
   ```
   BOT_TOKEN=<telegram bot token>
   ```
   If you plan to use the virtual assistant, also set `OPENAI_API_KEY` with your OpenAI key.

## Running the bot

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and set the required values:
   - `BOT_TOKEN` – Telegram bot token
   - `OPENAI_API_KEY` – OpenAI API key

Initialize the database and start the bot:
```bash
python bot.py
```
Interact with the bot in Telegram using commands like `/log`, `/progress` and `/chart`.

## Optional: load the knowledge base

If you have additional reference materials for the assistant, load them into the knowledge base using `load_kb.py`. Specify JSON files for one or more categories:
```bash
python load_kb.py --hatha Йогасаны.json --hatha "Сурья Крийя.json" \
                 --general "Общие вопросы.json"
```
Run the script again if you want to add more files later. This step is optional and only needed for the virtual assistant feature.
=======
This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.


