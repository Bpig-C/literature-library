# collector/collect.py
"""collector 采集编排 nucleus（§2 单核）：按主题/显式 ID/种子/GitHub 发起一次采集 + 轻量闸门。

CLI(scripts.literature_intake.collect) 与 API(api.routes.intake) 共用本函数，零逻辑复制。
触达网络(arxiv / Semantic Scholar / GitHub)——由调用方/测试桩各发现入口。
"""
from __future__ import annotations

from api.db import get_conn
from collector import topics
from collector.discovery_explicit import collect_explicit
from collector.discovery_citation import collect_from_seeds
from collector.adapters.github import collect_repo_paper
from collector.gate import light_gate


def collect_once(*, topic_id: str | None = None,
                 explicit_ids: list[str] | None = None,
                 seed_paper_ids: list[str] | None = None,
                 github_urls: list[str] | None = None) -> dict:
    """发起一次采集 + 轻量闸门（不下载）。返回 {created, ...} 统计。

    - topic_id 给定：读该主题 query_def 的 explicit_ids / seed_paper_ids（与显式参数合并），
      且本次采集的**所有**候选（含显式 explicit_ids/github_urls）都归属该主题
      (collection_topic_id=topic_id)——契合 UI「按主题发起一次采集」的心智模型。
    - 对仍是 resolution='pending' 的候选跑 light_gate 写 resolution/matched_work_id；
      非 pending（如 github 自带 resolution）跳过闸门。
    """
    created: list[dict] = []
    if topic_id:
        t = topics.get(topic_id)
        if t is None:
            raise ValueError(f"unknown topic {topic_id}")
        qd = t["query_def"] or {}
        explicit_ids = list(explicit_ids or []) + list(qd.get("explicit_ids") or [])
        seed_paper_ids = list(seed_paper_ids or []) + list(qd.get("seed_paper_ids") or [])
        kw_topic = {"collection_topic_id": topic_id}
    else:
        kw_topic = {}

    if explicit_ids:
        created += collect_explicit(explicit_ids, source_type="arxiv", **kw_topic)
    if seed_paper_ids:
        created += collect_from_seeds(seed_paper_ids, source_type="arxiv", **kw_topic)
    if github_urls:
        for url in github_urls:
            created.append(collect_repo_paper(url, **kw_topic))

    # 轻量闸门（不下载）：只对 pending 候选跑
    conn = get_conn()
    try:
        for c in created:
            if c.get("resolution") == "pending":
                res, matched = light_gate({"arxiv_id": c.get("arxiv_id"),
                                           "doi": None, "title": c.get("title")})
                conn.execute(
                    "UPDATE intake_candidates SET resolution=?, matched_work_id=? WHERE id=?",
                    (res, matched, c["id"]),
                )
        conn.commit()
    finally:
        conn.close()

    return {"created": len(created)}
