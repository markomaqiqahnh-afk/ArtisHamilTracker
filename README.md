# Artis Hamil Tracker

Aplikasi web satu-file (Flask) yang otomatis mencari, menyimpan, dan
menampilkan berita soal artis yang sedang hamil — semua dalam satu
aplikasi online.

## Fitur
- Auto-refresh otomatis tiap 3 jam (jalan di background, tanpa perlu klik apa-apa)
- Tombol "Refresh Sekarang" untuk cek manual kapan saja
- Tambah nama artis spesifik yang mau dipantau langsung dari halaman web
- Data tersimpan permanen di database SQLite (`berita.db`), tidak hilang saat server restart
- Endpoint `/api/berita` (JSON) kalau nanti mau dipakai di aplikasi mobile

## Coba di Komputer Sendiri Dulu

```bash
pip install -r requirements.txt
python app.py
```

Buka `http://localhost:5000` di browser.

## Deploy Supaya Bisa Diakses Online

Pilih salah satu, semuanya punya paket gratis:

### Opsi 1: Render.com (paling mudah)
1. Buat akun di render.com, hubungkan ke GitHub
2. Push folder ini ke repo GitHub baru
3. Di Render: **New +** → **Web Service** → pilih repo tadi
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn app:app`
6. Deploy — nanti dapat URL publik seperti `https://nama-app.onrender.com`

### Opsi 2: Railway.app
1. Buat akun di railway.app
2. **New Project** → **Deploy from GitHub repo**
3. Railway otomatis mendeteksi `Procfile` dan `requirements.txt`
4. Deploy — dapat URL publik otomatis

### Opsi 3: PythonAnywhere
1. Buat akun gratis di pythonanywhere.com
2. Upload folder ini lewat menu **Files**
3. Buat **Web App** baru, pilih Flask, arahkan ke `app.py`
4. Reload — aplikasi langsung bisa diakses di `namamu.pythonanywhere.com`

## Catatan Penting
- **Sumber berita**: pakai Google News RSS, gratis tanpa API key, tapi hasilnya
  bergantung pada apa yang diindeks Google News.
- **Akurasi**: berita kehamilan selebriti sering jadi gosip/hoax. Aplikasi ini
  cuma mengumpulkan dan menampilkan link berita — tetap cross-check ke sumber
  aslinya sebelum dipercaya sepenuhnya.
- **Privasi**: ini menyangkut info pribadi seseorang. Pertimbangkan untuk hanya
  menampilkan berita yang sudah dikonfirmasi resmi, bukan sekadar rumor.
- **Free tier hosting** biasanya "tidur" kalau tidak ada traffic — auto-refresh
  di background mungkin tidak jalan terus kalau server tidur. Untuk kebutuhan
  serius, pertimbangkan paket berbayar kecil atau cron job eksternal (misalnya
  cron-job.org) yang memanggil endpoint `/refresh` secara berkala.
