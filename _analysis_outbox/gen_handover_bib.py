# -*- coding: utf-8 -*-
"""生成交接用 64 条题录 bib（handover/references_64_20260902.bib）。

- 门禁与 /api/export/bibtex 一致（approved + 未隔离）
- 引用键 ref01–ref64 对应《64 篇文献清单》序号，注释行含库内 work_id
- arXiv 条目缺 url 时由 arxiv_id 派生补齐；ref01 机构规范为 DSIT
- 校验：条目数、键唯一、逐条括号配平、垃圾值零残留
可重复运行（幂等，覆盖生成）。
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.export_format import work_to_bibtex

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'handover' / 'references_64_20260902.bib'
BS = chr(92)

HEADER = (
    "% ============================================================================\n"
    "% 文献库交接题录 · 64 条（来源：literature_library / literature.sqlite）\n"
    "% 生成日期：2026-09-02   生成方式：api/export_format.work_to_bibtex + 导出门禁过滤\n"
    "% 门禁：metadata_extractions.review_status='approved' 且未隔离（与 /api/export/bibtex 一致）\n"
    "% 引用键：ref01-ref64，对应《64 篇文献清单》序号；每条上方注释含库内 work_id 可回溯\n"
    "% 约定：arXiv 预印本 = @article + journal={arXiv preprint} + eprint；报告/标准无卷期页属正常\n"
    "% 特殊条目：ref25 期号实为 12（57(12):7893-7906，清单原 57(1) 有误）；\n"
    "%           ref42 pages=e39116 为 PLOS 文章号；ref44 现题 VESTA（原 ForesightSafety-SAGE 改名）；\n"
    "%           ref01 以未隔离 arXiv 副本（2602.21012）为准，署名 Bengio（主席），机构 DSIT\n"
    "% ============================================================================\n\n"
)


def braces_balanced(entry: str) -> bool:
    depth, i = 0, 0
    esc = BS
    while i < len(entry):
        c = entry[i]
        if c == esc:
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        if depth < 0:
            return False
        i += 1
    return depth == 0


def main() -> None:
    conn = sqlite3.connect(str(ROOT / 'literature.sqlite'))
    conn.row_factory = sqlite3.Row
    final = json.loads((ROOT / '_analysis_outbox' / 'verify_64_final.json').read_text(encoding='utf-8'))
    idmap = {int(no): info['id'] for no, info in final['works'].items()}
    idmap.update({12: 'W-sha-50735b9ca01b', 18: 'W-sha-29ffcf0b387a', 42: 'W-sha-af2c9c70330d',
                  60: 'W-sha-d94638d0e14f', 1: 'W-arxiv-2602.21012'})

    chunks, keys = [HEADER], []
    for no in range(1, 65):
        wid = idmap[no]
        w = dict(conn.execute("SELECT w.* FROM works w WHERE w.id=?", (wid,)).fetchone())
        ax = (w.get('arxiv_id') or '').strip()
        m = re.match(r'^(\d{4}\.\d{4,5})', ax)
        if m and not (w.get('url') or '').strip():
            w['url'] = f"https://arxiv.org/abs/{m.group(1)}"
        bib = work_to_bibtex(w)
        bib = bib.replace('{{{', '{{').replace('}}}', '}}')
        key = f"ref{no:02d}"
        bib = re.sub(r'^(@\w+)\{W-[^,]+,', rf'\1{{{key},', bib, count=1)
        if key == 'ref01':
            bib = bib.replace('institution = {International AI Safety Report}',
                              'institution = {Department for Science, Innovation and Technology (DSIT)}')
        assert braces_balanced(bib), f"{key} braces unbalanced"
        short = re.sub(r'\s+', ' ', (w.get('title') or ''))[:70]
        chunks.append(f"% [{no:02d}] {short}\n%     library: {wid}\n{bib}\n")
        keys.append(key)
    conn.close()

    out = ''.join(chunks)
    entries = re.findall(r'^@\w+\{', out, re.M)
    junk = [j for j in ('Administrator', 'SoWise', '[object Object]', 'Anonymous') if j in out]
    assert len(entries) == 64 and len(set(keys)) == 64 and not junk, (len(entries), junk)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(out, encoding='utf-8')
    print(f"生成 {OUT}：{len(entries)} 条，逐条括号配平通过，键唯一，垃圾值：无")


if __name__ == '__main__':
    main()
