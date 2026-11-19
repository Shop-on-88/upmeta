#!/usr/bin/env python3
"""UP META 업무 지시·보고 보드 — 표준 라이브러리만 사용 (설치할 패키지 없음).

환경변수:
  PORT            기본 8090
  DB_PATH         기본 ./taskboard.db
  BOT_TOKEN       텔레그램 봇 토큰 (없으면 알림 끔)
  TG_CHAT_ID      알림 받을 그룹 ID (없으면 같은 폴더의 chat_id 파일을 읽음)
  BOARD_URL       알림에 넣을 보드 주소 (선택)
  DIGEST_HOUR     매일 현황판을 새 글로 올리는 시각(0~23, 한국 시간). 기본 9, 끄려면 -1
"""
import hashlib, hmac, json, os, queue, re, secrets, sqlite3, threading, time
import urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8090"))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "taskboard.db"))
TG_TOKEN = os.environ.get("TG_BOT_TOKEN") or os.environ.get("BOT_TOKEN", "")
KST = timezone(timedelta(hours=9))
SETUP_FILE = os.path.join(BASE, "setup_code")


def tg_chat():
    cid = os.environ.get("TG_CHAT_ID", "")
    if not cid:
        try:
            with open(os.path.join(BASE, "chat_id")) as f:
                cid = f.read().strip()
        except OSError:
            pass
    return cid
BOARD_URL = os.environ.get("BOARD_URL", "")
DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "9"))

STATUS = {"new": "미확인", "ack": "확인", "doing": "진행 중", "hold": "보류", "stop": "중지", "done": "완료"}
NEED_NOTE = {"hold": "보류 사유", "stop": "중지 사유", "done": "완료 내용"}
PRIORITY = {"high": "긴급", "normal": "보통", "low": "낮음"}
ROLES = {"admin": "관리자", "lead": "팀장", "staff": "직원"}
INVITE_DAYS = 7
CATS = ["광고관련", "계정관련", "결제관련", "홈페이지관련", "기타"]

lock = threading.Lock()
listeners = set()
fails = {}  # ip -> (count, until)


def db():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
          role TEXT NOT NULL, salt TEXT NOT NULL, hash TEXT NOT NULL, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created REAL);
        CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, title TEXT NOT NULL, detail TEXT DEFAULT '',
          assignee_id INTEGER, creator_id INTEGER, priority TEXT DEFAULT 'normal', due TEXT DEFAULT '',
          status TEXT DEFAULT 'new', status_note TEXT DEFAULT '', created REAL, updated REAL);
        CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL
          REFERENCES tasks(id) ON DELETE CASCADE, user_id INTEGER, kind TEXT, text TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS invites(token TEXT PRIMARY KEY, role TEXT NOT NULL, created REAL, expires REAL);
        """)
        if "category" not in [r["name"] for r in c.execute("PRAGMA table_info(tasks)")]:
            c.execute("ALTER TABLE tasks ADD COLUMN category TEXT DEFAULT '기타'")


def new_invite(c, role):
    tok = secrets.token_urlsafe(18)
    now = time.time()
    c.execute("INSERT INTO invites VALUES(?,?,?,?)", (tok, role, now, now + INVITE_DAYS * 86400))
    return tok


def get_invite(c, tok):
    c.execute("DELETE FROM invites WHERE expires<?", (time.time(),))
    return c.execute("SELECT * FROM invites WHERE token=?", (str(tok or ""),)).fetchone()


def hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 120000).hex()


def notify(text):
    chat = tg_chat()
    if not (TG_TOKEN and chat):
        return
    if BOARD_URL:
        text += "\n\n" + BOARD_URL

    def send():
        try:
            data = urllib.parse.urlencode({"chat_id": chat, "text": text,
                                           "disable_web_page_preview": "true"}).encode()
            urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % TG_TOKEN, data, timeout=10)
        except Exception as e:
            print("telegram error:", e, flush=True)
    threading.Thread(target=send, daemon=True).start()


status_dirty = threading.Event()
STATUS_FILE = os.path.join(BASE, "status_msg")


def tg_call(method, **params):
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen("https://api.telegram.org/bot%s/%s" % (TG_TOKEN, method), data, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"ok": False, "description": str(e)}
    except Exception as e:
        return {"ok": False, "description": str(e)}


SECTIONS = [("new", "", 5), ("doing", "", 5), ("ack", "", 4), ("hold", "사유", 4), ("done", "완료", 4)]
VENV_PY = "/root/upmeta/demo-bot/venv/bin/python"  # 서버 기본 파이썬에 Pillow가 없을 때 사용


def status_data():
    """현황판에 들어갈 내용"""
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    day0 = datetime(now.year, now.month, now.day, tzinfo=KST).timestamp()
    with db() as c:
        rows = c.execute("SELECT * FROM tasks ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, "
                         "CASE due WHEN '' THEN '9' ELSE due END, updated DESC").fetchall()
        names = {r["id"]: r["name"] for r in c.execute("SELECT id,name FROM users")}
    groups = {k: [r for r in rows if r["status"] == k] for k in STATUS}
    groups["done"] = [r for r in groups["done"] if r["updated"] >= day0]
    sections = []
    for k, note_label, limit in SECTIONS:
        items = [{"cat": r["category"] or "기타", "title": r["title"], "who": names.get(r["assignee_id"], "미지정"),
                  "due": r["due"][5:].replace("-", "/") if r["due"] else "",
                  "late": bool(r["due"]) and r["due"] < today and k != "done", "hot": r["priority"] == "high",
                  "note": r["status_note"] if note_label else ""} for r in groups[k][:limit]]
        sections.append({"key": k, "total": len(groups[k]), "note_label": note_label, "items": items})
    return {"now": "%d/%d %02d:%02d" % (now.month, now.day, now.hour, now.minute),
            "counts": {k: len(v) for k, v in groups.items()}, "sections": sections, "url": BOARD_URL}


def status_card(data):
    """카드 이미지(JPEG). 만들 수 없으면 None"""
    try:
        import card
        return card.render(data)
    except ImportError:
        pass
    except Exception as e:
        print("card error:", e, flush=True)
        return None
    try:
        import subprocess
        r = subprocess.run([VENV_PY, os.path.join(BASE, "card.py")], input=json.dumps(data).encode(),
                           capture_output=True, timeout=40)
        if r.returncode == 0 and r.stdout[:2] == b"\xff\xd8":
            return r.stdout
        print("card error:", r.stderr.decode(errors="replace")[-300:], flush=True)
    except Exception as e:
        print("card error:", e, flush=True)
    return None


def status_text(data):
    """카드를 만들 수 없을 때만 쓰는 글 현황판"""
    names = {"new": "미확인", "ack": "확인", "doing": "진행 중", "hold": "보류", "stop": "중지", "done": "오늘 완료"}
    out = ["UP META 업무 현황판 · %s 기준" % data["now"], "",
           "  ".join("%s %d" % (names[k], data["counts"][k]) for k in names)]
    for sec in data["sections"]:
        if sec["items"]:
            out += ["", "[%s] %d건" % (names[sec["key"]], sec["total"])]
            out += ["- (%s) %s / %s%s" % (i["cat"], i["title"][:60], i["who"], (" / ~" + i["due"]) if i["due"] else "")
                    for i in sec["items"]]
    return "\n".join(out + ["", data["url"]])[:4000]


def tg_photo(method, photo, **params):
    """사진을 붙여 보내는 텔레그램 호출 (sendPhoto / editMessageMedia)"""
    bd = "----tb" + secrets.token_hex(12)
    body = b""
    for k, v in params.items():
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (bd, k, v)).encode()
    body += ("--%s\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"board.jpg\"\r\n"
             "Content-Type: image/jpeg\r\n\r\n" % bd).encode() + photo + ("\r\n--%s--\r\n" % bd).encode()
    req = urllib.request.Request("https://api.telegram.org/bot%s/%s" % (TG_TOKEN, method), body,
                                 {"Content-Type": "multipart/form-data; boundary=" + bd})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"ok": False, "description": str(e)}
    except Exception as e:
        return {"ok": False, "description": str(e)}


status_lock = threading.Lock()


def status_update(fresh=False):
    """현황판을 고쳐 씀. fresh=True 이거나 고칠 글이 없으면 새로 올림"""
    with status_lock:
        _status_update(fresh)


def _status_update(fresh):
    chat = tg_chat()
    if not (TG_TOKEN and chat):
        return
    data = status_data()
    photo = status_card(data)
    kind = "photo" if photo else "text"
    caption = "UP META 업무 현황판 · %s 기준%s" % (data["now"], ("\n" + BOARD_URL) if BOARD_URL else "")
    try:
        with open(STATUS_FILE) as f:
            st = json.load(f)
    except Exception:
        st = {}
    if st.get("chat") == chat and st.get("id"):
        if not fresh and st.get("kind", "text") == kind:
            if photo:
                r = tg_photo("editMessageMedia", photo, chat_id=chat, message_id=st["id"],
                             media=json.dumps({"type": "photo", "media": "attach://photo", "caption": caption}))
            else:
                r = tg_call("editMessageText", chat_id=chat, message_id=st["id"], text=status_text(data),
                            disable_web_page_preview="true")
            desc = str(r.get("description", ""))
            if r.get("ok") or "not modified" in desc:
                return
            if "not found" not in desc and "can't be edited" not in desc:
                print("status edit error:", desc, flush=True)
                return  # 일시적인 오류: 다음 변경 때 다시 시도
        else:
            tg_call("deleteMessage", chat_id=chat, message_id=st["id"])
    if photo:
        r = tg_photo("sendPhoto", photo, chat_id=chat, caption=caption, disable_notification="true")
    else:
        r = tg_call("sendMessage", chat_id=chat, text=status_text(data), disable_web_page_preview="true",
                    disable_notification="true")
    if r.get("ok"):
        with open(STATUS_FILE, "w") as f:
            json.dump({"chat": chat, "id": r["result"]["message_id"], "kind": kind}, f)
    else:
        print("status send error:", r.get("description"), flush=True)


def status_loop():
    while True:
        status_dirty.wait()
        time.sleep(3)  # 연달아 바뀌면 한 번만 고침
        status_dirty.clear()
        try:
            status_update()
        except Exception as e:
            print("status error:", e, flush=True)


def broadcast():
    status_dirty.set()
    for q in list(listeners):
        try:
            q.put_nowait("change")
        except queue.Full:
            pass


def uname(c, uid):
    r = c.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return r["name"] if r else "미지정"


def backup(now):
    """하루 한 번 DB 사본 저장, 최근 14개만 보관"""
    try:
        d = os.path.join(os.path.dirname(DB_PATH), "backup")
        os.makedirs(d, exist_ok=True)
        src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(os.path.join(d, "taskboard-%s.db" % now.strftime("%Y%m%d")))
        src.backup(dst); dst.close(); src.close()
        for f in sorted(os.listdir(d))[:-14]:
            os.remove(os.path.join(d, f))
    except Exception as e:
        print("backup error:", e, flush=True)


def digest_loop():
    last = None
    while True:
        now = datetime.now(KST)
        if DIGEST_HOUR >= 0 and now.hour == DIGEST_HOUR and last != now.date():
            last = now.date()
            backup(now)
            try:
                status_update(fresh=True)  # 매일 아침 현황판을 새 글로 올려 대화 맨 아래로
            except Exception as e:
                print("status error:", e, flush=True)
        time.sleep(30)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "taskboard"

    def log_message(self, *a):
        pass

    # ---- helpers
    def send_json(self, obj, code=200, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def err(self, msg, code=400):
        self.send_json({"error": msg}, code)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 200000:
            return {}
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def me(self, c):
        m = re.search(r"(?:^|;\s*)tb=([A-Za-z0-9_-]+)", self.headers.get("Cookie") or "")
        if not m:
            return None
        return c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND u.active=1",
                         (m.group(1),)).fetchone()

    def ip(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def cookie(self, token, age=60 * 60 * 24 * 60):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return {"Set-Cookie": "tb=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d%s" % (token, age, secure)}

    # ---- GET
    def do_GET(self):
        path, _, qs = self.path.partition("?")
        if path in ("/", "/index.html"):
            with open(os.path.join(BASE, "index.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/state":
            with db() as c:
                me = self.me(c)
                if not me:
                    n = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
                    inv = get_invite(c, urllib.parse.parse_qs(qs).get("join", [""])[0])
                    return self.send_json({"me": None, "setup": n == 0,
                                           "join": {"role": inv["role"]} if inv else None})
                users = [dict(r) for r in c.execute("SELECT id,name,role,active FROM users ORDER BY role, name")]
                tasks = [dict(r) for r in c.execute("SELECT * FROM tasks ORDER BY updated DESC")]
                logs = {}
                for r in c.execute("SELECT * FROM logs ORDER BY created DESC"):
                    logs.setdefault(r["task_id"], []).append(dict(r))
                for t in tasks:
                    t["logs"] = logs.get(t["id"], [])
                out = {"me": {"id": me["id"], "name": me["name"], "role": me["role"]}, "users": users, "tasks": tasks}
                if me["role"] == "admin":
                    c.execute("DELETE FROM invites WHERE expires<?", (time.time(),))
                    out["invites"] = [dict(r) for r in c.execute("SELECT * FROM invites ORDER BY created")]
                self.send_json(out)
        elif path == "/api/events":
            with db() as c:
                if not self.me(c):
                    return self.err("로그인이 필요합니다", 401)
            q = queue.Queue(maxsize=20)
            listeners.add(q)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b"retry: 3000\n\n")
                self.wfile.flush()
                while True:
                    try:
                        q.get(timeout=20)
                        self.wfile.write(b"data: change\n\n")
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except Exception:
                pass
            finally:
                listeners.discard(q)
                self.close_connection = True
        else:
            self.err("없는 주소입니다", 404)

    # ---- POST
    def do_POST(self):
        path = self.path.split("?")[0]
        d = self.body()
        if path == "/internal/status":  # 같은 서버의 봇이 부르는 주소: 현황판 카드를 새로 올림 (/board 명령)
            if self.client_address[0] != "127.0.0.1" or self.headers.get("X-Forwarded-For"):
                return self.err("없는 주소입니다", 404)
            if str(d.get("chat", "")) != tg_chat():
                return self.send_json({"ok": False, "reason": "chat"})
            try:
                status_update(fresh=True)
                return self.send_json({"ok": True})
            except Exception as e:
                print("status error:", e, flush=True)
                return self.send_json({"ok": False, "reason": "error"})
        # CSRF: 다른 사이트에서 온 요청 거절
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc != (self.headers.get("Host") or ""):
            return self.err("허용되지 않은 요청입니다", 403)
        try:
            with lock, db() as c:
                self.route(c, path, d)
        except sqlite3.IntegrityError:
            self.err("이미 있는 이름입니다")

    def route(self, c, path, d):
        now = time.time()
        if path == "/api/setup":
            if c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]:
                return self.err("이미 설정되었습니다", 403)
            try:
                with open(SETUP_FILE) as f:
                    code = f.read().strip()
            except OSError:
                code = ""
            ip = self.ip()
            cnt, until = fails.get(ip, (0, 0))
            if now < until:
                return self.err("잠시 후 다시 시도해 주세요 (%d초)" % int(until - now), 429)
            if not code or not hmac.compare_digest(code, str(d.get("code", "")).strip()):
                fails[ip] = (cnt + 1, now + 300 if (cnt + 1) % 5 == 0 else 0)
                return self.err("설정 코드가 맞지 않습니다", 403)
            os.remove(SETUP_FILE)
            return self.make_user(c, d, "admin", login=True)
        if path == "/api/join":
            ip = self.ip()
            cnt, until = fails.get(ip, (0, 0))
            if now < until:
                return self.err("잠시 후 다시 시도해 주세요 (%d초)" % int(until - now), 429)
            inv = get_invite(c, d.get("token"))
            if not inv:
                fails[ip] = (cnt + 1, now + 300 if (cnt + 1) % 5 == 0 else 0)
                return self.err("가입 링크가 만료되었거나 잘못되었습니다. 관리자에게 새 링크를 받아 주세요", 403)
            if self.make_user(c, d, inv["role"], login=True):
                if inv["role"] == "admin":  # 관리자 링크는 한 번만 사용
                    c.execute("DELETE FROM invites WHERE token=?", (inv["token"],))
                if os.path.exists(SETUP_FILE):
                    os.remove(SETUP_FILE)
                notify("👋 %s님이 업무 보드에 가입했습니다 (%s)" % (str(d.get("name", "")).strip()[:30], ROLES[inv["role"]]))
            return
        if path == "/api/login":
            ip = self.ip()
            cnt, until = fails.get(ip, (0, 0))
            if now < until:
                return self.err("잠시 후 다시 시도해 주세요 (%d초)" % int(until - now), 429)
            u = c.execute("SELECT * FROM users WHERE name=? AND active=1", (str(d.get("name", "")).strip(),)).fetchone()
            if not u or not hmac.compare_digest(u["hash"], hash_pin(str(d.get("pin", "")), u["salt"])):
                cnt += 1
                fails[ip] = (cnt, now + 60 if cnt % 5 == 0 else 0)
                return self.err("이름 또는 비밀번호가 맞지 않습니다", 401)
            fails.pop(ip, None)
            tok = secrets.token_urlsafe(32)
            c.execute("INSERT INTO sessions VALUES(?,?,?)", (tok, u["id"], now))
            return self.send_json({"ok": True}, headers=self.cookie(tok))

        me = self.me(c)
        if not me:
            return self.err("로그인이 필요합니다", 401)
        admin = me["role"] == "admin"
        boss = me["role"] in ("admin", "lead")

        if path == "/api/logout":
            c.execute("DELETE FROM sessions WHERE user_id=?", (me["id"],))
            return self.send_json({"ok": True}, headers=self.cookie("x", 0))
        if path == "/api/users":
            if not admin:
                return self.err("관리자만 할 수 있습니다", 403)
            return self.make_user(c, d, d.get("role") if d.get("role") in ROLES else "staff")
        if path == "/api/invites":
            if not admin:
                return self.err("관리자만 할 수 있습니다", 403)
            tok = new_invite(c, d.get("role") if d.get("role") in ROLES else "staff")
            broadcast()
            return self.send_json({"ok": True, "token": tok})
        if path == "/api/invites/delete":
            if not admin:
                return self.err("관리자만 할 수 있습니다", 403)
            c.execute("DELETE FROM invites WHERE token=?", (str(d.get("token", "")),))
            broadcast()
            return self.send_json({"ok": True})
        m = re.fullmatch(r"/api/users/(\d+)/(delete|pin|role)", path)
        if m:
            uid, act = int(m.group(1)), m.group(2)
            if not (admin or (act == "pin" and uid == me["id"])):
                return self.err("권한이 없습니다", 403)
            if act == "delete":
                if uid == me["id"]:
                    return self.err("본인 계정은 삭제할 수 없습니다")
                c.execute("UPDATE users SET active=0, name=name||' (퇴사 '||id||')' WHERE id=?", (uid,))
                c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            elif act == "role":
                if not admin or d.get("role") not in ROLES:
                    return self.err("권한이 없습니다", 403)
                if uid == me["id"]:
                    return self.err("본인 직책은 바꿀 수 없습니다")
                c.execute("UPDATE users SET role=? WHERE id=?", (d["role"], uid))
            else:
                pin = str(d.get("pin", ""))
                if len(pin) < 4:
                    return self.err("비밀번호는 4자 이상이어야 합니다")
                salt = secrets.token_hex(16)
                c.execute("UPDATE users SET salt=?, hash=? WHERE id=?", (salt, hash_pin(pin, salt), uid))
            broadcast()
            return self.send_json({"ok": True})

        if path == "/api/tasks":
            title = str(d.get("title", "")).strip()[:200]
            if not title:
                return self.err("업무 제목을 적어 주세요")
            aid = self.valid_user(c, d.get("assignee_id"))
            pr = d.get("priority") if d.get("priority") in PRIORITY else "normal"
            due = d.get("due") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d.get("due") or "")) else ""
            cat = d.get("category") if d.get("category") in CATS else "기타"
            cur = c.execute("INSERT INTO tasks(title,detail,assignee_id,creator_id,priority,due,category,created,updated) "
                            "VALUES(?,?,?,?,?,?,?,?,?)",
                            (title, str(d.get("detail", ""))[:4000], aid, me["id"], pr, due, cat, now, now))
            c.execute("INSERT INTO logs(task_id,user_id,kind,text,created) VALUES(?,?,?,?,?)",
                      (cur.lastrowid, me["id"], "create", "업무 등록", now))
            notify("🆕 새 업무 지시%s\n[%s]「%s」\n담당: %s · 지시: %s%s%s" % (
                " 🔥긴급" if pr == "high" else "", cat, title, uname(c, aid), me["name"],
                ("\n기한: " + due) if due else "",
                ("\n\n" + str(d.get("detail", ""))[:500]) if d.get("detail") else ""))
            broadcast()
            return self.send_json({"ok": True, "id": cur.lastrowid})

        m = re.fullmatch(r"/api/tasks/(\d+)(?:/(delete|log))?", path)
        if not m:
            return self.err("없는 주소입니다", 404)
        t = c.execute("SELECT * FROM tasks WHERE id=?", (int(m.group(1)),)).fetchone()
        if not t:
            return self.err("이미 삭제된 업무입니다", 404)
        act = m.group(2)

        if act == "delete":
            if not (boss or t["creator_id"] == me["id"]):
                return self.err("등록한 사람이나 관리자·팀장만 삭제할 수 있습니다", 403)
            c.execute("DELETE FROM tasks WHERE id=?", (t["id"],))
            notify("🗑 업무 삭제\n「%s」\n삭제: %s" % (t["title"], me["name"]))
        elif act == "log":
            text = str(d.get("text", "")).strip()[:2000]
            if not text:
                return self.err("내용을 적어 주세요")
            c.execute("INSERT INTO logs(task_id,user_id,kind,text,created) VALUES(?,?,?,?,?)",
                      (t["id"], me["id"], "note", text, now))
            c.execute("UPDATE tasks SET updated=? WHERE id=?", (now, t["id"]))
            notify("📝 특이사항\n「%s」\n%s: %s" % (t["title"], me["name"], text))
        else:
            sets, vals, changes = [], [], []
            if "status" in d and d["status"] != t["status"]:
                st = d["status"]
                if st not in STATUS:
                    return self.err("잘못된 상태입니다")
                note = str(d.get("note", "")).strip()[:2000]
                if st in NEED_NOTE and not note:
                    return self.err("%s: 내용을 적어 주세요" % NEED_NOTE[st])
                sets += ["status=?", "status_note=?"]
                vals += [st, note]
                c.execute("INSERT INTO logs(task_id,user_id,kind,text,created) VALUES(?,?,?,?,?)",
                          (t["id"], me["id"], "status:" + st,
                           "%s → %s%s" % (STATUS[t["status"]], STATUS[st], (" · " + note) if note else ""), now))
                icon = {"ack": "👀", "doing": "▶️", "hold": "⏸", "stop": "⛔", "done": "✅", "new": "↩️"}[st]
                notify("%s %s\n「%s」\n%s%s" % (icon, STATUS[st], t["title"], me["name"],
                                              ("\n%s: %s" % (NEED_NOTE.get(st, "메모"), note)) if note else ""))
            if "title" in d and str(d["title"]).strip() and str(d["title"]).strip() != t["title"]:
                sets.append("title=?"); vals.append(str(d["title"]).strip()[:200]); changes.append("제목")
            if "detail" in d and str(d["detail"]) != t["detail"]:
                sets.append("detail=?"); vals.append(str(d["detail"])[:4000]); changes.append("내용")
            if "assignee_id" in d and self.valid_user(c, d["assignee_id"]) != t["assignee_id"]:
                aid = self.valid_user(c, d["assignee_id"])
                sets.append("assignee_id=?"); vals.append(aid); changes.append("담당자 → " + uname(c, aid))
            if "category" in d and d["category"] in CATS and d["category"] != t["category"]:
                sets.append("category=?"); vals.append(d["category"]); changes.append("분류 → " + d["category"])
            if "priority" in d and d["priority"] in PRIORITY and d["priority"] != t["priority"]:
                sets.append("priority=?"); vals.append(d["priority"]); changes.append("중요도 → " + PRIORITY[d["priority"]])
            if "due" in d and (d["due"] or "") != t["due"] and re.fullmatch(r"(\d{4}-\d{2}-\d{2})?", str(d["due"] or "")):
                sets.append("due=?"); vals.append(d["due"] or ""); changes.append("기한 → " + (d["due"] or "없음"))
            if changes:
                txt = "수정: " + ", ".join(changes)
                c.execute("INSERT INTO logs(task_id,user_id,kind,text,created) VALUES(?,?,?,?,?)",
                          (t["id"], me["id"], "edit", txt, now))
                notify("✏️ 업무 수정\n「%s」\n%s (%s)" % (d.get("title") or t["title"], txt, me["name"]))
            if sets:
                c.execute("UPDATE tasks SET %s, updated=? WHERE id=?" % ", ".join(sets), vals + [now, t["id"]])
        broadcast()
        self.send_json({"ok": True})

    def valid_user(self, c, uid):
        try:
            r = c.execute("SELECT id FROM users WHERE id=? AND active=1", (int(uid),)).fetchone()
            return r["id"] if r else None
        except (TypeError, ValueError):
            return None

    def make_user(self, c, d, role, login=False):
        name, pin = str(d.get("name", "")).strip()[:30], str(d.get("pin", ""))
        if not name or len(pin) < 4:
            self.err("이름과 4자 이상 비밀번호를 적어 주세요")
            return False
        if c.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone():
            self.err("이미 있는 이름입니다. 다른 이름을 적어 주세요")
            return False
        salt = secrets.token_hex(16)
        cur = c.execute("INSERT INTO users(name,role,salt,hash) VALUES(?,?,?,?)", (name, role, salt, hash_pin(pin, salt)))
        headers = None
        if login:
            tok = secrets.token_urlsafe(32)
            c.execute("INSERT INTO sessions VALUES(?,?,?)", (tok, cur.lastrowid, time.time()))
            headers = self.cookie(tok)
        broadcast()
        self.send_json({"ok": True}, headers=headers)
        return True


if __name__ == "__main__":
    init_db()
    with db() as c:
        if not c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"] and not os.path.exists(SETUP_FILE):
            with open(SETUP_FILE, "w") as f:
                f.write("%06d" % secrets.randbelow(10 ** 6))
            os.chmod(SETUP_FILE, 0o600)
        # 처음 한 번: 직책별 가입 링크를 만들어 파일로 남김 (서버가 사장님 텔레그램으로 전달 후 삭제)
        flag = os.path.join(BASE, "invites_made")
        if not os.path.exists(flag):
            base = BOARD_URL or "http://127.0.0.1:%d" % PORT
            lines = ["%s 가입 링크%s\n%s/?join=%s" % (ROLES[r], " (1회용)" if r == "admin" else "", base, new_invite(c, r))
                     for r in ("admin", "lead", "staff")]
            with open(os.path.join(BASE, "invite_links"), "w", encoding="utf-8") as f:
                f.write("\n\n".join(lines))
            os.chmod(os.path.join(BASE, "invite_links"), 0o600)
            open(flag, "w").close()
    threading.Thread(target=digest_loop, daemon=True).start()
    threading.Thread(target=status_loop, daemon=True).start()
    status_dirty.set()
    srv = ThreadingHTTPServer(("127.0.0.1" if os.environ.get("LOCAL_ONLY", "1") == "1" else "0.0.0.0", PORT), H)
    srv.daemon_threads = True
    print("taskboard on :%d" % PORT, flush=True)
    srv.serve_forever()
