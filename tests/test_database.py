"""Tes database multi-pengguna: skema, isolasi data, dan pelunasan."""

import sqlite3
from datetime import date, timedelta

import pytest

import database as db

CHAT_A = 111
CHAT_B = 222


# Helper ini membuat database bersih dengan dua pengguna untuk tes isolasi.
def siapkan_db(tmp_path):
    """Database baru berisi dua pengguna untuk tes isolasi."""
    path = tmp_path / "data.db"
    db.siapkan(path)
    db.daftar_atau_buat_user(CHAT_A, "Pengguna A", path=path)
    db.daftar_atau_buat_user(CHAT_B, "Pengguna B", path=path)
    return path


# Skema baru harus membuat tabel users, debts, dan payments.
def test_siapkan_membuat_tabel_multi_pengguna(tmp_path):
    path = tmp_path / "data.db"
    db.siapkan(path)

    con = sqlite3.connect(path)
    tabel = {
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    versi = con.execute("PRAGMA user_version").fetchone()[0]
    con.close()

    assert {"users", "debts", "payments"} <= tabel
    assert versi == 1


# Database lama tanpa kolom chat_id harus ditolak.
def test_siapkan_menolak_skema_lama(tmp_path):
    path = tmp_path / "lama.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE debts (id INTEGER PRIMARY KEY, nama TEXT)")
    con.commit()
    con.close()

    with pytest.raises(RuntimeError, match="skema lama"):
        db.siapkan(path)


# Pengguna baru harus mendapat pengaturan pengingat default.
def test_pengguna_baru_dan_pengaturan_default(tmp_path):
    path = siapkan_db(tmp_path)

    user = db.ambil_user(CHAT_A, path=path)
    assert user is not None
    assert user["nama"] == "Pengguna A"
    assert user["jam_pengingat"] == db.JAM_DEFAULT
    assert user["pengingat_hari"] == db.MILESTONE_DEFAULT
    assert user["tgl_daftar"] == date.today()

    diperbarui = db.daftar_atau_buat_user(CHAT_A, "A Baru", path=path)
    assert diperbarui["nama"] == "A Baru"
    assert db.ambil_user(999, path=path) is None


# Perubahan pengaturan satu pengguna tidak boleh memengaruhi pengguna lain.
def test_pengaturan_terpisah_per_pengguna(tmp_path):
    path = siapkan_db(tmp_path)

    assert db.simpan_jam_pengingat(CHAT_A, "07:30", path=path)
    assert db.simpan_milestone_pengingat(CHAT_A, "30,7", path=path)

    user_a = db.ambil_user(CHAT_A, path=path)
    user_b = db.ambil_user(CHAT_B, path=path)
    assert user_a is not None
    assert user_b is not None
    assert user_a["jam_pengingat"] == "07:30"
    assert user_a["pengingat_hari"] == "30,7"
    assert user_b["jam_pengingat"] == db.JAM_DEFAULT
    assert user_b["pengingat_hari"] == db.MILESTONE_DEFAULT

    assert not db.simpan_jam_pengingat(999, "09:00", path=path)
    assert not db.simpan_milestone_pengingat(999, "1", path=path)


# Setiap pengguna hanya boleh melihat dan mengambil catatannya sendiri.
def test_catatan_terpisah_per_pengguna(tmp_path):
    path = siapkan_db(tmp_path)

    id_a = db.tambah_debt(
        CHAT_A,
        db.TIPE_PIUTANG,
        "Budi",
        50000,
        "makan siang",
        date(2026, 11, 20),
        path=path,
    )
    id_b = db.tambah_debt(
        CHAT_B,
        db.TIPE_UTANG,
        "Ani",
        30000,
        None,
        None,
        path=path,
    )
    id_a2 = db.tambah_debt(
        CHAT_A, db.TIPE_UTANG, "Citra", 20000, path=path
    )

    debt_a = db.ambil_debt(CHAT_A, id_a, path=path)
    assert debt_a is not None
    assert debt_a["chat_id"] == CHAT_A
    assert debt_a["nama"] == "Budi"
    assert debt_a["sisa"] == 50000
    assert debt_a["status"] == "aktif"
    assert debt_a["jatuh_tempo"] == date(2026, 11, 20)

    assert db.ambil_debt(CHAT_B, id_a, path=path) is None
    assert db.ambil_debt(CHAT_A, id_b, path=path) is None
    assert db.ambil_debt(CHAT_A, 9999, path=path) is None

    daftar_a = db.daftar_debt(CHAT_A, path=path)
    assert [d["id"] for d in daftar_a] == [id_a, id_a2]

    daftar_b = db.daftar_debt(CHAT_B, path=path)
    assert [d["id"] for d in daftar_b] == [id_b]


# Pelunasan harus dibatasi pada pemilik catatan dan mencatat pembayaran.
def test_lunas_terbatas_pada_pemilik(tmp_path):
    path = siapkan_db(tmp_path)
    id_a = db.tambah_debt(
        CHAT_A, db.TIPE_PIUTANG, "Budi", 50000, path=path
    )
    id_b = db.tambah_debt(
        CHAT_B, db.TIPE_UTANG, "Ani", 30000, path=path
    )

    gagal = db.lunaskan(CHAT_B, id_a, path=path)
    assert gagal["hasil"] == "tidak_ada"
    debt_a = db.ambil_debt(CHAT_A, id_a, path=path)
    assert debt_a is not None
    assert debt_a["sisa"] == 50000
    assert debt_a["status"] == "aktif"

    hasil = db.lunaskan(CHAT_A, id_a, path=path)
    assert hasil["hasil"] == "berhasil"
    assert hasil["dibayar"] == 50000
    assert hasil["debt"]["sisa"] == 0
    assert hasil["debt"]["status"] == "lunas"

    assert db.daftar_debt(CHAT_A, path=path) == []
    assert [d["id"] for d in db.daftar_debt(CHAT_B, path=path)] == [id_b]

    con = sqlite3.connect(path)
    pembayaran = con.execute(
        "SELECT debt_id, jumlah FROM payments"
    ).fetchall()
    con.close()
    assert pembayaran == [(id_a, 50000)]

    assert len(db.riwayat_pembayaran(CHAT_A, id_a, path=path)) == 1
    assert db.riwayat_pembayaran(CHAT_B, id_a, path=path) == []
    assert db.total_pembayaran(CHAT_A, id_a, path=path) == 50000
    assert db.total_pembayaran(CHAT_B, id_a, path=path) == 0

    ulang = db.lunaskan(CHAT_A, id_a, path=path)
    assert ulang["hasil"] == "sudah_lunas"
    assert db.lunaskan(CHAT_A, 9999, path=path)["hasil"] == "tidak_ada"

# Ringkasan web harus memisahkan angka pengguna A dan B.
def test_ringkasan_web_terpisah_per_pengguna(tmp_path):
    path = siapkan_db(tmp_path)
    db.tambah_debt(CHAT_A, db.TIPE_PIUTANG, "Budi", 50000, path=path)
    db.tambah_debt(CHAT_A, db.TIPE_UTANG, "Ani", 20000, path=path)
    id_lunas = db.tambah_debt(
        CHAT_A, db.TIPE_PIUTANG, "Citra", 30000, path=path
    )
    db.lunaskan(CHAT_A, id_lunas, path=path)
    db.tambah_debt(CHAT_B, db.TIPE_PIUTANG, "Dedi", 40000, path=path)

    ringkasan_a = db.ringkasan_web(CHAT_A, path=path)
    assert ringkasan_a["piutang_aktif"] == 50000
    assert ringkasan_a["utang_aktif"] == 20000
    assert ringkasan_a["total_sisa"] == 70000
    assert ringkasan_a["saldo_bersih"] == 30000
    assert ringkasan_a["jumlah_aktif"] == 2
    assert ringkasan_a["jumlah_lunas"] == 1
    assert ringkasan_a["total_dibayar"] == 30000
    assert ringkasan_a["jumlah_telat"] == 0

    ringkasan_b = db.ringkasan_web(CHAT_B, path=path)
    assert ringkasan_b["piutang_aktif"] == 40000
    assert ringkasan_b["utang_aktif"] == 0
    assert ringkasan_b["jumlah_aktif"] == 1
    assert ringkasan_b["total_dibayar"] == 0


# Grafik per nama dan pembayaran bulanan hanya membaca data pemilik.
def test_agregat_grafik_web_terpisah(tmp_path):
    path = siapkan_db(tmp_path)
    db.tambah_debt(CHAT_A, db.TIPE_PIUTANG, "Budi", 50000, path=path)
    db.tambah_debt(CHAT_A, db.TIPE_PIUTANG, "Budi", 10000, path=path)
    db.tambah_debt(CHAT_A, db.TIPE_UTANG, "Ani", 20000, path=path)
    id_lunas = db.tambah_debt(
        CHAT_A, db.TIPE_PIUTANG, "Citra", 30000, path=path
    )
    db.lunaskan(CHAT_A, id_lunas, path=path)
    db.tambah_debt(CHAT_B, db.TIPE_PIUTANG, "Dedi", 40000, path=path)

    per_nama = db.sisa_per_nama(CHAT_A, path=path)
    assert per_nama[0] == {
        "nama": "Budi",
        "tipe": db.TIPE_PIUTANG,
        "sisa": 60000,
        "jumlah": 2,
    }
    assert per_nama[1]["nama"] == "Ani"
    assert per_nama[1]["sisa"] == 20000

    bulanan = db.pembayaran_per_bulan(CHAT_A, path=path)
    assert len(bulanan) == 12
    assert bulanan[-1]["bulan"] == date.today().strftime("%Y-%m")
    assert bulanan[-1]["total"] == 30000
    assert sum(item["total"] for item in bulanan) == 30000

    terbaru = db.pembayaran_terbaru(CHAT_A, path=path)
    assert len(terbaru) == 1
    assert terbaru[0]["nama"] == "Citra"
    assert terbaru[0]["jumlah"] == 30000
    assert terbaru[0]["tanggal"] == date.today()
    assert db.pembayaran_terbaru(CHAT_B, path=path) == []


# Jatuh tempo dan catatan telat tetap terisolasi per pengguna.
def test_jatuh_tempo_dan_telat_terpisah(tmp_path):
    path = siapkan_db(tmp_path)
    id_dekat = db.tambah_debt(
        CHAT_A,
        db.TIPE_PIUTANG,
        "Budi",
        50000,
        jatuh_tempo=date.today() + timedelta(days=5),
        path=path,
    )
    db.tambah_debt(
        CHAT_A,
        db.TIPE_UTANG,
        "Ani",
        20000,
        jatuh_tempo=date.today() + timedelta(days=40),
        path=path,
    )
    id_telat = db.tambah_debt(
        CHAT_A,
        db.TIPE_PIUTANG,
        "Citra",
        30000,
        jatuh_tempo=date.today() - timedelta(days=3),
        path=path,
    )
    db.tambah_debt(
        CHAT_B,
        db.TIPE_PIUTANG,
        "Dedi",
        40000,
        jatuh_tempo=date.today() + timedelta(days=5),
        path=path,
    )

    dekat = db.jatuh_tempo_terdekat(CHAT_A, path=path)
    assert [item["id"] for item in dekat] == [id_dekat]
    telat = db.catatan_telat(CHAT_A, path=path)
    assert [item["id"] for item in telat] == [id_telat]

    dekat_b = db.jatuh_tempo_terdekat(CHAT_B, path=path)
    assert len(dekat_b) == 1
    assert dekat_b[0]["nama"] == "Dedi"
    assert db.catatan_telat(CHAT_B, path=path) == []

# Database harus memakai WAL agar web dan bot bisa mengakses bersamaan.
def test_siapkan_mengaktifkan_wal(tmp_path):
    path = tmp_path / "data.db"
    db.siapkan(path)

    con = sqlite3.connect(path)
    mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    con.close()

    assert mode.lower() == "wal"
