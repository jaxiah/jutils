# TaskMonitor

轻量级 Python 守护进程，桥接 Obsidian 日记配额与 TaskNotes 番茄钟历史，超额时强制弹窗打断。

## 运行

```bash
python monitor.py
```

## 配置

编辑 `config.json`：

| 字段 | 说明 |
|------|------|
| `daily_notes_path` | Obsidian 日记目录（到文件夹一级，文件名按 `YYYY-MM-DD.md` 自动构建） |
| `data_json_path` | TaskNotes 插件的 `data.json` 完整路径 |
| `poll_interval` | 轮询间隔（秒），默认 3 |

## 代码规范

- Formatter: `black -l 160`（见 `pyproject.toml`）
