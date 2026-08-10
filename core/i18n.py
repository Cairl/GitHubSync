"""中英双语 i18n：按系统语言自动检测，测试中可 monkeypatch i18n.LANG 覆盖。"""
from __future__ import annotations

import locale
import os


def _detect_lang() -> str:
    """检测界面语言：GITHUBSYNC_LANG 环境变量 > 系统语言；中文环境返回 "zh"。

    Windows 下 locale.getlocale() 返回 'Chinese (Simplified)_China' 等非标准
    语言名（不以 "zh" 开头），需额外匹配 "chinese"。
    """
    override = os.environ.get("GITHUBSYNC_LANG", "").lower()
    if override in ("zh", "en"):
        return override
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "").lower()
        if val.startswith("zh"):
            return "zh"
        if val.startswith("en"):
            return "en"
    try:
        lang = (locale.getlocale()[0] or "").lower()
    except ValueError:
        lang = ""
    if lang.startswith("zh") or "chinese" in lang:
        return "zh"
    return "en"


LANG = _detect_lang()


def tr(zh: str, en: str) -> str:
    """按当前 LANG 返回中文或英文文案（调用时动态读取，支持测试覆盖）。"""
    return zh if LANG == "zh" else en
