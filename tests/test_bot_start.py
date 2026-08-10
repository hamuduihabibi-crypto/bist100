"""Canonical focused tests for bist_telegram_bot — gunicorn module-import fix.

Verifies that the Telegram bot thread starts at MODULE IMPORT time (what
`gunicorn main:app` does) and that render.yaml runs a single worker, so exactly
one bot polls (no Telegram "Conflict" from multiple workers).

Run (Hermes host, PYTHONPATH must be cleared for the 3.12 venv):
  env -u PYTHONPATH .venv312/Scripts/python.exe -m unittest tests.test_bot_start -v
"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestGunicornBotStart(unittest.TestCase):
    def setUp(self):
        # Disk cache'i her test için izole et (gerçek scan_cache.json repoya
        # yazılmasın; subprocess env'e temiz yol verilsin).
        import tempfile as _tf
        fd, p = _tf.mkstemp(prefix="scan_cache_", suffix=".json")
        os.close(fd)
        self._cache_file = p
        os.environ["SCAN_CACHE_FILE"] = p
        # watchlists.json de izole (V6 testleri repoyu kirletmesin)
        fd2, p2 = _tf.mkstemp(prefix="watchlists_", suffix=".json")
        os.close(fd2)
        self._wl_file = p2
        os.environ["WATCHLIST_FILE"] = p2

    def tearDown(self):
        try:
            os.remove(self._cache_file)
        except OSError:
            pass
        try:
            os.remove(self._wl_file)
        except OSError:
            pass

    def test_main_compiles(self):
        import py_compile
        py_compile.compile(os.path.join(ROOT, "main.py"), doraise=True)

    def test_render_runs_single_worker(self):
        with open(os.path.join(ROOT, "render.yaml"), encoding="utf-8") as f:
            txt = f.read()
        self.assertIn("gunicorn main:app --timeout 120 --workers 1", txt,
                      "cok worker = cok polling = Telegram Conflict")

    def _run(self, setup, tail):
        """Import main in a subprocess with a controlled TELEGRAM_BOT_TOKEN."""
        code = (
            "import os,sys,threading\nROOT=%r\n" % ROOT
            + "import os;%s;sys.path.insert(0,ROOT);import main as m;%s"
            % (setup, tail)
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)  # cp311-numpy golgelenmesini engelle
        return subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True
        )

    def test_web_only_when_no_token(self):
        p = self._run(
            "os.environ['TELEGRAM_BOT_TOKEN']=''",
            "print('started=%s' % m._BOT_STARTED)",
        )
        self.assertIn("missing. Running in web-only mode", p.stdout)
        self.assertNotIn("started in background", p.stdout)
        self.assertIn("started=False", p.stdout)

    def test_bot_thread_starts_at_module_import(self):
        p = self._run(
            "os.environ['TELEGRAM_BOT_TOKEN']='FAKE_123'",
            "names=[t.name for t in threading.enumerate()];"
            "print('started=%s thread=%s' % (m._BOT_STARTED, 'telegram-bot' in names));"
            "sys.stdout.flush();os._exit(0)",
        )
        self.assertIn("started in background", p.stdout)
        self.assertIn("started=True", p.stdout)
        self.assertIn("thread=True", p.stdout)

    # --- BIST Tüm evreni + toplu (batch) tarama ---------------------------------
    def test_bist_universe(self):
        """Seed evreni: hepsi .IS, benzersiz, en az 250 kod (aktif BIST; delisted
        temizliği sonrası gerçek canlı-veri doğrulamalı evren)."""
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["TELEGRAM_BOT_TOKEN"] = ""  # bot başlatma; Render botuyla çakışma yok
        code = (
            "import os,sys;os.environ['TELEGRAM_BOT_TOKEN']=''\n"
            "sys.path.insert(0,'@ROOT@')\nimport main as m\n"
            "t=m.get_bist_tickers()\n"
            "print('UNIVERSE n=%d is=%s uniq=%s' % (len(t),"
            " all(c.endswith('.IS') for c in t), len(set(t))==len(t)))\n"
        ).replace("@ROOT@", ROOT.replace("\\", "/"))
        p = subprocess.run([sys.executable, "-c", code], env=env,
                           capture_output=True, text=True)
        self.assertIn("n=", p.stdout)
        self.assertIn("is=True uniq=True", p.stdout)
        n = int(p.stdout.split("n=")[1].split()[0])
        self.assertGreaterEqual(n, 250)

    def test_scan_top5_mocked_batch(self):
        """download_batch tek çağrıda 6 hisse döndürür; tarama sıralı gelir."""
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["TELEGRAM_BOT_TOKEN"] = ""
        code = (
            "import os,sys;os.environ['TELEGRAM_BOT_TOKEN']=''\n"
            "sys.path.insert(0,'@ROOT@')\nimport numpy as np, pandas as pd\nimport main as m\n"
            "def frame(s):\n"
            "  rng=np.random.default_rng(s); n=90\n"
            "  close=np.linspace(100.,99.,n)+rng.normal(0,0.35,n)\n"
            "  close[-30:]+=np.linspace(0.,2.5,30); close[-1]+=0.8\n"
            "  hi=close*(1+np.abs(rng.normal(0,0.0025,n)))\n"
            "  lo=close*(1-np.abs(rng.normal(0,0.0025,n)))\n"
            "  vol=np.array(rng.integers(1_000_000,3_000_000,n),dtype=float)\n"
            "  vol[-1]=vol[-10:-1].mean()*2.5\n"
            "  idx=pd.date_range(end=pd.Timestamp.today(), periods=n)\n"
            "  return pd.DataFrame({'Open':close,'High':hi,'Low':lo,'Close':close,'Volume':vol}, index=idx)\n"
            "syms=m.get_bist_tickers()[:6]\n"
            "m.download_batch=lambda s,**k: pd.concat({sym:frame(i) for i,sym in enumerate(syms)},axis=1)\n"
            "top=m.scan_top_5_stocks(5)\n"
            "sc=[t['score'] for t in top]\n"
            "print('SCAN n=%d sorted=%s fields=%s' % (len(top),"
            " sc==sorted(sc,reverse=True), all(all(k in t for k in ('score','target','stop','symbol')) for t in top)))\n"
            "print('RESULT_SYMS:', [t['symbol'] for t in top])\n"
        ).replace("@ROOT@", ROOT.replace("\\", "/"))
        p = subprocess.run([sys.executable, "-c", code], env=env,
                           capture_output=True, text=True)
        self.assertIn("SCAN n=", p.stdout)
        self.assertIn("sorted=True fields=True", p.stdout)
        n = int(p.stdout.split("SCAN n=")[1].split()[0])
        self.assertEqual(n, 5)  # 6 geçerli seed kodundan gerçek en-iyi-5 çekildi

    def test_scan_top5_in_memory_cache(self):
        """Tarama sonucu 1 saat TTL'li cache'lenir; 2. çağrı indirme YAPMAZ."""
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["TELEGRAM_BOT_TOKEN"] = ""
        code = (
            "import os,sys;os.environ['TELEGRAM_BOT_TOKEN']=''\n"
            "sys.path.insert(0,'@ROOT@')\nimport numpy as np,pandas as pd\nimport main as m\n"
            "def frame(s):\n"
            "  rng=np.random.default_rng(s); n=90\n"
            "  c=np.linspace(100.,99.,n)+rng.normal(0,0.35,n); c[-1]+=0.8\n"
            "  hi=c*1.002; lo=c*0.998\n"
            "  v=np.array(rng.integers(1_000_000,3_000_000,n),dtype=float); v[-1]=v[-10:-1].mean()*2.0\n"
            "  idx=pd.date_range(end=pd.Timestamp.today(), periods=n)\n"
            "  return pd.DataFrame({'Open':c,'High':hi,'Low':lo,'Close':c,'Volume':v}, index=idx)\n"
            "syms=m.get_bist_tickers()[:6]\n"
            "hits=[0]\n"
            "def dl(s,**k):\n"
            "  hits[0]+=1; return pd.concat({sym:frame(i) for i,sym in enumerate(syms)},axis=1)\n"
            "m.download_batch=dl\n"
            "r1=m.scan_top_5_stocks(5); r2=m.scan_top_5_stocks(5)\n"
            "same=[x['symbol'] for x in r1]==[x['symbol'] for x in r2]\n"
            "print('CACHE first=%d second=%d downloads=%d same=%s' % (len(r1),len(r2),hits[0],same))\n"
            "m._SCAN_CACHE_TS=0; m.scan_top_5_stocks(5)\n"
            "print('CACHE2 after_expiry_downloads=%d' % hits[0])\n"
        ).replace("@ROOT@", ROOT.replace("\\", "/"))
        p = subprocess.run([sys.executable, "-c", code], env=env,
                           capture_output=True, text=True)
        blob = p.stdout + p.stderr
        self.assertIn("CACHE first=5 second=5 downloads=1 same=True", blob)
        self.assertIn("CACHE2 after_expiry_downloads=2", blob)  # TTL dolunca yeniden indirir

    def test_scan_concurrent_lock_and_error_fallback(self):
        """Eşzamanlı tarama yalnızca 1 download üretir (lock) ve download
        hatasında bayat cache'e düşer (worker çökmez)."""
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["TELEGRAM_BOT_TOKEN"] = ""
        code = (
            "import os,sys,time,threading\n"
            "sys.path.insert(0,'@R@')\n"
            "import numpy as np,pandas as pd\n"
            "import main as m\n"
            "def fr(s):\n"
            "  rng=np.random.default_rng(s); n=90\n"
            "  c=np.linspace(100.,99.,n)+rng.normal(0,0.35,n); c[-1]+=1.0\n"
            "  hi=c*1.002; lo=c*0.998\n"
            "  v=np.array(rng.integers(1_000_000,3_000_000,n),dtype=float); v[-1]=v[-10:-1].mean()*2.0\n"
            "  return pd.DataFrame({'Open':c,'High':hi,'Low':lo,'Close':c,'Volume':v}, index=pd.date_range(end=pd.Timestamp.today(),periods=n))\n"
            "syms=m.get_bist_tickers()[:6]\n"
            "cnt=[0]; lk=threading.Lock()\n"
            "def slow_dl(s,**k):\n"
            "  with lk: cnt[0]+=1\n"
            "  time.sleep(0.25)\n"
            "  return pd.concat({sym:fr(i) for i,sym in enumerate(syms)},axis=1)\n"
            "m.download_batch=slow_dl\n"
            "res=[]\n"
            "def w(): res.append(len(m.scan_top_5_stocks(5)))\n"
            "ts=[threading.Thread(target=w) for _ in range(6)]\n"
            "[t.start() for t in ts]; [t.join() for t in ts]\n"
            "print('LOCK downloads=%d all5=%s' % (cnt[0], sorted(res)==[5]*6))\n"
            "def boom(*a,**k): raise RuntimeError('Failed to obtain a crumb')\n"
            "m.download_batch=boom\n"
            "m._SCAN_CACHE=[{'symbol':'THYAO.IS','score':9.9}]; m._SCAN_CACHE_TS=time.time(); m._SCAN_CACHE_TOP_N=5\n"
            "fb=m.scan_top_5_stocks(5)\n"
            "print('ERRFALLBACK stale=%s' % (fb[0]['symbol'] if fb else 'EMPTY'))\n"
        ).replace("@R@", ROOT.replace("\\", "/"))
        p = subprocess.run([sys.executable, "-c", code], env=env,
                           capture_output=True, text=True)
        blob = p.stdout + p.stderr
        self.assertIn("LOCK downloads=1 all5=True", blob)
        self.assertIn("ERRFALLBACK stale=THYAO.IS", blob)

    def test_api_scan_nonblocking_202_then_200(self):
        """Soğuk cache'te /api/scan 202 (arka plan taraması) döner ve bloklamaz;
        tarama bitince aynı endpoint 200 + sonuç verir."""
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["TELEGRAM_BOT_TOKEN"] = ""
        code = (
            "import os,sys,time\n"
            "sys.path.insert(0,'@R@')\n"
            "import numpy as np,pandas as pd\n"
            "import main as m\n"
            "def fr(s):\n"
            "  rng=np.random.default_rng(s); n=90\n"
            "  c=np.linspace(100.,99.,n)+rng.normal(0,0.35,n); c[-1]+=1.0\n"
            "  hi=c*1.002; lo=c*0.998\n"
            "  v=np.array(rng.integers(1_000_000,3_000_000,n),dtype=float); v[-1]=v[-10:-1].mean()*2.0\n"
            "  return pd.DataFrame({'Open':c,'High':hi,'Low':lo,'Close':c,'Volume':v}, index=pd.date_range(end=pd.Timestamp.today(),periods=n))\n"
            "syms=m.get_bist_tickers()[:6]\n"
            "def dl(s,**k): return pd.concat({sym:fr(i) for i,sym in enumerate(syms)},axis=1)\n"
            "m.download_batch=dl\n"
            "m._SCAN_CACHE=None; m._SCAN_CACHE_TS=0.0; m._SCAN_CACHE_TOP_N=None\n"
            "c=m.app.test_client()\n"
            "r=c.get('/api/scan')\n"
            "j=r.get_json(); print('API cold=%d status=%s' % (r.status_code, j.get('status')))\n"
            "t0=time.time()\n"
            "while time.time()-t0 < 15:\n"
            "  r2=c.get('/api/scan')\n"
            "  if r2.status_code==200: break\n"
            "  time.sleep(0.3)\n"
            "j2=r2.get_json()\n"
            "print('API warm=%d count=%s' % (r2.status_code, j2.get('count')))\n"
        ).replace("@R@", ROOT.replace("\\", "/"))
        p = subprocess.run([sys.executable, "-c", code], env=env,
                           capture_output=True, text=True)
        blob = p.stdout + p.stderr
        self.assertIn("API cold=202 status=scanning", blob)
        self.assertIn("API warm=200 count=5", blob)


# --- APScheduler timezone fix (pytz) ---------------------------------------
    def test_disk_cache_roundtrip(self):
        """scan_top_5_stocks başarılı sonucu diske yazar; _load yeniden okur."""
        env = dict(os.environ); env.pop("PYTHONPATH", None); env["TELEGRAM_BOT_TOKEN"] = ""
        env["SCAN_CACHE_FILE"] = self._cache_file
        code = (
            "import os,sys,time\nsys.path.insert(0,'@R@')\n"
            "import numpy as np,pandas as pd\nimport main as m\n"
            "env_file=os.environ['SCAN_CACHE_FILE']  # test temp dosyası\n"
            "def fr(s):\n"
            "  rng=np.random.default_rng(s); n=90\n"
            "  c=np.linspace(100.,99.,n)+rng.normal(0,0.35,n); c[-1]+=1.0\n"
            "  return pd.DataFrame({'Open':c,'High':c,'Low':c,'Close':c,'Volume':np.full(n,1e6)},index=pd.date_range(end=pd.Timestamp.today(),periods=n))\n"
            "syms=m.get_bist_tickers()[:4]\n"
            "m.download_batch=lambda s,**k: pd.concat({sym:fr(i) for i,sym in enumerate(syms)},axis=1)\n"
            "top=m.scan_top_5_stocks(5)\n"
            "on_disk=os.path.exists(env_file) and os.path.getsize(env_file)>5\n"
            "loaded=m._load_scan_cache_disk()\n"
            "ls=[r['symbol'] for r in loaded['results']] if loaded else []\n"
            "ts=[r['symbol'] for r in top]\n"
            "print('DISK written=%s loaded=%s same_syms=%s' % (on_disk, loaded is not None, ls==ts))\n"
        ).replace("@R@", ROOT.replace("\\", "/"))
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertIn("DISK written=True loaded=True same_syms=True", p.stdout + p.stderr)

    def test_get_cached_top5_no_download_when_cold(self):
        """cache boşsa _get_cached_top5 None döner ve download_batch ÇAĞRILMAZ."""
        env = dict(os.environ); env.pop("PYTHONPATH", None); env["TELEGRAM_BOT_TOKEN"] = ""
        env["SCAN_CACHE_FILE"] = self._cache_file
        code = (
            "import os,sys\nsys.path.insert(0,'@R@')\nimport main as m\n"
            "hits=[0]\nm.download_batch=lambda *a,**k: (hits.__setitem__(0,hits[0]+1) or None)\n"
            "m._SCAN_CACHE=None; m._SCAN_CACHE_TS=0.0; m._SCAN_CACHE_TOP_N=None\n"
            "try:\n os.remove(os.environ['SCAN_CACHE_FILE'])\nexcept Exception:\n pass\n"
            "r=m._get_cached_top5()\n"
            "print('COLD result=%s downloads=%d' % (r, hits[0]))\n"
        ).replace("@R@", ROOT.replace("\\", "/"))
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertIn("COLD result=None downloads=0", p.stdout + p.stderr)

    def test_get_cached_top5_reads_disk_without_download(self):
        """Soğuk bellek ama geçerli disk cache varsa _get_cached_top5 indirme yapmadan yükler."""
        env = dict(os.environ); env.pop("PYTHONPATH", None); env["TELEGRAM_BOT_TOKEN"] = ""
        env["SCAN_CACHE_FILE"] = self._cache_file
        code = (
            "import os,sys,json,time\nsys.path.insert(0,'@R@')\nimport main as m\n"
            "f=os.environ['SCAN_CACHE_FILE']\n"
            "disk={'timestamp':'2026-08-10 18:30:00','epoch':time.time()-10,'top_n':5,\n"
            "      'results':[{'symbol':'THYAO.IS','price':300.0,'score':50.0,'data_source':'Yahoo Finance'}]}\n"
            "json.dump(disk,open(f,'w',encoding='utf-8'))\n"
            "hits=[0]\nm.download_batch=lambda *a,**k: (hits.__setitem__(0,hits[0]+1) or None)\n"
            "m._SCAN_CACHE=None; m._SCAN_CACHE_TS=0.0; m._SCAN_CACHE_TOP_N=None\n"
            "r=m._get_cached_top5()\n"
            "print('DISK5 r=%s downloads=%d sym=%s' % (r is not None, hits[0], r[0]['symbol'] if r else 'NONE'))\n"
        ).replace("@R@", ROOT.replace("\\", "/"))
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertIn("DISK5 r=True downloads=0 sym=THYAO.IS", p.stdout + p.stderr)

    def test_scheduler_cron_precache_jobs(self):
        """Kapanış (18:30) ve açılış (09:45) cron ön-tarama işleri tanımlanır."""
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('hour=18, minute=30', src)   # kapanış sonrası
        self.assertIn('hour=9, minute=45', src)     # açılış öncesi
        self.assertIn('def precache_job', src)

    def test_reply_keyboard_buttons_defined(self):
        """/start ve /bilgi kalıcı ReplyKeyboardMarkup butonları + yönlendirme var."""
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('ReplyKeyboardMarkup', src)
        for btn in ("🎯 Top 5 Hisse", "💰 Portföy Planı",
                    "⚙️ Otomatik Tarama", "ℹ️ Bilgi & Yardım"):
            self.assertIn(btn, src)
        self.assertIn('handle_button', src)          # buton -> komut yönlendirme
        self.assertIn('set_my_commands', src)        # / menüsü tanımı

    def test_interactive_sorgu_flow(self):
        """/sorgu parametresiz + 🔍 Hisse Sorgu butonu ForceReply akışı kurar,
        gelen metin awaiting_sorgu durumunda run_sorgu'ya gider."""
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
            src = f.read()
        # parametresiz -> awaiting_sorgu=True + ForceReply
        self.assertIn('context.user_data["awaiting_sorgu"] = True', src)
        self.assertIn('ForceReply(selective=True)', src)
        self.assertIn('🔍 <b>Hisse Analizi</b>', src)
        # parametreli -> doğrudan analiz (if args: -> run_sorgu, return; sonra ForceReply)
        self.assertIn('run_sorgu(update, context, args[0])', src)
        # metin yakalama -> durum sıfırla + run_sorgu
        self.assertIn('context.user_data["awaiting_sorgu"] = False', src)
        self.assertIn('run_sorgu(update, context, text)', src)
        # V6 klavyede 🔍 Hisse Sorgu kaldırıldı (yerine ⭐ İzleme Listem);
        # /sorgu akışı komut üzerinden hâlâ aktiftir (ForceReply).
        self.assertNotIn('"🔍 Hisse Sorgu"', src)

    def test_scheduler_accepts_pytz_timezone(self):
        """Scheduler, pytz timezone objesiyle hata vermeden başlamalı."""
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["TELEGRAM_BOT_TOKEN"] = ""
        code = (
            "import os,sys;os.environ['TELEGRAM_BOT_TOKEN']=''\n"
            "sys.path.insert(0,'@R@')\n"
            "import pytz\n"
            "from apscheduler.schedulers.background import BackgroundScheduler\n"
            "s=BackgroundScheduler(timezone=pytz.timezone('Europe/Istanbul'))\n"
            "s.add_job(lambda:None,'interval',minutes=30)\n"
            "s.start()\n"
            "print('SCHED tz=%s jobs=%d' % (s.timezone, len(s.get_jobs())))\n"
            "s.shutdown(wait=False)\n"
        ).replace("@R@", ROOT.replace("\\", "/"))
        p = subprocess.run([sys.executable, "-c", code], env=env,
                           capture_output=True, text=True)
        blob = p.stdout + p.stderr
        self.assertIn("SCHED tz=Europe/Istanbul jobs=1", blob)
        self.assertNotIn("Only timezones", blob)

    # --- TradeKing V6: watchlist + sinyal motoru davranışları ----------------
    def test_v6_watchlist_persist_roundtrip(self):
        """add/remove/load watchlists.json thread-safe ve atomik çalışır."""
        env = dict(os.environ); env.pop("PYTHONPATH", None)
        env["TELEGRAM_BOT_TOKEN"] = ""
        code = (
            "import os,sys\nsys.path.insert(0,'@R@')\n"
            "os.environ['WATCHLIST_FILE']=@W\n"
            "import main as m\n"
            "m.add_to_watchlist(101,'THYAO.IS',285.50)\n"
            "m.add_to_watchlist(101,'GARAN.IS')\n"
            "m.add_to_watchlist(202,'THYAO.IS')\n"
            "d1=m._load_watchlists()\n"
            "rec=d1['101']['THYAO.IS']\n"
            "sym_ok=rec['symbol']=='THYAO.IS' and rec['cost']==285.50 and rec['state']=='FLAT'\n"
            "sym_in_rec='symbol' in rec\n"
            "m.remove_from_watchlist(101,'GARAN.IS')\n"
            "d2=m._load_watchlists()\n"
            "removed='GARAN.IS' not in d2['101']\n"
            "keep='THYAO.IS' in d2['101'] and 'THYAO.IS' in d2['202']\n"
            "u=m.unique_watchlist_symbols()\n"
            "unique=(u==['THYAO.IS'])  # tekrar yok, silinen yok\n"
            "ok= sym_ok and sym_in_rec and removed and keep and unique\n"
            "print('WLPERSIST cost=%s state=%s sym_in_rec=%s removed=%s keep=%s unique=%s' % \\\n"
            "      (rec['cost'],rec['state'],sym_in_rec,removed,keep,unique))\n"
            "print('RESULT', 'ALL PASS' if ok else 'UNEXPECTED')\n"
            "sys.exit(0 if ok else 1)\n"
        ).replace("@R@", ROOT.replace("\\", "/")).replace("@W", repr(self._wl_file.replace("\\", "/")))
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertIn("RESULT ALL PASS", p.stdout + p.stderr)

    def test_v6_parse_input(self):
        """Akıllı ayrıştırıcı: THYAO / THYAO 285.50 / lot / TL kombinasyonları."""
        env = dict(os.environ); env.pop("PYTHONPATH", None); env["TELEGRAM_BOT_TOKEN"] = ""
        code = (
            "import os,sys\nsys.path.insert(0,'@R@')\nimport main as m\n"
            "a=m.parse_watchlist_input('THYAO')\n"
            "b=m.parse_watchlist_input('THYAO 285.50')\n"
            "c=m.parse_watchlist_input(' thyao 285,50 100 ')\n"
            "d=m.parse_watchlist_input('THYAO 28550TL 100lot')\n"
            "e=m.parse_watchlist_input('THYAO 285.50 28550TL')\n"
            "ok= (a==('THYAO.IS',None,None,None)\n"
            "  and b==('THYAO.IS',285.50,None,None)\n"
            "  and c==('THYAO.IS',285.50,100,28550.0)\n"
            "  and d==('THYAO.IS',285.5,100,28550.0)\n"
            "  and e==('THYAO.IS',285.50,100,28550.0))\n"
            "print('PARSE c=%s d=%s e=%s' % (c,d,e))\n"
            "print('RESULT', 'ALL PASS' if ok else 'UNEXPECTED')\n"
            "sys.exit(0 if ok else 1)\n"
        ).replace("@R@", ROOT.replace("\\", "/"))
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertIn("RESULT ALL PASS", p.stdout + p.stderr)

    def test_v6_lots_total_persist_and_display(self):
        """add_to_watchlist lots/total auto-calc + fmt portföy (yatırım/kâr-zarar)."""
        env = dict(os.environ); env.pop("PYTHONPATH", None); env["TELEGRAM_BOT_TOKEN"] = ""
        code = (
            "import os,sys\nsys.path.insert(0,'@R@')\nimport main as m\n"
            "# 1) persist + otomatik total hesabı\n"
            "m.add_to_watchlist(101,'THYAO.IS',285.50,100)  # cost+lot -> total\n"
            "rec=m._load_watchlists()['101']['THYAO.IS']\n"
            "persist_ok= rec['lots']==100 and rec['total_amount']==28550.0 and rec['cost']==285.50\n"
            "# 2) yalnız total+lot -> maliyet infer\n"
            "m.add_to_watchlist(202,'GARAN.IS',None,100,28550.0)\n"
            "rec2=m._load_watchlists()['202']['GARAN.IS']\n"
            "infer_ok= abs(rec2['cost']-285.50)<1e-6 and rec2['total_amount']==28550.0 and rec2['lots']==100\n"
            "# 3) portföy görünümü: fiyat 300 -> 100 lot, yatırım 28550, net +1450 TL\n"
            "a={'price':300.0,'ema8':295.0,'ema13':293.0,'rsi':52.0,'macd_hist':0.4,\n"
            "   'atr_stop':280.0,'atr_tp':320.0,'trend':'YUKSELEN','atr':9.0}\n"
            "line=m.fmt_watchlist_price(rec, a)\n"
            "disp_ok= ('100 lot' in line and '+1.450,00 TL' in line)  # _tr_num('.') binlik\n"
            "ok= persist_ok and infer_ok and disp_ok\n"
            "print('LOTS persist=%s infer=%s disp=[%s] netline=%s' % (persist_ok,infer_ok,a is not None,\n"
            "       [l for l in line.splitlines() if 'Net' in l]))\n"
            "print('RESULT', 'ALL PASS' if ok else 'UNEXPECTED')\n"
            "sys.exit(0 if ok else 1)\n"
        ).replace("@R@", ROOT.replace("\\", "/"))
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertIn("RESULT ALL PASS", p.stdout + p.stderr)

    def test_v6_signal_and_cooldown(self):
        """AL/STOP/KAR_AL kararları + cooldown state machine deterministik çalışır."""
        env = dict(os.environ); env.pop("PYTHONPATH", None); env["TELEGRAM_BOT_TOKEN"] = ""
        code = (
            "import os,sys\nsys.path.insert(0,'@R@')\nimport main as m\n"
            "# deterministik örnek analiz dict'leri (ağ çağrısı yok)\n"
            "al_a={'price':101.0,'ema8':100.0,'ema13':99.5,'rsi':55.0,'macd_hist':0.5,\n"
            "      'atr_stop':95.0,'atr_tp':109.0,'trend':'YUKSELEN','atr':3.0}\n"
            "stop_a=dict(al_a); stop_a['price']=90.0  # ATR stop(95) altı -> STOP\n"
            "kar_a=dict(al_a); kar_a['price']=112.0   # ATR TP(109) üstü -> KAR_AL\n"
            "no_a=dict(al_a); no_a['trend']='DUSEN'   # trend değil -> sinyal yok\n"
            "k1,_=m._v6_decision(al_a,None)\n"
            "k2,_=m._v6_decision(stop_a, None)\n"
            "k3,_=m._v6_decision(kar_a, None)\n"
            "k4,_=m._v6_decision(no_a, None)\n"
            "# cooldown state machine: AL sonrası COOLDOWN'a girer, sayaç azalır, 0'da FLAT\n"
            "m.add_to_watchlist(101,'TEST.IS')\n"
            "rec=m._load_watchlists()['101']['TEST.IS']\n"
            "rec['state']='COOLDOWN'; rec['cooldown_counter']=3\n"
            "m._persist_rec(rec)\n"
            "post=m._load_watchlists()['101']['TEST.IS']\n"
            "# bir cooldown tiki: counter 3->2\n"
            "post['cooldown_counter']=post['cooldown_counter']-1\n"
            "m._persist_rec(post)\n"
            "after=m._load_watchlists()['101']['TEST.IS']\n"
            "ok= (k1=='AL' and k2=='STOP' and k3=='KAR_AL' and k4 is None\n"
            "     and after['state']=='COOLDOWN' and after['cooldown_counter']==2)\n"
            "print('V6DEC k=(%s,%s,%s,%s) cooldown_state=%s counter=%s' % (k1,k2,k3,k4,after['state'],after['cooldown_counter']))\n"
            "print('RESULT', 'ALL PASS' if ok else 'UNEXPECTED')\n"
            "sys.exit(0 if ok else 1)\n"
        ).replace("@R@", ROOT.replace("\\", "/"))
        p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertIn("RESULT ALL PASS", p.stdout + p.stderr)

    def test_v6_handlers_wired(self):
        """/watchlist + ⭐ İzleme Listem + /sil_ + set_my_commands + scheduler bağlı."""
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('CommandHandler("watchlist", cmd_watchlist)', src)
        self.assertIn('"⭐ İzleme Listem": cmd_watchlist', src)
        self.assertIn('''["🎯 Top 5 Hisse", "⭐ İzleme Listem"]''', src)
        self.assertIn('CommandHandler("sil", cmd_sil)', src)
        self.assertIn('Filters.regex(r"^/sil_[A-Za-z0-9]+")', src)
        self.assertIn('("watchlist", "⭐ İzleme listem (ekle/sil/her seans sinyal)")', src)
        # scheduler: seans 30dk + 18:15 kapanış
        self.assertIn('watchlist_signal_job', src)
        self.assertIn('close_report_job', src)
        self.assertIn('hour="10-18"', src)
        self.assertIn('hour=18, minute=15', src)
        self.assertIn('def check_watchlist_signals', src)
        self.assertIn('V6_COOLDOWN_START = 6', src)


if __name__ == "__main__":
    unittest.main()