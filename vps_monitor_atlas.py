# ===== IMPORTS =====
from flask import Flask, render_template, request, redirect, url_for, session
from functools import wraps
from pymongo import MongoClient
from bson.objectid import ObjectId
import socket, requests, threading, time, os
import datetime                     # pakai modul: datetime.date / datetime.datetime
from datetime import datetime as dt # khusus untuk template: dt.utcnow()
from math import isfinite
import re
import json
import uuid
import io
import pandas as pd
from bson import ObjectId

def _parse_price_num(x):
    """Parse angka harga dengan pemisah ribuan/decimal ID/EN."""
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x or "").strip()
    if s == "":
        return 0.0
    s = s.replace(" ", "")
    if "," in s and "." in s:
        # format ID: 1.234,56
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "")
            s = s.replace(",", ".")
        else:
            # format EN: 1,234.56
            s = s.replace(",", "")
    else:
        if s.count(".") > 1:
            s = s.replace(".", "")
        elif s.count(",") > 1:
            s = s.replace(",", "")
        elif "," in s and "." not in s:
            s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


CHECK_INTERVAL_SEC = 300  # cek setiap 5 menit

# ===== APP & CONFIG =====
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me")  # wajib untuk session

# Admin ( rubah disini untuk login di /admin )
ADMIN_USER = "admin"
ADMIN_PASS = "123456"

@app.context_processor
def inject_now():
    return {'datetime': dt}

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login", next=request.path))
        return f(*args, **kwargs)
    return wrapper

# ===== DB & TELEGRAM =====
MONGO_URI = "#"  # <-- ganti punyamu
client = MongoClient(MONGO_URI)
db = client["vps_monitor"]
vps_collection = db["vps_data"]
prices_collection = db["prices"]   # daftar harga VPS/RDP
sales_collection  = db["sales"]    # pencatatan penjualan


TELEGRAM_BOT_TOKEN = "#"
TELEGRAM_CHAT_ID = "#"

# ===== HELPERS =====
def is_port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

def send_telegram_alert(message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=5
        )
    except Exception:
        pass

CHECK_EXPIRED_SEC = 60  # 1 menit


def monitor_expired():
    """Cek expired tiap interval, kirim notif sekali (pakai flag 'notified')."""
    while True:
        try:
            today = datetime.date.today()
            for vps in vps_collection.find({}):
                exp_raw = vps.get("expired")
                if isinstance(exp_raw, datetime.datetime):
                    exp_date = exp_raw.date()
                elif isinstance(exp_raw, datetime.date):
                    exp_date = exp_raw
                else:
                    exp_date = None
                is_expired = bool(exp_date and today > exp_date)
                update = {}
                if is_expired and not vps.get("notified", False):
                    try:
                        send_telegram_alert(
                            f"⚠️ VPS EXPIRED 😏 Nama : {vps.get('name','(tanpa nama)')} | IP : {vps.get('ip','-')} | Expired : {(exp_date.isoformat() if exp_date else '-')}"
                        )
                        update["notified"] = True
                    except Exception:
                        pass
                elif not is_expired and vps.get("notified", False):
                    update["notified"] = False
                if update:
                    vps_collection.update_one({"_id": vps["_id"]}, {"$set": update})
        except Exception as e:
            print("monitor_expired error:", e)
        time.sleep(CHECK_EXPIRED_SEC)

# ===== PUBLIC: READ-ONLY HOME =====
@app.route("/", methods=["GET"])
def index():
    today = datetime.date.today()
    vps_list = []
    for v in vps_collection.find():
        exp = v["expired"]
        exp_date = exp.date() if isinstance(exp, datetime.datetime) else exp
        vps_list.append({
            "_id": str(v["_id"]),
            "name": v.get("name",""),
            "ip": v.get("ip",""),
            "port": v.get("port",""),
            "expired": exp_date.strftime("%Y-%m-%d"),
            "is_up": is_port_open(v["ip"], v["port"]),
            "days_left": (exp_date - today).days,
            "price": v.get("price", 0),                 # <—
            "currency": v.get("currency", "IDR"),       # <—
        })

    akun_list = []
    for a in sales_collection.find({"category": "akun"}).sort("sold_at", -1).limit(200):
        sold_str = a["sold_at"].strftime("%Y-%m-%d") if isinstance(a.get("sold_at"), datetime.datetime) else str(a.get("sold_at",""))
        qty = int(a.get("qty", 1) or 1)
        price = float(a.get("price", 0) or 0)
        akun_list.append({
            "_id": str(a["_id"]),
            "date": sold_str,
            "name": a.get("name",""),
            "merchant": a.get("merchant",""),
            "atype": a.get("account_type",""),
            "qty": qty,
            "price": price,
            "currency": a.get("currency","IDR"),
            "subtotal": qty * price
        })

    return render_template("index.html", vps_list=vps_list, akun_list=akun_list)


# ===== ADMIN AUTH =====
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("username","").strip() == ADMIN_USER and request.form.get("password","") == ADMIN_PASS:
            session["admin"] = True
            return redirect(request.args.get("next") or url_for("admin_home"))
        return render_template("admin_login.html", error="Username atau password salah")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))



# ===== ADMIN PAGES =====
@app.route("/admin")
@admin_required
def admin_home():
    # --- Statistik VPS ---
    today = datetime.date.today()
    rows = list(vps_collection.find())
    stats = {"total": len(rows), "up": 0, "down": 0, "expiring": 0, "expired": 0}

    for v in rows:
        # tanggal expired bisa tersimpan sebagai datetime/date
        exp = v.get("expired")
        exp_date = exp.date() if isinstance(exp, datetime.datetime) else exp
        # fallback jika null
        if not isinstance(exp_date, datetime.date):
            # coba parse string 'YYYY-MM-DD'
            try:
                exp_date = datetime.datetime.strptime(str(exp), "%Y-%m-%d").date()
            except Exception:
                exp_date = today

        is_up = is_port_open(v.get("ip"), v.get("port"))
        if is_up:
            stats["up"] += 1
        else:
            stats["down"] += 1

        days_left = (exp_date - today).days
        if days_left < 0:
            stats["expired"] += 1
        elif days_left <= 3:
            stats["expiring"] += 1

    # --- Ambil price list (jika ada koleksinya) untuk form lama ---
    price_list = list(prices_collection.find()) if "prices_collection" in globals() else []

    # --- Rekap Penjualan (gabungan VPS + Akun) ---
    now = datetime.datetime.utcnow()
    month_start = datetime.datetime(now.year, now.month, 1)
    next_month = datetime.datetime(now.year + (now.month == 12), (now.month % 12) + 1, 1)

    def sum_total(cur):
        total = 0.0
        for s in cur:
            try:
                qty = int(s.get("qty", 1))           # default 1 untuk item VPS
                price = float(s.get("price", 0.0))
                total += qty * price
            except Exception:
                pass
        return total

    # total bulan ini (VPS + Akun)
    month_total = sum_total(
        sales_collection.find({"sold_at": {"$gte": month_start, "$lt": next_month}})
    )

    # total all time (VPS + Akun)
    all_total = sum_total(sales_collection.find({}))

    # --- Total Akun (jumlah item akun terjual = sum qty) ---
    total_akun = 0
    for s in sales_collection.find({"category": "akun"}):
        try:
            total_akun += int(s.get("qty", 0))
        except Exception:
            pass

    # --- Data Penjualan Akun (untuk tabel) ---
    akun_list = list(
        sales_collection.find({"category": "akun"}).sort("sold_at", -1).limit(100)
    )

    return render_template(
        "admin_index.html",
        stats=stats,            # statistik VPS
        items=rows,             # daftar VPS
        prices=price_list,      # daftar harga (opsional)
        month_total=month_total,
        all_total=all_total,
        total_akun=total_akun,
        akun_list=akun_list
    )



@app.route("/add", methods=["POST"])
@admin_required
def admin_add_vps():
    name = request.form["name"].strip()
    ip = request.form["ip"].strip()
    port = int(request.form["port"].strip())
    expired_dt = datetime.datetime.strptime(request.form["expired"], "%Y-%m-%d")

    # === harga (optional) ===
    def _to_float(s):
        try:
            return float(str(s).replace(",", "").strip())
        except:
            return 0.0
    price = _to_float(request.form.get("price", "0"))
    currency = (request.form.get("currency", "IDR") or "IDR").strip()

    res = vps_collection.insert_one({
        "name": name,
        "ip": ip,
        "port": port,
        "expired": expired_dt,
        "notified": False,
        "price": price,            # <—
        "currency": currency       # <—
    })

    # === tambahan: otomatis catat penjualan ===
    sold_at_str = request.form.get("sold_at")  # opsional jika kamu mau isi tanggal di modal
    if sold_at_str:
        sold_at = datetime.datetime.strptime(sold_at_str, "%Y-%m-%d")
    else:
        sold_at = datetime.datetime.utcnow()  # default: waktu input → ikut bulan saat input

    sales_collection.insert_one({
    "category": "vps",
    "ref_vps_id": res.inserted_id,
    "name": name,
    "price": price,
    "currency": currency,
    "sold_at": dt.utcnow()
})


    return redirect(url_for("admin_home"))


@app.route("/edit/<id>", methods=["GET", "POST"])
@app.route("/edit/<id>", methods=["GET", "POST"])
@admin_required
def edit_vps(id):
    _id = ObjectId(id)
    doc = vps_collection.find_one({"_id": _id}) or {}  # ambil dok lama (buat fallback nama)

    if request.method == "POST":
        # --- ambil nilai baru ---
        name     = (request.form.get("name") or "").strip()
        ip       = (request.form.get("ip") or "").strip()
        port     = str(request.form.get("port") or "").strip()
        currency = (request.form.get("currency") or "IDR").upper()

        # parser harga yang kuat (100.000 / 1,234.56 dll)
        def _parse_price_num(x):
            if isinstance(x, (int, float)): return float(x)
            s = str(x or "").strip()
            if s == "": return 0.0
            s = s.replace(" ", "")
            if "," in s and "." in s:
                if s.rfind(",") > s.rfind("."):
                    s = s.replace(".", "").replace(",", ".")
                else:
                    s = s.replace(",", "")
            else:
                if s.count(".") > 1: s = s.replace(".", "")
                elif s.count(",") > 1: s = s.replace(",", "")
                elif "," in s and "." not in s: s = s.replace(",", ".")
            try: return float(s)
            except: return 0.0

        price = _parse_price_num(request.form.get("price"))

        # expire_date opsional
        exp_dt = None
        exp_s = (request.form.get("expire_date") or "").strip()
        if exp_s:
            try:
                d = dt.strptime(exp_s, "%Y-%m-%d").date()
            except ValueError:
                try: d = dt.strptime(exp_s, "%d/%m/%Y").date()
                except ValueError: d = None
            if d:
                exp_dt = dt.combine(d, dt.min.time())

        # --- update vps_collection ---
        upd_vps = {"name": name, "ip": ip, "port": port, "currency": currency, "price": price}
        if exp_dt is not None:
            upd_vps["expired"] = exp_dt
        vps_collection.update_one({"_id": _id}, {"$set": upd_vps})

        # --- SINKRON sales_collection (kunci utama masalahmu) ---
        fields = {"name": name, "price": price, "currency": currency}

        # 1) Coba by ref_vps_id (paling akurat). Pakai upsert supaya kalau belum ada → dibuat.
        r = sales_collection.update_one(
            {"ref_vps_id": _id},
            {"$set": fields, "$setOnInsert": {"category": "vps", "sold_at": dt.utcnow()}},
            upsert=True
        )

        # 2) Kalau tadi bukan upsert (artinya sudah ada & update sukses), selesai.
        #    Kalau dia baru INSERT lewat upsert, juga sudah selesai.
        #    Tapi kalau sama sekali belum match (aneh), fallback by name.
        if r.matched_count == 0 and r.upserted_id is None:
            old_name = doc.get("name", name)
            r2 = sales_collection.update_many(
                {"name": {"$in": [old_name, name]}, "ref_vps_id": {"$exists": False}},
                {"$set": fields}
            )
            # 3) Kalau tetap tidak ada yang kena, buat baru (biar total ikut berubah)
            if r2.matched_count == 0:
                sales_collection.insert_one({
                    "category": "vps",
                    "ref_vps_id": _id,
                    "name": name,
                    "price": price,
                    "currency": currency,
                    "sold_at": dt.utcnow()
                })

        return redirect(url_for("admin_home"))

    # GET
    return render_template("edit.html", vps=doc)



@app.route("/delete/<id>")
@admin_required
def delete_vps(id):
    vps_collection.delete_one({"_id": ObjectId(id)})
    return redirect(url_for("admin_home"))

def _to_float(s):
    try:
        x = float(str(s).replace(",", "").strip())
        return x if isfinite(x) else 0.0
    except:
        return 0.0

# ====== HARGA ======
@app.route("/admin/price/add", methods=["POST"])
@admin_required
def admin_add_price():
    name = request.form["p_name"].strip()
    price = _to_float(request.form["p_price"])
    currency = request.form.get("p_currency", "IDR").strip() or "IDR"
    if name and price > 0:
        prices_collection.insert_one({"name": name, "price": price, "currency": currency})
    return redirect(url_for("admin_home"))

@app.route("/admin/price/delete/<id>")
@admin_required
def admin_delete_price(id):
    prices_collection.delete_one({"_id": ObjectId(id)})
    return redirect(url_for("admin_home"))

# ====== PENJUALAN ======
@app.route("/admin/sale/add", methods=["POST"])
@admin_required
def admin_add_sale():
    # Bisa pilih dari daftar harga, atau input manual
    use_price_id = request.form.get("s_price_id")  # id dari prices_collection (opsional)
    name = request.form.get("s_name", "").strip()
    price = _to_float(request.form.get("s_price", "0"))
    currency = request.form.get("s_currency", "IDR").strip() or "IDR"
    date_str = request.form.get("s_date")  # "YYYY-MM-DD" opsional

    if use_price_id and not (name and price):
        # ambil dari price list bila dipilih
        pr = prices_collection.find_one({"_id": ObjectId(use_price_id)})
        if pr:
            name = pr.get("name", name)
            price = pr.get("price", price)
            currency = pr.get("currency", currency)

    # tanggal jual
    if date_str:
        sold_at = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    else:
        sold_at = datetime.datetime.utcnow()

    if name and price > 0:
        sales_collection.insert_one({
            "name": name,
            "price": price,
            "currency": currency,
            "sold_at": sold_at
        })

    return redirect(url_for("admin_home"))

@app.route("/admin/account/add", methods=["POST"])
@admin_required
def admin_add_account_sale():
    # Ambil field form
    name = request.form.get("a_name", "").strip()                 # Nama Akun/Produk
    merchant = request.form.get("a_merchant", "").strip()         # Nama Merchant
    acc_type = request.form.get("a_type", "").strip()             # Type Akun
    qty = int(request.form.get("a_qty", "1") or 1)                # Total Beli
    # harga satuan
    def _to_float(s):
        try: return float(str(s).replace(",", "").strip())
        except: return 0.0
    price = _to_float(request.form.get("a_price", "0"))
    currency = (request.form.get("a_currency", "IDR") or "IDR").strip()
    date_str = request.form.get("a_date")  # opsional YYYY-MM-DD

    # tanggal jual
    import datetime
    if date_str:
        sold_at = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    else:
        sold_at = datetime.datetime.utcnow()

    if name and price > 0 and qty > 0:
        sales_collection.insert_one({
            "category": "akun",        # <— pembeda
            "name": name,
            "merchant": merchant,
            "account_type": acc_type,
            "qty": qty,
            "price": price,            # harga satuan
            "currency": currency,
            "sold_at": sold_at
        })
    return redirect(url_for("admin_home"))

@app.route("/admin/account/delete/<id>")
@admin_required
def admin_delete_account_sale(id):
    sales_collection.delete_one({"_id": ObjectId(id)})
    return redirect(url_for("admin_home"))

def _to_float(s):
    try: return float(str(s).replace(",", "").strip())
    except: return 0.0

@app.route("/admin/account/edit/<id>", methods=["POST"])
@admin_required
def admin_edit_account_sale(id):
    name     = request.form.get("a_name", "").strip()
    merchant = request.form.get("a_merchant", "").strip()
    acc_type = request.form.get("a_type", "").strip()
    qty      = int(request.form.get("a_qty", "1") or 1)
    price    = _to_float(request.form.get("a_price", "0"))
    currency = (request.form.get("a_currency", "IDR") or "IDR").strip()
    date_str = request.form.get("a_date", "")

    sold_at = None
    if date_str:
        try:
            sold_at = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        except:
            pass

    upd = {
        "name": name,
        "merchant": merchant,
        "account_type": acc_type,
        "qty": qty,
        "price": price,
        "currency": currency,
    }
    if sold_at:
        upd["sold_at"] = sold_at

    sales_collection.update_one({"_id": ObjectId(id)}, {"$set": upd})
    return redirect(url_for("admin_home"))

@app.route("/accounts")
def accounts_index():
    # daftar penjualan akun terbaru
    items = list(sales_collection.find({"category": "akun"}).sort("sold_at", -1))

    # total total (qty & nilai) untuk ringkasan
    total_qty = 0
    total_amount = 0.0
    for a in items:
        q = int(a.get("qty", 1) or 1)
        p = float(a.get("price", 0) or 0)
        total_qty += q
        total_amount += q * p

    return render_template("accounts_index.html",
                           items=items,
                           total_qty=total_qty,
                           total_amount=total_amount)


def monitor_status():
            #"""Cek UP/DOWN berkala dan kirim notif saat transisi ke DOWN."""
        while True:
         for v in vps_collection.find():
            host, port = v.get("ip"), v.get("port")
            name = v.get("name", "(tanpa nama)")
            is_up_now = is_port_open(host, port)

            last_is_up = v.get("last_is_up")
            # Kalau sebelumnya UP (atau belum pernah diset) dan sekarang DOWN -> kirim notif
            if (last_is_up is True or last_is_up is None) and not is_up_now:
                try:
                    send_telegram_alert(f"❌ VPS DOWN\n\n😏 Nama : {name} | IP: {host} | Port: {port}")
                except Exception:
                    pass
                vps_collection.update_one(
                    {"_id": v["_id"]},
                    {"$set": {"last_is_up": is_up_now, "down_notified": True}}
                )
            else:
                # Update jejak saja, tanpa kirim pesan
                vps_collection.update_one({"_id": v["_id"]},
                                          {"$set": {"last_is_up": is_up_now}},
                                          upsert=False)
        time.sleep(CHECK_INTERVAL_SEC)

@app.template_filter("cur")
def cur(value, code="IDR", decimals=0):
    """Format angka dengan titik ribuan: 100000 -> IDR 100.000"""
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = 0.0
    fmt = f"{{:,.{decimals}f}}"
    text = fmt.format(n).replace(",", ".")
    return f"{code} {text}"



# ===== IMPORT EXCEL SUPPORT =====
IMPORT_CACHE = {}

def _cleanup_import_cache(max_age=1800):
    now = int(time.time())
    for k, v in list(IMPORT_CACHE.items()):
        if now - v.get("ts", now) > max_age:
            IMPORT_CACHE.pop(k, None)

def _norm(s):
    return re.sub(r'[^a-z0-9]+', '', str(s or '').strip().lower())

def _find_sheet(xls, target):
    t = _norm(target)
    for name in xls.sheet_names:
        if _norm(name) == t:
            return name
    for name in xls.sheet_names:
        if t in _norm(name):
            return name
    return None

VPS_ALIASES = {
    "name": {"name","nama"},
    "ip": {"ip","ipdomain","domain","host"},
    "port": {"port"},
    "expire_date": {"expiredate","expired","expire","tanggalexpired","tanggalexpire","tglexpire","tanggal"},
    "price": {"price","harga"},
    "currency": {"currency","curr","matauang","uang"}
}

AKUN_ALIASES = {
    "sold_at": {"date","tanggal","tgl","dateddmmyyyy"},
    "name": {"name","nama"},
    "merchant": {"merchant","toko","platform","marketplace"},
    "type": {"type","tipe","jenis"},
    "qty": {"qty","jumlah","qtypcs"},
    "price": {"price","harga"},
    "currency": {"currency","curr","matauang","uang"}
}

def _map_columns(df, aliases):
    cols_norm = {_norm(c): c for c in df.columns}
    out = {}
    for key, choices in aliases.items():
        found = None
        for ch in choices:
            if ch in cols_norm:
                found = cols_norm[ch]; break
        if not found:
            for nc, orig in cols_norm.items():
                if any(ch in nc for ch in choices):
                    found = orig; break
        if not found:
            for nc, orig in cols_norm.items():
                if any(nc in ch for ch in choices):
                    found = orig; break
        if found:
            out[key] = found
    return out

def _parse_date_ddmmyyyy(s):
    if s is None or str(s).strip() == '':
        return None
    if isinstance(s, (datetime.datetime, datetime.date)):
        return s.date() if isinstance(s, datetime.datetime) else s
    if hasattr(s, "to_pydatetime"):
        p = s.to_pydatetime()
        return p.date() if isinstance(p, datetime.datetime) else p
    try:
        n = float(str(s))
        if 30000 < n < 60000:
            base = dt(1899,12,30)
            return (base + datetime.timedelta(days=n)).date()
    except Exception:
        pass
    s = str(s).strip()
    for fmt in ("%d/%m/%Y","%d-%m-%Y","%Y-%m-%d","%d/%m/%y","%d-%m-%y"):
        try:
            return dt.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

@app.post("/admin/import")
@admin_required
def admin_import_excel():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".xlsx"):
        return redirect(url_for("admin_home"))
    try:
        xls = pd.ExcelFile(io.BytesIO(f.read()))
    except Exception as e:
        return f"Gagal membaca Excel: {e}", 400

    vps_list, akun_list = [], []

    vs = _find_sheet(xls, "vps")
    if vs:
        df = xls.parse(vs).fillna("")
        col = _map_columns(df, VPS_ALIASES)
        if all(k in col for k in ["name","ip","port"]):
            for _, r in df.iterrows():
                name = str(r[col["name"]]).strip()
                ip   = str(r[col["ip"]]).strip()
                port_raw = str(r[col["port"]]).strip()
                if not (name and ip and port_raw):
                    continue
                try:
                    port = int(float(port_raw))
                except:
                    continue
                exp = _parse_date_ddmmyyyy(r[col["expire_date"]]) if "expire_date" in col else None
                price = 0.0
                if "price" in col:
                    s = str(r[col["price"]]).replace(",", "").strip()
                    price = float(s) if s else 0.0
                curr = (str(r[col["currency"]]).strip() or "IDR").upper() if "currency" in col else "IDR"
                vps_list.append({"name": name, "ip": ip, "port": str(port),
                                 "expire_date": exp, "price": price, "currency": curr})

    asheet = _find_sheet(xls, "akun")
    if asheet:
        df = xls.parse(asheet).fillna("")
        col = _map_columns(df, AKUN_ALIASES)
        if "name" in col:
            for _, r in df.iterrows():
                name = str(r[col["name"]]).strip()
                if not name: 
                    continue
                sold = _parse_date_ddmmyyyy(r[col["sold_at"]]) if "sold_at" in col else None
                merch = str(r[col["merchant"]]).strip() if "merchant" in col else ""
                typ   = str(r[col["type"]]).strip() if "type" in col else ""
                qty   = r[col["qty"]] if "qty" in col else 1
                try:
                    qty = int(float(str(qty).strip() or 1))
                except:
                    qty = 1
                price = 0.0
                if "price" in col:
                    s = str(r[col["price"]]).replace(",", "").strip()
                    price = float(s) if s else 0.0
                curr = (str(r[col["currency"]]).strip() or "IDR").upper() if "currency" in col else "IDR"
                akun_list.append({"sold_at": sold, "name": name, "merchant": merch,
                                  "type": typ, "qty": qty, "price": price, "currency": curr})

    token = uuid.uuid4().hex
    _cleanup_import_cache()
    IMPORT_CACHE[token] = {"ts": int(time.time()), "vps": vps_list, "akun": akun_list}
    return redirect(url_for("admin_home", import_token=token))

@app.get("/admin/import/preview/<token>")
@admin_required
def admin_import_preview(token):
    pkg = IMPORT_CACHE.get(token)
    if not pkg:
        return {"ok": False, "error": "token expired"}, 404
    def d2s(d):
        return d.strftime("%d/%m/%Y") if isinstance(d, (datetime.date, datetime.datetime)) else ""
    vps  = [{**x, "expire_date": d2s(x.get("expire_date"))} for x in pkg.get("vps", [])]
    akun = [{**x, "sold_at":     d2s(x.get("sold_at"))}     for x in pkg.get("akun", [])]
    return {"ok": True, "vps": vps, "akun": akun}


@app.post("/admin/import/confirm/<token>")
@admin_required
def admin_import_confirm(token):
    pkg = IMPORT_CACHE.pop(token, None)
    if not pkg:
        return redirect(url_for("admin_home"))

    # Commit VPS with UPSERT and record sales only when newly inserted
    for v in pkg.get("vps", []):
        flt = {"name": v["name"], "ip": v["ip"], "port": v["port"]}
        doc = {
            "name": v["name"], "ip": v["ip"], "port": v["port"],
            "price": float(v.get("price") or 0),
            "currency": (v.get("currency") or "IDR").upper(),
            "status": "UNKNOWN",
            "notified": False,
        }
        if v.get("expire_date"):
            doc["expired"] = dt.combine(v["expire_date"], dt.min.time())

        res = vps_collection.update_one(flt, {"$set": doc}, upsert=True)
        if res.upserted_id:
            sales_collection.insert_one({
                "category": "vps",
                "ref_vps_id": res.upserted_id,
                "name": v["name"],
                "price": float(v.get("price") or 0),
                "currency": (v.get("currency") or "IDR").upper(),
                "sold_at": dt.utcnow(),
            })

    # Commit Akun
    for a in pkg.get("akun", []):
        doc = {
            "category": "akun",
            "name": a["name"], "merchant": a.get("merchant",""), "account_type": a.get("type",""),
            "qty": int(a.get("qty") or 1),
            "price": float(a.get("price") or 0),
            "currency": (a.get("currency") or "IDR").upper(),
        }
        if a.get("sold_at"):
            doc["sold_at"] = dt.combine(a["sold_at"], dt.min.time())
        sales_collection.insert_one(doc)

    return redirect(url_for("admin_home"))

@app.post("/admin/import/cancel/<token>")
@admin_required
def admin_import_cancel(token):
    IMPORT_CACHE.pop(token, None)
    return redirect(url_for("admin_home"))

# ===== MAIN =====
if __name__ == "__main__":
    threading.Thread(target=monitor_expired, daemon=True).start()
    threading.Thread(target=monitor_status, daemon=True).start()
    app.run(debug=True)
