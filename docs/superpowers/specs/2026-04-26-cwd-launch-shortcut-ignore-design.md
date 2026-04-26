# CWD 启动模式与快捷方式自动忽略

## 背景

当前程序无 `argv[1]` 时会弹出 tkinter 文件选择对话框。用户希望直接启动程序（双击或快捷方式）时，自动以当前工作目录作为同步目标，并自动忽略指向自身的快捷方式文件。

## 需求

1. 无 `argv[1]` 时，使用 `os.getcwd()` 作为 `repo_path`
2. 自动检测 CWD 中指向自身程序的 `.lnk` 快捷方式，将其加入 `.gitignore`
3. 完全移除 tkinter 依赖

## 设计

### 入口逻辑改造

**文件**: `github_sync.py` `__main__` 块（第 942-966 行）

改造前：
- `argv[1]` 存在 → 用传入路径
- `argv[1]` 不存在 → tkinter 文件对话框

改造后：
- `argv[1]` 存在 → 用传入路径（不变）
- `argv[1]` 不存在 → `repo_path = os.getcwd()`

删除 `import tkinter` 和 `filedialog` 相关代码。不再需要"未选择文件夹"的退出逻辑。

### 快捷方式检测与自动忽略

**新增方法**: `GitManager.ignore_self_shortcuts()`

**流程**：

1. 扫描 CWD 下所有 `.lnk` 文件
2. 用 PowerShell 批量解析每个 `.lnk` 的目标路径
3. 将目标路径与程序自身路径（`sys.argv[0]` 绝对路径）比对
4. 匹配的 `.lnk` 文件名追加到 `.gitignore`

**PowerShell 命令**：

```powershell
$shell = New-Object -ComObject WScript.Shell
Get-ChildItem -Path "<cwd>" -Filter *.lnk | ForEach-Object {
    $lnk = $shell.CreateShortcut($_.FullName)
    "$($_.Name)|$($lnk.TargetPath)|$($lnk.Arguments)"
}
```

输出格式：`文件名.lnk|目标绝对路径|参数`，逐行解析。

**匹配逻辑**：

两种匹配场景：

1. **直接指向程序**：`TargetPath` 与 `os.path.abspath(sys.argv[0])` 精确匹配
2. **通过 Python 启动**：`TargetPath` 以 `python.exe` 或 `pythonw.exe` 结尾，且 `Arguments` 包含程序文件名（`os.path.basename(sys.argv[0])`）

匹配时使用 `os.path.normcase()` 处理 Windows 路径大小写不敏感。

**集成位置**：在 `sync()` 中 `create_ignore()` 之后调用 `ignore_self_shortcuts()`。

### 错误处理

- PowerShell 执行失败时静默跳过，不阻塞同步主流程
- 无 `.lnk` 文件时直接返回，不执行 PowerShell
- `.gitignore` 写入失败时记录日志，不阻塞

## 影响范围

- `github_sync.py` 入口块：移除 tkinter，改用 CWD
- `GitManager`：新增 `ignore_self_shortcuts()` 方法
- `GitManager.sync()`：在 `create_ignore()` 后调用新方法
- 移除 `import tkinter` 相关代码
