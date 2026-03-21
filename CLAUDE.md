# Jianxia's Utils

一系列独立功能脚本的集合. 每个脚本完成一件事, 单独分发也是完整功能.

## 脚本列表

| 脚本                         | 类型     | 说明                                            |
| ---------------------------- | -------- | ----------------------------------------------- |
| `tasknotes_quota_monitor.py` | 守护进程 | Obsidian TaskNotes 番茄钟配额监控, 超额强制弹窗 |
| `md_punct_cn2en.py`          | CLI 工具 | Markdown 中文标点转英文标点                     |
| `clang_format_dir.py`        | CLI 工具 | 批量 clang-format 格式化 C/C++/CUDA/GLSL 源码树 |

## 代码规范

- Formatter: `black -l 160` (见 `pyproject.toml`)
- 每个脚本文件头部包含: 功能描述, 设计要点, 用法说明, Changelog (时间逆序)

## Config 规范

脚本按需决定是否使用 config 文件:

- **一次性 CLI 工具** (如 `md_punct_cn2en.py`): 参数直接通过命令行传入, 无需 config.
- **长期运行的守护进程** (如 `tasknotes_quota_monitor.py`): 使用 per-script config 文件,
  命名为 `{脚本名}.config.json`, 由脚本首次运行时自动生成模板, 用户填入后重新运行.

`*.config.json` 已加入 `.gitignore`, 不提交个人路径配置. Config 模板内嵌于脚本中,
无需维护额外的 `.example` 文件.
