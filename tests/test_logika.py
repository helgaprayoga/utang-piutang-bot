"""Tes logika murni: parsing nominal/tanggal dan format pesan."""

from datetime import date

import pytest

import logika

# Tanggal tetap membuat hasil tes konsisten setiap hari.
HARI_INI = date(2026, 11, 8)


# Pastikan semua format nominal yang didukung dikenali dengan benar.
@pytest.mark.parametrize(
    ("token", "hasil"),
    [
        ("50000", 50000),
        ("50.000", 50000),
        ("Rp50.000", 50000),
        ("50rb", 50000),
        ("50K", 50000),
        ("2jt", 2_000_000),
        ("50 rb", 50000),
        ("0", None),
        ("-5000", None),
        ("abc", None),
        ("", None),
    ],
)
def test_parse_uang(token, hasil):
    assert logika.parse_uang(token) == hasil


# Tanggal lengkap dan singkat harus menghasilkan tanggal yang sama.
def test_parse_tanggal_lengkap_dan_singkat():
    assert logika.parse_tanggal("20/11", HARI_INI) == date(2026, 11, 20)
    assert logika.parse_tanggal("20/11/2027", HARI_INI) == date(2027, 11, 20)
    assert logika.parse_tanggal("20/11/27", HARI_INI) == date(2027, 11, 20)


# Tanggal awal tahun di bulan Desember harus dianggap tahun depan.
def test_parse_tanggal_tahun_ditebak_untuk_januari():
    assert logika.parse_tanggal("05/01", date(2026, 12, 20)) == date(2027, 1, 5)


# Tanggal yang tidak ada di kalender harus ditolak.
def test_parse_tanggal_tidak_valid():
    with pytest.raises(ValueError):
        logika.parse_tanggal("31/02", HARI_INI)


# Argumen harus terpecah menjadi nama, jumlah, catatan, dan tempo.
@pytest.mark.parametrize(
    ("args", "nama", "jumlah", "catatan", "tempo"),
    [
        (
            ["Budi", "50000", "makan", "siang", "20/11"],
            "Budi",
            50000,
            "makan siang",
            date(2026, 11, 20),
        ),
        (
            ["Budi", "Santoso", "50rb"],
            "Budi Santoso",
            50000,
            None,
            None,
        ),
        (
            ["Ani", "30", "rb", "kopi"],
            "Ani",
            30000,
            "kopi",
            None,
        ),
        (
            ["Ani", "Rp30.000", "20/11/2027"],
            "Ani",
            30000,
            None,
            date(2027, 11, 20),
        ),
    ],
)
def test_parse_debt(args, nama, jumlah, catatan, tempo):
    data = logika.parse_debt(args, HARI_INI)
    assert data == {
        "nama": nama,
        "jumlah": jumlah,
        "catatan": catatan,
        "jatuh_tempo": tempo,
    }


# Input tidak lengkap atau tidak valid harus memunculkan ValueError.
@pytest.mark.parametrize(
    "args",
    [
        [],
        ["Budi"],
        ["50000"],
        ["Budi", "50000", "31/02"],
    ],
)
def test_parse_debt_tidak_valid(args):
    with pytest.raises(ValueError):
        logika.parse_debt(args, HARI_INI)


# Format Rupiah harus memakai titik sebagai pemisah ribuan.
def test_format_rupiah():
    assert logika.format_rupiah(0) == "Rp0"
    assert logika.format_rupiah(50000) == "Rp50.000"
    assert logika.format_rupiah(1_234_567) == "Rp1.234.567"


# Daftar kosong harus menghasilkan pesan ramah.
def test_format_daftar_kosong():
    assert "Belum ada catatan aktif" in logika.format_daftar([])


# Piutang dan utang harus tampil terpisah beserta totalnya.
def test_format_daftar_lengkap_dan_terpisah():
    debts = [
        {
            "id": 2,
            "tipe": "utang",
            "nama": "Ani",
            "jumlah": 30000,
            "sisa": 30000,
            "catatan": "kopi",
            "jatuh_tempo": None,
        },
        {
            "id": 1,
            "tipe": "piutang",
            "nama": "Budi",
            "jumlah": 50000,
            "sisa": 20000,
            "catatan": "makan siang",
            "jatuh_tempo": date(2026, 11, 5),
        },
    ]

    teks = logika.format_daftar(debts, HARI_INI)

    assert teks.index("PIUTANG") < teks.index("UTANG")
    assert "#1 Budi — Rp50.000 (sisa Rp20.000)" in teks
    assert "telat 3 hari" in teks
    assert "Total piutang aktif: Rp20.000" in teks
    assert "Total utang aktif: Rp30.000" in teks
