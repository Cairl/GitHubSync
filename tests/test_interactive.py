"""极简交互模式测试：渲染纯函数、推荐动作映射、主循环与视图交互。"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import i18n
from core.status import RepoInfo, RepoStatus

i18n.LANG = "en"  # 测试固定英文输出
from tui.screen import (menu_for_action, recommended_action, render_main,
                        render_menu, render_header)


def _info(status, **kw):
    base = dict(branch="main", path="p")
    base.update(kw)
    return RepoInfo(status, **base)


def _strip_markup(s: str) -> str:
    """剥离 Rich markup 标签（反斜杠转义方括号还原为 [），仅保留可见文本。"""
    s = s.replace("\\[", "\x00")
    s = re.sub(r"\[/?[^\]]*\]", "", s)
    return s.replace("\x00", "[")


# ── 推荐动作映射 ──
def test_recommended_action_mapping():
    assert recommended_action(_info(RepoStatus.CHANGED, modified=1))[0] == "push"
    assert recommended_action(_info(RepoStatus.AHEAD, ahead=1))[0] == "push"
    assert recommended_action(_info(RepoStatus.BEHIND, behind=1))[0] == "restore_remote"
    assert recommended_action(_info(RepoStatus.DIVERGED, ahead=1, behind=1))[0] == "diff"
    assert recommended_action(_info(RepoStatus.CLEAN))[0] == "refresh"
    assert recommended_action(_info(RepoStatus.NO_REPO))[0] == "push"
    assert recommended_action(_info(RepoStatus.NO_REMOTE))[0] == "push"


def test_menu_for_action_mapping():
    """推荐动作 → 初始光标落点：push→推送，restore_remote→拉取，其余落推送。"""
    assert menu_for_action("push") == "push"
    assert menu_for_action("restore_remote") == "pull"
    assert menu_for_action("diff") == "push"
    assert menu_for_action("refresh") == "push"
    assert menu_for_action("unknown") == "push"


def test_render_main_contains_key_parts():
    out = _strip_markup(render_main(_info(RepoStatus.CHANGED, added=1, modified=2),
                                    "GitHubSync"))
    # 第一行：项目名（无远程 URL 时不附括号）；第二行：分支·状态
    assert out.startswith("GitHubSync\nbranch: main (+3)")
    assert "file(s) changed" not in out
    assert "Push" in out and "Pull" in out and "Files" in out
    assert "›" not in out       # render_main 无 active 时不显示光标
    assert "[r] Restore" not in out and "[i] Info" not in out  # 旧入口已移除
    assert "[p] Push" not in out  # 快捷键标识已移除，改为光标选择


def test_render_header_shows_remote_url():
    """有远程 URL 时，顶栏第一行显示「项目: 名 … 主页: URL（去 .git）」。"""
    out = _strip_markup(render_header(
        _info(RepoStatus.CHANGED, remote_url="https://github.com/Cairl/GitHubSync.git"),
        "GitHubSync"))
    assert "Project: GitHubSync" in out
    assert "branch: main" in out
    assert "Home: https://github.com/Cairl/GitHubSync" in out


def test_render_main_diverged_wording():
    out = _strip_markup(render_main(_info(RepoStatus.DIVERGED, ahead=1, behind=2),
                                    "GitHubSync"))
    assert "new commits to push and pull" in out


def test_render_main_status_branch_colored():
    """状态行仅分支名染色（#CDD6F4），括号内容为默认色。"""
    out = render_main(_info(RepoStatus.DIVERGED, ahead=1, behind=2), "GitHubSync")
    assert "[#CDD6F4]main" in out  # 分支名染色
    assert "#F85149" not in out    # 括号内容不再染语义色
    out_clean = render_main(_info(RepoStatus.CLEAN), "GitHubSync")
    assert "#3FB950" not in out_clean


def test_render_menu_uniform_three_items():
    """导航栏固定三项（推送/拉取/文件），分叉时不再切换为恢复/强制推送。"""
    menu = _strip_markup(render_menu(_info(RepoStatus.DIVERGED, ahead=1, behind=1)))
    assert "Push" in menu and "Pull" in menu and "Files" in menu
    assert "Restore" not in menu and "Force push" not in menu
    assert "[p]" not in menu and "[l]" not in menu and "[f]" not in menu  # 无快捷键标识


def test_render_menu_cursor_marks_active():
    """选中项背景 ` › 文本 `（左右各冗余 1 格、不顶格），未选中 `   文本 `（前缀3+后缀1）。"""
    menu = render_menu(_info(RepoStatus.CHANGED, modified=1), active="push")
    assert "[bold on #636363] › Push [/]" in menu
    assert "   Pull " in menu and "   Files " in menu
    menu_right = render_menu(_info(RepoStatus.CHANGED, modified=1), active="files")
    assert "[bold on #636363] › Files [/]" in menu_right
    assert "   Push " in menu_right


# ── 主循环与视图 ──
from core.file_ops_service import FileOpsService
from core.release_service import ReleaseService
from core.restore_service import RestoreService
from core.status_service import StatusService
from core.sync_service import SyncService
from core.config import (KEY_BACKSPACE, KEY_DOWN, KEY_ENTER, KEY_LEFT,
                         KEY_RIGHT, KEY_UP)
from core.events import DomainEventBus
from core.services import Services
from tui.files_view import FilesView
from tui.interactive import InteractiveApp
from tui.restore_view import RestoreView
from tests.fakes import FakeGitHubProvider, FakeGitProvider


def make_tui_services(**git_kw):
    bus = DomainEventBus()
    git = FakeGitProvider()
    for k, v in git_kw.items():
        setattr(git, k, v)
    gh = FakeGitHubProvider()
    release = ReleaseService(gh, bus, "fake_repo")
    return Services(
        git=git, gh=gh, bus=bus,
        status=StatusService(git, "fake_repo"),
        sync=SyncService(git, gh, bus, "fake_repo", release),
        restore=RestoreService(git, bus),
        file_ops=FileOpsService(git, bus, "fake_repo"),
        release=release,
    )


def scripted(keys):
    it = iter(keys)
    return lambda: next(it)


def test_interactive_enter_pushes():
    svc = make_tui_services(initialized=True, remote="x", files={"a.py": "1"})
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):  # 无退出键，按键耗尽即止
        app.run()
    assert svc.git.commits  # 确实提交了
    assert "(+1)" in "\n".join(out_lines)


def test_interactive_backspace_returns_to_main():
    """Backspace 清除子视图（文件视图）返回主屏。"""
    svc = make_tui_services(initialized=True, remote="x")
    out_lines = []
    # 初始光标在推送（CHANGED → push），右移 2 次到「文件」，Enter 进入后 Backspace 返回
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted(
                             [KEY_RIGHT, KEY_RIGHT, KEY_ENTER, KEY_BACKSPACE]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    joined = "\n".join(out_lines)
    assert "No files." in joined    # 文件视图已渲染
    assert joined.endswith("\x1b[J")  # 返回后内容区清空回主屏


def test_interactive_invalid_key_no_repaint():
    """无效键 + 状态未变：主屏块不重复输出（差异化刷新）。"""
    svc = make_tui_services(initialized=True, remote="x")
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([b"z", b"z"]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    joined = "\n".join(out_lines)
    # 主屏只渲染一次；后续两轮内容相同 → 零输出
    assert joined.count("Synced, working tree clean.") == 1


def test_files_view_include_ignored(tmp_path):
    (tmp_path / "notes.txt").write_text("x")
    svc = make_tui_services(initialized=True, remote="x")
    svc.git.gitignore_lines = ["notes.txt"]
    svc.file_ops.repo_path = str(tmp_path)
    view = FilesView(svc.file_ops, key_source=scripted([KEY_ENTER, KEY_BACKSPACE]),
                     out=lambda s: None)
    view.run()
    assert "notes.txt" not in svc.git.gitignore_lines


def test_files_view_cursor_matches_menu_style(tmp_path):
    """文件列表光标与导航栏同款：选中行 › 前缀 + 底色框选，未选中行等宽占位对齐。

    文本起始列均为 3（选中 ` › 名 ` / 未选中 `   名 `），与 render_menu 定案一致。
    """
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.py").write_text("x")
    svc = make_tui_services(initialized=True, remote="x")
    svc.file_ops.repo_path = str(tmp_path)
    out_lines = []
    view = FilesView(svc.file_ops, key_source=scripted([KEY_BACKSPACE]),
                     out=out_lines.append)
    view.run()
    block = out_lines[0]  # DiffRenderer 首次整块输出
    lines = block.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith(" › ")          # 选中行：› 光标（同菜单）
    assert lines[1].startswith("   ")          # 未选中行：3 空格占位
    assert lines[0].index("a.py") == lines[1].index("b.py") == 3  # 文本对齐


def test_files_view_button_column_aligned(tmp_path):
    """文件操作按钮独立一列且垂直对齐：忽略/推送按钮起点列一致，无 [已忽略] 标记。

    已忽略文件按钮显示 Push（Enter 纳入同步），未忽略显示 Ignore（Enter 排除）。
    """
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "notes.txt").write_text("x")
    svc = make_tui_services(initialized=True, remote="x")
    svc.git.gitignore_lines = ["notes.txt"]
    svc.file_ops.repo_path = str(tmp_path)
    out_lines = []
    view = FilesView(svc.file_ops, key_source=scripted([KEY_BACKSPACE]),
                     out=out_lines.append)
    view.run()
    block = out_lines[0]  # DiffRenderer 首次整块输出
    lines = block.splitlines()
    assert len(lines) == 2
    # 无 [已忽略] 标记，按钮代替状态标识
    assert "ignored" not in block and "[已忽略]" not in block
    assert "Push" in lines[1] and "Ignore" in lines[0]
    # 按钮独立一列：两行按钮起点列一致（垂直对齐）
    assert lines[0].index("Ignore") == lines[1].index("Push")


def test_files_view_ignored_name_strikethrough():
    """已忽略文件文件名带删除线（默认色），未忽略文件不带（状态一眼可辨）。"""
    from tui.files_view import _render_row
    ignored = _render_row({"name": "notes.txt", "ignored": True},
                          selected=False, name_col=20, btn_w=6,
                          push_text="Push", ignore_text="Ignore")
    active = _render_row({"name": "a.py", "ignored": False},
                         selected=False, name_col=20, btn_w=6,
                         push_text="Push", ignore_text="Ignore")
    assert "[strike]notes.txt[/]" in ignored
    assert "strike #292929" not in ignored  # 删除线为默认色，无自定义颜色
    assert "[strike" not in active
    assert "Push" in ignored and "Ignore" in active


def test_files_view_push_button_blue():
    """「推送」按钮蓝色（#58A6FF），「忽略」按钮保持默认色。"""
    from tui.files_view import _render_row
    ignored = _render_row({"name": "notes.txt", "ignored": True},
                          selected=False, name_col=20, btn_w=6,
                          push_text="Push", ignore_text="Ignore")
    active = _render_row({"name": "a.py", "ignored": False},
                         selected=False, name_col=20, btn_w=6,
                         push_text="Push", ignore_text="Ignore")
    assert "[#58A6FF]Push[/]" in ignored
    assert "[#58A6FF]" not in active


def test_files_view_button_gap_two_spaces():
    """文件名与操作按钮之间至少 2 空格分隔，避免视觉粘连。"""
    from tui.files_view import _render_row
    row = _render_row({"name": "notes.txt", "ignored": False},
                      selected=False, name_col=9, btn_w=6,
                      push_text="Push", ignore_text="Ignore")
    # name_col=9 恰好占满文件名（notes.txt 宽 9），按钮前仍保留 2 空格
    assert "notes.txt  Ignore" in row


def test_pull_view_enter_restores_commit():
    """拉取视图：选中历史提交后 Enter 直接恢复（无二次确认）。"""
    svc = make_tui_services(initialized=True, remote="x")
    svc.git.commits = ["abcdef1234567890", "fedcba9876543210"]
    view = RestoreView(svc.restore, svc.git,
                       key_source=scripted([KEY_DOWN, KEY_ENTER]),
                       out=lambda s: None)
    view.run()
    assert svc.git.reset_to == "abcdef1234567890"  # 第二项（较旧提交）


def test_pull_view_align_remote_on_first_item():
    """拉取视图：光标默认首个（最新提交），Enter = 对齐远程（fetch + reset origin/branch）。"""
    svc = make_tui_services(initialized=True, remote="x")
    svc.git.commits = ["abcdef1234567890"]
    view = RestoreView(svc.restore, svc.git,
                       key_source=scripted([KEY_ENTER]),
                       out=lambda s: None)
    view.run()
    assert svc.git.reset_to == "origin/main"
    assert svc.git.fetch_calls == 1
    assert svc.git.clean_calls == 1  # 1:1 复刻：对齐远程后清理未跟踪文件


def test_pull_view_cursor_matches_menu_style():
    """拉取视图光标与文件视图同款：› 前缀 + 底色框选，未选中行等宽占位对齐。

    列表 = 历史提交（最新在前）；文本起始列均为 3（选中 ` › 文本 ` / 未选中 `   文本 `）。
    """
    svc = make_tui_services(initialized=True, remote="x")
    svc.git.commits = ["abcdef1234567890", "fedcba9876543210"]
    out_lines = []
    view = RestoreView(svc.restore, svc.git,
                       key_source=scripted([KEY_BACKSPACE]),
                       out=out_lines.append)
    view.run()
    block = out_lines[0]  # DiffRenderer 首次整块输出
    lines = block.splitlines()
    assert len(lines) == 2
    assert lines[0].index("fedcba98") == 3  # 最新在前，选中行 › 光标
    assert lines[1].index("abcdef12") == 3  # 文本对齐


def test_pull_view_no_commits_shows_hint():
    """无历史提交时提示并返回（无对齐项兜底）。"""
    svc = make_tui_services(initialized=True, remote="x")
    svc.git.commits = []
    out_lines = []
    view = RestoreView(svc.restore, svc.git,
                       key_source=scripted([]),
                       out=out_lines.append)
    view.run()
    assert "No commits." in "\n".join(out_lines)


def test_menu_redraw_line_stable_after_remote_configured(tmp_path):
    """remote 从无到有后菜单重绘行号不漂移（顶栏布局固定），避免重行。

    复现：NO_REMOTE 启动（顶栏 7 行，菜单在第 5 行）→ Enter 推送配置 remote →
    左右键移动光标触发多次菜单重绘 → 重绘行号不漂移。
    """
    import re
    (tmp_path / "a.py").write_text("x")
    svc = make_tui_services(initialized=True, remote=None,
                            files={"a.py": "1"})
    svc.file_ops.repo_path = str(tmp_path)
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER, KEY_RIGHT, KEY_LEFT,
                                              KEY_RIGHT, KEY_LEFT,
                                              KEY_BACKSPACE]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    assert svc.git.remote is not None  # 推送确实配置了 remote
    menu_ys = []
    for ln in out_lines:
        if "\x1b[2K" in ln and re.search(r"›\s*(Push|Pull)", ln):
            m = re.search(r"\x1b\[(\d+);1H", ln)
            assert m, ln
            menu_ys.append(int(m.group(1)))
    assert len(menu_ys) >= 2, f"应发生多次菜单重绘: {menu_ys}"
    assert len(set(menu_ys)) == 1, \
        f"菜单重绘行号漂移导致重行: {menu_ys}"


def test_content_truncation_keeps_header_on_screen(monkeypatch):
    """内容区超长时截断保留末尾，不触发终端滚动（顶栏保持可见）。

    复现：21 行视图内容 + 顶栏 8 行超出 24 行终端，
    _render_content 应截断到可用行数，否则 print 触发滚动顶掉顶栏。
    """
    monkeypatch.setattr(InteractiveApp, "_terminal_height",
                        staticmethod(lambda: 24))
    monkeypatch.setattr(InteractiveApp, "_terminal_width",
                        staticmethod(lambda: 100))
    svc = make_tui_services(initialized=True, remote="x")
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([]),
                         out=out_lines.append)
    app._info = svc.status.get_status(fetch=False)
    app._view = "\n".join(f"line {i}" for i in range(21))
    app._paint()
    # 每次内容区重绘：定位行 + 内容行数不得超过屏幕高度（24 行）
    for ln in out_lines:
        m = re.search(r"\x1b\[(\d+);1H\x1b\[J", ln)
        if m:
            start_row = int(m.group(1))
            body = ln.split("\x1b[J", 1)[1]
            n = body.count("\n") + (1 if body.strip() else 0)
            assert start_row + n <= 24, \
                f"内容超屏触发滚动: start={start_row} rows={n} out={ln!r}"


# ── 菜单光标（← → + Enter）──
def test_menu_cursor_initial_follows_recommended():
    """BEHIND 时初始光标落在拉取，Enter 进入拉取视图，再 Enter 执行对齐远程。"""
    svc = make_tui_services(initialized=True, remote="x", behind=1,
                            commits=["abcdef1234567890"])
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER, KEY_ENTER]),
                         out=lambda s: None)
    with pytest.raises(StopIteration):
        app.run()
    assert svc.git.reset_to == "origin/main"  # 拉取视图首项对齐远程
    assert svc.git.clean_calls == 1


def test_menu_cursor_wraps_and_executes_selected():
    """← → 循环移动光标；CLEAN 状态（推荐刷新→光标推送）右移 2 次、左移 1 次后
    Enter 进拉取视图，再 Enter 执行对齐远程。"""
    svc = make_tui_services(initialized=True, remote="x",
                            commits=["abcdef1234567890"])
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted(
                             [KEY_RIGHT, KEY_RIGHT, KEY_LEFT, KEY_ENTER,
                              KEY_ENTER]),
                         out=lambda s: None)
    with pytest.raises(StopIteration):
        app.run()
    assert svc.git.reset_to == "origin/main"  # 光标最终落在拉取，Enter 对齐远程
    assert svc.git.clean_calls == 1


def test_menu_item_position_stable_across_cursor():
    """每项固定宽度（前缀3 + 文本 + 后缀1），join 0：文本位置对齐，光标移动不跳动。"""
    base = _strip_markup(render_menu(_info(RepoStatus.CLEAN)))
    positions = [base.index(t) for t in ("Push", "Pull", "Files")]
    for active in ("push", "pull", "files"):
        text = _strip_markup(render_menu(_info(RepoStatus.CLEAN), active=active))
        got = [text.index(t) for t in ("Push", "Pull", "Files")]
        assert got == positions, f"active={active}: {text!r}"


def test_menu_text_spacing_stable_across_cursor():
    """join 0，间距 = 后缀1 + 前缀3 = 4 格，任何光标位置下不变。"""
    for active in ("push", "pull", "files"):
        text = _strip_markup(render_menu(_info(RepoStatus.CLEAN), active=active))
        i_push, i_pull, i_files = (text.index(t) for t in ("Push", "Pull", "Files"))
        assert i_pull - i_push - 4 == 4, f"active={active}: {text!r}"
        assert i_files - i_pull - 4 == 4, f"active={active}: {text!r}"


# ── 无回显化：文件视图失败标记 ──
def test_file_ops_push_file_returns_bool():
    """push_file 返回 bool：推送失败 False，成功 True。"""
    svc = make_tui_services(initialized=True, remote="x")
    svc.git.fail_mode = "network"  # 持久推送失败
    assert svc.file_ops.push_file("a.py") is False
    svc.git.fail_mode = "ok"
    assert svc.file_ops.push_file("b.py") is True


def test_files_view_failed_marker_aligned():
    """失败行行首 [!] 红色；[!] 3 宽与正常行 3 空格等宽，文件名起始列一致。"""
    from tui.files_view import _render_row
    from tui.renderer import markup_to_ansi
    failed = _render_row({"name": "notes.txt", "ignored": True},
                         selected=False, name_col=20, btn_w=6,
                         push_text="Push", ignore_text="Ignore", failed=True)
    ok = _render_row({"name": "a.py", "ignored": False},
                     selected=False, name_col=20, btn_w=6,
                     push_text="Push", ignore_text="Ignore")
    assert "\\[!]" in failed            # [!] 转义后为字面文本
    assert "#F85149" in failed          # 错误红
    assert "\\[!]" not in ok
    # 对齐：转换后的可见文本中 [!] 3 宽与 3 空格等宽，文件名起始列一致
    f, o = markup_to_ansi(failed), markup_to_ansi(ok)
    assert f.index("notes.txt") == o.index("a.py") == 3


def test_files_view_shows_failed_marker_after_push_fail(tmp_path):
    """push 失败后文件行出现 [!] 标记。"""
    (tmp_path / "notes.txt").write_text("x")
    svc = make_tui_services(initialized=True, remote="x")
    svc.git.gitignore_lines = ["notes.txt"]
    svc.git.fail_mode = "network"      # 推送失败
    svc.file_ops.repo_path = str(tmp_path)
    out_lines = []
    view = FilesView(svc.file_ops, key_source=scripted([KEY_ENTER, KEY_BACKSPACE]),
                     out=out_lines.append)
    view.run()
    joined = "\n".join(out_lines)
    assert "[!]" in joined              # 失败标记出现
