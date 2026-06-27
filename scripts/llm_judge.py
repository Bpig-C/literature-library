"""共享「本地强模型裁判」模块：通过 opencode CLI 调 MiMo-v2.5-pro。

供 P3.5 解析质量门 + 后续元数据/主题/分类共用。

调用契约（已冒烟验证）：
    opencode run --pure -m mimo/mimo-v2.5-pro --format json "<prompt>"
- --format json 流式输出 NDJSON；assistant 文本在各 {"type":"text","part":{"text":"..."}} 事件，
  拼接所有 text 事件得完整回复；step_finish 带 token 计数。
- flags 在前、message 在后（规避 Windows shim 截断）。

运行时硬化原语（借鉴参考项目 ei_corpus_loop run_loop.py）：
- find_opencode() Windows 下依次找 opencode.cmd/.exe/opencode
- 流式读取 + 双超时（总超时 + 无输出超时）+ 进程树清理（Win: taskkill /T /F）
- noop/拒答检测 + 重试
- JSONL 调用日志（tokens/cost/verdict），便于核算 ~15k 脚手架成本

两种输出模式：
- judge(prompt) -> dict           内联 JSON（质量门用）
- run_executor(...) -> dict       写文件执行器（下游抽取/分类用，留接口）
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

LIBRARY_ROOT = Path(__file__).resolve().parents[1]
CALL_LOG = LIBRARY_ROOT / "llm_judge_calls.jsonl"

DEFAULT_MODEL = os.getenv("MINERU_JUDGE_MODEL", "mimo/mimo-v2.5-pro")
DEFAULT_TIMEOUT = 240          # 总超时（秒）
DEFAULT_IDLE_TIMEOUT = 120     # 无输出超时（秒）
DEFAULT_RETRIES = 2

_NOOP_MARKERS = (
    "what would you like",
    "i cannot",
    "i can't",
    "无法",
    "不能提供",
    "请提供",
)


# ---------------- opencode 可执行文件定位 ----------------
def find_opencode() -> str:
    """Windows 下依次找 opencode.cmd/.exe/opencode；找不到抛错。"""
    candidates = ["opencode.cmd", "opencode.exe", "opencode"] if os.name == "nt" else ["opencode"]
    for c in candidates:
        resolved = shutil.which(c)
        if resolved:
            return resolved
    raise RuntimeError("opencode 未找到：请确认 opencode.cmd/opencode 在 PATH 中。")


# ---------------- 流式进程执行（双超时 + 进程树清理）----------------
def _kill_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=False,
        )
    else:
        try:
            import signal as _sig
            os.killpg(os.getpgid(proc.pid), _sig.SIGKILL)
        except Exception:
            proc.kill()


def _run_streaming(
    cmd: list[str],
    *,
    timeout: float,
    idle_timeout: float,
) -> tuple[int, str, str, dict[str, Any]]:
    """运行 cmd，流式读 stdout。返回 (returncode, stdout, stderr, meta{timed_out,idle_timed_out,elapsed})。"""
    start = time.time()
    deadline = start + timeout
    meta: dict[str, Any] = {"timed_out": False, "idle_timed_out": False, "elapsed": 0.0}

    creationflags = 0
    start_new_session = False
    if os.name == "nt":
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        creationflags = CREATE_NEW_PROCESS_GROUP
    else:
        start_new_session = True

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        cwd=str(LIBRARY_ROOT),
        creationflags=creationflags,
        start_new_session=start_new_session,
    )

    out_q: queue.Queue[str | None] = queue.Queue()
    err_buf: list[str] = []

    def reader(stream, q: queue.Queue):
        try:
            for line in stream:
                q.put(line)
        except Exception:
            pass
        finally:
            q.put(None)

    def reader_err(stream):
        try:
            for line in stream:
                err_buf.append(line)
        except Exception:
            pass

    t_out = threading.Thread(target=reader, args=(proc.stdout, out_q), daemon=True)
    t_err = threading.Thread(target=reader_err, args=(proc.stderr,), daemon=True)
    t_out.start()
    t_err.start()

    out_lines: list[str] = []
    last_output = time.time()
    timed_out = False
    while True:
        remaining = min(deadline - time.time(), (last_output + idle_timeout) - time.time())
        if remaining <= 0:
            # 判定是哪种超时
            if time.time() >= deadline:
                meta["timed_out"] = True
            else:
                meta["idle_timed_out"] = True
            timed_out = True
            break
        try:
            line = out_q.get(timeout=min(remaining, 1.0))
        except queue.Empty:
            if proc.poll() is not None and out_q.empty():
                break
            continue
        if line is None:
            break
        out_lines.append(line)
        last_output = time.time()

    if timed_out:
        _kill_process_tree(proc)
        try:
            proc.wait(timeout=10)
        except Exception:
            pass

    proc.wait()
    meta["elapsed"] = round(time.time() - start, 2)
    return proc.returncode, "".join(out_lines), "".join(err_buf), meta


# ---------------- NDJSON 解析 ----------------
def _parse_ndjson_text(stdout: str) -> tuple[str, dict[str, Any]]:
    """从 opencode --format json 的 NDJSON 输出中拼接 assistant 文本，并取 token 计数。"""
    chunks: list[str] = []
    tokens: dict[str, Any] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            evt = json.loads(line)
        except Exception:
            continue
        if evt.get("type") == "text":
            part = evt.get("part") or {}
            if isinstance(part.get("text"), str):
                chunks.append(part["text"])
        elif evt.get("type") == "step_finish":
            part = evt.get("part") or {}
            t = part.get("tokens")
            if isinstance(t, dict):
                tokens = t
    return "".join(chunks), tokens


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:
            pass
    brace = re.search(r"\{.*\}", text, re.S)
    if brace:
        try:
            return json.loads(brace.group(0))
        except Exception:
            return None
    return None


def _looks_noop(text: str) -> bool:
    low = (text or "").lower().strip()
    if not low:
        return True
    return any(m in low for m in _NOOP_MARKERS) and len(low) < 80


# ---------------- 日志 ----------------
def _log_call(record: dict[str, Any]) -> None:
    try:
        CALL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with CALL_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------- 公开 API ----------------
def judge(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
    idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> dict[str, Any]:
    """让 opencode(MiMo) 对 prompt 给出**内联 JSON** 裁决。失败重试，最终兜底返回错误 dict。

    实现要点（Windows 实测）：大段 prompt 不能走命令行内联（opencode.cmd shim 会截断/破坏），
    故把 prompt 写入临时文件、用 opencode 原生 `-f` 附件传入；命令行只带一句短指令。
    形如：opencode run "<短指令>" --pure -m <model> --format json -f <prompt文件>
    """
    exe = find_opencode()
    prompt_file = LIBRARY_ROOT / f"_judge_prompt_{os.getpid()}_{int(time.time())}.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    short_msg = (
        "阅读附件文件的完整内容，并严格按其中的指示完成任务。"
        "只输出要求的 JSON 对象，不要任何额外文字、解释、前缀或代码围栏。"
    )
    last_err = ""
    try:
        for attempt in range(retries + 1):
            # 短 message 在前，flags 与 -f 在后（-f 必须在 message 之后，避免被当作多文件吞噬）
            cmd = [exe, "run", short_msg, "--pure", "-m", model, "--format", "json", "-f", str(prompt_file)]
            rc, stdout, stderr, meta = _run_streaming(cmd, timeout=timeout, idle_timeout=idle_timeout)
            text, tokens = _parse_ndjson_text(stdout)
            record = {
                "ts": _now(), "model": model, "attempt": attempt,
                "returncode": rc, "elapsed": meta.get("elapsed"),
                "timed_out": meta.get("timed_out"), "idle_timed_out": meta.get("idle_timed_out"),
                "tokens": tokens, "text_len": len(text),
            }
            if meta.get("timed_out") or meta.get("idle_timed_out") or rc not in (0, None):
                last_err = f"rc={rc} meta={meta} stderr={stderr[:300]}"
                _log_call({**record, "status": "run_failed", "error": last_err})
                time.sleep(2 ** attempt)
                continue
            data = _extract_json(text)
            if data is None or _looks_noop(text):
                last_err = f"无法解析JSON或拒答：{text[:200]}"
                _log_call({**record, "status": "parse_failed", "raw": text[:300], "error": last_err})
                time.sleep(2 ** attempt)
                continue
            _log_call({**record, "status": "ok", "verdict": data})
            return data
        return {"error": "judge_failed", "reason": last_err}
    finally:
        try:
            prompt_file.unlink(missing_ok=True)
        except Exception:
            pass


def quality_verdict(
    content_md_path: str | Path,
    *,
    full: bool = True,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """对一篇 content.md 出质量裁决。

    默认送全文（MiMo 1M context 可承载；通篇阅读才能判断完整性/结构质量）。
    full=False 时仅送首尾摘要，只能判断可见的解析缺陷（乱码/断行/表格损坏），
    不能判断完整性——仅用于极低成本粗筛。返回固定 schema。
    """
    path = Path(content_md_path)
    if not path.exists():
        return {"error": "content.md 不存在", "path": str(path)}
    text = path.read_text(encoding="utf-8", errors="replace")
    n = len(text)
    if full or n <= 8000:
        body = text
        body_note = f"全文（{n} 字符）"
        judge_scope = "判断解析质量与完整性：是否存在乱码、断行错误、表格/公式损坏、摘要或参考文献缺失、整体提取不完整等。"
    else:
        # 低成本粗筛：仅首尾，不评判完整性（避免把"省略中段"误判为解析截断）
        body = f"{text[:3000]}\n\n...[此处为节省篇幅仅展示首尾，不要据此判断完整性]...\n\n{text[-2000:]}"
        body_note = f"首尾采样（全文 {n} 字符，仅供检测可见解析缺陷，非完整性判断）"
        judge_scope = "仅根据可见内容判断是否存在乱码、断行错误、表格/公式损坏等解析缺陷；不要因为中段省略而判定不完整。"

    schema_hint = (
        '{"quality":"good|acceptable|poor","needs_reparse":bool,'
        '"issues":["missing_abstract","missing_refs","garbled","low_extraction",...],'
        '"completeness":0.0-1.0,"reason":"<短句>"}'
    )
    prompt = (
        "你是文档解析质量裁判。下面是一篇由 MinerU 从 PDF 解析得到的 Markdown"
        f"（{body_note}）。{judge_scope}\n\n"
        f"只输出如下 JSON，不要任何额外文字：\n{schema_hint}\n\n"
        f"--- 文档内容 ---\n{body}"
    )
    verdict = judge(prompt, model=model)
    if "error" in verdict:
        return verdict
    # 规整 schema
    return {
        "quality": verdict.get("quality", "unknown"),
        "needs_reparse": bool(verdict.get("needs_reparse", False)),
        "issues": verdict.get("issues", []) or [],
        "completeness": verdict.get("completeness", 0.0),
        "reason": verdict.get("reason", ""),
    }


def run_executor(
    task_prompt_path: str | Path,
    *,
    expected_outputs: list[str] | None = None,
    model: str = DEFAULT_MODEL,
    timeout: float = 1800,
) -> dict[str, Any]:
    """写文件执行器模式（下游元数据/主题/分类用）。

    让 opencode agent 读取 task_prompt_path 并按其指示写结构化产物文件。
    本期仅留接口；下游任务启动时补实现与产物校验。
    """
    raise NotImplementedError("run_executor 留待下游抽取/分类任务启动时实现")


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------- CLI（冒烟/手动调用）----------------
def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="LLM 裁判（opencode→MiMo）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_q = sub.add_parser("quality", help="对一篇 content.md 出质量裁决")
    p_q.add_argument("content_md")
    p_q.add_argument("--full", action="store_true", help="送全文而非摘要")
    p_j = sub.add_parser("judge", help="对任意 prompt 出 JSON 裁决")
    p_j.add_argument("prompt")
    args = ap.parse_args()

    if args.cmd == "quality":
        print(json.dumps(quality_verdict(args.content_md, full=args.full), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(judge(args.prompt), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
