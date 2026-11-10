"""Dashboard web read-only untuk Bot Utang-Piutang."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Any, Callable

from dotenv import load_dotenv
from flask import (
    Flask,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import database as db
import logika
import web_auth

# Nama cookie dibuat khusus agar tidak bentrok dengan aplikasi lain.
NAMA_COOKIE = "utangpiutang_session"


# Fungsi ini mengubah tanggal database menjadi teks ISO untuk JSON.
def _tanggal_iso(nilai: date | None) -> str | None:
    """Kembalikan tanggal ISO, atau None bila tanggal kosong."""
    return nilai.isoformat() if nilai is not None else None


# Catatan dikirim ke browser tanpa chat_id agar data pemilik tidak bocor.
def _debt_json(debt: db.Debt, hari_ini: date) -> dict[str, Any]:
    """Ubah satu catatan menjadi dictionary JSON untuk dashboard."""
    return {
        "id": debt["id"],
        "tipe": debt["tipe"],
        "nama": debt["nama"],
        "jumlah": debt["jumlah"],
        "sisa": debt["sisa"],
        "catatan": debt["catatan"],
        "tgl_dibuat": _tanggal_iso(debt["tgl_dibuat"]),
        "jatuh_tempo": _tanggal_iso(debt["jatuh_tempo"]),
        "status": debt["status"],
        "telat_hari": logika.hari_terlambat(debt["jatuh_tempo"], hari_ini),
    }


# Pembayaran juga dikirim dengan tanggal ISO agar mudah diformat di JavaScript.
def _pembayaran_json(pembayaran: dict) -> dict[str, Any]:
    """Ubah satu pembayaran menjadi dictionary JSON."""
    return {
        "id": pembayaran["id"],
        "debt_id": pembayaran["debt_id"],
        "jumlah": pembayaran["jumlah"],
        "tanggal": _tanggal_iso(pembayaran["tanggal"]),
        "nama": pembayaran.get("nama"),
        "tipe": pembayaran.get("tipe"),
    }


# Decorator ini memastikan hanya pengguna yang punya sesi valid bisa masuk.
def butuh_login(view: Callable) -> Callable:
    """Batasi route hanya untuk pengguna yang sudah login lewat bot."""
    @wraps(view)
    def pembungkus(*args: Any, **kwargs: Any):
        chat_id = session.get("chat_id")
        if chat_id is None:
            # API mengembalikan JSON agar JavaScript bisa menangani sesi habis.
            if request.path.startswith("/api/"):
                return jsonify({"error": "Sesi tidak ditemukan."}), 401
            return render_template(
                "error.html",
                judul="Belum masuk",
                pesan=(
                    "Buka Telegram, kirim /web ke bot, lalu klik tombol "
                    "Buka Dashboard."
                ),
            ), 403

        # Pastikan pengguna masih terdaftar di database.
        if db.ambil_user(int(chat_id), path=current_app.config["DB_PATH"]) is None:
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "Pengguna tidak ditemukan."}), 401
            return render_template(
                "error.html",
                judul="Pengguna tidak ditemukan",
                pesan="Kirim /start ke bot terlebih dahulu, lalu coba /web lagi.",
            ), 403

        return view(*args, **kwargs)

    return pembungkus


# Factory dipakai oleh tes dan oleh waitress-serve --call web:create_app.
def create_app(
    db_path: str | None = None,
    secret_key: str | None = None,
) -> Flask:
    """Rakit aplikasi Flask, database, sesi, dan seluruh route dashboard."""
    load_dotenv()
    secret = secret_key or os.getenv("SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "SECRET_KEY belum diisi. Tambahkan SECRET_KEY ke file .env."
        )

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=secret,
        DB_PATH=str(db_path or os.getenv("DB_PATH", db.DB_PATH)),
        SESSION_COOKIE_NAME=NAMA_COOKIE,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    )
    # Pastikan tabel dan mode WAL siap sebelum route dipakai.
    db.siapkan(app.config["DB_PATH"])

    # Header dasar ini mengurangi risiko sniffing dan pembukaan di iframe.
    @app.after_request
    def tambah_header_aman(response):
        """Tambahkan header keamanan dasar pada setiap respons."""
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.get("/")
    def index():
        """Arahkan pengguna yang sudah login ke dashboard."""
        if session.get("chat_id") is not None:
            return redirect(url_for("dashboard"))
        return render_template(
            "error.html",
            judul="Dashboard Utang-Piutang",
            pesan=(
                "Dashboard dibuka lewat link dari bot. Kirim /web di chat "
                "pribadi bot, lalu klik tombol Buka Dashboard."
            ),
        ), 403

    @app.get("/auth/<token>")
    def auth(token: str):
        """Verifikasi token dari bot lalu buat sesi dashboard."""
        chat_id = web_auth.verifikasi_token(
            token, secret=current_app.config["SECRET_KEY"]
        )
        if chat_id is None:
            return render_template(
                "error.html",
                judul="Link tidak valid",
                pesan=(
                    "Link dashboard sudah kadaluarsa atau tidak sah. "
                    "Kirim /web lagi ke bot untuk membuat link baru."
                ),
            ), 403

        user = db.ambil_user(chat_id, path=current_app.config["DB_PATH"])
        if user is None:
            return render_template(
                "error.html",
                judul="Pengguna tidak ditemukan",
                pesan="Kirim /start ke bot terlebih dahulu, lalu coba /web lagi.",
            ), 403

        session.clear()
        session["chat_id"] = chat_id
        session["nama"] = user["nama"] or "Pengguna"
        session.permanent = True

        # Redirect 303 menghilangkan token dari address bar setelah login.
        respons = redirect(url_for("dashboard"), code=303)
        respons.headers["Referrer-Policy"] = "no-referrer"
        respons.headers["Cache-Control"] = "no-store"
        return respons

    @app.get("/dashboard")
    @butuh_login
    def dashboard():
        """Tampilkan halaman utama dashboard."""
        return render_template(
            "dashboard.html",
            nama=session.get("nama") or "Pengguna",
        )

    @app.get("/logout")
    def logout():
        """Hapus sesi lalu kembali ke halaman awal."""
        session.clear()
        return redirect(url_for("index"))

    @app.get("/api/dashboard")
    @butuh_login
    def api_dashboard():
        """Kirim semua data dashboard milik pengguna yang sedang login."""
        chat_id = int(session["chat_id"])
        hari_ini = date.today()
        path = current_app.config["DB_PATH"]
        catatan = db.daftar_debt(chat_id, status=None, path=path)
        return jsonify(
            {
                "ringkasan": db.ringkasan_web(chat_id, path=path),
                "catatan": [_debt_json(item, hari_ini) for item in catatan],
                "grafik": {
                    "per_nama": db.sisa_per_nama(chat_id, path=path),
                    "bulanan": db.pembayaran_per_bulan(chat_id, path=path),
                },
                "pembayaran_terbaru": [
                    _pembayaran_json(item)
                    for item in db.pembayaran_terbaru(chat_id, path=path)
                ],
                "jatuh_tempo": [
                    _debt_json(item, hari_ini)
                    for item in db.jatuh_tempo_terdekat(chat_id, path=path)
                ],
                "telat": [
                    _debt_json(item, hari_ini)
                    for item in db.catatan_telat(chat_id, path=path)
                ],
                "diperbarui": datetime.now().isoformat(timespec="seconds"),
            }
        )

    @app.get("/api/debts/<int:debt_id>")
    @butuh_login
    def api_debt(debt_id: int):
        """Kirim detail satu catatan beserta riwayat pembayarannya."""
        chat_id = int(session["chat_id"])
        path = current_app.config["DB_PATH"]
        debt = db.ambil_debt(chat_id, debt_id, path=path)
        if debt is None:
            return jsonify({"error": "Catatan tidak ditemukan."}), 404

        return jsonify(
            {
                "catatan": _debt_json(debt, date.today()),
                "pembayaran": [
                    _pembayaran_json(item)
                    for item in db.riwayat_pembayaran(
                        chat_id, debt_id, path=path
                    )
                ],
                "total_dibayar": db.total_pembayaran(
                    chat_id, debt_id, path=path
                ),
            }
        )

    return app


def main() -> None:
    """Jalankan server dashboard untuk akses LAN."""
    load_dotenv()
    app = create_app()
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8000"))
    print(f"Dashboard berjalan di http://{web_auth.ip_lan()}:{port}")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
