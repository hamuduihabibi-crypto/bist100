# 🎯 BIST Trading Bot — Borsa İstanbul Otomatik Teknik Analiz & Momentum Tarayıcı

**100.000 TL'lik 3 haftalık trading yarışması (10 – 28 Ağu)** için hazırlanmış,
üretime hazır bir Flask web servisi + Telegram botu. `yfinance`, `pandas`,
`pandas-ta` ile RSI/MACD/EMA/pivot analizi ve Top 5 momentum taraması yapar.

---

## ✨ Özellikler

| Alan | Detay |
|------|-------|
| **Tek hisse analizi** | RSI(14), MACD(12,26,9), EMA20/50 trend, 20G destek/direnç, Klasik Pivot (P, R1–R3, S1–S3), hacim surge % |
| **Top 5 tarama** | Hacim surge + trend + RSI(55–72) + direnç yakınlığı skorlama, +%6 hedef / −%3 stop, R/R oranı |
| **Telegram botu** | `/start` `/bilgi` `/top5` `/sorgu KOD` `/portfoy` `/ototarma` |
| **Flask API** | `GET /` , `GET /api/scan` , `GET /api/stock/<symbol>` |
| **Otomatik uyarı** | APScheduler ile periyodik Top 5 taraması (`/ototarma ac|kapat`) |

---

## 🚀 Yerel Çalıştırma

> **Önemli (bazı Windows/Hermes ortamları):** Miras alınan `PYTHONPATH` doğru
> numpy'ü gölgeleyebilir (`env -u PYTHONPATH` ile temizleyin).

```bash
# 1) Bağımlılıklar (pandas-ta Python>=3.12 ister)
uv python install 3.12
uv venv --python 3.12 .venv312
uv pip install --python .venv312/Scripts/python.exe -r requirements.txt

# 2) Telegram token'ı (isterseniz)
cp .env.example .env   # TELEGRAM_BOT_TOKEN'ı doldurun

# 3) Çalıştır
env -u PYTHONPATH .venv312/Scripts/python.exe main.py
```

Token tanımlanmamışsa bot atlanır; yalnızca Flask sunucusu:
```
http://localhost:5000/
http://localhost:5000/api/scan
http://localhost:5000/api/stock/GOZDE.IS
```

---

## 🤖 Telegram Komutları

| Komut | Açıklama |
|-------|----------|
| `/start` | Karşılama, hızlı kılavuz ve buton bağlantıları |
| `/bilgi` | Tüm komutlar + 3 haftalık yarışma stratejisi |
| `/top5` | Skorlanmış ilk 5 momentum hissesi (fiyat, skor, RSI, MACD, EMA trend, hedef/stop) |
| `/sorgu KOD` | Hisse raporu: pivot seviyeleri dahil tam analiz (`/sorgu GOZDE`) |
| `/portfoy` | 100.000 TL → 4 eşit pozisyon (25.000 TL) + risk bütçesi (−750 TL/hisse) |
| `/ototarma ac\|kapat` | Periyodik otomatik tarama uyarılarını aç/kapat (30 dk) |

---

## ☁️ Buluta Dağıtım (Render / Heroku / VPS)

### Render (en kolay)
1. Repo'yu Render'a bağlayın → **New Web Service**.
2. **Start Command**:
   ```bash
   gunicorn main:app --timeout 120 --workers 1
   ```
3. Ortam değişkenlerini **Environment**'a ekleyin: `TELEGRAM_BOT_TOKEN`.
   Port'u Render otomatik `PORT` ile verir.
   > Bot "long polling" kullandığı için Web Servis olarak ayakta kalmalıdır
   > (sleep eden free tier'da zamanlayıcı/uyarılar çalışmaz).

### Heroku
```bash
heroku create
heroku config:set TELEGRAM_BOT_TOKEN=XXXX
echo "web: gunicorn main:app --timeout 120 --workers 1" > Procfile
git push heroku main
```

### VPS (systemd)
```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=XXXX
gunicorn main:app --timeout 120 --workers 1 --bind 0.0.0.0:5000
```
Arka planda kalması için `systemd` birimi ekleyin.

---

## 📁 Proje Yapısı

```
bist_telegram_bot/
├── main.py              # Analiz motoru + skorlama + Flask + Telegram bot + scheduler
├── requirements.txt     # Kilitlenmiş bağımlılıklar
├── .env.example         # Ortam değişkeni şablonu
└── README.md            # Bu doküman
```

---

## ⚙️ Yapılandırılabilir Parametreler (`main.py` üst kısmı)

- `CAPITAL = 100_000` — toplam sermaye
- `NUM_POSITIONS = 4` — eşit pozisyon sayısı
- `TARGET_PCT = 0.06` / `STOP_PCT = 0.03` — hedef/stop (R/R ≈ 2:1)
- `RSI_MIN, RSI_MAX = 55, 72` — momentum RSI bandı
- `AUTO_SCAN_INTERVAL_MIN = 30` — ototarma sıklığı
- `BIST_TICKERS` — tarama listesi (BIST 100'e genişletin)

---

## 🧪 Doğrulama

```bash
python -m py_compile main.py
env -u PYTHONPATH .venv312/Scripts/python.exe -c "from main import analyze_single_stock; print(analyze_single_stock('GOZDE.IS'))"
```

> **Yasal uyarı:** Araç eğitim/yarışma amaçlı bilgi sunar; yatırım tavsiyesi değildir.