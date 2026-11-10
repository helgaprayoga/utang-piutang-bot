"""Tes token login dan alamat dashboard web."""

import time
from unittest.mock import patch

import web_auth

SECRET = "rahasia-uji-web"


# Token yang baru dibuat harus bisa dibaca kembali.
def test_token_bolak_balik():
    token = web_auth.buat_token(123, secret=SECRET)

    assert web_auth.verifikasi_token(token, secret=SECRET) == 123


# Token yang diubah harus ditolak.
def test_token_diubah_ditolak():
    token = web_auth.buat_token(123, secret=SECRET)

    assert web_auth.verifikasi_token(token + "x", secret=SECRET) is None
    assert web_auth.verifikasi_token("token-palsu", secret=SECRET) is None


# Token yang melewati batas umur harus ditolak.
def test_token_kadaluarsa_ditolak():
    token = web_auth.buat_token(123, secret=SECRET)
    sekarang = time.time()

    with patch("time.time", return_value=sekarang + 2000):
        assert (
            web_auth.verifikasi_token(token, max_age=1800, secret=SECRET)
            is None
        )


# WEB_BASE_URL harus menimpa deteksi IP otomatis.
def test_base_url_memakai_override(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "http://192.168.1.9:8000/")

    assert web_auth.base_url() == "http://192.168.1.9:8000"
    tautan = web_auth.tautan_dashboard(123, secret=SECRET)
    assert tautan.startswith("http://192.168.1.9:8000/auth/")


# Tanpa SECRET_KEY, pembuatan token harus gagal dengan pesan jelas.
def test_secret_key_wajib_ada(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)

    try:
        web_auth.buat_token(123)
    except RuntimeError as exc:
        assert "SECRET_KEY" in str(exc)
    else:
        raise AssertionError("RuntimeError tidak muncul")
