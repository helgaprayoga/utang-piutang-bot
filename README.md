# Bot Utang-Piutang

Bot Telegram untuk mencatat utang dan piutang, dengan dashboard web read-only
yang bisa dibuka dari jaringan lokal.

## Fitur

- Catat piutang dan utang lewat Telegram.
- Tandai catatan lunas.
- Data terpisah per pengguna Telegram.
- Dashboard web berisi ringkasan, grafik, tabel, dan riwayat pembayaran.
- Akses dashboard lewat link bertanda tangan dari command `/web`.
- Tombol menu `/menu` berisi perintah yang sering dipakai.
- Data dashboard diperbarui otomatis setiap 10 detik.

## Persiapan

```powershell
python -m venv venv
& ".\venv\Scripts\python.exe" -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Isi `BOT_TOKEN` dari BotFather, lalu buat `SECRET_KEY`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Contoh isi `.env`:

```env
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRstuVWXyz
SECRET_KEY=hasil_token_acak_panjang
WEB_ENABLED=1
WEB_HOST=0.0.0.0
WEB_PORT=8000
# WEB_BASE_URL=http://192.168.1.10:8000
```

## Menjalankan

Satu perintah sudah menjalankan bot dan dashboard web sekaligus:

```powershell
& ".\venv\Scripts\python.exe" bot.py
```

Setelah bot menyala, kirim `/web` ke bot. Bot akan mengirim tombol
**Buka Dashboard** berisi alamat seperti
`http://192.168.1.10:8000/auth/<token>`.

Jika ingin menjalankan web sebagai proses terpisah, set `WEB_ENABLED=0` di
`.env`, lalu jalankan:

```powershell
& ".\venv\Scripts\python.exe" bot.py
& ".\venv\Scripts\python.exe" web.py
```

Atau memakai waitress:

```powershell
& ".\venv\Scripts\waitress-serve.exe" --call --listen=0.0.0.0:8000 web:create_app
```

## Akses dari HP

- HP dan komputer server harus berada di Wi-Fi/LAN yang sama.
- Izinkan port `8000` di Windows Firewall. Jalankan PowerShell sebagai
  Administrator, lalu:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\izinkan_firewall.ps1
```

- Dashboard aktif selama `bot.py` berjalan.
- Link login berlaku 30 menit. Setelah masuk, sesi berlaku 12 jam.
- Beberapa router memakai AP isolation sehingga perangkat tidak bisa saling
  terhubung.
- Jaringan kampus seperti **eduroam** biasanya memblokir akses antarperangkat.
  Jika alamat yang dikirim bot berawalan `10.x`, gunakan hotspot HP atau
  Windows Mobile Hotspot, lalu isi `WEB_BASE_URL` dengan IP hotspot komputer,
  misalnya `http://192.168.137.1:8000`.
- Jika IP yang terdeteksi otomatis salah, isi `WEB_BASE_URL` di `.env` dengan
  alamat LAN yang benar.
- Jangan membuka port ini ke internet tanpa HTTPS.

## Pengujian

```powershell
& ".\venv\Scripts\python.exe" -m pytest -q
```

## Struktur Singkat

- `bot.py` — handler Telegram, command `/web`, `/menu`, dan server web latar.
- `database.py` — skema SQLite dan query multi-pengguna.
- `logika.py` — parsing nominal, tanggal, dan format pesan.
- `web.py` — aplikasi Flask dan API dashboard.
- `web_auth.py` — token login dan deteksi alamat LAN.
- `templates/`, `static/` — tampilan dashboard.
- `izinkan_firewall.ps1` — helper membuka port 8000 di Windows Firewall.
- `tests/` — tes database, logika, bot, auth, dan web.
