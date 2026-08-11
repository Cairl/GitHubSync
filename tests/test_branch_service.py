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


# ── BranchService（Task 2）──
def test_switch_success():
    svc = make_services(initialized=True, remote="x",
                        branches=["main", "feature"])
    ok, msg = svc.branch.switch("feature")
    assert ok and msg == ""
    assert svc.git.branch == "feature"


def test_switch_dirty_blocked():
    """脏区（porcelain 非空）拒绝切换，不产生任何 switch 调用。"""
    svc = make_services(initialized=True, remote="x",
                        branches=["main", "feature"], files={"a.py": "1"})
    ok, msg = svc.branch.switch("feature")
    assert not ok and "Uncommitted" in msg
    assert svc.git.switch_calls == []
    assert svc.git.branch == "main"


def test_switch_create():
    svc = make_services(initialized=True, remote="x")
    ok, _ = svc.branch.switch("dev", create=True)
    assert ok and svc.git.branch == "dev"
    assert ("dev", True) in svc.git.switch_calls


def test_merge_to_main_flow():
    """完整流：switch main → merge feature → push main，结束停在 main。"""
    svc = make_services(initialized=True, remote="x",
                        branches=["main", "feature"])
    svc.git.branch = "feature"
    ok, msg = svc.branch.merge_to_main()
    assert ok and msg == ""
    assert svc.git.switch_calls == [("main", False)]
    assert svc.git.merge_calls == ["feature"]
    assert svc.git.branch == "main"


def test_merge_to_main_on_main_rejected():
    svc = make_services(initialized=True, remote="x")
    ok, msg = svc.branch.merge_to_main()
    assert not ok and "Already on main" in msg
    assert svc.git.switch_calls == []


def test_merge_to_main_dirty_blocked():
    svc = make_services(initialized=True, remote="x",
                        branches=["main", "feature"], files={"a.py": "1"})
    svc.git.branch = "feature"
    ok, _ = svc.branch.merge_to_main()
    assert not ok
    assert svc.git.switch_calls == [] and svc.git.merge_calls == []


def test_merge_to_main_conflict_aborts_and_restores():
    """合并冲突：自动 merge --abort + 切回原分支，不留半截状态。"""
    svc = make_services(initialized=True, remote="x",
                        branches=["main", "feature"])
    svc.git.branch = "feature"
    svc.git.merge_ok = False
    ok, msg = svc.branch.merge_to_main()
    assert not ok and "conflict" in msg.lower()
    assert svc.git.merge_abort_calls == 1
    assert svc.git.switch_calls == [("main", False), ("feature", False)]
    assert svc.git.branch == "feature"


def test_merge_to_main_push_failure_stays_on_main():
    """合并成功但 push 失败：不 abort（已合完），停在 main，报失败。"""
    svc = make_services(initialized=True, remote="x",
                        branches=["main", "feature"])
    svc.git.branch = "feature"
    svc.git.fail_mode = "network"
    ok, msg = svc.branch.merge_to_main()
    assert not ok and "push" in msg.lower()
    assert svc.git.merge_calls == ["feature"]
    assert svc.git.branch == "main"
