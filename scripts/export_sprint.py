"""Export the maintained sprint Markdown as a standalone printable HTML."""
from pathlib import Path
import markdown

root = Path(__file__).resolve().parents[1]
source = root / "docs/冲刺分工_2026-10-29.md"
style = """
body{font-family:'Segoe UI','Microsoft YaHei',sans-serif;color:#253f35;background:#f3f5ef;line-height:1.85;margin:0}main{max-width:1320px;margin:35px auto;padding:38px;background:#fffef9;border:1px solid #dfe7d8;border-radius:14px}h1{font-size:27px}h2{font-size:21px;margin-top:34px}p,li{font-size:14px}table{width:100%;border-collapse:collapse;font-size:12px;margin:18px 0}th,td{border:1px solid #d9e1d2;padding:11px;vertical-align:top}th{background:#eaf0e1;text-align:left}code{background:#f0f3eb;padding:2px 4px;overflow-wrap:anywhere}a{color:#427350}button{background:#28513e;color:white;border:0;padding:12px 18px;border-radius:7px;cursor:pointer}@media(max-width:850px){main{margin:10px;padding:18px}table{display:block;overflow:auto}th,td{min-width:100px}}@media print{body{background:white}main{margin:0;padding:0;border:0}button{display:none}h1,h2{break-after:avoid}tr{break-inside:avoid}table{font-size:10px}th,td{padding:6px}@page{size:A4 landscape;margin:13mm}}
"""
body = markdown.markdown(source.read_text(encoding="utf-8"), extensions=["tables", "fenced_code", "sane_lists"])
target = source.with_suffix(".html")
target.write_text('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LocalFit 10月29日冲刺分工</title><style>' + style + '</style></head><body><main><button onclick="window.print()">打印 / 保存为 PDF</button>' + body + '</main></body></html>',encoding="utf-8")
print("Exported sprint HTML")
