"""Token dan alamat lokal untuk login dashboard web."""

from __future__ import annotations

import os
import socket

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# Salt memisahkan token login web dari token lain yang memakai SECRET_KEY sama.
SALT_LOGIN = "web-login"
TOKEN_MAX_AGE = 1800


# Fungsi ini mengambil kunci rahasia dari environment.
def _secret(secret: str | None = None) -> str:
    """Kembalikan SECRET_KEY atau hentikan proses bila belum diisi."""
    nilai = secret or os.getenv("SECRET_KEY")
    if not nilai:
        raise RuntimeError(
            "SECRET_KEY belum diisi. Tambahkan SECRET_KEY ke file .env."
        )
    return nilai


# Serializer ini membuat dan membaca token login bertanda tangan.
def buat_serializer(secret: str | None = None) -> URLSafeTimedSerializer:
    """Buat serializer token login dengan kunci rahasia aplikasi."""
    return URLSafeTimedSerializer(_secret(secret), salt=SALT_LOGIN)


# Token membawa chat_id agar dashboard tahu data siapa yang boleh dibaca.
def buat_token(chat_id: int, secret: str | None = None) -> str:
    """Buat token login berisi chat_id pengguna."""
    return buat_serializer(secret).dumps({"chat_id": int(chat_id)})


# Verifikasi mengembalikan chat_id, atau None bila token tidak sah/kadaluarsa.
def verifikasi_token(
    token: str,
    max_age: int = TOKEN_MAX_AGE,
    secret: str | None = None,
) -> int | None:
    """Baca token login dan kembalikan chat_id bila masih valid."""
    try:
        data = buat_serializer(secret).loads(token, max_age=max_age)
        return int(data["chat_id"])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None


# Alamat IP LAN dipakai agar tautan bisa dibuka dari HP di Wi-Fi yang sama.
def ip_lan() -> str:
    """Deteksi alamat IPv4 komputer di jaringan lokal."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Koneksi UDP ini tidak mengirim data, hanya memilih antarmuka aktif.
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


# WEB_BASE_URL berguna bila deteksi IP otomatis memilih antarmuka yang salah.
def base_url() -> str:
    """Kembalikan alamat dasar dashboard tanpa garis miring di akhir."""
    alamat = os.getenv("WEB_BASE_URL")
    if alamat:
        return alamat.rstrip("/")
    port = os.getenv("WEB_PORT", "8000")
    return f"http://{ip_lan()}:{port}"


# Bot memakai fungsi ini untuk membuat tombol menuju dashboard.
def tautan_dashboard(chat_id: int, secret: str | None = None) -> str:
    """Susun URL login dashboard untuk satu pengguna."""
    return f"{base_url()}/auth/{buat_token(chat_id, secret=secret)}"
