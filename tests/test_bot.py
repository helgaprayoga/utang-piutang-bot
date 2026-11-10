"""Tes gerbang akses bot: chat pribadi didaftarkan, grup ditolak."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import bot
import database as db
import web_auth


# Buat objek tiruan Telegram agar handler bisa diuji tanpa jaringan.
def buat_update(chat_id=123, tipe_chat="private"):
    pesan = SimpleNamespace(reply_text=AsyncMock())
    chat = SimpleNamespace(id=chat_id, type=tipe_chat)
    user = SimpleNamespace(full_name="Pengguna Uji")
    update = SimpleNamespace(
        effective_chat=chat,
        effective_message=pesan,
        effective_user=user,
    )
    return update, pesan


# Context tiruan hanya menyediakan path database yang dibutuhkan.
def buat_context(path):
    return SimpleNamespace(bot_data={"db": str(path)})


# Pengguna dari chat pribadi harus otomatis terdaftar.
def test_chat_pribadi_didaftarkan(tmp_path):
    path = tmp_path / "data.db"
    db.siapkan(path)
    update, pesan = buat_update()

    hasil = asyncio.run(bot._siapkan_pengguna(update, buat_context(path)))

    assert hasil == 123
    user = db.ambil_user(123, path=path)
    assert user is not None
    assert user["nama"] == "Pengguna Uji"
    pesan.reply_text.assert_not_awaited()


# Pengguna dari grup harus ditolak tanpa menyimpan data.
def test_chat_grup_ditolak_tanpa_data(tmp_path):
    path = tmp_path / "data.db"
    db.siapkan(path)
    update, pesan = buat_update(chat_id=-100, tipe_chat="group")

    hasil = asyncio.run(bot._siapkan_pengguna(update, buat_context(path)))

    assert hasil is None
    assert db.ambil_user(-100, path=path) is None
    pesan.reply_text.assert_awaited_once()
    assert "chat pribadi" in pesan.reply_text.await_args.args[0]

# Command /web harus mengirim tombol berisi token dashboard yang valid.
def test_web_mengirim_tautan_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "rahasia-uji-web")
    monkeypatch.setenv("WEB_BASE_URL", "http://192.168.1.9:8000")
    monkeypatch.setattr(bot, "_port_web_terbuka", lambda: True)
    path = tmp_path / "data.db"
    db.siapkan(path)
    update, pesan = buat_update()

    asyncio.run(bot.web(update, buat_context(path)))

    pesan.reply_text.assert_awaited_once()
    teks = pesan.reply_text.await_args.args[0]
    assert "http://192.168.1.9:8000/auth/" in teks
    papan = pesan.reply_text.await_args.kwargs["reply_markup"]
    tautan = papan.inline_keyboard[0][0].url
    assert tautan.startswith("http://192.168.1.9:8000/auth/")
    token = tautan.rsplit("/", 1)[-1]
    assert web_auth.verifikasi_token(token, secret="rahasia-uji-web") == 123

# Command /menu harus mengirim tombol berisi daftar perintah.
def test_menu_mengirim_keyboard(tmp_path):
    path = tmp_path / "data.db"
    db.siapkan(path)
    update, pesan = buat_update()

    asyncio.run(bot.menu(update, buat_context(path)))

    pesan.reply_text.assert_awaited_once()
    papan = pesan.reply_text.await_args.kwargs["reply_markup"]
    teks = [tombol.text for baris in papan.keyboard for tombol in baris]
    assert "/piutang" in teks
    assert "/utang" in teks
    assert "/daftar" in teks
    assert "/lunas" in teks
    assert "/web" in teks
    assert "/bantuan" in teks
    assert "/menu" in teks


# Saklar WEB_ENABLED harus bisa mematikan dashboard web.
def test_web_diaktifkan_dari_env(monkeypatch):
    monkeypatch.setenv("WEB_ENABLED", "0")
    assert bot._web_diaktifkan() is False

    monkeypatch.setenv("WEB_ENABLED", "1")
    assert bot._web_diaktifkan() is True

# /web harus memberi pesan jelas bila server web belum menyala.
def test_web_memberi_tahu_bila_server_mati(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "_port_web_terbuka", lambda: False)
    path = tmp_path / "data.db"
    db.siapkan(path)
    update, pesan = buat_update()

    asyncio.run(bot.web(update, buat_context(path)))

    pesan.reply_text.assert_awaited_once()
    teks = pesan.reply_text.await_args.args[0]
    assert "belum aktif" in teks
