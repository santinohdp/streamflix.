from flask import Flask, request, jsonify, send_file, redirect, Response, stream_with_context
from flask_cors import CORS
import json, os, hashlib, secrets, uuid, re
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin, quote, unquote

try:
    import requests as req_lib
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

USERS_FILE   = "users.json"
CONTENT_FILE = "content.json"
IPTV_FILE    = "iptv.json"
ADMIN_KEY    = "admin1234"
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))

PROXY_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'es-AR,es;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
}

# ── HELPERS ──────────────────────────────────────────────────────────────────
def load_json(f, default):
    if not os.path.exists(f): return default
    with open(f) as fp: return json.load(fp)

def save_json(f, data): save_json_safe(f, data)
def save_json_safe(f, data):
    with open(f, "w") as fp: json.dump(data, fp, indent=2)

def load_users():   return load_json(USERS_FILE,   {"users":{}, "tokens":{}})
def save_users(d):  save_json_safe(USERS_FILE, d)
def load_content(): return load_json(CONTENT_FILE, {"movies":{}, "series":{}})
def save_content(d):save_json_safe(CONTENT_FILE, d)
def load_iptv():    return load_json(IPTV_FILE,    {"channels":[], "categories":[]})
def save_iptv(d):   save_json_safe(IPTV_FILE, d)

def hash_pw(pw):    return hashlib.sha256(pw.encode()).hexdigest()
def check_admin(r): return r.headers.get("X-Admin-Key") == ADMIN_KEY

def cors_headers():
    return {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
        'Access-Control-Allow-Headers': '*',
        'Access-Control-Expose-Headers': '*',
    }

# ── STATIC FILES ──────────────────────────────────────────────────────────────
@app.route("/")
def index(): return redirect("/app")

@app.route("/app")
def serve_app(): return send_file(os.path.join(BASE_DIR, "app.html"))

@app.route("/panel")
def serve_panel(): return send_file(os.path.join(BASE_DIR, "panel.html"))

@app.route("/mac-panel")
def serve_mac_panel(): return send_file(os.path.join(BASE_DIR, "mac_panel.html"))

@app.route("/fenix")
def serve_fenix(): return send_file(os.path.join(BASE_DIR, "fenix.html"))

@app.route("/playerjs.js")
def serve_playerjs():
    pjs = os.path.join(BASE_DIR, "playerjs.js")
    if os.path.exists(pjs): return send_file(pjs)
    return "// playerjs not found", 404

# ── HLS PROXY ─────────────────────────────────────────────────────────────────
# Rewrites a single URL to go through our proxy
def proxify(url, base_url):
    """Make a URL absolute and wrap it in our proxy"""
    if not url or url.startswith('#') or url.startswith('data:'):
        return url
    abs_url = urljoin(base_url, url.strip())
    return f"/proxy/hls?url={quote(abs_url, safe='')}"

def rewrite_m3u8(content, base_url):
    """Rewrite all URIs inside an m3u8 playlist to go through our proxy"""
    lines = content.split('\n')
    out   = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append(line); continue
        # Rewrite URI= attributes (encryption keys, etc.)
        if 'URI="' in line or "URI='" in line:
            line = re.sub(
                r'URI=["\']([^"\']+)["\']',
                lambda m: f'URI="{proxify(m.group(1), base_url)}"',
                line
            )
        # Rewrite segment/playlist lines (not comment lines)
        if not stripped.startswith('#') and (
            stripped.endswith('.m3u8') or stripped.endswith('.ts') or
            stripped.endswith('.mp4') or stripped.endswith('.aac') or
            stripped.endswith('.vtt') or stripped.startswith('http') or
            '/' in stripped
        ):
            out.append(proxify(stripped, base_url))
        else:
            out.append(line)
    return '\n'.join(out)

@app.route("/proxy/hls")
def proxy_hls():
    if not HAS_REQUESTS:
        return "requests library not installed. Run: pip install requests", 503
    
    url = request.args.get('url', '').strip()
    if not url:
        return "No URL provided", 400
    url = unquote(url)
    
    # Basic security: only allow http/https
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return "Invalid scheme", 400

    headers = dict(PROXY_HEADERS)
    # Forward range header for seeking
    if 'Range' in request.headers:
        headers['Range'] = request.headers['Range']
    # Set Referer/Origin to the stream's own domain to bypass hotlink protection
    headers['Referer'] = f"{parsed.scheme}://{parsed.netloc}/"
    headers['Origin']  = f"{parsed.scheme}://{parsed.netloc}"

    try:
        upstream = req_lib.get(
            url, headers=headers, stream=True,
            timeout=15, allow_redirects=True,
            verify=False  # some channels use self-signed certs
        )
        ct = upstream.headers.get('Content-Type', '').lower()
        is_m3u8 = (
            'm3u' in ct or 'mpegurl' in ct or
            url.lower().endswith('.m3u8') or
            url.lower().endswith('.m3u')
        )

        resp_headers = dict(cors_headers())
        resp_headers['Cache-Control'] = 'no-cache, no-store'

        if is_m3u8:
            # Rewrite the playlist so all segment URLs go through our proxy too
            content = upstream.content.decode('utf-8', errors='replace')
            rewritten = rewrite_m3u8(content, url)
            resp_headers['Content-Type'] = 'application/vnd.apple.mpegurl; charset=utf-8'
            return Response(rewritten, status=upstream.status_code, headers=resp_headers)
        else:
            # Stream binary (TS segments, MP4, etc.)
            resp_headers['Content-Type'] = ct or 'application/octet-stream'
            if 'Content-Length' in upstream.headers:
                resp_headers['Content-Length'] = upstream.headers['Content-Length']
            if 'Accept-Ranges' in upstream.headers:
                resp_headers['Accept-Ranges'] = upstream.headers['Accept-Ranges']
            if 'Content-Range' in upstream.headers:
                resp_headers['Content-Range'] = upstream.headers['Content-Range']

            def generate():
                try:
                    for chunk in upstream.iter_content(chunk_size=65536):
                        if chunk: yield chunk
                except Exception as e:
                    print(f"[PROXY] Stream error: {e}")

            return Response(
                stream_with_context(generate()),
                status=upstream.status_code,
                headers=resp_headers
            )
    except req_lib.exceptions.SSLError:
        # Retry without SSL verification (already false but just in case)
        return "SSL Error on upstream", 502
    except req_lib.exceptions.ConnectionError as e:
        return f"Connection error: {str(e)[:200]}", 502
    except req_lib.exceptions.Timeout:
        return "Upstream timeout", 504
    except Exception as e:
        return f"Proxy error: {str(e)[:200]}", 500

@app.route("/proxy/hls", methods=["OPTIONS"])
def proxy_hls_options():
    return Response("", headers=cors_headers())

# ── AUTH ──────────────────────────────────────────────────────────────────────
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

# ── CONTENT ───────────────────────────────────────────────────────────────────
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

# ── IPTV ──────────────────────────────────────────────────────────────────────
@app.route("/api/iptv")
def api_iptv(): return jsonify(load_iptv())

# ── ADMIN USERS ───────────────────────────────────────────────────────────────
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
    save_users(data); return jsonify({"success":True})

@app.route("/admin/users/<username>", methods=["DELETE"])
def admin_users_delete(username):
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    data = load_users()
    if username not in data["users"]: return jsonify({"error":"No encontrado"}), 404
    del data["users"][username]; save_users(data); return jsonify({"success":True})

@app.route("/admin/users/<username>/toggle", methods=["POST"])
def admin_users_toggle(username):
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    data = load_users()
    if username not in data["users"]: return jsonify({"error":"No encontrado"}), 404
    data["users"][username]["active"] = not data["users"][username].get("active",True)
    save_users(data); return jsonify({"success":True,"active":data["users"][username]["active"]})

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

# ── ADMIN CONTENT ─────────────────────────────────────────────────────────────
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

# ── ADMIN IPTV ─────────────────────────────────────────────────────────────────
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
    ch = {"id":str(uuid.uuid4())[:8],"name":name,"url":url,"logo":d.get("logo",""),"category":d.get("category","General"),"group":d.get("group",""),"created":datetime.utcnow().isoformat()}
    data["channels"].append(ch)
    data["categories"] = sorted(list({c["category"] for c in data["channels"]}))
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
    data = load_iptv(); added = 0
    lines = m3u.split("\n"); current = {}
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF"):
            name = line.split(",")[-1].strip() if "," in line else "Canal"
            logo = ""; cat = "General"
            if 'tvg-logo="' in line: logo = line.split('tvg-logo="')[1].split('"')[0]
            if 'group-title="' in line: cat = line.split('group-title="')[1].split('"')[0]
            current = {"name":name,"logo":logo,"category":cat}
        elif line and not line.startswith("#") and current:
            ch = {**current,"id":str(uuid.uuid4())[:8],"url":line,"group":"","created":datetime.utcnow().isoformat()}
            data["channels"].append(ch); added += 1; current = {}
    data["categories"] = sorted(list({c["category"] for c in data["channels"]}))
    save_iptv(data); return jsonify({"success":True,"added":added})

# ── XTREAM CODES ─────────────────────────────────────────────────────────────
@app.route("/admin/iptv/xtream", methods=["POST"])
def admin_iptv_xtream():
    if not check_admin(request): return jsonify({"error":"Unauthorized"}), 403
    d = request.get_json() or {}
    server = d.get("server","").strip().rstrip("/")
    user   = d.get("username","").strip()
    pw     = d.get("password","").strip()
    if not server or not user or not pw:
        return jsonify({"error":"Faltan datos: server, username, password"}), 400
    if not HAS_REQUESTS:
        return jsonify({"error":"Instala: pip install requests"}), 503
    import requests as rq
    try:
        h = dict(PROXY_HEADERS)
        cat_r = rq.get(f"{server}/player_api.php?username={user}&password={pw}&action=get_live_categories", timeout=15, headers=h)
        cats  = cat_r.json() if cat_r.status_code==200 else []
        cat_map = {str(c2.get("category_id","")): c2.get("category_name","General") for c2 in cats}
        streams_r = rq.get(f"{server}/player_api.php?username={user}&password={pw}&action=get_live_streams", timeout=30, headers=h)
        streams   = streams_r.json() if streams_r.status_code==200 else []
        data  = load_iptv()
        added = 0
        for s in streams:
            sid  = s.get("stream_id","")
            if not sid: continue
            ext  = s.get("container_extension","ts")
            cat  = cat_map.get(str(s.get("category_id","")),"General")
            ch   = {
                "id":       str(uuid.uuid4())[:8],
                "name":     s.get("name","Canal"),
                "url":      f"{server}/live/{user}/{pw}/{sid}.{ext}",
                "logo":     s.get("stream_icon",""),
                "category": cat,
                "group":    "",
                "xtream":   True,
                "created":  datetime.utcnow().isoformat()
            }
            data["channels"].append(ch); added += 1
        data["categories"] = sorted(list({c2["category"] for c2 in data["channels"]}))
        save_iptv(data)
        return jsonify({"success":True,"added":added,"categories":len(cat_map)})
    except Exception as e:
        return jsonify({"error":str(e)[:300]}), 500

@app.route("/api/iptv/xtream/info", methods=["POST"])
def api_xtream_info():
    d = request.get_json() or {}
    server = d.get("server","").strip().rstrip("/")
    user   = d.get("username","").strip()
    pw     = d.get("password","").strip()
    if not server or not user or not pw:
        return jsonify({"valid":False,"error":"Faltan datos"}), 400
    if not HAS_REQUESTS:
        return jsonify({"valid":False,"error":"requests no instalado"}), 503
    import requests as rq
    try:
        r = rq.get(f"{server}/player_api.php?username={user}&password={pw}", timeout=10, headers=PROXY_HEADERS)
        info = r.json().get("user_info",{})
        return jsonify({"valid":True,"status":info.get("status",""),"expiry":info.get("exp_date",""),"max_conns":info.get("max_connections","")})
    except Exception as e:
        return jsonify({"valid":False,"error":str(e)[:200]}), 500



# ── MAC → LISTA ───────────────────────────────────────────────────────────────
MAC_FILE = "mac_listas.json"

def load_macs():   return load_json(MAC_FILE, {})
def save_macs(d):  save_json_safe(MAC_FILE, d)

def normalize_mac(mac):
    return mac.strip().upper().replace("-", ":")

@app.route("/api/mac/<mac>", methods=["GET"])
def api_mac_get(mac):
    mac = normalize_mac(mac)
    macs = load_macs()
    entry = macs.get(mac)
    if not entry:
        return jsonify({"found": False}), 404
    return jsonify({"found": True, "mac": mac, "name": entry.get("name", ""), "url": entry.get("url", "")})

@app.route("/api/mac", methods=["POST"])
def api_mac_set():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    d = request.get_json() or {}
    mac = normalize_mac(d.get("mac", ""))
    url = d.get("url", "").strip()
    name = d.get("name", "").strip()
    if not mac or not url:
        return jsonify({"error": "Faltan mac y url"}), 400
    macs = load_macs()
    macs[mac] = {"url": url, "name": name, "updated": datetime.utcnow().isoformat()}
    save_macs(macs)
    return jsonify({"success": True, "mac": mac})

@app.route("/api/mac", methods=["GET"])
def api_mac_list():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    macs = load_macs()
    result = [{"mac": k, **v} for k, v in macs.items()]
    result.sort(key=lambda x: x.get("updated", ""), reverse=True)
    return jsonify(result)

@app.route("/api/mac/<mac>", methods=["DELETE"])
def api_mac_delete(mac):
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    mac = normalize_mac(mac)
    macs = load_macs()
    if mac not in macs:
        return jsonify({"error": "No encontrado"}), 404
    del macs[mac]
    save_macs(macs)
    return jsonify({"success": True})

if __name__ == "__main__":
    if not HAS_REQUESTS:
        print("WARNING: 'requests' library not found. IPTV proxy won't work.")
        print("Install it: pip install requests")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
