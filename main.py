oldmain.py
import os
import datetime
from dotenv import load_dotenv
from openai import OpenAI
import telebot
import requests

load_dotenv()

client = OpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1"
)

bot = telebot.TeleBot(os.getenv("TELEGRAM_BOT_TOKEN"))
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))

@bot.message_handler(commands=['chatid'])
def get_chat_id(message):
    bot.reply_to(message, f"Chat ID: {message.chat.id}")

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "NBA Betting Bot is running. Use /chatid to get this chat's ID.")

def send_nba_bets():
    # determine date to request picks for: env `NBA_DATE`, first CLI arg, or today's date
    import sys
    date_override = os.getenv("NBA_DATE") or (sys.argv[1] if len(sys.argv) > 1 else None)
    date_str = date_override if date_override else datetime.date.today().strftime("%B %d, %Y")

    # Get NBA schedule and odds from The Odds API
    api_key = os.getenv('ODDS_API_KEY')
    if not api_key:
        print("ODDS_API_KEY not set in .env")
        slate = "Check real-time NBA schedule and odds for today's games."
        odds_str = "Unable to fetch odds; use real-time data."
    else:
        url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/odds?apiKey={api_key}&regions=us&markets=spreads,totals,h2h"
        try:
            response = requests.get(url, timeout=30)
            data = response.json()
            games = []
            odds_info = []
            for game in data:
                home = game['home_team']
                away = game['away_team']
                time = game['commence_time']  # ISO 8601
                # Convert to ET
                dt = datetime.datetime.fromisoformat(time.replace('Z', '+00:00'))
                et_time = dt.astimezone(datetime.timezone(datetime.timedelta(hours=-5))).strftime('%I:%M %p ET')
                games.append(f"{away} @ {home} ({et_time})")
                # Get odds from DraftKings
                for bookmaker in game['bookmakers']:
                    if bookmaker['key'] == 'draftkings':
                        spreads = {}
                        totals = {}
                        h2h = {}
                        for market in bookmaker['markets']:
                            if market['key'] == 'spreads':
                                for outcome in market['outcomes']:
                                    spreads[outcome['name']] = {'point': outcome['point'], 'price': outcome['price']}
                            elif market['key'] == 'totals':
                                for outcome in market['outcomes']:
                                    totals[outcome['name']] = outcome['price']
                            elif market['key'] == 'h2h':
                                for outcome in market['outcomes']:
                                    h2h[outcome['name']] = outcome['price']
                        if spreads or totals or h2h:
                            odds_info.append(f"{away} vs {home}: Spreads {spreads}, Totals {totals}, ML {h2h}")
                        break
            if games:
                slate = "Today's NBA slate: " + "; ".join(games)
            else:
                slate = "Check real-time NBA schedule and odds for today's games."
            if odds_info:
                odds_str = "Today's odds from The Odds API (DraftKings): " + "; ".join(odds_info)
            else:
                odds_str = "Unable to fetch odds; use real-time data."
        except Exception as e:
            print(f"Error fetching from The Odds API: {e}")
            slate = "Check real-time NBA schedule and odds for today's games."
            odds_str = "Unable to fetch odds; use real-time data."

    print(f"🤖 Calling NBA God DayoneNBA Bets for {date_str}...")

    # Use model from env if provided, otherwise default to a known valid model
    model_name = os.getenv("GROK_MODEL", "grok-4-1-fast-reasoning")

    prompt = f"""Activate full Expert Mode for NBA betting on {date_str}.
Fuse historian, All-NBA player, statistical guru mindsets.
Strict style: Primary 5pt max teasers (tease favorites down), secondary strong fav MLs only with +EV.
First, confirm today's NBA slate using current data (games, times ET, key matchups).
{slate}
{odds_str}
Then debate internally and give top picks (aim 3+ if edges exist).
Output format: Start with 🔥 NBA MAX TEASERS + short text block, then full dashboard if needed.
If truly no games, say so – but check real schedules first."""

    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1200
    )
    
    full_text = response.choices[0].message.content

    # Debug: print and save full AI response so we can refine extraction
    try:
        print("Full AI response length:", len(full_text))
        with open("last_response.txt", "w", encoding="utf-8") as _f:
            _f.write(full_text)
        print("Saved AI response to last_response.txt")
    except Exception as _e:
        print("Warning: could not save full response:", _e)

    # Extract the short ready-to-send text (always at the top of my response)
    if "🔥 NBA BETS TONIGHT" in full_text:
        sections = full_text.split("🔥 NBA BETS TONIGHT")[1].strip().split("\n\n")
        selected = []

        def _parse_conf(s):
            import re
            flat = " ".join(s.split())
            m = re.search(r"(\d{1,3})\s*%", flat)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    return None
            m = re.search(r"confidence[:\s]+(\d{1,3})", flat, re.I)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    return None
            return None

        threshold = 75  # include picks with >=75% confidence (was 80)

        # Prefer sections that include a confidence >= threshold; if no confidence, include by default
        for sec in sections:
            if len(selected) >= 3:
                break
            conf = _parse_conf(sec)
            if conf is None or conf >= threshold:
                selected.append(sec.strip())

        # If not enough picks found, fill with next available sections
        idx = 0
        while len(selected) < 3 and idx < len(sections):
            sec = sections[idx].strip()
            if sec not in selected:
                selected.append(sec)
            idx += 1

        short_text = "🔥 NBA BETS TONIGHT\n\n" + "\n\n".join(selected)
    else:
        short_text = full_text[:800]
    
    try:
        bot.send_message(CHAT_ID, short_text.strip())
        print("✅ Text sent to Telegram!")
    except Exception as e:
        print(f"❌ Failed to send message: {e}")

if __name__ == "__main__":
    send_nba_bets()
    print("Bot is now polling for commands (e.g., /chatid). Press Ctrl+C to stop.")
    bot.polling()