"""领域层：纯业务逻辑，零 I/O，定义接口与事件。

依赖规则：
- 本层不依赖 infrastructure / presentation / application；
- 本层定义 GitProvider / GitHubProvider 协议（接口），由基础设施层实现。
"""
