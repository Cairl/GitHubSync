## 优化

- **架构重构**: 从单文件 ~1150 行重构为 src/ 模块化架构（config、utils、git_manager、app 四个模块）
- **TUI 引擎**: 从手写 ANSI 转义序列迁移到 Rich 库（Live 全屏渲染 + Text 样式 + OSC 8 超链接）
- **日志系统**: 从 ANSI 字符串改为结构化元组 (timestamp, level, message)，渲染与数据分离
- **启动体验**: 启动后立即显示菜单界面，同步过程日志实时可见
- **目录结构**: github_sync/ 包重命名为 src/，run_sync.bat 固定指向项目路径
