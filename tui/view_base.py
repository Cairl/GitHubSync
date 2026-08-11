"""标签页视图基类：懒加载缓存 + 统一键处理契约。

主循环（InteractiveApp）持有视图注册表，←/→ 切换标签时：
- 切出：old.deactivate()（默认无操作；PushView 借此清除推送结果锁定）；
- 切入：new.activate() → 首次或失效后才 _load()（懒加载），缓存命中零扫描。

handle_key 返回需失效的视图 id 列表（可空），由主循环统一 invalidate
并对当前视图 reactivate（数据过期立即重扫）。视图之间不直接引用。
渲染契约：render() 纯函数零 I/O，只读 activate 时缓存的数据。
"""
from __future__ import annotations


class ViewBase:
    """标签页视图公共基类：_loaded 缓存标记 + activate/invalidate 骨架。"""

    id: str = ""

    def __init__(self) -> None:
        self._loaded = False

    # ── 生命周期 ──
    def activate(self) -> None:
        """切入时调用；首次或失效后才 _load()（懒加载），缓存命中零扫描。"""
        if not self._loaded:
            self._load()
            self._loaded = True

    def deactivate(self) -> None:
        """切出时调用；默认无操作（缓存与光标保留，切回原样恢复）。"""

    def invalidate(self) -> None:
        """缓存失效：下次 activate 重扫；光标在 _load 时按列表长度钳位保留。"""
        self._loaded = False

    def _load(self) -> None:
        """扫描数据写入实例缓存；子类实现。I/O 只允许出现在此与 handle_key。"""
        raise NotImplementedError

    # ── 渲染与键处理 ──
    def render(self) -> str:
        """缓存数据 → 内容区文本（纯函数，零 I/O）；子类实现。"""
        raise NotImplementedError

    def handle_key(self, key: bytes) -> list[str]:
        """处理 ↑/↓/Enter，返回需失效的视图 id 列表（可空）；子类实现。"""
        raise NotImplementedError
