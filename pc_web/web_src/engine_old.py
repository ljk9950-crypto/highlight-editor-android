APP_TITLE = "농구 하이라이트 편집기"
IS_WIN = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HERE = os.path.dirname(os.path.abspath(__file__))


def _fatal(text):
    """창을 띄울 수 없을 때 윈도우 기본 알림창으로 안내하고 종료합니다."""
    try:
        if IS_WIN:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, APP_TITLE, 0x10)
        else:
            sys.stderr.write(text + "\n")
    finally:
        sys.exit(1)


# 자막 위치 이름 -> (x 식, y 식)
POSITIONS = {
    "좌측 상단": ("w*0.03", "h*0.05"),
    "우측 상단": ("w-text_w-w*0.03", "h*0.05"),
    "좌측 하단": ("w*0.03", "h-text_h-h*0.06"),
    "우측 하단": ("w-text_w-w*0.03", "h-text_h-h*0.06"),
    "하단 중앙": ("(w-text_w)/2", "h-text_h-h*0.06"),
    "화면 중앙": ("(w-text_w)/2", "(h-text_h)/2"),
}
DEFAULT_POSITION = "우측 하단"
HDR_TRANSFERS = ("smpte2084", "arib-std-b67")
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".avi")

INK = "#111827"
SUBTLE = "#3B4656"
ACCENT = "#C2410C"
LINE = "#DDE1E8"


class EditError(Exception):
    """사용자에게 그대로 보여줄 오류 메시지"""


class Cancelled(Exception):
    """사용자가 취소함"""


class MarkError(Exception):
    """구간 지정 중 사용자에게 보여줄 안내 메시지"""


# ----------------------------------------------------------------------
# 도구/글꼴 찾기
# ----------------------------------------------------------------------
SETTINGS_FILE = os.path.join(HERE, "highlight_editor_settings.json")


def _load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass


def _exe(name):
    return name + (".exe" if IS_WIN else "")


def _env_dirs():
    env = os.environ
    local = env.get("LOCALAPPDATA", "")
    pf = env.get("ProgramFiles", "C:\\Program Files")
    pf86 = env.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
    home = env.get("USERPROFILE", "") or os.path.expanduser("~")
    return local, pf, pf86, home


def _registry_path_dirs():
    """탐색기에서 실행하면 방금 설치한 프로그램의 PATH를 못 볼 수 있어, 레지스트리에서 직접 읽습니다."""
    dirs = []
    if not IS_WIN:
        return dirs
    try:
        import winreg
    except ImportError:
        return dirs
    places = ((winreg.HKEY_CURRENT_USER, "Environment"),
              (winreg.HKEY_LOCAL_MACHINE,
               r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"))
    for hive, sub in places:
        try:
            with winreg.OpenKey(hive, sub) as key:
                value, _kind = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        dirs += [p for p in str(value).split(";") if p.strip()]
    return dirs


def _candidate_dirs():
    local, pf, pf86, home = _env_dirs()
    dirs = [_load_settings().get("ffmpeg_dir", ""), HERE, os.path.join(HERE, "ffmpeg", "bin")]
    dirs += os.environ.get("PATH", "").split(os.pathsep)
    dirs += _registry_path_dirs()
    if local:
        dirs.append(os.path.join(local, "Microsoft", "WinGet", "Links"))
    dirs += [os.path.join(pf, "WinGet", "Links"),
             os.path.join(pf, "ffmpeg", "bin"), os.path.join(pf86, "ffmpeg", "bin"),
             "C:\\ffmpeg\\bin", os.path.join(home, "ffmpeg", "bin"),
             "C:\\ProgramData\\chocolatey\\bin",
             os.path.join(home, "scoop", "shims"),
             os.path.join(home, "scoop", "apps", "ffmpeg", "current", "bin")]
    seen, out = set(), []
    for d in dirs:
        d = os.path.expandvars(str(d).strip().strip('"'))
        if d and d.lower() not in seen:
            seen.add(d.lower())
            out.append(d)
    return out


def _package_roots():
    local, pf, pf86, _home = _env_dirs()
    roots = [os.path.join(local, "Microsoft", "WinGet", "Packages")] if local else []
    roots += [os.path.join(pf, "WinGet", "Packages"), os.path.join(pf86, "WinGet", "Packages")]
    return roots


def _walk_find(exe, root, max_depth=4):
    if not os.path.isdir(root):
        return None
    base = root.rstrip("\\/").count(os.sep)
    for cur, dirs, files in os.walk(root):   # 접근이 막힌 폴더는 자동으로 건너뜁니다
        if exe in files:
            return os.path.join(cur, exe)
        if cur.count(os.sep) - base >= max_depth:
            dirs[:] = []
    return None


def _glob_find(exe):
    """다운로드·바탕화면 등에 압축을 풀어 둔 FFmpeg 폴더를 찾습니다."""
    _local, _pf, _pf86, home = _env_dirs()
    bases = [os.path.join(home, "Downloads"), os.path.join(home, "Desktop"),
             os.path.join(home, "Documents"), home, "C:\\"]
    for base in bases:
        for pat in ("ffmpeg*/bin", "ffmpeg*/*/bin", "*/ffmpeg*/bin"):
            hits = sorted(glob.glob(os.path.join(base, pat, exe)))
            if hits:
                return hits[-1]
    return None


def find_tool(name, prefer_dir=None):
    """ffmpeg, ffprobe 같은 도구의 위치를 찾습니다. 없으면 None."""
    exe = _exe(name)
    if prefer_dir:
        p = os.path.join(prefer_dir, exe)
        if os.path.isfile(p):
            return p
    found = shutil.which(name)
    if found:
        return found
    for d in _candidate_dirs():
        p = os.path.join(d, exe)
        if os.path.isfile(p):
            return p
    for root in _package_roots():
        hit = _walk_find(exe, root)
        if hit:
            return hit
    return _glob_find(exe)


def find_ffmpeg_pair():
    """(ffmpeg 경로, ffprobe 경로). ffprobe는 ffmpeg와 같은 폴더를 먼저 찾습니다."""
    ff = find_tool("ffmpeg")
    fp = find_tool("ffprobe", prefer_dir=os.path.dirname(ff) if ff else None)
    return ff, fp


def remember_ffmpeg(ffmpeg_path):
    data = _load_settings()
    data["ffmpeg_dir"] = os.path.dirname(ffmpeg_path)
    _save_settings(data)


def admin_install_suspected():
    """관리자 권한으로 설치한 WinGet FFmpeg 폴더가 있는데 못 찾은 경우를 알아봅니다."""
    _local, pf, pf86, _home = _env_dirs()
    for root in (pf, pf86):
        if glob.glob(os.path.join(root, "WinGet", "Packages", "*FFmpeg*")):
            return True
    return False


def _fonts_in(folder):
    out = []
    if folder and os.path.isdir(folder):
        try:
            for f in os.listdir(folder):
                if f.lower().endswith((".ttf", ".otf", ".ttc")):
                    out.append(os.path.join(folder, f))
        except OSError:
            pass
    return out


def find_font():
    """(글꼴 경로, 안내문). 글꼴이 없으면 (None, 안내문)."""
    local = os.environ.get("LOCALAPPDATA", "")
    win = os.environ.get("WINDIR", "C:\\Windows")
    folders = [
        HERE,
        os.path.join(HERE, "static"),
        os.path.join(HERE, "fonts"),
        os.path.join(local, "Microsoft", "Windows", "Fonts") if local else "",
        os.path.join(win, "Fonts"),
    ]
    noto = []
    for fo in folders:
        noto += [p for p in _fonts_in(fo)
                 if os.path.basename(p).lower().startswith("notosanskr")]
    static = [p for p in noto if "variable" not in os.path.basename(p).lower()]
    for weight in ("bold", "medium", "regular"):
        for p in static:
            if weight in os.path.basename(p).lower():
                return p, None
    if static:
        return static[0], None
    if noto:
        return noto[0], ("Noto Sans KR 가변 글꼴만 찾았습니다. 자막이 얇게 보이면 "
                         "static 폴더의 NotoSansKR-Bold.ttf를 이 프로그램 폴더에 넣어 주세요.")
    for name in ("malgunbd.ttf", "malgun.ttf"):
        p = os.path.join(win, "Fonts", name)
        if os.path.isfile(p):
            return p, "Noto Sans KR을 찾지 못해 윈도우 기본 글꼴(맑은 고딕)로 자막을 넣습니다."
    for p in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",):
        if os.path.isfile(p):
            return p, None
    return None, "한글 글꼴을 찾지 못했습니다. 자막을 넣으려면 Noto Sans KR 글꼴이 필요합니다."


# ----------------------------------------------------------------------
# 시간 처리
# ----------------------------------------------------------------------
def parse_time(text):
    """'12:30', '1:02:30', '90', '12:30.5' -> 초(float). 잘못되면 ValueError."""
    t = str(text).strip().replace("：", ":")
    if not t:
        raise ValueError("비어 있음")
    parts = t.split(":")
    if len(parts) > 3:
        raise ValueError("형식 오류")
    secs = 0.0
    for p in parts:
        secs = secs * 60 + float(p)
    if secs < 0:
        raise ValueError("음수")
    return secs


def fmt_time(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ----------------------------------------------------------------------
# 영상 정보
# ----------------------------------------------------------------------
def _fps(stream):
    for key in ("avg_frame_rate", "r_frame_rate"):
        val = stream.get(key, "0/0")
        try:
            n, d = val.split("/")
            n, d = int(n), int(d)
            if d and 1 <= n / d <= 120:
                return f"{n}/{d}"
        except (ValueError, ZeroDivisionError):
            pass
    return "30/1"


def probe(ffprobe, path):
    cmd = [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path]
    r = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise EditError("영상 정보를 읽지 못했습니다.\n" + r.stderr.decode("utf-8", "replace")[-400:])
    data = json.loads(r.stdout.decode("utf-8", "replace"))
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v is None:
        raise EditError("영상 스트림을 찾지 못했습니다.")
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    try:
        rot = int(float(v.get("tags", {}).get("rotate", 0)))
    except (TypeError, ValueError):
        pass
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    if abs(rot) % 180 == 90:
        w, h = h, w
    dur = data.get("format", {}).get("duration") or v.get("duration") or 0
    return {
        "width": w - w % 2,
        "height": h - h % 2,
        "fps": _fps(v),
        "duration": float(dur),
        "codec": v.get("codec_name", "?"),
        "transfer": v.get("color_transfer", "") or "",
        "primaries": v.get("color_primaries", "") or "",
        "matrix": v.get("color_space", "") or "",
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def has_tonemap_filters(ffmpeg):
    """HDR -> SDR 변환에 필요한 필터(zscale, tonemap)가 있는지."""
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        text = r.stdout.decode("utf-8", "replace")
    except OSError:
        return False
    return " zscale " in text and " tonemap " in text


# ----------------------------------------------------------------------
# 편집 엔진
# ----------------------------------------------------------------------
def _write_text(folder, name, text):
    with open(os.path.join(folder, name), "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\r\n", "\n").replace("\r", "\n").strip("\n"))


def has_encoder(ffmpeg, name):
    """FFmpeg에 해당 인코더(예: libx265)가 들어 있는지."""
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        return (" " + name + " ") in r.stdout.decode("utf-8", "replace")
    except OSError:
        return False


def _hdr_tags(info):
    trc = info["transfer"] if info["transfer"] in HDR_TRANSFERS else "smpte2084"
    prim = info["primaries"] if info["primaries"] else "bt2020"
    mat = info["matrix"] if info["matrix"] else "bt2020nc"
    return prim, trc, mat


def _hdr_codec_args(fps, info):
    prim, trc, mat = _hdr_tags(info)
    x265 = (f"colorprim={prim}:transfer={trc}:colormatrix={mat}:range=limited:"
            "log-level=error")
    return ["-r", fps,
            "-c:v", "libx265", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p10le",
            "-tag:v", "hvc1", "-x265-params", x265,
            "-colorspace", mat, "-color_primaries", prim, "-color_trc", trc,
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


def _drawtext(textfile, fontsize, x, y, color="white"):
    border = max(8, fontsize // 3)
    return (f"drawtext=fontfile=font.ttf:textfile={textfile}:expansion=none:"
            f"fontsize={fontsize}:fontcolor={color}:box=1:boxcolor=black@0.55:"
            f"boxborderw={border}:x={x}:y={y}")


TONEMAP_CHAIN = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                 "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def _codec_args(fps):
    return ["-r", fps,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


def _run(cmd, cwd, cancel):
    errfile = os.path.join(cwd, "ffmpeg_error.log")
    with open(errfile, "wb") as ef:
        p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=ef,
                             creationflags=NO_WINDOW)
        while True:
            try:
                rc = p.wait(timeout=0.3)
                break
            except subprocess.TimeoutExpired:
                if cancel.is_set():
                    p.terminate()
                    p.wait()
                    raise Cancelled()
    if rc != 0:
        with open(errfile, "rb") as ef:
            tail = ef.read().decode("utf-8", "replace")[-700:]
        raise EditError("FFmpeg 처리 중 오류가 발생했습니다.\n\n" + tail)


RATIOS = {"1:1": (1, 1), "4:3": (4, 3), "16:9": (16, 9)}
DEFAULT_RATIO = "16:9"


def _even(v):
    v = int(round(v))
    return max(2, v - v % 2)


def output_size(W, H, ratio_name):
    """저장 영상 크기. 가로 영상은 높이를 유지하고 가로를 비율에 맞춥니다. (1920x1080: 1:1→1080x1080, 4:3→1440x1080)"""
    rw, rh = RATIOS.get(ratio_name, RATIOS[DEFAULT_RATIO])
    r = rw / rh
    oh, ow = H, H * r
    longest = max(W, H)
    if ow > longest:
        ow, oh = longest, longest / r
    return _even(ow), _even(oh)


def normalize_crop(crop, W, H):
    """화면에서 온 범위(가로·세로 비율 0~1)를 영상 픽셀 (너비, 높이, x, y)로 바꿉니다. 없거나 전체이면 None."""
    if not crop:
        return None
    try:
        x, y, w, h = (float(crop[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return None
    w = min(max(w, 0.02), 1.0)
    h = min(max(h, 0.02), 1.0)
    x = min(max(x, 0.0), 1.0 - w)
    y = min(max(y, 0.0), 1.0 - h)
    cw, ch = _even(w * W), _even(h * H)
    cx, cy = int(x * W), int(y * H)
    cx -= cx % 2
    cy -= cy % 2
    cw = min(cw, W - cx - (W - cx) % 2)
    ch = min(ch, H - cy - (H - cy) % 2)
    if cw >= W and ch >= H:
        return None
    return cw, ch, cx, cy


def make_highlight(ffmpeg, src, info, segments, title, font, out_path,
                   progress, cancel, tonemap_ok, keep_hdr=True, out_ratio=DEFAULT_RATIO):
    """
    segments: [{"start": 초, "end": 초, "text": 문자열, "pos": 위치이름, "crop": {x,y,w,h}(0~1) 또는 None}, ...]
    out_ratio: 저장 영상 비율 "1:1" / "4:3" / "16:9"  (비율이 다른 구간은 검은 여백으로 맞춤)
    title:    {"text": 문자열, "secs": 초} 또는 None  (메인화면)
    progress: progress(완료 수, 전체 수, 메시지)
    """
    needs_font = bool(title and title["text"]) or any(s["text"] for s in segments)
    if needs_font and not font:
        raise EditError("자막용 한글 글꼴을 찾지 못했습니다.\nNoto Sans KR 글꼴을 설치하거나 "
                        "프로그램 폴더에 넣어 주세요.")
    src = os.path.abspath(src)
    out_path = os.path.abspath(out_path)
    W, H, fps = info["width"], info["height"], info["fps"]
    OW, OH = output_size(W, H, out_ratio)
    is_hdr = info["transfer"] in HDR_TRANSFERS
    keep = is_hdr and keep_hdr and has_encoder(ffmpeg, "libx265")   # 원본 HDR 그대로 저장
    hdr = is_hdr and not keep and tonemap_ok                        # (대안) 일반 색상으로 변환
    pixfmt = "yuv420p10le" if keep else "yuv420p"
    # 자막 글자색: HDR 화면에서 눈부시지 않도록 기준 흰색(약 200nit) 수준의 회색
    txt_color = "white"
    if keep:
        txt_color = "#949494" if info["transfer"] == "smpte2084" else "#BFBFBF"
    codec = (lambda: _hdr_codec_args(fps, info)) if keep else (lambda: _codec_args(fps))
    tmp = tempfile.mkdtemp(prefix="hl_")
    try:
        if font:
            shutil.copyfile(font, os.path.join(tmp, "font.ttf"))
        total = (1 if title else 0) + len(segments) + 1
        done = 0
        parts = []

        if title:
            secs = f"{title['secs']:.3f}"
            progress(done, total, "메인화면 만드는 중...")
            _write_text(tmp, "title.txt", title["text"])
            fs = max(24, round(OH / 12))
            vf = ",".join([
                f"format={pixfmt}",
                _drawtext("title.txt", fs, "(w-text_w)/2", "(h-text_h)/2", txt_color),
            ])
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "lavfi", "-i", f"color=c=black:s={OW}x{OH}:r={fps}:d={secs}",
                   "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                   "-t", secs, "-map", "0:v", "-map", "1:a", "-vf", vf] + codec() + \
                  ["seg_title.mp4"]
            _run(cmd, tmp, cancel)
            parts.append("seg_title.mp4")
            done += 1

        for i, s in enumerate(segments, start=1):
            progress(done, total, f"득점 구간 {i}/{len(segments)} 처리 중...")
            dur = s["end"] - s["start"]
            vf_parts = []
            cp = normalize_crop(s.get("crop"), W, H)
            if cp:
                vf_parts.append(f"crop={cp[0]}:{cp[1]}:{cp[2]}:{cp[3]}")
            # 저장 크기에 맞추고, 비율이 다르면 검은 여백
            vf_parts.append(f"scale={OW}:{OH}:force_original_aspect_ratio=decrease:flags=lanczos")
            vf_parts.append(f"pad={OW}:{OH}:(ow-iw)/2:(oh-ih)/2:black")
            vf_parts.append(TONEMAP_CHAIN if hdr else f"format={pixfmt}")
            if s["text"]:
                _write_text(tmp, f"sub_{i}.txt", s["text"])
                x, y = POSITIONS.get(s["pos"], POSITIONS[DEFAULT_POSITION])
                vf_parts.append(_drawtext(f"sub_{i}.txt", max(18, round(OH / 18)), x, y, txt_color))
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                   "-ss", f"{s['start']:.3f}", "-i", src, "-t", f"{dur:.3f}"]
            if info["has_audio"]:
                audio_map = "0:a:0"
            else:
                cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
                audio_map = "1:a:0"
            cmd += ["-map", "0:v:0", "-map", audio_map, "-vf", ",".join(vf_parts)]
            cmd += codec() + [f"seg_{i:03d}.mp4"]
            _run(cmd, tmp, cancel)
            parts.append(f"seg_{i:03d}.mp4")
            done += 1

        progress(done, total, "하나의 영상으로 합치는 중...")
        with open(os.path.join(tmp, "list.txt"), "w", encoding="utf-8") as f:
            for p in parts:
                f.write(f"file '{p}'\n")
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", "list.txt",
               "-c", "copy", "-movflags", "+faststart", "final.mp4"]
        _run(cmd, tmp, cancel)
        shutil.move(os.path.join(tmp, "final.mp4"), out_path)
        progress(total, total, "완료")
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------
# 득점 구간 목록 계산 (화면과 무관한 부분)
# ----------------------------------------------------------------------
def fmt_time1(sec):
    """초 -> '05:42.3' (0.1초 단위). None이면 빈 문자열."""
    if sec is None:
        return ""
    tenths = int(round(max(0.0, float(sec)) * 10))
    h, rem = divmod(tenths, 36000)
    m, rem = divmod(rem, 600)
    s = rem / 10
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m:02d}:{s:04.1f}"


def fps_label(fps):
    """'30000/1001' -> '29.97', '30/1' -> '30'"""
    try:
        n, d = fps.split("/")
        v = int(n) / int(d)
    except (ValueError, ZeroDivisionError):
        return str(fps)
    return f"{v:.0f}" if abs(v - round(v)) < 0.005 else f"{v:.2f}"


def new_row(start=None, end=None, active=False):
    return {"start": start, "end": end, "text": "", "pos": DEFAULT_POSITION, "active": active,
            "cropOn": False, "cropRatio": None, "crop": None}


class Marks:
    """득점 구간 목록. [득점 시작]을 누르면 '지정 중' 행이 생기고, [득점 종료]에서 완성됩니다."""

    def __init__(self):
        self.rows = []

    def active_index(self):
        for i, r in enumerate(self.rows):
            if r["active"]:
                return i
        return None

    def begin(self, pos):
        if self.active_index() is not None:
            raise MarkError("이미 [득점 시작]을 눌렀습니다. 먼저 [득점 종료]를 눌러 주세요.")
        self.rows.append(new_row(start=float(pos), active=True))

    def finish(self, pos):
        i = self.active_index()
        if i is None:
            raise MarkError("먼저 [득점 시작]을 눌러 주세요.")
        r = self.rows[i]
        if pos <= r["start"]:
            raise MarkError("종료 위치가 시작 위치보다 앞입니다. 영상을 더 재생한 뒤 눌러 주세요.")
        r["end"] = float(pos)
        r["active"] = False
        return i

    def cancel(self):
        i = self.active_index()
        if i is None:
            return False
        del self.rows[i]
        return True

    def add_blank(self):
        self.rows.append(new_row())

    def delete(self, i):
        del self.rows[i]

    def set_time(self, i, key, value):
        """key는 'start' 또는 'end', value는 초 또는 None(비움)."""
        r = self.rows[i]
        other = r["end" if key == "start" else "start"]
        if value is not None and other is not None:
            s, e = (value, other) if key == "start" else (other, value)
            if e <= s:
                raise MarkError("종료 시간은 시작 시간보다 늦어야 합니다.")
        r[key] = value

    def nudge(self, i, key, delta, duration=0.0):
        """시작/종료 시간을 delta초만큼 움직입니다. 결과 시간을 돌려줍니다."""
        cur = self.rows[i][key]
        if cur is None:
            raise MarkError("먼저 시간을 입력해 주세요.")
        new = max(0.0, cur + delta)
        if duration and new > duration:
            new = float(duration)
        self.set_time(i, key, new)
        return new

    def complete_ranges(self):
        return [(r["start"], r["end"]) for r in self.rows
                if not r["active"] and r["start"] is not None
                and r["end"] is not None and r["end"] > r["start"]]


def crop_base(W, H, ratio):
    """비율 ratio에서 영상 안에 들어가는 가장 큰 사각형 (가로, 세로: 0~1)"""
    a, b = RATIOS[ratio]
    r = a / b
    return (r * H / W, 1.0) if r <= W / H else (1.0, W / (r * H))


def crop_make(W, H, ratio, zoom, cx=0.5, cy=0.5):
    """확대 배율 zoom(1~4)과 중심 (cx, cy)로 범위 사각형 {x,y,w,h} (0~1)을 만듭니다."""
    bw, bh = crop_base(W, H, ratio)
    zoom = min(4.0, max(1.0, float(zoom)))
    w, h = bw / zoom, bh / zoom
    return {"w": w, "h": h,
            "x": min(1.0 - w, max(0.0, cx - w / 2)),
            "y": min(1.0 - h, max(0.0, cy - h / 2))}


def crop_zoom(W, H, ratio, crop):
    return crop_base(W, H, ratio)[0] / crop["w"]


def crop_center(crop):
    return crop["x"] + crop["w"] / 2, crop["y"] + crop["h"] / 2


def crop_resize(W, H, ratio, crop, handle, px, py):
    """모서리(handle: tl/tr/bl/br)를 (px, py)로 끌었을 때의 새 범위. 반대쪽 모서리는 고정, 비율 유지."""
    a, b = RATIOS[ratio]
    k = (W / H) * (b / a)                     # 정규화 좌표에서 높이 = 너비 * k
    left = handle in ("tl", "bl")
    up = handle in ("tl", "tr")
    ax = crop["x"] + crop["w"] if left else crop["x"]
    ay = crop["y"] + crop["h"] if up else crop["y"]
    w = max(abs(px - ax), abs(py - ay) / k)
    avail_x = ax if left else 1.0 - ax
    avail_y = ay if up else 1.0 - ay
    w = min(w, avail_x, avail_y / k)
    w = max(w, crop_base(W, H, ratio)[0] / 4)  # 최대 4배 확대
    w = min(w, avail_x, avail_y / k)
    h = w * k
    return {"w": w, "h": h, "x": ax - w if left else ax, "y": ay - h if up else ay}


def len_text(r):
    if r["start"] is not None and r["end"] is not None and r["end"] > r["start"]:
        return f"{r['end'] - r['start']:.1f}초"
    return "-"


def collect_segments(rows, duration):
    """편집에 쓸 구간 목록을 만듭니다. 문제가 있으면 ValueError(안내문)."""
    segs = []
    for i, r in enumerate(rows, start=1):
        if r["active"]:
            raise ValueError(f"{i}번 구간은 아직 [득점 종료]를 누르지 않았습니다.\n"
                             "종료를 누르거나 [지정 취소]를 눌러 주세요.")
        s, e, t = r["start"], r["end"], r["text"].strip()
        if s is None and e is None and not t:
            continue
        if s is None or e is None:
            raise ValueError(f"{i}번 구간의 시작/종료 시간을 입력해 주세요.")
        if e <= s:
            raise ValueError(f"{i}번 구간은 종료 시간이 시작 시간보다 늦어야 합니다.")
        if duration and s >= duration:
            raise ValueError(f"{i}번 구간의 시작 시간이 영상 길이({fmt_time(duration)})를 넘었습니다.")
        if duration and e > duration + 0.5:
            e = duration
        segs.append({"start": s, "end": e, "text": t, "pos": r["pos"],
                     "crop": r.get("crop") if r.get("cropOn") else None})
    return segs


