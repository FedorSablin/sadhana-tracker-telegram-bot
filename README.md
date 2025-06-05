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

Initialize the database and start the bot:
```bash
python bot.py
```
Interact with the bot in Telegram using commands like `/log`, `/progress` and `/chart`.

## Optional: load the knowledge base

If you have additional reference materials for the assistant, you can load them into the database with:
```bash
python load_kb.py path/to/articles.csv
```
This step is optional and only needed for the virtual assistant feature.
