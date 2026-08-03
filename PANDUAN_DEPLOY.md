# Panduan Deploy Artis Hamil Tracker ke Render

Ikuti langkah-langkah ini urut dari atas ke bawah, jangan ada yang dilompat.
Total waktu kira-kira 15-20 menit.

---

## BAGIAN 1: Siapkan Akun GitHub

GitHub itu tempat untuk "menitipkan" kode aplikasi kamu, supaya nanti bisa
diambil otomatis oleh Render.

1. Buka **https://github.com**
2. Kalau belum punya akun, klik **Sign up** dan daftar (gratis)
3. Kalau sudah punya akun, tinggal **Login**

---

## BAGIAN 2: Upload File Aplikasi ke GitHub

1. Setelah login, klik tombol **hijau "New"** (atau ikon **+** di pojok kanan
   atas → pilih **New repository**)
2. Isi:
   - **Repository name**: ketik `artis-hamil-tracker` (atau nama lain bebas)
   - Pilih **Public**
   - JANGAN centang apapun di bawahnya (biarkan kosong)
3. Klik tombol **Create repository**
4. Di halaman berikutnya, cari tulisan **"uploading an existing file"**
   (ada link biru kecil di tengah halaman) → klik itu
5. Sekarang **drag & drop** ke-4 file berikut dari komputer kamu ke kotak
   upload di GitHub (file-file ini ada di download hasil chat kita):
   - `app.py`
   - `requirements.txt`
   - `Procfile`
   - `README.md`
6. Scroll ke bawah, klik tombol hijau **Commit changes**

Selesai — kode kamu sekarang sudah "online" di GitHub (tapi belum jadi
aplikasi yang bisa dibuka orang lain, ini baru penyimpanan kodenya saja).

---

## BAGIAN 3: Daftar & Setup Render

1. Buka **https://render.com**
2. Klik **Get Started** → pilih **Sign up with GitHub** (paling gampang,
   supaya otomatis terhubung dengan akun GitHub kamu tadi)
3. Kalau diminta izin akses (authorize), klik **Authorize Render**

---

## BAGIAN 4: Deploy Aplikasi

1. Di dashboard Render, klik tombol **New +** (pojok kanan atas)
2. Pilih **Web Service**
3. Cari dan klik repo yang tadi kamu buat (`artis-hamil-tracker`) →
   klik **Connect**
4. Akan muncul form, isi seperti ini:
   - **Name**: bebas, misal `artis-hamil-tracker`
   - **Region**: pilih yang paling dekat (misal Singapore)
   - **Branch**: biarkan default (`main`)
   - **Runtime**: pastikan otomatis terdeteksi **Python 3**
   - **Build Command**: ketik `pip install -r requirements.txt`
   - **Start Command**: ketik `gunicorn app:app`
   - **Instance Type**: pilih yang **Free**
5. Scroll ke bawah, klik tombol **Create Web Service**

---

## BAGIAN 5: Tunggu Proses Build

1. Render akan otomatis mulai proses install & menjalankan aplikasi kamu
2. Kamu akan lihat log berjalan di layar (teks-teks proses instalasi) —
   tunggu saja, biasanya 2-5 menit
3. Kalau sudah selesai, di bagian atas halaman akan muncul status
   **"Live"** berwarna hijau, dan ada URL seperti:
   ```
   https://artis-hamil-tracker.onrender.com
   ```
4. Klik URL itu — aplikasi kamu sudah bisa dibuka dan diakses siapa saja!

---

## BAGIAN 6: Coba Aplikasinya

1. Di halaman yang terbuka, klik tombol **"🔄 Refresh Sekarang"** untuk
   mencari berita pertama kali (soalnya database masih kosong)
2. Tunggu beberapa detik, halaman akan reload dan berita mulai muncul
3. Kalau mau memantau artis tertentu, ketik namanya di kolom yang ada
   tulisan "Tambah nama artis..." lalu klik **Tambah**

Setelah ini, aplikasi akan otomatis mencari berita baru sendiri setiap
3 jam, tanpa kamu perlu buka apa-apa. Tombol refresh manual tetap bisa
dipakai kapan saja kalau kamu nggak sabar nunggu.

---

## Catatan Penting

- **Free tier Render "tidur"** kalau tidak ada yang buka selama ~15 menit.
  Nanti pas dibuka lagi, loading pertama agak lama (~30 detik) karena
  server "bangun" dulu. Setelah itu normal lagi.
- Kalau nanti kamu edit kode di GitHub, Render akan otomatis
  re-deploy sendiri — tidak perlu setup ulang dari awal.
- Kalau ada error saat build, buka tab **Logs** di Render untuk lihat
  pesan errornya, lalu boleh kirim ke saya, saya bantu perbaiki.
