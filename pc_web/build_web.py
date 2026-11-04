"""WEB 버전(highlight_editor_web.pyw)을 조각 파일로 다시 만듭니다.

WEB = web_src/head.py + engine_old.py 앞부분 + PC 버전의 엔진 부분 + PAGE(web_src/page.html) + web_src/tail.py
엔진(영상 처리)은 PC 버전(highlight_editor_qt.pyw)과 같은 코드를 씁니다.
실행:  python build_web.py
"""
import os
import py_compile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "web_src")


def read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


q = read(HERE, "highlight_editor_qt.pyw")
old = read(SRC, "engine_old.py")
head, tail, page = read(SRC, "head.py"), read(SRC, "tail.py"), read(SRC, "page.html")
qeng = q[q.index("POSITIONS = {"):q.index("# ----------------------------------------------------------------------\n# 화면(GUI)")]
oldhead = old[:old.index("POSITIONS = {")]
assert "'''" not in page, "page.html 안에 ''' (작은따옴표 3개)를 쓰면 안 됩니다."
out = os.path.join(HERE, "highlight_editor_web.pyw")
with open(out, "w", encoding="utf-8") as f:
    f.write(head + oldhead + qeng + "\n\nPAGE = r'''" + page + "'''\n\n" + tail)
py_compile.compile(out, doraise=True)
print("만들었습니다:", out)
