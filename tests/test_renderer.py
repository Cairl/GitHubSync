"""DiffRenderer 差异刷新测试：相同跳过 / 变化重绘 / clear 重置。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tui.renderer import DiffRenderer


def test_first_render_plain():
    out = []
    r = DiffRenderer(out.append)
    r.render("a\nb")
    assert out == ["a\nb"]


def test_identical_render_skipped():
    out = []
    r = DiffRenderer(out.append)
    r.render("a\nb")
    r.render("a\nb")
    assert out == ["a\nb"]  # 第二次零输出


def test_changed_render_repaints_in_place():
    out = []
    r = DiffRenderer(out.append)
    r.render("a\nb")
    r.render("a\nc")
    # 首次整块 + [清除序列+新首行] + 其余新行
    assert len(out) == 3
    assert out[0] == "a\nb"
    assert out[1].startswith("\x1b[") and out[1].endswith("a")  # 清除后接首行
    assert out[2] == "c"


def test_clear_then_render_full_again():
    out = []
    r = DiffRenderer(out.append)
    r.render("a\nb")
    r.clear()
    assert len(out) == 2 and out[1].startswith("\x1b[")  # 只输出清除序列
    r.render("a\nb")
    assert out[2] == "a\nb"  # 重置后整块重画，不叠加清除


def test_reset_forces_plain_render():
    out = []
    r = DiffRenderer(out.append)
    r.render("a\nb")
    r.reset()
    r.render("a\nb")
    assert out[1] == "a\nb"


def test_render_empty_first_call():
    out = []
    r = DiffRenderer(out.append)
    r.render("")
    assert r.rendered and out == []
