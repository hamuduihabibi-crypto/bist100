#!/usr/bin/env python3
"""
BIST Trading Bot — Borsa İstanbul teknik analiz + momentum tarayıcı
====================================================================
100.000 TL'lik 3 haftalık trading yarışması için hazırlanan, üretime hazır
bir Python web servisi (Flask) + Telegram botudur.

Özellikler
----------
  * Tek hisse analizi          : RSI(14), MACD(12,26,9), EMA20/50 trend,
                                 20 günlük destek/direnç, Klasik Pivot (P,R1-R3,S1-S3)
                                 ve 10 günlük hacim surge %'si.
  * Top 5 Momentum taraması    : Hacim surge + ema trend + RSI(55-72) +
                                 direnç yakınlığı skorlama; +%6 hedef / -%3 stop.
  * Telegram bot (v13)         : /start /bilgi /top5 /sorgu <KOD> /portfoy /ototarma
  * Flask API                  : GET / | /api/scan | /api/stock/<symbol>
  * Otomatik tarama (ototarma): APScheduler ile periyodik uyarılar.

Çalıştırma (Hermes Windows host — NOT: PYTHONPATH temizlenmeli):
  env -u PYTHONPATH .venv312/Scripts/python.exe main.py

Uygulama TELEGRAM_BOT_TOKEN yoksa yalnızca web sunucusu olarak açılır
(bot parçası atlanır). Render/Heroku/VPS için README.md'ye bakınız.
"""

import os
import threading
from typing import Optional

import pandas as pd
import pandas_ta as ta
import yfinance as yf
from flask import Flask, jsonify

# --- Ortam değişkenleri (opsiyonel .env) -----------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # .env desteği yoksa os.environ yeterlidir
    pass

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
PORT = int(os.getenv("PORT", "5000"))

# --- Varsayılan BIST 100 tarama listesi -------------------------------------
# (Yarışma öncesi güncel BIST 100 bileşenleriyle genişletilebilir.)
BIST_TICKERS = [
    "GOZDE.IS", "ODAS.IS", "RNPOL.IS", "MAVI.IS", "THYAO.IS", "GARAN.IS",
    "TUPRS.IS", "EREGL.IS", "ASELS.IS", "SISE.IS", "AKBNK.IS", "FROTO.IS",
    "BIMAS.IS", "KCHOL.IS", "SAHOL.IS", "PETKM.IS", "TCELL.IS", "SASA.IS",
    "KOZAL.IS", "HEKTS.IS", "ULKER.IS", "TOASO.IS", "OTKAR.IS", "PGSUS.IS",
    "SOKM.IS", "AKSA.IS", "BAGFS.IS", "ISGYO.IS", "EKGYO.IS", "SARKY.IS",
]

# --- Yarışma / risk parametreleri -------------------------------------------
CAPITAL = 100_000.0          # toplam sermaye
NUM_POSITIONS = 4            # eşit pozisyon sayısı
TARGET_PCT = 0.06            # +%6 hedef kâr
STOP_PCT = 0.03              # -%3 sert stop-loss
RSI_MIN, RSI_MAX = 55.0, 72.0  # momentum RSI bandı
AUTO_SCAN_INTERVAL_MIN = 30  # /ototarma tarama sıklığı (dakika)

# --- Flask uygulaması --------------------------------------------------------
app = Flask(__name__)


# =============================================================================
# 1) TEKNİK ANALİZ MOTORU
# =============================================================================
def fetch_data(symbol: str) -> Optional[pd.DataFrame]:
    """6 aylık günlük OHLCV verisini çeker ve tek seviyeli kolon adları döndürür."""
    df = yf.download(
        symbol, period="6mo", interval="1d",
        progress=False, auto_adjust=True, threads=False,
    )
    if df is None or df.empty or len(df) < 60:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close", "Volume"]].astype(float)


def compute_macd_signal(close: pd.Series) -> tuple:
    """Bullish/Bearish MACD sinyali. (macd_line, signal_line, label) döndürür."""
    m = ta.macd(close, fast=12, slow=26, signal=9)
    if m is None or m.empty:
        return 0.0, 0.0, "Veri Yok ⚠️"
    macd_line = float(m["MACD_12_26_9"].iloc[-1])
    signal_line = float(m["MACDs_12_26_9"].iloc[-1])
    label = "Bullish 📈" if macd_line > signal_line else "Bearish 📉"
    return macd_line, signal_line, label


def ema_trend(price: float, ema20: float, ema50: float) -> tuple:
    """EMA trend etiketi. (label, emoji) döndürür."""
    if price > ema20 > ema50:
        return "Güçlü Boğa 🚀", "🚀"
    if price < ema20 < ema50:
        return "Ayı / Düşüş 🐻", "🐻"
    return "Yatay / Kararsız ⚖️", "⚖️"


def classic_pivots(h: float, low: float, c: float) -> dict:
    """Son günün High/Low/Close değerinden Klasik Pivot seviyeleri hesaplar."""
    p = (h + low + c) / 3.0
    r1 = 2 * p - low
    s1 = 2 * p - h
    r2 = p + (h - low)
    s2 = p - (h - low)
    r3 = h + 2 * (p - low)
    s3 = low - 2 * (h - p)
    return {
        "P": p, "R1": r1, "R2": r2, "R3": r3,
        "S1": s1, "S2": s2, "S3": s3,
    }


def analyze_single_stock(symbol: str) -> Optional[dict]:
    """Tek hissenin eksiksiz teknik + pivot analizini döndürür."""
    df = fetch_data(symbol)
    if df is None:
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    price = float(close.iloc[-1])
    rsi = float(ta.rsi(close, length=14).iloc[-1])
    macd_line, macd_sig, macd_label = compute_macd_signal(close)

    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    trend_label, trend_emoji = ema_trend(price, ema20, ema50)

    support20 = float(close.tail(20).min())
    resistance20 = float(close.tail(20).max())

    avg_vol10 = float(volume.rolling(10).mean().iloc[-1])
    vol_today = float(volume.iloc[-1])
    surge_pct = (vol_today / avg_vol10 * 100 - 100) if avg_vol10 > 0 else 0.0

    pivots = classic_pivots(float(high.iloc[-1]), float(low.iloc[-1]), price)

    target = price * (1 + TARGET_PCT)
    stop = price * (1 - STOP_PCT)

    rr = round((target - price) / (price - stop), 2) if price > stop else None

    return {
        "symbol": symbol, "price": price,
        "rsi": rsi,
        "rsi_state": "Momentum Bollukta 💪" if RSI_MIN <= rsi <= RSI_MAX
                      else ("Aşırı Alım 🔥" if rsi > RSI_MAX else "Zayıf/Soğuk 🧊"),
        "macd_line": macd_line, "macd_signal": macd_sig,
        "macd_label": macd_label,
        "ema20": ema20, "ema50": ema50,
        "trend_label": trend_label, "trend_emoji": trend_emoji,
        "support20": support20, "resistance20": resistance20,
        "volume_surge_pct": surge_pct,
        "target": target, "stop": stop, "rr": rr,
        "pivots": pivots,
    }


# =============================================================================
# 2) SKORLAMA & TOP 5 TARAYICI
# =============================================================================
def score_stock(a: dict) -> float:
    """İstenen momentum kriterlerine göre bir hisseye puan verir (0-100+)."""
    if a is None:
        return -1.0
    score = 0.0

    # Hacim surge (%300 üstü sınırlı) -> 0..30 puan
    score += min(max(a["volume_surge_pct"], 0), 300) * 0.1

    # RSI momentum bandı
    if RSI_MIN <= a["rsi"] <= RSI_MAX:
        score += 25
    elif a["rsi"] > RSI_MAX:
        score += 10          # güçlü ama aşırı alım
    elif a["rsi"] >= 50:
        score += 5

    # EMA trend
    if a["trend_label"].startswith("Güçlü Boğa"):
        score += 30
    elif a["trend_label"].startswith("Yatay"):
        score += 10

    # 20 günlük dirence yakınlık (kırılım potansiyeli) -> 0..35 puan
    rng = a["resistance20"] - a["support20"]
    if rng > 0:
        prox = (a["resistance20"] - a["price"]) / rng   # 0 dirençte, 1 destekte
        score += max(0.0, 1 - min(prox, 1.0)) * 35

    return round(score, 2)


def scan_top_5_stocks(top_n: int = 5) -> list:
    """BIST listesini tarar, skorlar ve ilk N hisseyi döndürür."""
    results = []
    for sym in BIST_TICKERS:
        try:
            a = analyze_single_stock(sym)
        except Exception:
            a = None      # tek hisse hatası tüm taramayı durdurmaz
        if a is None:
            continue
        a["score"] = score_stock(a)
        results.append(a)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


# =============================================================================
# 3) PORTFÖY HESAPLAMA
# =============================================================================
def portfolio_plan() -> dict:
    """100.000 TL'yi 4 eşit pozisyona böler; risk bütçelerini hesaplar."""
    position = CAPITAL / NUM_POSITIONS
    risk_per = position * STOP_PCT
    return {
        "capital": CAPITAL,
        "num_positions": NUM_POSITIONS,
        "position_size": position,
        "stop_pct": STOP_PCT * 100,
        "target_pct": TARGET_PCT * 100,
        "max_risk_per_position": risk_per,
        "total_risk_exposure": risk_per * NUM_POSITIONS,
        "note": "Her pozisyonda -%3 stop => hisse başına max -750 TL risk; "
                "4 pozisyon için toplam 3.000 TL risk bütçesi.",
    }


# =============================================================================
# 4) FLASK WEB SERVİSİ
# =============================================================================
@app.route("/", methods=["GET"])
def status():
    return jsonify({"status": "online", "service": "BIST Trading Bot"})


@app.route("/api/scan", methods=["GET"])
def api_scan():
    try:
        top = scan_top_5_stocks()
    except Exception as e:  # pragma: no cover
        return jsonify({"error": str(e)}), 500
    return jsonify({"count": len(top), "results": top})


@app.route("/api/stock/<symbol>", methods=["GET"])
def api_stock(symbol: str):
    a = analyze_single_stock(symbol.upper())
    if a is None:
        return jsonify({"error": f"{symbol} için veri bulunamadı"}), 404
    return jsonify(a)


# =============================================================================
# 5) TELEGRAM BOTU
# =============================================================================
BOT = None            # global bot instance (token varsa)
AUTO_SUBSCRIBERS = {}  # chat_id -> bool (ototarma açık/kapalı)
SCHEDULER = None
_BOT_STARTED = False   # idempotency: bot thread'i yalnızca bir kez başlat


# --- HTML biçimlendirme yardımcıları ----------------------------------------
def fmt_stock_line(a: dict, show_score=False) -> str:
    tag = ""
    if show_score:
        tag = f" 🔥 Skor: {a['score']}"
    return (
        f"<b>{a['symbol'].replace('.IS','')}</b>  {tag}\n"
        f"   Fiyat: <code>{a['price']:.2f} ₺</code> | RSI: {a['rsi']:.1f}\n"
        f"   MACD: {a['macd_label']} | Trend: {a['trend_label']}\n"
        f"   Hacim Surge: <code>%{a['volume_surge_pct']:.1f}</code>\n"
        f"   Hedef (+6%): <code>{a['target']:.2f} ₺</code> | "
        f"Stop (-3%): <code>{a['stop']:.2f} ₺</code> | R/R: {a['rr']}\n"
    )


def start_bot():
    """Telegram botunu bir daemon thread üzerinde başlatır (idempotent)."""
    global BOT, SCHEDULER, _BOT_STARTED
    if _BOT_STARTED:
        return None  # zaten başlatıldı (çift gunicorn importu / reloader koruması)
    if not TELEGRAM_BOT_TOKEN:
        print("[i] TELEGRAM_BOT_TOKEN tanımlı değil — yalnızca web sunucusu çalışacak.")
        return None
    _BOT_STARTED = True

    from telegram.ext import Updater, CommandHandler, Filters, MessageHandler

    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    BOT = updater.bot
    dp = updater.dispatcher

    # --- /start ---
    def cmd_start(update, context):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Top 5 Tarama", callback_data=None,
                                  url="https://t.me")],
            [InlineKeyboardButton("🧭 Kılavuz (/bilgi)", callback_data=None,
                                  url="https://t.me")],
        ])
        update.message.reply_text(
            "<b>🎯 BIST Trading Bot'a hoş geldiniz!</b>\n\n"
            "<b>Hızlı Başlangıç:</b>\n"
            "• <code>/sorgu GOZDE</code> → tek hisse analizi\n"
            "• <code>/top5</code> → en iyi 5 momentum hissesi\n"
            "• <code>/portfoy</code> → 100.000 TL sermaye planı\n"
            "• <code>/bilgi</code> → tüm komutlar ve strateji\n\n"
            "Yarışma dönemi: <b>10 Ağu – 28 Ağu</b> 🗓️",
            reply_markup=kb, parse_mode="HTML",
        )

    # --- /bilgi ---
    def cmd_bilgi(update, context):
        update.message.reply_text(
            "<b>🧭 Kullanım Kılavuzu</b>\n\n"
            "<b>Komutlar:</b>\n"
            "• <code>/sorgu KOD</code> → hisse raporu (Ör: <code>/sorgu GOZDE</code>)\n"
            "   Fiyat, RSI, MACD, EMA, 20G destek/direnç, tüm pivot seviyeleri.\n"
            "• <code>/top5</code> → skorlanmış ilk 5 momentum hissesi (+%6 hedef, -%3 stop).\n"
            "• <code>/portfoy</code> → 100.000 TL'yi 4 eşit pozisyona bölme planı.\n"
            "• <code>/ototarma ac|kapat</code> → periyodik otomatik tarama uyarıları.\n\n"
            "<b>📈 Strateji (3 hafta — 10-28 Ağu):</b>\n"
            "1) Hacim patlaması + trend (Fiyat>EMA20>EMA50) + RSI 55-72.\n"
            "2) 20 günlük direncin kırılımına yakın hisseleri seç.\n"
            "3) Hedef +%6, sert stop -%3 (R/R ≈ 2:1).\n"
            "4) Her seferinde max 1-2 pozisyon açık tut (sermaye 100.000 TL).",
            parse_mode="HTML",
        )

    # --- /top5 ---
    def cmd_top5(update, context):
        msg = "<b>🔥 Top 5 Momentum</b>\n\n"
        try:
            top = scan_top_5_stocks()
        except Exception as e:  # pragma: no cover
            update.message.reply_text(f"Tarama hatası: {e}")
            return
        if not top:
            update.message.reply_text("Kriterlere uyan hisse bulunamadı.")
            return
        for i, a in enumerate(top, 1):
            msg += f"<b>{i}.</b> " + fmt_stock_line(a, show_score=True) + "\n"
        update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)

    # --- /sorgu ---
    def cmd_sorgu(update, context):
        args = context.args
        if not args:
            update.message.reply_text("Kullanım: <code>/sorgu KOD</code> (Ör: <code>/sorgu GOZDE</code>)",
                                      parse_mode="HTML")
            return
        symbol = args[0].upper()
        if not symbol.endswith(".IS"):
            symbol += ".IS"
        a = analyze_single_stock(symbol)
        if a is None:
            update.message.reply_text(f"{symbol} için veri bulunamadı. Kodu kontrol edin.")
            return
        p = a["pivots"]
        msg = (
            f"<b>📌 {symbol}</b>\n\n"
            f"Fiyat: <code>{a['price']:.2f} ₺</code>\n"
            f"RSI(14): <b>{a['rsi']:.1f}</b> ({a['rsi_state']})\n"
            f"MACD: {a['macd_label']}\n"
            f"Trend: {a['trend_label']}\n"
            f"EMA20: <code>{a['ema20']:.2f}</code> | EMA50: <code>{a['ema50']:.2f}</code>\n"
            f"Direnç(20G): <code>{a['resistance20']:.2f}</code> | "
            f"Destek(20G): <code>{a['support20']:.2f}</code>\n"
            f"Hacim Surge: <code>%{a['volume_surge_pct']:.1f}</code>\n\n"
            f"<b>🎯 Hedef (+6%):</b> <code>{a['target']:.2f} ₺</code>\n"
            f"<b>🛑 Stop (-3%):</b> <code>{a['stop']:.2f} ₺</code> | R/R: {a['rr']}\n\n"
            f"<b>📐 Klasik Pivotlar</b>\n"
            f"Pivot P: <code>{p['P']:.2f}</code>\n"
            f"Direnç R1: <code>{p['R1']:.2f}</code> | R2: <code>{p['R2']:.2f}</code> | R3: <code>{p['R3']:.2f}</code>\n"
            f"Destek S1: <code>{p['S1']:.2f}</code> | S2: <code>{p['S2']:.2f}</code> | S3: <code>{p['S3']:.2f}</code>"
        )
        update.message.reply_text(msg, parse_mode="HTML")

    # --- /portfoy ---
    def cmd_portfoy(update, context):
        pl = portfolio_plan()
        update.message.reply_text(
            f"<b>💰 Portföy Planı (100.000 TL)</b>\n\n"
            f"Toplam Sermaye: <code>{pl['capital']:,.0f} ₺</code>\n"
            f"Pozisyon Sayısı: <b>{pl['num_positions']}</b>\n"
            f"Pozisyon Başına: <code>{pl['position_size']:,.0f} ₺</code>\n\n"
            f"<b>Risk Yönetimi</b>\n"
            f"Stop: -{pl['stop_pct']:.0f}%  →  max -<code>{pl['max_risk_per_position']:,.0f} ₺</code>/hisse\n"
            f"Toplam Risk: <code>{pl['total_risk_exposure']:,.0f} ₺</code>\n\n"
            f"{pl['note']}",
            parse_mode="HTML",
        )

    # --- /ototarma ---
    def toggle_auto(chat_id: int) -> bool:
        AUTO_SUBSCRIBERS[chat_id] = not AUTO_SUBSCRIBERS.get(chat_id, False)
        return AUTO_SUBSCRIBERS[chat_id]

    def cmd_ototarma(update, context):
        enabled = toggle_auto(update.effective_chat.id)
        state = "AÇIK ✅" if enabled else "KAPALI ❌"
        update.message.reply_text(
            f"Otomatik tarama {state}.\n"
            f"Her {AUTO_SCAN_INTERVAL_MIN} dk'da bir Top 5 uyarısı gönderilecek.",
            parse_mode="HTML",
        )

    dp.add_handler(CommandHandler("start", cmd_start))
    dp.add_handler(CommandHandler("bilgi", cmd_bilgi))
    dp.add_handler(CommandHandler("top5", cmd_top5))
    dp.add_handler(CommandHandler("sorgu", cmd_sorgu))
    dp.add_handler(CommandHandler("portfoy", cmd_portfoy))
    dp.add_handler(CommandHandler("ototarma", cmd_ototarma))
    dp.add_handler(MessageHandler(Filters.command, lambda u, c: None))

    # --- APScheduler ile periyodik tarama (ototarma abonelerine) -------------
    def auto_scan_job():
        if not AUTO_SUBSCRIBERS:
            return
        try:
            top = scan_top_5_stocks()
        except Exception:
            return
        if not top:
            return
        msg = "<b>🔔 Otomatik Tarama</b>\n\n"
        for i, a in enumerate(top, 1):
            msg += f"<b>{i}.</b> {fmt_stock_line(a)}\n"
        for chat_id in list(AUTO_SUBSCRIBERS):
            if not AUTO_SUBSCRIBERS.get(chat_id):
                continue
            try:
                BOT.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
            except Exception:
                pass

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        SCHEDULER = BackgroundScheduler()
        SCHEDULER.add_job(auto_scan_job, "interval", minutes=AUTO_SCAN_INTERVAL_MIN)
        SCHEDULER.start()
    except Exception as e:  # pragma: no cover
        print(f"[!] Zamanlayıcı başlatılamadı: {e}")

    # Bot poll'u ayrı bir daemon thread üzerinde açar.
    def _run_polling():
        updater.start_polling(poll_interval=1.0, timeout=20)

    threading.Thread(target=_run_polling, name="telegram-bot", daemon=True).start()
    print("[i] Telegram botu arka planda başlatıldı.")
    return updater


# =============================================================================
# 6) GİRİŞ NOKTASI
# =============================================================================
def maybe_start_bot_thread():
    """TELEGRAM_BOT_TOKEN varsa bot thread'ini modül yüklenince başlatır.

    Gunicorn (`gunicorn main:app`) modülü import ettiğinde `if __name__ ==
    "__main__"` çalışmaz; bu yüzden web sunucusuyla birlikte botun da ayağa
    kalkması için çağrı modül seviyesinde yapılır. Idempotenttir: aynı process
    içinde yalnızca bir kez başlatılır (gunicorn reloader / tekrar import).
    """
    if not TELEGRAM_BOT_TOKEN:
        print("[!] TELEGRAM_BOT_TOKEN is missing. Running in web-only mode.")
        return False
    thread = threading.Thread(target=start_bot, name="telegram-bot", daemon=True)
    thread.start()
    print("[i] Telegram bot thread started in background.")
    return True


def main():
    # Bot modül seviyesinde (şu dosyanın sonundaki çağrı ile) başladığından
    # burada tekrar başlatılmaz — yalnızca web sunucusu çalıştırılır.
    host = os.getenv("HOST", "0.0.0.0")
    print(f"[i] Flask sunucusu http://{host}:{PORT} üzerinde başlatılıyor...")
    # Debug/PORT ortam ayarlarına göre çalıştır.
    app.run(host=host, port=PORT, debug=os.getenv("FLASK_DEBUG", "0") == "1")


# --- Bot thread'ini OTOMATİK başlat: Gunicorn (gunicorn main:app) modülü
# import ettiğinde bu blok çalışır; `if __name__ == "__main__"` çalışmaz.
# Bu, Render'da web + bot'un aynı anda ayağa kalkmasını sağlar.
if TELEGRAM_BOT_TOKEN:
    import threading
    bot_thread = threading.Thread(target=start_bot, name="telegram-bot", daemon=True)
    bot_thread.start()
    print("[i] Telegram bot thread started in background.")
else:
    print("[!] TELEGRAM_BOT_TOKEN is missing. Running in web-only mode.")


if __name__ == "__main__":
    main()