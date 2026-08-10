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
SCAN_CACHE_FILE = os.getenv("SCAN_CACHE_FILE", "scan_cache.json")  # diske kalıcı önbellek

# --- BIST Tüm tarama evreni ------------------------------------------------
# ~500 BIST hissesi. Liste güncellenir; en güncel tam listeniz varsa
# ortam değişkeniyle BIST_TICKERS_FILE=/yol/liste.txt belirtin
# (her satır bir kod, ".IS" ekli ya da ekli değil). Varsayılan: aşağıdaki seed.
BIST_TICKERS_SEED = [
    # Banka & Finans
    "AKBNK.IS", "ALBRK.IS", "GARAN.IS", "HALKB.IS", "ISKUR.IS",
    "ISBIR.IS", "ISFIN.IS", "JANTS.IS", "KLNMA.IS", "SKBNK.IS",
    "TSKB.IS", "TUKAS.IS", "VAKFN.IS", "VAKBN.IS", "YKBNK.IS", 
    "AEFES.IS", "AKSA.IS", "AKSEN.IS", "AKSUE.IS",
    # Holding & Yatırım
    "AGHOL.IS", "ALARK.IS", "AVHOL.IS", "BAGFS.IS", "CCOLA.IS", "CIMSA.IS",
    "DOHOL.IS", "ECZYT.IS", "ENKAI.IS", "FROTO.IS", "GOLTS.IS",
    "GOZDE.IS", "GSDHO.IS", "KCHOL.IS",
    "NTHOL.IS", "OYAKC.IS", "SAHOL.IS", "SISE.IS", "TRCAS.IS",
    "TSPOR.IS", "TTRAK.IS", "YATAS.IS", "ZOREN.IS",
    # Gıda & İçecek
    "ARCLK.IS", "BANVT.IS", "BFREN.IS", "BIMAS.IS", "CANTE.IS",
    "ERSU.IS", "GENTS.IS", "IEYHO.IS", "IZFAS.IS",
    "KUTPO.IS", "MNDRS.IS", "PENGD.IS", "PINSU.IS",
    "TATGD.IS", "TBORG.IS", "ULKER.IS",
    "YAYLA.IS",
    # Petrokimya & Enerji
    "ALCAR.IS", "ALKIM.IS", "AYGAZ.IS", "BRISA.IS", "DMSAS.IS",
    "EGSER.IS", "EGEEN.IS", "ENERY.IS", "ENJSA.IS", "EREGL.IS", 
    "IZENR.IS", "KARSN.IS", "KRTEK.IS", "MAKTK.IS", "MRSHL.IS", "NATEN.IS",
    "ODAS.IS", "ORGE.IS", "PAPIL.IS", "PETKM.IS", "SAYAS.IS", "SODSN.IS",
    "TATEN.IS", "TAVHL.IS", "TERA.IS", "TUPRS.IS", "ZOREN.IS",
    # Savunma & Otomotiv & Teknoloji
    "ARCLK.IS", "ASELS.IS", "BERA.IS", "BJKAS.IS", "BOSSA.IS",
    "BRKSN.IS", "CLEBI.IS", "COSMO.IS", "DOAS.IS", "DOKTA.IS",
    "ECZYT.IS", "FMIZP.IS", "FROTO.IS", "GESAN.IS",
    "GRNYO.IS", "HEKTS.IS", "HUBVC.IS", "KARSN.IS", "KONTR.IS",
    "KCHOL.IS", "MAVI.IS", "MGROS.IS", "OTKAR.IS", "PGSUS.IS", "SDTTR.IS",
    "TAVHL.IS", "TOASO.IS", "TTKOM.IS", "TUKAS.IS", "VESTL.IS",
    # İlaç & Sağlık
    "BIOEN.IS", "ECILC.IS", "FADE.IS", "GENIL.IS",
    "GUBRF.IS", "IEYHO.IS", "INTEM.IS", "ISFIN.IS", "MEDTR.IS", "MEPET.IS",
    "NUGYO.IS", "OYLUM.IS", "SMRTG.IS", "TMPOL.IS",
    "TRILC.IS",
    # Hizmet & Turizm & GYO
    "AKENR.IS", "AKMGY.IS", "ALGYO.IS", "ATSYH.IS", "AVTUR.IS", 
    "DOHOL.IS", "EKGYO.IS", "EMKEL.IS", "HLGYO.IS", "ISGYO.IS", "KLKIM.IS",
    "MARTI.IS", "METRO.IS", "MIATK.IS", "MTRKS.IS", "NETAS.IS",
    "PEKGY.IS", "RGYAS.IS", "SARKY.IS", "SNGYO.IS", "TSGYO.IS", "TUPRS.IS",
    "VKGYO.IS", "YKBNK.IS",
    # Diğer / Tek halka
    "AFYON.IS", "ARASE.IS", "ARENA.IS",
    "ARZUM.IS", "ASUZU.IS", "AVOD.IS",
    "AYCES.IS", "BAGFS.IS", "BAKAB.IS", "BASGZ.IS", "BLCYT.IS",
    "BORSK.IS", "BTCIM.IS", "BUCIM.IS", "BURVA.IS", "CANTE.IS", "CASA.IS",
    "CEMTS.IS", "CELHA.IS", "CEMAS.IS", "CUSAN.IS", "DAGI.IS",
    "DERIM.IS", "DESA.IS", "DIRIT.IS", "DITAS.IS", "DOCO.IS",
    "DOKTA.IS", "DURDO.IS", "DYOBY.IS", "ECZYT.IS", "EGEPO.IS", "EKIZ.IS",
    "ETYAT.IS", "EUREN.IS", "EUYO.IS", "FORTE.IS", "FRIGO.IS", "GARFA.IS",
    "GEDZA.IS", "GLYHO.IS", "GOODY.IS", "GRNYO.IS",
    "HDFGS.IS", "INFO.IS", "ISKPL.IS", "ISMEN.IS",
    "KAYSE.IS", "KCHOL.IS", "KLMSN.IS", "LIDER.IS", "LUKSK.IS",
    "MAGEN.IS", "MAKIM.IS", "NUGYO.IS",
    "OBAMS.IS", "ORCAY.IS", "OSMEN.IS", "OZSUB.IS",
    "PARSN.IS", "PASEU.IS", "PATEK.IS", "POLHO.IS", "PRZMA.IS", 
    "REEDR.IS", "SAFKR.IS", "SARKY.IS",
    "SEKUR.IS", "SEYKM.IS", "SILVR.IS", "SKTAS.IS", "SUMAS.IS",
    "TAVHL.IS", "TCELL.IS", "TEKTU.IS", "THYAO.IS", "TKFEN.IS", "TKNSA.IS",
    "TMSN.IS", "TUKAS.IS", "ULUSE.IS", "VKING.IS", "VKING.IS",
    # GYO & Gayrimenkul
    "AGYO.IS", "AKFGY.IS", "AKSGY.IS", "ALGYO.IS", "ATAGY.IS", 
    "DZGYO.IS", "KGYO.IS", "KLGYO.IS",
    "KRGYO.IS", "MRGYO.IS", "OZKGY.IS",
    "PAGYO.IS", "RGYAS.IS", "YGGYO.IS",
    # Makine, İnşaat & Metal
    "ASUZU.IS",
    "CLEBI.IS", "DENGE.IS", "DIRIT.IS",
    "DMRGD.IS", "EMNIS.IS", "ERBOS.IS", "EREGL.IS",
    "FENER.IS", "GEREL.IS", "GOKNR.IS", "GOLTS.IS", "IEYHO.IS",
    "IHEVA.IS", "INVES.IS", "IZMDC.IS", "KLKIM.IS", "KONYA.IS",
    "KRDMD.IS", "KUTPO.IS", "MAALT.IS", "MERKO.IS", "NUHCM.IS",
    "OZATD.IS", "PASEU.IS", "PRKME.IS", "SAFKR.IS", "SARKY.IS",
    "SILVR.IS", "SODSN.IS", "TAVHL.IS", "TCELL.IS",
    "TKNSA.IS", "TUKAS.IS", "VAKKO.IS", "VKGYO.IS", "YAPRK.IS",
    "ZOREN.IS", "DOGUB.IS", "TUKAS.IS", "KCHOL.IS", "TUPRS.IS",
    # Diğer şirketler
    "ADESE.IS", "AFYON.IS",
    "ASELS.IS", "ATSYH.IS", "AVTUR.IS", "AYEN.IS", "BALAT.IS", "BANVT.IS",
    "BASGZ.IS", "BFREN.IS", "BRMEN.IS",
    "BSOKE.IS", "BTCIM.IS", "CMBTN.IS", "COSMO.IS", "CVKMD.IS", "DURKN.IS",
    "EGPRO.IS", "EKIZ.IS", "ERSU.IS",
    "ESCAR.IS", "ESCOM.IS", "ETYAT.IS", "EUREN.IS", "FADE.IS", "FMIZP.IS",
    "FORTE.IS", "GEDZA.IS", "GEREL.IS", "GLYHO.IS", "GOODY.IS",
    "GSDDE.IS", "INFO.IS",
    "ISKUR.IS", "ISMEN.IS", "KAREL.IS", "KARTN.IS", "KONYA.IS",
    "KORDS.IS", "LIDFA.IS", "MAKIM.IS", "MEGMT.IS",
    "MERCN.IS", "METRO.IS",
    "NETAS.IS", "NUGYO.IS", "OBAMS.IS", "ORGE.IS", "OSMEN.IS", "OTKAR.IS",
    "PARSN.IS", "PATEK.IS", "PKART.IS", "PLTUR.IS", "POLHO.IS", "PRKAB.IS",
    "PRZMA.IS", "REEDR.IS",
    "SAFKR.IS", "SARKY.IS", "SEKUR.IS",
    "SMRTG.IS", "SUNTK.IS", "SUWEN.IS", "TATEN.IS",
    "TBORG.IS", "TEKTU.IS", "TUREX.IS",
    "UFUK.IS", "ULAS.IS", "ULUFA.IS", "ULUUN.IS",
    "VBTYZ.IS", "VERTU.IS", "VKING.IS", "YATAS.IS",
    "YONGA.IS", "YUNSA.IS", "ZOREN.IS",
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
def fetch_data(symbol: str) -> tuple:
    """6 aylık günlük OHLCV verisi + veri kaynağı döndürür: (df, kaynak).

    Önce yfinance dener; başarısız olursa (hata, boş DF, timeout) GÜVENLİ yedek
    olarak İş Yatırım API'sine (isyatirimhisse) düşer. isyatirimhisse çağrısı da
    try/except içindedir; sunucu IP'yi engellerse veya yanıt vermezse worker
    çökmez, (None, kaynak) yumuşak dönülür.
    """
    try:
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as _YF_FutTimeout
        # Yahoo, Render veri-merkezi IP'sini rate-limit edebilir; yf.download'in
        # timeout=20'si yalnızca bağlantı-başınadır ve toplamı sınırlamaz. Bu
        # yüzden YF çağrısı da 20s'lik thread-timeout'a alınır -> toplam blok
        # ~20s(yf)+15s(isy) = ~35s < Render proxy ~60s; 502 olmaz.
        _yf_pool = ThreadPoolExecutor(max_workers=1)
        try:
            _yf_fut = _yf_pool.submit(yf.download, symbol,
                                      period="6mo", interval="1d",
                                      progress=False, auto_adjust=True,
                                      threads=False, timeout=20)
            try:
                df = _yf_fut.result(timeout=20)
            except _YF_FutTimeout:
                df = None  # yavaş/takılı Yahoo -> yedek kaynağa geç
        finally:
            _yf_pool.shutdown(wait=False)  # takılı thread'i bekleme
        if df is not None and not df.empty and len(df) >= 60:
            if isinstance(df.columns, pd.MultiIndex):
                df = df.copy()
                df.columns = df.columns.get_level_values(0)
            return df[["Open", "High", "Low", "Close", "Volume"]].astype(float), "Yahoo Finance"
    except Exception:
        pass  # yfinance hata verdi → yedek kaynağa geç

    # --- Güvenli yedek: İş Yatırım API'si (isyatirimhisse) ---
    try:
        import datetime as _dt
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as _FutTimeout
        from isyatirimhisse import fetch_stock_data
        code = symbol.replace(".IS", "").strip()
        end = _dt.date.today()
        start = end - _dt.timedelta(days=200)
        # Ağ çağrısı 15s ile sınırlanır: İş Yatırım IP'yi engeller/takılırsa
        # Gunicorn 120s'yi aşan block olusmaz; worker çökmez, yumuşak döner.
        raw = None
        _pool = ThreadPoolExecutor(max_workers=1)  # with kulanma: __exit__->wait=True
        try:
            _fut = _pool.submit(fetch_stock_data,
                                code, start.strftime("%d-%m-%Y"), end.strftime("%d-%m-%Y"))
            try:
                raw = _fut.result(timeout=15)
            except _FutTimeout:
                return None, "İş Yatırım"  # yavaş/takılı sunucu -> yumuşak hata
        finally:
            _pool.shutdown(wait=False)  # takılı thread'i bekleme
        if raw is None or raw.empty:
            return None, "İş Yatırım"
        raw = raw[~raw["HGDG_TARIH"].isna()].copy()
        raw["HGDG_TARIH"] = pd.to_datetime(raw["HGDG_TARIH"])
        raw = raw.dropna(subset=["HGDG_KAPANIS", "HGDG_MAX", "HGDG_MIN", "HGDG_HACIM"])
        df = pd.DataFrame({
            "Open": raw["HGDG_AOF"].astype(float),
            "High": raw["HGDG_MAX"].astype(float),
            "Low": raw["HGDG_MIN"].astype(float),
            "Close": raw["HGDG_KAPANIS"].astype(float),
            "Volume": raw["HGDG_HACIM"].astype(float),
        })
        df.index = pd.DatetimeIndex(raw["HGDG_TARIH"])
        df = df.sort_index()
        if len(df) < 60:
            return None, "İş Yatırım"
        return df, "İş Yatırım"
    except Exception:
        # İş Yatırım sunucusu engelledi / yanıt vermedi → yumuşak hata (worker çökmez)
        return None, "İş Yatırım"


def download_batch(symbols: list, chunk_size: int = 40, period: str = "3mo") -> Optional[pd.DataFrame]:
    """BIST listesini PARÇALI (chunked) yf.download çağrılarıyla indirir.

    278 hisselik evren tek dev yf.download yerine `chunk_size` (varsayılan 40)
    hisselik alt gruplara bölünür; her parça kendi timeout=20 değeriyle çekilir.
    Böylece tek bir takılan/yavaş hisse tüm batch'i kilitlemez ve bellek (RAM)
    yükü her çağrıda düşük kalır — Render free tier (512MB) için güvenli.
    Parçalar sütun ekseninde (axis=1) birleştirilerek aynı MultiIndex
    (ticker, alan) çerçevesine geri döndürülür.
    """
    symbols = list(dict.fromkeys(symbols))  # yinelenenleri koru
    if not symbols:
        return None
    import math
    frames = []
    for start in range(0, len(symbols), chunk_size):
        piece = symbols[start:start + chunk_size]
        try:
            df = yf.download(
                piece, period=period, interval="1d",
                                progress=False, auto_adjust=True, threads=True,
                group_by="ticker", timeout=20,
            )
            if df is not None and not df.empty:
                frames.append(df)
        except Exception:
            # Bir parça başarısız olursa tüm evreni düşürme; parçayı atla.
            continue
    if not frames:
        return None
    if len(frames) == 1:
        return frames[0]
    # Sütun ekseninde birleştir (her parça MultiIndex: ticker x alan).
    return pd.concat(frames, axis=1)

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


def _compute_analysis(symbol: str, df: pd.DataFrame, data_source: str = "Yahoo Finance") -> Optional[dict]:
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
        "data_source": data_source,
    }


def analyze_single_stock(symbol: str) -> Optional[dict]:
    """HERHANGİ bir geçerli hisse için eksiksiz analiz döndürür (/sorgu)."""
    df, source = fetch_data(symbol)
    if df is None:
        return None
    return _compute_analysis(symbol, df, source)


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
_PENDING_GUNCELTOP5 = set()     # /gunceltop5 isteyen chat_id listesi
_PENDING_LOCK = threading.Lock()  # pending listesini serialize eder


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
        _save_scan_cache_disk(_SCAN_CACHE)  # diske kalıcı önbellek (restore-safe)
        return [dict(a) for a in _SCAN_CACHE]


# --- Arka plan tarama yönetimi (non-blocking /api/scan) ---------------------
_SCAN_RUNNING = False          # arka plan taraması zaten çalışıyor mu
_SCAN_RUNNING_LOCK = threading.Lock()
_SCAN_LAST_ERROR = None        # son arka plan tarama hatası (teşhis)


def _now_tr_str():
    """İstanbul saatiyle şimdiki zaman damgası (disk cache için)."""
    import datetime
    tr = datetime.datetime.now(pytz.timezone("Europe/Istanbul"))
    return tr


def _save_scan_cache_disk(cache: list):
    """Tarama sonucunu diske (scan_cache.json) kalıcı olarak yazar.

    Render free tier'da instance zaman zaman restore/sleep olur; diske yazılan
    önbellek sayesinde uygulama yeniden başladığında bile /api/scan ve /top5
    0 ms yanıt verebilir (yeniden indirme/zaman alan tarama gerekmez).
    """
    try:
        ts = _now_tr_str()
        disk = {
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "epoch": ts.timestamp(),
            "top_n": _SCAN_CACHE_TOP_N,
            "results": [dict(a) for a in cache],
        }
        tmp = SCAN_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            import json
            json.dump(disk, f, ensure_ascii=False)
        import os as _os
        _os.replace(tmp, SCAN_CACHE_FILE)  # atomik yazma (yarım dosya okunmaz)
    except Exception as e:  # pragma: no cover — disk hatası taramayı durdurmasın
        print(f"[!] Disk cache yazılamadı: {e}")


def _load_scan_cache_disk() -> Optional[list]:
    """scan_cache.json'dan (varsa geçerli) sonucu döndürür; yoksa None.

    "Geçerli" = dosya mevcut VE results listesi boş değil. TTL ayrımı yapılmaz;
    geçerlilik kararı arayan fonksiyondadır (bugüne-ait kontrolü api/scheduler'da).
    """
    try:
        if not os.path.isfile(SCAN_CACHE_FILE):
            return None
        import json
        with open(SCAN_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        results = data.get("results") or []
        top_n = data.get("top_n") or 5
        ts = data.get("timestamp") or ""
        if not results:
            return None
        return {"results": results, "top_n": top_n, "timestamp": ts}
    except Exception as e:  # pragma: no cover
        print(f"[!] Disk cache okunamadı: {e}")
        return None


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
            _dispatch_gunceltop5()  # bekleyenlere yeni Top-5'i gönder

    threading.Thread(target=_bg, name="scan-background", daemon=True).start()


def _get_cached_top5() -> Optional[list]:
    """Mevcut Top-5 sonucunu, indirme YAPMADAN döndürür (/top5 için).

    Öncelik: in-memory TTL cache; yoksa diske yazılmış kalıcı cache. Canlı
    tarama başlatmaz -> /top5 komutu her zaman 0 ms yanıt verir.
    """
    global _SCAN_CACHE, _SCAN_CACHE_TS, _SCAN_CACHE_TOP_N
    if _scan_cache_fresh():
        return [dict(a) for a in _SCAN_CACHE]
    disk = _load_scan_cache_disk()
    if disk and disk.get("results"):
        # diski bellek cache'ine de yükle (sonraki çağrılar daha da hızlı)
        _SCAN_CACHE = [dict(a) for a in disk["results"]]
        _SCAN_CACHE_TOP_N = disk.get("top_n") or 5
        # epoch yoksa timestamp'tan dene
        try:
            import datetime
            ts = disk.get("timestamp", "") or ""
            _SCAN_CACHE_TS = datetime.datetime.strptime(
                ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC).timestamp()
        except Exception:
            _SCAN_CACHE_TS = time.time() - SCAN_CACHE_TTL  # bayat varsay (indirme çalışır)
        return [dict(a) for a in _SCAN_CACHE]
    return None


def _last_scan_display_str() -> str:
    """Son taramanın İstanbul saatiyle okunur zaman damgası (/top5 için)."""
    try:
        import datetime
        if not _SCAN_CACHE_TS:
            return "Bilinmiyor"
        tr = datetime.datetime.fromtimestamp(_SCAN_CACHE_TS,
                                             pytz.timezone("Europe/Istanbul"))
        return tr.strftime("%d %B %Y - %H:%M")
    except Exception:
        return "Bilinmiyor"


def _dispatch_gunceltop5():
    """Arka plan taraması bitince /gunceltop5 bekleyenlere yeni Top-5'i gönder."""
    global _PENDING_GUNCELTOP5
    if not _PENDING_GUNCELTOP5:
        return
    top = _get_cached_top5()
    if not top:
        return
    msg = "<b>🔥 Yeni Top 5 Momentum</b>\n\n"
    for i, a in enumerate(top, 1):
        msg += f"<b>{i}.</b> " + fmt_stock_line(a, show_score=True) + "\n"
    msg += f"\n📊 <b>Kaynak:</b> {top[0].get('data_source', 'Yahoo Finance')}"
    import threading as _th
    with _th.Lock():  # idempotent: sadece mevcut listedekilere gönder
        chat_ids = list(_PENDING_GUNCELTOP5)
        _PENDING_GUNCELTOP5 = set()
    for chat_id in chat_ids:
        try:
            if BOT is not None:
                BOT.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
        except Exception:
            pass

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
    top = _get_cached_top5()
    if top:
        return jsonify({"count": len(top),
                        "results": top})
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


# =============================================================================
# 5b) TRADEKING V6: İZLEME LİSTESİ + SİNYAL MOTORU (BIST-uyarlı)
# =============================================================================
# btcv6'dan (EMA pullback + ATR risk/ödül + state machine cooldown + trend
# filtresi) esinlenerek, BIST günlük bar + kullanıcı bazlı watchlist yapısına
# uyarlandı. Birebir kopyalanmadı — her kullanıcının kendi izleme listesi,
# hisse başına maliyet/state/cooldown, batch indirme ve kural tabanlı sinyal.
# -----------------------------------------------------------------------------
WATCHLIST_FILE = os.getenv("WATCHLIST_FILE", "watchlists.json")
_WATCHLIST_LOCK = threading.Lock()

# sinyal seviyeleri (btcv6 riskManagement'tan uyarlanmış sabitler)
V6_ATR_STOP_MULT = 1.5     # Stop = Close - (1.5 * ATR)
V6_ATR_TP_MULT = 2.0       # TP1  = Close + (2.0 * ATR)
V6_PULLBACK_PCT = 0.01     # EMA8/13'e ±%1 yakınlık
V6_MAX_RSI = 60.0          # alımda RSI < 60
V6_COOLDOWN_START = 6      # sinyal sonrası 6 tik (30dk x6 = 3 saat) tekrarlamaz


def _load_watchlists() -> dict:
    """watchlists.json okur (thread-safe). {chat_id_str: {SYM: {...}}}"""
    with _WATCHLIST_LOCK:
        if not os.path.isfile(WATCHLIST_FILE):
            return {}
        try:
            import json
            with open(WATCHLIST_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[!] watchlists.json okunamadı: {e}")
            return {}


def _save_watchlists(data: dict):
    """watchlists.json atomik yazar (tmp + os.replace, thread-safe)."""
    with _WATCHLIST_LOCK:
        try:
            import json
            tmp = WATCHLIST_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, WATCHLIST_FILE)  # atomik: yarım dosya oluşmaz
        except Exception as e:
            print(f"[!] watchlists.json yazılamadı: {e}")


def add_to_watchlist(chat_id, symbol: str, cost=None) -> bool:
    """Kullanıcı izleme listesine hisse ekler (V6 initial state: FLAT)."""
    data = _load_watchlists(); cid = str(chat_id)
    data.setdefault(cid, {})
    data[cid][symbol] = {
        "symbol": symbol,
        "cost": cost,
        "state": "FLAT",
        "cooldown_counter": 0,
        "added_at": _now_tr_str().strftime("%Y-%m-%d %H:%M"),
    }
    _save_watchlists(data)
    return True


def remove_from_watchlist(chat_id, symbol: str) -> bool:
    """Kullanıcı izleme listesinden hisse çıkarır."""
    data = _load_watchlists(); cid = str(chat_id)
    if cid in data and symbol in data[cid]:
        del data[cid][symbol]
        if not data[cid]:
            del data[cid]
        _save_watchlists(data)
        return True
    return False


def parse_watchlist_input(text: str):
    """'THYAO' veya 'THYAO 285.50' -> (symbol, cost); geçersizse None."""
    parts = (text or "").strip().split()
    if not parts:
        return None
    sym = parts[0].upper()
    if not sym.endswith(".IS"):
        sym += ".IS"
    cost = None
    if len(parts) > 1:
        try:
            cost = float(parts[1].replace(",", "."))
        except ValueError:
            cost = None
    return sym, cost


def unique_watchlist_symbols() -> list:
    """Tüm kullanıcıların izleme listelerindeki benzersiz hisse kodları."""
    data = _load_watchlists(); out = []
    for cid, d in data.items():
        for sym in d:
            if sym not in out:
                out.append(sym)
    return out


def _v6_trend(df) -> str:
    """Uzun vadeli trend: EMA50 > EMA200 -> 'YUKSELEN'; altı -> 'DUSEN'."""
    if df is None or len(df) < 210:
        return "YETERSIZ"
    try:
        close = df["Close"].astype(float)
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])
        return "YUKSELEN" if ema50 > ema200 else "DUSEN"
    except Exception:
        return "YETERSIZ"


def _v6_analyze(df):
    """V6 göstergelerini tek veri çerçevesinden hesaplar (dict)."""
    if df is None or df.empty or len(df) < 60:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy(); df.columns = df.columns.get_level_values(0)
    close = df["Close"].astype(float); high = df["High"].astype(float)
    low = df["Low"].astype(float)
    price = float(close.iloc[-1])
    try:
        atr = float(ta.atr(high, low, close, length=14).iloc[-1])
    except Exception:
        atr = float((high.iloc[-1] - low.iloc[-1]))
    rsi = float(ta.rsi(close, length=14).iloc[-1])
    ema8 = float(close.ewm(span=8, adjust=False).mean().iloc[-1])
    ema13 = float(close.ewm(span=13, adjust=False).mean().iloc[-1])
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    hist = 0.0
    try:
        m = ta.macd(close, fast=12, slow=26, signal=9)
        hist = float((m["MACD_12_26_9"] - m["MACDs_12_26_9"]).iloc[-1])
    except Exception:
        hist = 0.0
    stop = price - (V6_ATR_STOP_MULT * atr)
    tp = price + (V6_ATR_TP_MULT * atr)
    return {
        "price": price, "atr": atr, "rsi": rsi,
        "ema8": ema8, "ema13": ema13, "ema50": ema50,
        "macd_hist": hist, "atr_stop": stop, "atr_tp": tp,
        "trend": _v6_trend(df),
    }


def check_watchlist_signals():
    """TÜM kullanıcı watchlist'lerini tarar (bench batch; state machine).

    Dönüş: {chat_id_str: [(symbol, sinyal_dict), ...]} — gönderici (scheduler)
    Telegram mesajına çevirir. Sinyal alan hisse COOLDOWN'a girer; sayaç her
    koşuda 1 azalır, 0 olunca FLAT (3 saatte aynı alarm tekrarlamaz).
    """
    syms = unique_watchlist_symbols()
    if not syms:
        return {}
    # Batch indirme: tüm benzersiz kodlar TEK download_batch (1y -> EMA200)
    batch = None
    try:
        batch = download_batch(syms, period="1y")
    except Exception:
        batch = None

    alerts = {}
    data = _load_watchlists()
    for cid, holdings in data.items():
        for sym, rec in holdings.items():
            sig = _evaluate_symbol(sym, rec, batch)
            if sig:
                alerts.setdefault(cid, []).append((sym, sig))
    return alerts


def _v6_decision(a, cost):
    """Saf sinyal kararı (btcv6 StrategyEngine tarzı, BIST-uyarlı).

    a: _v6_analyze çıktısı. Döner: ('AL'|'STOP'|'KAR_AL'|None, gerekçe).
    Sıralama: önce Stop/KarAl (fiyat risk seviyesinin dışında), sonra AL/pullback.
    """
    if a is None:
        return None, "yetersiz veri"
    price = a["price"]
    # Stop/KarAl bandı: tek maliyet için maliyet±%3 ile ATR seviyeleri birleştirilir
    stop_band = min(cost * 0.97, a["atr_stop"]) if cost else a["atr_stop"]
    tp_band = max(cost * 1.03, a["atr_tp"]) if cost else a["atr_tp"]
    if price <= stop_band:
        return "STOP", "Fiyat durdurma seviyesinin altına düştü"
    if price >= tp_band:
        return "KAR_AL", "Fiyat kâr hedefi ATR TP1 seviyesine ulaştı"
    # AL / PULLBACK: yalnızca yükselen trend + pullback + RSI<60 + MACD hist>0
    if a["trend"] != "YUKSELEN":
        return None, "trend yükselen değil"
    near8 = abs(price - a["ema8"]) / a["ema8"] <= V6_PULLBACK_PCT
    near13 = abs(price - a["ema13"]) / a["ema13"] <= V6_PULLBACK_PCT
    if not (near8 or near13):
        return None, "fiyat EMA8/13 destek bölgesinde değil"
    if a["rsi"] >= V6_MAX_RSI:
        return None, "RSI aşırı yüksek"
    if a["macd_hist"] <= 0:
        return None, "MACD histogram pozitif değil"
    return "AL", "Yükselen trendde EMA desteğinden tepki alındı"


def _evaluate_symbol(sym, rec, batch):
    """Tek hisse için V6 sinyal üretimi + state machine/cooldown güncelle."""
    if rec.get("state") == "COOLDOWN":
        # her 30dk tikte sayaç 1 azalt; 0 olunca FLAT (tekrar alım serbest)
        rec["cooldown_counter"] = max(0, rec.get("cooldown_counter", 1) - 1)
        if rec["cooldown_counter"] <= 0:
            rec["state"] = "FLAT"
        _persist_rec(rec)
        return None

    sub = None
    if batch is not None and not batch.empty:
        try:
            if isinstance(batch.columns, pd.MultiIndex):
                sub = batch[sym] if sym in batch.columns.get_level_values(0) else None
            else:
                sub = batch
        except Exception:
            sub = None
        if sub is not None and sub.empty:
            sub = None
    if sub is None:
        # gerekirse tek indirme (batch'e girememişse) — sinyal ağ erişimine düşebilir
        df, _src = fetch_data(sym)
        sub = df
    a = _v6_analyze(sub)
    if a is None:
        return None
    cost = rec.get("cost")
    kind, reason = _v6_decision(a, cost)
    if kind is None:
        return None
    # state machine: AL sinyali hisseyi COOLDOWN'a alır (3 saat tekrarlamaz)
    if kind == "AL":
        rec["state"] = "COOLDOWN"
        rec["cooldown_counter"] = V6_COOLDOWN_START
        _persist_rec(rec)
    return _signal(sym, kind, a, cost, reason)


def _signal(sym, kind, a, cost, reason):
    """V6 sinyal dict'i (state/cooldown, _evaluate_symbol tarafından yönetilir)."""
    return {
        "symbol": sym, "kind": kind, "price": a["price"],
        "rsi": a["rsi"], "atr": a["atr"], "atr_stop": a["atr_stop"],
        "atr_tp": a["atr_tp"], "trend": a["trend"], "reason": reason,
        "cost": cost,
    }


def _persist_rec(rec):
    """Değişen state/counter'ı diske geri yazar (sembol bazlı eşleme).

    Not: _load_watchlists her çağrıda JSON'dan TAZE dict üretir; bu yüzden
    referans eşitliği (r is rec) asla tutmaz. Sembol adıyla eşleşip ilgili
    kaydın state/counter alanlarını güncelleriz.
    """
    sym = rec.get("symbol")
    if not sym:
        return
    data = _load_watchlists()
    changed = False
    for cid, d in data.items():
        if sym in d:
            d[sym]["state"] = rec.get("state", "FLAT")
            d[sym]["cooldown_counter"] = rec.get("cooldown_counter", 0)
            changed = True
    if changed:
        _save_watchlists(data)


def fmt_watchlist_price(rec, a):
    """Etkileşimli /watchlist satırı: sembol + fiyat + maliyet bazlı % kar/zarar."""
    if a is None:
        return f"<b>{rec['symbol']}</b> — veri yok"
    price = a["price"]
    cost = rec.get("cost")
    tag = ""
    if cost:
        pnl = (price - cost) / cost * 100
        emoji = "🟢" if pnl >= 0 else "🔴"
        tag = f" | Maliyet {cost:,.2f} ₺ 👉 {emoji} %{pnl:+.2f}"
    return (f"<b>{rec['symbol'].replace('.IS','')}</b> — "
            f"<code>{price:,.2f} ₺</code>{tag} | 🧍 {rec.get('state','FLAT')}")


def _watchlist_price(sym):
    """Tek hisse için (display satırı) güncel fiyat + göstergeler."""
    sub, _src = fetch_data(sym)
    return _v6_analyze(sub)



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
        from telegram import ReplyKeyboardMarkup
        kb = ReplyKeyboardMarkup([
            ["🎯 Top 5 Hisse", "⭐ İzleme Listem"],
            ["💰 Portföy Planı", "⚙️ Otomatik Tarama"],
            ["ℹ️ Bilgi & Yardım"],
        ], resize_keyboard=True)
        update.message.reply_text(
            "<b>🎯 BIST Trading Bot'a hoş geldiniz!</b>\n\n"
            "<b>Hızlı Başlangıç:</b>\n"
            "• <code>/sorgu GOZDE</code> → tek hisse analizi\n"
            "• <code>/top5</code> → en iyi 5 momentum hissesi\n"
            "• <code>/portfoy</code> → 100.000 TL sermaye planı\n"
            "• <code>/bilgi</code> → tüm komutlar ve strateji\n"
            "• <code>/gunceltop5</code> → arka planda taze Top 5 taraması\n\n"
            "Yarışma dönemi: <b>10 Ağu – 28 Ağu</b> 🗓️",
            reply_markup=kb, parse_mode="HTML",
        )

    # --- /bilgi ---
    def cmd_bilgi(update, context):
        from telegram import ReplyKeyboardMarkup
        kb = ReplyKeyboardMarkup([
            ["🎯 Top 5 Hisse", "⭐ İzleme Listem"],
            ["💰 Portföy Planı", "⚙️ Otomatik Tarama"],
            ["ℹ️ Bilgi & Yardım"],
        ], resize_keyboard=True)
        update.message.reply_text(
            "<b>🧭 Kullanım Kılavuzu</b>\n\n"
            "<b>Komutlar:</b>\n"
            "• <code>/sorgu KOD</code> → hisse raporu (Ör: <code>/sorgu GOZDE</code>)\n"
            "   Fiyat, RSI, MACD, EMA, 20G destek/direnç, tüm pivot seviyeleri.\n"
            "• <code>/top5</code> → skorlanmış ilk 5 momentum hissesi (+%6 hedef, -%3 stop).\n"
            "• <code>/portfoy</code> → 100.000 TL'yi 4 eşit pozisyona bölme planı.\n"
            "• <code>/ototarma ac|kapat</code> → periyodik otomatik tarama uyarıları.\n"
            "• <code>/gunceltop5</code> → arka planda ilk 5'i tazeler ve sonucu bildirir.\n\n"
            "<b>📈 Strateji (3 hafta — 10-28 Ağu):</b>\n"
            "1) Hacim patlaması + trend (Fiyat>EMA20>EMA50) + RSI 55-72.\n"
            "2) 20 günlük direncin kırılımına yakın hisseleri seç.\n"
            "3) Hedef +%6, sert stop -%3 (R/R ≈ 2:1).\n"
            "4) Her seferinde max 1-2 pozisyon açık tut (sermaye 100.000 TL).",
            reply_markup=kb, parse_mode="HTML",
        )

    # --- /top5 ---
    def cmd_top5(update, context):
        # Akıllı önbellek: /top5 ASLA canlı tarama başlatmaz -> 0 ms yanıt.
        # Önce bellek/disk cache'ini döndürür; cache yoksa yönlendirir.
        top = _get_cached_top5()
        if not top:
            update.message.reply_text(
                "Henüz bir Top 5 sonucu yok. Arka planda taze tarama için "
                "<code>/gunceltop5</code> komutuna dokunabilirsiniz.",
                parse_mode="HTML")
            return
        msg = "<b>🔥 Top 5 Momentum</b>\n\n"
        for i, a in enumerate(top, 1):
            msg += f"<b>{i}.</b> " + fmt_stock_line(a, show_score=True) + "\n"
        msg += f"\n📊 <b>Kaynak:</b> {top[0].get('data_source', 'Yahoo Finance')}"
        msg += f"\n🕒 <b>Son Güncelleme:</b> {_last_scan_display_str()}"
        msg += ("\n🔄 <i>Daha güncel bir Top 5 istiyorsanız /gunceltop5 "
                "komutuna dokunabilirsiniz.</i>")
        update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)


    def cmd_gunceltop5(update, context):
        # Asenkron: kullanıcıyı ASLA beklemez; anında bilgi + arka plan taraması.
        chat_id = update.effective_chat.id
        update.message.reply_text(
            "⏳ <b>Taze Top 5 Taraması Başlatıldı!</b>\n\n"
            "BİST evreninin taranması arka planda devam ediyor. Siz işlerinize "
            "devam edebilirsiniz; tarama tamamlandığında sizi buradan "
            "bilgilendireceğim! 🔔",
            parse_mode="HTML")
        global _PENDING_GUNCELTOP5
        with _PENDING_LOCK:
            _PENDING_GUNCELTOP5.add(chat_id)
        _ensure_scan_running()

    # --- /sorgu ---
    def run_sorgu(update, context, raw_symbol):
        """Verilen kod için analiz üretip kullanıcıya gönderir (parametre veya
        ForceReply akışından gelen metin için ortak akış)."""
        symbol = raw_symbol.strip().upper()
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
            f"Destek S1: <code>{p['S1']:.2f}</code> | S2: <code>{p['S2']:.2f}</code> | S3: <code>{p['S3']:.2f}</code>\n"
            f"\n📊 <b>Kaynak:</b> {a['data_source']}"
        )
        update.message.reply_text(msg, parse_mode="HTML")

    def cmd_sorgu(update, context):
        args = context.args
        if args:
            run_sorgu(update, context, args[0])  # parametre verildi -> doğrudan analiz
            return
        # Parametre yok / 🔍 Hisse Sorgu butonu -> etkileşimli sorgu (ForceReply)
        context.user_data["awaiting_sorgu"] = True
        from telegram import ForceReply
        update.message.reply_text(
            "🔍 <b>Hisse Analizi</b>\n\n"
            "Lütfen incelemek istediğiniz hisse kodunu yazın "
            "(Örn: <code>THYAO</code>, <code>GARAN</code>):",
            reply_markup=ForceReply(selective=True), parse_mode="HTML")

    # --- /watchlist (TradeKing V6: interaktif izleme listesi) ---
    def cmd_watchlist(update, context):
        cid = update.effective_chat.id
        if context.args:
            # /watchlist THYAO [maliyet] -> dogrudan ekle
            parsed = parse_watchlist_input(" ".join(context.args))
            if parsed:
                sym, cost = parsed
                add_to_watchlist(cid, sym, cost)
                update.message.reply_text(
                    f"⭐ <b>İzleme listesine eklendi:</b> <code>{sym}</code>"
                    + (f" ({cost:,.2f} ₺ maliyet)" if cost else ""),
                    parse_mode="HTML")
            else:
                update.message.reply_text("Geçersiz kod. Örn: <code>/watchlist THYAO 285.50</code>",
                                          parse_mode="HTML")
            return
        holdings = _load_watchlists().get(str(cid), {})
        if not holdings:
            # Boş liste -> ForceReply ile ekleme istemi
            context.user_data["awaiting_watchlist"] = True
            from telegram import ForceReply
            update.message.reply_text(
                "⭐ <b>İzleme Listesi</b>\n\n"
                "Listeniz henüz boş. Eklemek istediğiniz hisse kodunu ve varsa "
                "maliyetinizi yazın (Örn: <code>THYAO</code> veya <code>THYAO 285.50</code>):",
                reply_markup=ForceReply(selective=True), parse_mode="HTML")
            return
        # Dolu liste -> takip edilen hisseler + güncel fiyat + kar/zarar + `/sil_`
        lines = []
        for sym, rec in holdings.items():
            a = _watchlist_price(sym)
            lines.append(fmt_watchlist_price(rec, a) +
                         f"\n   <code>/sil_{sym.replace('.IS','')}</code>")
        msg = "⭐ <b>İzleme Listesi</b>\n\n" + "\n".join(lines)
        msg += "\n\n<i>Silme için hisse yanındaki komuta dokunun. Ekleme için bir kod yazın.</i>"
        context.user_data["awaiting_watchlist"] = True
        update.message.reply_text(msg, parse_mode="HTML")

    def cmd_sil(update, context):
        # /sil_THYAO -> hisseyi kullanicinin listesinden cikar
        text = (update.message.text or "").strip()
        tok = text.split()
        if not tok:
            return
        raw = tok[0].replace("/sil_", "").strip()
        if not raw:
            return
        sym = raw.upper()
        if not sym.endswith(".IS"):
            sym += ".IS"
        ok = remove_from_watchlist(update.effective_chat.id, sym)
        if ok:
            update.message.reply_text(f"🗑 <b>İzleme listesinden çıkarıldı:</b> <code>{sym}</code>",
                                      parse_mode="HTML")
        else:
            update.message.reply_text(f"<code>{sym}</code> izleme listenizde bulunamadı.",
                                      parse_mode="HTML")

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
    dp.add_handler(CommandHandler("gunceltop5", cmd_gunceltop5))
    dp.add_handler(CommandHandler("sorgu", cmd_sorgu))
    dp.add_handler(CommandHandler("watchlist", cmd_watchlist))
    dp.add_handler(CommandHandler("portfoy", cmd_portfoy))
    dp.add_handler(CommandHandler("ototarma", cmd_ototarma))
    dp.add_handler(CommandHandler("sil", cmd_sil))
    dp.add_handler(MessageHandler(Filters.regex(r"^/sil_[A-Za-z0-9]+"), cmd_sil))

    # --- ReplyKeyboard buton metinlerini ilgili komuta yönlendir ---
    def handle_button(update, context):
        text = (update.message.text or "").strip()
        btn_map = {
            "🎯 Top 5 Hisse": cmd_top5,
            "⭐ İzleme Listem": cmd_watchlist,
            "💰 Portföy Planı": cmd_portfoy,
            "⚙️ Otomatik Tarama": cmd_ototarma,
            "ℹ️ Bilgi & Yardım": cmd_bilgi,
        }
        fn = btn_map.get(text)
        if fn:
            # Bekleyen etkileşimli durumları, farklı bir butona geçilince sıfırla
            if fn is not cmd_sorgu:
                context.user_data.pop("awaiting_sorgu", None)
            if fn is not cmd_watchlist:
                context.user_data.pop("awaiting_watchlist", None)
            fn(update, context)
            return
        # Buton metni değil: beklenen sorgu/izleme girdisi olabilir
        if context.user_data.get("awaiting_sorgu"):
            context.user_data["awaiting_sorgu"] = False
            run_sorgu(update, context, text)
            return
        if context.user_data.get("awaiting_watchlist"):
            context.user_data["awaiting_watchlist"] = False
            parsed = parse_watchlist_input(text)
            if parsed:
                sym, cost = parsed
                add_to_watchlist(update.effective_chat.id, sym, cost)
                update.message.reply_text(
                    f"⭐ <b>İzleme listesine eklendi:</b> <code>{sym}</code>"
                    + (f" ({cost:,.2f} ₺ maliyet)" if cost else ""),
                    parse_mode="HTML")
            else:
                update.message.reply_text("Geçersiz girdi. Örn: <code>THYAO</code> veya <code>THYAO 285.50</code>",
                                          parse_mode="HTML")
            return
        # tanınmayan text -> sessizce yok say (bildirim verme)
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_button))
    dp.add_handler(MessageHandler(Filters.command, lambda u, c: None))

    # --- Telegram / menüsü: komut + açıklama kaydı (set_my_commands) ------
    try:
        BOT.set_my_commands([
            ("top5", "En iyi 5 momentum hissesi (anında önbellek)"),
            ("gunceltop5", "Arka planda taze Top 5 taraması başlat"),
            ("sorgu", "Tek hisse analizi (ör: /sorgu GOZDE)"),
            ("watchlist", "⭐ İzleme listem (ekle/sil/her seans sinyal)"),
            ("portfoy", "100.000 TL portföy planı"),
            ("ototarma", "Otomatik taramayı aç/kapat"),
            ("bilgi", "Kullanım kılavuzu ve strateji"),
        ])
        print("[i] Telegram komut menüsü set_my_commands ile güncellendi.")
    except Exception as e:  # pragma: no cover
        print(f"[!] set_my_commands başarısız: {e}")

    # --- TradeKing V6: seans sinyal taramasi + 18:15 kapanis raporu ---
    def send_watchlist_signal(cid, sym, sig):
        """V6 sinyalini Telegram mesajına çevirir + kural bazlı gerekçe."""
        code = sym.replace(".IS", "")
        kind = sig["kind"]
        if kind == "AL":
            title = "🟢 AL / PULLBACK BUY"
        elif kind == "STOP":
            title = "⚠️ STOP"
        else:
            title = "🎯 KAR AL"
        msg = (
            f"<b>{title} — {code}</b>\n"
            f"Fiyat: <code>{sig['price']:,.2f} ₺</code>\n"
            f"RSI(14): <b>{sig['rsi']:.1f}</b> | Trend: {sig['trend']}\n"
            f"ATR(14): <code>{sig['atr']:.2f}</code>\n"
            f"İzleme Maliyeti: "
            + (f"<code>{sig['cost']:,.2f} ₺</code>" if sig.get("cost") else "<i>yok</i>")
            + f"\n💡 <b>Sinyal Gerekçesi:</b> {sig['reason']} "
              f"(RSI: {sig['rsi']:.1f}, ATR Stop: {sig['atr_stop']:.2f} TL)."
        )
        try:
            BOT.send_message(chat_id=int(cid), text=msg, parse_mode="HTML")
        except Exception:
            pass

    def watchlist_signal_job():
        """Hafta içi 10:00-18:15 arası her 30dk: tüm watchlist'leri tara + sinyal gönder."""
        alerts = {}
        try:
            alerts = check_watchlist_signals()
        except Exception as e:
            print(f"[!] V6 sinyal taraması hatası: {e}")
            return
        for cid, sigs in alerts.items():
            for sym, sig in sigs:
                send_watchlist_signal(cid, sym, sig)

    def close_report_job():
        """Hafta içi 18:15: seans kapanış özeti (takip edilen hisselerin günlük kapanışı)."""
        data = _load_watchlists()
        for cid, holdings in data.items():
            lines = []
            for sym, rec in holdings.items():
                a = _watchlist_price(sym)
                lines.append(fmt_watchlist_price(rec, a))
            if not lines:
                continue
            msg = "📊 <b>Seans Kapanış Raporu</b>\n\n" + "\n".join(lines)
            try:
                BOT.send_message(chat_id=int(cid), text=msg, parse_mode="HTML")
            except Exception:
                pass

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
    msg += f"\n📊 <b>Kaynak:</b> {top[0].get('data_source', 'Yahoo Finance')}"
    for chat_id in list(AUTO_SUBSCRIBERS):
        if not AUTO_SUBSCRIBERS.get(chat_id):
            continue
        try:
            BOT.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
        except Exception:
            pass

    # --- Borsa kapanış/açılış ön taraması (diske taze cache yazar) --------
    def precache_job():
        # Sunucu yükü sıfır: sabah 09:45 ve akşam 18:30'da BİST kapanışı sonrası
        # otomatik tarama -> scan_cache.json diske yazılır. Gün içi /top5 ve
        # /api/scan bu diske 0 ms'de 200 döner (yeniden indirme yok).
        global _SCAN_CACHE_TS
        _SCAN_CACHE_TS = 0.0  # önbelleği bayatlat -> taze indirme + diske yaz
        try:
            scan_top_5_stocks()
        except Exception as e:  # pragma: no cover
            print(f"[!] Ön tarama hatası: {e}")

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        # APScheduler 3.x yalnızca pytz timezone objelerini kabul eder
        # (strings desteklenmez) -> Europe/Istanbul açıkça pytz ile verilir.
        SCHEDULER = BackgroundScheduler(timezone=pytz.timezone("Europe/Istanbul"))
        SCHEDULER.add_job(auto_scan_job, "interval", minutes=AUTO_SCAN_INTERVAL_MIN)
        # Hafta içi 09:45 (açılış öncesi) ve 18:30 (kapanış sonrası) ön-tarama.
        SCHEDULER.add_job(precache_job, "cron", day_of_week="mon-fri",
                          hour=9, minute=45, timezone=pytz.timezone("Europe/Istanbul"))
        SCHEDULER.add_job(precache_job, "cron", day_of_week="mon-fri",
                          hour=18, minute=30, timezone=pytz.timezone("Europe/Istanbul"))
        # V6 seans sinyalleri: hafta içi 10:00-18:15 her 30dk
        SCHEDULER.add_job(watchlist_signal_job, "cron", day_of_week="mon-fri",
                          hour="10-18", minute="0,30", timezone=pytz.timezone("Europe/Istanbul"))
        # V6 seans sonu raporu: hafta içi 18:15
        SCHEDULER.add_job(close_report_job, "cron", day_of_week="mon-fri",
                          hour=18, minute=15, timezone=pytz.timezone("Europe/Istanbul"))
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