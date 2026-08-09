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


if __name__ == "__main__":
    unittest.main()