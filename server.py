from flask import Flask, request, jsonify, send_file, redirect
from flask_cors import CORS
import json, os, hashlib, secrets
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

USERS_FILE = "users.json"
CONTENT_FILE = "content.json"
ADMIN_KEY = "admin1234"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_users():
    if not os.path.exists(USERS_FILE):
        return {"users": {}, "tokens": {}}
    with open(USERS_FILE) as f:
        return json.load(f)

def save_users(data):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_content():
    if not os.path.exists(CONTENT_FILE):
        return {"movies": {}, "series": {}}
    with open(CONTENT_FILE) as f:
        return json.load(f)

def save_content(data):
    with open(CONTENT_FILE, "w") as f:
        json.dump(data, f, indent=2)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def check_admin(req):
    return req.headers.get("X-Admin-Key") == ADMIN_KEY

# FILE ROUTES
@app.route("/")
def index():
    return redirect("/app")

@app.route("/app")
def serve_app():
    return send_file(os.path.join(BASE_DIR, "app.html"))

@app.route("/panel")
def serve_panel():
    return send_file(os.path.join(BASE_DIR, "panel.html"))

# AUTH
@app.route("/api/login", methods=["POST"])
def api_login():
    d = request.get_json() or {}
    username = d.get("username", "").strip().lower()
    password = d.get("password", "")
    data = load_users()
    user = data["users"].get(username)
    if not user:
        return jsonify({"success": False, "error": "Usuario no encontrado"}), 401
    if user.get("password") != hash_pw(password):
        return jsonify({"success": False, "error": "Contraseña incorrecta"}), 401
    if not user.get("active", True):
        return jsonify({"success": False, "error": "Cuenta desactivada"}), 403
    exp = user.get("expires")
    if exp and datetime.fromisoformat(exp) < datetime.utcnow():
        return jsonify({"success": False, "error": "Cuenta vencida"}), 403
    token = secrets.token_hex(32)
    data["tokens"][token] = {"username": username, "created": datetime.utcnow().isoformat()}
    save_users(data)
    return jsonify({"success": True, "token": token, "username": user.get("display_name", username)})

@app.route("/api/verify", methods=["POST"])
def api_verify():
    d = request.get_json() or {}
    tok = d.get("token", "")
    data = load_users()
    info = data["tokens"].get(tok)
    if not info:
        return jsonify({"valid": False})
    return jsonify({"valid": True, "username": info["username"]})

@app.route("/api/version")
def api_version():
    return jsonify({"version": "1.0.0", "apk_url": "", "message": ""})

@app.route("/api/links/<content_type>/<tmdb_id>")
def api_links(content_type, tmdb_id):
    data = load_content()
    store = "movies" if content_type == "movie" else "series"
    item = data[store].get(str(tmdb_id), {})
    return jsonify({"links": item.get("links", [])})

@app.route("/api/catalog")
def api_catalog():
    data = load_content()
    return jsonify({
        "movie_ids": list(data["movies"].keys()),
        "serie_ids": list(data["series"].keys())
    })

# ADMIN USERS
@app.route("/admin/users", methods=["GET"])
def admin_users_list():
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 403
    data = load_users()
    result = []
    for uname, u in data["users"].items():
        result.append({
            "username": uname,
            "display_name": u.get("display_name", uname),
            "active": u.get("active", True),
            "expires": u.get("expires"),
            "created": u.get("created")
        })
    return jsonify(result)

@app.route("/admin/users", methods=["POST"])
def admin_users_create():
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 403
    d = request.get_json() or {}
    username = d.get("username", "").strip().lower()
    password = d.get("password", "")
    display_name = d.get("display_name", username)
    days = d.get("days")
    if not username or not password:
        return jsonify({"error": "Faltan datos"}), 400
    data = load_users()
    if username in data["users"]:
        return jsonify({"error": "Usuario ya existe"}), 409
    expires = None
    if days:
        expires = (datetime.utcnow() + timedelta(days=int(days))).isoformat()
    data["users"][username] = {
        "password": hash_pw(password),
        "display_name": display_name,
        "active": True,
        "expires": expires,
        "created": datetime.utcnow().isoformat()
    }
    save_users(data)
    return jsonify({"success": True})

@app.route("/admin/users/<username>", methods=["DELETE"])
def admin_users_delete(username):
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 403
    data = load_users()
    if username not in data["users"]:
        return jsonify({"error": "No encontrado"}), 404
    del data["users"][username]
    save_users(data)
    return jsonify({"success": True})

@app.route("/admin/users/<username>/toggle", methods=["POST"])
def admin_users_toggle(username):
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 403
    data = load_users()
    if username not in data["users"]:
        return jsonify({"error": "No encontrado"}), 404
    data["users"][username]["active"] = not data["users"][username].get("active", True)
    save_users(data)
    return jsonify({"success": True, "active": data["users"][username]["active"]})

@app.route("/admin/users/<username>/extend", methods=["POST"])
def admin_users_extend(username):
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 403
    d = request.get_json() or {}
    days = int(d.get("days", 30))
    data = load_users()
    if username not in data["users"]:
        return jsonify({"error": "No encontrado"}), 404
    user = data["users"][username]
    exp = user.get("expires")
    base = datetime.fromisoformat(exp) if exp else datetime.utcnow()
    if base < datetime.utcnow():
        base = datetime.utcnow()
    user["expires"] = (base + timedelta(days=days)).isoformat()
    save_users(data)
    return jsonify({"success": True, "expires": user["expires"]})

# ADMIN CONTENT
@app.route("/admin/content", methods=["GET"])
def admin_content_list():
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 403
    data = load_content()
    result = []
    for tid, item in data["movies"].items():
        result.append({**item, "tmdb_id": tid, "type": "movie"})
    for tid, item in data["series"].items():
        result.append({**item, "tmdb_id": tid, "type": "tv"})
    result.sort(key=lambda x: x.get("updated", ""), reverse=True)
    return jsonify(result)

@app.route("/admin/content", methods=["POST"])
def admin_content_save():
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 403
    d = request.get_json() or {}
    tmdb_id = str(d.get("tmdb_id", ""))
    ctype = d.get("type", "movie")
    if not tmdb_id: return jsonify({"error": "Falta tmdb_id"}), 400
    data = load_content()
    store = "movies" if ctype == "movie" else "series"
    data[store][tmdb_id] = {
        "title": d.get("title", ""),
        "year": d.get("year", ""),
        "poster": d.get("poster", ""),
        "links": d.get("links", []),
        "updated": datetime.utcnow().isoformat()
    }
    save_content(data)
    return jsonify({"success": True})

@app.route("/admin/content/<content_type>/<tid>", methods=["GET"])
def admin_content_get(content_type, tid):
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 403
    data = load_content()
    store = "movies" if content_type == "movie" else "series"
    item = data[store].get(tid)
    if not item: return jsonify({"error": "No encontrado"}), 404
    return jsonify({**item, "tmdb_id": tid, "type": content_type})

@app.route("/admin/content/<content_type>/<tid>", methods=["DELETE"])
def admin_content_delete(content_type, tid):
    if not check_admin(request): return jsonify({"error": "Unauthorized"}), 403
    data = load_content()
    store = "movies" if content_type == "movie" else "series"
    if tid not in data[store]: return jsonify({"error": "No encontrado"}), 404
    del data[store][tid]
    save_content(data)
    return jsonify({"success": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
