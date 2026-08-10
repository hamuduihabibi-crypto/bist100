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
        """Seed evreni: hepsi .IS, benzersiz, en az 300 kod (BIST Tüm'e yakın)."""
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
        self.assertGreaterEqual(n, 300)

    def test_scan_top5_mocked_batch(self):
        """yf.download TEK batch çağrısına karşılık verir; tarama sıralı döner."""
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
            "m.yf.download=lambda s,**k: pd.concat({sym:frame(i) for i,sym in enumerate(syms)},axis=1)\n"
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
        """Tarama sonucu 10 dk TTL'li cache'lenir; 2. çağrı indirme YAPMAZ."""
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
            "m.yf.download=dl\n"
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
            "m.yf.download=slow_dl\n"
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
            "m.yf.download=dl\n"
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


if __name__ == "__main__":
    unittest.main()