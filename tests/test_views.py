"""标签页视图协议级测试：懒加载、失效重扫、键处理、渲染。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import i18n
i18n.LANG = "en"  # 测试固定英文输出，必须先于 import tui 模块

from tests.fakes import make_services


def test_activate_loads_once_then_cache_hits():
    from tui.view_base import ViewBase

    class Probe(ViewBase):
        id = "probe"

        def __init__(self):
            super().__init__()
            self.loads = 0

        def _load(self):
            self.loads += 1

        def render(self):
            return "x"

        def handle_key(self, key):
            return []

    v = Probe()
    v.activate()
    v.activate()
    assert v.loads == 1          # 二次切入零扫描（缓存命中）
    v.invalidate()
    v.activate()
    assert v.loads == 2          # 失效后重扫
