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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import pandas as pd
import pandas_ta as ta
import pytz
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

# --- BIST Tüm tarama evreni ------------------------------------------------
# ~500 BIST hissesi. Liste güncellenir; en güncel tam listeniz varsa
# ortam değişkeniyle BIST_TICKERS_FILE=/yol/liste.txt belirtin
# (her satır bir kod, ".IS" ekli ya da ekli değil). Varsayılan: aşağıdaki seed.
BIST_TICKERS_SEED = [
    # Banka & Finans
    "AKBNK.IS", "ALBRK.IS", "GARAN.IS", "HALKB.IS", "ICBCR.IS", "ISKUR.IS",
    "ISBIR.IS", "ISFIN.IS", "ISATY.IS", "JANTS.IS", "KLNMA.IS", "SKBNK.IS",
    "TSKB.IS", "TUKAS.IS", "VAKFN.IS", "VAKBN.IS", "YKBNK.IS", 
    "AEFES.IS", "AKSA.IS", "AKSEN.IS", "AKSUE.IS",
    # Holding & Yatırım
    "AGHOL.IS", "ALARK.IS", "AVHOL.IS", "BAGFS.IS", "CCOLA.IS", "CIMSA.IS",
    "DOHOL.IS", "ECZYT.IS", "ENKAI.IS", "FROTO.IS", "GOLTS.IS",
    "GOZDE.IS", "GSDHO.IS", "IBAY.IS", "KCHOL.IS", 
    "NTHOL.IS", "OYAKC.IS", "SAHOL.IS", "SISE.IS", "TRCAS.IS",
    "TSPOR.IS", "TTRAK.IS", "YATAS.IS", "ZOREN.IS",
    # Gıda & İçecek
    "ARCLK.IS", "BANVT.IS", "BFREN.IS", "BIMAS.IS", "CANTE.IS", "DANIS.IS",
    "ERSU.IS", "ETIY.IS", "GENTS.IS", "IEYHO.IS", "IZFAS.IS", "KERVT.IS",
    "KNYA.IS", "KRSAN.IS", "KUTPO.IS", "MNDRS.IS", "PENGD.IS", "PINSU.IS",
    "SELGD.IS", "TATGD.IS", "TBORG.IS", "ULKER.IS", 
    "YAYLA.IS", "YYLAP.IS",
    # Petrokimya & Enerji
    "ALCAR.IS", "ALKIM.IS", "AYGAZ.IS", "BATAS.IS", "BRISA.IS", "DMSAS.IS",
    "EGSER.IS", "EGEEN.IS", "ENERY.IS", "ENJSA.IS", "EREGL.IS", 
    "IZENR.IS", "KARSN.IS", "KRTEK.IS", "MAKTK.IS", "MRSHL.IS", "NATEN.IS",
    "ODAS.IS", "ORGE.IS", "PAPIL.IS", "PETKM.IS", "SAYAS.IS", "SODSN.IS",
    "TATEN.IS", "TAVHL.IS", "TERA.IS", "TUPRS.IS", "ZOREN.IS",
    # Savunma & Otomotiv & Teknoloji
    "ARCLK.IS", "ASELS.IS", "BERA.IS", "BJKAS.IS", "BOSSA.IS",
    "BRKSN.IS", "BURSA.IS", "CLEBI.IS", "COSMO.IS", "DOAS.IS", "DOKTA.IS",
    "EAGB.IS", "ECZYT.IS", "FMIZP.IS", "FROTO.IS", "GESAN.IS",
    "GRNYO.IS", "HCAY.IS", "HEKTS.IS", "HUBVC.IS", "KARSN.IS", "KONTR.IS",
    "KCHOL.IS", "MAVI.IS", "MGROS.IS", "OTKAR.IS", "PGSUS.IS", "SDTTR.IS",
    "TAVHL.IS", "TOASO.IS", "TTKOM.IS", "TUKAS.IS", "VESTL.IS",
    # İlaç & Sağlık
    "AEDFS.IS", "BIOEN.IS", "ECILC.IS", "FADE.IS", "GENIL.IS",
    "GUBRF.IS", "IEYHO.IS", "INTEM.IS", "ISFIN.IS", "MEDTR.IS", "MEPET.IS",
    "NUGYO.IS", "OYLUM.IS", "RTAYB.IS", "SELGD.IS", "SMRTG.IS", "TMPOL.IS",
    "TRILC.IS",
    # Hizmet & Turizm & GYO
    "AKENR.IS", "AKMGY.IS", "ALGYO.IS", "ATSYH.IS", "AVTUR.IS", 
    "DOHOL.IS", "EKGYO.IS", "EMKEL.IS", "HLGYO.IS", "ISGYO.IS", "KLKIM.IS",
    "MARTI.IS", "METRO.IS", "MIATK.IS", "MTRKS.IS", "NETAS.IS",
    "PEKGY.IS", "RGYAS.IS", "SARKY.IS", "SNGYO.IS", "TSGYO.IS", "TUPRS.IS",
    "VKGYO.IS", "YKBNK.IS",
    # Diğer / Tek halka
    "AFYON.IS", "ANSA.IS", "APYUN.IS", "ARASE.IS", "ARENA.IS",
    "ARZUM.IS", "ASUZU.IS", "AUTKER.IS", "AVOD.IS",
    "AYCES.IS", "BAGFS.IS", "BAKAB.IS", "BASGZ.IS", "BLCYT.IS",
    "BORSK.IS", "BTCIM.IS", "BUCIM.IS", "BURVA.IS", "CANTE.IS", "CASA.IS",
    "CEDBN.IS", "CEMTS.IS", "CELHA.IS", "CEMAS.IS", "CUSAN.IS", "DAGI.IS",
    "DERIM.IS", "DESA.IS", "DIRIT.IS", "DITAS.IS", "DOCO.IS",
    "DOKTA.IS", "DURDO.IS", "DYOBY.IS", "ECZYT.IS", "EGEPO.IS", "EKIZ.IS",
    "ETYAT.IS", "EUREN.IS", "EUYO.IS", "FORTE.IS", "FRIGO.IS", "GARFA.IS",
    "GEDZA.IS", "GLYHO.IS", "GOODY.IS", "GRAFT.IS", "GRNYO.IS",
    "HDFGS.IS", "HMSO.IS", "INFO.IS", "ISKPL.IS", "ISMEN.IS",
    "KAYSE.IS", "KCHOL.IS", "KLMSN.IS", "LIDER.IS", "LUKSK.IS",
    "MAGEN.IS", "MAKIM.IS", "MEMSA.IS", "NUGYO.IS",
    "OBAMS.IS", "ORCAY.IS", "OSMEN.IS", "OZSUB.IS",
    "PARSN.IS", "PASEU.IS", "PATEK.IS", "POLHO.IS", "PRZMA.IS", 
    "REEDR.IS", "RPOWER.IS", "RSYO.IS", "SAFKR.IS", "SARKY.IS",
    "SBAG.IS", "SEKUR.IS", "SEYKM.IS", "SILVR.IS", "SKTAS.IS", "SUMAS.IS",
    "TAVHL.IS", "TCELL.IS", "TEKTU.IS", "THYAO.IS", "TKFEN.IS", "TKNSA.IS",
    "TMSN.IS", "TUKAS.IS", "UKSE.IS", "ULUSE.IS", "VKING.IS", "VKING.IS",
    # GYO & Gayrimenkul
    "AGYO.IS", "AKFGY.IS", "AKSGY.IS", "ALGYO.IS", "ATAGY.IS", 
    "DZGYO.IS", "EGEYH.IS", "GYHO.IS", "HALKGY.IS", "KGYO.IS", "KLGYO.IS",
    "KRGYO.IS", "LGKYO.IS", "MRGYO.IS", "OZKGY.IS",
    "PAGYO.IS", "RGYAS.IS", "YKGYO.IS", "YGGYO.IS", "ZMKGY.IS",
    # Makine, İnşaat & Metal
    "ANIET.IS", "ASUZU.IS", "BASTK.IS", "BOLUC.IS",
    "CLEBI.IS", "CONKA.IS", "DCTRK.IS", "DENGE.IS", "DFHOL.IS", "DIRIT.IS",
    "DMRGD.IS", "EKINC.IS", "EMNIS.IS", "ERBOS.IS", "EREGL.IS", 
    "FENER.IS", "GEREL.IS", "GOKNR.IS", "GOLTS.IS", "HILAS.IS", "IEYHO.IS",
    "IHEVA.IS", "INVES.IS", "IZMDC.IS", "KLKIM.IS", "KONYA.IS",
    "KRDMD.IS", "KUTPO.IS", "MAALT.IS", "MERKO.IS", "NUHCM.IS",
    "OZATD.IS", "PASEU.IS", "PRKME.IS", "RLKM.IS", "SAFKR.IS", "SARKY.IS",
    "SILVR.IS", "SKKN.IS", "SODSN.IS", "TAVHL.IS", "TCELL.IS",
    "TKNSA.IS", "TUKAS.IS", "VAKKO.IS", "VKGYO.IS", "YAPRK.IS",
    "ZOREN.IS", "DOGUB.IS", "TUKAS.IS", "KCHOL.IS", "TUPRS.IS",
    # Diğer şirketler
    "ACIPD.IS", "ADESE.IS", "AFYON.IS", 
    "ASELS.IS", "ATSYH.IS", "AVTUR.IS", "AYEN.IS", "BALAT.IS", "BANVT.IS",
    "BASGZ.IS", "BEPAS.IS", "BFREN.IS", "BRMEN.IS",
    "BSOKE.IS", "BTCIM.IS", "CMBTN.IS", "COSMO.IS", "CVKMD.IS", "DURKN.IS",
    "DYKHO.IS", "EGPRO.IS", "EKIZ.IS", "ENRUT.IS", "ERSU.IS",
    "ESCAR.IS", "ESCOM.IS", "ETYAT.IS", "EUREN.IS", "FADE.IS", "FMIZP.IS",
    "FORTE.IS", "GEDZA.IS", "GEREL.IS", "GLYHO.IS", "GOODY.IS",
    "GRTRK.IS", "GSDDE.IS", "GSTKM.IS", "HECEB.IS", "INFO.IS",
    "ISKUR.IS", "ISMEN.IS", "KAREL.IS", "KARTN.IS", "KAYSER.IS", "KONYA.IS",
    "KORDS.IS", "KRTM.IS", "LIDFA.IS", "MAKIM.IS", "MEGMT.IS",
    "MERCN.IS", "METAL.IS", "METRO.IS", "MIKRS.IS", "MKART.IS", 
    "NETAS.IS", "NUGYO.IS", "OBAMS.IS", "ORGE.IS", "OSMEN.IS", "OTKAR.IS",
    "PARSN.IS", "PATEK.IS", "PKART.IS", "PLTUR.IS", "POLHO.IS", "PRKAB.IS",
    "PRZMA.IS", "REEDR.IS", "RPOWER.IS",
    "RSYO.IS", "SAFKR.IS", "SARKY.IS", "SBAG.IS", "SEKUR.IS", "SELGD.IS",
    "SERVE.IS", "SMRTG.IS", "SUNTK.IS", "SUWEN.IS", "TACTR.IS", "TATEN.IS",
    "TBORG.IS", "TEKTU.IS", "TFTCB.IS", "TUREX.IS", "UEEC.IS",
    "UFUK.IS", "ULAS.IS", "ULUFA.IS", "ULUUN.IS", "USA.IS", 
    "USYO.IS", "VBTYZ.IS", "VERTU.IS", "VKING.IS", "YATAS.IS", 
    "YONGA.IS", "YUNSA.IS", "ZOREN.IS", "ZTAR.IS",
]


def _normalize(code: str) -> str:
    c = code.strip().upper()
    return c if c.endswith(".IS") else c + ".IS"


def get_bist_tickers() -> list:
    """Tarama listesini döndürür.

    Öncelik: BIST_TICKERS_FILE ortam değişkenindeki dosya (her satır bir kod).
    Aksi halde yerleşik BIST Tüm seed listesi kullanılır. Kodlar ".IS" ile
    normalize edilir ve sırayı koruyarak yinelenenler temizlenir.
    """
    f = os.getenv("BIST_TICKERS_FILE", "")
    codes = list(BIST_TICKERS_SEED)
    if f and os.path.isfile(f):
        try:
            with open(f, encoding="utf-8") as fh:
                file_codes = [_normalize(l) for l in fh if l.strip()]
            if file_codes:
                codes = file_codes
                print(f"[i] BIST_TICKERS_FILE kullanılıyor: {f} ({len(codes)} kod)")
        except Exception as e:  # pragma: no cover
            print(f"[!] BIST_TICKERS_FILE okunamadı, seed kullanılacak: {e}")
    # sırayı bozmadan tekilleştir
    seen, out = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out

# --- Yarışma / risk parametreleri -------------------------------------------
CAPITAL = 100_000.0          # toplam sermaye
NUM_POSITIONS = 4            # eşit pozisyon sayısı
TARGET_PCT = 0.06            # +%6 hedef kâr
STOP_PCT = 0.03              # -%3 sert stop-loss
RSI_MIN, RSI_MAX = 55.0, 72.0  # momentum RSI bandı
AUTO_SCAN_INTERVAL_MIN = 30  # /ototarma tarama sıklığı (dakika)
AUTO_SCAN_ENABLED = True     # /ototarma VARSYILAN OLARAK AÇIK (startup'tan itibaren)

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


def download_batch(symbols: list) -> Optional[pd.DataFrame]:
    """BIST Tüm listesini TEK yf.download çağrısıyla toplu indirir.

    group_by="ticker" => kolonlar MultiIndex (ticker, alan) olur; 500+ hisse
    tek seferde, yfinance'ın iç thread'leriyle çekilir (teker teker 500 çağrı
    yerine). 120 sn'lik Gunicorn timeout'unun altında kalmanın asıl anahtarı budur.
    """
    symbols = list(dict.fromkeys(symbols))  # yinelenenleri koru
    if not symbols:
        return None
    df = yf.download(
        symbols, period="6mo", interval="1d",
        progress=False, auto_adjust=True, threads=True,
        group_by="ticker", timeout=20,
    )
    if df is None or df.empty:
        return None
    return df


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


def _compute_analysis(symbol: str, df: pd.DataFrame) -> Optional[dict]:
    """Hazır, tek hisselik OHLCV çerçevesinden eksiksiz analiz üretir.

    Hem analyze_single_stock (tek indirme) hem de scan_top_5_stocks (toplu
    indirme + thread havuzu) bu fonksiyonu kullanır => aynı hesaplama, çifte kod yok.
    """
    if df is None or df.empty or len(df) < 60:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float)

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


def analyze_single_stock(symbol: str) -> Optional[dict]:
    """HERHANGİ bir geçerli hisse için eksiksiz analiz döndürür (/sorgu)."""
    return _compute_analysis(symbol, fetch_data(symbol))


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


# --- In-memory scan cache (1 saat) --------------------------------------------
# Aynı TTL aralığında yapılan tüm tarama istekleri yeniden indirme YAPMAZ.
SCAN_CACHE_TTL = 3600          # tarama sonucunun ömrü (saniye). 10dk üstüne çıkarıldı:
                              # free tier'da tek 340-hisse taraması 15+ dk sürebildiği için
                              # (TTL < tarama süresi olursa /api/scan ASLA 200 dönmez).
_SCAN_CACHE = None            # son tarama sonucu (dict listesi)
_SCAN_CACHE_TS = 0.0          # son taramanın zaman damgası
_SCAN_CACHE_TOP_N = None      # cache'lenen top_n (farklı N için cache geçersiz)
_SCAN_LOCK = threading.Lock()  # eşzamanlı taramaları serileştirir (F5 patlaması)


def scan_top_5_stocks(top_n: int = 5) -> list:
    """BIST Tüm evrenini tarar, skorlar ve ilk N hisseyi döndürür.

    Performans: tüm semboller TEK yf.download çağrısıyla toplu çekilir
    (download_batch), ardından her hisse için göstergeler ThreadPoolExecutor ile
    paralel hesaplanır. 500+ hisse tek tek indirmek yerine birkaç saniyede biter.

    Eşzamanlılık: _SCAN_LOCK, aynı anda birden çok yf.download çalışmasını
    engeller (F5 patlaması). Sonuç SCAN_CACHE_TTL (10 dk) ömründe bellekte
    saklanır; cache taze ise istekler sıfır indirmeyle döner.
    """
    global _SCAN_CACHE, _SCAN_CACHE_TS, _SCAN_CACHE_TOP_N
    now = time.time()
    # Hızlı yol: cache taze ise lock'a girmeden döndür (F5'te sıfır bek).
    if _SCAN_CACHE is not None and _SCAN_CACHE_TOP_N == top_n \
            and (now - _SCAN_CACHE_TS) < SCAN_CACHE_TTL:
        return [dict(a) for a in _SCAN_CACHE]  # çağıran mutasyondan korunmuş kopya

    # Tek kritik bölge: indirme + hesap + cache yazma, lock altında.
    with _SCAN_LOCK:
        now = time.time()
        if _SCAN_CACHE is not None and _SCAN_CACHE_TOP_N == top_n \
                and (now - _SCAN_CACHE_TS) < SCAN_CACHE_TTL:
            return [dict(a) for a in _SCAN_CACHE]  # beklerken biri tazelemiş

        tickers = get_bist_tickers()
        try:
            batch = download_batch(tickers)
        except Exception:
            # Yahoo rate-limit / Invalid Crumb / ağ hatası: worker çökmesin;
            # varsa bayat cache, yoksa boş liste döndür.
            if _SCAN_CACHE is not None and _SCAN_CACHE_TOP_N == top_n:
                return [dict(a) for a in _SCAN_CACHE]
            return []
        if batch is None:
            if _SCAN_CACHE is not None and _SCAN_CACHE_TOP_N == top_n:
                return [dict(a) for a in _SCAN_CACHE]
            return []

        results = []
        futures = {}
        with ThreadPoolExecutor(max_workers=4) as pool:  # Render shared-CPU'ya uyumlu
            for sym in tickers:
                if isinstance(batch.columns, pd.MultiIndex):
                    sub = batch[sym] if sym in batch.columns.get_level_values(0) else None
                else:  # tek hisse düşerse
                    sub = batch
                if sub is None or sub.empty:
                    continue
                futures[pool.submit(_compute_analysis, sym, sub)] = sym
            for fut in as_completed(futures):
                try:
                    a = fut.result()
                except Exception:
                    continue  # tek hisse hatası tüm taramayı durdurmaz
                if a is None:
                    continue
                a["score"] = score_stock(a)
                results.append(a)

        results.sort(key=lambda x: x["score"], reverse=True)
        top = results[:top_n]
        _SCAN_CACHE = [dict(a) for a in top]
        _SCAN_CACHE_TS = now
        _SCAN_CACHE_TOP_N = top_n
        return [dict(a) for a in _SCAN_CACHE]


# --- Arka plan tarama yönetimi (non-blocking /api/scan) ---------------------
_SCAN_RUNNING = False          # arka plan taraması zaten çalışıyor mu
_SCAN_RUNNING_LOCK = threading.Lock()
_SCAN_LAST_ERROR = None        # son arka plan tarama hatası (teşhis)


def _scan_cache_fresh(top_n: int = 5) -> bool:
    """Cache dolu ve TTL içinde mi (indirme gerekmez mi)."""
    return (_SCAN_CACHE is not None and _SCAN_CACHE_TOP_N == top_n
            and (time.time() - _SCAN_CACHE_TS) < SCAN_CACHE_TTL)


def _ensure_scan_running():
    """Cache soğuksa taramayı TEK arka plan thread'inde başlatır.

    Eşzamanlı /api/scan istekleri (F5) yalnızca bir tarama başlatır; diğerleri
    mevcut arka plan işini bekler. HTTP isteğini ASLA bloklamaz — böylece
    Gunicorn 120s timeout'u (Bad Gateway) tetiklenmez.
    """
    global _SCAN_RUNNING
    with _SCAN_RUNNING_LOCK:
        if _SCAN_RUNNING:
            return
        if _scan_cache_fresh():
            return  # biri bu arada tazelemiş
        _SCAN_RUNNING = True

    def _bg():
        global _SCAN_RUNNING, _SCAN_LAST_ERROR
        try:
            scan_top_5_stocks()
            _SCAN_LAST_ERROR = None
        except Exception as e:  # pragma: no cover
            print(f"[!] Arka plan tarama hatası: {e}")
            _SCAN_LAST_ERROR = repr(e)
        finally:
            global _SCAN_RUNNING
            with _SCAN_RUNNING_LOCK:
                _SCAN_RUNNING = False

    threading.Thread(target=_bg, name="scan-background", daemon=True).start()

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
    """Top 5 momentum listesi — non-blocking.

    Cache taze ise anında döner. Cache soğuksa tarama arka plan thread'inde
    başlatılır ve 202 döner (Gunicorn 120s timeout / Bad Gateway koruması):
    HTTP isteği asla bloklanmaz.
    """
    if _scan_cache_fresh():
        return jsonify({"count": len(_SCAN_CACHE),
                        "results": [dict(a) for a in _SCAN_CACHE]})
    _ensure_scan_running()
    payload = {
        "status": "scanning",
        "message": "Tarama arka planda başlatıldı, lütfen 10 saniye sonra tekrar deneyin",
        "scan_running": _SCAN_RUNNING,
    }
    if _SCAN_LAST_ERROR:
        payload["last_error"] = _SCAN_LAST_ERROR
    return jsonify(payload), 202

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
    def cmd_ototarma(update, context):
            global AUTO_SCAN_ENABLED
            chat_id = update.effective_chat.id
            args = (context.args or [])
            if args:
                cmd = args[0].lower()
                if cmd in ("ac", "on", "aç", "1"):
                    AUTO_SCAN_ENABLED = True
                    AUTO_SUBSCRIBERS[chat_id] = True
                elif cmd in ("kapat", "off", "0"):
                    AUTO_SCAN_ENABLED = False
                    AUTO_SUBSCRIBERS[chat_id] = False
                else:
                    # Bilinmeyen argüman → durumu raporla, değiştirme
                    pass
            else:
                AUTO_SCAN_ENABLED = not AUTO_SCAN_ENABLED  # argümansız toggle
                AUTO_SUBSCRIBERS[chat_id] = AUTO_SCAN_ENABLED
            state = "AÇIK ✅" if AUTO_SCAN_ENABLED else "KAPALI ❌"
            update.message.reply_text(
                f"Otomatik tarama <b>{state}</b>.\n"
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
        if not AUTO_SCAN_ENABLED:
            return  # global kapatıldı (/ototarma kapat) → tarama durur
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
        # APScheduler 3.x yalnızca pytz timezone objelerini kabul eder
        # (strings desteklenmez) -> Europe/Istanbul açıkça pytz ile verilir.
        SCHEDULER = BackgroundScheduler(timezone=pytz.timezone("Europe/Istanbul"))
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
    # Cache ısındırma: açılışta arka planda ilk tarama → /api/scan açılışta bile
    # hazır sonuç döndürür (ilk istekte Bad Gateway / 120s timeout riski yok).
    _ensure_scan_running()
else:
    print("[!] TELEGRAM_BOT_TOKEN is missing. Running in web-only mode.")


if __name__ == "__main__":
    main()