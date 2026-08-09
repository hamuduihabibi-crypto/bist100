# 🎯 BIST Trading Bot — Borsa İstanbul (BIST Tüm) Teknik Analiz & Momentum Tarayıcı

**Flask Web API + Telegram Bot** uygulaması; **Borsa İstanbul (BIST Tüm)** piyasası için
geliştirilmiştir. 100.000 TL'lik 3 haftalık trading yarışması (10 – 28 Ağu 2026) için
üretime hazır bir tarama, analiz, bildirim ve portföy risk planlama aracıdır.

`yfinance` veri kaynağı + `pandas` / `pandas-ta` ile **RSI, MACD, EMA trend, 20 günlük
destek/direnç, Klasik Pivot seviyeleri ve Hacim Surge** analizi yapar; momentum
kriterlerini karşılayan hisseleri skorlayıp **Top 5** listesini hem web API hem Telegram
üzerinden sunar.

---

## ✨ Öne Çıkan Özellikler

| Alan | Detay |
|------|-------|
| **BIST Tüm Evreni** | BIST 30/100 ile sınırlı kalmayıp **~384+ seed hisse** (`main.py` → `BIST_TICKERS_SEED`) içeren geniş bir evreni tarar. En güncel tam liste için `BIST_TICKERS_FILE` ortam değişkeniyle bir metin dosyası da belirtilebilir (bir satır bir kod). |
| **Dinamik Sorgu (`/sorgu`)** | Borsa İstanbul'da işlem gören **herhangi bir** hisse kodu canlı analiz edilir — kodun seed evreninde olması gerekmez (`/sorgu GOZDE`). |
| **Performans Optimizasyonu** | `yf.download(BIST_TICKERS, ..., group_by="ticker")` ile **tek paket (batch) indirme** + `concurrent.futures.ThreadPoolExecutor` ile **paralel** gösterge hesabı. 500'e yakın hisse, 120 sn'lik Render/Gunicorn timeout'una takılmadan saniyeler içinde taranır. |
| **Teknik Göstergeler** | RSI(14) momentum bandı (55–72), MACD(12,26,9) sinyalleri, EMA20/50 trendi, 20 günlük destek/direnç, Klasik Pivot seviyeleri (P, R1–R3, S1–S3) ve Hacim Surge %. |
| **Portföy & Risk Stratejisi** | 100.000 TL sermaye, **4 eşit pozisyon** (25.000 TL/hisse), **+%6 hedef** ve **−%3 sert stop-loss** planı (R/R ≈ 2:1). |
| **Otomatik Tarama & Zamanlayıcı** | `APScheduler` + `pytz.timezone("Europe/Istanbul")` ile periyodik Top 5 taraması ve bildirim (`/ototarma ac\|kapat`, varsayılan 30 dk). |
| **Flask Web API** | Sağlık kontrolü ve JSON analiz endpoint'leri (HTTPS üzerinden bot'a entegre). |

---

## 🏗️ Mimari Genel Bakış

```
                        ┌──────────────────────────────────────────────┐
                        │              yfinance (Yahoo .IS)             │
                        └───────────────────────┬──────────────────────┘
                                                │  batch yf.download(...) group_by="ticker"
                                                ▼
        ┌──────────────────────────────────────────────────────────────────┐
        │   main.py  —  Analiz Motoru                                      │
        │   • get_bist_tickers() : BIST Tüm seed / BIST_TICKERS_FILE       │
        │   • download_batch()   : TEK çağrıda ~384+ hissenin OHLCV'si     │
        │   • _compute_analysis(): RSI · MACD · EMA20/50 · pivotlar · surge │
        │   • score_stock()      : momentum puanı (0–100+)                 │
        │   • scan_top_5_stocks(): ThreadPoolExecutor (8) paralel hesap     │
        └──────────────┬───────────────────────────────────────────────────┘
                       │
          ┌────────────┴─────────────┬───────────────────────────────┐
          ▼                          ▼                               ▼
 ┌─────────────────┐      ┌──────────────────────┐        ┌───────────────────┐
 │   Flask /api    │      │  Telegram Bot (PTB)  │        │  APScheduler      │
 │  /  /api/scan   │      │  /start /top5 /sorgu │        │  + pytz Istanbul  │
 │  /api/stock/<s> │      │  /portfoy /ototarma  │        │  ototarma bildir. │
 └─────────────────┘      └──────────────────────┘        └───────────────────┘
                Dış tetik: cron-job.org → GET / (10 dk)  → Render uyutmaz
```

**Önemli başlatma davranışı:** Gunicorn `main:app` ile modülü **import** ettiğinde
(ör. `python -m main` değil!) `if __name__ == "__main__"` çalışmaz. Bu nedenle bot
thread'i **modül seviyesinde**, `TELEGRAM_BOT_TOKEN` varsa otomatik başlar; yoksa
yalnızca "web-only" modda Flask sunucusu koşar. `_BOT_STARTED` bayrağı bot'un yalnızca
**bir kez** başlamasını garantiler.

---

## 🤖 Telegram Bot Komutları

Örnek bot: **[@abi447734_bot](https://t.me/abi447734_bot)**

| Komut | Açıklama | Örnek |
|-------|----------|-------|
| `/start` | Karşılama mesajı, hızlı kılavuz ve buton bağlantıları | `/start` |
| `/bilgi` | Tüm komutlar + 3 haftalık yarışma stratejisi | `/bilgi` |
| `/top5` | Skorlanmış ilk 5 momentum hissesi (fiyat, skor, RSI, MACD, EMA trend, hedef/stop) | `/top5` |
| `/sorgu <KOD>` | **Herhangi bir** BIST hissesinin tam teknik + pivot raporu | `/sorgu GOZDE` |
| `/portfoy` | 100.000 TL → 4 eşit pozisyon (25.000 TL) + risk bütçesi (−750 TL/hisse) | `/portfoy` |
| `/ototarma ac\|kapat` | Periyodik otomatik tarama bildirimlerini aç/kapat (varsayılan 30 dk) | `/ototarma ac` |

---

## 🔌 Flask Web API Endpoint'leri

| Method | Yol | Açıklama |
|--------|-----|----------|
| `GET` | `/` | **Sağlık kontrolü** → `{"status": "online"}` (Render health check ve keep-alive ping'i). |
| `GET` | `/api/scan` | **Top 5 momentum listesi** (JSON). Batch indirme + paralel hesap; `score`, `target`, `stop`, `rr` vb. alanlar içerir. |
| `GET` | `/api/stock/<symbol>` | **Tekil hisse ve pivot analizi** (JSON). Herhangi bir `.IS` sembolü: `EMA20/50`, `RSI`, `MACD`, `support20/resistance20`, `pivots.P–R3/S1–S3`, hedef/stop. |

Örnekler:
```bash
curl http://localhost:5000/
curl http://localhost:5000/api/scan
curl http://localhost:5000/api/stock/THYAO.IS
```

---

## ☁️ Render.com Deployment & Konfigürasyon

Proje, repo kökündeki **`render.yaml`** Blueprint dosyasıyla Render'a deploy edilir
(New → **Blueprint**, repoyu seçin). Manuel kurulumda:<br>
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:**
  ```bash
  gunicorn main:app --timeout 120 --workers 1
  ```
  > ⚠️ **`--workers 1` ZORUNLUDUR.** Her Gunicorn worker, modül-seviyesi bot
  > thread'ini kendi process'inde ayrı ayrı başlatır → birden çok `getUpdates` long-poll
  > aynı anda çalışınca Telegram **"Conflict: terminated by other getUpdates"** hatası
  > üretir. Tek worker bunu önler.

### Ortam Değişkenleri (Render "Environment" paneli)

| Değişken | Değer | Zorunlu | Açıklama |
|----------|-------|:------:|----------|
| `TELEGRAM_BOT_TOKEN` | (BotFather token'ı) | ✅ | Boşsa bot başlamaz, yalnızca web. Render'da **gizli** girilir (`sync: false` — repoya asla yazılmaz). |
| `PYTHON_VERSION` | `3.12.8` | ✅ | pand-ta yalnızca Python ≥ 3.12'de çalışır; Render'da python runtime'ı buna sabitle. |
| `PORT` | `10000` | ⚠️ | Render otomatik atar; el ile set edilebilir. |
| `HOST` | `0.0.0.0` | ⚠️ | Gunicorn'un dinleyeceği adres. |
| `FLASK_DEBUG` | `0` | ✖️ | Production'da kapalı. |
| `BIST_TICKERS_FILE` | (opsiyonel dizin) | ✖️ | Göreceli olarak BIST Tüm tam listeyi içeren dosya; seed yerine geçer. |

> Render free tier'ı, işlem gelmeyince ~15 dk sonra örnekleri askıya alır. Bot "long
> polling" kullandığından **Web Service ayakta kaldığı sürece** `ototarma` zamanlayıcısı
> ve uyarılar çalışır; uyursa uyarılar durur → aşağıdaki keep-alive önerilir.

### Uyanık Tutma (Keep-Alive)
Render'ın free tier'da uykuya dalmasını engellemek için **cron-job.org** üzerinden
**her 10 dakikada bir** sağlık kontrolüne HTTP GET ping atılır:
- cron-job.org'da **Yeni Cron Job** → *URL*: `https://bist-telegram-bot.onrender.com/`
- *Schedule*: `*/10 * * * *` (her 10 dk)
- *Network/HTTP*: GET, bekle. Kaydedip aktifleştirin.

Bu ping, `/` endpoint'ini çağırır; web servis uyumadan ayakta kalır ve bot polling'i sürekli yaşar.

---

## 💻 Yerel Kurulum & Çalıştırma (Local Setup)

> **Windows/Hermes notu:** Miras alınan `PYTHONPATH` doğru numpy'ü gölgeleyebilir;
> çalıştırmalarda `env -u PYTHONPATH` ile temizleyin.

```bash
# 0) Repoya girin
cd bist_telegram_bot

# 1) Bağımlılıklar (pandas-ta Python>=3.12 ister)
uv python install 3.12
uv venv --python 3.12 .venv312
uv pip install --python .venv312/Scripts/python.exe -r requirements.txt

# 2) Telegram token'ı (isterseniz)
cp .env.example .env   # TELEGRAM_BOT_TOKEN'ı doldurun

# 3) Çalıştır
env -u PYTHONPATH .venv312/Scripts/python.exe main.py
```

Token tanımlanmamışsa bot aşağı geçer; yalnızca Flask sunucusu:
```
http://localhost:5000/
http://localhost:5000/api/scan
http://localhost:5000/api/stock/GOZDE.IS
```

> ⚠️ **Telegram Conflict uyarısı:** Render'daki bot **canlıyken yerelde `main.py`**
> çalıştırmayın — iki örnek aynı token ile `getUpdates` yarışıp Telegram "Conflict"
> üretir. Yerel testler için `TELEGRAM_BOT_TOKEN=` boş bırakın (web-only) veya ayrı bir
> test token'ı kullanın.

---

## 🧪 Test Süiti

Birim testler `tests/test_bot_start.py` içindedir (stdlib `unittest`) ve şunları doğrular:
`main.py` derlenmesi, `render.yaml`'ın tek-worker sözleşmesi, bot'un Gunicorn import'unda
modül seviyesinde başlaması, web-only yolu, BIST Tüm evreni (`.IS`/benzersiz/≥300),
batch (toplu) taramanın gerçek eşleşmeleri ve APScheduler'ın `pytz` zaman dilimini
kabul etmesi.

```bash
cd bist_telegram_bot
env -u PYTHONPATH .venv312/Scripts/python.exe -m unittest tests.test_bot_start -v
```

Beklenen çıktı: `Ran 7 tests ... OK`, çıkış kodu `0`.

---

## 📁 Proje Yapısı

```
bist_telegram_bot/
├── main.py              # Analiz motoru + skorlama + Flask + Telegram bot + APScheduler(pytz)
├── requirements.txt     # Kilitlenmiş bağımlılıklar (urllib3<2, APScheduler==3.6.3, setuptools<81, pytz ...)
├── render.yaml          # Render Blueprint (gunicorn --workers 1, TELEGRAM_BOT_TOKEN sync:false)
├── .env.example         # Ortam değişkeni şablonu (şimdi .env => gitignore'da)
├── .gitignore           # .env, .venv312/, __pycache__ vb.
├── README.md            # Bu doküman
└── tests/
    ├── __init__.py
    └── test_bot_start.py  # Kanonik unittest (7 test)
```

---

## ⚙️ Yapılandırılabilir Parametreler (`main.py` üst kısmı)

| Parametre | Varsayılan | Açıklama |
|-----------|-----------|----------|
| `CAPITAL` | `100_000` | Toplam yarışma sermayesi (TL). |
| `NUM_POSITIONS` | `4` | Eşit pozisyon sayısı. |
| `TARGET_PCT` / `STOP_PCT` | `0.06` / `0.03` | Hedef / sert stop (R/R ≈ 2:1). |
| `RSI_MIN`, `RSI_MAX` | `55` / `72` | Momentum RSI bandı. |
| `AUTO_SCAN_INTERVAL_MIN` | `30` | `/ototarma` tarama sıklığı (dk). |
| `BIST_TICKERS_SEED` | ~384 kod | BIST Tüm seed evreni (`get_bist_tickers()`). |
| `BIST_TICKERS_FILE` | (env) | Seed yerine geçen tam liste dosyası. |

---

## 🧾 Yasal Uyarı

Bu araç yalnızca **eğitim / yarışma** amaçlı bilgi üretir; **yatırım tavsiyesi değildir.**
Teknik göstergeler ve sinyaller kâr garantisi sağlamaz.