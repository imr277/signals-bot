import os
import time
import json
import hashlib
import requests
from datetime import datetime, timezone
from xml.etree import ElementTree

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ALPHA_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")
INTERVAL = int(os.environ.get("INTERVAL_MINUTES", "5"))

TG_URL = f"https://api.telegram.org/bot{TOKEN}"
seen = set()
prices_cache = {}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def send_telegram(text):
    try:
        r = requests.post(f"{TG_URL}/sendMessage", json={
            "chat_id": CHAT_ID,
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=10)
        data = r.json()
        if not data.get("ok"):
            log(f"Telegram error: {data.get('description')}")
            return False
        return True
    except Exception as e:
        log(f"Telegram exception: {e}")
        return False

def uid(text):
    return hashlib.md5(text.encode()).hexdigest()[:12]

SYMBOLS = {
    "EURUSD": {"name": "EUR/USD", "cat": "forex"},
    "GBPUSD": {"name": "GBP/USD", "cat": "forex"},
    "USDJPY": {"name": "USD/JPY", "cat": "forex"},
    "USDCHF": {"name": "USD/CHF", "cat": "forex"},
    "AUDUSD": {"name": "AUD/USD", "cat": "forex"},
    "USDCAD": {"name": "USD/CAD", "cat": "forex"},
    "XAUUSD": {"name": "Or (XAU/USD)", "cat": "metals"},
    "XAGUSD": {"name": "Argent (XAG/USD)", "cat": "metals"},
    "BTCUSDT": {"name": "Bitcoin (BTC)", "cat": "crypto"},
    "ETHUSDT": {"name": "Ethereum (ETH)", "cat": "crypto"},
    "SOLUSDT": {"name": "Solana (SOL)", "cat": "crypto"},
}

def get_forex_price(symbol):
    try:
        from_sym = symbol[:3]
        to_sym = symbol[3:]
        url = (
            "https://www.alphavantage.co/query"
            "?function=CURRENCY_EXCHANGE_RATE"
            f"&from_currency={from_sym}"
            f"&to_currency={to_sym}"
            f"&apikey={ALPHA_KEY}"
        )
        r = requests.get(url, timeout=8)
        rate = r.json().get("Realtime Currency Exchange Rate", {}).get("5. Exchange Rate")
        return float(rate) if rate else None
    except:
        return None

def get_crypto_price(symbol):
    try:
        r = requests.get(
            f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
            timeout=8
        )
        price = r.json().get("price")
        return float(price) if price else None
    except:
        return None

def get_price(symbol):
    cached = prices_cache.get(symbol)
    if cached and (time.time() - cached[0]) < 60:
        return cached[1]
    info = SYMBOLS.get(symbol, {})
    if info.get("cat") == "crypto":
        price = get_crypto_price(symbol)
    else:
        price = get_forex_price(symbol)
    if price:
        prices_cache[symbol] = (time.time(), price)
    return price

def get_all_prices():
    prices = {}
    for symbol in SYMBOLS:
        price = get_price(symbol)
        if price:
            prices[symbol] = price
    return prices

NEWS_SOURCES = [
    {"name": "FXStreet",         "url": "https://www.fxstreet.com/rss/news"},
    {"name": "MarketWatch",      "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"},
    {"name": "Bloomberg",        "url": "https://feeds.bloomberg.com/markets/news.rss"},
    {"name": "Reuters",          "url": "https://feeds.reuters.com/reuters/topNews"},
    {"name": "Financial Times",  "url": "https://www.ft.com/rss/home"},
    {"name": "CoinDesk",         "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "Cointelegraph",    "url": "https://cointelegraph.com/rss"},
    {"name": "AP News",          "url": "https://rsshub.app/apnews/topics/apf-topnews"},
    {"name": "BBC World",        "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "Fed Reserve",      "url": "https://www.federalreserve.gov/feeds/press_all.xml"},
    {"name": "r/Forex",          "url": "https://www.reddit.com/r/Forex/hot.json?limit=10", "type": "reddit"},
    {"name": "r/Daytrading",     "url": "https://www.reddit.com/r/Daytrading/hot.json?limit=10", "type": "reddit"},
    {"name": "r/wallstreetbets", "url": "https://www.reddit.com/r/wallstreetbets/hot.json?limit=10", "type": "reddit"},
    {"name": "r/Gold",           "url": "https://www.reddit.com/r/Gold/hot.json?limit=10", "type": "reddit"},
]

HIGH_VALUE_KEYWORDS = [
    "fed","fomc","rate","inflation","cpi","nfp","gdp","recession",
    "ecb","lagarde","powell","rate cut","rate hike",
    "tariff","trade war","sanction",
    "war","conflict","attack","ceasefire","nuclear",
    "oil","opec","energy",
    "etf","sec","regulation","hack","crash","surge","bitcoin","ethereum",
    "gold","xau","safe haven","precious metals",
    "breaking","urgent","flash","just in","alert",
]

def fetch_rss(src):
    try:
        r = requests.get(
            "https://api.allorigins.win/get?url=" + requests.utils.quote(src["url"]),
            timeout=8
        )
        j = r.json()
        xml = ElementTree.fromstring(j["contents"])
        items = xml.findall(".//item") or xml.findall(".//{http://www.w3.org/2005/Atom}entry")
        news = []
        for i in items[:10]:
            title = (
                i.findtext("title") or
                i.findtext("{http://www.w3.org/2005/Atom}title") or ""
            )
            title = title.replace("<![CDATA[", "").replace("]]>", "").strip()
            link = (i.findtext("link") or "").strip()
            if title and len(title) > 10:
                news.append({"title": title, "link": link, "source": src["name"]})
        return news
    except:
        return []

def fetch_reddit(src):
    try:
        r = requests.get(src["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        posts = r.json().get("data", {}).get("children", [])
        news = []
        for p in posts:
            d = p.get("data", {})
            if d.get("stickied"):
                continue
            title = d.get("title", "")
            ups = d.get("ups", 0)
            if title and len(title) > 10 and ups > 100:
                link = "https://reddit.com" + d.get("permalink", "")
                news.append({"title": title, "link": link, "source": src["name"]})
        return news
    except:
        return []

def fetch_all_news():
    all_news = []
    for src in NEWS_SOURCES:
        if src.get("type") == "reddit":
            all_news.extend(fetch_reddit(src))
        else:
            all_news.extend(fetch_rss(src))
    return all_news

def is_high_value(title):
    t = title.lower()
    return any(k in t for k in HIGH_VALUE_KEYWORDS)

def call_claude(prompt, max_tokens=400):
    if not ANTHROPIC_KEY:
        return None
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=25
        )
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        log(f"Claude error: {e}")
        return None

def generate_signal(news_item, prices):
    prices_str = "\n".join([
        f"- {SYMBOLS[s]['name']} : {p}"
        for s, p in prices.items()
    ])
    prompt = (
        "Tu es un trader professionnel expert en forex, or et crypto.\n\n"
        f"NEWS : {news_item['title']}\n"
        f"SOURCE : {news_item['source']}\n\n"
        f"PRIX EN TEMPS REEL :\n{prices_str}\n\n"
        "Genere un signal de trading si tu vois une opportunite claire.\n"
        "Reponds UNIQUEMENT en JSON strict :\n"
        "{\n"
        '  "score": <1-10>,\n'
        '  "opportunite": <true/false>,\n'
        '  "actif": "<nom de l actif ex: Or (XAU/USD)>",\n'
        '  "symbole": "<symbole ex: XAUUSD>",\n'
        '  "direction": "<LONG ou SHORT>",\n'
        '  "entry": <prix entree>,\n'
        '  "tp1": <objectif 1>,\n'
        '  "tp2": <objectif 2>,\n'
        '  "sl": <stop loss>,\n'
        '  "rr": "<ratio ex: 1:2.5>",\n'
        '  "timeframe": "<M15/H1/H4/D1>",\n'
        '  "analyse": "<3 phrases max en francais>",\n'
        '  "risque": "<FAIBLE/MOYEN/ELEVE>"\n'
        "}\n\n"
        "Score 7+ = signal valide. Si pas d opportunite, opportunite: false"
    )
    text = call_claude(prompt, max_tokens=400)
    if not text:
        return None
    try:
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except:
        return None

def build_signal_message(news_item, signal):
    score = signal.get("score", 0)
    direction = signal.get("direction", "")
    actif = signal.get("actif", "")
    entry = signal.get("entry", 0)
    tp1 = signal.get("tp1", 0)
    tp2 = signal.get("tp2", 0)
    sl = signal.get("sl", 0)
    rr = signal.get("rr", "")
    timeframe = signal.get("timeframe", "")
    analyse = signal.get("analyse", "")
    risque = signal.get("risque", "MOYEN")

    if score >= 9:
        score_icon = "🔥"
    elif score >= 7:
        score_icon = "🟢"
    else:
        score_icon = "🟡"

    direction_icon = "📈 LONG" if direction == "LONG" else "📉 SHORT"

    if risque == "FAIBLE":
        risque_icon = "🟢"
    elif risque == "ELEVE":
        risque_icon = "🔴"
    else:
        risque_icon = "🟡"

    msg = (
        f"{score_icon} <b>SIGNAL [{score}/10] — {actif}</b>\n\n"
        f"📰 {news_item['title']}\n"
        f"Source : {news_item['source']}\n\n"
        f"━━━━━━━━━━━━━\n"
        f"  {direction_icon}\n"
        f"━━━━━━━━━━━━━\n\n"
        f"💰 <b>Entry :</b> {entry}\n"
        f"🎯 <b>TP1 :</b> {tp1}\n"
        f"🎯 <b>TP2 :</b> {tp2}\n"
        f"🛑 <b>SL :</b> {sl}\n"
        f"⚖️ <b>R/R :</b> {rr}\n"
        f"⏱ <b>Timeframe :</b> {timeframe}\n"
        f"{risque_icon} <b>Risque :</b> {risque}\n\n"
        f"🤖 <b>Analyse</b>\n{analyse}"
    )
    if news_item.get("link"):
        msg += f"\n\n🔗 {news_item['link']}"
    return msg

def run_check():
    log("Scan des sources...")
    news = fetch_all_news()
    prices = get_all_prices()
    log(f"{len(prices)} prix charges, {len(news)} articles")
    sent = 0
    for item in news:
        nid = uid(item["title"] + item["source"])
        if nid in seen:
            continue
        seen.add(nid)
        if not is_high_value(item["title"]):
            continue
        log(f"Analyse : {item['title'][:60]}")
        signal = generate_signal(item, prices)
        if not signal:
            continue
        score = int(signal.get("score", 0))
        opportunite = signal.get("opportunite", False)
        if not opportunite or score < 7:
            log(f"Score {score}/10 — pas d opportunite")
            continue
        msg = build_signal_message(item, signal)
        if send_telegram(msg):
            sent += 1
            log(f"Signal envoye [{score}/10] : {item['title'][:50]}")
        time.sleep(3)
        if sent >= 2:
            break
    if sent == 0:
        log("Aucun signal valide ce cycle")

def main():
    log("=== Bot Trading Signals demarre ===")
    if not TOKEN or not CHAT_ID:
        log("ERREUR : TOKEN ou CHAT_ID manquant")
        return
    send_telegram(
        "📊 <b>Bot Trading Signals demarre</b>\n\n"
        f"✅ {len(NEWS_SOURCES)} sources surveillees\n"
        "✅ Forex, Or, Crypto\n"
        "✅ Entry / TP1 / TP2 / SL sur chaque signal\n"
        "✅ Ratio Risque/Reward calcule\n"
        f"✅ Scan toutes les {INTERVAL} min\n\n"
        "Tu recevras un signal complet des qu une opportunite est detectee."
    )
    while True:
        run_check()
        log(f"Prochain scan dans {INTERVAL} min...")
        time.sleep(INTERVAL * 60)

if __name__ == "__main__":
    main()
