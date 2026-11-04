"""WEB 버전 화면 점검: 서버를 띄우고 브라우저로 탭①②③을 라이트·다크로 캡처합니다.

필요: pip install playwright && playwright install chromium,  PATH에 ffmpeg/ffprobe
실행:  python tests/test_web.py   →  tests/out/*.png 생성
파일 선택 창은 test.webm 을 고른 것으로 바꿔치기합니다.
"""
import importlib.machinery
import importlib.util
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

ld = importlib.machinery.SourceFileLoader("hw", os.path.join(ROOT, "highlight_editor_web.pyw"))
spec = importlib.util.spec_from_loader("hw", ld)
hw = importlib.util.module_from_spec(spec)
ld.exec_module(hw)
hw.SETTINGS_FILE = os.path.join(OUT, "settings.json")
hw.load_tools()
hw._dialog = lambda *a, **k: os.path.join(HERE, "test.webm")
srv = hw.ThreadingHTTPServer(("127.0.0.1", 0), hw.Handler)
srv.daemon_threads = True
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1600, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"http://127.0.0.1:{port}/")
    pg.click("[data-th=light]")
    pg.click("#pickBtn")
    pg.wait_for_timeout(1500)
    pg.click("#startBtn"); pg.wait_for_timeout(300)
    pg.click("[data-seek='5']"); pg.wait_for_timeout(300)
    pg.click("#endBtn"); pg.wait_for_timeout(300)
    pg.click("#list .item"); pg.check("#cropOn")
    pg.click("button.spd[data-v='1.5x']")
    assert pg.evaluate("document.getElementById('vid').playbackRate") == 1.5
    for theme in ("light", "dark"):
        pg.click(f"[data-th={theme}]")
        for tab in (1, 2, 3):
            pg.click(f"[data-tab='{tab}']"); pg.wait_for_timeout(300)
            pg.screenshot(path=os.path.join(OUT, f"tab{tab}_{theme}.png"))
    b.close()
print("페이지 오류:", errs or "없음", "/ 캡처:", OUT)
