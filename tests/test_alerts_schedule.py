from datetime import datetime

import dealfinder.__main__ as main_mod
import dealfinder.alerts as alerts
from dealfinder.analysis import analyse
from tests.helpers import comps
from tests.test_analysis import TODAY, listing


class FakeSMTP:
    sent = []

    def __init__(self, host, port):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.tls = True

    def login(self, user, pw):
        self.user = user

    def send_message(self, msg):
        FakeSMTP.sent.append((self.host, self.port, msg))


def test_deal_alert_email(cfg, monkeypatch):
    for k, v in {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587", "SMTP_USER": "me@example.com",
                 "SMTP_PASSWORD": "pw"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    l = listing(url="https://www.rightmove.co.uk/properties/1")
    a = analyse(l, comps(10, 160000), cfg, rent_pcm=950, today=TODAY)
    assert alerts.send_deal_alert("you@example.com", l, a)
    host, port, msg = FakeSMTP.sent[-1]
    assert (host, port) == ("smtp.example.com", 587) and msg["To"] == "you@example.com"
    assert msg["Subject"].startswith(f"Deal {a.score}/100: 12 Test Street") and "£120,000" in msg["Subject"]
    body = msg.get_content()
    assert "BMV" in body and "rightmove.co.uk/properties/1" in body and "Yield 9.5%" in body


def test_alert_not_sent_without_smtp_settings(cfg, monkeypatch):
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    l = listing()
    assert alerts.send_deal_alert("you@example.com", l, analyse(l, [], cfg, today=TODAY)) is False


def test_alerts_sent_once_per_deal(cfg, monkeypatch):
    from tests.test_pipeline import scanner
    sent = []
    monkeypatch.setattr("dealfinder.alerts.send_deal_alert", lambda to, l, a: sent.append(l.key) or True)
    cfg["alerts"].update(enabled=True, to="you@example.com", min_score=10)
    scanner(cfg, 125000).run()
    scanner(cfg, 120000).run()
    assert sent == ["rightmove:1"]


def test_daily_scan_runs_once_at_the_set_time(cfg, monkeypatch):
    runs, jobs = [], []

    class Sched:
        def add_job(self, fn, *a, **k):
            jobs.append(fn)

        def start(self):
            pass

    class FakeApp:
        class state:
            settings = {"cfg": {**cfg, "schedule": {"daily_at": "07:30"}}}

    class FakeScanner:
        def __init__(self, cfg):
            pass

        def run(self):
            runs.append(1)

    import apscheduler.schedulers.background as bg
    import dealfinder.pipeline as pipeline
    monkeypatch.setattr(bg, "BackgroundScheduler", Sched)
    monkeypatch.setattr(pipeline, "Scanner", FakeScanner)
    clock = {"now": datetime(2026, 11, 10, 7, 29)}

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]
    monkeypatch.setattr(main_mod, "datetime", FakeDT)
    main_mod.start_daily_scans(FakeApp)
    tick = jobs[0]
    tick()
    assert runs == []                                   # 07:29
    clock["now"] = datetime(2026, 11, 10, 7, 30)
    tick()
    tick()
    assert runs == [1]                                  # once at 07:30, not twice
    clock["now"] = datetime(2026, 11, 11, 7, 30)
    tick()
    assert runs == [1, 1]                               # again the next day
    FakeApp.state.settings["cfg"]["schedule"]["daily_at"] = "9:05"   # changed in Settings, no restart
    clock["now"] = datetime(2026, 11, 12, 9, 5)
    tick()
    assert runs == [1, 1, 1]
