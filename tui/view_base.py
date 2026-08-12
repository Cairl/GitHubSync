"""标签页视图基类：懒加载缓存 + loading 态 + 统一键处理契约。

主循环（InteractiveApp）持有视图注册表，←/→ 切换标签时：
- 切出：old.deactivate()（默认无操作；PushView 借此清除推送结果锁定）；
- 切入：new.activate() → 首次或失效后踢后台加载（loading 态），缓存命中零扫描。

handle_key 返回需失效的视图 id 列表（可空），由主循环统一 invalidate
并对当前视图 reactivate（数据过期立即重扫）。视图之间不直接引用。
渲染契约：render() 纯函数零 I/O，只读 activate 时缓存的数据；
loading 期间返回空串（留白不显示），handle_key 全部无效（含 Enter）。

异步加载：activate 经注入的 executor 提交 _load（生产 ThreadExecutor 后台
线程，测试默认 InlineExecutor 同步），完成后 _load_done 置标记并触发
on_loaded（回调在 worker 线程触发，只允许线程安全操作如 queue.put）。
"""
from __future__ import annotations

from core.executor import InlineExecutor


class ViewBase:
    """标签页视图公共基类：_loaded/_loading 状态机 + activate/invalidate 骨架。"""

    id: str = ""

    def __init__(self, executor=None, on_loaded=None) -> None:
        self._executor = executor or InlineExecutor()
        self._on_loaded = on_loaded  # 后台加载完成回调（如主循环事件入队）
        self._loaded = False
        self._loading = False

    # ── 生命周期 ──
    def activate(self) -> None:
        """切入时调用；首次或失效后才踢后台加载（懒加载），缓存命中零扫描。"""
        if self._loaded or self._loading:
            return
        self._loading = True
        self._executor.submit(self._load_guard, self._load_done)

    def _load_guard(self) -> bool:
        """加载探针：_load 正常完成返回 True；异常经 executor 契约降级为 None
        （callback(None)），_load_done 据此区分成败——_load 本身恒返回 None。"""
        self._load()
        return True

    def _load_done(self, result) -> None:
        """后台加载完成：置缓存标记并通知主循环（回调须线程安全）。

        result 为 None（_load 异常）时不置 _loaded：视图不缓存空数据，
        下次 activate 自动重试；_loading 仍复位、on_loaded 仍触发。
        """
        self._loading = False
        if result is not None:
            self._loaded = True
        if self._on_loaded:
            self._on_loaded()

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
        """loading 期间留白（空串）；否则返回子类 _render 的缓存渲染。"""
        if self._loading:
            return ""
        return self._render()

    def _render(self) -> str:
        """缓存数据 → 内容区文本（纯函数，零 I/O）；子类实现。"""
        raise NotImplementedError

    def handle_key(self, key: bytes) -> list[str]:
        """处理 ↑/↓/Enter，返回需失效的视图 id 列表（可空）；子类实现。

        子类实现首行必须 `if self._loading: return []`（loading 期间无数据，
        一律无效键；PushView 的 Enter 尤其需要——空数据不得触发推送流程）。
        """
        raise NotImplementedError
