"""Tests for md_punct_cn2en.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from md_punct_cn2en import convert_markdown, _convert_text

PASS = FAIL = 0


def check(desc, got, expected):
    global PASS, FAIL
    if got == expected:
        print(f"  PASS  {desc}")
        PASS += 1
    else:
        print(f"  FAIL  {desc}")
        print(f"        got:      {repr(got)}")
        print(f"        expected: {repr(expected)}")
        FAIL += 1


# ---------------------------------------------------------------------------
print("=== Punctuation mapping ===")
# ---------------------------------------------------------------------------

check("comma", _convert_text("你好，世界"), "你好, 世界")
check("enumeration comma", _convert_text("苹果、香蕉、橙子"), "苹果, 香蕉, 橙子")
check("period", _convert_text("结束了。新开始"), "结束了. 新开始")
check("colon", _convert_text("注意：以下内容"), "注意: 以下内容")
# trailing space after ? / ! gets stripped by the line-end cleanup — correct behaviour
check("question mark", _convert_text("你好吗？"), "你好吗?")
check("exclamation", _convert_text("太好了！"), "太好了!")
check("semicolon", _convert_text("第一点；第二点"), "第一点; 第二点")
check("parentheses", _convert_text("这（括号内）是测试"), "这 (括号内) 是测试")
# standalone book-title brackets: leading space is harmless; prettier trims it
check("book title brackets", _convert_text("《三体》"), ' "三体"')
check("book title in sentence", _convert_text("我喜欢《三体》这本书"), '我喜欢 "三体" 这本书')
check("ellipsis", _convert_text("等等…后来"), "等等... 后来")
check("em dash single", _convert_text("前言—后语"), "前言 — 后语")
check("em dash double (——)", _convert_text("前言——后语"), "前言 -- 后语")
check("em dash double standalone", _convert_text("前——后"), "前 -- 后")
check("curly double quotes", _convert_text("\u201c引用\u201d"), ' "引用"')

# ---------------------------------------------------------------------------
print("\n=== CJK <-> Latin spacing ===")
# ---------------------------------------------------------------------------

check("Chinese before English", _convert_text("使用Python编程"), "使用 Python 编程")
check("English before Chinese", _convert_text("用GPT生成"), "用 GPT 生成")
check("Chinese before number", _convert_text("第3章"), "第 3 章")
check("number before Chinese", _convert_text("3个苹果"), "3 个苹果")
check("mixed with comma", _convert_text("使用Python，效率很高"), "使用 Python, 效率很高")
check("no extra space between Latin chars", _convert_text("hello world"), "hello world")

# ---------------------------------------------------------------------------
print("\n=== Space cleanup ===")
# ---------------------------------------------------------------------------

check("no space before period", _convert_text("end ."), "end.")
check("no space before comma", _convert_text("hello ,world"), "hello,world")
check("no space inside parens", _convert_text("( content )"), "(content)")
check("trailing space stripped", _convert_text("行末，"), "行末,")
# multiple spaces from source are collapsed
check("collapse multiple spaces", _convert_text("你好，  世界"), "你好, 世界")

# ---------------------------------------------------------------------------
print("\n=== Bold/italic closing markers ===")
# ---------------------------------------------------------------------------

check("colon before closing **",   convert_markdown("**对 Device：** 说明"),     "**对 Device:** 说明")
check("comma before closing **",   convert_markdown("**加粗，** 更多"),           "**加粗,** 更多")
check("colon before closing *",    convert_markdown("*斜体：* 说明"),             "*斜体:* 说明")
check("opening ** unaffected",              convert_markdown("这是 **重要** 内容"),                "这是 **重要** 内容")
check("english ( after ** unaffected",      convert_markdown("这是 **(重要)** 内容"),               "这是 **(重要)** 内容")
check("fullwidth ( after ** fixed",          convert_markdown("这是 **（重要）** 内容"),              "这是 **(重要)** 内容")
check("bold not broken by colon",           convert_markdown("**对 Device (设备端)：** CPU 执行"),   "**对 Device (设备端):** CPU 执行")
check("bold not broken by closing bracket", convert_markdown("**对 Device (设备端)）** CPU 执行"),   "**对 Device (设备端))** CPU 执行")

# ---------------------------------------------------------------------------
print("\n=== Markdown task-list checkboxes preserved ===")
# ---------------------------------------------------------------------------

check("unchecked box untouched", convert_markdown("- [ ] buy milk"), "- [ ] buy milk")
check("checked box (x) untouched", convert_markdown("- [x] done"), "- [x] done")
check("checked box (X) untouched", convert_markdown("- [X] done"), "- [X] done")
check("checkbox with Chinese content", convert_markdown("- [ ] 完成任务，今天"), "- [ ] 完成任务, 今天")
check("checkbox with Chinese colon", convert_markdown("- [ ] 注意：截止今天"), "- [ ] 注意: 截止今天")
check("mixed checked and unchecked", convert_markdown("- [x] 已完成\n- [ ] 未完成，继续"), "- [x] 已完成\n- [ ] 未完成, 继续")

# ---------------------------------------------------------------------------
print("\n=== Code blocks & inline code preserved ===")
# ---------------------------------------------------------------------------

check(
    "fenced code block untouched",
    convert_markdown("```\n你好，世界\n```"),
    "```\n你好，世界\n```",
)
check(
    "inline code untouched",
    convert_markdown("使用`print(你好，世界)`函数"),
    "使用 `print(你好，世界)` 函数",
)
check(
    "inline code with Latin inside, CJK outside",
    convert_markdown("调用`foo()`方法"),
    "调用 `foo()` 方法",
)

# ---------------------------------------------------------------------------
print("\n=== URLs preserved ===")
# ---------------------------------------------------------------------------

check(
    "url with space already around it",
    convert_markdown("访问 https://example.com/path?a=1&b=2 获取"),
    "访问 https://example.com/path?a=1&b=2 获取",
)
check(
    "url directly after Chinese (no space)",
    convert_markdown("访问https://example.com 获取"),
    "访问 https://example.com 获取",
)

# ---------------------------------------------------------------------------
print("\n=== Full Markdown document ===")
# ---------------------------------------------------------------------------

sample = """\
# 标题

这是一段中文内容，包含了Python代码示例，以及一些数字3和标点：

1. 第一点；关于性能
2. 第二点（见附录）

```python
# 这里不动，保留中文标点，世界！
x = 1，
```

访问 https://docs.example.com/api?lang=zh 了解详情。
"""

expected = """\
# 标题

这是一段中文内容, 包含了 Python 代码示例, 以及一些数字 3 和标点:

1. 第一点; 关于性能
2. 第二点 (见附录)

```python
# 这里不动，保留中文标点，世界！
x = 1，
```

访问 https://docs.example.com/api?lang=zh 了解详情.
"""

check("full document", convert_markdown(sample), expected)

# ---------------------------------------------------------------------------
print(f"\n{'='*40}")
print(f"  {PASS} passed, {FAIL} failed")
