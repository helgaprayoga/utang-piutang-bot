"""Logika murni Bot Utang-Piutang: parsing input dan format teks.

Tidak ada akses Telegram maupun database di modul ini supaya mudah diuji.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

# Pengali satuan uang yang diterima, misalnya 50rb, 50k, 2jt.
_SATUAN_UANG = {
    "": 1,
    "k": 1_000,
    "rb": 1_000,
    "ribu": 1_000,
    "jt": 1_000_000,
    "juta": 1_000_000,
}

# Regex nominal menerima angka dengan satuan k, rb, jt, atau juta.
_RE_UANG = re.compile(r"^(\d+)(k|rb|ribu|jt|juta)?$", re.IGNORECASE)
# Regex tanggal menerima dd/mm dan dd/mm/yyyy.
_RE_TANGGAL = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?$")


def format_rupiah(nominal: int) -> str:
    """Format angka rupiah dengan titik ribuan, contoh 50000 -> 'Rp50.000'."""
    nominal = int(nominal)
    tanda = "-" if nominal < 0 else ""
    # Gunakan titik sebagai pemisah ribuan sesuai format Rupiah.
    return f"{tanda}Rp{abs(nominal):,}".replace(",", ".")


def parse_uang(token: str) -> int | None:
    """Ubah token nominal menjadi int.

    Menerima 50000, 50.000, Rp50.000, 50rb, 50k, 2jt.
    Mengembalikan None bila token bukan nominal positif yang valid.
    """
    # Bersihkan token dari simbol Rp, titik, koma, dan spasi.
    bersih = (
        token.strip()
        .lower()
        .replace("rp", "")
        .replace(".", "")
        .replace(",", "")
        .replace(" ", "")
    )
    cocok = _RE_UANG.fullmatch(bersih)
    # Kembalikan None bila token bukan nominal positif.
    if cocok is None:
        return None

    angka = int(cocok.group(1))
    satuan = (cocok.group(2) or "").lower()
    # Kalikan angka dengan satuan yang dipilih.
    nilai = angka * _SATUAN_UANG[satuan]
    return nilai if nilai > 0 else None


def parse_tanggal(token: str, hari_ini: date | None = None) -> date:
    """Parse 'dd/mm' atau 'dd/mm/yyyy' menjadi date.

    Bila tahun tidak ditulis, pakai tahun berjalan. Tanggal yang sudah lewat
    lebih dari 180 hari dianggap tahun depan (misalnya input 05/01 di bulan
    Desember).

    Raises:
        ValueError: format salah atau tanggal tidak ada di kalender.
    """
    # Periksa format tanggal sebelum memecah komponennya.
    cocok = _RE_TANGGAL.fullmatch(token.strip())
    if cocok is None:
        raise ValueError(f"Tanggal '{token}' harus format dd/mm atau dd/mm/yyyy.")

    hari = int(cocok.group(1))
    bulan = int(cocok.group(2))
    tahun_teks = cocok.group(3)
    hari_ini = hari_ini or date.today()

    if tahun_teks:
        tahun = int(tahun_teks)
        # Tahun dua digit dianggap berada di tahun 2000-an.
        if tahun < 100:
            tahun += 2000
    else:
        tahun = hari_ini.year

    try:
        hasil = date(tahun, bulan, hari)
    except ValueError:
        raise ValueError(f"Tanggal {token} tidak ada di kalender.") from None

    # Tanggal yang terlalu jauh di masa lalu dianggap tahun depan.
    if not tahun_teks and hasil < hari_ini - timedelta(days=180):
        try:
            hasil = date(tahun + 1, bulan, hari)
        except ValueError:
            pass
    return hasil


def format_tanggal(tanggal: date | None, pakai_tahun: bool = True) -> str:
    """Format date menjadi 'dd/mm/yyyy' atau 'dd/mm'; None menjadi '-'."""
    # Tanda '-' dipakai untuk catatan tanpa jatuh tempo.
    if tanggal is None:
        return "-"
    return tanggal.strftime("%d/%m/%Y" if pakai_tahun else "%d/%m")


def parse_debt(
    args: Sequence[str], hari_ini: date | None = None
) -> dict[str, Any]:
    """Pecah argumen /piutang atau /utang.

    Format: <nama> <jumlah> [catatan] [dd/mm | dd/mm/yyyy]
    Nama boleh terdiri dari beberapa kata selama berada sebelum nominal.

    Returns:
        {"nama": str, "jumlah": int, "catatan": str | None,
         "jatuh_tempo": date | None}

    Raises:
        ValueError: bila nama, jumlah, atau tanggal tidak valid.
    """
    # Tanpa argumen, nama dan jumlah belum bisa diproses.
    if not args:
        raise ValueError("Nama dan jumlah belum diisi.")

    tokens = list(args)
    indeks_uang: int | None = None
    jumlah: int | None = None
    sisa_token: list[str] = []

    # Cari token pertama yang bisa dibaca sebagai nominal.
    for i, token in enumerate(tokens):
        nilai = parse_uang(token)
        if nilai is None:
            continue

        pakai_token_berikutnya = False
        # Dukung nominal yang terpisah spasi seperti '50 rb'.
        if (
            i + 1 < len(tokens)
            and token.strip().isdigit()
            and tokens[i + 1].strip().lower() in _SATUAN_UANG
            and tokens[i + 1].strip().lower() != ""
        ):
            gabungan = parse_uang(token + tokens[i + 1])
            if gabungan is not None:
                nilai = gabungan
                pakai_token_berikutnya = True

        indeks_uang = i
        jumlah = nilai
        awal_catatan = i + 1 + (1 if pakai_token_berikutnya else 0)
        sisa_token = tokens[awal_catatan:]
        break

    if indeks_uang is None or jumlah is None:
        raise ValueError("Jumlah harus angka positif, contoh: 50000 atau 50rb.")

    nama = " ".join(tokens[:indeks_uang]).strip()
    if not nama:
        raise ValueError("Nama nggak boleh kosong.")

    jatuh_tempo: date | None = None
    # Token terakhir yang berbentuk tanggal dianggap jatuh tempo.
    if sisa_token and _RE_TANGGAL.fullmatch(sisa_token[-1].strip()):
        jatuh_tempo = parse_tanggal(sisa_token[-1], hari_ini)
        sisa_token = sisa_token[:-1]

    # Sisa token setelah nominal berisi catatan dan mungkin tanggal.
    catatan = " ".join(sisa_token).strip() or None
    return {
        "nama": nama,
        "jumlah": jumlah,
        "catatan": catatan,
        "jatuh_tempo": jatuh_tempo,
    }


def hari_terlambat(
    jatuh_tempo: date | None, hari_ini: date | None = None
) -> int:
    """Jumlah hari lewat jatuh tempo (0 bila belum lewat atau tanpa tempo)."""
    if jatuh_tempo is None:
        return 0
    # Nilai keterlambatan tidak pernah negatif.
    return max(0, ((hari_ini or date.today()) - jatuh_tempo).days)


def _format_item(debt: Mapping[str, Any], hari_ini: date) -> str:
    """Format satu catatan menjadi beberapa baris teks."""
    jumlah = int(debt["jumlah"])
    sisa = int(debt["sisa"])

    judul = f"- #{debt['id']} {debt['nama']} — {format_rupiah(jumlah)}"
    # Tampilkan sisa hanya jika sudah ada pembayaran.
    if sisa != jumlah:
        judul += f" (sisa {format_rupiah(sisa)})"

    rincian: list[str] = []
    tempo = debt.get("jatuh_tempo")
    if isinstance(tempo, date):
        selisih = (tempo - hari_ini).days
        teks_tempo = f"tempo {format_tanggal(tempo)}"
        # Beri label berbeda untuk telat, hari ini, dan mendekati tempo.
        if selisih < 0:
            teks_tempo += f" — telat {-selisih} hari"
        elif selisih == 0:
            teks_tempo += " — jatuh tempo hari ini"
        elif selisih <= 2:
            teks_tempo += f" — {selisih} hari lagi"
        rincian.append(teks_tempo)
    else:
        rincian.append("tanpa jatuh tempo")

    # Tambahkan catatan bila pengguna mengisinya.
    if debt.get("catatan"):
        rincian.append(f"catatan: {debt['catatan']}")

    return judul + "\n  " + " · ".join(rincian)


def format_daftar(
    debts: Sequence[Mapping[str, Any]], hari_ini: date | None = None
) -> str:
    """Susun pesan /daftar: bagian piutang dan utang beserta totalnya."""
    # Beri pesan ramah bila belum ada catatan aktif.
    if not debts:
        return (
            "Belum ada catatan aktif.\n\n"
            "Tambah piutang: /piutang Budi 50000 makan siang 20/11\n"
            "Tambah utang: /utang Ani 30000 kopi"
        )

    hari_ini = hari_ini or date.today()
    # Kelompokkan catatan berdasarkan jenisnya.
    kelompok: dict[str, list[Mapping[str, Any]]] = {
        "piutang": [],
        "utang": [],
    }
    for debt in debts:
        kelompok.setdefault(str(debt["tipe"]), []).append(debt)

    judul_bagian = (
        ("piutang", "PIUTANG — orang lain utang ke kamu"),
        ("utang", "UTANG — kamu utang ke orang lain"),
    )

    baris: list[str] = ["Daftar catatan aktif", ""]
    # Selalu tampilkan kedua bagian agar hasilnya konsisten.
    for tipe, judul in judul_bagian:
        items = kelompok.get(tipe, [])
        baris.append(judul)
        if not items:
            baris.append("- belum ada catatan")
            baris.append(f"Total {tipe} aktif: {format_rupiah(0)}")
        else:
            total_sisa = 0
            for debt in items:
                total_sisa += int(debt["sisa"])
                baris.append(_format_item(debt, hari_ini))
            baris.append(f"Total {tipe} aktif: {format_rupiah(total_sisa)}")
        baris.append("")

    return "\n".join(baris).rstrip()
