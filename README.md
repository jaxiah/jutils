# Jaxiah's Utils

存放一些功能实用且一个文件就能讲清楚的脚本.

- [pomo_debrief.py](#pomo_debriefpy)
- [md_punct_cn2en.py](#md_punct_cn2enpy)
- [clang_format_dir.py](#clang_format_dirpy)

## pomo_debrief.py

Obsidian TaskNotes 番茄钟复盘提示器. 每当 TaskNotes 完成一个 work 番茄钟, 自动弹出置顶窗口, 引导记录本次进展 (save state), 并将内容追加到对应 TaskNote 文件的当日日期分组下.

弹窗显示任务名、今日第几个番茄钟、开始/结束时间, 输入框支持单行和多行记录. 单行直接跟在时间戳后, 多行自动缩进为合法的 Markdown bullet 续行. 跳过时静默关闭, 不写入任何内容.

写入格式示例:

```markdown
### 2026-04-19

- [2026-04-19 Sat 10:25] -- [2026-04-19 Sat 10:50] 确认 wmma tiling 逻辑正确, bank conflict 问题已排除
- [2026-04-19 Sat 11:00] -- [2026-04-19 Sat 11:25]
  尝试 double buffering 方案
  卡在 async memcpy 的 barrier 位置, 下一步查文档
```

**运行**: 首次运行自动生成 `pomo_debrief.config.json`, 填入路径后重新运行.

```bash
pythonw pomo_debrief.py   # 后台运行（无命令行窗口）
```

**Config 字段**:

| 字段 | 说明 |
| --- | --- |
| `data_json_path` | TaskNotes 插件的 data.json 完整路径 |
| `poll_interval` | 轮询间隔秒数 (默认 3) |

依赖: Python 3.8+, 标准库 (`tkinter`, `json`), 无需额外安装.

## md_punct_cn2en.py

将 Markdown 文件中的中文 (全角) 标点替换为英文 (半角) 标点, 并修正 CJK 与 Latin/数字之间的空格. 代码块, 行内代码, URL 保持原样不动.

```bash
python md_punct_cn2en.py file.md          # 输出到 stdout
python md_punct_cn2en.py -o out.md file.md  # 输出到指定文件
python md_punct_cn2en.py -i file.md       # 原地修改
python md_punct_cn2en.py -i docs/         # 递归处理目录
python md_punct_cn2en.py -i "**/*.md"     # glob 模式
```

## clang_format_dir.py

递归扫描目录下所有 C/C++/CUDA/GLSL/HLSL 源文件并用 `clang-format` 原地格式化. 要求目录内存在 `.clang-format`, 否则跳过. 多线程并行, 大型代码库也快.

```bash
python clang_format_dir.py src/                  # 格式化 src/ 下所有文件
python clang_format_dir.py src/ include/ -j 16   # 多目录, 16 线程
```

依赖: `clang-format` (需在 PATH 中), `tqdm` (`pip install tqdm`).
