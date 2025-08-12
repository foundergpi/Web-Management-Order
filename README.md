# VPS/RDP Monitor – Web Management Order

Aplikasi web sederhana untuk **memantau VPS/RDP** (cek port TCP), **mengelola masa berlaku (expired)**, dan **mencatat penjualan/akun**. Dilengkapi **notifikasi Telegram** ketika server **DOWN** atau **EXPIRED**, serta fitur **import Excel (.xlsx)** dengan **preview** sebelum commit.

> Dibangun dengan: **Flask (Python)** + **MongoDB** + **Bootstrap 5**.

---

## ✨ Fitur Utama

- **Dashboard publik**: Tabel VPS/RDP dengan status **UP/DOWN**, sisa hari sebelum expired, dan penanda **expiring**/**expired**.
- **Admin panel** (login):
  - Tambah/Ubah/Hapus data VPS/RDP.
  - Kelola **Price List** (harga & mata uang).
  - Catat **Penjualan** (otomatis ketika tambah VPS, atau manual).
  - Kelola **Akun** (nama, merchant, tipe, qty, harga, mata uang, tanggal jual).
  - **Import dari Excel (.xlsx)**: sheet `VPS` & `AKUN` dengan mapping nama kolom yang fleksibel (pakai alias); ada **preview** sebelum commit.
- **Monitoring background**:
  - Cek **expired** berkala dan kirim **notifikasi Telegram** (sekali saat melewati masa berlaku).
  - Cek **status port** berkala dan kirim **notifikasi Telegram** saat transisi ke **DOWN**.
- **UI modern**: Bootstrap 5 + Bootstrap Icons via CDN.

---

## 🧱 Arsitektur Singkat

- **Backend**: Flask (`vps_monitor_atlas.py`).
- **DB**: MongoDB (disarankan **MongoDB Atlas**, boleh lokal).
- **Template**: Jinja2 (`templates/*.html`).
- **Threading**: 2 thread daemon
  - `monitor_expired` (interval: `CHECK_EXPIRED_SEC`, default 60 detik)
  - `monitor_status` (interval: `CHECK_INTERVAL_SEC`, default 300 detik)
- **Integrasi**: Telegram Bot API (sendMessage).

---

## 🧰 Prasyarat

- Python **3.10+**
- Pip / Virtualenv
- MongoDB (Atlas/lokal)
- **Telegram Bot Token** & **Chat ID** (untuk notifikasi)
- Akses internet keluar (untuk Telegram & CDN Bootstrap)

---

## 🗂️ Struktur Proyek (ringkas)

```
vps-monitor/
├─ vps_monitor_atlas.py        # Aplikasi Flask
└─ templates/
   ├─ base.html
   ├─ index.html               # dashboard publik
   ├─ admin_login.html
   ├─ admin_index.html         # dashboard admin (+ import preview)
   ├─ edit.html
   └─ accounts_index.html
```

---

## ⚙️ Konfigurasi

> **Penting:** Saat ini konfigurasi diset **di dalam file** `vps_monitor_atlas.py`. Demi keamanan, **ubah** nilai default dan **jangan commit secret** Anda ke publik.

Buka `vps_monitor_atlas.py`, periksa & **ganti** nilai berikut:

- `SECRET_KEY` — ganti string default untuk session Flask.
- `MONGO_URI` — string koneksi MongoDB Anda (Atlas/lokal).
- `ADMIN_USER` dan `ADMIN_PASS` — kredensial login admin (default `admin`/`123456` → **wajib ganti**).
- `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` — kredensial Telegram Anda.

> Rekomendasi: di masa depan pindahkan ke **environment variables** agar lebih aman.

---

## 📦 Instalasi

```bash
# 1) Clone dan masuk folder proyek
git clone https://github.com/<user>/<repo>.git
cd vps-monitor

# 2) Buat dan aktifkan virtualenv (opsional tapi disarankan)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3) Install dependensi
pip install flask pymongo requests pandas openpyxl
```

---

## ▶️ Menjalankan Secara Lokal

```bash
python vps_monitor_atlas.py
```
Akses:
- Halaman publik: **http://localhost:5000/**
- Halaman admin: **http://localhost:5000/admin**
  - Login: username & password sesuai yang Anda set di `vps_monitor_atlas.py`.

> Secara default `debug=True` (hanya untuk dev). Nonaktifkan untuk produksi.

---

## 📥 Import Data dari Excel (.xlsx)

### 1) Struktur Sheet & Kolom

Aplikasi mencari **dua sheet** (nama tidak case-sensitive, cukup **mengandung** kata berikut):
- Sheet **`VPS`** — data VPS/RDP
- Sheet **`AKUN`** — data akun/penjualan

Nama kolom **fleksibel** (ada alias). Berikut **kolom yang didukung** (huruf besar/kecil tidak berpengaruh):

**Sheet `VPS` (minimal: `name`, `ip`, `port`)**
| Field        | Alias header yang dikenali (contoh)                          |
|--------------|---------------------------------------------------------------|
| `name`       | `name`, `nama`                                                |
| `ip`         | `ip`, `ipdomain`, `domain`, `host`                            |
| `port`       | `port`                                                        |
| `expire_date`| `expiredate`, `expired`, `expire`, `tanggalexpired`, `tanggalexpire`, `tglexpire`, `tanggal` |
| `price`      | `price`, `harga`                                              |
| `currency`   | `currency`, `curr`, `matauang`, `uang`                        |

**Sheet `AKUN`**
| Field      | Alias header yang dikenali (contoh)                  |
|------------|-------------------------------------------------------|
| `sold_at`  | `date`, `tanggal`, `tgl`, `dateddmmyyyy`             |
| `name`     | `name`, `nama`                                       |
| `merchant` | `merchant`, `toko`, `platform`, `marketplace`        |
| `type`     | `type`, `tipe`, `jenis`                              |
| `qty`      | `qty`, `jumlah`, `qtypcs`                            |
| `price`    | `price`, `harga`                                     |
| `currency` | `currency`, `curr`, `matauang`, `uang`               |

### 2) Format Tanggal yang Didukung
- `DD/MM/YYYY`, `DD-MM-YYYY`, `YYYY-MM-DD`, `DD/MM/YY`, `DD-MM-YY`
- **Excel serial date** juga otomatis dideteksi.

### 3) Alur Import
1. Buka **Admin → Import Excel**, upload file `.xlsx`.
2. Lihat **Preview** (sheet `VPS` & `AKUN`). Jika kolom wajib kurang, baris akan diskip.
3. Klik **Confirm** untuk commit ke database:
   - Data **VPS** di-*upsert* (berdasarkan kombinasi `name + ip + port`). Item baru akan otomatis dicatat ke **sales** (harga & mata uang).
   - Data **AKUN** disimpan ke koleksi sales akun.
4. Klik **Cancel** untuk membatalkan import (cache preview dibersihkan).

---

## 🔔 Notifikasi Telegram

- **Expired**: akan mengirim pesan ketika sebuah VPS **melewati tanggal expired** (hanya sekali) dan menandai flag `notified` di DB. Jika diperbarui kembali belum expired, flag akan direset.
- **Status DOWN**: akan mengirim pesan saat transisi **UP → DOWN** berdasarkan cek port TCP.

> Pastikan server memiliki akses keluar ke **api.telegram.org** dan Anda sudah mengisi `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`.

---

## 🛠️ Operasional

- **Interval cek** dapat diatur di sumber kode:
  - `CHECK_EXPIRED_SEC` (default **60** detik)
  - `CHECK_INTERVAL_SEC` (default **300** detik)
- **Port check** menggunakan `socket.create_connection(host, port, timeout=3)`.

---

## 🔐 Keamanan & Praktik Baik

- **Ganti semua default secret/credential** sebelum dipakai (ADMIN, SECRET_KEY, Telegram, MongoDB URI).
- **Jangan commit kredensial** ke repo publik.
- Matikan `debug=True` untuk produksi.
- Batasi akses **/admin** di level reverse proxy/firewall bila perlu.

---

## 🚀 Deploy Singkat (Opsional)

Contoh dengan **gunicorn** di Linux:

```bash
pip install gunicorn
# Jalankan 3 worker (sesuaikan CPU)
gunicorn -w 3 -b 0.0.0.0:8000 vps_monitor_atlas:app
# lalu pasang reverse proxy (Nginx/Caddy) ke 127.0.0.1:8000
```

Atau pakai layanan PaaS (Railway/Render/DO App Platform) yang mendukung Python WSGI.

---

## ❓ FAQ

**Q: Kenapa status selalu DOWN?**  
Cek firewall VPS/hosting Anda, pastikan port tujuan terbuka dari server aplikasi ini.

**Q: Tidak ada notifikasi Telegram?**  
Pastikan token & chat id valid, dan server bisa menjangkau `api.telegram.org`.

**Q: Import Excel gagal?**  
Gunakan format `.xlsx` (bukan `.xls`/CSV), cek nama sheet & minimal kolom wajib.

---

## 📝 Lisensi

Bebas dipakai & dimodifikasi di lingkungan Anda. Tambahkan lisensi (mis. **MIT**) bila ingin dibagikan publik.

---

## 🙌 Kontribusi

PR/issue dipersilakan. Mohon jangan menyertakan secret pada contoh konfigurasi.

