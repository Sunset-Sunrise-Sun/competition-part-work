"""Export maintained Markdown to a self-contained, printable discussion document."""
from pathlib import Path
import html
import markdown

root = Path(__file__).resolve().parents[1]
files = ["冲刺分工_2026-10-29.md", "IMPLEMENTATION_2026-10-21.md", "ACCEPTANCE_CHECKLIST.md", "方案分析.md", "VISION_DEMOS_REVIEW.md", "ARCHITECTURE.md", "ROADMAP.md", "TASKS.md", "EVALUATION.md", "API.md", "PRIVACY.md", "SETUP.md", "DEPENDENCIES.md", "SOURCES.md", "ADR.md", "VALIDATION.md"]
sections = []
links = []
for i, filename in enumerate(files):
    text = (root / "docs" / filename).read_text(encoding="utf-8")
    title = text.splitlines()[0].lstrip("# ")
    links.append(f'<a href="#doc-{i}">{html.escape(title)}</a>')
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    sections.append(f'<section id="doc-{i}">{body}</section>')
style = """
*{box-sizing:border-box}body{margin:0;font-family:'Segoe UI','Microsoft YaHei',sans-serif;background:#f3f5ef;color:#284236;line-height:1.85}aside{position:fixed;width:250px;padding:30px 22px;height:100vh;overflow:auto;background:#203f32;color:#e6efdc}aside strong{font-size:25px}aside small{display:block;color:#b6c7a6;margin:8px 0 25px}aside a{display:block;padding:9px 0;color:#c8d6bd;text-decoration:none;font-size:12px}main{margin-left:250px;padding:45px;max-width:1250px}section{background:#fffef8;border:1px solid #e0e6d8;border-radius:14px;padding:34px;margin-bottom:30px;scroll-margin-top:15px}h1{font-size:27px;line-height:1.5}h2{font-size:21px;margin-top:32px}h3{font-size:16px}p,li{font-size:14px}table{border-collapse:collapse;width:100%;font-size:12px;display:block;overflow:auto}th,td{border:1px solid #dce4d2;padding:10px;vertical-align:top}th{background:#edf2e4;text-align:left}pre{background:#eef2e8;padding:18px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}code{font-family:Consolas,monospace}a{color:#527746}blockquote{border-left:3px solid #91a573;padding-left:16px}button{background:#446646;color:white;border:0;border-radius:7px;padding:10px 16px;cursor:pointer;margin-bottom:20px}@media(max-width:800px){aside{position:static;width:auto;height:auto}main{margin:0;padding:15px}section{padding:20px}}@media print{aside,button{display:none}main{margin:0;padding:0;max-width:none}body{background:white}section{border:0;padding:0;break-before:page}section:first-of-type{break-before:auto}h1,h2,h3{break-after:avoid}tr{break-inside:avoid}a{color:inherit}pre{white-space:pre-wrap}@page{size:A4;margin:18mm}}
"""
document = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LocalFit · 方案与团队交流文档</title><style>' + style + '</style></head><body><aside><strong>LocalFit Agent</strong><small>本地健身教练 · 团队交流文档<br>2026-10-21 / v0.2 基线</small>' + ''.join(links) + '</aside><main><button onclick="window.print()">打印 / 保存为 PDF</button>' + ''.join(sections) + '</main></body></html>'
(root / "docs" / "展示文档.html").write_text(document, encoding="utf-8")
print(f"Exported {len(files)} documents to docs/展示文档.html")
