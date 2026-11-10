"""Tes login dan isolasi data dashboard web."""

from datetime import date, timedelta

import database as db
import web_auth
from web import create_app

CHAT_A = 111
CHAT_B = 222
SECRET = "rahasia-uji-web"


# Helper ini menyiapkan aplikasi dan dua pengguna untuk tes isolasi.
def buat_aplikasi(tmp_path):
    path = tmp_path / "data.db"
    app = create_app(db_path=str(path), secret_key=SECRET)
    app.config.update(TESTING=True)
    db.daftar_atau_buat_user(CHAT_A, "Pengguna A", path=path)
    db.daftar_atau_buat_user(CHAT_B, "Pengguna B", path=path)
    return app, path


# Login memakai token bot lalu menyimpan chat_id di sesi.
def masuk(client, chat_id):
    token = web_auth.buat_token(chat_id, secret=SECRET)
    return client.get(f"/auth/{token}")


# Dashboard dan API harus menolak permintaan tanpa sesi.
def test_dashboard_butuh_login(tmp_path):
    app, _ = buat_aplikasi(tmp_path)
    client = app.test_client()

    api = client.get("/api/dashboard")
    assert api.status_code == 401

    halaman = client.get("/dashboard")
    assert halaman.status_code == 403
    assert "Belum masuk" in halaman.get_data(as_text=True)


# Link dari bot harus membuat sesi dan logout harus menghapusnya.
def test_login_dan_logout(tmp_path):
    app, _ = buat_aplikasi(tmp_path)
    client = app.test_client()

    respons = masuk(client, CHAT_A)
    assert respons.status_code == 303
    assert respons.headers["Location"].endswith("/dashboard")
    with client.session_transaction() as sesi:
        assert sesi["chat_id"] == CHAT_A
        assert sesi["nama"] == "Pengguna A"

    assert client.get("/api/dashboard").status_code == 200
    client.get("/logout")
    assert client.get("/api/dashboard").status_code == 401


# Token palsu dan pengguna yang belum terdaftar harus ditolak.
def test_token_palsu_dan_pengguna_baru_ditolak(tmp_path):
    app, _ = buat_aplikasi(tmp_path)
    client = app.test_client()

    assert client.get("/auth/token-palsu").status_code == 403
    token = web_auth.buat_token(999, secret=SECRET)
    assert client.get(f"/auth/{token}").status_code == 403


# API dashboard hanya mengirim data milik pengguna yang login.
def test_api_hanya_data_milik_sendiri(tmp_path):
    app, path = buat_aplikasi(tmp_path)
    id_a = db.tambah_debt(
        CHAT_A,
        db.TIPE_PIUTANG,
        "Budi",
        50000,
        jatuh_tempo=date.today() + timedelta(days=5),
        path=path,
    )
    id_b = db.tambah_debt(
        CHAT_B, db.TIPE_UTANG, "Ani", 30000, path=path
    )
    client = app.test_client()
    masuk(client, CHAT_A)

    data = client.get("/api/dashboard").get_json()
    assert [item["nama"] for item in data["catatan"]] == ["Budi"]
    assert data["ringkasan"]["piutang_aktif"] == 50000
    assert data["ringkasan"]["utang_aktif"] == 0
    assert all(item["nama"] != "Ani" for item in data["catatan"])

    detail_a = client.get(f"/api/debts/{id_a}")
    assert detail_a.status_code == 200
    assert detail_a.get_json()["catatan"]["nama"] == "Budi"

    detail_b = client.get(f"/api/debts/{id_b}")
    assert detail_b.status_code == 404


# Payload dashboard harus memuat ringkasan, grafik, dan detail pembayaran.
def test_payload_dashboard_lengkap(tmp_path):
    app, path = buat_aplikasi(tmp_path)
    db.tambah_debt(CHAT_A, db.TIPE_PIUTANG, "Budi", 50000, path=path)
    id_lunas = db.tambah_debt(
        CHAT_A, db.TIPE_PIUTANG, "Citra", 30000, path=path
    )
    db.lunaskan(CHAT_A, id_lunas, path=path)
    client = app.test_client()
    masuk(client, CHAT_A)

    data = client.get("/api/dashboard").get_json()
    assert data["ringkasan"]["total_dibayar"] == 30000
    assert data["ringkasan"]["jumlah_lunas"] == 1
    assert data["grafik"]["per_nama"][0]["nama"] == "Budi"
    assert data["grafik"]["bulanan"][-1]["total"] == 30000
    assert data["pembayaran_terbaru"][0]["nama"] == "Citra"
    assert data["diperbarui"]

    detail = client.get(f"/api/debts/{id_lunas}").get_json()
    assert detail["total_dibayar"] == 30000
    assert detail["pembayaran"][0]["jumlah"] == 30000

# Halaman dashboard dan aset lokal harus bisa dimuat setelah login.
def test_halaman_dashboard_dan_aset(tmp_path):
    app, _ = buat_aplikasi(tmp_path)
    client = app.test_client()
    masuk(client, CHAT_A)

    halaman = client.get("/dashboard")
    assert halaman.status_code == 200
    isi = halaman.get_data(as_text=True)
    assert "Utang &amp; piutang kamu" in isi
    assert "chart.umd.min.js" in isi

    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/dashboard.js").status_code == 200
    assert client.get("/static/vendor/chart.umd.min.js").status_code == 200
