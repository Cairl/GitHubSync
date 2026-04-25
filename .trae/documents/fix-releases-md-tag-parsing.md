# 修复：releases.md 版本号解析包含 markdown 标题符号

## 问题

`releases.md` 第一行是 markdown 标题格式 `# 26w17a`，当前代码直接取整行作为 tag，导致：
- tag 变为 `# 26w17a`
- `gh release create # 26w17a ...` 中，`#` 被当作 tag，`26w17a` 被当作文件附件参数
- 报错 "no matches found for 26w17a"

## 修复步骤

### 1. 修改 `github_sync.py` 中 `publish_release()` 的 tag 提取逻辑

将：
```python
tag = lines[0].strip()
```

改为：
```python
tag = lines[0].strip().lstrip('#').strip()
```

先 `strip()` 去首尾空白，再 `lstrip('#')` 去掉开头的 `#`，再 `strip()` 去掉 `#` 后可能跟的空格。

### 2. 更新测试

在 `tests/test_publish_release.py` 中添加一个测试用例，验证 markdown 标题格式的版本号能正确提取。
