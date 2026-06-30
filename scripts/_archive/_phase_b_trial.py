"""P3.5 Phase B 一次性试跑脚本（不入 VCS，scripts/_*.py 被 gitignore）。

对 3 篇 reward-hacking 样本用官网 cloud API 重解析到**隔离目录** _cloud_trial/，
绝不覆盖现有 content.md。然后做新旧比对 + llm_judge 质量裁判比对，写报告。

用法：python scripts/_phase_b_trial.py
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

LIBRARY_ROOT = Path(__file__).resolve().parents[1]
PARSER_ROOT = LIBRARY_ROOT / "parser"
sys.path.insert(0, str(PARSER_ROOT))
sys.path.insert(0, str(LIBRARY_ROOT / "scripts"))

SAMPLES = [
    "W-arxiv-2406.10162",
    "W-arxiv-2511.18397",
    "W-arxiv-2105.14111",
]
TRIAL_ROOT = LIBRARY_ROOT / "_cloud_trial"
DB_PATH = LIBRARY_ROOT / "literature.sqlite"
REPORT_JSON = LIBRARY_ROOT / "docs/superpowers/reviews/phase_b_trial_report.json"


def load_env_file() -> None:
    env = LIBRARY_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def get_runs() -> list[dict]:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    out = []
    for wid in SAMPLES:
        r = c.execute(
            "SELECT id, work_id, source_path, content_md_path FROM literature_parse_runs WHERE work_id=? ORDER BY id LIMIT 1",
            (wid,),
        ).fetchone()
        if r:
            out.append(dict(r))
    c.close()
    return out


def md_stats(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    text = path.read_text(encoding="utf-8", errors="replace")
    heads = re.findall(r"^#{1,6}\s+.+$", text, flags=re.M)
    low = text.lower()
    return {
        "exists": True,
        "chars": len(text),
        "h_headers": len(heads),
        "has_abstract": "abstract" in low,
        "has_references": "references" in low or "[1]" in text or "bibliography" in low,
        "lines": text.count("\n") + 1,
    }


def main() -> int:
    load_env_file()
    if not os.getenv("MinerU_API_KEY"):
        print("ERROR: MinerU_API_KEY missing"); return 2
    from core.mineru.cloud_client import CloudClient  # noqa: PLC0415
    from core.mineru.base_client import ParseRequest  # noqa: PLC0415
    import llm_judge  # noqa: PLC0415

    client = CloudClient()
    runs = get_runs()
    report = {"samples": [], "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    print(f"Phase B trial: {len(runs)} samples -> {TRIAL_ROOT}")

    for run in runs:
        wid = run["work_id"]
        sf_id = run["id"].replace("LPR-", "")
        src = Path(run["source_path"])
        old_md = Path(run["content_md_path"])
        out_dir = TRIAL_ROOT / wid / sf_id
        out_dir.mkdir(parents=True, exist_ok=True)
        rec = {"work_id": wid, "sf_id": sf_id, "source": str(src), "out_dir": str(out_dir)}

        print(f"\n[{wid}] cloud parse (pipeline/en) ...")
        t0 = time.time()
        req = ParseRequest(pdf_path=src, output_dir=out_dir, backend="pipeline", lang_list="en")
        try:
            ok, msg = client.parse_pdf(req)
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, f"EXC {exc}"
        rec["parse_ok"] = ok
        rec["parse_msg"] = msg[:300]
        rec["batch_id"] = getattr(client, "last_batch_id", "")
        rec["elapsed_s"] = round(time.time() - t0, 1)

        new_md = out_dir / "content.md"
        rec["old_stats"] = md_stats(old_md)
        rec["new_stats"] = md_stats(new_md)

        # 质量裁判：新旧各一次（成功解析才判新）
        rec["judge_old"] = llm_judge.quality_verdict(old_md) if old_md.exists() else {"error": "old md missing"}
        if ok and new_md.exists():
            rec["judge_new"] = llm_judge.quality_verdict(new_md)
        else:
            rec["judge_new"] = {"error": "new parse failed"}

        report["samples"].append(rec)
        print(f"  ok={ok} batch={rec['batch_id']} {rec['elapsed_s']}s")
        print(f"  old: {rec['old_stats'].get('chars')} chars | new: {rec['new_stats'].get('chars')} chars")
        print(f"  judge old={rec['judge_old'].get('quality')} new={rec['judge_new'].get('quality')}")

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport -> {REPORT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
