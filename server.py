from flask import Flask, request, jsonify, send_file, redirect
from flask_cors import CORS
import json, os, hashlib, secrets, uuid
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

USERS_FILE   = "users.json"
CONTENT_FILE = "content.json"
IPTV_FILE    = "iptv.json"
ADMIN_KEY    = "admin1234"
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))

# ── HELPERS ─────────────────────────────────────────────────────────────
def load_json(f, default):
    if not os.path.exists(f): return default
    with open(f) as fp: return json.load(fp)

def save_json(f, data):
    with open(f, "w") as fp: json.dump(data, fp, indent=2)

def load_users():   return load_json(USERS_FILE,   {"users":{}, "tokens":{}})
def save_users(d):  save_json(USERS_FILE, d)
def load_content(): return load_json(CONTENT_FILE, {"movies":{}, "series":{}})
def save_content(d):save_json(CONTENT_FILE, d)
def load_iptv():    return load_json(IPTV_FILE,    {"channels":[], "categories":[]})
def save_iptv(d):   save_json(IPTV_FILE, d)

def hash_pw(pw):    return hashlib.sha256(pw.encode()).hexdigest()
def check_admin(r): return r.headers.get("X-Admin-Key") == ADMIN_KEY

# ── STATIC FILES ────────────────────────────────────────────────────────
@app.route("/")
def index(): return redirect("/app")

@app.route("/app")
def serve_app(): return send_file(os.path.join(BASE_DIR, "app.html"))

@app.route("/panel")
def serve_panel(): return send_file(os.path.join(BASE_DIR, "panel.html"))

@app.route("/playerjs.js")
def serve_playerjs(): return send_file(os.path.join(BASE_DIR, "playerjs.js"))

# ── AUTH ────────────────────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def api_login():
    d = request.get_json() or {}
    username = d.get("username","").strip().lower()
    password = d.get("password","")
    data = load_users()
    user = data["users"].get(username)
    if not user: return jsonify({"success":False,"error":"Usuario no encontrado"}), 401
    if user.get("password") != hash_pw(password): return jsonify({"success":False,"error":"Contraseña incorrecta"}), 401
    if not user.get("active",True): return jsonify({"success":False,"error":"Cuenta desactivada"}), 403
    exp = user.get("expires")
    if exp and datetime.fromisoformat(exp) < datetime.utcnow(): return jsonify({"success":False,"error":"Cuenta vencida"}), 403
    tok = secrets.token_hex(32)
    data["tokens"][tok] = {"username":username,"created":datetime.utcnow().isoformat()}
    save_users(data)
    return jsonify({"success":True,"token":tok,"username":user.get("display_name",username)})

@app.route("/api/verify", methods=["POST"])
def api_verify():
    d = request.get_json() or {}
    tok = d.get("token","")
    data = load_users()
    info = data["tokens"].get(tok)
    if not info: return jsonify({"valid":False})
    return jsonify({"valid":True,"username":info["username"]})

@app.route("/api/version")
def api_version(): return jsonify({"version":"1.0.0","apk_url":"","message":""})

# ── CONTENT ─────────────────────────────────────────────────────────────
@app.route("/api/links/<ctype>/<tmdb_id>")
def api_links(ctype, tmdb_id):
    data = load_content()
    store = "movies" if ctype == "movie" else "series"
    item = data[store].get(str(tmdb_id), {})
    return jsonify({"links": item.get("links", [])})

@app.route("/api/catalog")
def api_catalog():
    data = load_content()
    return jsonify({"movie_ids":list(data["movies"].keys()),"serie_ids":list(data["series"].keys())})

# ── IPTV ────────────────────────────────────────────────────────────────
@app.route("/api/iptv")
def api_iptv():
    return jsonify(load_iptv())

# ── ADMIN USERS ─────────────────────────────────────────────────────────
@app.route("/admin/users", methods=["GET"])
def admin_users_list():
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    data = load_users()
    return jsonify([{"username":u,"display_name":d.get("display_name",u),"active":d.get("active",True),"expires":d.get("expires"),"created":d.get("created")} for u,d in data["users"].items()])

@app.route("/admin/users", methods=["POST"])
def admin_users_create():
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    d = request.get_json() or {}
    username = d.get("username","").strip().lower()
    password = d.get("password","")
    if not username or not password: return jsonify({"error":"Faltan datos"}), 400
    data = load_users()
    if username in data["users"]: return jsonify({"error":"Ya existe"}), 409
    days = d.get("days")
    expires = (datetime.utcnow()+timedelta(days=int(days))).isoformat() if days else None
    data["users"][username] = {"password":hash_pw(password),"display_name":d.get("display_name",username),"active":True,"expires":expires,"created":datetime.utcnow().isoformat()}
    save_users(data)
    return jsonify({"success":True})

@app.route("/admin/users/<username>", methods=["DELETE"])
def admin_users_delete(username):
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    data = load_users()
    if username not in data["users"]: return jsonify({"error":"No encontrado"}), 404
    del data["users"][username]; save_users(data)
    return jsonify({"success":True})

@app.route("/admin/users/<username>/toggle", methods=["POST"])
def admin_users_toggle(username):
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    data = load_users()
    if username not in data["users"]: return jsonify({"error":"No encontrado"}), 404
    data["users"][username]["active"] = not data["users"][username].get("active",True)
    save_users(data)
    return jsonify({"success":True,"active":data["users"][username]["active"]})

@app.route("/admin/users/<username>/extend", methods=["POST"])
def admin_users_extend(username):
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    d = request.get_json() or {}
    days = int(d.get("days",30))
    data = load_users()
    if username not in data["users"]: return jsonify({"error":"No encontrado"}), 404
    user = data["users"][username]
    exp = user.get("expires")
    base = datetime.fromisoformat(exp) if exp else datetime.utcnow()
    if base < datetime.utcnow(): base = datetime.utcnow()
    user["expires"] = (base+timedelta(days=days)).isoformat()
    save_users(data); return jsonify({"success":True,"expires":user["expires"]})

# ── ADMIN CONTENT ────────────────────────────────────────────────────────
@app.route("/admin/content", methods=["GET"])
def admin_content_list():
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    data = load_content()
    result = []
    for tid,item in data["movies"].items(): result.append({**item,"tmdb_id":tid,"type":"movie"})
    for tid,item in data["series"].items(): result.append({**item,"tmdb_id":tid,"type":"tv"})
    result.sort(key=lambda x: x.get("updated",""), reverse=True)
    return jsonify(result)

@app.route("/admin/content", methods=["POST"])
def admin_content_save():
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    d = request.get_json() or {}
    tmdb_id = str(d.get("tmdb_id",""))
    ctype = d.get("type","movie")
    if not tmdb_id: return jsonify({"error":"Falta tmdb_id"}), 400
    data = load_content()
    store = "movies" if ctype=="movie" else "series"
    data[store][tmdb_id] = {"title":d.get("title",""),"year":d.get("year",""),"poster":d.get("poster",""),"links":d.get("links",[]),"updated":datetime.utcnow().isoformat()}
    save_content(data); return jsonify({"success":True})

@app.route("/admin/content/<ctype>/<tid>", methods=["GET"])
def admin_content_get(ctype, tid):
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    data = load_content()
    store = "movies" if ctype=="movie" else "series"
    item = data[store].get(tid)
    if not item: return jsonify({"error":"No encontrado"}), 404
    return jsonify({**item,"tmdb_id":tid,"type":ctype})

@app.route("/admin/content/<ctype>/<tid>", methods=["DELETE"])
def admin_content_delete(ctype, tid):
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    data = load_content()
    store = "movies" if ctype=="movie" else "series"
    if tid not in data[store]: return jsonify({"error":"No encontrado"}), 404
    del data[store][tid]; save_content(data); return jsonify({"success":True})

# ── ADMIN IPTV ────────────────────────────────────────────────────────────
@app.route("/admin/iptv", methods=["GET"])
def admin_iptv_list():
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    return jsonify(load_iptv())

@app.route("/admin/iptv", methods=["POST"])
def admin_iptv_add():
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    d = request.get_json() or {}
    name = d.get("name","").strip()
    url  = d.get("url","").strip()
    if not name or not url: return jsonify({"error":"Nombre y URL requeridos"}), 400
    data = load_iptv()
    ch = {
        "id":      str(uuid.uuid4())[:8],
        "name":    name,
        "url":     url,
        "logo":    d.get("logo",""),
        "category":d.get("category","General"),
        "group":   d.get("group",""),
        "created": datetime.utcnow().isoformat()
    }
    data["channels"].append(ch)
    cats = list({c["category"] for c in data["channels"]})
    data["categories"] = sorted(cats)
    save_iptv(data); return jsonify({"success":True,"channel":ch})

@app.route("/admin/iptv/<ch_id>", methods=["PUT"])
def admin_iptv_update(ch_id):
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    d = request.get_json() or {}
    data = load_iptv()
    ch = next((c for c in data["channels"] if c["id"]==ch_id), None)
    if not ch: return jsonify({"error":"No encontrado"}), 404
    for k in ["name","url","logo","category","group"]:
        if k in d: ch[k] = d[k]
    data["categories"] = sorted(list({c["category"] for c in data["channels"]}))
    save_iptv(data); return jsonify({"success":True})

@app.route("/admin/iptv/<ch_id>", methods=["DELETE"])
def admin_iptv_delete(ch_id):
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    data = load_iptv()
    data["channels"] = [c for c in data["channels"] if c["id"]!=ch_id]
    data["categories"] = sorted(list({c["category"] for c in data["channels"]}))
    save_iptv(data); return jsonify({"success":True})

@app.route("/admin/iptv/import", methods=["POST"])
def admin_iptv_import():
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    d = request.get_json() or {}
    m3u = d.get("m3u","")
    data = load_iptv()
    added = 0
    lines = m3u.split("\n")
    current = {}
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF"):
            name = line.split(",")[-1].strip() if "," in line else "Canal"
            logo = ""
            cat  = "General"
            if 'tvg-logo="' in line: logo = line.split('tvg-logo="')[1].split('"')[0]
            if 'group-title="' in line: cat = line.split('group-title="')[1].split('"')[0]
            current = {"name":name,"logo":logo,"category":cat}
        elif line and not line.startswith("#") and current:
            ch = {**current,"id":str(uuid.uuid4())[:8],"url":line,"group":"","created":datetime.utcnow().isoformat()}
            data["channels"].append(ch); added += 1; current = {}
    data["categories"] = sorted(list({c["category"] for c in data["channels"]}))
    save_iptv(data); return jsonify({"success":True,"added":added})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
