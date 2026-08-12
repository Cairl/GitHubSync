"""极简交互模式测试：渲染纯函数、推荐动作映射、标签页主循环交互。"""
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
    """剥离 markup 标签（反斜杠转义的 [ * 还原为原字符），仅保留可见文本。"""
    s = s.replace("\\[", "\x00").replace("\\*", "\x01")
    s = re.sub(r"\[/?[^\]]*\]", "", s)
    return s.replace("\x00", "[").replace("\x01", "*")


# ── 推荐动作映射 ──
def test_recommended_action_mapping():
    assert recommended_action(_info(RepoStatus.CHANGED, modified=1))[0] == "push"
    assert recommended_action(_info(RepoStatus.AHEAD, ahead=1))[0] == "push"
    assert recommended_action(_info(RepoStatus.BEHIND, behind=1))[0] == "restore_remote"
    assert recommended_action(_info(RepoStatus.DIVERGED, ahead=1, behind=1))[0] == "diff"
    assert recommended_action(_info(RepoStatus.CLEAN))[0] == "refresh"
    assert recommended_action(_info(RepoStatus.NO_REPO))[0] == "push"
    assert recommended_action(_info(RepoStatus.NO_REMOTE))[0] == "push"


def test_recommended_action_release_pending():
    """工作区干净但 Release 待发布：推荐推送（changelog.md 不入库但可见）。"""
    assert recommended_action(
        _info(RepoStatus.CLEAN, release_pending=True))[0] == "push"
    assert recommended_action(
        _info(RepoStatus.CLEAN, release_pending=True))[1] == "Push"


def test_menu_for_action_mapping():
    """推荐动作 → 初始标签落点：push→推送，restore_remote→拉取，其余落推送。"""
    assert menu_for_action("push") == "push"
    assert menu_for_action("restore_remote") == "pull"
    assert menu_for_action("diff") == "push"
    assert menu_for_action("refresh") == "push"
    assert menu_for_action("unknown") == "push"


def test_render_main_contains_key_parts():
    out = _strip_markup(render_main(_info(RepoStatus.CHANGED, added=1, modified=2),
                                    "GitHubSync"))
    # 第一行：项目名（无远程 URL 时不附括号）；第二行：分支（无状态详情括号）
    assert out.startswith("GitHubSync\nbranch: main\n")
    assert "file(s) changed" not in out
    assert "Push" in out and "Pull" in out and "Files" in out
    assert "›" not in out       # render_main 无 active 时不显示光标
    assert "[r] Restore" not in out and "[i] Info" not in out  # 旧入口已移除
    assert "[p] Push" not in out  # 快捷键标识已移除，改为标签选择


def test_render_header_shows_remote_url():
    """有远程 URL 时，顶栏显示「项目: 名 … 主页: URL（去 .git）」；无版本号时显示 `-`。"""
    out = _strip_markup(render_header(
        _info(RepoStatus.CHANGED, remote_url="https://github.com/Cairl/GitHubSync.git"),
        "GitHubSync"))
    assert "Project: GitHubSync" in out
    assert "branch: main" in out
    assert "Home: https://github.com/Cairl/GitHubSync" in out
    assert "Version: -" in out  # 未传版本号 → `-` 占位


def test_render_header_shows_release_version():
    """版本行显示最新 Release tag，文本包 OSC 8 超链接（终端 Ctrl+点击打开 Releases）。

    `[link <releases_url> …]` 由 core/ansi.py 渲染为 OSC 8 序列；无远程 URL 时不渲染版本行。
    """
    out = render_header(
        _info(RepoStatus.CHANGED, remote_url="https://github.com/Cairl/GitHubSync.git"),
        "GitHubSync", release_tag="26w32a")
    assert "[link https://github.com/Cairl/GitHubSync/releases #ABDFA7]26w32a[/]" in out
    assert "Version: 26w32a" in _strip_markup(out)
    # 无远程：无主页行也无版本行
    out_no_remote = _strip_markup(render_header(
        _info(RepoStatus.NO_REMOTE), "GitHubSync", release_tag="26w32a"))
    assert "Version:" not in out_no_remote
    assert "Home:" not in out_no_remote


def test_render_main_diverged_no_bracket_detail():
    """分叉时状态行同样只有分支名，无括号状态详情。"""
    out = _strip_markup(render_main(_info(RepoStatus.DIVERGED, ahead=1, behind=2),
                                    "GitHubSync"))
    assert out.startswith("GitHubSync\nbranch: main\n")
    assert "new commits to push and pull" not in out
    assert "(" not in out


def test_render_main_status_branch_colored():
    """状态行仅分支名染色（#CDD6F4），无括号内容。"""
    out = render_main(_info(RepoStatus.DIVERGED, ahead=1, behind=2), "GitHubSync")
    assert "[#CDD6F4]main" in out  # 分支名染色
    assert "#F85149" not in out    # 无括号状态详情
    out_clean = render_main(_info(RepoStatus.CLEAN), "GitHubSync")
    assert "#3FB950" not in out_clean


def test_render_menu_uniform_items():
    """导航栏固定四项（推送/拉取/文件/分支），分叉时不再切换为恢复/强制推送。"""
    menu = _strip_markup(render_menu(_info(RepoStatus.DIVERGED, ahead=1, behind=1)))
    assert "Push" in menu and "Pull" in menu and "Files" in menu
    assert "Branch" in menu
    assert "Restore" not in menu and "Force push" not in menu
    assert "[p]" not in menu and "[l]" not in menu and "[f]" not in menu  # 无快捷键标识


def test_render_menu_cursor_marks_active():
    """仅选中项带可见括号 + 底色紧贴内容（两侧各 1 格，槽内居中），未选中项裸文本。"""
    menu = render_menu(_info(RepoStatus.CLEAN), active="push")
    assert "  [bold #FFFFFF on #636363] \\[Push] [/]  " in menu
    assert "[#292929]" not in menu  # 无隐形括号
    sel = _strip_markup(menu)
    assert "[Push]" in sel and "[Pull]" not in sel and "[Files]" not in sel
    menu_right = render_menu(_info(RepoStatus.CLEAN), active="files")
    assert " [bold #FFFFFF on #636363] \\[Files] [/]  " in menu_right
    assert "[#292929]" not in menu_right
    sel_right = _strip_markup(menu_right)
    assert "[Files]" in sel_right and "[Push]" not in sel_right


def test_render_menu_sync_marks():
    """推送/拉取有待处理同步时用 `*` 包裹：CHANGED→*Push*，BEHIND→*Pull*，DIVERGED 两者都有。"""
    menu = render_menu(_info(RepoStatus.CHANGED, modified=1))
    assert "*Push*" in menu and "Pull" in menu
    assert "Files" in menu
    assert "\\[Push]" not in menu  # 无 active 时全部裸文本，无任何括号
    menu_behind = render_menu(_info(RepoStatus.BEHIND, behind=1))
    assert "Push" in menu_behind and "*Pull*" in menu_behind
    menu_div = render_menu(_info(RepoStatus.DIVERGED, ahead=1, behind=1))
    assert "*Push*" in menu_div and "*Pull*" in menu_div
    menu_clean = render_menu(_info(RepoStatus.CLEAN))
    assert "Push" in menu_clean and "Pull" in menu_clean
    assert "*" not in menu_clean  # 干净状态无任何同步标记
    # 选中项可见文本（剥 markup）为 [*Push*] / [Push]，未选中项为裸文本
    sel = _strip_markup(render_menu(_info(RepoStatus.CHANGED, modified=1),
                                    active="push"))
    assert "[*Push*]" in sel
    sel_clean = _strip_markup(render_menu(_info(RepoStatus.CLEAN), active="push"))
    assert "[Push]" in sel_clean


# ── 标签页主循环 ──
from core.config import (KEY_BACKSPACE, KEY_ENTER, KEY_LEFT, KEY_O,
                         KEY_RIGHT)
from core.events import ReleasePublished
from tests.fakes import make_services
from tui.interactive import InteractiveApp


def scripted(keys):
    it = iter(keys)
    return lambda: next(it)


def test_tab_switch_shows_content_immediately():
    """←/→ 直接切换标签并即时显示内容，全程无 Enter。"""
    svc = make_services(initialized=True, remote="x",
                        commits=["abcdef1234567890"])
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_RIGHT]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    assert app._active == "pull"
    assert "abcdef12" in "\n".join(out_lines)  # 拉取页内容已显示


def test_initial_tab_follows_recommendation():
    """BEHIND 时初始标签落拉取，内容区直接显示提交列表（无需任何按键）。"""
    svc = make_services(initialized=True, remote="x", behind=1,
                        commits=["abcdef1234567890"])
    out_lines = []
    app = InteractiveApp(svc, "fake_repo", key_source=scripted([]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    assert app._active == "pull"
    assert "abcdef12" in "\n".join(out_lines)


def test_tab_switch_wraps():
    """CLEAN 初始推送页，右移 4 次回卷回推送页。"""
    svc = make_services(initialized=True, remote="x")
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_RIGHT, KEY_RIGHT, KEY_RIGHT,
                                              KEY_RIGHT]),
                         out=lambda s: None)
    with pytest.raises(StopIteration):
        app.run()
    assert app._active == "push"


def test_backspace_is_dead_key():
    """Backspace 已废弃：按后标签不变、内容不变（无效键零输出）。"""
    svc = make_services(initialized=True, remote="x",
                        commits=["abcdef1234567890"])
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_RIGHT, KEY_BACKSPACE]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    assert app._active == "pull"               # 仍在拉取页
    assert "abcdef12" in "\n".join(out_lines)  # 内容仍是拉取视图


def test_enter_on_pull_tab_aligns_remote():
    """初始落拉取页（BEHIND），Enter 直接对齐远程（单个 Enter，无需先进入）。"""
    svc = make_services(initialized=True, remote="x", behind=1,
                        commits=["abcdef1234567890"])
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER]),
                         out=lambda s: None)
    with pytest.raises(StopIteration):
        app.run()
    assert svc.git.reset_to == "origin/main"
    assert svc.git.clean_calls == 1


def test_files_tab_switch_and_toggle(tmp_path):
    """切到文件标签即显示文件列表；Enter 忽略文件后列表重扫（按钮翻转）。"""
    (tmp_path / "a.py").write_text("x")
    svc = make_services(initialized=True, remote="x")
    svc.file_ops.repo_path = str(tmp_path)
    out_lines = []
    # 初始推送页 → → 到文件页（显示 a.py）→ Enter 忽略 → 重扫后按钮变 Push
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_RIGHT, KEY_RIGHT, KEY_ENTER]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    joined = "\n".join(out_lines)
    assert "a.py" in joined            # 切入即显示，无 Enter 进入
    assert "a.py" in svc.git.gitignore_lines  # Enter 忽略生效
    assert "Ignore" in joined          # 忽略前按钮
    assert "Push" in joined            # 重扫后按钮翻转（已忽略文件仍在列表）


def test_interactive_enter_pushes():
    svc = make_services(initialized=True, remote="x", files={"a.py": "1"})
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):  # 无退出键，按键耗尽即止
        app.run()
    assert svc.git.commits  # 确实提交了
    assert "(+1)" not in "\n".join(out_lines)  # 状态行不再显示变化计数括号


def test_interactive_invalid_key_no_repaint():
    """无效键 + 状态未变：主屏块不重复输出（差异化刷新）。"""
    svc = make_services(initialized=True, remote="x")
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([b"z", b"z"]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    joined = "\n".join(out_lines)
    # 主屏只渲染一次；后续两轮内容相同 → 零输出
    assert joined.count("Project: fake_repo") == 1


def test_release_tag_loaded_once_at_startup():
    """启动时从 gh 获取一次最新 Release 版本号，供顶栏版本行显示。"""
    svc = make_services(initialized=True, remote="x")
    svc.gh.latest_release = {"tag": "26w32a", "published_at": ""}
    out_lines = []
    app = InteractiveApp(svc, "fake_repo", key_source=scripted([]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    assert app._release_tag == "26w32a"
    assert "26w32a" in "\n".join(out_lines)  # 顶栏版本行已渲染


def test_release_tag_missing_and_failure_degrades_to_none(monkeypatch):
    """无 Release 或 gh 查询失败时版本行降级为 `-`（release_tag 为 None）。"""
    svc = make_services(initialized=True, remote="x")
    app = InteractiveApp(svc, "fake_repo", key_source=scripted([]),
                         out=lambda s: None)
    with pytest.raises(StopIteration):
        app.run()
    assert app._release_tag is None
    # 查询抛异常：同样降级为 None，不中断主循环
    svc2 = make_services(initialized=True, remote="x")
    monkeypatch.setattr(svc2.gh, "get_latest_release",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    app2 = InteractiveApp(svc2, "fake_repo", key_source=scripted([]),
                          out=lambda s: None)
    with pytest.raises(StopIteration):
        app2.run()
    assert app2._release_tag is None


def test_release_tag_refreshed_after_publish():
    """Release 发布后顶栏版本号刷新为新 tag：重新获取并定点重绘版本行（第 4 行）。"""
    svc = make_services(initialized=True, remote="x")
    svc.gh.latest_release = {"tag": "26w32a", "published_at": ""}
    out_lines = []
    app = InteractiveApp(svc, "fake_repo", key_source=scripted([]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    assert app._release_tag == "26w32a"
    # 同步发布新 Release（模拟事件派发）：版本号应刷新并定点重绘
    svc.gh.latest_release = {"tag": "26w32b", "published_at": ""}
    svc.bus.publish(ReleasePublished("26w32b", "- 新"))
    assert app._release_tag == "26w32b"
    joined = "\n".join(out_lines)
    assert "\x1b[4;1H\x1b[2K" in joined  # 定点重绘顶栏版本行
    assert "26w32b" in joined


def test_menu_sync_star_clears_after_push():
    """推送完成后状态变 CLEAN，菜单 `*` 同步标记消失（状态变化触发菜单重绘）。"""
    svc = make_services(initialized=True, remote="x", files={"a.py": "1"})
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    assert svc.git.commits  # 确实推送了
    assert app._views["push"]._push_result is True  # 结果锁定
    joined = "\n".join(out_lines)
    assert "[*Push*]" in joined  # 推送前菜单带 * 标记（CHANGED）
    menu_redraws = [ln for ln in out_lines
                    if "\x1b[2K" in ln and "[Push]" in ln]
    assert menu_redraws, "推送后应发生菜单重绘"
    assert "[*Push*]" not in menu_redraws[-1], \
        f"推送完成后 * 应消失: {menu_redraws[-1]!r}"


def test_menu_redraw_line_stable_after_remote_configured(tmp_path):
    """remote 从无到有后菜单重绘行号不漂移（顶栏布局固定），避免重行。

    复现：NO_REMOTE 启动（顶栏 7 行，菜单在第 5 行）→ Enter 推送配置 remote →
    左右键切换标签触发多次菜单重绘 → 重绘行号不漂移。
    """
    (tmp_path / "a.py").write_text("x")
    svc = make_services(initialized=True, remote=None,
                        files={"a.py": "1"})
    svc.file_ops.repo_path = str(tmp_path)
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER, KEY_RIGHT, KEY_LEFT,
                                              KEY_RIGHT, KEY_LEFT]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    assert svc.git.remote is not None  # 推送确实配置了 remote
    menu_ys = []
    for ln in out_lines:
        if "\x1b[2K" in ln and re.search(r"\[(Push|Pull)", ln):
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
    svc = make_services(initialized=True, remote="x")
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


# ── 菜单标签（← → 切换）──
def test_menu_brackets_only_on_selected():
    """仅选中项带括号：剥离标签后无 active 时无任何 `[]`，有 active 时恰一项 [X]。

    `*` 同步标记由 pad 补偿宽度，不影响括号规则（选中项仍恰一个括号对）。
    """
    for st, kw in [(RepoStatus.CLEAN, {}),
                   (RepoStatus.CHANGED, {"modified": 1}),
                   (RepoStatus.DIVERGED, {"ahead": 1, "behind": 1})]:
        base = _strip_markup(render_menu(_info(st, **kw)))  # active=None 全未选中
        assert "[" not in base and "]" not in base, f"{st.name}: {base!r}"
        for active in ("push", "pull", "files", "branch"):
            t = _strip_markup(render_menu(_info(st, **kw), active=active))
            assert t.count("[") == 1 and t.count("]") == 1, \
                f"{st.name} active={active}: {t!r}"
            name = {"push": "Push", "pull": "Pull",
                    "files": "Files", "branch": "Branch"}[active]
            # 选中项恰一个括号对；带 * 时括号包住 *文本*（星逻辑由 sync_marks 测试覆盖）
            assert f"[{name}]" in t or f"[*{name}*]" in t, \
                f"{st.name} active={active}: {t!r}"


def test_menu_widths_selected_vs_unselected():
    """四项槽位等宽（12 列），行总宽恒 48，与选中项/同步标记无关。

    框选左右移动、`*` 增减只改槽内留白：未选中项文本列位置在任何
    active 下零偏移；自身被选中时仅槽内居中位置微调（括号 +2）。
    """
    for st, kw in [(RepoStatus.CLEAN, {}),
                   (RepoStatus.CHANGED, {"modified": 1}),
                   (RepoStatus.DIVERGED, {"ahead": 1, "behind": 1})]:
        base = _strip_markup(render_menu(_info(st, **kw)))  # active=None 全未选中
        assert len(base) == 48, f"{st.name}: {base!r} len={len(base)}"
        for active in ("push", "pull", "files", "branch"):
            text = _strip_markup(render_menu(_info(st, **kw), active=active))
            assert len(text) == 48, \
                f"{st.name} active={active}: {text!r} len={len(text)}"
    # 未选中项位置不受框选影响：Pull 列位置在 active=push/files/None 下一致
    positions = {_strip_markup(render_menu(_info(RepoStatus.CLEAN),
                                           active=a)).find("Pull")
                 for a in (None, "push", "files")}
    assert len(positions) == 1, f"Pull 位置漂移: {positions}"
    positions = {_strip_markup(render_menu(_info(RepoStatus.CLEAN),
                                           active=a)).find("Push")
                 for a in (None, "pull", "files")}
    assert len(positions) == 1, f"Push 位置漂移: {positions}"


# ── 文件行渲染（_render_row 纯函数）──
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


# ── 无回显化：文件操作与推送状态机 ──
def test_file_ops_push_file_returns_bool():
    """push_file 返回 bool：推送失败 False，成功 True。"""
    svc = make_services(initialized=True, remote="x")
    svc.git.fail_mode = "network"  # 持久推送失败
    assert svc.file_ops.push_file("a.py") is False
    svc.git.fail_mode = "ok"
    assert svc.file_ops.push_file("b.py") is True


def test_push_marks_progress_then_done():
    """按 Enter 推送：文件标记先 [·] 后 [✓]，且无 ActionLog 回显。"""
    svc = make_services(initialized=True, remote="x", files={"a.py": "1", "b.py": "2"})
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    joined = "\n".join(out_lines)
    assert "[·]" in joined  # 上传中标记出现过（带方括号）
    assert "[✓]" in joined  # 完成标记出现（带方括号）
    assert "Scanning changes" not in joined  # 无 ActionLog 过程回显
    assert svc.git.commits   # 确实推送了


def test_push_failure_marks_error_no_reason():
    """推送失败：所有文件 [✕]，不显示失败原因（完全无回显）。"""
    svc = make_services(initialized=True, remote="x", files={"a.py": "1"})
    svc.git.fail_mode = "network"  # 持久推送失败 → SyncError
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    joined = "\n".join(out_lines)
    assert "[✕]" in joined
    assert "unable to access" not in joined  # 无失败原因
    assert "Scanning changes" not in joined  # 无过程回显


def test_push_no_changes_no_status_markers():
    """无待推文件（如仅初始化仓库）时不显示状态标记，仍正常执行。"""
    svc = make_services(initialized=False, remote=None)
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    joined = "\n".join(out_lines)
    assert "·" not in joined and "✓" not in joined
    assert svc.git.initialized  # 仓库已初始化


def test_push_ahead_clean_tree_shows_placeholder():
    """AHEAD 且工作区干净（变更已提交未推送）：推送视图显示本地提交占位行而非空白。"""
    # ahead=1 + 无 files → porcelain 为空 → 状态 AHEAD，工作区干净
    svc = make_services(initialized=True, remote="x", ahead=1)
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    joined = "\n".join(out_lines)
    assert "[·]" in joined  # 上传中占位标记
    assert "[✓]" in joined  # 完成标记
    assert "1 local commit" in joined  # 占位行表达推送本地提交


def test_push_result_cleared_after_tab_switch():
    """推送结果 [✓] 常驻于推送页；切出再切入后清除（重扫为干净清单）。"""
    svc = make_services(initialized=True, remote="x", files={"a.py": "1"})
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER, KEY_RIGHT, KEY_LEFT]),
                         out=out_lines.append)
    with pytest.raises(StopIteration):
        app.run()
    assert app._views["push"]._push_result is False  # 切出已清锁定
    assert "[✓]" not in app._view  # 切回推送页后重扫，结果视图已消失


def test_push_result_cleared_on_empty_push():
    """推送结果锁定期间再次按 Enter（无可推内容）：旧结果清除，重扫为空。"""
    svc = make_services(initialized=True, remote="x", files={"a.py": "1"})
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER, KEY_ENTER]),
                         out=out_lines.append,
                         cooldown=0)  # 测试连按语义，关闭冷却期
    with pytest.raises(StopIteration):
        app.run()
    assert app._views["push"]._push_result is False
    assert "[✓]" not in app._view


def test_enter_swallowed_during_cooldown():
    """冷却期：动作执行后 1 秒内连按 Enter 被吞掉（防连按重复执行）。"""
    svc = make_services(initialized=True, remote="x", files={"a.py": "1"})
    out_lines = []
    app = InteractiveApp(svc, "fake_repo",
                         key_source=scripted([KEY_ENTER, KEY_ENTER]),
                         out=out_lines.append)  # 默认 cooldown=1.0
    with pytest.raises(StopIteration):
        app.run()
    # 第二个 Enter 被吞：推送结果锁定未清除（空推送清锁定逻辑未触发）
    assert app._views["push"]._push_result is True
    assert "[✓]" in app._view
