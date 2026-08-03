"""
Artis Hamil Tracker — v2
--------------------------
Perubahan dari v1:
1. Fix: refresh sekarang pakai header browser (User-Agent) supaya
   Google News tidak menganggap request sebagai bot dan hasilnya kosong
2. Fix: berita diurutkan berdasarkan TANGGAL TERBIT berita (bukan
   kapan sistem menemukannya), jadi yang paling baru selalu di atas
3. Fix: sekarang bisa hapus nama artis yang sudah ditambahkan ke daftar pantauan
4. Baru: halaman "Tracker Follow Up" — tabel CRM (Nama, Domisili, No WA,
   HPL, Kontak Pertama, Follow Up Lanjutan, Follow Up Terakhir, Bulan,
   Status Aktif) dengan tambah / edit / hapus data
"""

import sqlite3
import urllib.parse
import threading
import time
from datetime import datetime

import requests
import feedparser
from flask import Flask, render_template_string, request, redirect, url_for, jsonify

app = Flask(__name__)

DB_FILE = "berita.db"

DEFAULT_KEYWORDS = [
    "artis hamil",
    "selebriti hamil",
    "umumkan kehamilan",
]

AUTO_REFRESH_INTERVAL = 3 * 60 * 60  # 3 jam

# Header supaya request kita dianggap seperti browser biasa, bukan bot
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS berita (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            judul TEXT NOT NULL,
            link TEXT UNIQUE NOT NULL,
            sumber TEXT,
            tanggal_terbit TEXT,
            tanggal_terbit_iso TEXT,
            kata_kunci TEXT,
            ditemukan_pada TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keyword_tambahan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT UNIQUE NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT NOT NULL,
            domisili TEXT,
            no_wa TEXT,
            hpl TEXT,
            kontak_pertama_tanggal TEXT,
            kontak_pertama_hasil TEXT,
            followup_lanjutan_tanggal TEXT,
            followup_lanjutan_hasil TEXT,
            followup_terakhir_tanggal TEXT,
            hasil_akhir TEXT,
            keterangan TEXT,
            bulan INTEGER,
            aktif TEXT DEFAULT 'AKTIF',
            dibuat_pada TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_all_keywords_rows():
    conn = get_db()
    rows = conn.execute("SELECT id, nama FROM keyword_tambahan").fetchall()
    conn.close()
    return rows


def get_all_search_terms():
    rows = get_all_keywords_rows()
    extra = [f'"{r["nama"]}" hamil' for r in rows]
    return DEFAULT_KEYWORDS + extra


def simpan_berita(items):
    conn = get_db()
    baru = 0
    for item in items:
        try:
            conn.execute(
                """INSERT INTO berita
                   (judul, link, sumber, tanggal_terbit, tanggal_terbit_iso, kata_kunci, ditemukan_pada)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["judul"],
                    item["link"],
                    item["sumber"],
                    item["tanggal"],
                    item["tanggal_iso"],
                    item["kata_kunci"],
                    datetime.now().isoformat(),
                ),
            )
            baru += 1
        except sqlite3.IntegrityError:
            pass  # link sudah ada, skip
    conn.commit()
    conn.close()
    return baru


# ---------------------------------------------------------
# FETCH DARI GOOGLE NEWS RSS
# ---------------------------------------------------------

def build_query_url(term: str) -> str:
    encoded = urllib.parse.quote(term)
    return f"https://news.google.com/rss/search?q={encoded}&hl=id&gl=ID&ceid=ID:id"


def fetch_news_for_term(term: str):
    url = build_query_url(term)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as e:
        print(f"Gagal fetch untuk '{term}': {e}")
        return []

    results = []
    for entry in feed.entries:
        tanggal_iso = ""
        if getattr(entry, "published_parsed", None):
            try:
                tanggal_iso = datetime(*entry.published_parsed[:6]).isoformat()
            except Exception:
                tanggal_iso = ""
        results.append({
            "judul": entry.title,
            "link": entry.link,
            "sumber": entry.get("source", {}).get("title", "Tidak diketahui"),
            "tanggal": entry.get("published", ""),
            "tanggal_iso": tanggal_iso,
            "kata_kunci": term,
        })
    return results


def jalankan_pencarian():
    total_baru = 0
    error_terjadi = False
    for term in get_all_search_terms():
        items = fetch_news_for_term(term)
        if not items:
            error_terjadi = True
        total_baru += simpan_berita(items)
    return total_baru, error_terjadi


def background_scheduler():
    while True:
        try:
            jumlah, _ = jalankan_pencarian()
            print(f"[{datetime.now()}] Auto-refresh selesai, {jumlah} berita baru.")
        except Exception as e:
            print(f"[{datetime.now()}] Gagal auto-refresh: {e}")
        time.sleep(AUTO_REFRESH_INTERVAL)


# ---------------------------------------------------------
# TEMPLATE
# ---------------------------------------------------------

BASE_STYLE = """
<style>
    * { box-sizing: border-box; }
    body { font-family: -apple-system, sans-serif; margin: 0; padding: 0; background: #faf7f5; color: #222; }
    .wrap { max-width: 1200px; margin: 0 auto; padding: 20px; }
    h1 { color: #b5478c; margin-bottom: 4px; }
    .tabs { display: flex; gap: 8px; margin: 16px 0; border-bottom: 2px solid #eee; }
    .tab { padding: 10px 18px; text-decoration: none; color: #666; border-bottom: 3px solid transparent; font-weight: 600; }
    .tab.active { color: #b5478c; border-bottom-color: #b5478c; }
    button, input[type=submit], .btn { background: #b5478c; color: white; border: none; padding: 9px 16px; border-radius: 6px; cursor: pointer; font-size: 14px; text-decoration: none; display: inline-block; }
    button:hover, input[type=submit]:hover, .btn:hover { background: #99396f; }
    .btn-secondary { background: #888; }
    .btn-secondary:hover { background: #666; }
    .btn-danger { background: #c0392b; }
    .btn-danger:hover { background: #992d22; }
    input[type=text], select, textarea { padding: 8px; border-radius: 6px; border: 1px solid #ccc; font-size: 14px; }
    .toolbar { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
    .card { background: white; border-radius: 10px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
    .card a { text-decoration: none; color: #222; font-weight: 600; }
    .card a:hover { text-decoration: underline; }
    .meta { color: #888; font-size: 13px; margin-top: 6px; }
    .badge { display: inline-block; background: #f3e3ec; color: #b5478c; padding: 2px 8px; border-radius: 12px; font-size: 12px; margin-right: 6px; }
    .empty { text-align: center; color: #999; padding: 40px 0; }
    .chip { display: inline-flex; align-items: center; gap: 6px; background: #f3e3ec; color: #b5478c; padding: 4px 6px 4px 12px; border-radius: 14px; font-size: 13px; margin: 3px; }
    .chip form { margin: 0; }
    .chip button.hapus-chip { background: none; color: #b5478c; padding: 0 8px; font-size: 15px; font-weight: bold; }
    .flash { padding: 10px 14px; border-radius: 6px; margin-bottom: 14px; font-size: 14px; }
    .flash-ok { background: #e2f5e9; color: #1e7e42; }
    .flash-error { background: #fdecea; color: #b3261e; }
    table.tracker { width: 100%; border-collapse: collapse; background: white; font-size: 13px; }
    table.tracker th, table.tracker td { border: 1px solid #eee; padding: 8px; text-align: left; vertical-align: top; }
    table.tracker th { background: #f3e3ec; color: #99396f; white-space: nowrap; }
    table.tracker tr:hover { background: #fdf9fb; }
    .status-aktif { color: #1e7e42; font-weight: 600; }
    .status-tidak { color: #999; }
    .table-scroll { overflow-x: auto; border-radius: 10px; }
    .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; background: white; padding: 20px; border-radius: 10px; }
    .form-grid label { font-size: 13px; font-weight: 600; color: #555; display: block; margin-bottom: 4px; }
    .form-grid .full { grid-column: 1 / -1; }
    .form-grid input, .form-grid select, .form-grid textarea { width: 100%; }
    .form-actions { grid-column: 1 / -1; display: flex; gap: 10px; margin-top: 8px; }
    .aksi-cell { white-space: nowrap; }
    .aksi-cell a, .aksi-cell button { font-size: 12px; padding: 5px 9px; margin-right: 4px; }
</style>
"""

TEMPLATE_BERITA = """
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>Artis Hamil Tracker</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
""" + BASE_STYLE + """
</head>
<body>
<div class="wrap">
    <h1>🎀 Artis Hamil Tracker</h1>
    <div class="tabs">
        <a class="tab active" href="{{ url_for('index') }}">Berita Terbaru</a>
        <a class="tab" href="{{ url_for('tracker') }}">Tracker Follow Up</a>
    </div>

    {% if flash_msg %}
    <div class="flash {{ 'flash-ok' if flash_ok else 'flash-error' }}">{{ flash_msg }}</div>
    {% endif %}

    <p>Total berita tersimpan: <strong>{{ total }}</strong> — auto-refresh tiap {{ interval_jam }} jam</p>

    <div class="toolbar">
        <form action="{{ url_for('refresh') }}" method="post" onsubmit="document.getElementById('btnRefresh').innerText='Memproses...'; document.getElementById('btnRefresh').disabled=true;">
            <button type="submit" id="btnRefresh">🔄 Refresh Sekarang</button>
        </form>
        <form action="{{ url_for('tambah_keyword') }}" method="post" style="display:flex; gap:8px; flex:1;">
            <input type="text" name="nama_artis" placeholder="Tambah nama artis untuk dipantau...">
            <input type="submit" value="Tambah">
        </form>
    </div>

    {% if keywords_tambahan %}
    <div style="margin-bottom: 16px;">
        <span style="font-size: 13px; color: #666;">Sedang memantau:</span><br>
        {% for kw in keywords_tambahan %}
        <span class="chip">
            {{ kw.nama }}
            <form action="{{ url_for('hapus_keyword', keyword_id=kw.id) }}" method="post" onsubmit="return confirm('Hapus {{ kw.nama }} dari daftar pantauan?');">
                <button type="submit" class="hapus-chip">✕</button>
            </form>
        </span>
        {% endfor %}
    </div>
    {% endif %}

    {% if berita|length == 0 %}
        <div class="empty">Belum ada berita. Klik "Refresh Sekarang" untuk mulai mencari.</div>
    {% endif %}

    {% for b in berita %}
    <div class="card">
        <a href="{{ b.link }}" target="_blank" rel="noopener">{{ b.judul }}</a>
        <div class="meta">
            <span class="badge">{{ b.sumber }}</span>
            {{ b.tanggal_terbit }}
        </div>
    </div>
    {% endfor %}
</div>
</body>
</html>
"""

TEMPLATE_TRACKER = """
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>Tracker Follow Up</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
""" + BASE_STYLE + """
</head>
<body>
<div class="wrap">
    <h1>🎀 Artis Hamil Tracker</h1>
    <div class="tabs">
        <a class="tab" href="{{ url_for('index') }}">Berita Terbaru</a>
        <a class="tab active" href="{{ url_for('tracker') }}">Tracker Follow Up</a>
    </div>

    {% if flash_msg %}
    <div class="flash {{ 'flash-ok' if flash_ok else 'flash-error' }}">{{ flash_msg }}</div>
    {% endif %}

    <div class="toolbar">
        <a href="{{ url_for('tambah_lead') }}" class="btn">+ Tambah Public Figure</a>
    </div>

    <div class="table-scroll">
    <table class="tracker">
        <thead>
            <tr>
                <th>No</th>
                <th>Nama Public Figure</th>
                <th>Domisili</th>
                <th>No WA</th>
                <th>HPL</th>
                <th>Kontak Pertama (Tgl)</th>
                <th>Kontak Pertama (Hasil)</th>
                <th>Follow Up Lanjutan (Tgl)</th>
                <th>Follow Up Lanjutan (Hasil)</th>
                <th>Follow Up Terakhir (Tgl)</th>
                <th>Hasil Akhir</th>
                <th>Keterangan</th>
                <th>Bulan</th>
                <th>Status</th>
                <th>Aksi</th>
            </tr>
        </thead>
        <tbody>
            {% for l in leads %}
            <tr>
                <td>{{ loop.index }}</td>
                <td>{{ l.nama }}</td>
                <td>{{ l.domisili or '' }}</td>
                <td>{{ l.no_wa or '' }}</td>
                <td>{{ l.hpl or '' }}</td>
                <td>{{ l.kontak_pertama_tanggal or '' }}</td>
                <td>{{ l.kontak_pertama_hasil or '' }}</td>
                <td>{{ l.followup_lanjutan_tanggal or '' }}</td>
                <td>{{ l.followup_lanjutan_hasil or '' }}</td>
                <td>{{ l.followup_terakhir_tanggal or '' }}</td>
                <td>{{ l.hasil_akhir or '' }}</td>
                <td>{{ l.keterangan or '' }}</td>
                <td>{{ l.bulan or '' }}</td>
                <td class="{{ 'status-aktif' if l.aktif == 'AKTIF' else 'status-tidak' }}">{{ l.aktif }}</td>
                <td class="aksi-cell">
                    <a href="{{ url_for('edit_lead', lead_id=l.id) }}" class="btn btn-secondary">Edit</a>
                    <form action="{{ url_for('hapus_lead', lead_id=l.id) }}" method="post" style="display:inline;" onsubmit="return confirm('Hapus data {{ l.nama }}?');">
                        <button type="submit" class="btn-danger">Hapus</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
            {% if leads|length == 0 %}
            <tr><td colspan="15" class="empty">Belum ada data. Klik "+ Tambah Public Figure" untuk mulai.</td></tr>
            {% endif %}
        </tbody>
    </table>
    </div>
</div>
</body>
</html>
"""

TEMPLATE_FORM_LEAD = """
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>{{ 'Edit' if lead else 'Tambah' }} Public Figure</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
""" + BASE_STYLE + """
</head>
<body>
<div class="wrap">
    <h1>🎀 {{ 'Edit' if lead else 'Tambah' }} Public Figure</h1>
    <div class="tabs">
        <a class="tab" href="{{ url_for('index') }}">Berita Terbaru</a>
        <a class="tab active" href="{{ url_for('tracker') }}">Tracker Follow Up</a>
    </div>

    <form method="post" class="form-grid">
        <div>
            <label>Nama Public Figure *</label>
            <input type="text" name="nama" required value="{{ lead.nama if lead else '' }}">
        </div>
        <div>
            <label>Domisili</label>
            <input type="text" name="domisili" value="{{ lead.domisili if lead else '' }}">
        </div>
        <div>
            <label>No WA</label>
            <input type="text" name="no_wa" value="{{ lead.no_wa if lead else '' }}">
        </div>
        <div>
            <label>HPL</label>
            <input type="text" name="hpl" placeholder="misal: Mei 2026" value="{{ lead.hpl if lead else '' }}">
        </div>
        <div>
            <label>Kontak Pertama — Tanggal</label>
            <input type="text" name="kontak_pertama_tanggal" placeholder="DD/MM/YYYY" value="{{ lead.kontak_pertama_tanggal if lead else '' }}">
        </div>
        <div>
            <label>Kontak Pertama — Hasil</label>
            <input type="text" name="kontak_pertama_hasil" value="{{ lead.kontak_pertama_hasil if lead else '' }}">
        </div>
        <div>
            <label>Follow Up Lanjutan — Tanggal</label>
            <input type="text" name="followup_lanjutan_tanggal" placeholder="DD/MM/YYYY" value="{{ lead.followup_lanjutan_tanggal if lead else '' }}">
        </div>
        <div>
            <label>Follow Up Lanjutan — Hasil</label>
            <input type="text" name="followup_lanjutan_hasil" value="{{ lead.followup_lanjutan_hasil if lead else '' }}">
        </div>
        <div>
            <label>Follow Up Terakhir — Tanggal</label>
            <input type="text" name="followup_terakhir_tanggal" placeholder="DD/MM/YYYY" value="{{ lead.followup_terakhir_tanggal if lead else '' }}">
        </div>
        <div>
            <label>Hasil Akhir</label>
            <select name="hasil_akhir">
                {% for opt in ['BELUM', 'TIDAK', 'CLOSING', 'NON MUSLIM / KRISTEN'] %}
                <option value="{{ opt }}" {{ 'selected' if lead and lead.hasil_akhir == opt else '' }}>{{ opt }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="full">
            <label>Keterangan</label>
            <textarea name="keterangan" rows="2">{{ lead.keterangan if lead else '' }}</textarea>
        </div>
        <div>
            <label>Bulan (kode sort)</label>
            <input type="text" name="bulan" value="{{ lead.bulan if lead else '' }}">
        </div>
        <div>
            <label>Status</label>
            <select name="aktif">
                <option value="AKTIF" {{ 'selected' if lead and lead.aktif == 'AKTIF' else '' }}>AKTIF</option>
                <option value="TIDAK AKTIF" {{ 'selected' if lead and lead.aktif == 'TIDAK AKTIF' else '' }}>TIDAK AKTIF</option>
            </select>
        </div>
        <div class="form-actions">
            <button type="submit">Simpan</button>
            <a href="{{ url_for('tracker') }}" class="btn btn-secondary">Batal</a>
        </div>
    </form>
</div>
</body>
</html>
"""


# ---------------------------------------------------------
# ROUTES — BERITA
# ---------------------------------------------------------

@app.route("/")
def index():
    conn = get_db()
    berita = conn.execute(
        """SELECT * FROM berita
           ORDER BY
             CASE WHEN tanggal_terbit_iso = '' OR tanggal_terbit_iso IS NULL THEN 1 ELSE 0 END,
             tanggal_terbit_iso DESC
           LIMIT 100"""
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) as c FROM berita").fetchone()["c"]
    kw_rows = get_all_keywords_rows()
    conn.close()

    flash_msg = request.args.get("msg")
    flash_ok = request.args.get("ok") == "1"

    return render_template_string(
        TEMPLATE_BERITA,
        berita=berita,
        total=total,
        interval_jam=AUTO_REFRESH_INTERVAL // 3600,
        keywords_tambahan=kw_rows,
        flash_msg=flash_msg,
        flash_ok=flash_ok,
    )


@app.route("/refresh", methods=["POST"])
def refresh():
    jumlah, error_terjadi = jalankan_pencarian()
    if jumlah == 0 and error_terjadi:
        msg = "Refresh selesai tapi tidak ada berita baru ditemukan (bisa jadi belum ada berita baru, atau Google News sedang membatasi request — coba lagi beberapa saat lagi)."
        ok = "0"
    elif jumlah == 0:
        msg = "Refresh selesai, tidak ada berita baru (semua berita yang ada sudah tersimpan sebelumnya)."
        ok = "1"
    else:
        msg = f"Refresh selesai, {jumlah} berita baru ditemukan."
        ok = "1"
    return redirect(url_for("index", msg=msg, ok=ok))


@app.route("/tambah-keyword", methods=["POST"])
def tambah_keyword():
    nama = request.form.get("nama_artis", "").strip()
    if nama:
        conn = get_db()
        try:
            conn.execute("INSERT INTO keyword_tambahan (nama) VALUES (?)", (nama,))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        conn.close()
        items = fetch_news_for_term(f'"{nama}" hamil')
        simpan_berita(items)
    return redirect(url_for("index"))


@app.route("/hapus-keyword/<int:keyword_id>", methods=["POST"])
def hapus_keyword(keyword_id):
    conn = get_db()
    conn.execute("DELETE FROM keyword_tambahan WHERE id = ?", (keyword_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))


@app.route("/api/berita")
def api_berita():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM berita ORDER BY tanggal_terbit_iso DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------
# ROUTES — TRACKER (CRM)
# ---------------------------------------------------------

@app.route("/tracker")
def tracker():
    conn = get_db()
    leads = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    conn.close()
    flash_msg = request.args.get("msg")
    flash_ok = request.args.get("ok") == "1"
    return render_template_string(
        TEMPLATE_TRACKER, leads=leads, flash_msg=flash_msg, flash_ok=flash_ok
    )


def form_ke_dict(form):
    return {
        "nama": form.get("nama", "").strip(),
        "domisili": form.get("domisili", "").strip(),
        "no_wa": form.get("no_wa", "").strip(),
        "hpl": form.get("hpl", "").strip(),
        "kontak_pertama_tanggal": form.get("kontak_pertama_tanggal", "").strip(),
        "kontak_pertama_hasil": form.get("kontak_pertama_hasil", "").strip(),
        "followup_lanjutan_tanggal": form.get("followup_lanjutan_tanggal", "").strip(),
        "followup_lanjutan_hasil": form.get("followup_lanjutan_hasil", "").strip(),
        "followup_terakhir_tanggal": form.get("followup_terakhir_tanggal", "").strip(),
        "hasil_akhir": form.get("hasil_akhir", "").strip(),
        "keterangan": form.get("keterangan", "").strip(),
        "bulan": form.get("bulan", "").strip() or None,
        "aktif": form.get("aktif", "AKTIF"),
    }


@app.route("/tracker/tambah", methods=["GET", "POST"])
def tambah_lead():
    if request.method == "POST":
        d = form_ke_dict(request.form)
        if not d["nama"]:
            return redirect(url_for("tambah_lead"))
        conn = get_db()
        conn.execute(
            """INSERT INTO leads
               (nama, domisili, no_wa, hpl, kontak_pertama_tanggal, kontak_pertama_hasil,
                followup_lanjutan_tanggal, followup_lanjutan_hasil, followup_terakhir_tanggal,
                hasil_akhir, keterangan, bulan, aktif, dibuat_pada)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                d["nama"], d["domisili"], d["no_wa"], d["hpl"],
                d["kontak_pertama_tanggal"], d["kontak_pertama_hasil"],
                d["followup_lanjutan_tanggal"], d["followup_lanjutan_hasil"],
                d["followup_terakhir_tanggal"], d["hasil_akhir"], d["keterangan"],
                d["bulan"], d["aktif"], datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("tracker", msg="Data baru berhasil ditambahkan.", ok="1"))
    return render_template_string(TEMPLATE_FORM_LEAD, lead=None)


@app.route("/tracker/edit/<int:lead_id>", methods=["GET", "POST"])
def edit_lead(lead_id):
    conn = get_db()
    if request.method == "POST":
        d = form_ke_dict(request.form)
        conn.execute(
            """UPDATE leads SET nama=?, domisili=?, no_wa=?, hpl=?,
               kontak_pertama_tanggal=?, kontak_pertama_hasil=?,
               followup_lanjutan_tanggal=?, followup_lanjutan_hasil=?,
               followup_terakhir_tanggal=?, hasil_akhir=?, keterangan=?,
               bulan=?, aktif=? WHERE id=?""",
            (
                d["nama"], d["domisili"], d["no_wa"], d["hpl"],
                d["kontak_pertama_tanggal"], d["kontak_pertama_hasil"],
                d["followup_lanjutan_tanggal"], d["followup_lanjutan_hasil"],
                d["followup_terakhir_tanggal"], d["hasil_akhir"], d["keterangan"],
                d["bulan"], d["aktif"], lead_id,
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("tracker", msg="Data berhasil diperbarui.", ok="1"))

    lead = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    conn.close()
    if lead is None:
        return redirect(url_for("tracker"))
    return render_template_string(TEMPLATE_FORM_LEAD, lead=lead)


@app.route("/tracker/hapus/<int:lead_id>", methods=["POST"])
def hapus_lead(lead_id):
    conn = get_db()
    conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("tracker", msg="Data berhasil dihapus.", ok="1"))


# ---------------------------------------------------------
# START
# ---------------------------------------------------------

init_db()

scheduler_thread = threading.Thread(target=background_scheduler, daemon=True)
scheduler_thread.start()

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
