"""Akses data Bot Utang-Piutang (multi-pengguna) ke SQLite.

Setiap catatan dimiliki oleh satu chat_id. Seluruh query SQL berada di modul
ini dan wajib menyertakan chat_id agar data antar pengguna tidak tercampur.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator, TypedDict

# Nilai default dipakai saat pengguna pertama kali terdaftar.
DB_PATH = "data.db"

STATUS_AKTIF = "aktif"
STATUS_LUNAS = "lunas"

TIPE_PIUTANG = "piutang"
TIPE_UTANG = "utang"

JAM_DEFAULT = "08:00"
MILESTONE_DEFAULT = "30,7,1,0"


# Struktur data untuk satu pengguna bot.
class User(TypedDict):
    """Satu baris tabel users."""

    chat_id: int
    nama: str | None
    jam_pengingat: str
    pengingat_hari: str
    tgl_daftar: date


# Struktur data untuk satu catatan piutang atau utang.
class Debt(TypedDict):
    """Satu baris tabel debts dengan tipe data yang sudah dirapikan."""

    id: int
    chat_id: int
    tipe: str
    nama: str
    jumlah: int
    sisa: int
    catatan: str | None
    tgl_dibuat: date
    jatuh_tempo: date | None
    status: str


# Struktur data untuk satu pembayaran cicilan.
class Payment(TypedDict):
    """Satu baris tabel payments."""

    id: int
    debt_id: int
    jumlah: int
    tanggal: date


# Context manager ini memastikan koneksi selalu ditutup dengan aman.
@contextmanager
def koneksi(path: str | Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Buka koneksi SQLite, commit bila sukses, rollback bila terjadi error."""
    con = sqlite3.connect(str(path), timeout=5)
    con.row_factory = sqlite3.Row
    # Aktifkan foreign key agar data terkait ikut terhapus dengan benar.
    con.execute("PRAGMA foreign_keys = ON")
    # Beri waktu tunggu bila bot dan web mengakses database bersamaan.
    con.execute("PRAGMA busy_timeout = 5000")
    con.execute("PRAGMA synchronous = NORMAL")
    try:
        # Transaksi otomatis commit atau rollback di dalam blok ini.
        with con:
            yield con
    finally:
        con.close()


def _tolak_skema_lama(path: Path) -> None:
    """Cegah database satu-pengguna lama dipakai tanpa migrasi."""
    # File database kosong tidak perlu diperiksa.
    if not path.exists() or path.stat().st_size == 0:
        return
    con = sqlite3.connect(str(path))
    try:
        tabel = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "debts" in tabel:
            kolom = {
                row[1] for row in con.execute("PRAGMA table_info(debts)")
            }
            # Tabel debts lama tidak memiliki kolom chat_id.
            if "chat_id" not in kolom:
                raise RuntimeError(
                    "data.db memakai skema lama satu pengguna. "
                    "Pindahkan atau hapus file data.db, lalu jalankan ulang."
                )
    finally:
        con.close()


def siapkan(path: str | Path = DB_PATH) -> None:
    """Buat tabel dan indeks multi-pengguna bila database belum ada."""
    path = Path(path)
    # Tolak database lama sebelum membuat tabel baru.
    _tolak_skema_lama(path)

    # Aktifkan WAL agar bot dan web bisa membaca/menulis bersamaan.
    con_wal = sqlite3.connect(str(path))
    try:
        con_wal.execute("PRAGMA journal_mode = WAL")
    finally:
        con_wal.close()

    with koneksi(path) as con:
        # Buat seluruh tabel dan indeks yang dibutuhkan aplikasi.
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id        INTEGER PRIMARY KEY,
                nama           TEXT,
                jam_pengingat  TEXT NOT NULL DEFAULT '08:00',
                pengingat_hari TEXT NOT NULL DEFAULT '30,7,1,0',
                tgl_daftar     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS debts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER NOT NULL,
                tipe        TEXT    NOT NULL CHECK (tipe IN ('piutang', 'utang')),
                nama        TEXT    NOT NULL,
                jumlah      INTEGER NOT NULL CHECK (jumlah > 0),
                sisa        INTEGER NOT NULL CHECK (sisa >= 0),
                catatan     TEXT,
                tgl_dibuat  TEXT    NOT NULL,
                jatuh_tempo TEXT,
                status      TEXT    NOT NULL DEFAULT 'aktif'
                            CHECK (status IN ('aktif', 'lunas')),
                FOREIGN KEY (chat_id) REFERENCES users (chat_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS payments (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                debt_id INTEGER NOT NULL,
                jumlah  INTEGER NOT NULL CHECK (jumlah > 0),
                tanggal TEXT    NOT NULL,
                FOREIGN KEY (debt_id) REFERENCES debts (id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_debts_chat_status
                ON debts (chat_id, status);
            CREATE INDEX IF NOT EXISTS idx_debts_chat_tempo
                ON debts (chat_id, jatuh_tempo);
            CREATE INDEX IF NOT EXISTS idx_payments_debt
                ON payments (debt_id);

            PRAGMA user_version = 1;
            """
        )


# Fungsi pengguna mengatur pendaftaran dan preferensi pengingat.
def _user_dari_row(row: sqlite3.Row) -> User:
    """Ubah sqlite3.Row menjadi User dengan tanggal asli."""
    # Konversi baris database menjadi struktur User.
    return User(
        chat_id=row["chat_id"],
        nama=row["nama"],
        jam_pengingat=row["jam_pengingat"],
        pengingat_hari=row["pengingat_hari"],
        tgl_daftar=date.fromisoformat(row["tgl_daftar"]),
    )


def daftar_atau_buat_user(
    chat_id: int, nama: str | None = None, path: str | Path = DB_PATH
) -> User:
    """Daftarkan pengguna baru atau perbarui namanya bila sudah terdaftar."""
    with koneksi(path) as con:
        # Upsert menjaga pengaturan lama tetap utuh saat pengguna kembali.
        con.execute(
            """
            INSERT INTO users (chat_id, nama, tgl_daftar)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                nama = COALESCE(excluded.nama, users.nama)
            """,
            (chat_id, nama, date.today().isoformat()),
        )
        # Ambil ulang data agar nilai default ikut terbaca.
        row = con.execute(
            "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    if row is None:
        raise RuntimeError("Gagal menyimpan data pengguna.")
    return _user_dari_row(row)


def ambil_user(
    chat_id: int, path: str | Path = DB_PATH
) -> User | None:
    """Ambil data pengguna, atau None bila belum terdaftar."""
    with koneksi(path) as con:
        row = con.execute(
            "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    # Kembalikan None bila chat_id belum terdaftar.
    return _user_dari_row(row) if row is not None else None


def daftar_user(path: str | Path = DB_PATH) -> list[User]:
    """Ambil semua pengguna, dipakai saat menjadwalkan pengingat."""
    with koneksi(path) as con:
        rows = con.execute("SELECT * FROM users ORDER BY chat_id").fetchall()
    # Data ini nanti dipakai untuk menjadwalkan pengingat semua pengguna.
    return [_user_dari_row(row) for row in rows]


def simpan_jam_pengingat(
    chat_id: int, jam: str, path: str | Path = DB_PATH
) -> bool:
    """Simpan jam pengingat milik satu pengguna."""
    with koneksi(path) as con:
        # Hanya pengguna yang cocok yang boleh diperbarui.
        cur = con.execute(
            "UPDATE users SET jam_pengingat = ? WHERE chat_id = ?",
            (jam, chat_id),
        )
        # Hasil True menandakan jam berhasil disimpan.
        return cur.rowcount == 1


def simpan_milestone_pengingat(
    chat_id: int, milestone: str, path: str | Path = DB_PATH
) -> bool:
    """Simpan daftar H-N pengingat milik satu pengguna."""
    with koneksi(path) as con:
        # Hanya pengguna yang cocok yang boleh diperbarui.
        cur = con.execute(
            "UPDATE users SET pengingat_hari = ? WHERE chat_id = ?",
            (milestone, chat_id),
        )
        # Hasil True menandakan milestone berhasil disimpan.
        return cur.rowcount == 1


# Fungsi catatan mengatur piutang, utang, dan pembayarannya.
def _debt_dari_row(row: sqlite3.Row) -> Debt:
    """Ubah sqlite3.Row menjadi Debt dengan tanggal asli."""
    # Konversi baris database dan parse tanggal ISO menjadi date.
    return Debt(
        id=row["id"],
        chat_id=row["chat_id"],
        tipe=row["tipe"],
        nama=row["nama"],
        jumlah=row["jumlah"],
        sisa=row["sisa"],
        catatan=row["catatan"],
        tgl_dibuat=date.fromisoformat(row["tgl_dibuat"]),
        jatuh_tempo=(
            date.fromisoformat(row["jatuh_tempo"]) if row["jatuh_tempo"] else None
        ),
        status=row["status"],
    )


def tambah_debt(
    chat_id: int,
    tipe: str,
    nama: str,
    jumlah: int,
    catatan: str | None = None,
    jatuh_tempo: date | None = None,
    path: str | Path = DB_PATH,
) -> int:
    """Simpan catatan piutang/utang milik chat_id lalu kembalikan id-nya."""
    # Tolak jenis catatan di luar piutang dan utang.
    if tipe not in (TIPE_PIUTANG, TIPE_UTANG):
        raise ValueError("tipe harus 'piutang' atau 'utang'")
    # Nominal harus positif agar sisa tidak aneh.
    if jumlah <= 0:
        raise ValueError("jumlah harus lebih dari 0")

    with koneksi(path) as con:
        # Sisa awal selalu sama dengan jumlah catatan.
        cur = con.execute(
            """
            INSERT INTO debts
                (chat_id, tipe, nama, jumlah, sisa, catatan,
                 tgl_dibuat, jatuh_tempo, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                tipe,
                nama,
                jumlah,
                jumlah,
                catatan,
                date.today().isoformat(),
                jatuh_tempo.isoformat() if jatuh_tempo else None,
                STATUS_AKTIF,
            ),
        )
        return int(cur.lastrowid)


def ambil_debt(
    chat_id: int, debt_id: int, path: str | Path = DB_PATH
) -> Debt | None:
    """Ambil catatan milik chat_id, atau None bila tidak ada/bukan miliknya."""
    with koneksi(path) as con:
        # Filter chat_id mencegah akses ke catatan pengguna lain.
        row = con.execute(
            "SELECT * FROM debts WHERE id = ? AND chat_id = ?",
            (debt_id, chat_id),
        ).fetchone()
    return _debt_dari_row(row) if row is not None else None


def daftar_debt(
    chat_id: int,
    status: str | None = STATUS_AKTIF,
    path: str | Path = DB_PATH,
) -> list[Debt]:
    """Ambil catatan milik chat_id, urut jatuh tempo terdekat."""
    # Catatan tanpa jatuh tempo diletakkan paling bawah.
    urutan = "ORDER BY jatuh_tempo IS NULL, jatuh_tempo, id"
    with koneksi(path) as con:
        if status is None:
            # Status None dipakai untuk mengambil semua status.
            rows = con.execute(
                f"SELECT * FROM debts WHERE chat_id = ? {urutan}",
                (chat_id,),
            ).fetchall()
        else:
            rows = con.execute(
                f"""SELECT * FROM debts
                    WHERE chat_id = ? AND status = ? {urutan}""",
                (chat_id, status),
            ).fetchall()
    return [_debt_dari_row(row) for row in rows]


def lunaskan(
    chat_id: int, debt_id: int, path: str | Path = DB_PATH
) -> dict:
    """Tandai catatan milik chat_id lunas dan catat sisa akhir.

    Returns:
        {"hasil": "tidak_ada"} bila id tidak ada atau bukan milik chat_id.
        {"hasil": "sudah_lunas", "debt": Debt} bila sudah lunas sebelumnya.
        {"hasil": "berhasil", "debt": Debt, "dibayar": int} bila berhasil.
    """
    with koneksi(path) as con:
        # Cari catatan hanya di dalam data milik chat_id ini.
        row = con.execute(
            "SELECT * FROM debts WHERE id = ? AND chat_id = ?",
            (debt_id, chat_id),
        ).fetchone()
        if row is None:
            return {"hasil": "tidak_ada"}

        debt = _debt_dari_row(row)
        # Catatan yang sudah lunas tidak dicatat pembayarannya lagi.
        if debt["status"] == STATUS_LUNAS:
            return {"hasil": "sudah_lunas", "debt": debt}

        dibayar = debt["sisa"]
        # Simpan sisa terakhir sebagai pembayaran penutup.
        if dibayar > 0:
            con.execute(
                "INSERT INTO payments (debt_id, jumlah, tanggal) VALUES (?, ?, ?)",
                (debt_id, dibayar, date.today().isoformat()),
            )
        # Ubah sisa dan status dalam satu transaksi.
        con.execute(
            "UPDATE debts SET sisa = 0, status = ? WHERE id = ? AND chat_id = ?",
            (STATUS_LUNAS, debt_id, chat_id),
        )

    # Sinkronkan objek hasil dengan kondisi setelah transaksi.
    debt["sisa"] = 0
    debt["status"] = STATUS_LUNAS
    return {"hasil": "berhasil", "debt": debt, "dibayar": dibayar}


def riwayat_pembayaran(
    chat_id: int, debt_id: int, path: str | Path = DB_PATH
) -> list[Payment]:
    """Riwayat pembayaran satu catatan, hanya bila milik chat_id."""
    with koneksi(path) as con:
        # Join ke debts memastikan riwayat hanya terbaca oleh pemiliknya.
        rows = con.execute(
            """
            SELECT p.* FROM payments p
            JOIN debts d ON d.id = p.debt_id
            WHERE p.debt_id = ? AND d.chat_id = ?
            ORDER BY p.tanggal, p.id
            """,
            (debt_id, chat_id),
        ).fetchall()
    # Ubah setiap baris menjadi struktur Payment.
    return [
        Payment(
            id=row["id"],
            debt_id=row["debt_id"],
            jumlah=row["jumlah"],
            tanggal=date.fromisoformat(row["tanggal"]),
        )
        for row in rows
    ]


def total_pembayaran(
    chat_id: int, debt_id: int, path: str | Path = DB_PATH
) -> int:
    """Total pembayaran satu catatan milik chat_id."""
    with koneksi(path) as con:
        # Jumlahkan pembayaran lewat join agar tetap terikat pada pemilik.
        row = con.execute(
            """
            SELECT COALESCE(SUM(p.jumlah), 0) AS total
            FROM payments p
            JOIN debts d ON d.id = p.debt_id
            WHERE p.debt_id = ? AND d.chat_id = ?
            """,
            (debt_id, chat_id),
        ).fetchone()
    return int(row["total"]) if row is not None else 0


# Fungsi agregat berikut khusus dashboard web dan tetap dibatasi chat_id.
def _bulan_terakhir(jumlah: int, hari_ini: date | None = None) -> list[str]:
    """Kembalikan daftar bulan ISO terakhir, urut dari lama ke baru."""
    hari_ini = hari_ini or date.today()
    tahun = hari_ini.year
    bulan = hari_ini.month
    daftar: list[str] = []
    # Mundur satu bulan sampai jumlah bulan yang diminta terpenuhi.
    for _ in range(max(1, jumlah)):
        daftar.append(f"{tahun:04d}-{bulan:02d}")
        bulan -= 1
        # Setelah Januari, lanjut ke Desember tahun sebelumnya.
        if bulan == 0:
            bulan = 12
            tahun -= 1
    return list(reversed(daftar))


def ringkasan_web(chat_id: int, path: str | Path = DB_PATH) -> dict:
    """Ambil angka ringkasan dashboard milik satu pengguna."""
    hari_ini = date.today().isoformat()
    with koneksi(path) as con:
        # Hitung piutang, utang, dan jumlah catatan dalam satu query.
        row = con.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN tipe = :piutang AND status = :aktif
                                  THEN sisa END), 0) AS piutang_aktif,
                COALESCE(SUM(CASE WHEN tipe = :utang AND status = :aktif
                                  THEN sisa END), 0) AS utang_aktif,
                COALESCE(SUM(CASE WHEN status = :aktif
                                  THEN sisa END), 0) AS total_sisa,
                COALESCE(SUM(CASE WHEN status = :aktif
                                  THEN 1 ELSE 0 END), 0) AS jumlah_aktif,
                COALESCE(SUM(CASE WHEN status = :lunas
                                  THEN 1 ELSE 0 END), 0) AS jumlah_lunas,
                COALESCE(SUM(CASE WHEN status = :aktif
                                  AND jatuh_tempo IS NOT NULL
                                  AND jatuh_tempo < :hari_ini
                                  THEN 1 ELSE 0 END), 0) AS jumlah_telat
            FROM debts
            WHERE chat_id = :chat_id
            """,
            {
                "piutang": TIPE_PIUTANG,
                "utang": TIPE_UTANG,
                "aktif": STATUS_AKTIF,
                "lunas": STATUS_LUNAS,
                "hari_ini": hari_ini,
                "chat_id": chat_id,
            },
        ).fetchone()
        # Jumlahkan semua pembayaran lewat relasi ke catatan pemilik.
        bayar = con.execute(
            """
            SELECT COALESCE(SUM(p.jumlah), 0) AS total
            FROM payments p
            JOIN debts d ON d.id = p.debt_id
            WHERE d.chat_id = ?
            """,
            (chat_id,),
        ).fetchone()

    piutang = int(row["piutang_aktif"])
    utang = int(row["utang_aktif"])
    # Kembalikan angka siap pakai untuk kartu ringkasan dashboard.
    return {
        "piutang_aktif": piutang,
        "utang_aktif": utang,
        "total_sisa": int(row["total_sisa"]),
        "saldo_bersih": piutang - utang,
        "jumlah_aktif": int(row["jumlah_aktif"]),
        "jumlah_lunas": int(row["jumlah_lunas"]),
        "jumlah_telat": int(row["jumlah_telat"]),
        "total_dibayar": int(bayar["total"]),
    }


def sisa_per_nama(chat_id: int, path: str | Path = DB_PATH) -> list[dict]:
    """Ambil total sisa aktif per nama dan tipe untuk grafik batang."""
    with koneksi(path) as con:
        rows = con.execute(
            """
            SELECT nama, tipe, SUM(sisa) AS sisa, COUNT(*) AS jumlah
            FROM debts
            WHERE chat_id = ? AND status = ?
            GROUP BY nama, tipe
            ORDER BY sisa DESC, nama
            """,
            (chat_id, STATUS_AKTIF),
        ).fetchall()
    # Ubah hasil agregat menjadi list dictionary yang mudah dikirim ke web.
    return [
        {
            "nama": row["nama"],
            "tipe": row["tipe"],
            "sisa": int(row["sisa"]),
            "jumlah": int(row["jumlah"]),
        }
        for row in rows
    ]


def pembayaran_per_bulan(
    chat_id: int, bulan: int = 12, path: str | Path = DB_PATH
) -> list[dict]:
    """Ambil total pembayaran per bulan, termasuk bulan tanpa pembayaran."""
    daftar_bulan = _bulan_terakhir(bulan)
    with koneksi(path) as con:
        rows = con.execute(
            """
            SELECT substr(p.tanggal, 1, 7) AS bulan, SUM(p.jumlah) AS total
            FROM payments p
            JOIN debts d ON d.id = p.debt_id
            WHERE d.chat_id = ? AND substr(p.tanggal, 1, 7) >= ?
            GROUP BY bulan
            """,
            (chat_id, daftar_bulan[0]),
        ).fetchall()
    total_per_bulan = {row["bulan"]: int(row["total"]) for row in rows}
    # Lengkapi bulan yang kosong dengan nilai nol agar grafik tetap rapi.
    return [
        {"bulan": nama_bulan, "total": total_per_bulan.get(nama_bulan, 0)}
        for nama_bulan in daftar_bulan
    ]


def pembayaran_terbaru(
    chat_id: int, limit: int = 10, path: str | Path = DB_PATH
) -> list[dict]:
    """Ambil pembayaran terbaru milik satu pengguna."""
    limit = max(1, min(int(limit), 100))
    with koneksi(path) as con:
        rows = con.execute(
            """
            SELECT p.id, p.debt_id, p.jumlah, p.tanggal, d.nama, d.tipe
            FROM payments p
            JOIN debts d ON d.id = p.debt_id
            WHERE d.chat_id = ?
            ORDER BY p.tanggal DESC, p.id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        ).fetchall()
    # Sertakan nama catatan agar pembayaran mudah dikenali di dashboard.
    return [
        {
            "id": row["id"],
            "debt_id": row["debt_id"],
            "jumlah": row["jumlah"],
            "tanggal": date.fromisoformat(row["tanggal"]),
            "nama": row["nama"],
            "tipe": row["tipe"],
        }
        for row in rows
    ]


def jatuh_tempo_terdekat(
    chat_id: int, hari: int = 30, path: str | Path = DB_PATH
) -> list[Debt]:
    """Ambil catatan aktif yang jatuh tempo dalam beberapa hari ke depan."""
    hari_ini = date.today()
    batas = hari_ini + timedelta(days=max(0, int(hari)))
    with koneksi(path) as con:
        rows = con.execute(
            """
            SELECT * FROM debts
            WHERE chat_id = ? AND status = ? AND jatuh_tempo IS NOT NULL
              AND jatuh_tempo >= ? AND jatuh_tempo <= ?
            ORDER BY jatuh_tempo, id
            """,
            (
                chat_id,
                STATUS_AKTIF,
                hari_ini.isoformat(),
                batas.isoformat(),
            ),
        ).fetchall()
    return [_debt_dari_row(row) for row in rows]


def catatan_telat(chat_id: int, path: str | Path = DB_PATH) -> list[Debt]:
    """Ambil catatan aktif yang sudah melewati jatuh tempo."""
    with koneksi(path) as con:
        rows = con.execute(
            """
            SELECT * FROM debts
            WHERE chat_id = ? AND status = ? AND jatuh_tempo IS NOT NULL
              AND jatuh_tempo < ?
            ORDER BY jatuh_tempo, id
            """,
            (chat_id, STATUS_AKTIF, date.today().isoformat()),
        ).fetchall()
    return [_debt_dari_row(row) for row in rows]
