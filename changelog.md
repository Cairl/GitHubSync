## 变更

- **添加**: 项目结构恢复为支持上传 + 远端删除 + Release 发布
- **修复**: 恢复 `remove_from_github()` 删除远程文件功能（之前的纯上传模式误删了该功能）
- **恢复**: `publish_release()` 流程，包含 changelog.md 自动发布为 Release 并删除本地文件
- **移除**: 自动合并/rebase 冲突处理（保留强制推送作为最后手段）
