

# ----------------------------------------------------------------------
# 웹 서버 (이 PC 안에서만 접속 가능: 127.0.0.1)
# ----------------------------------------------------------------------
TOKEN = os.urandom(12).hex()
S = {
    "ffmpeg": None, "ffprobe": None, "font": None, "font_note": "",
    "src": None, "info": None, "uploaded": False,
    "cut": {"src": None, "info": None, "uploaded": False},
    "clips": [], "next_id": 1,
    "tonemap_ok": None, "last_ping": 0.0,
    "job": {"state": "idle", "kind": "", "done": 0, "total": 1, "msg": "", "out": "", "error": ""},
}
THUMBS = {}
CANCEL = threading.Event()
UPLOAD_DIR = tempfile.mkdtemp(prefix="hl_upload_")
LOCK = threading.Lock()


def _dialog(kind, title, initial="", filetypes=None, default_name=""):
    """파일 선택/저장 창(윈도우 기본 창)을 따로 띄워 선택한 경로를 돌려줍니다."""
    code = (
        "import sys, json\n"
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "a = json.loads(sys.argv[1])\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "ft = [tuple(x) for x in a['ft']] or [('모든 파일', '*.*')]\n"
        "if a['kind'] == 'save':\n"
        "    p = filedialog.asksaveasfilename(title=a['title'], initialdir=a['init'] or None,\n"
        "        initialfile=a['name'], defaultextension='.mp4', filetypes=ft)\n"
        "elif a['kind'] == 'dir':\n"
        "    p = filedialog.askdirectory(title=a['title'], initialdir=a['init'] or None)\n"
        "elif a['kind'] == 'openmulti':\n"
        "    p = '\\n'.join(filedialog.askopenfilenames(title=a['title'], initialdir=a['init'] or None, filetypes=ft))\n"
        "else:\n"
        "    p = filedialog.askopenfilename(title=a['title'], initialdir=a['init'] or None, filetypes=ft)\n"
        "sys.stdout.buffer.write((p or '').encode('utf-8'))\n"
    )
    arg = json.dumps({"kind": kind, "title": title, "init": initial,
                      "ft": filetypes or [], "name": default_name})
    exe = sys.executable
    if IS_WIN and exe.lower().endswith("pythonw.exe"):
        cand = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.isfile(cand):
            exe = cand
    r = subprocess.run([exe, "-c", code, arg], capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=NO_WINDOW)
    return r.stdout.decode("utf-8", "replace").strip("\r\n")


def load_tools():
    ff, fp = find_ffmpeg_pair()
    S["ffmpeg"], S["ffprobe"] = ff, fp
    S["font"], S["font_note"] = find_font()


def load_video(path, uploaded=False):
    if not (S["ffmpeg"] and S["ffprobe"]):
        raise EditError("FFmpeg를 먼저 찾아야 합니다. 화면 위쪽의 [FFmpeg 위치 지정]을 눌러 주세요.")
    info = probe(S["ffprobe"], path)
    old = S["src"]
    S["src"], S["info"], S["uploaded"] = path, info, uploaded
    if old and old != path and old.startswith(UPLOAD_DIR):
        try:
            os.remove(old)
        except OSError:
            pass


def info_json():
    i = S["info"]
    if not i:
        return None
    is_hdr = i["transfer"] in HDR_TRANSFERS
    return {"name": os.path.basename(S["src"]), "width": i["width"], "height": i["height"],
            "fps": fps_label(i["fps"]), "duration": i["duration"], "codec": i["codec"],
            "hdr": is_hdr}


def _brief(path, i, uploaded=False):
    return {"name": os.path.basename(path), "width": i["width"], "height": i["height"],
            "fps": fps_label(i["fps"]), "duration": i["duration"], "codec": i["codec"],
            "hdr": i["transfer"] in HDR_TRANSFERS, "audio": bool(i["has_audio"])}


def cut_json():
    c = S["cut"]
    return _brief(c["src"], c["info"]) if c["src"] else None


def clips_json():
    out = []
    for c in S["clips"]:
        d = _brief(c["path"], c["info"])
        d["id"] = c["id"]
        out.append(d)
    plan = None
    if len(S["clips"]) >= 1:
        p = merge_plan(S["clips"], False, bool(S["ffmpeg"]) and has_encoder(S["ffmpeg"], "libx265"))
        plan = {"width": p["width"], "height": p["height"], "fps": fps_label(p["fps"]),
                "fpsRaw": p["fps"], "keepHdr": p["keep"], "mixedHdr": p["mixed_hdr"],
                "fast": p["fast"]}
    return {"list": out, "plan": plan}


def state_json():
    return {"ffmpeg": bool(S["ffmpeg"] and S["ffprobe"]),
            "ffmpegPath": S["ffmpeg"] or "", "font": bool(S["font"]),
            "video": info_json(), "job": S["job"], "positions": list(POSITIONS.keys()),
            "defaultPosition": DEFAULT_POSITION, "cut": cut_json(), "clips": clips_json()}


def _clean(path, uploaded):
    if uploaded and path and path.startswith(UPLOAD_DIR):
        try:
            os.remove(path)
        except OSError:
            pass


def load_cut(path, uploaded=False):
    if not (S["ffmpeg"] and S["ffprobe"]):
        raise EditError("FFmpeg를 먼저 찾아야 합니다. 화면 위쪽의 [FFmpeg 위치 지정]을 눌러 주세요.")
    info = probe(S["ffprobe"], path)
    old = S["cut"]
    if old["src"] and old["src"] != path:
        _clean(old["src"], old["uploaded"])
    S["cut"] = {"src": path, "info": info, "uploaded": uploaded}


def add_clip(path, uploaded=False):
    if not (S["ffmpeg"] and S["ffprobe"]):
        raise EditError("FFmpeg를 먼저 찾아야 합니다. 화면 위쪽의 [FFmpeg 위치 지정]을 눌러 주세요.")
    info = probe(S["ffprobe"], path)
    S["clips"].append({"id": S["next_id"], "path": path, "info": info, "uploaded": uploaded})
    S["next_id"] += 1


def start_job(segments, title, out, out_ratio=DEFAULT_RATIO, kind="highlight", runner=None):
    CANCEL.clear()
    S["job"] = {"state": "running", "kind": kind, "done": 0, "total": 1, "msg": "준비 중...",
                "out": out, "error": ""}

    def progress(d, t, m):
        S["job"].update(done=d, total=max(t, 1), msg=m)

    def work():
        try:
            if S["tonemap_ok"] is None:
                S["tonemap_ok"] = has_tonemap_filters(S["ffmpeg"])
            if runner:
                runner(progress)
            else:
                make_highlight(S["ffmpeg"], S["src"], S["info"], segments, title, S["font"], out,
                               progress, CANCEL, S["tonemap_ok"], True, out_ratio)
            S["job"].update(state="done", done=1, total=1, msg="완료")
        except Cancelled:
            S["job"].update(state="cancelled", msg="취소했습니다.")
        except EditError as e:
            S["job"].update(state="error", error=str(e))
        except Exception:
            S["job"].update(state="error",
                            error="예상하지 못한 오류가 발생했습니다.\n\n" + traceback.format_exc()[-800:])

    threading.Thread(target=work, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HighlightEditor"

    def log_message(self, *a):
        pass

    # ---- 공통 ----
    def _ok_host(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _fail(self, text, code=400):
        self._json({"error": text}, code)

    def _authed(self):
        if self.headers.get("X-Token") == TOKEN:
            return True
        q = parse_qs(urlparse(self.path).query)
        return q.get("t", [""])[0] == TOKEN

    # ---- GET ----
    def do_GET(self):
        if not self._ok_host():
            return self._send(403)
        u = urlparse(self.path)
        if u.path == "/":
            page = PAGE.replace("__TOKEN__", TOKEN).replace("__TITLE__", APP_TITLE).replace("__THEME__", get_theme())
            return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if not self._authed():
            return self._send(403)
        if u.path == "/api/state":
            S["last_ping"] = __import__("time").time()
            return self._json(state_json())
        if u.path == "/video":
            q = parse_qs(u.query)
            if q.get("slot", [""])[0] == "cut":
                return self._video(S["cut"]["src"])
            if q.get("clip", [""])[0]:
                cid = q["clip"][0]
                c = next((x for x in S["clips"] if str(x["id"]) == cid), None)
                return self._video(c["path"] if c else None)
            return self._video(S["src"])
        if u.path == "/thumb":
            return self._thumb(parse_qs(u.query).get("id", [""])[0])
        self._send(404)

    do_HEAD = do_GET

    def _thumb(self, cid):
        c = next((x for x in S["clips"] if str(x["id"]) == cid), None)
        if not c:
            return self._send(404)
        data = THUMBS.get(c["id"])
        if data is None:
            t = min(1.0, max(0.0, c["info"]["duration"] / 4))
            r = subprocess.run([S["ffmpeg"], "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}",
                                "-i", c["path"], "-frames:v", "1", "-vf", "scale=160:-2",
                                "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                               capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
            data = r.stdout if r.returncode == 0 else b""
            THUMBS[c["id"]] = data
        if not data:
            return self._send(404)
        self._send(200, data, "image/jpeg", {"Cache-Control": "max-age=3600"})

    def _video(self, path):
        if not path or not os.path.isfile(path):
            return self._send(404)
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "video/mp4"
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            else:
                start = max(0, size - int(m.group(2)))
            if start >= size:
                return self._send(416, extra={"Content-Range": f"bytes */{size}"})
            code = 206
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, OSError):
            pass

    # ---- POST ----
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw.decode("utf-8")) if raw else {}

    def do_POST(self):
        if not self._ok_host() or not self._authed():
            return self._send(403)
        u = urlparse(self.path)
        try:
            if u.path == "/api/upload":
                return self._upload(u)
            if u.path == "/api/cut/upload":
                return self._upload(u, "cut")
            if u.path == "/api/clips/upload":
                return self._upload(u, "clip")
            data = self._body()
            fn = {"/api/pick": self._pick, "/api/ffmpeg": self._pick_ffmpeg,
                  "/api/save": self._save, "/api/cancel": self._cancel,
                  "/api/openfolder": self._openfolder, "/api/quit": self._quit,
                  "/api/unload": self._unload, "/api/theme": self._theme, "/api/log/save": self._log_save, "/api/log/folder": self._log_folder, "/api/log/load": self._log_load, "/api/cut/pick": self._cut_pick, "/api/cut/save": self._cut_save,
                  "/api/clips/pick": self._clips_pick, "/api/clips/remove": self._clips_remove,
                  "/api/clips/move": self._clips_move, "/api/clips/clear": self._clips_clear,
                  "/api/merge/save": self._merge_save}.get(u.path)
            if not fn:
                return self._send(404)
            return fn(data)
        except EditError as e:
            return self._fail(str(e))
        except (ConnectionError, OSError):
            raise
        except Exception:
            return self._fail("예상하지 못한 오류가 발생했습니다.\n\n" + traceback.format_exc()[-700:], 500)

    def _pick(self, _d):
        if not (S["ffmpeg"] and S["ffprobe"]):
            raise EditError("FFmpeg를 먼저 찾아야 합니다. [FFmpeg 위치 지정]을 눌러 주세요.")
        exts = " ".join("*" + e for e in VIDEO_EXTS)
        path = _dialog("open", "영상 파일 선택", "", [["영상", exts], ["모든 파일", "*.*"]])
        if not path:
            return self._json({"cancelled": True})
        load_video(path)
        self._json(state_json())

    def _upload(self, u, slot="main"):
        if not (S["ffmpeg"] and S["ffprobe"]):
            raise EditError("FFmpeg를 먼저 찾아야 합니다.")
        name = os.path.basename(parse_qs(u.query).get("name", ["video.mp4"])[0]) or "video.mp4"
        if not name.lower().endswith(VIDEO_EXTS):
            raise EditError("지원하는 영상 형식은 mp4, mov, m4v, mkv, avi 입니다.")
        folder = UPLOAD_DIR
        if slot != "main":
            folder = os.path.join(UPLOAD_DIR, slot + str(S["next_id"] if slot == "clip" else ""))
            os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, name)
        left = int(self.headers.get("Content-Length") or 0)
        with open(dest, "wb") as f:
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if slot == "cut":
            load_cut(dest, True)
        elif slot == "clip":
            add_clip(dest, True)
        else:
            load_video(dest, uploaded=True)
        self._json(state_json())

    def _log_save(self, d):
        if not S["src"]:
            raise EditError("먼저 영상 파일을 선택해 주세요.")
        t = d.get("title") if isinstance(d.get("title"), dict) else {}
        rows = d.get("rows") if isinstance(d.get("rows"), list) else []
        name = os.path.basename(S["src"])
        log = build_log("" if S["uploaded"] else os.path.abspath(S["src"]), name, S["info"], rows, t)
        base = get_log_dir() or (os.path.dirname(S["src"]) if not S["uploaded"] else os.path.expanduser("~"))
        path = _dialog("save", "편집 로그 저장", base, [["편집 로그", "*.json"]],
                       log_default_name(name))
        if not path:
            return self._json({"cancelled": True})
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=1)
        except OSError as e:
            raise EditError(f"로그를 저장하지 못했습니다.\n{e}")
        self._json({"path": path})

    def _theme(self, d):
        set_theme(str(d.get("mode", "auto")))
        self._json({"ok": True})

    def _log_folder(self, _d):
        d = _dialog("dir", "로그를 저장할 폴더 선택 (구글 드라이브·OneDrive 폴더를 고르면 클라우드에 보관됩니다)", get_log_dir())
        if not d:
            return self._json({"cancelled": True})
        set_log_dir(d)
        self._json({"dir": d})

    def _log_load(self, _d):
        if S["job"]["state"] == "running":
            raise EditError("편집이 진행 중입니다. 끝난 뒤에 불러와 주세요.")
        if not (S["ffmpeg"] and S["ffprobe"]):
            raise EditError("FFmpeg를 먼저 찾아야 합니다. [FFmpeg 위치 지정]을 눌러 주세요.")
        path = _dialog("open", "편집 로그 불러오기", get_log_dir(), [["편집 로그", "*.json"], ["모든 파일", "*.*"]])
        if not path:
            return self._json({"cancelled": True})
        log = read_log(path)
        vp = log["video"]["path"]
        found = bool(vp and os.path.isfile(vp))
        if found:
            load_video(vp)
        dur = S["info"]["duration"] if (found and S["info"]) else 0.0
        log["rows"] = clean_log_rows(log["rows"], dur)
        out = state_json()
        out.update({"log": log, "videoFound": found})
        self._json(out)

    def _unload(self, _d):
        if S["job"]["state"] == "running":
            raise EditError("편집이 진행 중입니다. 끝난 뒤에 초기화해 주세요.")
        old, up = S["src"], S["uploaded"]
        S["src"], S["info"], S["uploaded"] = None, None, False
        _clean(old, up)
        self._json({"ok": True})

    def _cut_pick(self, _d):
        if not (S["ffmpeg"] and S["ffprobe"]):
            raise EditError("FFmpeg를 먼저 찾아야 합니다. [FFmpeg 위치 지정]을 눌러 주세요.")
        exts = " ".join("*" + e for e in VIDEO_EXTS)
        path = _dialog("open", "영상 파일 선택", "", [["영상", exts], ["모든 파일", "*.*"]])
        if not path:
            return self._json({"cancelled": True})
        load_cut(path)
        self._json(state_json())

    def _clips_pick(self, _d):
        if not (S["ffmpeg"] and S["ffprobe"]):
            raise EditError("FFmpeg를 먼저 찾아야 합니다. [FFmpeg 위치 지정]을 눌러 주세요.")
        exts = " ".join("*" + e for e in VIDEO_EXTS)
        res = _dialog("openmulti", "합칠 영상 선택 (여러 개 선택 가능)", "", [["영상", exts], ["모든 파일", "*.*"]])
        paths = [p for p in res.split("\n") if p.strip()]
        if not paths:
            return self._json({"cancelled": True})
        bad = []
        for p in paths:
            try:
                add_clip(p)
            except EditError as e:
                bad.append(f"{os.path.basename(p)}: {e}")
        out = state_json()
        if bad:
            out["warn"] = "일부 영상을 불러오지 못했습니다.\n" + "\n".join(bad)
        self._json(out)

    def _clips_remove(self, d):
        c = next((x for x in S["clips"] if x["id"] == d.get("id")), None)
        if c:
            S["clips"].remove(c)
            _clean(c["path"], c["uploaded"])
            THUMBS.pop(c["id"], None)
        self._json(state_json())

    def _clips_move(self, d):
        ids = [x["id"] for x in S["clips"]]
        cid, to = d.get("id"), d.get("to")
        if cid in ids and isinstance(to, int):
            c = S["clips"].pop(ids.index(cid))
            S["clips"].insert(max(0, min(to, len(S["clips"]))), c)
        self._json(state_json())

    def _clips_clear(self, _d):
        for c in S["clips"]:
            _clean(c["path"], c["uploaded"])
        S["clips"] = []
        THUMBS.clear()
        self._json(state_json())

    def _cut_save(self, d):
        c = S["cut"]
        if not c["src"]:
            raise EditError("먼저 영상을 선택해 주세요.")
        if S["job"]["state"] == "running":
            raise EditError("이미 편집이 진행 중입니다.")
        dels = []
        for r in d.get("deletes", []):
            try:
                a, b = float(r[0]), float(r[1])
            except (TypeError, ValueError, IndexError, KeyError):
                raise EditError("지울 구간의 시간이 올바르지 않습니다.")
            if b <= a:
                raise EditError("지울 구간의 종료 시간은 시작 시간보다 늦어야 합니다.")
            dels.append((a, b))
        if not dels:
            raise EditError("지울 구간을 1개 이상 지정해 주세요.")
        if not keep_ranges(dels, c["info"]["duration"]):
            raise EditError("지우고 남는 영상이 없습니다. 지울 구간을 확인해 주세요.")
        fast = bool(d.get("fast"))
        base = os.path.dirname(c["src"]) if not c["uploaded"] else os.path.expanduser("~")
        out = _dialog("save", "저장할 위치와 이름", base, [["MP4 동영상", "*.mp4"]], "구간삭제.mp4")
        if not out:
            return self._json({"cancelled": True})
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        if os.path.abspath(out) == os.path.abspath(c["src"]):
            raise EditError("원본 영상과 같은 이름으로는 저장할 수 없습니다.")
        src, info = c["src"], c["info"]
        start_job(None, None, out, kind="cut", runner=lambda pr: make_cut(
            S["ffmpeg"], src, info, dels, out, pr, CANCEL, S["tonemap_ok"], fast))
        self._json({"started": True})

    def _merge_save(self, d):
        if len(S["clips"]) < 2:
            raise EditError("합칠 영상을 2개 이상 추가해 주세요.")
        if S["job"]["state"] == "running":
            raise EditError("이미 편집이 진행 중입니다.")
        trans = bool(d.get("transition"))
        clips = [dict(c) for c in S["clips"]]
        first = clips[0]["path"]
        base = os.path.dirname(first) if not clips[0]["uploaded"] else os.path.expanduser("~")
        out = _dialog("save", "저장할 위치와 이름", base, [["MP4 동영상", "*.mp4"]], "합친영상.mp4")
        if not out:
            return self._json({"cancelled": True})
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        start_job(None, None, out, kind="merge", runner=lambda pr: make_merge(
            S["ffmpeg"], clips, out, pr, CANCEL, S["tonemap_ok"], trans))
        self._json({"started": True})

    def _pick_ffmpeg(self, _d):
        local = os.environ.get("LOCALAPPDATA", "")
        links = os.path.join(local, "Microsoft", "WinGet", "Links") if local else ""
        path = _dialog("open", "ffmpeg.exe 선택", links if os.path.isdir(links) else "",
                       [["FFmpeg", "ffmpeg.exe ffprobe.exe"], ["모든 파일", "*.*"]])
        if not path:
            return self._json({"cancelled": True})
        folder = os.path.dirname(path)
        ff, fp = os.path.join(folder, _exe("ffmpeg")), os.path.join(folder, _exe("ffprobe"))
        if not (os.path.isfile(ff) and os.path.isfile(fp)):
            raise EditError("선택한 폴더에 ffmpeg.exe와 ffprobe.exe가 모두 있어야 합니다.\n"
                            f"선택한 폴더: {folder}")
        S["ffmpeg"], S["ffprobe"] = ff, fp
        remember_ffmpeg(ff)
        self._json(state_json())

    def _save(self, d):
        if not S["src"]:
            raise EditError("먼저 영상을 선택해 주세요.")
        if S["job"]["state"] == "running":
            raise EditError("이미 편집이 진행 중입니다.")
        rows = [{"start": r.get("start"), "end": r.get("end"), "text": str(r.get("text") or ""),
                 "pos": r.get("pos") if r.get("pos") in POSITIONS else DEFAULT_POSITION,
                 "active": bool(r.get("active")),
                 "crop": r.get("crop") if isinstance(r.get("crop"), dict) else None,
                 "cropOn": isinstance(r.get("crop"), dict)}
                for r in d.get("rows", [])]
        out_ratio = d.get("outRatio") if d.get("outRatio") in RATIOS else DEFAULT_RATIO
        try:
            segs = collect_segments(rows, S["info"]["duration"])
        except ValueError as e:
            raise EditError(str(e))
        if not segs:
            raise EditError("득점 구간을 1개 이상 지정해 주세요.")
        title = None
        t = d.get("title")
        if t and str(t.get("text", "")).strip():
            try:
                secs = float(t.get("secs"))
            except (TypeError, ValueError):
                raise EditError("메인화면 표시 시간(초)을 숫자로 입력해 주세요.")
            if secs < 0:
                raise EditError("메인화면 표시 시간은 0 이상이어야 합니다.")
            if secs > 0:
                title = {"text": str(t["text"]).strip(), "secs": secs}
        base = os.path.dirname(S["src"]) if not S["uploaded"] else os.path.expanduser("~")
        out = _dialog("save", "저장할 위치와 이름", base, [["MP4 동영상", "*.mp4"]], "하이라이트.mp4")
        if not out:
            return self._json({"cancelled": True})
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        if os.path.abspath(out) == os.path.abspath(S["src"]):
            raise EditError("원본 영상과 같은 이름으로는 저장할 수 없습니다.")
        start_job(segs, title, out, out_ratio)
        self._json({"started": True})

    def _cancel(self, _d):
        CANCEL.set()
        self._json({"ok": True})

    def _openfolder(self, _d):
        out = S["job"].get("out")
        if out and IS_WIN:
            os.startfile(os.path.dirname(out))
        self._json({"ok": True})

    def _quit(self, _d):
        self._json({"ok": True})
        CANCEL.set()
        threading.Thread(target=_shutdown, daemon=True).start()


def _shutdown():
    import time
    time.sleep(0.4)
    shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
    os._exit(0)


def _watchdog():
    """브라우저 탭을 닫아 신호가 1분 넘게 끊기면(편집 중이 아닐 때) 프로그램을 끝냅니다."""
    import time
    while True:
        time.sleep(5)
        lp = S["last_ping"]
        if lp and time.time() - lp > 60 and S["job"]["state"] != "running":
            _shutdown()


def main():
    load_tools()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=_watchdog, daemon=True).start()
    threading.Timer(0.6, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    try:
        srv.serve_forever()
    finally:
        shutil.rmtree(UPLOAD_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
