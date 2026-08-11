"""BranchService 测试：切换/新建/合并到 main，脏区拦截，冲突自动复原。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import i18n
i18n.LANG = "en"  # 测试固定英文输出，必须先于 import tui 模块

from tests.fakes import make_services


# ── Fake Provider 分支行为（Task 1）──
def test_fake_branch_ops():
    svc = make_services(initialized=True)
    git = svc.git
    assert git.list_branches() == ["main"]
    ok, _ = git.switch_branch("feature", create=True)
    assert ok and git.branch == "feature"
    assert git.list_branches() == ["main", "feature"]
    ok, _ = git.switch_branch("main")
    assert ok and git.branch == "main"
    ok, _ = git.switch_branch("nope")          # 不存在的分支
    assert not ok and git.branch == "main"
    assert git.switch_calls == [("feature", True), ("main", False), ("nope", False)]
    git.merge("feature")
    git.merge_abort()
    assert git.merge_calls == ["feature"]
    assert git.merge_abort_calls == 1
