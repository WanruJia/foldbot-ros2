#!/usr/bin/env python3
"""把 dashboard/progress.json 的最新内容嵌入 index.html 的离线快照块。

用法: python3 dashboard/inline.py
每次更新 progress.json 后运行一次，保证双击打开 index.html (file://)
时也能看到最新数据；联网/本地服务打开时仍优先用 fetch 读 progress.json。
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML = HERE / "index.html"
DATA = HERE / "progress.json"

TAG_RE = re.compile(
    r'(<script id="progress-embedded" type="application/json">\s*).*?(\s*</script>)',
    re.DOTALL,
)


def main():
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    # 防 HTML 解析器提前结束 script 块
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = HTML.read_text(encoding="utf-8")
    if 'id="progress-embedded"' not in html:
        print("index.html 缺少 progress-embedded 快照块，未改动", file=sys.stderr)
        sys.exit(1)
    html2 = TAG_RE.sub(lambda m: m.group(1) + blob + m.group(2), html, count=1)
    HTML.write_text(html2, encoding="utf-8")
    # 自检：嵌入的 JSON 必须能解析 (\/ 是合法 JSON 转义)
    json.loads(blob)
    print(f"已嵌入 {DATA.name} (updated={payload.get('updated')}) 到 {HTML.name}")


if __name__ == "__main__":
    main()
