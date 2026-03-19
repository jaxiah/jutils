# Obsidian Task Monitor

一个轻量级 Python 守护进程，通过桥接 Obsidian 每日计划与 [TaskNotes](https://github.com/calber-m/obsidian-tasknotes) 插件的番茄钟数据，实现自动化的任务防沉迷与动态分流指引。

当你在某个任务上花费的番茄钟达到或超出当日配额时，程序会强制弹出置顶窗口打断你，并同时展示当日尚有盈余的任务供你切换。

## 设计思想

多任务并行推进时，人很容易陷入"单一项目陷阱"——只盯着一件事做，表面上进度不错，但其他事情毫无进展。这个工具的核心逻辑是：

- **你在日记里做配额规划**，声明今天每个任务最多投入几个番茄钟
- **工具帮你守住这条线**，一旦某个任务用满配额，立刻打断，并告诉你下一步该做什么

弹窗分两个区域，对应"推拉"双向反馈：

- **红色 Stop 区**：显示超额任务，打断当前行为
- **绿色 Go 区**：列出待办任务及剩余配额，引导下一步行动

## 依赖

- Python 3.8+
- 标准库（`tkinter`、`json`、`re`），无需额外安装

## 配置

编辑 `config.json`：

```json
{
  "daily_notes_path": "D:/JNote/daily",
  "data_json_path":   "D:/JNote/.obsidian/plugins/tasknotes/data.json",
  "poll_interval":    3
}
```

| 字段 | 说明 |
|------|------|
| `daily_notes_path` | Obsidian 日记所在目录，文件名须为 `YYYY-MM-DD.md` |
| `data_json_path` | TaskNotes 插件的 `data.json` 完整路径 |
| `poll_interval` | 轮询间隔（秒），默认 3 |

## 日记格式

在当日笔记的任意位置，按如下格式声明任务配额：

```markdown
- [[任务文件名]] : 数字
```

示例：

```markdown
- [[new ankify pass - ddca.solid]] : 5
- [[CS149 Kayvon part - 剩下的课程以及之前的 ankify]] : 4
```

双链中的文件名须与 TaskNotes 中的任务文件名一致（不含路径和 `.md` 后缀）。匹配采用路径后缀匹配，因此任务可以放在 vault 的任意子目录下。

## 运行

```bash
python monitor.py
```

后台运行（不显示命令行窗口）：

```bash
pythonw monitor.py
```

启动后终端会实时打印当前状态，每当日记或番茄钟数据发生变化时刷新一次：

```
[TaskMonitor] 2026-03-19  ─────────────────────────────
  [OK   ]  2/5  ██░░░  new ankify pass - ddca.solid
  [OK   ]  1/4  █░░░   CS149 Kayvon part - 剩下的课程以及之前的 ankify
```

## 弹窗行为

| 状态 | 触发条件 | 弹窗文字 |
|------|----------|----------|
| 额度已用完 | `done == quota` | 🛑 额度已用完 |
| 严重超时 | `done > quota` | 🛑 已花费 N/M 个番茄钟，严重超时！ |

**阶梯式打断**：若无视警告继续做同一任务，每多完成一个番茄钟触发一次新弹窗。

**跨夜重置**：零点后自动切换到次日笔记，历史警告记录清空。

**静默容错**：文件不存在或 JSON 读写冲突时静默跳过，等待下一个周期重试。
