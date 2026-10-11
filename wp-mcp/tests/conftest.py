from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from fake_wp import start_fake_wp  # noqa: E402

from wp_mcp.app import build_services  # noqa: E402
from wp_mcp.config import load_config  # noqa: E402


class RecordingNotifier:
    enabled = True

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, actor, text):
        self.sent.append((actor.id, text))
        return True

    def last_otp(self) -> str:
        import re
        for _, text in reversed(self.sent):
            m = re.search(r"\b(\d{6})\b", text)
            if m:
                return m.group(1)
        raise AssertionError("tidak ada OTP terkirim")


class Clock:
    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t

    def advance(self, seconds: float):
        self.t += seconds


@pytest.fixture
def fake_wp():
    wp, srv, url = start_fake_wp()
    yield wp, url
    srv.shutdown()


@pytest.fixture
def env(tmp_path, fake_wp):
    wp, url = fake_wp
    cfgdir = tmp_path / "etc"
    cfgdir.mkdir()
    cli = tmp_path / "wp"
    cli.write_text(f"#!{sys.executable}\n" + (Path(__file__).parent / "fake_wp_cli.py").read_text())
    cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
    cli_log = tmp_path / "wpcli.log"
    os.environ["FAKE_WP_LOG"] = str(cli_log)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (cfgdir / "config.yaml").write_text(json.dumps({
        "site": {"url": url, "wp_path": str(tmp_path / "www"), "wp_cli": str(cli)},
        "state_dir": str(tmp_path / "state"), "log_dir": str(tmp_path / "log"),
        "media": {"inbox_dirs": [str(inbox)]},
        "notify": {"telegram": {"enabled": True}},
    }))
    (cfgdir / "actors.yaml").write_text(json.dumps({"actors": [
        {"id": "admin1", "name": "Admin Satu", "role": "admin-web", "telegram_user_id": 11, "wp_user": "rina"},
        {"id": "tech1", "name": "Admin Teknis", "role": "admin-web", "technical_admin": True, "telegram_user_id": 12},
        {"id": "pim1", "name": "Kepala", "role": "pimpinan", "telegram_user_id": 21, "wp_user": "kepala"},
    ]}))
    (cfgdir / "secrets.env").write_text("WPMCP_WP_USER=editor-ai\nWPMCP_WP_APP_PASSWORD='abcd efgh'\n")
    cfg = load_config(cfgdir)
    notifier = RecordingNotifier()
    clock = Clock()
    services = build_services(cfg, notifier=notifier, clock=clock)

    class Env:
        pass

    e = Env()
    e.wp, e.url, e.cfg, e.services, e.notifier, e.clock = wp, url, cfg, services, notifier, clock
    e.disp = services.dispatcher
    e.cfgdir, e.tmp, e.inbox, e.cli_log = cfgdir, tmp_path, inbox, cli_log

    # Bawaan uji: pintu manusia ("cli"). Pintu model ("claude_code") diuji khusus di test_model_door.py.
    def call(actor, tool, door="cli", **args):
        return e.disp.call(actor, tool, args, door=door)

    def ok(actor, tool, door="cli", **args):
        r = call(actor, tool, door=door, **args)
        assert r["ok"], r
        return r["data"] if r.get("data") is not None else r

    def confirm(actor, action_id, otp=None, door="cli"):
        return e.disp.call(actor, "confirm_action", {"action_id": action_id, "otp": otp}, door=door)

    e.call, e.ok, e.confirm = call, ok, confirm
    return e


FILLED_DIRECTORY = """---
dosir: direktori-redaksi
versi_skema: 1.0
situs_url: "https://humas.contoh.go.id"
opd_pemilik: "Bagian Protokol dan Komunikasi Pimpinan"
pemda: "Pemerintah Kabupaten Contoh"
diperbarui: "2026-10-11"
disahkan_oleh: "Admin Satu"
status: draft
---

## A. Identitas pemerintah daerah

| Bidang | Nilai | Keterangan | Wajib |
|---|---|---|---|
| nama_resmi | Pemerintah Kabupaten Contoh | | WAJIB |
| singkatan_resmi | Pemkab Contoh | | WAJIB |
| singkatan_dilarang | Pemda Contoh | | OPSIONAL |
| ibu_kota | Kota Baru | | WAJIB |
| format_dateline | `KOTA BARU -` | | WAJIB |

### A.1 Pimpinan daerah

| jabatan | nama_lengkap_bergelar | sebutan_pertama | sebutan_berikutnya | sejak | sumber | verif |
|---|---|---|---|---|---|---|
| Bupati | H. Ahmad Fauzi, S.E. | Bupati Contoh, H. Ahmad Fauzi | Bupati | 2025 | SK | ya |

## B. OPD pemilik website `[WAJIB]`

| Bidang | Nilai | Wajib |
|---|---|---|
| nama_resmi | Badan Kepegawaian dan Pengembangan Sumber Daya Manusia | WAJIB |
| singkatan_resmi | BKPSDM | WAJIB |
| singkatan_dilarang | BKD, BKPPD | OPSIONAL |
| alamat_kantor | Jl. Contoh No. 1 | WAJIB |
| kredit_foto | (Foto: BKPSDM Contoh) | WAJIB |
| penanda_sumber_berita | (BKPSDM Contoh) | WAJIB |

## C. Unit kerja di dalam OPD `[WAJIB]`

| kode | nama_resmi_unit | singkatan | induk | sumber | verif |
|---|---|---|---|---|---|
| U02 | Bidang Pengembangan Sumber Daya Manusia | Bidang PSDM | (OPD) | Perbup | ya |

## D. Pejabat struktural `[WAJIB]`

| kode | nama_lengkap_bergelar | jabatan_resmi | unit | sebutan_berikutnya | sejak | ejaan_salah | sumber | verif |
|---|---|---|---|---|---|---|---|---|
| P01 | Drs. Budi Santoso, M.AP | Kepala Badan Kepegawaian dan Pengembangan Sumber Daya Manusia | (OPD) | Kepala BKPSDM | 2024 | Budi Santosa | SK | ya |
| P03 | Rina Marlina, S.Kom | Kepala Bidang Pengembangan Sumber Daya Manusia | U02 | Kabid PSDM | 2025 | | SK | ya |

## F. Tempat yang sering disebut `[OPSIONAL]`

| nama_resmi | ejaan_salah | jenis | kecamatan | verif |
|---|---|---|---|---|
| Aula Rakat Mufakat | Aula Rakat Mupakat | aula | Kota Baru | ya |

### H.1 Peta kategori WordPress

| jenis_berita | kategori_wordpress | tag_wajib |
|---|---|---|
| kegiatan pimpinan | Kegiatan Pimpinan | |

## I. Redaksi website

| peran | nama | kanal |
|---|---|---|
| Admin (penerbit) | Admin Satu | Telegram user_id: 11 |
"""


@pytest.fixture
def env_dir(env):
    r = env.call("admin1", "directory_import", markdown=FILLED_DIRECTORY)
    assert r["ok"], r
    return env
