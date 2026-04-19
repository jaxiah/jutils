#!/usr/bin/env python3
"""
pomo_debrief.py -- Obsidian TaskNotes 番茄钟复盘提示器

每当 TaskNotes 完成一个 work 番茄钟，弹出提示窗口，引导用户记录本次进展
(save state)，并将内容追加到对应 TaskNote 文件的当日日期分组下。

Config
------
首次运行时自动生成 pomo_debrief.config.json，填入路径后重新运行。

Changelog
---------
2026-04-19  rename to pomo_debrief; derive vault_path from data_json_path
2026-04-18  initial implementation
"""

import json
import sys
import time
import tkinter as tk
from datetime import date, datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "data_json_path": "填入 TaskNotes data.json 的完整路径，例如 D:/JNote/.obsidian/plugins/tasknotes/data.json",
    "poll_interval": 3,
}


def vault_path_from_config(cfg: dict) -> Path:
    """从 data_json_path 推导 vault 根目录 (<vault>/.obsidian/plugins/tasknotes/data.json)."""
    return Path(cfg["data_json_path"]).parents[3]


def load_config() -> dict:
    path = Path(__file__).with_suffix(".config.json")
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.exit(f"已生成配置文件 {path.name}，请填入路径后重新运行。")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 数据解析
# ---------------------------------------------------------------------------


def load_pomo_history(cfg: dict) -> list:
    try:
        data = json.loads(Path(cfg["data_json_path"]).read_text(encoding="utf-8"))
        return data.get("pomodoroHistory", [])
    except Exception:
        return []


def is_completed_work(entry: dict) -> bool:
    return entry.get("type") == "work" and entry.get("completed") is True



def count_today_pomos_for_task(history: list, task_path: str) -> int:
    today = date.today().strftime("%Y-%m-%d")
    return sum(1 for e in history if is_completed_work(e) and e.get("taskPath") == task_path and e.get("startTime", "").startswith(today))


def task_display_name(task_path: str) -> str:
    return Path(task_path).stem


# ---------------------------------------------------------------------------
# 写入 TaskNote
# ---------------------------------------------------------------------------


_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def fmt_time(iso: str) -> str:
    """从 ISO 时间字符串生成 org-mode 风格时间戳 [YYYY-MM-DD Dow HH:MM]，容错返回原串。"""
    try:
        dt = datetime.fromisoformat(iso)
        dow = _WEEKDAYS[dt.weekday()]
        return dt.strftime(f"[%Y-%m-%d {dow} %H:%M]")
    except Exception:
        return iso


def append_save_state(cfg: dict, task_path: str, text: str, start_time: str, end_time: str) -> None:
    full_path = vault_path_from_config(cfg) / task_path
    if not full_path.exists():
        print(f"[SaveState] 文件不存在: {full_path}")
        return
    if start_time:
        time_range = f"{fmt_time(start_time)} -- {fmt_time(end_time)}"
    else:
        now = datetime.now()
        dow = _WEEKDAYS[now.weekday()]
        time_range = now.strftime(f"[%Y-%m-%d {dow} %H:%M]")
    stripped = text.strip()
    lines = stripped.splitlines()
    if len(lines) <= 1:
        bullet = f"- {time_range} {stripped}"
    else:
        indented = "\n".join(f"  {l}" for l in lines)
        bullet = f"- {time_range}\n{indented}"
    today_heading = f"### {date.today().strftime('%Y-%m-%d')}"
    existing = full_path.read_text(encoding="utf-8")
    if today_heading in existing:
        entry = f"\n{bullet}\n"
    else:
        entry = f"\n{today_heading}\n\n{bullet}\n"
    with open(full_path, "a", encoding="utf-8") as f:
        f.write(entry)
    print(f"[SaveState] 已写入: {full_path.name}")


# ---------------------------------------------------------------------------
# 弹窗
# ---------------------------------------------------------------------------

PLACEHOLDER = "[做了什么] -> [排除了什么] -> [卡点在哪] -> [下一步]"


def show_prompt(cfg: dict, task_path: str, pomo_count: int, start_time: str = "", end_time: str = "") -> None:
    task_name = task_display_name(task_path)

    root = tk.Tk()
    root.withdraw()

    win = tk.Toplevel(root)
    win.title("番茄钟结束 -- 记录进展")
    win.attributes("-topmost", True)
    win.resizable(False, False)
    win.configure(bg="#1a1a1a")

    # 任务名
    tk.Label(
        win,
        text=task_name,
        fg="#ffffff",
        bg="#1a1a1a",
        font=("Microsoft YaHei", 13, "bold"),
        wraplength=560,
        justify="center",
    ).pack(padx=28, pady=(18, 2))

    # pomo 计数 + 时间段
    time_range_str = f"{fmt_time(start_time)} - {fmt_time(end_time)}" if start_time and end_time else ""
    subtitle = f"今日第 {pomo_count} 个番茄钟完成"
    if time_range_str:
        subtitle += f"  |  {time_range_str}"
    tk.Label(
        win,
        text=subtitle,
        fg="#888888",
        bg="#1a1a1a",
        font=("Microsoft YaHei", 10),
    ).pack(pady=(0, 10))

    tk.Frame(win, height=1, bg="#444444").pack(fill="x", padx=28, pady=(0, 10))

    # 文本输入框
    text_widget = tk.Text(
        win,
        width=60,
        height=4,
        bg="#2a2a2a",
        fg="#555555",
        insertbackground="#ffffff",
        font=("Microsoft YaHei", 11),
        relief="flat",
        padx=8,
        pady=8,
        wrap="word",
    )
    text_widget.pack(padx=28, pady=(0, 4))
    text_widget.insert("1.0", PLACEHOLDER)

    def on_focus_in(event):
        if text_widget.get("1.0", "end-1c") == PLACEHOLDER:
            text_widget.delete("1.0", "end")
            text_widget.config(fg="#cccccc")

    def on_focus_out(event):
        if not text_widget.get("1.0", "end-1c").strip():
            text_widget.insert("1.0", PLACEHOLDER)
            text_widget.config(fg="#555555")

    text_widget.bind("<FocusIn>", on_focus_in)
    text_widget.bind("<FocusOut>", on_focus_out)

    # 提示文字
    tk.Label(
        win,
        text="Ctrl+Enter 记录  |  Esc 跳过",
        fg="#555555",
        bg="#1a1a1a",
        font=("Microsoft YaHei", 9),
    ).pack(pady=(0, 8))

    # 按钮
    def on_submit():
        content = text_widget.get("1.0", "end-1c").strip()
        if content and content != PLACEHOLDER:
            append_save_state(cfg, task_path, content, start_time, end_time)
        root.destroy()

    def on_skip():
        root.destroy()

    btn_frame = tk.Frame(win, bg="#1a1a1a")
    btn_frame.pack(pady=(0, 20))

    btn_style = dict(
        bg="#333333",
        fg="#ffffff",
        activebackground="#555555",
        activeforeground="#ffffff",
        font=("Microsoft YaHei", 11),
        relief="flat",
        padx=20,
        pady=8,
        cursor="hand2",
    )

    tk.Button(btn_frame, text="记录", command=on_submit, **btn_style).pack(side="left", padx=8)
    tk.Button(btn_frame, text="跳过", command=on_skip, **btn_style).pack(side="left", padx=8)

    win.bind("<Control-Return>", lambda e: on_submit())
    win.bind("<Escape>", lambda e: on_skip())
    win.protocol("WM_DELETE_WINDOW", on_skip)

    # 屏幕居中
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    text_widget.focus_set()
    root.mainloop()


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------


def run() -> None:
    cfg = load_config()
    interval = cfg.get("poll_interval", 3)

    last_count = -1  # -1 表示尚未初始化
    mtime_json = None

    print(f"[SaveState] 启动  |  轮询间隔 {interval}s")
    print(f"[SaveState] data.json: {cfg['data_json_path']}")

    while True:
        try:
            try:
                new_mtime = Path(cfg["data_json_path"]).stat().st_mtime
            except FileNotFoundError:
                time.sleep(interval)
                continue

            if new_mtime != mtime_json:
                mtime_json = new_mtime
                history = load_pomo_history(cfg)

                if last_count == -1:
                    # 第一次扫描只建立基线，不触发弹窗
                    last_count = len(history)
                    print(f"[SaveState] 基线建立，已知记录 {last_count} 条")
                else:
                    new_entries = history[last_count:]
                    last_count = len(history)
                    for e in new_entries:
                        if not is_completed_work(e):
                            continue
                        task_path = e.get("taskPath", "")
                        if not task_path:
                            continue
                        pomo_count = count_today_pomos_for_task(history, task_path)
                        print(f"[SaveState] 新番茄钟: {task_display_name(task_path)} (今日第 {pomo_count} 个)")
                        show_prompt(cfg, task_path, pomo_count, e.get("startTime", ""), e.get("endTime", ""))

        except Exception as ex:
            print(f"[SaveState] 异常 (已忽略): {ex}")

        time.sleep(interval)


if __name__ == "__main__":
    run()
