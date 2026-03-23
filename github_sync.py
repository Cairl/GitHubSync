import os
import sys

if sys.platform != "win32":
    print("此工具仅支持 Windows 平台。")
    sys.exit(1)

import subprocess
import time
import msvcrt
import shutil
import unicodedata
import re
import atexit
from datetime import datetime

# 确保退出时恢复终端光标（包括异常退出）
atexit.register(lambda: print("\033[?25h", end="", flush=True))

# ==========================================
#              工具函数
# ==========================================

def get_display_width(text):
    """计算字符串在终端的显示宽度（中文占2，英文占1）"""
    width = 0
    for char in text:
        if unicodedata.east_asian_width(char) in ('F', 'W'):
            width += 2
        else:
            width += 1
    return width

def strip_ansi(text):
    """移除所有 ANSI 转义序列和 OSC 超链接"""
    # 移除 OSC 序列 (包括超链接 \033]8;;...\033\\)
    text = re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)', '', text)
    # 移除 CSI 序列 (ANSI 颜色等 \033[...m)
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    return text

def get_input_with_default(prompt, default_val=""):
    """
    带预填充文本的输入框实现。
    用户可以直接按回车使用默认值，也可以退格修改。
    """
    sys.stdout.write(prompt + default_val)
    sys.stdout.flush()
    
    res = list(default_val)
    while True:
        try:
            char = msvcrt.getwch()
        except Exception:
            continue
            
        if char == '\r': # Enter
            sys.stdout.write('\n')
            return "".join(res)
        elif char == '\x08': # Backspace
            if res:
                last_char = res.pop()
                # 根据字符宽度回退
                width = get_display_width(last_char)
                sys.stdout.write('\b' * width + ' ' * width + '\b' * width)
                sys.stdout.flush()
        elif char == '\x1b': # ESC
            sys.stdout.write('\n')
            return ""
        elif char == '\x00' or char == '\xe0': # Special keys
            msvcrt.getwch() # Consume the next character
        else:
            if char.isprintable():
                res.append(char)
                sys.stdout.write(char)
                sys.stdout.flush()

# ==========================================
#              TUI 框架
# ==========================================

class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[38;2;243;139;168m"      # 淡红色 #F38BA8
    GREEN = "\033[38;2;166;227;161m"    # 淡绿色 #A6E3A1
    YELLOW = "\033[38;2;249;226;175m"   # 淡黄色 #F9E2AF
    BLUE = "\033[38;2;137;180;250m"     # 淡蓝色 #89B4FA
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    STRIKETHROUGH = "\033[9m"
    BG_BLUE = "\033[48;2;69;71;90m"     # 选中的背景色 (柔和深灰色/蓝灰色)
    BG_RESET = "\033[49m"

class Keys:
    UP = b'H'
    DOWN = b'P'
    LEFT = b'K'
    RIGHT = b'M'
    ENTER = b'\r'
    ESC = b'\x1b'

def init_console():
    os.system("")  # 启用 Windows VT100
    os.system("cls")
    print("\033[?25l", end="", flush=True) # 隐藏光标

def clear_screen():
    print("\033[H\033[J", end="") 

def get_key():
    key = msvcrt.getch()
    if key in (b'\xe0', b'\x00'): 
        return msvcrt.getch()
    return key

# ==========================================
#              Git 逻辑
# ==========================================

def run_command(command, cwd=None):
    try:
        result = subprocess.run(
            command, cwd=cwd, shell=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace'
        )
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        # 合并 stdout 和 stderr 以获取完整错误信息
        msg = (e.stdout.strip() + "\n" + e.stderr.strip()).strip()
        return False, msg

class GitManager:
    def __init__(self, repo_path, on_log=None):
        self.cwd = repo_path
        self.logs = []
        self.on_log = on_log
        self.frozen_changes = None
        self.updated_items = {}  # { name: status_char } 'A'=Added/Modified, 'D'=Deleted

    def log(self, msg, type="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = Colors.RESET
        if type == "SUCCESS": 
            color = Colors.GREEN
        if type == "ERROR": 
            color = Colors.RED
        if type == "WARN": 
            color = Colors.YELLOW
        
        entry = f"{Colors.DIM}[{timestamp}]{Colors.RESET} {color}{msg}{Colors.RESET}"
        self.logs.append(entry)

        if self.on_log:
            self.on_log()

    def get_status(self):
        if not os.path.exists(os.path.join(self.cwd, ".git")):
            return {"initialized": False}

        # 使用更兼容的方式获取分支名
        s, branch = run_command("git rev-parse --abbrev-ref HEAD", cwd=self.cwd)
        if not s or branch == "HEAD":
            s, branch = run_command("git branch --show-current", cwd=self.cwd)
        
        branch = branch.strip() if s and branch.strip() else "main"

        s, remote_out = run_command("git remote -v", cwd=self.cwd)
        remote = "未配置"
        if s and "origin" in remote_out:
            parts = remote_out.split()
            if len(parts) > 1:
                remote = parts[1]

        return {
            "initialized": True,
            "branch": branch,
            "remote": remote
        }
    def init_repo(self):
        self.log("正在初始化 Git 仓库", "INFO")
        s, m = run_command("git init", cwd=self.cwd)
        if s: self.log("Git 仓库初始化成功", "SUCCESS")
        else: self.log(f"初始化失败: {m}", "ERROR")

    def create_ignore(self):
        gitignore_path = os.path.join(self.cwd, ".gitignore")
        if os.path.exists(gitignore_path):
            return
        
        content = "__pycache__/\n*.pyc\n.env\n.DS_Store\n.vscode/\n.idea/\ndist/\nbuild/\n*.spec\nvenv/\n"
        try:
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.log("已创建默认 .gitignore", "SUCCESS")
        except Exception as e:
            self.log(f"创建失败: {e}", "ERROR")

    def get_github_username(self):
        """尝试获取当前登录的 GitHub 用户名"""
        # 1. 尝试使用 gh CLI
        s, m = run_command("gh api user -q .login")
        if s and m and len(m) < 40: return m.strip()
        
        # 2. 尝试从本地 git remote 推测
        s, m = run_command("git remote -v", cwd=self.cwd)
        if "github.com" in m:
            match = re.search(r"github\.com[:/]([^/ \n\r]+)/", m)
            if match: return match.group(1).split('@')[-1] # 处理 https://token@github.com/user 格式
        
        # 3. 兜底: 检查同级目录的 git 配置
        try:
            parent_dir = os.path.dirname(self.cwd)
            # 优先检查已知的成功案例
            for folder in os.listdir(parent_dir):
                folder_path = os.path.join(parent_dir, folder)
                if not os.path.isdir(folder_path) or folder.startswith('.'):
                    continue
                
                try:
                    dot_git = os.path.join(folder_path, ".git")
                    if os.path.exists(dot_git):
                        # 使用 -C 配合引号处理空格路径
                        s, m = run_command(f'git -C "{folder_path}" remote -v')
                        if s and "github.com" in m:
                            match = re.search(r"github\.com[:/]([^/ \n\r]+)/", m)
                            if match:
                                user = match.group(1).split('@')[-1]
                                if user and user != "git": return user
                except Exception:
                    continue
        except Exception: pass
        
        return None

    def configure_remote(self):
        username = self.get_github_username()
        repo_name = os.path.basename(self.cwd)
        default_url = f"https://github.com/{username}/{repo_name}" if username else ""
        
        print("\033[?25h", end="", flush=True) # 显示光标
        timestamp = datetime.now().strftime("%H:%M:%S")
        sys.stdout.write(f" {Colors.YELLOW}[{timestamp}] 正在配置远程仓库: {Colors.RESET}")
        url = get_input_with_default("", default_url).strip()
        print("\033[?25l", end="", flush=True) # 隐藏光标

        if not url:
            self.log("未输入 URL，操作取消", "WARN")
            return
        s, m = run_command(f"git remote add origin {url}", cwd=self.cwd)
        if not s: 
            s, m = run_command(f"git remote set-url origin {url}", cwd=self.cwd)
        
        if s: self.log(f"远程仓库已设置为: {url}", "SUCCESS")
        else: self.log(f"设置远程失败: {m}", "ERROR")

    def sync(self):
        self.create_ignore()
        
        status = self.get_status()
        if not status["initialized"]:
            self.init_repo()
            status = self.get_status()
        
        self.log("正在扫描文件", "INFO")
        s, m = run_command("git add .", cwd=self.cwd)
        if not s:
            self.log(f"文件暂存失败: {m}", "ERROR")
            return

        s, st = run_command("git status --porcelain", cwd=self.cwd)
        self.updated_items = {}
        if st:
            for line in st.splitlines():
                if len(line) > 3:
                    # git status --porcelain 输出格式如 "M  file" 或 "R  old -> new"
                    status_char = line[0] if line[0] != ' ' else line[1]
                    path = line[3:].strip().strip('"')
                    if " -> " in path:
                        path = path.split(" -> ")[-1].strip().strip('"')
                    
                    # 提取当前层级的目录或文件名
                    parts = re.split(r'[\\/]', path)
                    if parts:
                        name = parts[0]
                        # 映射状态：D 为删除，其他（A, M, R, ?）统一视为添加/修改 (+)
                        final_status = 'D' if status_char == 'D' else 'A'
                        self.updated_items[name] = final_status
            
            msg = f"Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            self.log("正在提交", "INFO")
            s, m = run_command(f'git commit -m "{msg}"', cwd=self.cwd)
            if not s:
                self.log(f"提交失败: {m}", "ERROR")
                return
        else:
            self.log("没有更改需要提交", "INFO")

        if status["remote"] == "未配置":
            self.configure_remote()
            status = self.get_status()
            if status["remote"] == "未配置":
                return
        
        run_command("git branch -M main", cwd=self.cwd)
        self.log("正在推送到 GitHub", "INFO")
        s, m = run_command("git push -u origin main", cwd=self.cwd)
        
        if s:
            self.log("同步成功", "SUCCESS")
        else:
            if "repository not found" in m.lower() or "does not exist" in m.lower() or "404" in m:
                if self.create_github_repo():
                    self.log("正在重新推送", "INFO")
                    s, m = run_command("git push -u origin main", cwd=self.cwd)
                    if s:
                        self.log("同步成功", "SUCCESS")
                        return
            
            if "rejected" in m or "fetch first" in m:
                self.log("检测到冲突，尝试自动合并", "WARN")
                s_pull, m_pull = run_command("git pull origin main --rebase", cwd=self.cwd)
                if s_pull:
                    self.log("合并成功，重新推送", "INFO")
                    s_push, m_push = run_command("git push -u origin main", cwd=self.cwd)
                    if s_push:
                        self.log("同步成功 (已合并)", "SUCCESS")
                        return
                    else:
                        self.log(f"合并后推送失败: {m_push}", "ERROR")
                else:
                    self.log("自动合并失败，尝试强制推送", "WARN")
                    run_command("git rebase --abort", cwd=self.cwd)
            
            self.force_push()
    
    def create_github_repo(self):
        """打开浏览器创建 GitHub 仓库，自动检测创建完成"""
        import webbrowser

        repo_name = os.path.basename(self.cwd)
        username = self.get_github_username()

        if username:
            url = f"https://github.com/new?name={repo_name}"
        else:
            url = "https://github.com/new"

        webbrowser.open(url)

        self.log("等待仓库创建", "WARN")

        remote_url = f"https://github.com/{username}/{repo_name}" if username else ""
        if not remote_url:
            self.log("无法确定仓库地址", "ERROR")
            return False

        max_wait = 300  # 最多等待5分钟
        waited = 0
        while waited < max_wait:
            time.sleep(3)
            waited += 3
            # 使用 gh api 检查仓库是否存在（支持私有仓库）
            s, m = run_command(f'gh repo view {username}/{repo_name}')
            if s:
                self.log("检测到仓库已创建", "SUCCESS")
                break
            if self.on_log:
                self.on_log()
        else:
            self.log("等待仓库创建超时（5分钟）", "ERROR")
            return False

        # 静默删除 .git 并重新初始化，确保新仓库同步干净
        dot_git_path = os.path.join(self.cwd, ".git")
        if os.path.exists(dot_git_path):
            run_command('rmdir /s /q .git', cwd=self.cwd)
            if os.path.exists(dot_git_path):
                shutil.rmtree(dot_git_path, ignore_errors=True)

        run_command("git init", cwd=self.cwd)
        run_command("git add .", cwd=self.cwd)
        run_command(f'git commit -m "Initial sync {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}"', cwd=self.cwd)
        run_command("git branch -M main", cwd=self.cwd)
        run_command(f"git remote add origin {remote_url}", cwd=self.cwd)

        return True

    def force_push(self):
        s, m = run_command("git push -u origin main --force", cwd=self.cwd)
        if s: self.log("强制推送成功", "SUCCESS")
        else: self.log(f"强制推送失败: {m}", "ERROR")

# ==========================================
#              TUI 应用程序
# ==========================================

class App:
    def __init__(self, repo_path):
        self.git = GitManager(repo_path, on_log=self.render)
        self.running = True
        self.selected_index = 0
        self.action_index = 0  # 0: 文件类型, 1: 删除
        self.options = []
        self.refresh_file_list()
        self.first_sync_done = False
        self.last_lines = []
        self.timeout_seconds = 60
        self.deadline = time.time() + 60
        self.operation_in_progress = False  # 操作进行中标志
        self.cooldown_until = 0  # 冷却时间截止时间

    def refresh_file_list(self):
        """刷新当前目录的文件列表到菜单"""
        self.options = []
        try:
            items = os.listdir(self.git.cwd)
            dirs = []
            files = []
            for item in items:
                if item == ".git": continue
                if os.path.isdir(os.path.join(self.git.cwd, item)):
                    dirs.append(item)
                else:
                    files.append(item)
            
            dirs.sort()
            files.sort()
            
            gitignore_path = os.path.join(self.git.cwd, ".gitignore")
            ignored_items = set()
            if os.path.exists(gitignore_path):
                with open(gitignore_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            ignored_items.add(line.rstrip("/"))
            
            for d in dirs:
                self.options.append({
                    "name": d, 
                    "action": lambda n=d: self.confirm_delete(n),
                    "ignored": d in ignored_items
                })
            for f in files:
                self.options.append({
                    "name": f, 
                    "action": lambda n=f: self.confirm_delete(n),
                    "ignored": f in ignored_items
                })
                
            if not self.options:
                self.options.append({"name": "(空目录)", "action": lambda: None, "ignored": False})
                
            if self.selected_index >= len(self.options):
                self.selected_index = 0
                
        except Exception as e:
            self.git.log(f"刷新文件列表失败: {e}", "ERROR")

    def delete_selected(self):
        """删除或推送选中的文件"""
        option = self.options[self.selected_index]
        item_name = option["name"]

        if item_name == "(空目录)":
            return

        self.operation_in_progress = True
        try:
            if option.get("ignored", False):
                self.push_to_github(item_name)
            else:
                self.remove_from_github(item_name)
        finally:
            self.operation_in_progress = False
            # 操作完成后添加冷却时间，忽略这段时间内的按键
            self.cooldown_until = time.time() + 1.0  # 1秒冷却时间
    
    def remove_from_github(self, item_name):
        """从 GitHub 仓库删除文件并添加到忽略"""
        self.git.log(f"正在删除: {item_name}", "INFO")
        
        s, m = run_command(f'git ls-files "{item_name}"', cwd=self.git.cwd)
        if s and m.strip():
            s, m = run_command(f'git rm -r --cached "{item_name}"', cwd=self.git.cwd)
            if not s:
                self.git.log(f"删除失败: {m}", "ERROR")
                return
        
        self.add_to_gitignore(item_name)
        run_command('git add .gitignore', cwd=self.git.cwd)
        
        msg = f"Delete: {item_name}"
        s, m = run_command(f'git commit -m "{msg}"', cwd=self.git.cwd)
        if not s and "nothing to commit" not in m.lower() and "no changes added to commit" not in m.lower():
            self.git.log(f"提交失败: {m}", "ERROR")
            return
        
        if s:
            # 明确推送到当前或 main 分支
            status = self.git.get_status()
            branch = status.get("branch", "main")
            if branch == "未知" or not branch: branch = "main"
            
            s, m = run_command(f"git push origin {branch}", cwd=self.git.cwd)
            if not s:
                self.git.log(f"推送失败: {m}", "ERROR")
        
        self.refresh_file_list() # 同步 UI 状态
        self.git.updated_items[item_name] = 'D'
        self.git.log(f"已删除: {item_name}", "SUCCESS")
    
    def push_to_github(self, item_name):
        """从忽略列表移除并推送到 GitHub"""
        self.git.log(f"正在推送: {item_name}", "INFO")
        
        self.remove_from_gitignore(item_name)
        
        # 同时 stage gitignore 变更和目标文件
        run_command('git add .gitignore', cwd=self.git.cwd)
        run_command(f'git add "{item_name}"', cwd=self.git.cwd)
        
        msg = f"Add: {item_name}"
        s, m = run_command(f'git commit -m "{msg}"', cwd=self.git.cwd)
        if not s and "nothing to commit" not in m.lower() and "no changes added to commit" not in m.lower():
            self.git.log(f"提交失败: {m}", "ERROR")
            self.refresh_file_list()
            return
        
        if not s:
            self.git.log("没有新文件需要推送", "WARN")
            self.refresh_file_list()
            return
        
        # 明确推送到当前或 main 分支
        status = self.git.get_status()
        branch = status.get("branch", "main")
        if branch == "未知" or not branch: branch = "main"
        
        s, m = run_command(f"git push origin {branch}", cwd=self.git.cwd)
        if s:
            self.git.log(f"已推送: {item_name}", "SUCCESS")
            self.git.updated_items[item_name] = 'A'
        else:
            self.git.log(f"推送失败: {m}", "ERROR")
        
        self.refresh_file_list() # 同步 UI 状态
    
    def add_to_gitignore(self, item_name):
        """将文件或文件夹添加到 .gitignore"""
        gitignore_path = os.path.join(self.git.cwd, ".gitignore")
        try:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write(f"\n{item_name}\n")
        except Exception as e:
            self.git.log(f"添加忽略失败: {e}", "ERROR")
    
    def remove_from_gitignore(self, item_name):
        """从 .gitignore 移除文件或文件夹"""
        gitignore_path = os.path.join(self.git.cwd, ".gitignore")
        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            new_lines = [line for line in lines if line.strip().rstrip("/") != item_name]
            
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            
        except Exception as e:
            self.git.log(f"移除忽略失败: {e}", "ERROR")

    def open_remote(self):
        """在浏览器中打开远程仓库"""
        import webbrowser
        status = self.git.get_status()
        if status["initialized"] and status["remote"] != "未配置":
            remote_url = status["remote"]
            # 确保是完整的 URL
            if not remote_url.startswith("http"):
                remote_url = f"https://{remote_url.replace('git@', '').replace(':', '/')}"
            webbrowser.open(remote_url)
            self.git.log(f"已打开: {remote_url}", "SUCCESS")
        else:
            self.git.log("未配置远程仓库", "WARN")

    def confirm_delete(self, item_name):
        """确认并删除文件或文件夹"""
        path = os.path.join(self.git.cwd, item_name)
        
        self.git.log(f"确定删除 '{item_name}' 吗？(按回车确认，Esc/Q 取消)", "WARN")
        self.render()
        
        key = get_key()
        if key == Keys.ENTER:
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                self.git.log(f"已从本地磁盘物理删除: {item_name}", "SUCCESS")
                self.refresh_file_list()
            except Exception as e:
                self.git.log(f"物理删除失败: {e}", "ERROR")
        else:
            self.git.log("取消删除操作", "INFO")

    def get_box_lines(self, content_lines, color=Colors.CYAN):
        lines = []
        # 设定框的总宽度（显示宽度）
        box_width = 60
        
        # 圆角边框字符
        TL, TR = '╭', '╮'
        BL, BR = '╰', '╯'
        H, V = '─', '│'
        
        # 顶部边框
        lines.append(f"{color}{TL}" + H * (box_width - 2) + f"{TR}{Colors.RESET}")
        
        for line in content_lines:
            # 计算纯文本的显示宽度
            clean_line = strip_ansi(line)
            visible_len = get_display_width(clean_line)
            
            # 计算右侧填充空格
            padding = box_width - visible_len - 2
            if padding < 0: padding = 0
            
            lines.append(f"{color}{V}{Colors.RESET} {line}" + " " * (padding - 1) + f"{color}{V}{Colors.RESET}")
            
        lines.append(f"{color}{BL}" + H * (box_width - 2) + f"{BR}{Colors.RESET}")
        return lines

    def get_render_lines(self):
        # 获取当前终端高度，用于动态分配显示区域
        try:
            term_height = shutil.get_terminal_size().lines
        except:
            term_height = 24

        lines = []
        status = self.git.get_status()
        lines.append("") # 顶部留白

        # 状态面板 (圆角，无标题) - 约 5 行
        if status["initialized"]:
            remote_raw = status['remote']
            # 按协议类型分别处理，避免全局 replace 误伤
            if remote_raw.startswith("git@"):
                remote_display = remote_raw[len("git@"):].replace(":", "/", 1)
            elif remote_raw.startswith("https://"):
                remote_display = remote_raw[len("https://"):]
            elif remote_raw.startswith("http://"):
                remote_display = remote_raw[len("http://"):]
            else:
                remote_display = remote_raw
            if len(remote_display) > 40:
                remote_display = remote_display[-40:]
            # 确保 OSC 8 链接使用完整的 https URL
            if remote_raw.startswith("git@"):
                osc_url = f"https://{remote_raw[len('git@'):].replace(':', '/', 1)}"
            elif remote_raw.startswith("http"):
                osc_url = remote_raw
            else:
                osc_url = f"https://{remote_display}"
            # 远程地址可点击（OSC 8 超链接格式）
            remote_clickable = f"\033]8;;{osc_url}\033\\{Colors.YELLOW}{remote_display}{Colors.RESET}\033]8;;\033\\"
            status_lines = [
                f"项目: {Colors.WHITE}{os.path.basename(self.git.cwd)}{Colors.RESET}",
                f"分支: {Colors.GREEN}{status['branch']}{Colors.RESET}",
                f"远程: {remote_clickable}"
            ]
        else:
            status_lines = [
                f"{Colors.RED}未初始化 Git 仓库{Colors.RESET}",
                "请使用 '同步' 进行初始化"
            ]
        
        # 手动构建框：顶边 + 状态行 + 分隔线 + 文件列表 + 底边
        box_width = 60
        TL, TR = '╭', '╮'
        BL, BR = '╰', '╯'
        H, V = '─', '│'

        # 顶边
        lines.append(f"{Colors.CYAN}{TL}" + H * (box_width - 2) + f"{TR}{Colors.RESET}")

        # 状态行: │ + space + content + padding + │
        for line in status_lines:
            clean_line = strip_ansi(line)
            visible_len = get_display_width(clean_line)
            padding = box_width - visible_len - 3
            lines.append(f"{Colors.CYAN}{V}{Colors.RESET} {line}" + " " * padding + f"{Colors.CYAN}{V}{Colors.RESET}")

        # 文件列表 (在框内部)
        if self.first_sync_done and self.options:
            # 动态计算分配给文件列表的高度
            reserved_for_logs = 8
            reserved_for_header = 10
            max_file_height = max(3, term_height - reserved_for_header - reserved_for_logs)

            # 分隔线 + 倒计时 (在同一行，有边框，淡灰实体线)
            rem = max(0, min(box_width - 4, self.timeout_seconds))
            elap = (box_width - 4) - rem
            timer_bar = f"{Colors.DIM}{'─' * rem}{Colors.DIM}{'┄' * elap}{Colors.RESET}"
            sep_line = f"{Colors.CYAN}│{Colors.RESET} " + timer_bar + f" {Colors.CYAN}│{Colors.RESET}"
            lines.append(sep_line)

            # 如果文件较多，实现简单的滚动窗口
            display_start = 0
            display_options = self.options
            if len(self.options) > max_file_height:
                display_start = max(0, self.selected_index - max_file_height // 2)
                end = min(len(self.options), display_start + max_file_height)
                if end == len(self.options):
                    display_start = max(0, end - max_file_height)
                display_options = self.options[display_start:end]

                # 添加更多指示器
                if display_start > 0:
                    indicator = f"{Colors.CYAN}│{Colors.RESET}  {Colors.DIM}↑ 更多...{Colors.RESET}"
                    lines.append(indicator + " " * (box_width - 18) + f"{Colors.CYAN}│{Colors.RESET}")

            max_cn_width = 0
            for opt in display_options:
                max_cn_width = max(max_cn_width, get_display_width(opt['name']))

            for i, option in enumerate(display_options):
                actual_index = display_start + i
                is_selected = (actual_index == self.selected_index)

                cn_text = option['name']
                ignored = option.get('ignored', False)
                action_text = "推送" if ignored else "删除"

                status_char = self.git.updated_items.get(cn_text)
                if status_char == 'A': status_indicator = f"[{Colors.GREEN}+{Colors.RESET}]"
                elif status_char == 'D': status_indicator = f"[{Colors.RED}-{Colors.RESET}]"
                else: status_indicator = "   "

                padding = " " * (max_cn_width - get_display_width(cn_text))
                tag_text = f"{Colors.DIM}(已忽略){Colors.RESET}" if ignored else ""

                # 被忽略时同时应用淡色 (DIM) 和删除线 (STRIKETHROUGH)
                ignored_style = f"{Colors.DIM}{Colors.STRIKETHROUGH}" if ignored else ""

                # 保持与原始代码相同的格式
                if is_selected:
                    if self.action_index == 0:
                        line = f"{Colors.CYAN}│{Colors.RESET} {status_indicator} {Colors.BG_BLUE}{Colors.BOLD}{ignored_style}{cn_text} {Colors.RESET}{padding}  {action_text} {tag_text}"
                    else:
                        action_color = Colors.GREEN if ignored else Colors.RED
                        line = f"{Colors.CYAN}│{Colors.RESET} {status_indicator} {ignored_style}{cn_text}{Colors.RESET if ignored else ''}{padding}  {Colors.BG_BLUE}{Colors.BOLD}{action_color} {action_text} {Colors.RESET}{tag_text}"
                else:
                    line = f"{Colors.CYAN}│{Colors.RESET} {status_indicator} {ignored_style}{cn_text}{Colors.RESET if ignored else ''}{padding}   {action_text} {tag_text}"

                # 计算右边距使行宽等于box_width
                visible_len = get_display_width(strip_ansi(line))
                right_padding = max(0, box_width - visible_len - 1)
                lines.append(line + " " * right_padding + f"{Colors.CYAN}│{Colors.RESET}")

            if len(self.options) > max_file_height and display_start + len(display_options) < len(self.options):
                indicator = f"{Colors.CYAN}│{Colors.RESET}  {Colors.DIM}↓ 更多...{Colors.RESET}"
                lines.append(indicator + " " * (box_width - 18) + f"{Colors.CYAN}│{Colors.RESET}")

        # 底边
        lines.append(f"{Colors.CYAN}╰" + "─" * (box_width - 2) + f"╯{Colors.RESET}")

        if self.git.logs:
            lines.append("")
            # 动态计算剩余行数用于显示日志
            occupied = len(lines)
            available_log_rows = term_height - occupied - 1 # 留 1 行底边
            
            if available_log_rows > 0:
                # 仅显示最新的日志，模拟“继续往下显示”的效果
                display_logs = self.git.logs[-available_log_rows:] if len(self.git.logs) > available_log_rows else self.git.logs
                for log in display_logs:
                    lines.append(f" {log}")
            else:
                # 空间极度受限时至少显示最后一条
                lines.append(f" {self.git.logs[-1]}")
        
        return lines

    def render(self):
        new_lines = self.get_render_lines()
        
        # 首次渲染清屏
        if not self.last_lines:
            clear_screen()
        
        # 对比更新
        for i, line in enumerate(new_lines):
            if i >= len(self.last_lines) or line != self.last_lines[i]:
                sys.stdout.write(f"\033[{i+1};1H{line}\033[K")
        
        # 清除多余行
        if len(new_lines) < len(self.last_lines):
            sys.stdout.write(f"\033[{len(new_lines)+1};1H\033[J")
        elif len(new_lines) == len(self.last_lines):
             # 确保最后一行的下方也被清理（应对弹出的 Prompt 残留）
             sys.stdout.write(f"\033[{len(new_lines)+1};1H\033[J")
        
        # 如果新行比旧行多，也要清理下方（其实 \033[K 只清行内，需要确保下方干净）
        # 这里统一在最后做一次 \033[J 清理光标位置之后的内容
        sys.stdout.write(f"\033[{len(new_lines)+1};1H\033[J")

        self.last_lines = new_lines
        sys.stdout.flush()

    def run(self):
        init_console()
        
        # 启动时自动同步
        if not self.first_sync_done:
            self.operation_in_progress = True
            self.render()
            self.git.sync()
            self.first_sync_done = True
            self.operation_in_progress = False
            self.cooldown_until = time.time() + 1.0  # 同步后冷却
            self.refresh_file_list() # 同步后刷新文件列表
            self.deadline = time.time() + 60
            
        while self.running:
            self.render()

            # 非阻塞检测按键
            if msvcrt.kbhit():
                # 操作进行中或冷却期间时，清空键盘缓冲区并忽略按键
                if self.operation_in_progress or time.time() < self.cooldown_until:
                    while msvcrt.kbhit():
                        msvcrt.getch()
                    time.sleep(0.05)
                    continue

                key = get_key()
                self.deadline = time.time() + 60

                if key == Keys.UP:
                    if self.options:
                        self.selected_index = (self.selected_index - 1) % len(self.options)
                        self.action_index = 0 # 切换行时重置到文件名焦点
                elif key == Keys.DOWN:
                    if self.options:
                        self.selected_index = (self.selected_index + 1) % len(self.options)
                        self.action_index = 0 # 切换行时重置到文件名焦点
                elif key == Keys.LEFT:
                    self.action_index = 0
                elif key == Keys.RIGHT:
                    self.action_index = 1
                elif key == Keys.ENTER:
                    if self.options and self.options[self.selected_index]['name'] != "(空目录)":
                        if self.action_index == 1:
                            # 焦点在操作时按回车执行操作 (删除或推送)
                            self.delete_selected()
                        else:
                            # 焦点在文件名时按回车，自动切换到操作焦点，并提示再次按键确认
                            self.action_index = 1
                        self.deadline = time.time() + 60
            else:
                # 基于 deadline 计算剩余秒数，避免计时器丢帧
                remaining = self.deadline - time.time()
                self.timeout_seconds = max(0, round(remaining))
                if remaining < 0:
                    self.running = False
                time.sleep(0.05)

        print("\n已退出。")

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
