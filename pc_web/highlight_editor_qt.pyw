# -*- coding: utf-8 -*-
"""
농구 하이라이트 편집기 (Windows 10 / 64비트용, 화면: PySide6)

영상을 이 프로그램 안에서 재생하면서 [득점 시작] / [득점 종료] 버튼으로 구간을 지정하고,
메인화면 자막과 구간별 자막을 넣어 하나의 MP4 하이라이트로 저장합니다.

필요한 것: Python, FFmpeg, PySide6 (자막 글꼴은 Noto Sans KR 권장)
설치:      python -m pip install pyside6
실행:      이 파일(highlight_editor_qt.pyw)을 더블클릭

영상 불러오기: [영상 파일 선택] 버튼 또는 창 위로 영상 파일을 끌어다 놓기
단축키:    S = 득점 시작, E = 득점 종료, 스페이스 = 재생/일시정지, 좌/우 화살표 = 5초 이동
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback

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


try:
    from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, QSizeF, Qt, QTimer, QUrl, Signal
    from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QIcon, QImage, QKeySequence, QPixmap,
                               QPainter, QPainterPath, QPalette, QShortcut)
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QGraphicsVideoItem, QVideoWidget
    from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
                                   QGraphicsScene, QGraphicsView,
                                   QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                                   QButtonGroup, QMainWindow, QMessageBox, QProgressBar, QPushButton,
                                   QScrollArea, QSizePolicy, QSlider, QStackedWidget, QTabWidget,
                                   QVBoxLayout, QWidget)
except ImportError as _err:
    _fatal("PySide6가 설치되어 있지 않아 프로그램을 실행할 수 없습니다.\n\n"
           "윈도우 키를 누르고 cmd 를 입력해 명령 프롬프트를 연 뒤\n"
           "python -m pip install pyside6\n"
           "를 입력하고 Enter를 눌러 설치한 다음 다시 실행해 주세요.\n\n"
           "(자세한 오류: %s)" % _err)

# 자막 위치 이름 -> (x 식, y 식)
# 프로그램 아이콘 (남색 바탕 + 필름 띠 + 농구공 + 재생 버튼) — PC 앱 전용
ICON_B64 = "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"


def app_icon():
    import base64
    img = QImage()
    img.loadFromData(base64.b64decode(ICON_B64))
    return QIcon(QPixmap.fromImage(img))


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
        "pix_fmt": v.get("pix_fmt", "") or "",
        "acodec": (next((s for s in streams if s.get("codec_type") == "audio"), {}) or {}).get("codec_name", ""),
        "arate": (next((s for s in streams if s.get("codec_type") == "audio"), {}) or {}).get("sample_rate", ""),
        "achannels": (next((s for s in streams if s.get("codec_type") == "audio"), {}) or {}).get("channels", 0),
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
                   progress, cancel, tonemap_ok, keep_hdr=True, out_ratio=DEFAULT_RATIO,
                   out_size=None, label="득점 구간", ai=None):
    """
    segments: [{"start": 초, "end": 초, "text": 문자열, "pos": 위치이름, "crop": {x,y,w,h}(0~1) 또는 None}, ...]
    out_ratio: 저장 영상 비율 "1:1" / "4:3" / "16:9"  (비율이 다른 구간은 검은 여백으로 맞춤)
    title:    {"text": 문자열, "secs": 초} 또는 None  (메인화면)
    progress: progress(완료 수, 전체 수, 메시지)
    ai:       {"exe": Real-ESRGAN 경로, "model": "quality"|"fast"} 이면 범위로 확대한 구간을 AI로 선명하게
    """
    needs_font = bool(title and title["text"]) or any(s["text"] for s in segments)
    if needs_font and not font:
        raise EditError("자막용 한글 글꼴을 찾지 못했습니다.\nNoto Sans KR 글꼴을 설치하거나 "
                        "프로그램 폴더에 넣어 주세요.")
    src = os.path.abspath(src)
    out_path = os.path.abspath(out_path)
    W, H, fps = info["width"], info["height"], info["fps"]
    OW, OH = out_size if out_size else output_size(W, H, out_ratio)
    is_hdr = info["transfer"] in HDR_TRANSFERS
    ai_on = bool(ai and ai.get("exe") and any(normalize_crop(sg.get("crop"), W, H) for sg in segments))
    if ai_on and is_hdr:
        keep_hdr = False      # AI 선명화 그림은 일반(SDR) 색상이라, 섞이지 않게 전체를 일반 색상으로 저장
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
            progress(done, total, f"{label} {i}/{len(segments)} 처리 중...")
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
            if ai_on and cp:
                _ai_segment(ffmpeg, ai, src, info, s, i, len(segments), cp, OW, OH, pixfmt, hdr, codec,
                            vf_parts[-1] if s["text"] else None, tmp, f"seg_{i:03d}.mp4",
                            lambda frac, msg, d=done: progress(d + frac, total, msg), cancel)
                parts.append(f"seg_{i:03d}.mp4")
                done += 1
                continue
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
# AI 선명화 (Real-ESRGAN, 그래픽카드 사용) — 범위로 확대한 구간만
# ----------------------------------------------------------------------
ESRGAN_URL = ("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
              "realesrgan-ncnn-vulkan-20220424-windows.zip")
ESRGAN_SHA256 = "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d"
ESRGAN_DIR = os.path.join(HERE, "realesrgan")
# 화질: 고화질 = 실사 사진용 4배 모델 / 빠르게 = 영상용 경량 2배 모델
AI_MODELS = {"quality": ("realesrgan-x4plus", 4), "fast": ("realesr-animevideov3", 2)}
AI_BENCH_FRAMES = 10
AI_BENCH_SIZE = (960, 540)


def esrgan_exe_name():
    return "realesrgan-ncnn-vulkan.exe" if IS_WIN else "realesrgan-ncnn-vulkan"


def find_esrgan():
    """Real-ESRGAN 실행 파일 경로. 없으면 None."""
    exe = esrgan_exe_name()
    p = os.path.join(ESRGAN_DIR, exe)
    if os.path.isfile(p):
        return p
    hits = glob.glob(os.path.join(ESRGAN_DIR, "**", exe), recursive=True)
    return hits[0] if hits else None


def get_ai_prefs():
    d = _load_settings()
    model = d.get("ai_model", "quality")
    return {"on": bool(d.get("ai_on", False)), "model": model if model in AI_MODELS else "quality",
            "speed": d.get("ai_speed", {}) if isinstance(d.get("ai_speed"), dict) else {}}


def set_ai_prefs(on=None, model=None, speed=None):
    d = _load_settings()
    if on is not None:
        d["ai_on"] = bool(on)
    if model in AI_MODELS:
        d["ai_model"] = model
    if speed:
        sp = d.get("ai_speed") if isinstance(d.get("ai_speed"), dict) else {}
        sp.update(speed)
        d["ai_speed"] = sp
    _save_settings(d)


def install_esrgan(progress, cancel):
    """공식 배포 파일(Windows용 zip)을 내려받아 프로그램 폴더의 realesrgan 폴더에 풉니다."""
    import hashlib
    import urllib.request
    import zipfile
    os.makedirs(ESRGAN_DIR, exist_ok=True)
    tmpzip = os.path.join(ESRGAN_DIR, "download.zip")
    h = hashlib.sha256()
    try:
        req = urllib.request.Request(ESRGAN_URL, headers={"User-Agent": "highlight-editor"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmpzip, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                if cancel.is_set():
                    raise Cancelled()
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                h.update(b)
                got += len(b)
                progress(got, max(total, got), f"AI 선명화 도구 내려받는 중... {got >> 20}MB"
                         + (f" / {total >> 20}MB" if total else ""))
    except (Cancelled, EditError):
        raise
    except Exception as e:
        raise EditError("AI 선명화 도구를 내려받지 못했습니다. 인터넷 연결을 확인해 주세요.\n\n" + str(e)[:300])
    if h.hexdigest() != ESRGAN_SHA256:
        os.remove(tmpzip)
        raise EditError("내려받은 파일이 공식 배포 파일과 다릅니다. 잠시 뒤 다시 시도해 주세요.")
    with zipfile.ZipFile(tmpzip) as z:
        z.extractall(ESRGAN_DIR)
    os.remove(tmpzip)
    exe = find_esrgan()
    if not exe:
        raise EditError("AI 선명화 도구 파일을 찾지 못했습니다.")
    return exe


def _run_esrgan(exe, indir, outdir, model_key, cancel, on_count=None, scale=None):
    """폴더의 그림들을 AI로 키웁니다. on_count(완성된 장 수)로 진행을 알립니다."""
    model, mscale = AI_MODELS[model_key]
    scale = scale or mscale
    total = len([f for f in os.listdir(indir) if f.lower().endswith(".jpg")])
    errfile = os.path.join(os.path.dirname(outdir), "esrgan_error.log")
    exe_dir = os.path.dirname(exe)
    cmd = [exe, "-i", indir, "-o", outdir, "-n", model, "-s", str(scale), "-f", "jpg",
           "-m", os.path.join(exe_dir, "models")]
    with open(errfile, "wb") as ef:
        p = subprocess.Popen(cmd, cwd=exe_dir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=ef, creationflags=NO_WINDOW)
        while True:
            try:
                rc = p.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if cancel.is_set():
                    p.terminate()
                    p.wait()
                    raise Cancelled()
                if on_count:
                    on_count(len(os.listdir(outdir)), total)
    made = len([f for f in os.listdir(outdir) if f.lower().endswith(".jpg")])
    if rc != 0 or made < total:
        with open(errfile, "rb") as ef:
            tail = ef.read().decode("utf-8", "replace")[-500:]
        raise EditError("AI 선명화 중 오류가 발생했습니다. 그래픽카드 드라이버를 최신으로 업데이트한 뒤 "
                        "다시 해 보세요. (또는 AI 선명화를 끄고 저장)\n\n" + tail)
    if on_count:
        on_count(made, total)
    return made


def esrgan_benchmark(ffmpeg, exe, model_key, cancel):
    """시험 그림 10장으로 속도를 잽니다. 결과: 1메가픽셀 한 장당 초."""
    tmp = tempfile.mkdtemp(prefix="esrb_")
    try:
        ind, outd = os.path.join(tmp, "in"), os.path.join(tmp, "out")
        os.makedirs(ind)
        os.makedirs(outd)
        w, h = AI_BENCH_SIZE
        _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
              "-i", f"testsrc2=size={w}x{h}:rate=30", "-frames:v", str(AI_BENCH_FRAMES), "-q:v", "2",
              os.path.join(ind, "%06d.jpg")], tmp, cancel)
        t0 = time.time()
        _run_esrgan(exe, ind, outd, model_key, cancel)
        spmp = (time.time() - t0) / (AI_BENCH_FRAMES * w * h / 1e6)
        set_ai_prefs(speed={model_key: round(spmp, 4)})
        return spmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _fps_value(fps):
    try:
        t = str(fps)
        if "/" in t:
            n, d = t.split("/")
            return float(n) / float(d)
        return float(t)
    except (ValueError, ZeroDivisionError):
        return 30.0


def ai_targets(segments, info):
    """AI 선명화 대상 구간: [(번호, 프레임 수, 잘라낸 픽셀 수)]"""
    out = []
    W, H = info["width"], info["height"]
    fps = _fps_value(info.get("fps", "30"))
    for i, s in enumerate(segments, start=1):
        cp = normalize_crop(s.get("crop"), W, H)
        if cp and s.get("start") is not None and s.get("end") is not None:
            out.append((i, int((s["end"] - s["start"]) * fps) + 1, cp[0] * cp[1]))
    return out


def ai_estimate(segments, info, model_key):
    """예상 시간(초). 속도를 아직 안 쟀으면 None."""
    spmp = get_ai_prefs()["speed"].get(model_key)
    if not spmp:
        return None
    return sum(fr * px / 1e6 * spmp for _i, fr, px in ai_targets(segments, info))


def fmt_eta(sec):
    sec = int(round(sec))
    if sec < 60:
        return f"{sec}초"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m}분 {s}초" if s and m < 10 else f"{m}분"
    h, m = divmod(m, 60)
    return f"{h}시간 {m}분"


def _ai_segment(ffmpeg, ai, src, info, s, idx, count, cp, OW, OH, pixfmt, hdr, codec, drawtext,
                tmp, out_name, progress, cancel):
    """확대 구간 하나: 잘라낸 장면을 그림으로 뽑아 → AI로 키움 → 저장 크기로 맞춰 영상으로."""
    dur = s["end"] - s["start"]
    fps = info["fps"]
    ind, outd = os.path.join(tmp, f"ai{idx}_in"), os.path.join(tmp, f"ai{idx}_out")
    os.makedirs(ind, exist_ok=True)
    os.makedirs(outd, exist_ok=True)
    progress(0.0, f"AI 선명화 준비 · {idx}번 구간 장면 뽑는 중...")
    pre = [f"crop={cp[0]}:{cp[1]}:{cp[2]}:{cp[3]}", f"fps={fps}",
           TONEMAP_CHAIN if hdr else "format=yuv420p"]
    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{s['start']:.3f}", "-i", src,
          "-t", f"{dur:.3f}", "-an", "-vf", ",".join(pre), "-q:v", "2",
          os.path.join(ind, "%06d.jpg")], tmp, cancel)
    t0 = time.time()

    def on_count(n, total):
        frac = 0.9 * n / max(total, 1)
        eta = ""
        if n >= 3:
            eta = " · 남은 시간 약 " + fmt_eta((time.time() - t0) / n * (total - n))
        progress(frac, f"AI 선명화 중 · {idx}번 구간 · 프레임 {n}/{total}{eta}")
    _run_esrgan(ai["exe"], ind, outd, ai.get("model", "quality"), cancel, on_count)
    shutil.rmtree(ind, ignore_errors=True)
    progress(0.92, f"AI 선명화 · {idx}번 구간 영상으로 합치는 중...")
    vf = [f"scale={OW}:{OH}:force_original_aspect_ratio=decrease:flags=lanczos",
          f"pad={OW}:{OH}:(ow-iw)/2:(oh-ih)/2:black", f"format={pixfmt}"]
    if drawtext:
        vf.append(drawtext)
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-framerate", fps,
           "-i", os.path.join(outd, "%06d.jpg")]
    if info["has_audio"]:
        cmd += ["-ss", f"{s['start']:.3f}", "-t", f"{dur:.3f}", "-i", src]
    else:
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += ["-map", "0:v:0", "-map", "1:a:0", "-vf", ",".join(vf), "-shortest"] + codec() + [out_name]
    _run(cmd, tmp, cancel)
    shutil.rmtree(outd, ignore_errors=True)
    progress(1.0, f"AI 선명화 · {idx}번 구간 완료")


# ----------------------------------------------------------------------
# 구간 삭제(컷 편집) / 영상 합치기
# ----------------------------------------------------------------------
def merge_ranges(ranges, dur=0.0):
    """겹치거나 붙은 구간을 합치고 영상 길이 안으로 자릅니다. [(시작, 끝)] -> 정렬된 [(시작, 끝)]"""
    out = []
    for s, e in sorted((max(0.0, float(a)), float(b)) for a, b in ranges):
        if dur:
            e = min(e, float(dur))
        if e - s <= 0.001:
            continue
        if out and s <= out[-1][1] + 0.001:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def keep_ranges(deletes, dur, min_len=0.2):
    """지울 구간을 뺀 나머지(남길 구간) 목록"""
    keep, cur = [], 0.0
    for s, e in merge_ranges(deletes, dur):
        if s - cur >= min_len:
            keep.append((cur, s))
        cur = max(cur, e)
    if dur - cur >= min_len:
        keep.append((cur, float(dur)))
    return keep


def _esc(path):
    return path.replace("'", "'\\''")


def _write_concat(folder, paths, name="list.txt"):
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        for p in paths:
            f.write("file '%s'\n" % _esc(p))
    return name


def _concat_copy(ffmpeg, tmp, paths, out_name, cancel):
    _write_concat(tmp, paths)
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
           "-i", "list.txt", "-c", "copy", "-movflags", "+faststart", out_name]
    _run(cmd, tmp, cancel)


def make_cut(ffmpeg, src, info, deletes, out_path, progress, cancel, tonemap_ok, fast=False):
    """영상에서 deletes([(시작, 끝)])를 지우고 나머지를 이어 붙여 저장합니다.
    fast=True: 다시 인코딩하지 않아 빠르고 화질 손실이 없지만, 경계가 가까운 키프레임으로 맞춰져 약간 어긋날 수 있습니다."""
    dur = info["duration"]
    keep = keep_ranges(deletes, dur)
    if not keep:
        raise EditError("지우고 남는 영상이 없습니다. 지울 구간을 확인해 주세요.")
    if not fast:
        segs = [{"start": s, "end": e, "text": "", "pos": DEFAULT_POSITION, "crop": None} for s, e in keep]
        return make_highlight(ffmpeg, src, info, segs, None, None, out_path, progress, cancel,
                              tonemap_ok, True, DEFAULT_RATIO,
                              out_size=(info["width"], info["height"]), label="남길 구간")
    src = os.path.abspath(src)
    out_path = os.path.abspath(out_path)
    tmp = tempfile.mkdtemp(prefix="hl_")
    try:
        total = len(keep) + 1
        parts = []
        for i, (s, e) in enumerate(keep, start=1):
            progress(i - 1, total, f"남길 구간 {i}/{len(keep)} 자르는 중...")
            name = f"seg_{i:03d}.mp4"
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{s:.3f}", "-i", src,
                   "-t", f"{e - s:.3f}", "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                   "-avoid_negative_ts", "make_zero"]
            if info["codec"] == "hevc":
                cmd += ["-tag:v", "hvc1"]
            _run(cmd + [name], tmp, cancel)
            parts.append(name)
        progress(len(keep), total, "하나의 영상으로 합치는 중...")
        _concat_copy(ffmpeg, tmp, parts, "final.mp4", cancel)
        shutil.move(os.path.join(tmp, "final.mp4"), out_path)
        progress(total, total, "완료")
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _most_common(values):
    counts, order = {}, []
    for v in values:
        if v not in counts:
            counts[v] = 0
            order.append(v)
        counts[v] += 1
    best = order[0]
    for v in order:
        if counts[v] > counts[best]:
            best = v
    return best, counts[best]


def merge_plan(clips, transition=False, can_hdr=True):
    """합칠 영상들의 저장 조건을 정합니다. (가장 많은 크기·fps를 따르고, 모두 HDR이면 HDR 유지)"""
    infos = [c["info"] for c in clips]
    (ow, oh), n_size = _most_common([(i["width"], i["height"]) for i in infos])
    fps, _ = _most_common([i["fps"] for i in infos])
    all_hdr = all(i["transfer"] in HDR_TRANSFERS for i in infos)
    same_tr = len({i["transfer"] for i in infos}) == 1
    keep = bool(all_hdr and same_tr and can_hdr)
    any_hdr = any(i["transfer"] in HDR_TRANSFERS for i in infos)
    keys = {(i["codec"], i["width"], i["height"], i["fps"], i["transfer"], i["pix_fmt"], i["has_audio"],
             i["acodec"], i["arate"], i["achannels"]) for i in infos}
    fast = bool(len(keys) == 1 and not transition)
    return {"width": ow, "height": oh, "fps": fps, "keep": keep, "mixed_hdr": bool(any_hdr and not all_hdr),
            "fast": fast, "n_same_size": n_size, "ref": infos[0]}


def make_merge(ffmpeg, clips, out_path, progress, cancel, tonemap_ok, transition=False):
    """여러 영상을 순서대로 하나의 MP4로 합칩니다.
    clips: [{"path": 경로, "info": probe 결과}, ...]
    모두 같은 조건이면 다시 인코딩하지 않고 붙이고, 크기·fps·HDR이 다르면 맞춰서 다시 인코딩합니다."""
    if len(clips) < 2:
        raise EditError("합칠 영상을 2개 이상 추가해 주세요.")
    out_path = os.path.abspath(out_path)
    paths = [os.path.abspath(c["path"]) for c in clips]
    if os.path.abspath(out_path) in paths:
        raise EditError("합칠 영상과 같은 이름으로는 저장할 수 없습니다.")
    plan = merge_plan(clips, transition, has_encoder(ffmpeg, "libx265"))
    OW, OH, fps, keep = plan["width"], plan["height"], plan["fps"], plan["keep"]
    pixfmt = "yuv420p10le" if keep else "yuv420p"
    tmp = tempfile.mkdtemp(prefix="hl_")
    try:
        if plan["fast"]:
            progress(0, 2, "영상을 이어 붙이는 중... (다시 인코딩하지 않습니다)")
            _concat_copy(ffmpeg, tmp, paths, "final.mp4", cancel)
            shutil.move(os.path.join(tmp, "final.mp4"), out_path)
            progress(2, 2, "완료")
            return out_path
        total = len(clips) + 1
        codec = (lambda: _hdr_codec_args(fps, plan["ref"])) if keep else (lambda: _codec_args(fps))
        norm, durs = [], []
        for i, (c, p) in enumerate(zip(clips, paths), start=1):
            progress(i - 1, total, f"영상 {i}/{len(clips)} 크기·색상 맞추는 중...")
            info = c["info"]
            is_hdr = info["transfer"] in HDR_TRANSFERS
            vf = [f"scale={OW}:{OH}:force_original_aspect_ratio=decrease:flags=lanczos",
                  f"pad={OW}:{OH}:(ow-iw)/2:(oh-ih)/2:black"]
            if is_hdr and not keep and tonemap_ok:
                vf.append(TONEMAP_CHAIN)
            else:
                vf.append(f"format={pixfmt}")
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", p]
            if info["has_audio"]:
                amap = "0:a:0"
            else:
                cmd += ["-f", "lavfi", "-t", f"{info['duration']:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
                amap = "1:a:0"
            cmd += ["-map", "0:v:0", "-map", amap, "-vf", ",".join(vf)] + codec()
            name = f"n_{i:03d}.mp4"
            _run(cmd + [name], tmp, cancel)
            norm.append(name)
            durs.append(float(info["duration"]))
        progress(len(clips), total, "하나의 영상으로 합치는 중...")
        if not transition:
            _concat_copy(ffmpeg, tmp, norm, "final.mp4", cancel)
        else:
            T = max(0.1, min(0.5, min(durs) / 3.0))
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
            for n in norm:
                cmd += ["-i", n]
            fv, fa, acc = [], [], 0.0
            prev_v, prev_a = "0:v", "0:a"
            for k in range(1, len(norm)):
                acc += durs[k - 1]
                off = acc - k * T
                fv.append(f"[{prev_v}][{k}:v]xfade=transition=fade:duration={T:.3f}:offset={off:.3f}[v{k}]")
                fa.append(f"[{prev_a}][{k}:a]acrossfade=d={T:.3f}[a{k}]")
                prev_v, prev_a = f"v{k}", f"a{k}"
            last = len(norm) - 1
            cmd += ["-filter_complex", ";".join(fv + fa), "-map", f"[v{last}]", "-map", f"[a{last}]"]
            cmd += codec() + ["-movflags", "+faststart", "final.mp4"]
            _run(cmd, tmp, cancel)
        shutil.move(os.path.join(tmp, "final.mp4"), out_path)
        progress(total, total, "완료")
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------
# 편집 로그 (불러온 영상·득점 구간·자막·범위 설정을 파일로 저장/복원)
# ----------------------------------------------------------------------
LOG_KIND = "basketball-highlight-log"


def build_log(video_path, video_name, info, rows, title):
    """편집 상태를 로그(dict)로 만듭니다. video_path가 비어 있으면(끌어다 놓은 파일) 이름만 기록합니다."""
    import datetime
    out_rows = []
    for r in rows:
        crop = r.get("crop") if r.get("cropOn") else None
        out_rows.append({"start": r.get("start"), "end": r.get("end"), "text": str(r.get("text") or ""),
                         "pos": r.get("pos"), "cropOn": bool(crop),
                         "cropRatio": r.get("cropRatio") if crop else None, "crop": crop})
    return {"kind": LOG_KIND, "version": 1,
            "saved": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "video": {"path": video_path or "", "name": video_name, "width": info["width"],
                      "height": info["height"], "duration": info["duration"]},
            "title": {"on": bool(title.get("on")), "text": str(title.get("text") or ""),
                      "secs": str(title.get("secs") or "3")},
            "rows": out_rows}


def get_log_dir():
    """로그를 저장할 폴더(구글 드라이브·OneDrive 같은 동기화 폴더 등). 지정하지 않았거나 없으면 빈 문자열."""
    d = _load_settings().get("log_dir", "")
    return d if d and os.path.isdir(d) else ""


def set_log_dir(path):
    data = _load_settings()
    data["log_dir"] = path
    _save_settings(data)


def get_theme():
    t = _load_settings().get("theme", "auto")
    return t if t in ("light", "dark", "auto") else "auto"


def set_theme(mode):
    if mode not in ("light", "dark", "auto"):
        return
    data = _load_settings()
    data["theme"] = mode
    _save_settings(data)


def log_default_name(video_name):
    """로그 기본 파일명: 저장한 날짜(YYMMDD) + 영상 파일명. 예) 261103_파미용배 2경기 하이라이트.json"""
    import datetime
    return datetime.datetime.now().strftime("%y%m%d") + "_" + os.path.splitext(os.path.basename(video_name))[0] + ".json"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f >= 0 else None


def clean_log_rows(raw_rows, duration=0.0):
    """로그의 구간 목록을 검사해 화면에서 쓰는 형태로 바꿉니다. (잘못된 값은 버립니다)"""
    out = []
    for r in raw_rows if isinstance(raw_rows, list) else []:
        if not isinstance(r, dict):
            continue
        st, en = _num(r.get("start")), _num(r.get("end"))
        if duration:
            st = min(st, duration) if st is not None else None
            en = min(en, duration) if en is not None else None
        if st is not None and en is not None and en <= st:
            en = None
        crop, ratio = None, r.get("cropRatio")
        c = r.get("crop")
        if isinstance(c, dict) and ratio in RATIOS:
            x, y, w, h = (_num(c.get(k)) for k in ("x", "y", "w", "h"))
            if None not in (x, y, w, h) and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1.0001 and y + h <= 1.0001:
                crop = {"x": x, "y": y, "w": w, "h": h}
        out.append({"start": st, "end": en, "text": str(r.get("text") or ""),
                    "pos": r.get("pos") if r.get("pos") in POSITIONS else DEFAULT_POSITION,
                    "active": False, "cropOn": bool(crop), "cropRatio": ratio if crop else None, "crop": crop})
    return out


def read_log(path):
    """로그 파일을 읽어 검사한 뒤 dict로 돌려줍니다."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            log = json.load(f)
    except (OSError, ValueError):
        raise EditError("편집 로그 파일을 읽을 수 없습니다. 이 프로그램에서 저장한 로그 파일인지 확인해 주세요.")
    if not isinstance(log, dict) or log.get("kind") != LOG_KIND or not isinstance(log.get("video"), dict):
        raise EditError("이 프로그램에서 저장한 편집 로그 파일이 아닙니다.")
    v = log["video"]
    t = log.get("title") if isinstance(log.get("title"), dict) else {}
    return {"video": {"path": str(v.get("path") or ""), "name": str(v.get("name") or ""),
                      "duration": _num(v.get("duration")) or 0.0},
            "title": {"on": bool(t.get("on")), "text": str(t.get("text") or ""), "secs": str(t.get("secs") or "3")},
            "rows": log.get("rows") if isinstance(log.get("rows"), list) else []}


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


def auto_out_ratio(rows):
    """저장 영상 비율을 자동으로 정합니다: 완성된 구간 중 가장 많이 지정된 비율.
    범위를 쓰지 않은 구간은 전체 화면(16:9)으로 셉니다. 동률이면 먼저 나온 구간의 비율. 구간이 없으면 16:9."""
    counts, order = {}, []
    for r in rows:
        if r["active"] or r["start"] is None or r["end"] is None or r["end"] <= r["start"]:
            continue
        name = r["cropRatio"] if (r.get("cropOn") and r.get("crop") and r.get("cropRatio") in RATIOS) else DEFAULT_RATIO
        if name not in counts:
            order.append(name)
            counts[name] = 0
        counts[name] += 1
    if not counts:
        return DEFAULT_RATIO, 0, 0
    best = max(order, key=lambda n: (counts[n], -order.index(n)))
    return best, counts[best], sum(counts.values())


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


# ----------------------------------------------------------------------
# 화면(GUI)
# ----------------------------------------------------------------------
STYLE = """
QWidget { color: #111827; font-size: 10pt; }
#root { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @BGFROM@, stop:1 @BGTO@); }
#card { background: #E8ECF2; border: 1px solid #9AA7B8; border-radius: 16px; }
#videoBox { background: #0B1220; border-radius: 12px; }
QLabel { background: transparent; }
QLabel#h { font-weight: 700; font-size: 11pt; color: #111827; }
QLabel#sub { color: #3B4656; font-size: 9pt; }
QLabel#placeholder { color: #C9D1DD; }
QMessageBox, QDialog { background: #E8ECF2; }
QToolTip { background: #E8ECF2; color: #111827; border: 1px solid #9AA7B8; }
QMenu { background: #E8ECF2; color: #111827; border: 1px solid #9AA7B8; }
QPushButton#themeBtn { min-height: 24px; max-height: 24px; padding: 0 12px; font-size: 9pt; border-radius: 0; border: 2px solid #8FA6D6; background: #E8ECF2; color: #3B4656; }
QPushButton#themeBtn:checked { background: #1E3A8A; color: #FFFFFF; border-color: #1E3A8A; }
QPushButton#themeBtn[pos="l"] { border-top-left-radius: 12px; border-bottom-left-radius: 12px; }
QPushButton#themeBtn[pos="r"] { border-top-right-radius: 12px; border-bottom-right-radius: 12px; }

/* 입력칸: 흰 바탕 + 진한 테두리로 배경과 확실히 구분 */
QLineEdit:disabled { background: #E2E8F0; color: #94A3B8; border: 2px solid #CBD5E1; }
QCheckBox { font-size: 15px; font-weight: 700; color: #111827; spacing: 6px; }
QCheckBox::indicator { width: 20px; height: 20px; border: 2px solid #475569; border-radius: 4px; background: @FIELD@; }
QCheckBox::indicator:checked { background: #1E3A8A; border-color: #1E3A8A; }
QLineEdit, QComboBox { border: 2px solid #475569; border-radius: 6px; padding: 2px 8px;
                       min-height: 26px; background: @FIELD@; color: #111827; }
QLineEdit:focus, QComboBox:focus { border: 2px solid #F59E0B; }
QComboBox QAbstractItemView { background: #FFFFFF; color: #111827;
                              selection-background-color: #DCE5F7; selection-color: #1E3A8A; }

/* 버튼 기본(회색 계열 보조 버튼) */
QPushButton { border: 2px solid #475569; border-radius: 12px; padding: 4px 14px;
              background: #FFFFFF; color: #111827; min-height: 28px; font-weight: 700; }
QPushButton:hover { background: #F1F5F9; }
QPushButton:disabled { background: #D5DBE5; color: #475569; border: 2px solid #94A3B8; }

/* 파일 */
QPushButton#file { background: #0F766E; color: #FFFFFF; border: 2px solid #0F766E; }
QPushButton#file:hover { background: #0B5F59; border-color: #0B5F59; }
/* 재생 조절: 이동(연한 남색) / 재생(남색 채움) / 정지(남색 테두리) */
QPushButton#move { background: #DCE5F7; color: #1E3A8A; border: 2px solid #8FA6D6; padding: 4px 8px; }
QPushButton#move:hover { background: #C8D6F2; }
QPushButton#play { background: #1E3A8A; color: #FFFFFF; border: 2px solid #1E3A8A; padding: 4px 14px; }
QPushButton#play:hover { background: #172E6E; border-color: #172E6E; }
QPushButton#stop { background: #FFFFFF; color: #1E3A8A; border: 2px solid #1E3A8A; padding: 4px 14px; }
QPushButton#stop:hover { background: #DCE5F7; }
/* 구간 지정: 득점 시작(초록) / 득점 종료(주황) */
QPushButton#start { background: #15803D; color: #FFFFFF; border: 2px solid #15803D;
                    font-size: 12pt; border-radius: 16px; }
QPushButton#start:hover { background: #116A32; border-color: #116A32; }
QPushButton#end { background: #C2410C; color: #FFFFFF; border: 2px solid #C2410C;
                  font-size: 12pt; border-radius: 16px; }
QPushButton#end:hover { background: #A8370A; border-color: #A8370A; }
QPushButton#start:disabled, QPushButton#end:disabled { background: #D5DBE5; color: #475569;
                                                       border: 2px solid #94A3B8; }
/* 취소·삭제(빨강 테두리) */
QPushButton#danger { background: #FFFFFF; color: #B91C1C; border: 2px solid #B91C1C; border-radius: 16px; }
QPushButton#danger:hover { background: #FEE2E2; }
QPushButton#danger:disabled { background: #D5DBE5; color: #475569; border: 2px solid #94A3B8; }
/* 구간 직접 추가 */
QPushButton#add { background: #FFFFFF; color: #1E3A8A; border: 2px solid #1E3A8A; }
QPushButton#add:hover { background: #DCE5F7; }
/* 편집 시작(보라 채움) */
QPushButton#go { background: #6D28D9; color: #FFFFFF; border: 2px solid #6D28D9; font-size: 11pt; }
QPushButton#go:hover { background: #5B21B6; border-color: #5B21B6; }
QPushButton#go:disabled { background: #D5DBE5; color: #475569; border: 2px solid #94A3B8; }
/* 목록 행 안의 작은 버튼 */
QPushButton#iconplay, QPushButton#icondel { padding: 0; min-width: 34px; max-width: 34px;
                                            min-height: 34px; max-height: 34px; border-radius: 6px; }
QPushButton#iconplay { background: #DCE5F7; color: #1E3A8A; border: 2px solid #1E3A8A; }
QPushButton#iconplay:hover { background: #C8D6F2; }
QPushButton#icondel { background: #FFFFFF; color: #B91C1C; border: 2px solid #B91C1C; }
QPushButton#icondel:hover { background: #FEE2E2; }
QPushButton#nudge { background: #DCE5F7; color: #1E3A8A; border: 2px solid #8FA6D6;
                    padding: 0; min-width: 36px; max-width: 36px; min-height: 28px;
                    max-height: 28px; border-radius: 6px; }
QPushButton#nudge:hover { background: #C8D6F2; }
QPushButton#num { border: 0; background: transparent; color: #111827; font-weight: 700; padding: 0; }
QPushButton#num:hover { background: #D5DBE5; }

QFrame#row { border: 2px solid transparent; border-radius: 12px; }
QFrame#rowSel { background: #FFF4DC; border: 2px solid #F59E0B; border-radius: 12px; }
QFrame#cropbar { background: @FIELD@; border: 2px solid #475569; border-radius: 12px; }
QFrame#cropbarOn { background: @FIELD@; border: 2px solid #F59E0B; border-radius: 12px; }
QPushButton#ratio { background: #DCE5F7; color: #1E3A8A; border: 2px solid #8FA6D6; padding: 0 12px;
                    min-height: 26px; max-height: 26px; border-radius: 6px; }
QPushButton#ratio:hover { background: #C8D6F2; }
QPushButton#ratio:checked { background: #1E3A8A; color: #FFFFFF; border: 2px solid #1E3A8A; }
QPushButton#ratio:disabled { background: #D5DBE5; color: #475569; border: 2px solid #94A3B8; }
QPushButton#reset { background: #FFFFFF; color: #B91C1C; border: 2px solid #B91C1C; padding: 0 12px;
                    min-height: 26px; max-height: 26px; border-radius: 6px; }
QPushButton#reset:hover { background: #FEE2E2; }
QPushButton#reset:disabled { background: #D5DBE5; color: #475569; border: 2px solid #94A3B8; }
QFrame#rowActive { background: #FFE9DA; border: 2px solid #C2410C; border-radius: 12px; }
QProgressBar { border: 1px solid #64748B; background: @FIELD@; border-radius: 6px;
               min-height: 12px; max-height: 12px; }
QProgressBar::chunk { background: #6D28D9; border-radius: 5px; }
QScrollArea { border: 0; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QTabWidget::pane { border: 0; background: transparent; }
QTabBar::tab { background: transparent; color: #3B4656; border: 2px solid transparent; border-bottom: 4px solid transparent;
               border-top-left-radius: 14px; border-top-right-radius: 14px;
               padding: 8px 22px; margin-right: 6px; font-weight: 700; }
QTabBar::tab:hover { background: #E8ECF2; }
QTabBar::tab:selected { background: #E8ECF2; color: #111827; border-bottom: 4px solid #F59E0B; }
QPushButton#dstart { background: #DC2626; color: #FFFFFF; border: 2px solid #DC2626;
                     border-radius: 16px; font-size: 12pt; }
QPushButton#dstart:hover { background: #B91C1D; border-color: #B91C1D; }
QPushButton#dend { background: #7F1D1D; color: #FFFFFF; border: 2px solid #7F1D1D;
                   border-radius: 16px; font-size: 12pt; }
QPushButton#dend:hover { background: #661515; border-color: #661515; }
QPushButton#dstart:disabled, QPushButton#dend:disabled { background: #D5DBE5; color: #475569;
                     border: 2px solid #94A3B8; }
QPushButton#prev { background: #0F766E; color: #FFFFFF; border: 2px solid #0F766E; }
QPushButton#prev:hover { background: #0B5F59; border-color: #0B5F59; }
QPushButton#icondn { background: #DCE5F7; color: #1E3A8A; border: 2px solid #8FA6D6; padding: 0; border-radius: 6px; }
QPushButton#icondn:hover { background: #C8D6F2; }
QPushButton#icondn:disabled { background: #D5DBE5; color: #94A3B8; border: 2px solid #CBD5E1; }
QFrame#clipRow { background: transparent; }
QListWidget { background: transparent; border: 0; outline: 0; }
QListWidget::item { background: #F4F6FA; border: 2px solid transparent; border-radius: 12px; }
QListWidget::item:selected { background: #EAF0FC; border: 2px solid #1E3A8A; }
QLabel#infobox { background: @FIELD@; border: 2px solid #475569; border-radius: 12px; padding: 8px 12px; }
QLabel#note { background: #FFF7E6; border: 1px solid #F5C77E; border-radius: 12px; padding: 6px 10px;
              color: #7C4A03; font-size: 9pt; }
"""

# ───────── 테마(스카이 팝: 라이트 / 다크 / 자동) ─────────
# 예전 색상값 → (라이트, 다크). 화면 곳곳의 색을 이 표 하나로 바꿉니다.
THEME_MAP = {
    "#111827": ("#14263D", "#EAF3FF"),   # 글자
    "#3B4656": ("#5B6F86", "#9DB2CC"),   # 보조 글자
    "#E8ECF2": ("#FFFFFF", "#18283F"),   # 카드
    "#9AA7B8": ("#CFE6FA", "#294262"),   # 카드 테두리
    "#0B1220": ("#0E2238", "#050C16"),   # 영상 바탕
    "#E2E8F0": ("#E4EDF6", "#223149"),
    "#CBD5E1": ("#E4EDF6", "#223149"),
    "#94A3B8": ("#E4EDF6", "#223149"),   # (글자색으로 쓰이면 아래에서 따로 처리)
    "#D5DBE5": ("#E4EDF6", "#223149"),   # 비활성 바탕
    "#475569": ("#B7D6F4", "#355278"),   # 입력칸·버튼 테두리
    "#64748B": ("#B7D6F4", "#355278"),
    "#7C8AA0": ("#B7D6F4", "#355278"),
    "#1E3A8A": ("#2F80ED", "#5BA8FF"),   # 주 색(파랑)
    "#172E6E": ("#2570D6", "#7DBAFF"),
    "#DCE5F7": ("#DCEBFF", "#22406A"),
    "#C8D6F2": ("#C4DDFB", "#2C4F7F"),
    "#8FA6D6": ("#9CC4F5", "#3A6296"),
    "#0F766E": ("#2F80ED", "#5BA8FF"),   # 파일/미리보기 버튼
    "#0B5F59": ("#2570D6", "#7DBAFF"),
    "#15803D": ("#18B26B", "#2BD283"),   # 득점 시작
    "#116A32": ("#139A5B", "#4DE09A"),
    "#C2410C": ("#FF7A45", "#FF8A57"),   # 득점 종료
    "#A8370A": ("#E8652F", "#FFA074"),
    "#9A3412": ("#D9541E", "#FF8A57"),   # 안내 글자(주황)
    "#6D28D9": ("#7C5CFF", "#8E78FF"),   # 편집 시작(보라)
    "#5B21B6": ("#6A48F0", "#A592FF"),
    "#B91C1C": ("#E5484D", "#FF6B70"),   # 취소·삭제(빨강)
    "#B91C1D": ("#C93A3F", "#FF8A8E"),
    "#FEE2E2": ("#FFE4E4", "#4A2328"),
    "#DC2626": ("#E5484D", "#FF6B70"),   # 컷 편집 시작
    "#7F1D1D": ("#9B2C34", "#C2454D"),
    "#661515": ("#82242B", "#D4565D"),
    "#FCA5A5": ("#FFB4B8", "#7A3A40"),
    "#F1F5F9": ("#EAF4FF", "#22364F"),   # 마우스 올림
    "#F59E0B": ("#FFC93C", "#FFD35C"),   # 노란 강조
    "#FFF4DC": ("#FFF6D6", "#3A3320"),   # 선택 행
    "#FFE9DA": ("#FFE9DA", "#4A2E22"),   # 지정 중 행
    "#F4F6FA": ("#F3F9FF", "#102036"),
    "#EAF0FC": ("#E3F0FF", "#22406A"),
    "#FFF7E6": ("#FFF8E1", "#3A3320"),
    "#F5C77E": ("#FFD97A", "#6B5A25"),
    "#7C4A03": ("#7A5200", "#FFD98A"),
    "#F6C6AB": ("#FFD9C2", "#7A4A33"),
    "#E58A5E": ("#FF7A45", "#FF8A57"),
    "#FFFFFF": ("#FFFFFF", "#18283F"),   # 흰 바탕(글자색 흰색은 따로 보호)
}
THEME_TOK = {
    "@AI_BG1@": ("#F3EEFF", "#2E2552"),
    "@AI_BG2@": ("#FFF6D6", "#3A3020"),
    "@AI_LINE@": ("#8B5CF6", "#A78BFA"),
    "@AI_INK@": ("#6D3FE0", "#C4B0FF"),
    "@AIQ1@": ("#DCD0FF", "#3E3270"),
    "@AIQ1INK@": ("#3B2390", "#E6DCFF"),
    "@AI_NOTE_INK@": ("#4B2BB0", "#D9CCFF"),
    "@C_BLUE@": ("#2F80ED", "#5BA8FF"),
    "@T_BLUE@": ("#E1EEFF", "#1E3A62"),
    "@C_VIO@": ("#8B5CF6", "#A78BFA"),
    "@T_VIO@": ("#F1EAFF", "#2E2552"),
    "@C_TEAL@": ("#0FA5A0", "#2DD4BF"),
    "@T_TEAL@": ("#DDF6F4", "#15403F"),
    "@C_SKY@": ("#0EA5E9", "#38BDF8"),
    "@T_SKY@": ("#E0F4FD", "#123A52"),
    "@C_RED@": ("#E5484D", "#FF6B70"),
    "@T_RED@": ("#FFE8E8", "#4A2328"),
    "@C_GO@": ("#7C5CFF", "#8E78FF"),
    "@C_ORG@": ("#FF7A45", "#FF8A57"),
    "@C_AMB@": ("#F5A00B", "#FFC24D"),
    "@T_AMB@": ("#FFF4D6", "#3A3020"),
    "@SELRING@": ("#14263D", "#FFFFFE"),
    "@ST1@": ("#FFF0C2", "#5E4A1C"),
    "@ST2@": ("#FFDB7A", "#80621E"),
    "@ST3@": ("#FFC233", "#A67C14"),
    "@STINK@": ("#5A3B00", "#FFFFFE"),
    "@ZM1@": ("#FFE9A8", "#6B5420"),
    "@ZM2@": ("#FFD25E", "#8A6420"),
    "@ZM3@": ("#FFB020", "#B07A10"),
    "@ZM4@": ("#F08A00", "#D88A00"),
    "@SK1@": ("#6CC0F2", "#5FB4EC"),
    "@SK2@": ("#2A8BD6", "#2F8ED6"),
    "@SK3@": ("#0B5FA8", "#1F6FB8"),
    "@SP1@": ("#C9F2E6", "#1E5C50"),
    "@SP2@": ("#7FDDC4", "#1F7A68"),
    "@SP3@": ("#2FC2A0", "#24A088"),
    "@SP4@": ("#0F8F78", "#2FC2A0"),
    "@SPINK@": ("#0B4F42", "#FFFFFE"),
    "@DIS_ST@": ("rgba(24,178,107,110)", "rgba(43,210,131,90)"),
    "@DIS_EN@": ("rgba(255,122,69,110)", "rgba(255,138,87,90)"),
    "@DIS_GO@": ("rgba(124,92,255,110)", "rgba(142,120,255,90)"),
    "@DIS_DS@": ("rgba(229,72,77,110)", "rgba(255,107,112,90)"),
    "@DIS_DE@": ("rgba(155,44,52,110)", "rgba(194,69,77,90)"),
    "@DIS_INK@": ("rgba(255,255,255,200)", "rgba(255,255,255,170)"),
    "@DIS_STEP@": ("rgba(245,160,11,70)", "rgba(255,194,77,50)"),
    "@DIS_STEPINK@": ("rgba(90,59,0,120)", "rgba(255,255,255,110)"),
    "@FIELD@": ("#F3F9FF", "#102036"),
    "@BGFROM@": ("#E8F4FF", "#0E1A2B"),
    "@BGTO@": ("#FFF4CC", "#16233A"),
}
THEME = {"mode": "auto", "dark": False}
_FG_KEEP = ("#FFFFFF", "#14263D")   # (어두운 글자색 아님) 채움 버튼 위 글자


def system_is_dark():
    """윈도우의 '앱 색상 모드' 설정을 읽습니다."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        pass
    try:
        from PySide6.QtGui import QGuiApplication
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def T(hexcolor):
    """예전 색상값을 현재 테마의 색상으로 바꿔 돌려줍니다."""
    pair = THEME_MAP.get(hexcolor.upper())
    return (pair[1] if THEME["dark"] else pair[0]) if pair else hexcolor


def themed(css):
    """스타일시트 문장 속 색상을 현재 테마로 바꿉니다."""
    d = 1 if THEME["dark"] else 0
    for tok, pair in THEME_TOK.items():
        css = css.replace(tok, pair[d])
    # 글자색으로 쓰인 흰색(채움 버튼 위 글자)은 바꾸지 않도록 보호
    css = re.sub(r"(?<![-\w])color:\s*#FFFFFF", "color:@@W@@", css, flags=re.I)
    css = re.sub(r"(?<![-\w])color:\s*#(94A3B8|475569)\b",
                 lambda m: "color:" + ("#60758F" if d else "#8CA0B8"), css, flags=re.I)
    css = re.sub(r"#[0-9A-Fa-f]{6}\b", lambda m: T(m.group(0)), css)
    css = css.replace("color:@@W@@", "color:#FFFFFF")
    # B안: 둥근 모서리를 각지게 (최대 5px)
    css = re.sub(r"border-radius:\s*(\d+)px", lambda m: f"border-radius: {min(int(m.group(1)), 5)}px", css)
    if THEME["dark"]:   # 밝은 파랑 바탕 위 글자는 어둡게(대비 확보)
        css += ("\nQPushButton#file, QPushButton#prev, QPushButton#ratio:checked,"
                " QPushButton#themeBtn:checked { color: #0E1A2B; }")
    return css


def sty(widget, css):
    """원본 스타일을 기억해 두고 테마에 맞춰 적용합니다(테마를 바꾸면 다시 적용)."""
    widget.setProperty("rawqss", css)
    widget.setStyleSheet(themed(css))


def apply_theme(mode, app=None, win=None):
    """mode: 'light' | 'dark' | 'auto'. 앱 전체 스타일·팔레트·직접 그린 부분을 모두 갱신합니다."""
    app = app or QApplication.instance()
    THEME["mode"] = mode
    THEME["dark"] = system_is_dark() if mode == "auto" else (mode == "dark")
    pal = QPalette()
    for role, key in ((QPalette.ColorRole.Window, "#E8ECF2"), (QPalette.ColorRole.Base, "@FIELD@"),
                      (QPalette.ColorRole.AlternateBase, "#E8ECF2"), (QPalette.ColorRole.Button, "#E8ECF2"),
                      (QPalette.ColorRole.WindowText, "#111827"), (QPalette.ColorRole.Text, "#111827"),
                      (QPalette.ColorRole.ButtonText, "#111827"), (QPalette.ColorRole.ToolTipBase, "#E8ECF2"),
                      (QPalette.ColorRole.ToolTipText, "#111827")):
        pal.setColor(role, QColor(THEME_TOK[key][1 if THEME["dark"] else 0] if key in THEME_TOK else T(key)))
    app.setPalette(pal)
    app.setStyleSheet(themed(STYLE))
    if win is not None:
        for w in win.findChildren(QWidget):
            raw = w.property("rawqss")
            if raw:
                w.setStyleSheet(themed(raw))
            w.update()
        win.update()


# ───────── 영역별 색 · 조절 버튼 색 단계 (기능 영역·버튼 가시성) ─────────
EXTRA_STYLE = """
QFrame#card[area="blue"] { border-top: 6px solid @C_BLUE@; }
QFrame#card[area="vio"] { border-top: 6px solid @C_VIO@; }
QFrame#card[area="teal"] { border-top: 6px solid @C_TEAL@; }
QFrame#card[area="sky"] { border-top: 6px solid @C_SKY@; }
QFrame#card[area="red"] { border-top: 6px solid @C_RED@; }
QFrame#card[area="go"] { border-top: 6px solid @C_GO@; }
QLabel#nb { color: #FFFFFF; font-weight: 800; border-radius: 8px; min-width: 26px; max-width: 26px;
            min-height: 26px; max-height: 26px; qproperty-alignment: AlignCenter; }
QLabel#nb[area="blue"] { background: @C_BLUE@; }
QLabel#nb[area="vio"] { background: @C_VIO@; }
QLabel#nb[area="teal"] { background: @C_TEAL@; }
QLabel#nb[area="sky"] { background: @C_SKY@; }
QLabel#nb[area="red"] { background: @C_RED@; }
QLabel#nb[area="go"] { background: @C_GO@; }
QFrame#card[area="blue"] QPushButton#move { background: @T_BLUE@; color: @C_BLUE@; border: 2px solid @C_BLUE@; }
QFrame#card[area="vio"] QPushButton#move { background: @T_VIO@; color: @C_VIO@; border: 2px solid @C_VIO@; }
QFrame#card[area="teal"] QPushButton#move, QFrame#card[area="teal"] QPushButton#add { background: @T_TEAL@; color: @C_TEAL@; border: 2px solid @C_TEAL@; }
QFrame#card[area="red"] QPushButton#move, QFrame#card[area="red"] QPushButton#add { background: @T_RED@; color: @C_RED@; border: 2px solid @C_RED@; }
QFrame#card[area="teal"] QFrame#row, QFrame#card[area="teal"] QFrame#rowSel, QFrame#card[area="teal"] QFrame#rowActive { border-left: 6px solid @C_TEAL@; }
QFrame#card[area="red"] QFrame#row, QFrame#card[area="red"] QFrame#rowSel, QFrame#card[area="red"] QFrame#rowActive { border-left: 6px solid @C_RED@; }
QPushButton#iconplay { background: @T_SKY@; color: @C_SKY@; border: 2px solid @C_SKY@; }
QPushButton#icondel { background: @T_RED@; }
/* 재생 시간: 가운데(1초) 밝게 → 5초 진하게, 재생/정지는 주황 */
QPushButton#sk1, QPushButton#sk2, QPushButton#sk3 { color: #FFFFFF; border: 2px solid transparent; font-weight: 800;
            padding: 4px 10px; border-radius: 12px; min-height: 28px; }
QPushButton#sk1 { background: @SK1@; }
QPushButton#sk2 { background: @SK2@; }
QPushButton#sk3 { background: @SK3@; }
QPushButton#sk1:hover, QPushButton#sk2:hover, QPushButton#sk3:hover { border: 2px solid @SELRING@; }
QPushButton#play { background: @C_ORG@; border: 2px solid @C_ORG@; color: #FFFFFF; }
QPushButton#play:hover { background: @C_ORG@; border: 2px solid @SELRING@; }
QPushButton#stop { background: transparent; border: 2px solid @C_ORG@; color: @C_ORG@; }
/* 구간 범위(노랑 영역) */
QFrame#cropbar, QFrame#cropbarOn { background: @T_AMB@; border: 2px solid @C_AMB@; }
QPushButton#rt, QPushButton#zm { color: @STINK@; border: 2px solid transparent; padding: 0 12px; font-weight: 800;
            min-height: 28px; max-height: 28px; border-radius: 10px; }
QPushButton#rt[step="1"] { background: @ST1@; }
QPushButton#rt[step="2"] { background: @ST2@; }
QPushButton#rt[step="3"] { background: @ST3@; }
QPushButton#zm[step="1"] { background: @ZM1@; }
QPushButton#zm[step="2"] { background: @ZM2@; }
QPushButton#zm[step="3"] { background: @ZM3@; color: #FFFFFF; }
QPushButton#zm[step="4"] { background: @ZM4@; color: #FFFFFF; }
QPushButton#rt:checked, QPushButton#zm:checked, QPushButton#spd:checked { border: 3px solid @SELRING@; }
QPushButton#rt:disabled, QPushButton#zm:disabled { background: @DIS_STEP@; color: @DIS_STEPINK@; border: 2px solid transparent; }
/* 배속 버튼 */
QPushButton#spd { color: @SPINK@; border: 2px solid transparent; padding: 0 10px; font-weight: 800; font-size: 9pt;
            min-height: 28px; max-height: 28px; border-radius: 10px; }
QPushButton#spd[step="1"] { background: @SP1@; }
QPushButton#spd[step="2"] { background: @SP2@; }
QPushButton#spd[step="3"] { background: @SP3@; color: #FFFFFF; }
QPushButton#spd[step="4"] { background: @SP4@; color: #FFFFFF; }
/* 비활성: 회색 대신 원래 색을 흐리게 */
QPushButton#start:disabled { background: @DIS_ST@; color: @DIS_INK@; border: 2px solid transparent; }
QPushButton#end:disabled { background: @DIS_EN@; color: @DIS_INK@; border: 2px solid transparent; }
QPushButton#go:disabled { background: @DIS_GO@; color: @DIS_INK@; border: 2px solid transparent; }
QPushButton#dstart:disabled { background: @DIS_DS@; color: @DIS_INK@; border: 2px solid transparent; }
QPushButton#dend:disabled { background: @DIS_DE@; color: @DIS_INK@; border: 2px solid transparent; }
"""
AI_STYLE = """
QFrame#aibox { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @AI_BG1@, stop:1 @AI_BG2@);
               border: 2px solid @AI_LINE@; border-radius: 12px; }
QLabel#aititle { color: @AI_INK@; font-weight: 800; font-size: 11pt; }
QPushButton#aiq { border: 2px solid transparent; padding: 0 12px; font-weight: 800; min-height: 28px; max-height: 28px;
                  border-radius: 10px; background: @AIQ1@; color: @AIQ1INK@; }
QPushButton#aiq:checked { background: @AI_LINE@; color: #FFFFFF; border: 3px solid @SELRING@; }
QPushButton#aiq:disabled { color: rgba(128,128,128,150); }
QLabel#aibadge { color: #FFFFFF; font-weight: 800; font-size: 9pt; border-radius: 9px; padding: 1px 8px;
                 background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8B5CF6, stop:1 #FFB020); }
QLabel#ainote { background: @AI_BG1@; border: 1px dashed @AI_LINE@; border-radius: 10px; padding: 4px 10px;
                color: @AI_NOTE_INK@; font-weight: 700; }
"""
B_STYLE = """
QFrame#pnl { background: #E8ECF2; border: 1px solid #9AA7B8; border-radius: 4px; }
QFrame#phd { border: none; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QFrame#pnl[area="blue"] QFrame#phd { background: @C_BLUE@; }
QFrame#pnl[area="teal"] QFrame#phd { background: @C_TEAL@; }
QFrame#pnl[area="go"] QFrame#phd { background: @C_GO@; }
QFrame#phd QLabel { color: #FFFFFF; background: transparent; }
QLabel#ph { color: #FFFFFF; font-weight: 800; font-size: 13pt; }
QLabel#phs { color: #FFFFFF; font-size: 9pt; }
QLabel#nbw { background: #FFFFFF; font-weight: 800; border-radius: 4px; min-width: 24px; max-width: 24px;
             min-height: 24px; max-height: 24px; qproperty-alignment: AlignCenter; }
QFrame#pnl[area="blue"] QLabel#nbw { color: @C_BLUE@; }
QFrame#pnl[area="teal"] QLabel#nbw { color: @C_TEAL@; }
QFrame#pnl[area="go"] QLabel#nbw { color: @C_GO@; }
QPushButton#hbtn { background: #FFFFFF; border: 1px solid #FFFFFF; border-radius: 4px; padding: 2px 10px;
                   min-height: 26px; max-height: 26px; font-weight: 700; }
QFrame#pnl[area="blue"] QPushButton#hbtn { color: @C_BLUE@; }
QPushButton#hbtn:hover { border: 2px solid @SELRING@; }
QFrame#pnl[area="teal"] QFrame#row, QFrame#pnl[area="teal"] QFrame#rowSel, QFrame#pnl[area="teal"] QFrame#rowActive { border-left: 6px solid @C_TEAL@; }
QFrame#pnl[area="teal"] QPushButton#add { background: @T_TEAL@; color: @C_TEAL@; border: 2px solid @C_TEAL@; }
QFrame#tools { background: transparent; border: none; border-top: 1px solid #9AA7B8; }
QFrame#aibox { border-radius: 4px; }
QLabel#ttl { color: @C_GO@; font-weight: 800; }
"""
STYLE = STYLE + EXTRA_STYLE + AI_STYLE + B_STYLE

AREA_BY_TITLE = (("영상", "blue"), ("메인화면 자막", "vio"), ("합치기 방식", "vio"), ("득점 구간 목록", "teal"),
                 ("합칠 영상 목록", "teal"), ("지울 구간 목록", "red"), ("선택한 영상 미리보기", "sky"),
                 ("편집 및 저장", "go"), ("합치기 및 저장", "go"))
SEEK_STEP = {"-1초": "sk1", "+1초": "sk1", "-2초": "sk2", "+2초": "sk2", "-5초": "sk3", "+5초": "sk3"}
SPEEDS = ["0.5x", "1x", "1.5x", "2x"]


def _find_in_layout(lay, w):
    """레이아웃(중첩 포함)에서 위젯 w가 들어 있는 (레이아웃, 위치)를 찾습니다."""
    if lay is None:
        return None
    for i in range(lay.count()):
        it = lay.itemAt(i)
        if it.widget() is w:
            return lay, i
        if it.layout() is not None:
            r = _find_in_layout(it.layout(), w)
            if r:
                return r
    return None


def _layout_of(w):
    """위젯이 들어 있는 레이아웃(부모 위젯의 레이아웃)을 찾습니다."""
    par = w.parentWidget()
    while par is not None:
        if par.layout() is not None and _find_in_layout(par.layout(), w):
            return par.layout()
        par = par.parentWidget()
    return None


def _repolish(w):
    w.style().unpolish(w)
    w.style().polish(w)


def _tab_dot(n, color):
    pm = QPixmap(22, 22)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(1, 1, 20, 20)
    p.setPen(QColor("#FFFFFF"))
    f = QFont(p.font())
    f.setBold(True)
    f.setPointSize(9)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, str(n))
    p.end()
    return QIcon(pm)


def _check_text(b, text):
    b.toggled.connect(lambda c, b=b, t=text: b.setText(("✓ " if c else "") + t))


def decorate_ui(win):
    """화면을 만든 뒤 한 번: 영역 색·번호 배지·재생/배속/범위 버튼 색 단계를 입힙니다."""
    # 탭: 번호 색 동그라미
    for i, (title, color) in enumerate((("득점 하이라이트", "#FF7A45"), ("구간 삭제 (컷 편집)", "#E5484D"),
                                        ("영상 합치기", "#0FA5A0"))):
        if i < win.tabs.count():
            win.tabs.setTabText(i, title)
            win.tabs.setTabIcon(i, _tab_dot(i + 1, color))
    win.tabs.setIconSize(QSize(20, 20))

    # 카드: 제목으로 영역을 정하고 번호 배지를 붙임
    for card in win.findChildren(QFrame, "card"):
        heads = [lb for lb in card.findChildren(QLabel, "h") if _find_in_layout(card.layout(), lb)]
        if not heads:
            if card.findChild(QCheckBox) is not None and card.findChild(QPushButton) is None:
                card.setProperty("area", "vio")      # ② 화질 옵션 카드
            continue
        h = heads[0]
        text = h.text().strip()
        num, title = "", text
        if len(text) > 2 and text[0].isdigit() and text[1] == ".":
            num, title = text[0], text[2:].strip()
        area = next((a for t, a in AREA_BY_TITLE if title.startswith(t)), None)
        if area is None:
            continue
        card.setProperty("area", area)
        h.setText(title)
        nb = QLabel(num or ("✦" if area == "vio" else "▶"))
        nb.setObjectName("nb")
        nb.setProperty("area", area)
        found = _find_in_layout(card.layout(), h)
        if found:
            found[0].insertWidget(found[1], nb)

    # 재생 시간 버튼: 1초 밝게 → 5초 진하게
    for b in win.findChildren(QPushButton, "move"):
        if b.text() in SEEK_STEP:
            b.setObjectName(SEEK_STEP[b.text()])

    # 범위: 비율(16:9 → 4:3 → 1:1)·확대(1x → 3x) 버튼
    if hasattr(win, "ratio_btns") and hasattr(win, "crop_bar"):
        order = ("16:9", "4:3", "1:1")
        label_pos = None
        for lb in win.crop_bar.findChildren(QLabel):
            if lb.text() == "비율":
                label_pos = lb
        for k, name in enumerate(order):
            b = win.ratio_btns.get(name)
            if b is None:
                continue
            b.setObjectName("rt")
            b.setProperty("step", str(k + 1))
            _check_text(b, name)
            found = _find_in_layout(win.crop_bar.layout(), b)
            if found:
                found[0].removeWidget(b)
        if label_pos is not None:
            lp = _find_in_layout(win.crop_bar.layout(), label_pos)
            if lp:
                for k, name in enumerate(order):
                    if name in win.ratio_btns:
                        lp[0].insertWidget(lp[1] + 1 + k, win.ratio_btns[name])
        for k, b in enumerate(win.zoom_btns):
            b.setObjectName("zm")
            b.setProperty("step", str(k + 1))
            b.setCheckable(True)
            _check_text(b, b.text())

    # 배속: 목록 상자 → 버튼 4개 (목록 상자는 숨겨서 그대로 사용)
    for combo in win.findChildren(QComboBox):
        if [combo.itemText(i) for i in range(combo.count())] != SPEEDS:
            continue
        lay = _layout_of(combo)
        found = _find_in_layout(lay, combo) if lay is not None else None
        if not found:
            continue
        lay, idx = found
        combo.hide()
        group = QButtonGroup(combo)
        group.setExclusive(True)
        btns = {}
        for k, v in enumerate(SPEEDS):
            b = QPushButton(v)
            b.setObjectName("spd")
            b.setProperty("step", str(k + 1))
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            _check_text(b, v)
            b.clicked.connect(lambda _=False, c=combo, t=v: c.setCurrentText(t))
            group.addButton(b)
            btns[v] = b
            lay.insertWidget(idx + k, b)
        btns.get(combo.currentText(), btns["1x"]).setChecked(True)
        combo.currentTextChanged.connect(lambda t, btns=btns: btns[t].setChecked(True) if t in btns else None)

    for w in win.findChildren(QWidget):
        _repolish(w)


PILL_ACTIVE = (f"background:{ACCENT};color:#FFFFFF;border-radius:12px;"
               "padding:4px 12px;font-weight:700;")
PILL_IDLE = f"background:#D5DBE5;color:{SUBTLE};border-radius:12px;padding:4px 12px;"
GHOST = (f"border:2px dashed #7C8AA0;border-radius:8px;padding:10px;color:{SUBTLE};"
         "font-size:9pt;")


class Bridge(QObject):
    """편집 작업(별도 스레드)에서 화면으로 소식을 전하는 통로"""
    progress = Signal(float, float, str)
    done = Signal(str)
    failed = Signal(str)
    cancelled = Signal()


class SeekBar(QWidget):
    """재생 위치 막대: 지정한 득점 구간(주황)과 지정 중인 구간(줄무늬)을 함께 보여줍니다."""
    seekRequested = Signal(float)

    def __init__(self, parent=None, color=None, fill="#F6C6AB", hatch="#E58A5E"):
        super().__init__(parent)
        self.setMinimumHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color = color or ACCENT
        self._fill = fill
        self._hatch = hatch
        self._dur = 0.0
        self._pos = 0.0
        self._segs = []
        self._active = None

    def set_duration(self, dur):
        self._dur = max(0.0, float(dur))
        self.update()

    def set_position(self, pos):
        self._pos = max(0.0, float(pos))
        self.update()

    def set_segments(self, segs, active):
        self._segs = list(segs)
        self._active = active
        self.update()

    def _sec_at(self, x):
        if self._dur <= 0:
            return 0.0
        return max(0.0, min(1.0, x / max(1, self.width()))) * self._dur

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.seekRequested.emit(self._sec_at(ev.position().x()))

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.MouseButton.LeftButton:
            self.seekRequested.emit(self._sec_at(ev.position().x()))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        ty = (h - 14) / 2
        p.setPen(QColor(T("#64748B")))
        p.setBrush(QColor(THEME_TOK["@FIELD@"][1 if THEME["dark"] else 0]))
        p.drawRoundedRect(QRectF(0.5, ty, w - 1, 14), 7, 7)
        p.setPen(Qt.PenStyle.NoPen)
        if self._dur > 0:
            def px(sec):
                return sec / self._dur * w
            p.setBrush(QColor(T(self._color)))
            for s, e in self._segs:
                x1 = px(s)
                x2 = max(px(e), x1 + 4)
                p.drawRoundedRect(QRectF(x1, ty, x2 - x1, 14), 3, 3)
            if self._active:
                s, cur = self._active
                x1 = px(s)
                x2 = max(px(max(cur, s)), x1 + 4)
                rect = QRectF(x1, ty, x2 - x1, 14)
                p.setBrush(QColor(T(self._fill)))
                p.drawRoundedRect(rect, 3, 3)
                p.setBrush(QBrush(QColor(T(self._hatch)), Qt.BrushStyle.BDiagPattern))
                p.drawRoundedRect(rect, 3, 3)
            p.setBrush(QColor(T(INK)))
            p.drawRoundedRect(QRectF(px(self._pos) - 2, ty - 5, 4, 24), 2, 2)
        p.end()


class ClickFrame(QFrame):
    """눌렀다는 신호를 보내는 틀 (구간 목록의 한 줄)"""
    clicked = Signal()

    def mousePressEvent(self, ev):
        self.clicked.emit()
        super().mousePressEvent(ev)


class VideoView(QGraphicsView):
    """영상을 보여주고, 그 위에 저장 범위(주황 사각형)를 항상 겹쳐 그리는 화면.
    재생 전·재생 중·정지 중 모두 사각형이 보이고, 끌어서 조절할 수 있습니다."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.item = QGraphicsVideoItem()
        self._scene.addItem(self.item)
        self._W, self._H = 16, 9
        self._crop = None
        self._ratio = DEFAULT_RATIO
        self._mode = None
        self._st = None
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QColor("#0B1220"))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.set_source(16, 9)

    def set_source(self, W, H):
        self._W, self._H = max(1, int(W)), max(1, int(H))
        self.item.setSize(QSizeF(self._W, self._H))
        self._scene.setSceneRect(QRectF(0, 0, self._W, self._H))
        self._fit()
        self.viewport().update()

    def _fit(self):
        self.fitInView(QRectF(0, 0, self._W, self._H), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit()

    def set_crop(self, crop, ratio):
        self._crop = crop
        self._ratio = ratio or DEFAULT_RATIO
        if crop is None:
            self.viewport().unsetCursor()
        self.viewport().update()

    # ---- 화면 좌표 계산 (viewport 픽셀 기준) ----
    def _area(self):
        r = self.mapFromScene(QRectF(0, 0, self._W, self._H)).boundingRect()
        return QRectF(float(r.x()), float(r.y()), float(r.width()), float(r.height()))

    def _rect(self):
        a, c = self._area(), self._crop
        return QRectF(a.x() + c["x"] * a.width(), a.y() + c["y"] * a.height(),
                      c["w"] * a.width(), c["h"] * a.height())

    def _norm(self, pos):
        a = self._area()
        return (pos.x() - a.x()) / max(1.0, a.width()), (pos.y() - a.y()) / max(1.0, a.height())

    def _hit_handle(self, pos):
        r = self._rect()
        for name, pt in (("tl", r.topLeft()), ("tr", r.topRight()),
                         ("bl", r.bottomLeft()), ("br", r.bottomRight())):
            if abs(pos.x() - pt.x()) <= 12 and abs(pos.y() - pt.y()) <= 12:
                return name
        return None

    def mousePressEvent(self, ev):
        if self._crop is None or ev.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(ev)
        pos = ev.position()
        h = self._hit_handle(pos)
        if h:
            self._mode, self._st = "size", h
        elif self._rect().contains(pos):
            nx, ny = self._norm(pos)
            self._mode, self._st = "move", (nx - self._crop["x"], ny - self._crop["y"])
        else:
            super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._crop is None:
            return super().mouseMoveEvent(ev)
        pos = ev.position()
        if self._mode is None:
            h = self._hit_handle(pos)
            if h in ("tl", "br"):
                self.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif h in ("tr", "bl"):
                self.viewport().setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif self._rect().contains(pos):
                self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.viewport().unsetCursor()
            return
        nx, ny = self._norm(pos)
        c = self._crop
        if self._mode == "move":
            c["x"] = min(1.0 - c["w"], max(0.0, nx - self._st[0]))
            c["y"] = min(1.0 - c["h"], max(0.0, ny - self._st[1]))
        else:
            c.update(crop_resize(self._W, self._H, self._ratio, c, self._st, nx, ny))
        self.viewport().update()
        self.changed.emit()

    def mouseReleaseEvent(self, ev):
        self._mode = None
        self._st = None
        super().mouseReleaseEvent(ev)

    def drawForeground(self, p, rect):
        if self._crop is None:
            return
        p.save()
        p.resetTransform()                       # 이제부터 화면(픽셀) 좌표로 그립니다
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        a = self._area()
        r = self._rect()
        path = QPainterPath()
        path.addRect(a)
        path.addRect(r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawPath(path)                         # 사각형 밖을 살짝 어둡게
        pen = p.pen()
        pen.setColor(QColor(T("#F59E0B")))
        pen.setWidth(3)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T("#F59E0B")))
        for pt in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
            p.drawRect(QRectF(pt.x() - 6, pt.y() - 6, 12, 12))
        tag = f"{self._ratio} · {crop_zoom(self._W, self._H, self._ratio, self._crop):.1f}배"
        tr = QRectF(r.x() + 8, r.y() + 8, 14 + 9 * len(tag), 22)
        p.drawRoundedRect(tr, 11, 11)
        p.setPen(QColor("#111827"))
        p.drawText(tr, Qt.AlignmentFlag.AlignCenter, tag)
        p.restore()


# ----------------------------------------------------------------------
# 탭 ②(구간 삭제)·탭 ③(영상 합치기) 화면
# ----------------------------------------------------------------------
def mk_btn(text, slot=None, name=None):
    b = QPushButton(text)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # 스페이스바가 버튼을 누르지 않도록
    if name:
        b.setObjectName(name)
    if slot:
        b.clicked.connect(lambda _checked=False, f=slot: f())
    return b


def mk_label(text, name=None, wrap=False):
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def mk_card(vertical=True):
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f) if vertical else QHBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(10)
    return f, lay


def mk_controls(seek_rel, play, stop, on_speed=None):
    """-5 -2 -1 ▶ ■ +1 +2 +5 (+ 배속) 줄"""
    ctl = QHBoxLayout()
    ctl.setSpacing(6)
    for t, d in (("-5초", -5), ("-2초", -2), ("-1초", -1)):
        ctl.addWidget(mk_btn(t, lambda d=d: seek_rel(d), "move"))
    ctl.addWidget(mk_btn("▶ 재생", play, "play"))
    ctl.addWidget(mk_btn("■ 정지", stop, "stop"))
    for t, d in (("+1초", 1), ("+2초", 2), ("+5초", 5)):
        ctl.addWidget(mk_btn(t, lambda d=d: seek_rel(d), "move"))
    speed = None
    if on_speed:
        ctl.addStretch(1)
        ctl.addWidget(mk_label("배속", "sub"))
        speed = QComboBox()
        speed.addItems(["0.5x", "1x", "1.5x", "2x"])
        speed.setCurrentText("1x")
        speed.setFixedWidth(70)
        speed.currentTextChanged.connect(on_speed)
        ctl.addWidget(speed)
    return ctl, speed


def fmt_len(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}시간 {m}분 {s}초" if h else (f"{m}분 {s}초" if m else f"{s}초")


def make_thumb(ffmpeg, path, duration):
    """영상 한 장면을 작은 그림(JPEG 바이트)으로 뽑습니다. 실패하면 빈 바이트."""
    try:
        t = min(1.0, max(0.0, duration / 4))
        r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", path,
                            "-frames:v", "1", "-vf", "scale=168:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                           capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=30)
        return r.stdout if r.returncode == 0 else b""
    except Exception:
        return b""


def ratio_label(w, h):
    r = w / max(1, h)
    for name, val in (("16:9", 16 / 9), ("4:3", 4 / 3), ("1:1", 1.0), ("9:16", 9 / 16)):
        if abs(r - val) < 0.02:
            return name
    return f"{w}x{h}"


class BaseTab(QWidget):
    """탭 ②·③이 함께 쓰는 부분: 편집 작업(별도 스레드) 시작·진행·종료 처리"""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.worker = None
        self.cancel_event = threading.Event()
        self.bridge = Bridge()
        self.bridge.progress.connect(self.on_progress)
        self.bridge.done.connect(self.on_done)
        self.bridge.failed.connect(self.on_failed)
        self.bridge.cancelled.connect(self.on_cancelled)

    def busy(self):
        return bool(self.worker and self.worker.is_alive())

    def build_bottom(self, title, go_text, go_slot):
        card, lay = mk_card(vertical=False)
        lay.setSpacing(16)
        lay.addWidget(mk_label(title, "h"))
        col = QVBoxLayout()
        col.setSpacing(4)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        col.addWidget(self.bar)
        self.status = mk_label("대기 중", "sub")
        col.addWidget(self.status)
        lay.addLayout(col, 1)
        self.cancel_btn = mk_btn("취소", self.cancel_edit, "danger")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setMinimumHeight(46)
        lay.addWidget(self.cancel_btn)
        self.go_btn = mk_btn(go_text, go_slot, "go")
        self.go_btn.setMinimumHeight(46)
        self.go_btn.setMinimumWidth(220)
        lay.addWidget(self.go_btn)
        return card

    def run_job(self, fn, out):
        """fn(progress, cancel) 를 별도 스레드에서 실행합니다."""
        self.cancel_event.clear()
        self.bar.setValue(0)
        self.set_running(True)

        def work():
            try:
                fn(lambda d, t, m: self.bridge.progress.emit(d, t, m), self.cancel_event)
                self.bridge.done.emit(out)
            except Cancelled:
                self.bridge.cancelled.emit()
            except EditError as e:
                self.bridge.failed.emit(str(e))
            except Exception:
                self.bridge.failed.emit("예상하지 못한 오류가 발생했습니다.\n\n" + traceback.format_exc()[-800:])

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def set_running(self, running):
        self.go_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)

    def cancel_edit(self):
        self.cancel_event.set()

    def on_progress(self, done, total, text):
        self.bar.setValue(int(100.0 * done / max(total, 1)))
        self.status.setText(text)

    def on_done(self, path):
        self.set_running(False)
        self.bar.setValue(100)
        self.status.setText("완료: " + path)
        ans = QMessageBox.question(self.win, APP_TITLE, f"저장했습니다.\n{path}\n\n저장 폴더를 열까요?")
        if ans == QMessageBox.StandardButton.Yes and IS_WIN:
            os.startfile(os.path.dirname(path))

    def on_failed(self, text):
        self.set_running(False)
        self.status.setText("오류가 발생했습니다.")
        QMessageBox.critical(self.win, APP_TITLE, text)

    def on_cancelled(self):
        self.set_running(False)
        self.status.setText("취소했습니다.")


class CutTab(BaseTab):
    """② 구간 삭제 (컷 편집): 지울 구간을 지정하면 나머지를 이어 붙여 저장합니다."""

    def __init__(self, win):
        super().__init__(win)
        self.src = None
        self.info = None
        self.dur = 0.0
        self.can_play = False
        self.rows = []              # {"start", "end", "active"}
        self.play_until = None
        self.skip = False
        self.row_widgets = []
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player.setAudioOutput(self.audio)
        self.build()
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self.on_position)
        self.player.durationChanged.connect(self.on_duration)
        self.player.errorOccurred.connect(self.on_error)
        self.rebuild()

    # ---- 화면 ----
    def build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 12, 0, 0)
        outer.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(12)
        c1, l1 = mk_card(vertical=False)
        l1.addWidget(mk_label("1. 영상", "h"))
        l1.addWidget(mk_btn("영상 파일 선택", self.choose_video, "file"))
        self.info_label = mk_label("선택된 영상이 없습니다.", "sub", wrap=True)
        l1.addWidget(self.info_label, 1)
        c2, l2 = mk_card()
        self.fast_chk = QCheckBox("화질 손실 없이 빠르게 (재인코딩 안 함)")
        l2.addWidget(self.fast_chk)
        l2.addWidget(mk_label("체크하면 삭제 경계가 키프레임에 맞춰져 최대 약 2초 오차가 생길 수 있습니다. "
                              "체크하지 않으면 정확한 위치에서 자릅니다(다시 인코딩).", "sub", wrap=True))
        top.addWidget(c1, 1)
        top.addWidget(c2, 1)
        outer.addLayout(top)

        mid = QHBoxLayout()
        mid.setSpacing(12)
        mid.addWidget(self.build_player_card(), 135)
        mid.addWidget(self.build_list_card(), 100)
        outer.addLayout(mid, 1)
        outer.addWidget(self.build_bottom("4. 편집 및 저장", "편집 시작 (MP4로 저장)", self.start_edit))

    def build_player_card(self):
        card, lay = mk_card()
        self.pill = QLabel("")
        self.pill.setWordWrap(True)
        lay.addWidget(self.pill)
        box = QFrame()
        box.setObjectName("videoBox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.placeholder = mk_label("영상 파일을 여기로 끌어다 놓거나\n[영상 파일 선택]을 눌러 주세요.", "placeholder", wrap=True)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video = QVideoWidget()
        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(self.video)
        self.stack.setMinimumHeight(220)
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        bl.addWidget(self.stack)
        lay.addWidget(box, 1)
        self.seek_bar = SeekBar(color="#DC2626", fill="#FCA5A5", hatch="#7F1D1D")
        self.seek_bar.seekRequested.connect(self.seek)
        lay.addWidget(self.seek_bar)
        self.pos_label = mk_label("00:00.0 / 00:00.0", "sub")
        lay.addWidget(self.pos_label)
        ctl, self.speed = mk_controls(self.seek_rel, self.play, self.stop, self.on_speed)
        lay.addLayout(ctl)
        big = QHBoxLayout()
        big.setSpacing(10)
        self.start_btn = mk_btn("삭제 시작 (S)", self.begin_mark, "dstart")
        self.end_btn = mk_btn("삭제 종료 (E)", self.end_mark, "dend")
        self.cancel_mark_btn = mk_btn("지정 취소", self.cancel_mark, "danger")
        for b in (self.start_btn, self.end_btn, self.cancel_mark_btn):
            b.setMinimumHeight(58)
        big.addWidget(self.start_btn, 2)
        big.addWidget(self.end_btn, 2)
        big.addWidget(self.cancel_mark_btn, 1)
        lay.addLayout(big)
        pv = mk_btn("▶ 삭제 후 결과 미리보기", self.preview_result, "prev")
        pv.setMinimumHeight(40)
        lay.addWidget(pv)
        lay.addWidget(mk_label("단축키: S 시작 · E 종료 · 스페이스 재생/정지 · ←/→ 5초 이동", "sub"))
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        sty(self.msg, "color:#9A3412;font-weight:700;")
        lay.addWidget(self.msg)
        return card

    def build_list_card(self):
        card, lay = mk_card()
        card.setMinimumWidth(430)
        lay.addWidget(mk_label("3. 지울 구간 목록", "h"))
        head = QWidget()
        hg = QGridLayout(head)
        hg.setContentsMargins(8, 0, 8, 0)
        hg.setHorizontalSpacing(6)
        self._cols(hg)
        for col, t in enumerate(("번호", "시작", "종료", "길이", "확인", "삭제")):
            lb = mk_label(t, "sub")
            lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hg.addWidget(lb, 0, col)
        lay.addWidget(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self.rows_layout = QVBoxLayout(host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        self.scroll.setWidget(host)
        lay.addWidget(self.scroll, 1)
        brow = QHBoxLayout()
        brow.setSpacing(8)
        brow.addWidget(mk_btn("＋ 구간 직접 추가", self.add_blank, "add"), 1)
        brow.addWidget(mk_btn("전체 초기화", self.reset_all, "danger"))
        lay.addLayout(brow)
        self.summary = QLabel("")
        self.summary.setStyleSheet("font-weight:700;")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        return card

    def _cols(self, grid):
        grid.setColumnMinimumWidth(0, 34)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnMinimumWidth(3, 70)
        grid.setColumnMinimumWidth(4, 34)
        grid.setColumnMinimumWidth(5, 34)

    # ---- 영상 불러오기 ----
    def choose_video(self):
        if not self.win.ensure_tools():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "영상 선택", "", "동영상 (*.mp4 *.mov *.m4v *.mkv *.avi);;모든 파일 (*.*)")
        if path:
            self.load_video(path)

    def load_video(self, path):
        if not self.win.ensure_tools():
            return
        if self.busy():
            QMessageBox.information(self.win, APP_TITLE, "편집이 진행 중입니다. 끝난 뒤에 영상을 바꿔 주세요.")
            return
        try:
            info = probe(self.win.ffprobe, path)
        except EditError as e:
            QMessageBox.critical(self.win, APP_TITLE, str(e))
            return
        if self.complete():
            ans = QMessageBox.question(self.win, APP_TITLE,
                                       "새 영상을 선택하면 지금까지 지정한 지울 구간이 모두 지워집니다.\n계속할까요?")
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.src, self.info = path, info
        self.dur = info["duration"]
        self.rows = []
        self.can_play = True
        self.play_until = None
        self.skip = False
        self.seek_bar.set_duration(self.dur)
        self.placeholder.setText("영상을 불러오는 중입니다...")
        self.stack.setCurrentIndex(1)
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.pause()
        text = (f"{os.path.basename(path)} · {info['width']}x{info['height']} · {fps_label(info['fps'])} fps · "
                f"{fmt_time(info['duration'])} · {info['codec']}")
        if info["transfer"] in HDR_TRANSFERS:
            text += " · HDR"
        self.info_label.setText(text)
        self.flash("")
        self.on_position(0)
        self.rebuild()

    # ---- 구간 계산 ----
    def complete(self):
        return [(r["start"], r["end"]) for r in self.rows
                if not r["active"] and r["start"] is not None and r["end"] is not None and r["end"] > r["start"]]

    def merged(self):
        return merge_ranges(self.complete(), self.dur)

    def active_index(self):
        for i, r in enumerate(self.rows):
            if r["active"]:
                return i
        return None

    def flash(self, text):
        self.msg.setText(text or "")

    # ---- 재생 ----
    def cur_sec(self):
        return self.player.position() / 1000.0

    def seek(self, sec):
        sec = max(0.0, min(float(sec), self.dur if self.dur > 0 else float(sec)))
        self.play_until = None
        self.skip = False
        self.player.setPosition(int(sec * 1000))
        self.on_position(int(sec * 1000))

    def seek_rel(self, delta):
        if self.can_play:
            self.seek(self.cur_sec() + delta)

    def toggle_play(self):
        if not self.can_play:
            return
        self.play_until = None
        self.skip = False
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def play(self):
        if self.can_play:
            self.play_until = None
            self.skip = False
            self.player.play()

    def stop(self):
        if self.can_play:
            self.play_until = None
            self.skip = False
            self.player.pause()

    def on_speed(self, text):
        try:
            self.player.setPlaybackRate(float(text.rstrip("x")))
        except ValueError:
            pass

    def on_position(self, ms):
        sec = ms / 1000.0
        self.seek_bar.set_position(sec)
        self.pos_label.setText(f"{fmt_time1(sec)} / {fmt_time1(self.dur)}")
        ai = self.active_index()
        self.seek_bar.set_segments(self.merged(), (self.rows[ai]["start"], sec) if ai is not None else None)
        if self.skip:
            for s, e in self.merged():
                if s - 0.02 <= sec < e:
                    if e >= self.dur - 0.05:
                        self.skip = False
                        self.player.pause()
                    else:
                        self.player.setPosition(int(e * 1000))
                    break
        if self.play_until is not None and sec >= self.play_until:
            self.play_until = None
            self.player.pause()

    def on_duration(self, ms):
        if ms > 0:
            self.dur = ms / 1000.0
            self.seek_bar.set_duration(self.dur)

    def on_error(self, _error, message):
        self.can_play = False
        self.placeholder.setText("이 영상은 프로그램 안에서 재생할 수 없습니다.\n"
                                 f"({message})\n\n오른쪽 목록의 [+ 구간 직접 추가]로 시간을 직접 입력해도 편집은 할 수 있습니다.")
        self.stack.setCurrentIndex(0)

    def preview_result(self):
        if not self.can_play:
            self.flash("영상을 재생할 수 없는 상태입니다.")
            return
        m = self.merged()
        if not m:
            self.flash("지울 구간을 먼저 지정해 주세요.")
            return
        self.play_until = None
        self.skip = True
        self.player.setPosition(int((m[0][1] if m[0][0] <= 0.01 else 0.0) * 1000))
        self.player.play()
        self.flash("삭제 후 결과를 미리 봅니다. (지운 구간은 건너뜁니다)")

    def play_row(self, i):
        r = self.rows[i]
        if not self.can_play:
            self.flash("영상을 재생할 수 없는 상태입니다.")
            return
        if r["start"] is None or r["end"] is None or r["end"] <= r["start"]:
            self.flash("시작과 종료 시간이 올바른 구간만 확인할 수 있습니다.")
            return
        self.skip = False
        self.player.setPosition(int(max(0.0, r["start"] - 3) * 1000))
        self.play_until = min(self.dur, r["end"] + 3)     # 앞뒤 3초를 함께 보여줌
        self.player.play()

    # ---- 구간 지정 ----
    def begin_mark(self):
        if not self.can_play:
            self.flash("먼저 재생 가능한 영상을 선택해 주세요.")
            return
        if self.active_index() is not None:
            self.flash("이미 [삭제 시작]을 눌렀습니다. 먼저 [삭제 종료]를 눌러 주세요.")
            return
        self.rows.append({"start": self.cur_sec(), "end": None, "active": True})
        self.flash("")
        self.rebuild(True)

    def end_mark(self):
        if not self.can_play:
            self.flash("먼저 재생 가능한 영상을 선택해 주세요.")
            return
        i = self.active_index()
        if i is None:
            self.flash("먼저 [삭제 시작]을 눌러 주세요.")
            return
        t = self.cur_sec()
        if t <= self.rows[i]["start"]:
            self.flash("종료 위치가 시작 위치보다 앞입니다. 영상을 더 재생한 뒤 눌러 주세요.")
            return
        self.rows[i].update(end=t, active=False)
        self.flash(f"{i + 1}번 구간을 지정했습니다.")
        self.rebuild(True)

    def cancel_mark(self):
        i = self.active_index()
        if i is None:
            return
        self.rows.pop(i)
        self.flash("지정 중이던 구간을 취소했습니다.")
        self.rebuild()

    def add_blank(self):
        self.rows.append({"start": None, "end": None, "active": False})
        self.flash("시작·종료 시간을 직접 입력해 주세요.")
        self.rebuild(True)

    def delete_row(self, i):
        if 0 <= i < len(self.rows):
            self.rows.pop(i)
            self.rebuild()

    def edit_time(self, i, key, edit):
        txt = edit.text().strip()
        try:
            if not txt:
                val = None
            else:
                val = parse_time(txt)
                if self.dur and val > self.dur:
                    val = self.dur
            r = self.rows[i]
            other = r["end" if key == "start" else "start"]
            if val is not None and other is not None:
                s, e = (val, other) if key == "start" else (other, val)
                if e <= s:
                    raise EditError("종료 시간은 시작 시간보다 늦어야 합니다.")
            r[key] = val
            self.flash("")
        except EditError as e:
            self.flash(str(e))
        except ValueError:
            self.flash("시간은 분:초 형식(예: 1:23.5)으로 입력해 주세요.")
        QTimer.singleShot(0, self.rebuild)

    def reset_all(self):
        ans = QMessageBox.question(self.win, APP_TITLE,
                                   "지정한 지울 구간을 모두 지우고 처음 상태로 되돌립니다.\n"
                                   "불러온 영상은 그대로 둡니다.\n\n계속할까요?")
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.play_until = None
        self.skip = False
        if self.can_play:
            self.player.pause()
        self.rows = []
        self.bar.setValue(0)
        self.flash("전체 초기화했습니다.")
        self.rebuild()

    # ---- 목록 그리기 ----
    def rebuild(self, scroll_end=False):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for i, r in enumerate(self.rows):
            fr = QFrame()
            fr.setObjectName("rowActive" if r["active"] else "row")
            g = QGridLayout(fr)
            g.setContentsMargins(8, 6, 8, 6)
            g.setHorizontalSpacing(6)
            self._cols(g)
            n = mk_label(str(i + 1), "h")
            n.setAlignment(Qt.AlignmentFlag.AlignCenter)
            g.addWidget(n, 0, 0)
            for col, key in ((1, "start"), (2, "end")):
                ed = QLineEdit("" if r[key] is None else fmt_time1(r[key]))
                ed.setAcceptDrops(False)
                ed.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ed.editingFinished.connect(lambda i=i, k=key, e=ed: self.edit_time(i, k, e))
                g.addWidget(ed, 0, col)
            ln = QLabel(len_text({"start": r["start"], "end": r["end"]}))
            ln.setStyleSheet("font-weight:700;")
            ln.setAlignment(Qt.AlignmentFlag.AlignCenter)
            g.addWidget(ln, 0, 3)
            pb = mk_btn("▶", lambda i=i: self.play_row(i), "iconplay")
            pb.setToolTip("앞뒤 3초를 포함해 확인")
            g.addWidget(pb, 0, 4)
            g.addWidget(mk_btn("✕", lambda i=i: self.delete_row(i), "icondel"), 0, 5)
            self.rows_layout.addWidget(fr)
        ghost = QLabel("다음 지울 구간은 [삭제 시작] 버튼으로 추가하세요")
        sty(ghost, GHOST)
        ghost.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rows_layout.addWidget(ghost)
        self.rows_layout.addStretch(1)
        if scroll_end:
            QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().maximum()))
        self.refresh()

    def refresh(self):
        ai = self.active_index()
        if ai is not None:
            self.pill.setText(f"{ai + 1}번 지울 구간 지정 중 · 지울 장면이 끝나면 [삭제 종료]를 누르세요")
            sty(self.pill, PILL_ACTIVE)
        else:
            self.pill.setText("지울 구간 지정 대기 · 지울 장면이 시작되면 [삭제 시작]을 누르세요")
            sty(self.pill, PILL_IDLE)
        m = self.merged()
        dele = sum(e - s for s, e in m)
        if self.src:
            dtxt = f"{dele:.1f}초" if dele < 60 else fmt_time(dele)
            self.summary.setText(f"원본 {fmt_time(self.dur)} − 지울 구간 {len(self.complete())}개 완료({dtxt})"
                                 f" = 결과 약 {fmt_time(max(0.0, self.dur - dele))}")
        else:
            self.summary.setText("")
        ai = self.active_index()
        self.seek_bar.set_segments(m, (self.rows[ai]["start"], self.cur_sec()) if ai is not None else None)

    # ---- 저장 ----
    def start_edit(self):
        if self.busy() or not self.win.ensure_tools():
            return
        if not self.src:
            QMessageBox.information(self.win, APP_TITLE, "먼저 영상 파일을 선택해 주세요.")
            return
        dels = self.complete()
        if not dels:
            QMessageBox.warning(self.win, APP_TITLE, "지울 구간을 1개 이상 지정해 주세요.")
            return
        if not keep_ranges(dels, self.dur):
            QMessageBox.warning(self.win, APP_TITLE, "지우고 남는 영상이 없습니다. 지울 구간을 확인해 주세요.")
            return
        if self.win.tonemap_ok is None:
            self.win.tonemap_ok = has_tonemap_filters(self.win.ffmpeg)
        default = os.path.join(os.path.dirname(self.src), "구간삭제.mp4")
        out, _ = QFileDialog.getSaveFileName(self, "저장할 위치와 이름", default, "MP4 동영상 (*.mp4)")
        if not out:
            return
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        if os.path.abspath(out) == os.path.abspath(self.src):
            QMessageBox.warning(self.win, APP_TITLE, "원본 영상과 같은 이름으로는 저장할 수 없습니다.")
            return
        self.player.pause()
        src, info, fast, ff, tm = self.src, self.info, self.fast_chk.isChecked(), self.win.ffmpeg, self.win.tonemap_ok
        self.run_job(lambda pr, ce: make_cut(ff, src, info, dels, out, pr, ce, tm, fast), out)

    def shutdown(self):
        self.cancel_event.set()
        self.player.stop()

    def key(self, name):
        {"mark_start": self.begin_mark, "mark_end": self.end_mark, "toggle": self.toggle_play,
         "back": lambda: self.seek_rel(-5), "fwd": lambda: self.seek_rel(5)}[name]()


class MergeTab(BaseTab):
    """③ 영상 합치기: 여러 영상을 순서대로 하나의 MP4로 합칩니다."""

    def __init__(self, win):
        super().__init__(win)
        self.clips = []             # {"id", "path", "info", "thumb"}
        self.next_id = 1
        self.sel_id = None
        self.transition = False
        self._x265 = None
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player.setAudioOutput(self.audio)
        self.build()
        self.player.setVideoOutput(self.video)
        self.rebuild()

    def build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 12, 0, 0)
        outer.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(12)
        c1, l1 = mk_card(vertical=False)
        l1.addWidget(mk_label("1. 영상 추가", "h"))
        l1.addWidget(mk_btn("영상 파일 추가 (여러 개 선택 가능)", self.choose_files, "file"))
        l1.addWidget(mk_label("여기에 끌어다 놓아도 추가됩니다.", "sub"), 1)
        c2, l2 = mk_card(vertical=False)
        l2.addWidget(mk_label("합치기 방식", "h"))
        self.tr0 = mk_btn("바로 이어붙이기", lambda: self.set_transition(False), "ratio")
        self.tr1 = mk_btn("부드럽게 전환(0.5초)", lambda: self.set_transition(True), "ratio")
        for b in (self.tr0, self.tr1):
            b.setCheckable(True)
            b.setMinimumHeight(34)
        self.tr0.setChecked(True)
        l2.addWidget(self.tr0)
        l2.addWidget(self.tr1)
        l2.addStretch(1)
        top.addWidget(c1, 1)
        top.addWidget(c2, 1)
        outer.addLayout(top)

        mid = QHBoxLayout()
        mid.setSpacing(12)
        lc, ll = mk_card()
        lc.setMinimumWidth(520)
        ll.addWidget(mk_label("2. 합칠 영상 목록", "h"))
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSpacing(4)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.model().rowsMoved.connect(self.on_rows_moved)
        self.list.currentRowChanged.connect(self.on_current_row)
        ll.addWidget(self.list, 1)
        ll.addWidget(mk_label("영상 파일을 창에 끌어다 놓으면 목록 끝에 추가됩니다 · 줄을 끌어서 순서를 바꾸거나 ▲▼ 버튼을 누르세요", "sub", wrap=True))
        brow = QHBoxLayout()
        brow.setSpacing(8)
        brow.addWidget(mk_btn("＋ 영상 파일 추가", self.choose_files, "add"), 1)
        brow.addWidget(mk_btn("전체 초기화", self.reset_all, "danger"))
        ll.addLayout(brow)
        self.summary = QLabel("")
        self.summary.setStyleSheet("font-weight:700;")
        ll.addWidget(self.summary)

        rc, rl = mk_card()
        rl.addWidget(mk_label("선택한 영상 미리보기", "h"))
        box = QFrame()
        box.setObjectName("videoBox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.placeholder = mk_label("목록에서 영상을 선택하면\n여기에 나옵니다.", "placeholder", wrap=True)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video = QVideoWidget()
        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(self.video)
        self.stack.setMinimumHeight(200)
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        bl.addWidget(self.stack)
        rl.addWidget(box, 1)
        ctl, _sp = mk_controls(self.seek_rel, self.play, self.stop)
        rl.addLayout(ctl)
        self.info_box = QLabel("")
        self.info_box.setObjectName("infobox")
        self.info_box.setWordWrap(True)
        self.info_box.setTextFormat(Qt.TextFormat.RichText)
        rl.addWidget(self.info_box)
        self.note = QLabel("")
        self.note.setObjectName("note")
        self.note.setWordWrap(True)
        rl.addWidget(self.note)
        mid.addWidget(lc, 135)
        mid.addWidget(rc, 100)
        outer.addLayout(mid, 1)
        outer.addWidget(self.build_bottom("3. 합치기 및 저장", "합치기 시작 (MP4로 저장)", self.start_merge))

    # ---- 계산 ----
    def can_hdr(self):
        if self._x265 is None:
            self._x265 = bool(self.win.ffmpeg) and has_encoder(self.win.ffmpeg, "libx265")
        return self._x265

    def plan(self):
        return merge_plan(self.clips, self.transition, self.can_hdr()) if self.clips else None

    def warns(self, c, p):
        w = []
        i = c["info"]
        if (i["width"], i["height"]) != (p["width"], p["height"]):
            same = abs(i["width"] / i["height"] - p["width"] / p["height"]) < 0.02
            w.append(f"해상도 다름 → {p['width']}x{p['height']}로 맞춤" if same else "해상도 다름 → 검은 여백")
        if i["fps"] != p["fps"]:
            w.append(f"fps 다름 → {fps_label(p['fps'])}fps로 맞춤")
        if p["mixed_hdr"] and i["transfer"] in HDR_TRANSFERS:
            w.append("HDR → SDR로 변환")
        return w

    # ---- 영상 추가·삭제·순서 ----
    def choose_files(self):
        if not self.win.ensure_tools():
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "합칠 영상 선택 (여러 개 선택 가능)", "", "동영상 (*.mp4 *.mov *.m4v *.mkv *.avi);;모든 파일 (*.*)")
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths):
        if not self.win.ensure_tools():
            return
        if self.busy():
            QMessageBox.information(self.win, APP_TITLE, "합치는 중에는 영상을 바꿀 수 없습니다.")
            return
        bad = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for p in paths:
                if not p.lower().endswith(VIDEO_EXTS):
                    bad.append(f"{os.path.basename(p)}: 지원하지 않는 형식")
                    continue
                try:
                    info = probe(self.win.ffprobe, p)
                except EditError as e:
                    bad.append(f"{os.path.basename(p)}: {e}")
                    continue
                self.clips.append({"id": self.next_id, "path": p, "info": info,
                                   "thumb": make_thumb(self.win.ffmpeg, p, info["duration"])})
                self.next_id += 1
        finally:
            QApplication.restoreOverrideCursor()
        if self.sel_id is None and self.clips:
            self.sel_id = self.clips[0]["id"]
        self.rebuild()
        self.load_preview()
        if bad:
            QMessageBox.warning(self.win, APP_TITLE, "일부 영상을 불러오지 못했습니다.\n" + "\n".join(bad))

    def index_of(self, cid):
        for i, c in enumerate(self.clips):
            if c["id"] == cid:
                return i
        return -1

    def move(self, cid, to):
        i = self.index_of(cid)
        if i < 0:
            return
        c = self.clips.pop(i)
        self.clips.insert(max(0, min(to, len(self.clips))), c)
        self.rebuild()

    def remove(self, cid):
        i = self.index_of(cid)
        if i < 0:
            return
        self.clips.pop(i)
        if self.sel_id == cid:
            self.sel_id = self.clips[0]["id"] if self.clips else None
            self.load_preview()
        self.rebuild()

    def on_rows_moved(self, *_args):
        ids = [self.list.item(r).data(Qt.ItemDataRole.UserRole) for r in range(self.list.count())]
        QTimer.singleShot(0, lambda ids=ids: self.apply_order(ids))

    def apply_order(self, ids):
        by = {c["id"]: c for c in self.clips}
        if sorted(ids) == sorted(by):
            self.clips = [by[i] for i in ids]
        self.rebuild()

    def on_current_row(self, row):
        if 0 <= row < self.list.count():
            cid = self.list.item(row).data(Qt.ItemDataRole.UserRole)
            if cid != self.sel_id:
                self.sel_id = cid
                self.load_preview()

    def set_transition(self, on):
        self.transition = bool(on)
        self.tr0.setChecked(not on)
        self.tr1.setChecked(bool(on))
        self.refresh()

    def reset_all(self):
        if not self.clips:
            return
        ans = QMessageBox.question(self.win, APP_TITLE,
                                   "합칠 영상 목록을 모두 비우고 처음 상태로 되돌립니다.\n"
                                   "(원본 파일은 지워지지 않습니다.)\n\n계속할까요?")
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.player.stop()
        self.clips = []
        self.sel_id = None
        self.stack.setCurrentIndex(0)
        self.bar.setValue(0)
        self.status.setText("대기 중")
        self.set_transition(False)
        self.rebuild()

    # ---- 화면 갱신 ----
    def rebuild(self):
        p = self.plan()
        self.list.blockSignals(True)
        self.list.clear()
        for i, c in enumerate(self.clips):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, c["id"])
            item.setSizeHint(QSize(100, 76))
            self.list.addItem(item)
            self.list.setItemWidget(item, self.make_row(i, c, p))
            if c["id"] == self.sel_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.refresh()

    def make_row(self, i, c, p):
        fr = QFrame()
        fr.setObjectName("clipRow")
        g = QHBoxLayout(fr)
        g.setContentsMargins(8, 4, 8, 4)
        g.setSpacing(10)
        grip = mk_label("≡", "h")
        grip.setFixedWidth(20)
        g.addWidget(grip)
        th = QLabel()
        th.setFixedSize(84, 48)
        sty(th, "background:#0B1220;border-radius:4px;")
        if c["thumb"]:
            pm = QPixmap()
            if pm.loadFromData(c["thumb"]):
                th.setPixmap(pm.scaled(84, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
                th.setAlignment(Qt.AlignmentFlag.AlignCenter)
        g.addWidget(th)
        mid = QVBoxLayout()
        mid.setSpacing(1)
        nm = mk_label(f"{i + 1}. {os.path.basename(c['path'])}", "h")
        nm.setToolTip(c["path"])
        mid.addWidget(nm)
        inf = c["info"]
        mid.addWidget(mk_label(f"{inf['width']}x{inf['height']} · {fps_label(inf['fps'])}fps · "
                               f"{fmt_time(inf['duration'])} · {inf['codec']}", "sub"))
        badges = []
        if inf["transfer"] in HDR_TRANSFERS:
            badges.append(("HDR", "#FDE68A", "#78350F"))
        badges.append(("소리 있음" if inf["has_audio"] else "소리 없음", "#D1FAE5", "#065F46"))
        if p:
            badges += [(w, "#FFE4D5", "#9A3412") for w in self.warns(c, p)]
        bl = QLabel("&nbsp;".join(
            f'<span style="background-color:{bg};color:{fg};">&nbsp;{t}&nbsp;</span>' for t, bg, fg in badges))
        bl.setTextFormat(Qt.TextFormat.RichText)
        bl.setStyleSheet("font-size:9pt;font-weight:700;")
        mid.addWidget(bl)
        g.addLayout(mid, 1)
        cid = c["id"]
        up = mk_btn("▲", lambda cid=cid: self.move(cid, self.index_of(cid) - 1), "icondn")
        dn = mk_btn("▼", lambda cid=cid: self.move(cid, self.index_of(cid) + 1), "icondn")
        up.setEnabled(i > 0)
        dn.setEnabled(i < len(self.clips) - 1)
        for b in (up, dn):
            b.setFixedSize(30, 30)
            g.addWidget(b)
        rm = mk_btn("✕", lambda cid=cid: self.remove(cid), "icondel")
        rm.setFixedSize(30, 30)
        g.addWidget(rm)
        return fr

    def refresh(self):
        tot = sum(c["info"]["duration"] for c in self.clips)
        self.summary.setText(f"영상 {len(self.clips)}개 · 합계 {fmt_len(tot)}" if self.clips else "")
        p = self.plan()
        if not p:
            self.info_box.setText("영상을 추가하면 합친 영상의 크기·화질이 여기에 표시됩니다.")
            self.note.setText("")
            self.note.setVisible(False)
            return
        mode = ("다시 인코딩 없이 이어붙임 (빠름)" if p["fast"] and not self.transition
                else "크기·fps를 맞춰 다시 인코딩")
        self.info_box.setText(
            f"합친 영상 크기(자동): <b>{ratio_label(p['width'], p['height'])} {p['width']}x{p['height']}</b>"
            f" · {fps_label(p['fps'])}fps (가장 많은 크기 기준)<br>"
            f"화질: <b>{'원본 색상(HDR) 유지' if p['keep'] else 'SDR(일반 색상)'}</b><br>"
            f"방식: <b>{mode}</b>")
        t = ""
        if p["mixed_hdr"]:
            t = "HDR 영상과 일반(SDR) 영상이 섞여 있어 모두 SDR로 통일해 저장합니다. "
        if any(self.warns(c, p) for c in self.clips) or self.transition:
            t += "크기·fps가 다르거나 부드러운 전환을 쓰면 다시 인코딩하므로 시간이 더 걸립니다."
        self.note.setText(t)
        self.note.setVisible(bool(t))

    # ---- 미리보기 ----
    def sel_clip(self):
        i = self.index_of(self.sel_id)
        return self.clips[i] if i >= 0 else None

    def load_preview(self):
        c = self.sel_clip()
        if not c:
            self.player.stop()
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(c["path"]))
        self.player.pause()

    def seek_rel(self, d):
        if self.sel_clip():
            self.player.setPosition(max(0, int(self.player.position() + d * 1000)))

    def play(self):
        if self.sel_clip():
            self.player.play()

    def stop(self):
        if self.sel_clip():
            self.player.pause()

    # ---- 저장 ----
    def start_merge(self):
        if self.busy() or not self.win.ensure_tools():
            return
        if len(self.clips) < 2:
            QMessageBox.information(self.win, APP_TITLE, "합칠 영상을 2개 이상 추가해 주세요.")
            return
        if self.win.tonemap_ok is None:
            self.win.tonemap_ok = has_tonemap_filters(self.win.ffmpeg)
        default = os.path.join(os.path.dirname(self.clips[0]["path"]), "합친영상.mp4")
        out, _ = QFileDialog.getSaveFileName(self, "저장할 위치와 이름", default, "MP4 동영상 (*.mp4)")
        if not out:
            return
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        self.player.pause()
        clips = [{"path": c["path"], "info": c["info"]} for c in self.clips]
        ff, tm, tr = self.win.ffmpeg, self.win.tonemap_ok, self.transition
        self.run_job(lambda pr, ce: make_merge(ff, clips, out, pr, ce, tm, tr), out)

    def shutdown(self):
        self.cancel_event.set()
        self.player.stop()

    def key(self, name):
        pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(app_icon())
        self.resize(1280, 880)
        self.setMinimumSize(1120, 760)
        self.setAcceptDrops(True)

        self.ffmpeg, self.ffprobe = find_ffmpeg_pair()
        self.font_path, self.font_note = find_font()
        self.tonemap_ok = None
        self.src = None
        self.info = None
        self.dur = 0.0
        self.can_play = False
        self.play_until = None
        self.marks = Marks()
        self.row_widgets = []
        self.row_frames = []
        self.sel = -1
        self.out_ratio = DEFAULT_RATIO
        self._syncing = False
        self.worker = None
        self.cancel_event = threading.Event()
        self.bridge = Bridge()
        self.bridge.progress.connect(self.on_progress)
        self.bridge.done.connect(self.on_done)
        self.bridge.failed.connect(self.on_failed)
        self.bridge.cancelled.connect(self.on_cancelled)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player.setAudioOutput(self.audio)

        self.build_ui()
        decorate_ui(self)
        QApplication.instance().installEventFilter(self)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self.on_position)
        self.player.durationChanged.connect(self.on_duration)
        self.player.playbackStateChanged.connect(self.on_state)
        self.player.errorOccurred.connect(self.on_error)

        for key, name in (("S", "mark_start"), ("E", "mark_end"), ("Space", "toggle"),
                          ("Left", "back"), ("Right", "fwd")):
            QShortcut(QKeySequence(key), self).activated.connect(lambda n=name: self.on_key(n))

        self.rebuild_rows()
        self.show_tool_status()
        QTimer.singleShot(400, self.ensure_tools)   # 못 찾았으면 창이 뜬 직후 바로 안내

    def build_theme_toggle(self):
        """탭 오른쪽 끝: ☀ 라이트 / ☾ 다크 / 자동"""
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(0)
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_btns = {}
        for mode, text, pos in (("light", "☀ 라이트", "l"), ("dark", "☾ 다크", "m"), ("auto", "자동", "r")):
            b = QPushButton(text)
            b.setObjectName("themeBtn")
            b.setProperty("pos", pos)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, m=mode: self.set_theme_mode(m))
            self.theme_group.addButton(b)
            self.theme_btns[mode] = b
            lay.addWidget(b)
        self.theme_btns[THEME["mode"]].setChecked(True)
        self.tabs.setCornerWidget(box, Qt.Corner.TopRightCorner)
        self._sys_dark = system_is_dark()
        self.theme_timer = QTimer(self)             # '자동'일 때 윈도우 설정이 바뀌면 따라갑니다
        self.theme_timer.timeout.connect(self.check_system_theme)
        self.theme_timer.start(4000)

    def set_theme_mode(self, mode):
        apply_theme(mode, win=self)
        set_theme(mode)                              # 다음 실행 때도 기억
        self.update_theme_dependents()

    def check_system_theme(self):
        if THEME["mode"] != "auto":
            return
        now = system_is_dark()
        if now != self._sys_dark:
            self._sys_dark = now
            apply_theme("auto", win=self)
            self.update_theme_dependents()

    def update_theme_dependents(self):
        for w in self.findChildren(SeekBar):
            w.update()
        for w in self.findChildren(VideoView):
            w.viewport().update()

    def on_key(self, name):
        """단축키는 지금 보이는 탭에만 적용됩니다."""
        i = self.tabs.currentIndex()
        if i == 0:
            {"mark_start": self.begin_mark, "mark_end": self.end_mark, "toggle": self.toggle_play,
             "back": lambda: self.seek_rel(-5), "fwd": lambda: self.seek_rel(5)}[name]()
        elif i == 1:
            self.cut_tab.key(name)

    def on_tab_changed(self, _i):
        self.player.pause()
        self.cut_tab.player.pause()
        self.merge_tab.player.pause()

    # ---- 작은 도우미 ----
    def _btn(self, text, slot=None, name=None):
        b = QPushButton(text)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # 스페이스바가 버튼을 누르지 않도록
        if name:
            b.setObjectName(name)
        if slot:
            b.clicked.connect(lambda _checked=False, f=slot: f())
        return b

    def _edit(self, text=""):
        e = QLineEdit(text)
        e.setAcceptDrops(False)   # 입력칸 위에 놓아도 창이 파일을 받도록
        return e

    def _label(self, text, name=None, wrap=False):
        lb = QLabel(text)
        if name:
            lb.setObjectName(name)
        lb.setWordWrap(wrap)
        return lb

    def _card(self, vertical=True):
        f = QFrame()
        f.setObjectName("card")
        lay = QVBoxLayout(f) if vertical else QHBoxLayout(f)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)
        return f, lay

    def _panel(self, num, title, area):
        """B안 패널: 색 머리띠(번호·제목·오른쪽 내용) + 본문. (패널, 머리띠 레이아웃, 본문 레이아웃)"""
        f = QFrame()
        f.setObjectName("pnl")
        f.setProperty("area", area)
        v = QVBoxLayout(f)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        hd = QFrame()
        hd.setObjectName("phd")
        hl = QHBoxLayout(hd)
        hl.setContentsMargins(10, 6, 10, 6)
        hl.setSpacing(8)
        nb = QLabel(str(num))
        nb.setObjectName("nbw")
        hl.addWidget(nb)
        hl.addWidget(self._label(title, "ph"))
        v.addWidget(hd)
        body = QVBoxLayout()
        body.setContentsMargins(12, 10, 12, 10)
        body.setSpacing(8)
        v.addLayout(body, 1)
        return f, hl, body

    # ---- 화면 구성 ----
    def build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        root_lay = QVBoxLayout(root)
        root_lay.setContentsMargins(14, 10, 14, 14)
        root_lay.setSpacing(0)
        self.tabs = QTabWidget()
        root_lay.addWidget(self.tabs)
        page1 = QWidget()
        outer = QVBoxLayout(page1)
        outer.setContentsMargins(0, 12, 0, 0)
        outer.setSpacing(12)

        # B안: 왼쪽 1.영상 패널 / 오른쪽 2.득점 구간 목록 + 3.편집 및 저장 패널
        self.title_on = QCheckBox("사용")
        self.title_on.setChecked(False)
        self.title_edit = self._edit()
        self.title_edit.setPlaceholderText("예: [팀명] 시즌 하이라이트")
        self.title_secs = self._edit("3")
        self.title_secs.setFixedWidth(56)
        mid = QHBoxLayout()
        mid.setSpacing(12)
        mid.addWidget(self.build_player_card(), 135)
        rcol = QVBoxLayout()
        rcol.setSpacing(12)
        rcol.addWidget(self.build_list_card(), 1)
        rcol.addWidget(self.build_bottom_card())
        mid.addLayout(rcol, 100)
        outer.addLayout(mid, 1)
        self.title_on.toggled.connect(self.toggle_title)
        self.toggle_title(False)
        self.title_edit.textChanged.connect(lambda _t: self.refresh_marks())
        self.title_secs.textChanged.connect(lambda _t: self.refresh_marks())

        self.cut_tab = CutTab(self)
        self.merge_tab = MergeTab(self)
        self.tabs.addTab(page1, "① 득점 하이라이트")
        self.tabs.addTab(self.cut_tab, "② 구간 삭제 (컷 편집)")
        self.tabs.addTab(self.merge_tab, "③ 영상 합치기")
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.build_theme_toggle()

    def build_player_card(self):
        card, hl, lay = self._panel(1, "영상", "blue")
        self.info_label = self._label("선택된 영상이 없습니다.", "phs")
        self.info_label.setMinimumWidth(40)
        hl.addWidget(self.info_label, 1)
        for text, slot in (("📂 영상 선택", self.choose_video), ("💾 로그 저장", self.save_log),
                           ("📄 로그 불러오기", self.load_log), ("📁 로그 폴더", self.choose_log_dir)):
            hl.addWidget(self._btn(text, slot, "hbtn"))
        self.pill = QLabel("")
        self.pill.setWordWrap(True)
        lay.addWidget(self.pill)

        box = QFrame()
        box.setObjectName("videoBox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.placeholder = self._label("영상 파일을 여기로 끌어다 놓거나\n[영상 파일 선택]을 눌러 주세요.", "placeholder", wrap=True)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas = VideoView()                  # 영상 + 범위 사각형(항상 표시)
        self.video = self.canvas.item
        self.canvas.changed.connect(self.on_canvas_changed)
        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(self.canvas)
        self.stack.setMinimumHeight(220)
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        bl.addWidget(self.stack)
        lay.addWidget(box, 1)
        lay.addWidget(self.build_crop_bar())

        self.seek_bar = SeekBar()
        self.seek_bar.seekRequested.connect(self.seek)
        lay.addWidget(self.seek_bar)
        row = QHBoxLayout()
        self.pos_label = self._label("00:00.0 / 00:00.0", "sub")
        row.addWidget(self.pos_label)
        row.addStretch(1)
        lay.addLayout(row)

        ctl = QHBoxLayout()
        ctl.setSpacing(6)
        ctl.addWidget(self._btn("-5초", lambda: self.seek_rel(-5), "move"))
        ctl.addWidget(self._btn("-2초", lambda: self.seek_rel(-2), "move"))
        ctl.addWidget(self._btn("-1초", lambda: self.seek_rel(-1), "move"))
        self.play_btn = self._btn("▶ 재생", self.play, "play")
        ctl.addWidget(self.play_btn)
        self.stop_btn = self._btn("■ 정지", self.stop, "stop")
        ctl.addWidget(self.stop_btn)
        ctl.addWidget(self._btn("+1초", lambda: self.seek_rel(1), "move"))
        ctl.addWidget(self._btn("+2초", lambda: self.seek_rel(2), "move"))
        ctl.addWidget(self._btn("+5초", lambda: self.seek_rel(5), "move"))
        ctl.addStretch(1)
        ctl.addWidget(self._label("배속", "sub"))
        self.speed = QComboBox()
        self.speed.addItems(["0.5x", "1x", "1.5x", "2x"])
        self.speed.setCurrentText("1x")
        self.speed.setFixedWidth(70)
        self.speed.currentTextChanged.connect(self.on_speed)
        ctl.addWidget(self.speed)
        lay.addLayout(ctl)

        big = QHBoxLayout()
        big.setSpacing(10)
        self.start_btn = self._btn("득점 시작 (S)", self.begin_mark, "start")
        self.end_btn = self._btn("득점 종료 (E)", self.end_mark, "end")
        self.cancel_mark_btn = self._btn("지정 취소", self.cancel_mark, "danger")
        for b in (self.start_btn, self.end_btn, self.cancel_mark_btn):
            b.setMinimumHeight(58)
        big.addWidget(self.start_btn, 2)
        big.addWidget(self.end_btn, 2)
        big.addWidget(self.cancel_mark_btn, 1)
        lay.addLayout(big)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        sty(self.msg, "color:#9A3412;font-weight:700;")
        lay.addWidget(self.msg)
        return card

    def build_crop_bar(self):
        bar = QFrame()
        bar.setObjectName("cropbar")
        self.crop_bar = bar
        v = QVBoxLayout(bar)
        v.setContentsMargins(10, 6, 10, 6)
        v.setSpacing(4)
        r1 = QHBoxLayout()
        r1.setSpacing(6)
        self.crop_on = QCheckBox("구간 범위 사용")
        self.crop_on.toggled.connect(self.on_crop_toggle)
        r1.addWidget(self.crop_on)
        r1.addWidget(self._label("비율", "sub"))
        self.ratio_btns = {}
        for name in RATIOS:
            b = self._btn(name, lambda n=name: self.on_ratio(n), "ratio")
            b.setCheckable(True)
            self.ratio_btns[name] = b
            r1.addWidget(b)
        r1.addStretch(1)
        self.crop_reset = self._btn("이 구간 초기화", self.on_crop_reset, "reset")
        r1.addWidget(self.crop_reset)
        v.addLayout(r1)
        r2 = QHBoxLayout()
        r2.setSpacing(6)
        r2.addWidget(self._label("확대", "sub"))
        self.zoom_btns = []
        for z in (1, 1.5, 2, 3):
            b = self._btn(f"{z:g}x", lambda z=z: self.on_zoom(z), "ratio")
            self.zoom_btns.append(b)
            r2.addWidget(b)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(100, 400)
        self.zoom_slider.setValue(150)
        self.zoom_slider.setFixedWidth(130)
        self.zoom_slider.valueChanged.connect(self.on_slider)
        r2.addWidget(self.zoom_slider)
        self.zoom_label = QLabel("-")
        self.zoom_label.setStyleSheet("font-weight:700;")
        r2.addWidget(self.zoom_label)
        r2.addStretch(1)
        v.addLayout(r2)
        self.crop_hint = self._label("구간 목록에서 구간을 선택하면 그 구간의 범위를 설정합니다.", "sub", wrap=True)
        v.addWidget(self.crop_hint)
        self.ai_note = QLabel("✨ 범위로 확대한 구간은 저장할 때 AI로 선명하게 만듭니다 (확대로 흐려지는 부분 보정)")
        self.ai_note.setObjectName("ainote")
        self.ai_note.setWordWrap(True)
        self.ai_note.setVisible(get_ai_prefs()["on"])
        v.addWidget(self.ai_note)
        return bar

    def _col_widths(self, grid):
        for col, w in enumerate((30, 90, 112, 34, 34)):
            grid.setColumnMinimumWidth(col, w)
        grid.setColumnStretch(1, 1)

    def build_list_card(self):
        card, hl, lay = self._panel(2, "득점 구간 목록", "teal")
        card.setMinimumWidth(430)
        hl.addStretch(1)
        self.summary = self._label("", "phs")
        hl.addWidget(self.summary)
        head = QWidget()
        hg = QGridLayout(head)
        hg.setContentsMargins(8, 0, 8, 0)
        hg.setHorizontalSpacing(6)
        self._col_widths(hg)
        for col, t in enumerate(("번호", "자막 내용", "자막 위치", "재생", "삭제")):
            lb = self._label(t, "sub")
            if col in (0, 3, 4):
                lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hg.addWidget(lb, 0, col)
        lay.addWidget(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self.rows_layout = QVBoxLayout(host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        self.scroll.setWidget(host)
        lay.addWidget(self.scroll, 1)

        tools = QFrame()
        tools.setObjectName("tools")
        brow = QHBoxLayout(tools)
        brow.setContentsMargins(0, 8, 0, 0)
        brow.setSpacing(6)
        brow.addWidget(self._btn("＋ 직접 추가", self.add_blank, "add"))
        self.bulk_pos = QComboBox()
        self.bulk_pos.addItem("자막 위치 일괄")
        self.bulk_pos.addItems(list(POSITIONS.keys()))
        self.bulk_pos.setMinimumHeight(38)
        self.bulk_pos.setToolTip("고르면 모든 득점 구간의 자막 위치가 한 번에 바뀝니다.")
        self.bulk_pos.activated.connect(self.on_bulk_pos)
        brow.addWidget(self.bulk_pos)
        brow.addWidget(self.build_ai_bar(), 1)
        self.reset_list_btn = self._btn("목록 초기화", self.reset_list, "danger")
        brow.addWidget(self.reset_list_btn)
        lay.addWidget(tools)
        return card

    # ---- AI 선명화 (확대 구간) ----
    def build_ai_bar(self):
        bar = QFrame()
        bar.setObjectName("aibox")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(6)
        t = QLabel("✨ AI 선명화")
        t.setObjectName("aititle")
        lay.addWidget(t)
        prefs = get_ai_prefs()
        self.ai_chk = QCheckBox("사용")
        self.ai_chk.setChecked(prefs["on"] and find_esrgan() is not None)
        self.ai_chk.toggled.connect(self.on_ai_toggle)
        lay.addWidget(self.ai_chk)
        self.ai_group = QButtonGroup(self)
        self.ai_group.setExclusive(True)
        self.ai_btns = {}
        for key, text in (("fast", "빠르게"), ("quality", "고화질")):
            b = QPushButton(text)
            b.setObjectName("aiq")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.toggled.connect(lambda c, b=b, t=text: b.setText(("✓ " if c else "") + t))
            b.clicked.connect(lambda _=False, k=key: self.on_ai_model(k))
            self.ai_group.addButton(b)
            self.ai_btns[key] = b
            lay.addWidget(b)
        self.ai_btns[prefs["model"]].setChecked(True)
        self.ai_info = self._label("", "sub")
        self.ai_info.setMinimumWidth(10)
        lay.addWidget(self.ai_info, 1)
        self.ai_bridge = Bridge()
        self.ai_bridge.progress.connect(lambda d, t, m: (self.bar.setValue(int(100.0 * d / max(t, 1))),
                                                         self.status.setText(m)))
        self.ai_bridge.done.connect(self.on_ai_ready)
        self.ai_bridge.failed.connect(self.on_ai_failed)
        self.ai_bridge.cancelled.connect(lambda: self.on_ai_failed("취소했습니다."))
        self.ai_worker = None
        return bar

    def ai_model(self):
        return "fast" if self.ai_btns["fast"].isChecked() else "quality"

    def ai_crop_segments(self):
        return [{"start": r["start"], "end": r["end"], "crop": r.get("crop")}
                for r in self.marks.rows
                if r.get("cropOn") and r.get("crop") and not r["active"]
                and r["start"] is not None and r["end"] is not None]

    def update_ai_info(self):
        if not hasattr(self, "ai_info"):
            return
        on = self.ai_chk.isChecked()
        for b in self.ai_btns.values():
            b.setEnabled(on)
        if hasattr(self, "ai_note"):
            self.ai_note.setVisible(on)
        if not on:
            self.ai_info.setText("꺼짐")
            self.ai_info.setToolTip("끄면 확대 구간도 지금처럼 빠르게 저장합니다. (그래픽카드로 확대 구간을 선명하게 하려면 [사용])")
            return
        segs = self.ai_crop_segments()
        if not segs:
            self.ai_info.setText("대상 없음")
            self.ai_info.setToolTip("구간 범위로 확대한 구간이 생기면 그 구간만 AI로 선명하게 만듭니다.")
            return
        est = ai_estimate(segs, self.info, self.ai_model()) if self.info else None
        self.ai_info.setText(f"{len(segs)}개" + (f" · 약 {fmt_eta(est)}" if est is not None else " · 시간 측정 전"))
        self.ai_info.setToolTip("범위로 확대한 구간 수와 예상 시간")

    def ai_busy(self):
        return bool(self.ai_worker and self.ai_worker.is_alive())

    def on_ai_toggle(self, on):
        set_ai_prefs(on=on)
        if on and find_esrgan() is None:
            box = QMessageBox(self)
            box.setWindowTitle("AI 선명화 도구 설치")
            box.setText("확대 구간 AI 선명화에는 Real-ESRGAN(무료 공개 도구)이 필요합니다.\n"
                        "처음 한 번만 인터넷에서 내려받아(약 45MB) 프로그램 폴더에 설치합니다.\n\n"
                        "그래픽카드를 사용합니다. 설치 후 시험 그림으로 처리 속도를 재서 예상 시간을 알려 드립니다.")
            inst = box.addButton("설치하기", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("나중에", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not inst:
                self.ai_chk.blockSignals(True)
                self.ai_chk.setChecked(False)
                self.ai_chk.blockSignals(False)
                set_ai_prefs(on=False)
                self.update_ai_info()
                return
            self.start_ai_setup(install=True)
        elif on and self.ai_model() not in get_ai_prefs()["speed"]:
            self.start_ai_setup(install=False)
        self.rebuild_rows()
        self.update_ai_info()

    def on_ai_model(self, key):
        set_ai_prefs(model=key)
        if self.ai_chk.isChecked() and find_esrgan() and key not in get_ai_prefs()["speed"]:
            self.start_ai_setup(install=False)
        self.update_ai_info()

    def start_ai_setup(self, install):
        if self.ai_busy() or (self.worker and self.worker.is_alive()):
            return
        if not self.ensure_tools():
            return
        self.edit_btn.setEnabled(False)
        self.ai_chk.setEnabled(False)
        ff, model, br, ce = self.ffmpeg, self.ai_model(), self.ai_bridge, threading.Event()
        self.ai_cancel = ce

        def job():
            try:
                exe = find_esrgan()
                if install or exe is None:
                    exe = install_esrgan(lambda d, t, m: br.progress.emit(d, t, m), ce)
                br.progress.emit(0, 1, "AI 선명화 속도를 재는 중... (그래픽카드 시험, 잠시만 기다려 주세요)")
                esrgan_benchmark(ff, exe, model, ce)
                br.done.emit(model)
            except Cancelled:
                br.cancelled.emit()
            except EditError as e:
                br.failed.emit(str(e))
            except Exception:
                br.failed.emit("예상하지 못한 오류가 발생했습니다.\n\n" + traceback.format_exc()[-600:])
        self.ai_worker = threading.Thread(target=job, daemon=True)
        self.ai_worker.start()

    def on_ai_ready(self, model):
        self.edit_btn.setEnabled(True)
        self.ai_chk.setEnabled(True)
        self.bar.setValue(0)
        sp = get_ai_prefs()["speed"].get(model)
        self.status.setText("AI 선명화 준비 완료" + (f" · 1메가픽셀 그림 1장에 약 {sp:.2f}초" if sp else ""))
        self.update_ai_info()

    def on_ai_failed(self, text):
        self.edit_btn.setEnabled(True)
        self.ai_chk.setEnabled(True)
        self.bar.setValue(0)
        self.status.setText("AI 선명화 준비 실패")
        if find_esrgan() is None:
            self.ai_chk.blockSignals(True)
            self.ai_chk.setChecked(False)
            self.ai_chk.blockSignals(False)
            set_ai_prefs(on=False)
        QMessageBox.warning(self, APP_TITLE, text)
        self.update_ai_info()

    def build_bottom_card(self):
        card, hl, lay = self._panel(3, "편집 및 저장", "go")
        hl.addStretch(1)
        self.out_label = self._label("", "phs")
        self.out_label.setToolTip("지정한 구간들 중 가장 많이 쓴 비율로 자동으로 정해집니다.")
        hl.addWidget(self.out_label)
        tr = QHBoxLayout()
        tr.setSpacing(8)
        tr.addWidget(self._label("메인화면 자막", "ttl"))
        tr.addWidget(self.title_on)
        tr.addWidget(self.title_edit, 1)
        tr.addWidget(self._label("표시(초)", "sub"))
        tr.addWidget(self.title_secs)
        lay.addLayout(tr)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)
        self.status = self._label("대기 중 (구간을 모두 지정한 뒤 눌러 주세요)", "sub")
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.reset_everything_btn = self._btn("⟲ 전체 초기화", self.reset_everything, "danger")
        self.reset_everything_btn.setToolTip("불러온 영상 · 구간 목록 · 메인화면 자막을 모두 지웁니다.")
        self.reset_everything_btn.setMinimumHeight(42)
        row.addWidget(self.reset_everything_btn)
        row.addStretch(1)
        self.cancel_edit_btn = self._btn("취소", self.cancel_edit, "danger")
        self.cancel_edit_btn.setEnabled(False)
        self.cancel_edit_btn.setMinimumHeight(42)
        row.addWidget(self.cancel_edit_btn)
        self.edit_btn = self._btn("🎬 편집 시작 (MP4 저장)", self.start_edit, "go")
        self.edit_btn.setMinimumHeight(42)
        self.edit_btn.setMinimumWidth(200)
        row.addWidget(self.edit_btn)
        quit_btn = self._btn("종료", self.close, "move")
        quit_btn.setMinimumHeight(42)
        row.addWidget(quit_btn)
        lay.addLayout(row)
        return card

    # ---- 구간 목록 화면 ----
    def rebuild_rows(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.row_widgets = []
        self.row_frames = []
        if self.sel >= len(self.marks.rows):
            self.sel = len(self.marks.rows) - 1
        for i, r in enumerate(self.marks.rows):
            self.rows_layout.addWidget(self._make_row(i, r))
        n = len(self.marks.rows) + 1
        if self.marks.active_index() is None:
            text = f"{n}번 구간: [득점 시작]을 누르면 여기에 추가됩니다"
        else:
            text = f"{n}번 구간: 종료 후 다시 [득점 시작]을 누르면 여기에 추가됩니다"
        ghost = QLabel(text)
        sty(ghost, GHOST)
        ghost.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rows_layout.addWidget(ghost)
        self.rows_layout.addStretch(1)
        self.refresh_marks()
        self.update_crop_ui()
        self.update_stack()
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _row_name(self, i, r):
        if r["active"]:
            return "rowActive"
        return "rowSel" if i == self.sel else "row"

    def _make_row(self, i, r):
        f = ClickFrame()
        f.setObjectName(self._row_name(i, r))
        f.clicked.connect(lambda i=i: self.select_row(i))
        self.row_frames.append(f)
        outer = QVBoxLayout(f)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        self._col_widths(g)
        outer.addLayout(g)

        # 윗줄: 번호 · 자막 내용 · 자막 위치 · 재생 · 삭제
        num = self._btn(str(i + 1), lambda i=i: self.goto_row(i), "num")
        num.setToolTip("누르면 이 구간 시작 위치로 이동합니다")
        num.setFixedWidth(30)
        g.addWidget(num, 0, 0)

        tx = self._edit(r["text"])
        tx.setPlaceholderText("자막 내용 (선택)")
        tx.textChanged.connect(lambda t, i=i: self.set_text(i, t))
        tx.setMinimumWidth(90)            # 창이 좁으면 자막 칸이 먼저 줄어듭니다
        g.addWidget(tx, 0, 1)

        ps = QComboBox()
        ps.addItems(list(POSITIONS.keys()))
        ps.setCurrentText(r["pos"])
        ps.setFixedWidth(112)
        ps.currentTextChanged.connect(lambda t, i=i: self.set_pos(i, t))
        g.addWidget(ps, 0, 2)

        g.addWidget(self._btn("▶", lambda i=i: self.play_row(i), "iconplay"), 0, 3)
        g.addWidget(self._btn("✕", lambda i=i: self.delete_row(i), "icondel"), 0, 4)

        # 아랫줄: 시작 [-0.5][시간][+0.5]   종료 [-0.5][시간][+0.5]   길이
        tl = QHBoxLayout()
        tl.setContentsMargins(30, 0, 0, 0)   # 자막 칸과 왼쪽 선을 맞춤
        tl.setSpacing(3)
        tl.addWidget(self._label("시작", "sub"))
        st = self._edit(fmt_time1(r["start"]))
        st.setFixedWidth(70)
        st.setPlaceholderText("00:00.0")
        st.editingFinished.connect(lambda i=i, e=st: self.edit_time(i, "start", e))
        tl.addWidget(st)
        tl.addSpacing(6)
        en = None
        tl.addWidget(self._label("종료", "sub"))
        if r["active"]:
            lb = QLabel("지정 중…")
            sty(lb, "color:#9A3412;font-weight:700;")
            tl.addWidget(lb)
        else:
            en = self._edit(fmt_time1(r["end"]))
            en.setFixedWidth(70)
            en.setPlaceholderText("00:00.0")
            en.editingFinished.connect(lambda i=i, e=en: self.edit_time(i, "end", e))
            tl.addWidget(en)
        tl.addSpacing(6)
        tl.addSpacing(8)

        ln = QLabel("길이 " + len_text(r))
        ln.setStyleSheet("font-weight:700;")
        tl.addWidget(ln)
        if r.get("cropOn") and r.get("crop") and getattr(self, "ai_chk", None) is not None and self.ai_chk.isChecked():
            badge = QLabel("✨ AI 선명화")
            badge.setObjectName("aibadge")
            tl.addWidget(badge)
        tl.addStretch(1)
        outer.addLayout(tl)

        self.row_widgets.append({"start": st, "end": en, "len": ln})
        return f

    def _nudge_btn(self, text, i, key, delta):
        return self._btn(text, lambda i=i, k=key, d=delta: self.nudge_time(i, k, d), "nudge")

    # ---- 화면 범위(크롭) ----
    def cur_row(self):
        if 0 <= self.sel < len(self.marks.rows):
            return self.marks.rows[self.sel]
        return None

    def src_dims(self):
        if self.info:
            return self.info["width"], self.info["height"]
        return 16, 9

    def eventFilter(self, obj, ev):
        """구간 줄 안쪽(입력칸·버튼 포함)을 누르면 그 구간을 선택합니다."""
        try:
            if ev.type() == QEvent.Type.MouseButtonPress:
                w = obj
                while w is not None and not isinstance(w, ClickFrame):
                    w = w.parent() if hasattr(w, "parent") else None
                if w is not None and w in self.row_frames:
                    self.select_row(self.row_frames.index(w))
        except RuntimeError:
            pass
        return False

    def select_row(self, i):
        if i >= len(self.marks.rows) or i == self.sel:
            return
        self.sel = i
        for k, f in enumerate(self.row_frames):
            f.setObjectName(self._row_name(k, self.marks.rows[k]))
            f.style().unpolish(f)
            f.style().polish(f)
        self.update_crop_ui()
        self.update_stack()

    def update_stack(self):
        """선택한 구간의 범위 사각형을 영상 위에 표시합니다. (재생 전·재생 중·정지 중 모두)"""
        if not self.info:
            return
        r = self.cur_row()
        W, H = self.src_dims()
        self.canvas.set_source(W, H)
        if r and r["cropOn"] and r["crop"]:
            self.canvas.set_crop(r["crop"], r["cropRatio"])
        else:
            self.canvas.set_crop(None, None)

    def update_crop_ui(self):
        self.update_ai_info()
        r = self.cur_row()
        en = bool(r is not None and self.info is not None and self.can_play)
        on = bool(en and r["cropOn"] and r["crop"])
        self._syncing = True
        try:
            self.crop_on.setEnabled(en)
            self.crop_on.setChecked(on)
            self.crop_on.setText(f"{self.sel + 1}번 구간 범위 사용" if r is not None else "구간 범위 사용")
            for name, b in self.ratio_btns.items():
                b.setEnabled(on)
                b.setChecked(on and name == r["cropRatio"])
            zcur = crop_zoom(*self.src_dims(), r["cropRatio"], r["crop"]) if on else None
            for b, zv in zip(self.zoom_btns, (1, 1.5, 2, 3)):
                b.setEnabled(on)
                if b.isCheckable():
                    b.setChecked(bool(on and abs(zcur - zv) < 0.05))
            self.zoom_slider.setEnabled(on)
            self.crop_reset.setEnabled(on)
            self.crop_bar.setObjectName("cropbarOn" if on else "cropbar")
            self.crop_bar.style().unpolish(self.crop_bar)
            self.crop_bar.style().polish(self.crop_bar)
            if on:
                W, H = self.src_dims()
                z = crop_zoom(W, H, r["cropRatio"], r["crop"])
                self.zoom_slider.setValue(int(round(z * 100)))
                self.zoom_label.setText(f"{z:.1f}x")
                self.crop_hint.setText("사각형을 끌어 옮기고, 모서리를 끌어 크기를 바꿉니다.")
            else:
                self.zoom_label.setText("-")
                self.crop_hint.setText("체크하면 이 구간의 화면 일부만 확대해서 저장합니다." if r is not None
                                       else "구간 목록에서 구간을 선택하면 그 구간의 범위를 설정합니다.")
        finally:
            self._syncing = False
        self.update_out_ratio()

    def _crop_apply(self, ratio=None, zoom=None):
        r = self.cur_row()
        if r is None or not r["cropOn"] or not r["crop"]:
            return
        W, H = self.src_dims()
        ratio = ratio or r["cropRatio"]
        zoom = zoom if zoom is not None else crop_zoom(W, H, r["cropRatio"], r["crop"])
        cx, cy = crop_center(r["crop"])
        r["crop"] = crop_make(W, H, ratio, zoom, cx, cy)
        r["cropRatio"] = ratio
        self.update_crop_ui()
        self.update_stack()
        self.canvas.set_crop(r["crop"], r["cropRatio"])

    def on_crop_toggle(self, on):
        if self._syncing:
            return
        r = self.cur_row()
        if r is None or self.info is None:
            return
        r["cropOn"] = bool(on)
        if on and not r["crop"]:
            W, H = self.src_dims()
            r["cropRatio"] = self.out_ratio
            r["crop"] = crop_make(W, H, self.out_ratio, 1.5)
        self.update_crop_ui()
        self.update_stack()
        if getattr(self, "ai_chk", None) is not None and self.ai_chk.isChecked():
            self.rebuild_rows()              # ✨ AI 선명화 표시 갱신

    def on_ratio(self, name):
        self._crop_apply(ratio=name)

    def on_zoom(self, z):
        self._crop_apply(zoom=z)

    def on_slider(self, v):
        if self._syncing:
            return
        self._crop_apply(zoom=v / 100.0)

    def on_crop_reset(self):
        r = self.cur_row()
        if r is None:
            return
        r["cropOn"], r["crop"], r["cropRatio"] = False, None, None
        self.update_crop_ui()
        self.update_stack()

        if getattr(self, "ai_chk", None) is not None and self.ai_chk.isChecked():
            self.rebuild_rows()
    def on_canvas_changed(self):
        r = self.cur_row()
        if r is None or not r["crop"]:
            return
        W, H = self.src_dims()
        z = crop_zoom(W, H, r["cropRatio"], r["crop"])
        self._syncing = True
        try:
            self.zoom_slider.setValue(int(round(z * 100)))
            self.zoom_label.setText(f"{z:.1f}x")
        finally:
            self._syncing = False

    # ---- 편집 로그 저장/불러오기 ----
    def save_log(self):
        if not self.src:
            QMessageBox.information(self, APP_TITLE, "먼저 영상 파일을 선택해 주세요.")
            return
        title = {"on": self.title_on.isChecked(), "text": self.title_edit.text(), "secs": self.title_secs.text()}
        log = build_log(os.path.abspath(self.src), os.path.basename(self.src), self.info, self.marks.rows, title)
        default = os.path.join(get_log_dir() or os.path.dirname(self.src), log_default_name(self.src))
        path, _ = QFileDialog.getSaveFileName(self, "편집 로그 저장", default, "편집 로그 (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=1)
        except OSError as e:
            QMessageBox.critical(self, APP_TITLE, f"로그를 저장하지 못했습니다.\n{e}")
            return
        self.flash("편집 로그를 저장했습니다: " + path)

    def choose_log_dir(self):
        cur = get_log_dir()
        d = QFileDialog.getExistingDirectory(
            self, "로그를 저장할 폴더 선택 (구글 드라이브·OneDrive 폴더를 고르면 자동으로 클라우드에 보관됩니다)", cur)
        if d:
            set_log_dir(d)
            self.flash("로그 폴더를 지정했습니다: " + d)

    def load_log(self):
        if self.worker and self.worker.is_alive():
            QMessageBox.information(self, APP_TITLE, "편집이 진행 중입니다. 끝난 뒤에 불러와 주세요.")
            return
        if not self.ensure_tools():
            return
        path, _ = QFileDialog.getOpenFileName(self, "편집 로그 불러오기", get_log_dir(), "편집 로그 (*.json);;모든 파일 (*.*)")
        if not path:
            return
        try:
            log = read_log(path)
        except EditError as e:
            QMessageBox.critical(self, APP_TITLE, str(e))
            return
        if self.marks.complete_ranges():
            ans = QMessageBox.question(self, APP_TITLE,
                                       "지금 지정한 득점 구간이 로그 내용으로 바뀝니다.\n계속할까요?")
            if ans != QMessageBox.StandardButton.Yes:
                return
            self.marks = Marks()
        vpath = log["video"]["path"]
        if not (vpath and os.path.isfile(vpath)):
            QMessageBox.information(self, APP_TITLE,
                                    f"원본 영상을 찾을 수 없습니다.\n({log['video']['name'] or vpath})\n"
                                    "영상 파일을 직접 선택해 주세요.")
            vpath, _ = QFileDialog.getOpenFileName(
                self, "원본 영상 선택", "", "동영상 (*.mp4 *.mov *.m4v *.mkv *.avi);;모든 파일 (*.*)")
            if not vpath:
                return
        self.load_video(vpath)
        if not self.src or os.path.abspath(self.src) != os.path.abspath(vpath):
            return
        self.marks.rows = [dict(r) for r in clean_log_rows(log["rows"], self.dur)]
        self.sel = -1
        t = log["title"]
        self.title_on.setChecked(t["on"])
        self.toggle_title(t["on"])
        self.title_edit.setText(t["text"])
        self.title_secs.setText(t["secs"])
        self.rebuild_rows()
        note = f"편집 로그를 불러왔습니다. (구간 {len(self.marks.rows)}개)"
        if log["video"]["duration"] and abs(log["video"]["duration"] - self.dur) > 1.0:
            note += " 주의: 로그에 기록된 영상 길이와 다릅니다. 같은 영상인지 확인해 주세요."
        self.flash(note)

    def update_out_ratio(self):
        """저장 영상 크기를 구간들의 범위 비율에서 자동으로 정합니다."""
        name, cnt, total = auto_out_ratio(self.marks.rows)
        self.out_ratio = name
        if self.info:
            ow, oh = output_size(self.info["width"], self.info["height"], name)
            size = f" ({ow}x{oh})"
        else:
            size = ""
        extra = f" · {total}개 중 {cnt}개" if total else ""
        self.out_label.setText(f"저장 영상 크기(자동): {name}{size}{extra}")

    def _reset_busy(self):
        if self.worker and self.worker.is_alive():
            QMessageBox.information(self, APP_TITLE, "편집이 진행 중입니다. 끝난 뒤에 초기화해 주세요.")
            return True
        return False

    def _clear_rows(self):
        self.play_until = None
        if self.can_play:
            self.player.pause()
        self.marks = Marks()
        self.sel = -1
        self.bar.setValue(0)

    def reset_list(self):
        """목록 초기화: 득점 구간(자막·범위 포함)만 지웁니다. 영상·메인화면 자막은 그대로."""
        if self._reset_busy():
            return
        if QMessageBox.question(self, APP_TITLE, "득점 구간 목록(자막·범위 포함)을 모두 지울까요?\n"
                                "불러온 영상과 메인화면 자막은 그대로 둡니다.") != QMessageBox.StandardButton.Yes:
            return
        self._clear_rows()
        self.flash("득점 구간 목록을 초기화했습니다.")
        self.rebuild_rows()

    def reset_everything(self):
        """전체 초기화: 불러온 영상 · 구간 목록 · 메인화면 자막을 모두 처음 상태로."""
        if self._reset_busy():
            return
        if QMessageBox.question(self, APP_TITLE, "불러온 영상, 득점 구간 목록, 메인화면 자막을 모두 지우고\n"
                                "처음 상태로 되돌릴까요?") != QMessageBox.StandardButton.Yes:
            return
        self._clear_rows()
        self.title_edit.clear()
        self.title_on.setChecked(False)
        self.toggle_title(False)
        self.title_secs.setText("3")
        self.clear_video()
        self.flash("전체 초기화했습니다. (영상 포함)")
        self.rebuild_rows()

    reset_all = reset_everything

    def clear_video(self):
        """불러온 영상을 내리고 처음 화면으로 되돌립니다."""
        self.player.stop()
        self.player.setSource(QUrl())
        self.src = None
        self.info = None
        self.dur = 0.0
        self.can_play = False
        self.canvas.set_crop(None, None)
        self.canvas.set_source(16, 9)
        self.seek_bar.set_duration(0)
        self.seek_bar.set_segments([], None)
        self.placeholder.setText("영상 파일을 여기로 끌어다 놓거나\n[영상 파일 선택]을 눌러 주세요.")
        self.stack.setCurrentIndex(0)
        self.info_label.setText("선택된 영상이 없습니다.")
        self.pos_label.setText("00:00.0 / 00:00.0")

    def on_bulk_pos(self, idx):
        """풀다운에서 고른 자막 위치를 모든 득점 구간에 한 번에 적용"""
        if idx <= 0:
            return
        pos = self.bulk_pos.itemText(idx)
        self.bulk_pos.setCurrentIndex(0)
        if not self.marks.rows:
            self.flash("자막 위치를 바꿀 득점 구간이 없습니다.")
            return
        for r in self.marks.rows:
            r["pos"] = pos
        self.flash(f"모든 구간({len(self.marks.rows)}개)의 자막 위치를 '{pos}'(으)로 바꿨습니다.")
        self.rebuild_rows()

    def toggle_title(self, on):
        """메인화면 자막 사용 체크: 꺼져 있으면 자막 내용·표시(초) 입력 불가."""
        self.title_edit.setEnabled(on)
        self.title_secs.setEnabled(on)
        if on:
            self.title_secs.setText("3")      # 기본 3초
            self.title_edit.setFocus()
        if hasattr(self, "summary"):
            self.refresh_marks()

    def nudge_time(self, i, key, delta):
        if i >= len(self.marks.rows):
            return
        try:
            self.marks.nudge(i, key, delta, self.dur)
            self.flash("")
        except MarkError as e:
            self.flash(str(e))
        self.sync_row(i)

    def sync_row(self, i):
        r = self.marks.rows[i]
        w = self.row_widgets[i]
        w["start"].setText(fmt_time1(r["start"]))
        if w["end"] is not None:
            w["end"].setText(fmt_time1(r["end"]))
        w["len"].setText("길이 " + len_text(r))
        self.refresh_marks()

    def edit_time(self, i, key, edit):
        if i >= len(self.marks.rows):
            return
        txt = edit.text().strip()
        try:
            try:
                val = None if not txt else parse_time(txt)
            except ValueError:
                raise MarkError("시간은 12:30 또는 1:02:30 처럼 입력해 주세요.")
            self.marks.set_time(i, key, val)
        except MarkError as e:
            self.flash(str(e))
        self.sync_row(i)

    def set_text(self, i, text):
        if i < len(self.marks.rows):
            self.marks.rows[i]["text"] = text

    def set_pos(self, i, pos):
        if i < len(self.marks.rows):
            self.marks.rows[i]["pos"] = pos

    def goto_row(self, i):
        self.select_row(i)
        s = self.marks.rows[i]["start"]
        if s is None or not self.can_play:
            return
        self.seek(s)

    def play_row(self, i):
        r = self.marks.rows[i]
        if not self.can_play:
            self.flash("영상을 앱 안에서 재생할 수 없는 상태입니다.")
            return
        if r["start"] is None or r["end"] is None or r["end"] <= r["start"]:
            self.flash("시작과 종료 시간이 올바른 구간만 재생할 수 있습니다.")
            return
        self.seek(r["start"])
        self.play_until = r["end"]
        self.player.play()

    def delete_row(self, i):
        if i < len(self.marks.rows):
            self.marks.delete(i)
            if self.sel >= len(self.marks.rows):
                self.sel = len(self.marks.rows) - 1
            self.rebuild_rows()

    def add_blank(self):
        self.marks.add_blank()
        self.rebuild_rows()

    def flash(self, text):
        self.msg.setText(text)

    def refresh_marks(self):
        self.update_out_ratio()
        self.update_ai_info()
        ranges = self.marks.complete_ranges()
        ai = self.marks.active_index()
        active = None
        if ai is not None:
            active = (self.marks.rows[ai]["start"], self.cur_sec())
        self.seek_bar.set_segments(ranges, active)
        if ai is not None:
            sty(self.pill, PILL_ACTIVE)
            self.pill.setText(f"{ai + 1}번 구간 지정 중 · 시작 {fmt_time1(self.marks.rows[ai]['start'])}"
                              " (득점이 끝나면 [득점 종료]를 누르세요)")
        else:
            sty(self.pill, PILL_IDLE)
            self.pill.setText("구간 지정 대기 · 득점 장면이 시작되면 [득점 시작]을 누르세요")
        self.start_btn.setEnabled(self.can_play and ai is None)
        self.end_btn.setEnabled(self.can_play and ai is not None)
        self.cancel_mark_btn.setEnabled(ai is not None)
        total = sum(e - s for s, e in ranges)
        try:
            ts = float(self.title_secs.text())
        except ValueError:
            ts = 0.0
        extra = ts if (self.title_on.isChecked() and self.title_edit.text().strip() and ts > 0) else 0.0
        self.summary.setText(f"득점 구간 {len(ranges)}개 완료 · 합계 {total:.0f}초 + 메인화면 {extra:.0f}초"
                             f" = 전체 약 {total + extra:.0f}초")

    # ---- 재생 ----
    def cur_sec(self):
        return self.player.position() / 1000.0

    def seek(self, sec):
        sec = max(0.0, min(float(sec), self.dur if self.dur > 0 else float(sec)))
        self.play_until = None
        self.player.setPosition(int(sec * 1000))
        self.on_position(int(sec * 1000))

    def seek_rel(self, delta):
        if self.can_play:
            self.seek(self.cur_sec() + delta)

    def toggle_play(self):
        if not self.can_play:
            return
        self.play_until = None
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def play(self):
        if not self.can_play:
            return
        self.play_until = None
        self.player.play()

    def stop(self):
        """정지: 영상을 멈추고, 현재 위치는 그대로 둡니다."""
        if not self.can_play:
            return
        self.play_until = None
        self.player.pause()

    def on_state(self, state):
        self.update_stack()

    def on_speed(self, text):
        try:
            self.player.setPlaybackRate(float(text.rstrip("x")))
        except ValueError:
            pass

    def on_position(self, ms):
        sec = ms / 1000.0
        self.seek_bar.set_position(sec)
        self.pos_label.setText(f"{fmt_time1(sec)} / {fmt_time1(self.dur)}")
        ai = self.marks.active_index()
        if ai is not None:
            self.seek_bar.set_segments(self.marks.complete_ranges(), (self.marks.rows[ai]["start"], sec))
        if self.play_until is not None and sec >= self.play_until:
            self.play_until = None
            self.player.pause()

    def on_duration(self, ms):
        if ms > 0:
            self.dur = ms / 1000.0
            self.seek_bar.set_duration(self.dur)
            self.pos_label.setText(f"{fmt_time1(self.cur_sec())} / {fmt_time1(self.dur)}")

    def on_error(self, _error, message):
        self.can_play = False
        self.placeholder.setText(
            "이 영상은 프로그램 안에서 재생할 수 없습니다.\n"
            f"({message})\n\n"
            "오른쪽 목록의 [+ 구간 직접 추가]로 시간을 직접 입력해도 편집은 할 수 있습니다.")
        self.stack.setCurrentIndex(0)
        self.refresh_marks()

    # ---- 구간 지정 버튼 ----
    def begin_mark(self):
        if not self.can_play:
            self.flash("먼저 재생 가능한 영상을 선택해 주세요.")
            return
        try:
            self.marks.begin(self.cur_sec())
        except MarkError as e:
            self.flash(str(e))
            return
        self.flash("")
        self.sel = len(self.marks.rows) - 1
        self.rebuild_rows()

    def end_mark(self):
        try:
            i = self.marks.finish(self.cur_sec())
        except MarkError as e:
            self.flash(str(e))
            return
        self.flash(f"{i + 1}번 구간을 지정했습니다. 다음 득점 장면에서 [득점 시작]을 누르세요.")
        self.sel = i
        self.rebuild_rows()

    def cancel_mark(self):
        if self.marks.cancel():
            self.flash("지정 중이던 구간을 취소했습니다.")
            self.rebuild_rows()

    # ---- 영상 선택 ----
    def show_tool_status(self):
        if self.ffmpeg and self.ffprobe:
            self.status.setText(f"대기 중 · FFmpeg 확인됨: {self.ffmpeg}")
        else:
            self.status.setText("FFmpeg를 아직 찾지 못했습니다. (영상을 선택하면 안내합니다)")

    def ensure_tools(self):
        if self.ffmpeg and self.ffprobe:
            return True
        self.ffmpeg, self.ffprobe = find_ffmpeg_pair()   # 방금 설치했을 수 있으니 다시 찾기
        if self.ffmpeg and self.ffprobe:
            self.show_tool_status()
            return True
        lines = ["FFmpeg를 찾지 못했습니다.", "",
                 f"ffmpeg.exe: {'찾음' if self.ffmpeg else '못 찾음'}",
                 f"ffprobe.exe: {'찾음' if self.ffprobe else '못 찾음'}", ""]
        if admin_install_suspected():
            lines += ["관리자 권한으로 설치된 FFmpeg 폴더가 있는 것 같습니다.",
                      "일반 권한으로 실행한 프로그램은 그 폴더를 열 수 없을 수 있습니다.", ""]
        lines += ["해결 방법:",
                  "1) 명령 프롬프트(cmd)를 새로 열고  where ffmpeg  를 입력하면 설치 위치가 나옵니다.",
                  "2) 아래 [Yes]를 눌러 그 ffmpeg.exe 파일을 직접 지정해 주세요. (한 번만 지정하면 기억합니다)"]
        ans = QMessageBox.question(self, APP_TITLE, "\n".join(lines))
        if ans != QMessageBox.StandardButton.Yes:
            self.show_tool_status()
            return False
        local = os.environ.get("LOCALAPPDATA", "")
        links = os.path.join(local, "Microsoft", "WinGet", "Links") if local else ""
        start = links if links and os.path.isdir(links) else ""
        path, _ = QFileDialog.getOpenFileName(self, "ffmpeg.exe 선택", start,
                                              "FFmpeg (ffmpeg.exe ffprobe.exe);;모든 파일 (*.*)")
        if not path:
            return False
        folder = os.path.dirname(path)
        ff, fp = os.path.join(folder, _exe("ffmpeg")), os.path.join(folder, _exe("ffprobe"))
        if not (os.path.isfile(ff) and os.path.isfile(fp)):
            QMessageBox.warning(self, APP_TITLE,
                                "선택한 폴더에 ffmpeg.exe와 ffprobe.exe가 모두 있어야 합니다.\n"
                                f"선택한 폴더: {folder}")
            return False
        self.ffmpeg, self.ffprobe = ff, fp
        remember_ffmpeg(ff)
        self.show_tool_status()
        return True

    def choose_video(self):
        if not self.ensure_tools():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "시합 영상 선택", "",
            "동영상 (*.mp4 *.mov *.m4v *.mkv *.avi);;모든 파일 (*.*)")
        if path:
            self.load_video(path)

    def load_video(self, path, note=""):
        """파일 선택 버튼과 끌어다 놓기가 함께 쓰는 영상 불러오기"""
        if not self.ensure_tools():
            return
        if self.worker and self.worker.is_alive():
            QMessageBox.information(self, APP_TITLE, "편집이 진행 중입니다. 끝난 뒤에 영상을 바꿔 주세요.")
            return
        try:
            info = probe(self.ffprobe, path)
        except EditError as e:
            QMessageBox.critical(self, APP_TITLE, str(e))
            return
        if self.marks.complete_ranges():
            ans = QMessageBox.question(self, APP_TITLE,
                                       "새 영상을 선택하면 지금까지 지정한 득점 구간이 모두 지워집니다.\n계속할까요?")
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.src, self.info = path, info
        self.dur = info["duration"]
        self.marks = Marks()
        self.sel = -1
        self.canvas.set_source(info["width"], info["height"])
        self.canvas.set_crop(None, None)
        self.flash(note)
        self.seek_bar.set_duration(self.dur)
        self.can_play = True
        self.play_until = None
        self.placeholder.setText("영상을 불러오는 중입니다...")
        self.stack.setCurrentIndex(1)
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.pause()
        text = (f"{os.path.basename(path)} · {info['width']}x{info['height']} · {fps_label(info['fps'])} fps · "
                f"{fmt_time(info['duration'])} · {info['codec']}")
        if info["transfer"] in HDR_TRANSFERS:
            if has_encoder(self.ffmpeg, "libx265"):
                text += " · HDR (원본 색상 그대로 HEVC로 저장)"
            else:
                if self.tonemap_ok is None:
                    self.tonemap_ok = has_tonemap_filters(self.ffmpeg)
                text += (" · HDR (이 FFmpeg에는 HEVC 인코더가 없어 일반 색상으로 변환해 저장)"
                         if self.tonemap_ok else " · HDR (HEVC 인코더·변환 필터가 없어 색이 흐릴 수 있음)")
        self.info_label.setText(text)
        self.on_position(0)
        self.rebuild_rows()

    # ---- 파일 끌어다 놓기 ----
    def _dropped_files(self, mime):
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]

    def dragEnterEvent(self, ev):
        if self._dropped_files(ev.mimeData()):
            ev.acceptProposedAction()
            self.flash("여기에 놓으면 영상을 불러옵니다.")
        else:
            ev.ignore()

    def dragMoveEvent(self, ev):
        if self._dropped_files(ev.mimeData()):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragLeaveEvent(self, ev):
        self.flash("")

    def dropEvent(self, ev):
        files = self._dropped_files(ev.mimeData())
        ev.acceptProposedAction()
        self.flash("")
        videos = [f for f in files if f.lower().endswith(VIDEO_EXTS)]
        if not videos:
            self.flash("동영상 파일(mp4, mov 등)만 불러올 수 있습니다.")
            return
        tab = self.tabs.currentIndex()
        if tab == 1:
            QTimer.singleShot(0, lambda p=videos[0]: self.cut_tab.load_video(p))
            return
        if tab == 2:
            QTimer.singleShot(0, lambda v=videos: self.merge_tab.add_paths(v))
            return
        note = "여러 파일 중 첫 번째 영상만 불러왔습니다." if len(files) > 1 else ""
        # 탐색기 쪽 끌기 동작이 끝난 뒤에 불러오도록 한 박자 늦춥니다.
        QTimer.singleShot(0, lambda p=videos[0], n=note: self.load_video(p, n))

    # ---- 편집 ----
    def start_edit(self):
        if self.worker and self.worker.is_alive():
            return
        if not self.ensure_tools():
            return
        if not self.src:
            QMessageBox.information(self, APP_TITLE, "먼저 영상 파일을 선택해 주세요.")
            return
        try:
            segs = collect_segments(self.marks.rows, self.dur)
        except ValueError as e:
            QMessageBox.warning(self, APP_TITLE, str(e))
            return
        if not segs:
            QMessageBox.warning(self, APP_TITLE, "득점 구간을 1개 이상 지정해 주세요.")
            return
        title = None
        t_text = self.title_edit.text().strip()
        if self.title_on.isChecked() and t_text:
            try:
                secs = float(self.title_secs.text())
            except ValueError:
                QMessageBox.warning(self, APP_TITLE, "메인화면 표시 시간(초)을 숫자로 입력해 주세요.")
                return
            if secs < 0:
                QMessageBox.warning(self, APP_TITLE, "메인화면 표시 시간은 0 이상이어야 합니다.")
                return
            if secs > 0:   # 0초이면 메인화면 없이 바로 시작
                title = {"text": t_text, "secs": secs}
        if self.tonemap_ok is None:
            self.tonemap_ok = has_tonemap_filters(self.ffmpeg)
        ai = None
        if self.ai_chk.isChecked() and self.ai_crop_segments():
            if self.ai_busy():
                QMessageBox.information(self, APP_TITLE, "AI 선명화 준비가 끝난 뒤 다시 눌러 주세요.")
                return
            exe = find_esrgan()
            if exe is None:
                QMessageBox.warning(self, APP_TITLE, "AI 선명화 도구가 설치되어 있지 않습니다.\n"
                                    "[사용]을 껐다가 다시 켜서 설치하거나, 끄고 저장해 주세요.")
                return
            ai = {"exe": exe, "model": self.ai_model()}
            est = ai_estimate(self.ai_crop_segments(), self.info, ai["model"])
            if est is not None and est > 600:
                ans = QMessageBox.question(self, APP_TITLE, f"AI 선명화에 약 {fmt_eta(est)} 걸릴 것으로 보입니다.\n"
                                           "계속할까요? (중간에 [취소]할 수 있습니다)")
                if ans != QMessageBox.StandardButton.Yes:
                    return
        default = os.path.join(os.path.dirname(self.src), "하이라이트.mp4")
        out, _ = QFileDialog.getSaveFileName(self, "저장할 위치와 이름", default, "MP4 동영상 (*.mp4)")
        if not out:
            return
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        if os.path.abspath(out) == os.path.abspath(self.src):
            QMessageBox.warning(self, APP_TITLE, "원본 영상과 같은 이름으로는 저장할 수 없습니다.")
            return
        self.player.pause()
        self.cancel_event.clear()
        self.bar.setValue(0)
        self.set_running(True)
        self.worker = threading.Thread(target=self.work, args=(segs, title, out, self.out_ratio, ai), daemon=True)
        self.worker.start()

    def work(self, segs, title, out, out_ratio=DEFAULT_RATIO, ai=None):
        try:
            make_highlight(self.ffmpeg, self.src, self.info, segs, title, self.font_path, out,
                           lambda d, t, m: self.bridge.progress.emit(d, t, m),
                           self.cancel_event, self.tonemap_ok, True, out_ratio, ai=ai)
            self.bridge.done.emit(out)
        except Cancelled:
            self.bridge.cancelled.emit()
        except EditError as e:
            self.bridge.failed.emit(str(e))
        except Exception:
            self.bridge.failed.emit("예상하지 못한 오류가 발생했습니다.\n\n" + traceback.format_exc()[-800:])

    def set_running(self, running):
        self.edit_btn.setEnabled(not running)
        self.cancel_edit_btn.setEnabled(running)

    def cancel_edit(self):
        self.cancel_event.set()

    def on_progress(self, done, total, text):
        self.bar.setValue(int(100.0 * done / max(total, 1)))
        self.status.setText(text)

    def on_done(self, path):
        self.set_running(False)
        self.bar.setValue(100)
        self.status.setText("완료: " + path)
        ans = QMessageBox.question(self, APP_TITLE, f"저장했습니다.\n{path}\n\n저장 폴더를 열까요?")
        if ans == QMessageBox.StandardButton.Yes and IS_WIN:
            os.startfile(os.path.dirname(path))

    def on_failed(self, text):
        self.set_running(False)
        self.status.setText("오류가 발생했습니다.")
        QMessageBox.critical(self, APP_TITLE, text)

    def on_cancelled(self):
        self.set_running(False)
        self.status.setText("취소했습니다.")

    def closeEvent(self, ev):
        self.cancel_event.set()
        self.player.stop()
        self.cut_tab.shutdown()
        self.merge_tab.shutdown()
        super().closeEvent(ev)


def main():
    if IS_WIN:      # 작업표시줄에서 파이썬 아이콘 대신 이 프로그램 아이콘이 보이도록
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("basketball.highlight.editor.app")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())

    def hook(exc_type, exc, tb):
        msg = "".join(traceback.format_exception(exc_type, exc, tb))[-900:]
        try:
            QMessageBox.critical(None, APP_TITLE, "오류가 발생했습니다.\n\n" + msg)
        except Exception:
            pass
    sys.excepthook = hook

    if "Malgun Gothic" in QFontDatabase.families():
        app.setFont(QFont("Malgun Gothic", 10))
    apply_theme(get_theme())
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
