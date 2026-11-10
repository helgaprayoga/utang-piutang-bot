"""Bot Utang-Piutang multi-pengguna: pencatat utang/piutang di Telegram.

Setiap pengguna hanya melihat dan mengubah catatannya sendiri. Bot hanya
melayani chat pribadi agar data tidak terlihat oleh anggota chat lain.

Perintah saat ini:
  /start    sambutan + daftar pengguna
  /piutang  catat piutang (orang lain utang ke kita)
  /utang    catat utang (kita utang ke orang lain)
  /daftar   lihat semua catatan aktif milik sendiri
  /lunas    tandai satu catatan lunas
  /web      buka dashboard web di browser
  /menu     tampilkan tombol menu
  /bantuan  daftar perintah

Jalankan: python bot.py  (hentikan dengan Ctrl+C)
"""

from __future__ import annotations

import logging
import os
import socket
import threading

from dotenv import load_dotenv
from telegram import (
    BotCommand,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import database as db
import logika
import web_auth

# Siapkan logging agar aktivitas bot mudah dilacak.
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("utangpiutangbot")

# Teks bantuan dipakai oleh /start dan /bantuan.
BANTUAN = (
    "Bot ini bisa dipakai siapa saja. Data tiap orang disimpan terpisah "
    "dan cuma bisa diakses dari chat pribadinya.\n\n"
    "Perintah Bot Utang-Piutang:\n\n"
    "/piutang <nama> <jumlah> [catatan] [dd/mm]\n"
    "  Catat orang lain utang ke kamu.\n"
    "  Contoh: /piutang Budi 50000 makan siang 20/11\n\n"
    "/utang <nama> <jumlah> [catatan] [dd/mm]\n"
    "  Catat utangmu ke orang lain.\n"
    "  Contoh: /utang Ani 30000 kopi\n\n"
    "/daftar — lihat semua catatan aktifmu\n"
    "/lunas <id> — tandai catatan lunas\n"
    "/web — buka dashboard di browser\n"
    "/menu — tampilkan tombol menu\n"
    "/bantuan — bantuan ini\n\n"
    "Jumlah bisa 50000, 50.000, atau 50rb.\n"
    "Tanggal boleh dd/mm atau dd/mm/yyyy."
)

# Tombol menu berisi perintah agar pengguna tidak perlu mengetik manual.
MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("/piutang"), KeyboardButton("/utang")],
        [KeyboardButton("/daftar"), KeyboardButton("/lunas")],
        [KeyboardButton("/web"), KeyboardButton("/bantuan")],
        [KeyboardButton("/menu")],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Pilih menu...",
)

# Pesan ini dikirim saat bot dipanggil dari chat grup.
PESAN_CHAT_PRIBADI = (
    "Bot ini cuma bisa dipakai di chat pribadi. "
    "Chat aku langsung (DM) ya, biar datamu nggak kelihatan orang lain."
)


# Fungsi ini memvalidasi chat pribadi sekaligus mendaftarkan pengguna.
async def _siapkan_pengguna(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int | None:
    """Tolak chat non-pribadi, daftarkan pengguna, lalu kembalikan chat_id."""
    chat = update.effective_chat
    pesan = update.effective_message
    if chat is None or pesan is None:
        return None

    # Tolak chat grup agar data pengguna tidak terlihat orang lain.
    if chat.type != Chat.PRIVATE:
        await pesan.reply_text(PESAN_CHAT_PRIBADI)
        return None

    # Simpan pengguna baru atau perbarui nama yang sudah terdaftar.
    nama = update.effective_user.full_name if update.effective_user else None
    db.daftar_atau_buat_user(
        chat.id, nama=nama, path=context.bot_data["db"]
    )
    return chat.id


# Bagian ini berisi handler untuk setiap perintah Telegram.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sambut pengguna baru dan tampilkan daftar perintah."""
    # Pastikan pengguna valid sebelum mengirim sambutan.
    chat_id = await _siapkan_pengguna(update, context)
    if chat_id is None:
        return

    # Ambil nama depan untuk sapaan yang lebih akrab.
    nama = (
        update.effective_user.first_name
        if update.effective_user and update.effective_user.first_name
        else "kamu"
    )
    log.info("Pengguna /start: chat_id=%s", chat_id)

    # Kirim sambutan beserta daftar perintah.
    await update.effective_message.reply_text(
        f"Halo, {nama}! Aku Bot Utang-Piutang.\n"
        "Aku bantu catat piutang, utang, dan pengingatnya.\n\n" + BANTUAN,
        reply_markup=MENU_KEYBOARD,
    )


async def bantuan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tampilkan daftar perintah dan contoh pemakaian."""
    # Hentikan proses bila pengguna tidak lolos validasi chat pribadi.
    if await _siapkan_pengguna(update, context) is None:
        return
    # Tampilkan daftar perintah dan contoh pemakaian.
    await update.effective_message.reply_text(BANTUAN)


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tampilkan tombol menu berisi perintah yang sering dipakai."""
    # Pastikan pengguna valid sebelum menampilkan menu.
    if await _siapkan_pengguna(update, context) is None:
        return
    await update.effective_message.reply_text(
        "Pilih menu yang kamu butuhkan. Tombol berisi perintah yang bisa "
        "langsung dikirim.",
        reply_markup=MENU_KEYBOARD,
    )


async def _tambah_catatan(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    tipe: str,
) -> None:
    """Parse argumen lalu simpan piutang/utang milik chat_id."""
    # Pilih contoh perintah sesuai jenis catatan.
    contoh = (
        "/piutang Budi 50000 makan siang 20/11"
        if tipe == db.TIPE_PIUTANG
        else "/utang Ani 30000 kopi 25/12"
    )
    # Parse argumen dan tangani input yang tidak valid.
    try:
        data = logika.parse_debt(context.args)
    except ValueError as exc:
        await update.effective_message.reply_text(
            f"{exc}\n\nContoh yang benar:\n{contoh}"
        )
        return

    # Simpan catatan ke database milik pengguna ini.
    debt_id = db.tambah_debt(
        chat_id=chat_id,
        tipe=tipe,
        nama=str(data["nama"]),
        jumlah=int(data["jumlah"]),
        catatan=data["catatan"],
        jatuh_tempo=data["jatuh_tempo"],
        path=context.bot_data["db"],
    )
    log.info(
        "Pengguna %s menambah %s #%s: %s %s",
        chat_id,
        tipe,
        debt_id,
        data["nama"],
        data["jumlah"],
    )

    # Susun kalimat pembuka sesuai jenis catatan.
    if tipe == db.TIPE_PIUTANG:
        pembuka = f"Siap! Piutang dari {data['nama']} sudah dicatat."
    else:
        pembuka = f"Oke, utang ke {data['nama']} sudah dicatat."

    # Kumpulkan rincian yang akan ditampilkan ke pengguna.
    rincian = [
        pembuka,
        f"Jumlah: {logika.format_rupiah(int(data['jumlah']))}",
    ]
    # Tambahkan jatuh tempo bila pengguna mengisinya.
    if data["jatuh_tempo"] is not None:
        rincian.append(
            f"Jatuh tempo: {logika.format_tanggal(data['jatuh_tempo'])}"
        )
    # Tambahkan catatan bila pengguna mengisinya.
    if data["catatan"]:
        rincian.append(f"Catatan: {data['catatan']}")
    # Beri tahu ID agar pengguna bisa memakai /lunas.
    rincian.append(
        f"ID: {debt_id} · pakai /lunas {debt_id} kalau sudah dibayar penuh."
    )
    await update.effective_message.reply_text("\n".join(rincian))


async def piutang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /piutang."""
    # Validasi pengguna lalu catat piutang baru.
    chat_id = await _siapkan_pengguna(update, context)
    if chat_id is None:
        return
    await _tambah_catatan(update, context, chat_id, db.TIPE_PIUTANG)


async def utang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /utang."""
    # Validasi pengguna lalu catat utang baru.
    chat_id = await _siapkan_pengguna(update, context)
    if chat_id is None:
        return
    await _tambah_catatan(update, context, chat_id, db.TIPE_UTANG)


async def daftar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tampilkan semua catatan aktif milik pengguna."""
    # Pastikan pengguna valid sebelum mengambil data.
    chat_id = await _siapkan_pengguna(update, context)
    if chat_id is None:
        return

    # Ambil hanya catatan aktif milik pengguna ini.
    debts = db.daftar_debt(
        chat_id=chat_id,
        status=db.STATUS_AKTIF,
        path=context.bot_data["db"],
    )
    # Kirim hasil dalam format daftar yang mudah dibaca.
    await update.effective_message.reply_text(logika.format_daftar(debts))


async def lunas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tandai catatan milik pengguna sebagai lunas."""
    # Pastikan pengguna valid sebelum memproses ID.
    chat_id = await _siapkan_pengguna(update, context)
    if chat_id is None:
        return

    # Validasi jumlah argumen yang diberikan.
    if len(context.args) != 1:
        await update.effective_message.reply_text(
            "Format: /lunas <id>\nContoh: /lunas 1"
        )
        return

    # Pastikan ID berupa angka positif.
    try:
        debt_id = int(context.args[0])
        if debt_id <= 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text(
            "ID harus angka positif.\nContoh: /lunas 1"
        )
        return

    # Proses pelunasan hanya untuk catatan milik pengguna ini.
    hasil = db.lunaskan(
        chat_id=chat_id,
        debt_id=debt_id,
        path=context.bot_data["db"],
    )
    # Beri pesan khusus bila catatan tidak ditemukan.
    if hasil["hasil"] == "tidak_ada":
        await update.effective_message.reply_text(
            f"Catatan dengan ID {debt_id} nggak ketemu di daftarmu. "
            "Cek /daftar ya."
        )
        return

    # Beri pesan khusus bila catatan sudah lunas.
    if hasil["hasil"] == "sudah_lunas":
        await update.effective_message.reply_text(
            f"Catatan #{debt_id} sudah lunas dari sebelumnya."
        )
        return

    debt = hasil["debt"]
    dibayar = logika.format_rupiah(int(hasil["dibayar"]))
    # Catat aktivitas pelunasan ke log.
    log.info(
        "Pengguna %s melunaskan catatan #%s (%s)",
        chat_id,
        debt_id,
        dibayar,
    )
    # Kirim konfirmasi pelunasan kepada pengguna.
    await update.effective_message.reply_text(
        f"{debt['nama']} — {debt['tipe']} #{debt_id} sudah ditandai lunas.\n"
        f"Sisa {dibayar} dicatat sebagai pembayaran terakhir. Mantap!"
    )


def _port_web_terbuka() -> bool:
    """Periksa apakah server dashboard benar-benar menerima koneksi."""
    try:
        port = int(os.getenv("WEB_PORT", "8000"))
    except ValueError:
        return False
    host = os.getenv("WEB_HOST", "0.0.0.0")
    alamat = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    try:
        with socket.create_connection((alamat, port), timeout=0.5):
            return True
    except OSError:
        return False


async def web(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kirim tautan dashboard web yang hanya bisa dibuka di jaringan lokal."""
    # Pastikan pengguna valid dan sudah terdaftar.
    chat_id = await _siapkan_pengguna(update, context)
    if chat_id is None:
        return

    # Jangan kirim link mati bila server web belum menyala.
    if not _port_web_terbuka():
        await update.effective_message.reply_text(
            "Dashboard web belum aktif.\n\n"
            "Jalankan ulang bot.py dan pastikan port 8000 tidak dipakai "
            "aplikasi lain. Kalau memakai proses web terpisah, jalankan "
            "web.py terlebih dahulu."
        )
        return

    try:
        # Token dibuat dari SECRET_KEY dan berlaku selama 30 menit.
        tautan = web_auth.tautan_dashboard(
            chat_id, secret=os.getenv("SECRET_KEY")
        )
    except RuntimeError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    # Tombol inline memudahkan pengguna membuka dashboard dari Telegram.
    papan = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Buka Dashboard", url=tautan)]]
    )
    log.info("Pengguna %s meminta tautan dashboard web", chat_id)
    await update.effective_message.reply_text(
        "Dashboard web kamu sudah siap.\n\n"
        "Buka dari HP atau laptop yang terhubung ke Wi-Fi yang sama "
        "dengan komputer server.\n"
        "Link berlaku 30 menit dan dashboard aktif selama bot berjalan.\n\n"
        "Kalau HP tidak bisa membuka, jaringan kampus seperti eduroam "
        "sering memblokir akses antarperangkat. Gunakan hotspot HP/laptop, "
        "lalu atur WEB_BASE_URL di .env sesuai IP hotspot.\n\n"
        f"{tautan}",
        reply_markup=papan,
        disable_web_page_preview=True,
    )


async def teks_biasa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Balas pesan teks biasa; diam saja bila bot dipakai di grup."""
    # Abaikan pesan dari grup agar bot tidak berisik.
    chat = update.effective_chat
    if chat is None or chat.type != Chat.PRIVATE:
        return
    # Beri arahan singkat untuk pesan bebas.
    await update.effective_message.reply_text(
        "Aku belum ngerti pesan bebas. Ketik /bantuan untuk lihat perintah."
    )


async def perintah_tak_dikenal(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Balas perintah yang tidak terdaftar."""
    # Abaikan update yang tidak memiliki chat.
    chat = update.effective_chat
    if chat is None:
        return
    # Arahkan pengguna grup ke chat pribadi.
    if chat.type != Chat.PRIVATE:
        await update.effective_message.reply_text(PESAN_CHAT_PRIBADI)
        return
    # Beri tahu bahwa perintah belum tersedia.
    await update.effective_message.reply_text(
        "Perintah itu belum ada. Ketik /bantuan ya."
    )


async def saat_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catat error di log dan kirim pesan ramah ke pengguna."""
    # Catat detail error ke log untuk investigasi.
    log.error("Error saat memproses update", exc_info=context.error)
    # Kirim pesan ramah bila update masih bisa dibalas.
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "Maaf, terjadi kesalahan. Coba lagi sebentar lagi ya."
        )


async def setelah_mulai(app: Application) -> None:
    """Dijalankan sekali saat bot menyala: pasang menu perintah Telegram."""
    # Daftarkan menu perintah agar muncul di aplikasi Telegram.
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Mulai dan lihat daftar perintah"),
            BotCommand("menu", "Tampilkan tombol menu"),
            BotCommand("piutang", "Catat piutang baru"),
            BotCommand("utang", "Catat utang baru"),
            BotCommand("daftar", "Lihat catatan aktif"),
            BotCommand("lunas", "Tandai catatan lunas"),
            BotCommand("web", "Buka dashboard di browser"),
            BotCommand("bantuan", "Bantuan dan contoh"),
        ]
    )


def buat_aplikasi(token: str, db_path: str = db.DB_PATH) -> Application:
    """Rakit Application beserta semua handler (dipisah agar mudah diuji)."""
    app = Application.builder().token(token).post_init(setelah_mulai).build()
    app.bot_data["db"] = db_path
    # Siapkan database sebelum handler dipasang.
    db.siapkan(db_path)

    # Daftarkan seluruh handler perintah dan pesan.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("bantuan", bantuan))
    app.add_handler(CommandHandler("piutang", piutang))
    app.add_handler(CommandHandler("utang", utang))
    app.add_handler(CommandHandler("daftar", daftar))
    app.add_handler(CommandHandler("lunas", lunas))
    app.add_handler(CommandHandler("web", web))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, teks_biasa))
    app.add_handler(MessageHandler(filters.COMMAND, perintah_tak_dikenal))
    app.add_error_handler(saat_error)
    return app


def _web_diaktifkan() -> bool:
    """Periksa apakah dashboard web harus ikut dijalankan."""
    nilai = os.getenv("WEB_ENABLED", "1").strip().lower()
    return nilai not in {"0", "false", "no", "off"}


def mulai_web_latar() -> None:
    """Jalankan dashboard web di thread latar agar cukup satu perintah."""
    if not _web_diaktifkan():
        log.info("Dashboard web dimatikan lewat WEB_ENABLED.")
        return

    try:
        # Import dilakukan di sini agar tes bot tidak membutuhkan Flask.
        from waitress import serve

        from web import create_app

        aplikasi = create_app()
    except Exception:
        log.exception(
            "Dashboard web gagal disiapkan. Bot tetap berjalan tanpa web."
        )
        return

    host = os.getenv("WEB_HOST", "0.0.0.0")
    try:
        port = int(os.getenv("WEB_PORT", "8000"))
    except ValueError:
        log.error("WEB_PORT harus berupa angka. Dashboard web dimatikan.")
        return

    def jalankan_server() -> None:
        try:
            # Waitress menangani banyak permintaan tanpa mode debug Flask.
            serve(aplikasi, host=host, port=port)
        except Exception:
            log.exception(
                "Dashboard web gagal berjalan. Mungkin port %s sudah dipakai.",
                port,
            )

    threading.Thread(
        target=jalankan_server,
        name="dashboard-web",
        daemon=True,
    ).start()
    log.info("Dashboard web aktif di %s", web_auth.base_url())


def main() -> None:
    """Baca token dari .env lalu jalankan bot."""
    # Baca token dari file .env.
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    # Hentikan proses bila token belum tersedia.
    if not token:
        raise SystemExit(
            "BOT_TOKEN belum diisi. Salin .env.example menjadi .env "
            "lalu isi token dari BotFather."
        )
    app = buat_aplikasi(token)
    # Dashboard web ikut menyala bersama bot agar /web langsung bisa dipakai.
    mulai_web_latar()
    log.info("Bot berjalan. Tekan Ctrl+C untuk berhenti.")
    # Jalankan bot dengan mode polling.
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
