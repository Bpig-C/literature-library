"""双栏阅读顺序检测单测（方案 B）。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.mineru.pymupdf_client import (  # noqa: E402
    column_switch_count,
    reading_order_ok,
)

W = 612.0  # US Letter 宽


def _blk(x0, y0, x1, y1, txt="text block"):
    return (x0, y0, x1, y1, txt)


def _left(y):
    return _blk(40, y, 290, y + 20)


def _right(y):
    return _blk(322, y, 572, y + 20)


def test_column_sequential_has_one_switch():
    # 左栏 3 块（自上而下）后接右栏 3 块 → 1 次切换
    blocks = [_left(100), _left(140), _left(180), _right(100), _right(140), _right(180)]
    assert column_switch_count(blocks, W) == 1


def test_column_interleaved_has_many_switches():
    # 左右逐行交错 L,R,L,R,L,R → 5 次切换
    blocks = [_left(100), _right(100), _left(140), _right(140), _left(180), _right(180)]
    assert column_switch_count(blocks, W) == 5


def test_reading_order_ok_sequential():
    blocks = [_left(100), _left(140), _left(180), _right(100), _right(140), _right(180)]
    ok, info = reading_order_ok([(blocks, W)])
    assert ok and info["two_col_pages"] == 1 and info["bad_pages"] == 0


def test_reading_order_not_ok_interleaved():
    # 8 行左右逐行交错 L,R,L,R,... → 15 次切换 > 6 → 判为乱序页
    blocks = []
    for i in range(8):
        y = 100 + i * 40
        blocks.append(_left(y))
        blocks.append(_right(y))
    ok, info = reading_order_ok([(blocks, W)])
    assert not ok and info["bad_pages"] == 1 and info["max_switches"] >= 15


def test_single_column_page_not_judged():
    # 仅左栏块 → 非双栏页，不参与判定 → ok
    blocks = [_left(100), _left(140), _left(180)]
    ok, info = reading_order_ok([(blocks, W)])
    assert ok and info["two_col_pages"] == 0


def test_majority_bad_fails_whole_doc():
    # 2 页双栏：1 页顺序良好(1 切换)，1 页严重交错(15 切换>6) → bad/2=0.5 不 < 0.5 → 不 ok
    good = [_left(100), _left(140), _right(100), _right(140)]
    bad = []
    for i in range(8):
        y = 100 + i * 40
        bad.append(_left(y))
        bad.append(_right(y))
    ok, info = reading_order_ok([(good, W), (bad, W)])
    assert not ok and info["two_col_pages"] == 2 and info["bad_pages"] == 1


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
