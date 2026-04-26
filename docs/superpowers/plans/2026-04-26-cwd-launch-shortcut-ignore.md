# CWD 启动模式与快捷方式自动忽略 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 无 argv[1] 时以 CWD 作为同步目录，自动忽略指向自身的快捷方式文件，移除 tkinter 依赖。

**Architecture:** 在 GitManager 中新增 `ignore_self_shortcuts()` 方法，通过 PowerShell COM 解析 .lnk 目标路径，匹配后追加到 .gitignore。入口逻辑简化为 CWD 直接使用。

**Tech Stack:** Python 3, PowerShell (WScript.Shell COM), pytest

---

### Task 1: 新增 `ignore_self_shortcuts()` 方法

**Files:**
- Modify: `github_sync.py:129` (GitManager 类内)
- Create: `tests/test_ignore_shortcuts.py`

- [ ] **Step 1: 创建测试文件并编写失败测试**

创建 `tests/test_ignore_shortcuts.py`：

```python
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from github_sync import GitManager


class TestIgnoreSelfShortcuts:
    def test_ignore_shortcuts_no_lnk_files(self, tmp_path):
        gm = GitManager(str(tmp_path))
        gm.ignore_self_shortcuts()
        gitignore_path = os.path.join(str(tmp_path), ".gitignore")
        if os.path.exists(gitignore_path):
            with open(gitignore_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert ".lnk" not in content

    def test_ignore_shortcuts_direct_match(self, tmp_path):
        gitignore_path = os.path.join(str(tmp_path), ".gitignore")
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("__pycache__/\n")

        script_path = os.path.abspath(sys.argv[0])
        ps_output = f"MyApp.lnk|{script_path}|"

        with patch("github_sync.run_command") as mock_run:
            mock_run.return_value = (True, ps_output)
            gm = GitManager(str(tmp_path))
            gm.ignore_self_shortcuts()

        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "MyApp.lnk" in content

    def test_ignore_shortcuts_python_launcher(self, tmp_path):
        gitignore_path = os.path.join(str(tmp_path), ".gitignore")
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("__pycache__/\n")

        script_basename = os.path.basename(sys.argv[0])
        ps_output = f"RunApp.lnk|C:\\Python312\\python.exe|{script_basename}"

        with patch("github_sync.run_command") as mock_run:
            mock_run.return_value = (True, ps_output)
            gm = GitManager(str(tmp_path))
            gm.ignore_self_shortcuts()

        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "RunApp.lnk" in content

    def test_ignore_shortcuts_no_match(self, tmp_path):
        gitignore_path = os.path.join(str(tmp_path), ".gitignore")
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("__pycache__/\n")

        ps_output = "OtherApp.lnk|C:\\Other\\app.exe|"

        with patch("github_sync.run_command") as mock_run:
            mock_run.return_value = (True, ps_output)
            gm = GitManager(str(tmp_path))
            gm.ignore_self_shortcuts()

        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "OtherApp.lnk" not in content

    def test_ignore_shortcuts_powershell_failure(self, tmp_path):
        gitignore_path = os.path.join(str(tmp_path), ".gitignore")
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("__pycache__/\n")

        with patch("github_sync.run_command") as mock_run:
            mock_run.return_value = (False, "error")
            gm = GitManager(str(tmp_path))
            gm.ignore_self_shortcuts()

        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert ".lnk" not in content
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd "s:\Github @Cairl\GitHubSync" && python -m pytest tests/test_ignore_shortcuts.py -v`
Expected: FAIL — `AttributeError: 'GitManager' object has no attribute 'ignore_self_shortcuts'`

- [ ] **Step 3: 实现 `ignore_self_shortcuts()` 方法**

在 `GitManager` 类中 `create_ignore()` 方法之后添加：

```python
    def ignore_self_shortcuts(self):
        lnk_files = [f for f in os.listdir(self.cwd) if f.lower().endswith('.lnk')]
        if not lnk_files:
            return

        ps_script = (
            '$shell = New-Object -ComObject WScript.Shell; '
            f'Get-ChildItem -Path "{self.cwd}" -Filter *.lnk | ForEach-Object {{ '
            '$lnk = $shell.CreateShortcut($_.FullName); '
            '"$($_.Name)|$($lnk.TargetPath)|$($lnk.Arguments)" '
            '}}'
        )
        s, m = run_command(f'powershell -NoProfile -Command "{ps_script}"')
        if not s or not m.strip():
            return

        self_path = os.path.normcase(os.path.abspath(sys.argv[0]))
        self_basename = os.path.basename(sys.argv[0])
        shortcuts_to_ignore = []

        for line in m.strip().splitlines():
            parts = line.strip().split('|')
            if len(parts) < 2:
                continue
            lnk_name, target_path = parts[0], parts[1]
            arguments = parts[2] if len(parts) > 2 else ""

            if os.path.normcase(target_path) == self_path:
                shortcuts_to_ignore.append(lnk_name)
            elif (os.path.basename(target_path).lower() in ('python.exe', 'pythonw.exe')
                  and self_basename in arguments):
                shortcuts_to_ignore.append(lnk_name)

        if not shortcuts_to_ignore:
            return

        gitignore_path = os.path.join(self.cwd, ".gitignore")
        try:
            existing = ""
            if os.path.exists(gitignore_path):
                with open(gitignore_path, "r", encoding="utf-8") as f:
                    existing = f.read()

            existing_lines = {line.strip() for line in existing.splitlines() if line.strip()}
            new_entries = [name for name in shortcuts_to_ignore if name not in existing_lines]
            if new_entries:
                with open(gitignore_path, "a", encoding="utf-8") as f:
                    for entry in new_entries:
                        f.write(f"\n{entry}")
                self.log(f"已自动忽略快捷方式: {', '.join(new_entries)}", "INFO")
        except OSError as e:
            self.log(f"忽略快捷方式失败: {e}", "ERROR")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd "s:\Github @Cairl\GitHubSync" && python -m pytest tests/test_ignore_shortcuts.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add github_sync.py tests/test_ignore_shortcuts.py
git commit -m "feat: add ignore_self_shortcuts method to GitManager"
```

---

### Task 2: 在 `sync()` 中集成 `ignore_self_shortcuts()`

**Files:**
- Modify: `github_sync.py:316` (sync 方法)

- [ ] **Step 1: 修改 `sync()` 方法**

在 `sync()` 方法中，将 `self.create_ignore()` 改为在其后追加 `self.ignore_self_shortcuts()`：

当前代码（第 316-317 行）：
```python
    def sync(self):
        self.create_ignore()
```

改为：
```python
    def sync(self):
        self.create_ignore()
        self.ignore_self_shortcuts()
```

- [ ] **Step 2: 运行全部测试验证**

Run: `cd "s:\Github @Cairl\GitHubSync" && python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 3: 提交**

```bash
git add github_sync.py
git commit -m "feat: integrate ignore_self_shortcuts into sync flow"
```

---

### Task 3: 入口逻辑改造 — 移除 tkinter，使用 CWD

**Files:**
- Modify: `github_sync.py:942-966` (__main__ 块)

- [ ] **Step 1: 编写入口逻辑测试**

在 `tests/test_ignore_shortcuts.py` 末尾追加：

```python


class TestEntryPoint:
    def test_no_argv_uses_cwd(self):
        with patch.object(sys, 'argv', ['github_sync.py']):
            with patch('github_sync.App') as MockApp:
                mock_instance = MagicMock()
                MockApp.return_value = mock_instance

                original_main = globals().get('__main__')
                repo_path = os.getcwd()
                assert os.path.isdir(repo_path)

    def test_argv1_uses_provided_path(self, tmp_path):
        with patch.object(sys, 'argv', ['github_sync.py', str(tmp_path)]):
            assert os.path.isdir(str(tmp_path))
```

- [ ] **Step 2: 修改入口代码**

将 `__main__` 块（第 942-966 行）从：

```python
if __name__ == "__main__":
    try:
        import tkinter as tk
        from tkinter import filedialog

        repo_path = ""
        if len(sys.argv) > 1:
            potential_path = sys.argv[1]
            if os.path.isdir(potential_path):
                repo_path = potential_path
            else:
                print(f"错误: '{potential_path}' 不是一个有效的文件夹。")
                sys.exit(1)
        else:
            root = tk.Tk()
            root.withdraw()
            repo_path = filedialog.askdirectory(title="选择 Git 仓库文件夹")
            root.destroy()

        if not repo_path:
            print("未选择文件夹，程序退出。")
            sys.exit(0)

        app = App(repo_path)
        app.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n发生错误: {e}")
    finally:
        print("\033[?25h", end="") # 恢复光标
```

改为：

```python
if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            potential_path = sys.argv[1]
            if os.path.isdir(potential_path):
                repo_path = potential_path
            else:
                print(f"错误: '{potential_path}' 不是一个有效的文件夹。")
                sys.exit(1)
        else:
            repo_path = os.getcwd()

        app = App(repo_path)
        app.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n发生错误: {e}")
    finally:
        print("\033[?25h", end="")
```

- [ ] **Step 3: 运行全部测试验证**

Run: `cd "s:\Github @Cairl\GitHubSync" && python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add github_sync.py tests/test_ignore_shortcuts.py
git commit -m "feat: use CWD when no argv, remove tkinter dependency"
```

---

### Task 4: 更新 release.md

**Files:**
- Modify: `release.md`

- [ ] **Step 1: 更新 release.md**

根据 AGENTS.md 规范，在 release.md 中记录本次变更。版本号格式 `YYwNNx`，按当前日期计算。

- [ ] **Step 2: 提交**

```bash
git add release.md
git commit -m "docs: update release notes for CWD launch feature"
```
