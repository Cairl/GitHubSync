"""基础设施层：适配器与外部资源访问。

依赖规则：本层实现领域层定义的接口（GitProvider / GitHubProvider），
依赖方向为 domain ← infrastructure，绝不反向。
"""
