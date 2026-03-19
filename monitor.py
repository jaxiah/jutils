#!/usr/bin/env python3
"""
Obsidian Task Monitor
番茄钟配额守护进程 — 自动检测超额并强制弹窗打断
"""

import json
import re
import sys
import time
import tkinter as tk
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
def load_config() -> dict:
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 数据解析
# ---------------------------------------------------------------------------
QUOTA_RE = re.compile(r"^[-*]\s+\[\[(.*?)\]\]\s*:\s*(\d+)", re.MULTILINE)


def daily_note_path(cfg: dict, d: date) -> Path:
    return Path(cfg["daily_notes_path"]) / f"{d.strftime('%Y-%m-%d')}.md"


def parse_quotas(cfg: dict, d: date) -> dict:
    """返回 {task_name: quota}"""
    result = {}
    try:
        text = daily_note_path(cfg, d).read_text(encoding="utf-8")
        for m in QUOTA_RE.finditer(text):
            result[m.group(1).strip()] = int(m.group(2))
    except Exception:
        pass
    return result


def count_pomodoros(cfg: dict, d: date) -> dict:
    """返回今日完成的 work 番茄钟计数 {task_path: count}"""
    result = {}
    try:
        data = json.loads(Path(cfg["data_json_path"]).read_text(encoding="utf-8"))
        today = d.strftime("%Y-%m-%d")
        for e in data.get("pomodoroHistory", []):
            if e.get("type") == "work" and e.get("completed") is True and e.get("startTime", "").startswith(today) and "taskPath" in e:
                p = e["taskPath"]
                result[p] = result.get(p, 0) + 1
    except Exception:
        pass
    return result


def task_done_count(task_name: str, pomo_counts: dict) -> int:
    """路径后缀匹配，统计 task_name 的完成数"""
    suffix = f"{task_name.lower()}.md"
    return sum(v for k, v in pomo_counts.items() if k.lower().endswith(suffix))


# ---------------------------------------------------------------------------
# 弹窗
# ---------------------------------------------------------------------------
def show_alert(overloaded: list, pending: list) -> None:
    """
    overloaded: [(task_name, done, quota), ...]
    pending:    [(task_name, done, quota), ...]
    """
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass

    root = tk.Tk()
    root.withdraw()

    win = tk.Toplevel(root)
    win.title("任务监控 — 超时警告")
    win.attributes("-topmost", True)
    win.resizable(False, False)
    win.configure(bg="#1a1a1a")

    # 红色警告区
    for task_name, done, quota in overloaded:
        tk.Label(
            win,
            text=f"🛑  [{task_name}]\n已花费 {done}/{quota} 个番茄钟，严重超时！",
            fg="#ff4444",
            bg="#1a1a1a",
            font=("Microsoft YaHei", 13, "bold"),
            wraplength=640,
            justify="center",
            pady=4,
        ).pack(padx=28, pady=(18, 4))

    # 分隔线
    tk.Frame(win, height=1, bg="#444444").pack(fill="x", padx=28, pady=10)

    # 绿色引导区
    if pending:
        tk.Label(
            win,
            text="请立即切换至以下任务：",
            fg="#888888",
            bg="#1a1a1a",
            font=("Microsoft YaHei", 10),
        ).pack()
        for task_name, done, quota in pending:
            tk.Label(
                win,
                text=f"🟢  [{task_name}]  (已做 {done}/{quota})",
                fg="#44dd44",
                bg="#1a1a1a",
                font=("Microsoft YaHei", 12),
                wraplength=640,
                justify="center",
                pady=2,
            ).pack(padx=28, pady=3)
    else:
        tk.Label(
            win,
            text="📋  今日所有计划任务均已完成！",
            fg="#44dd44",
            bg="#1a1a1a",
            font=("Microsoft YaHei", 12),
        ).pack(padx=28, pady=8)

    # 关闭按钮
    def on_close():
        win.destroy()
        root.destroy()

    tk.Button(
        win,
        text="我知道了，关闭",
        command=on_close,
        bg="#333333",
        fg="#ffffff",
        activebackground="#555555",
        activeforeground="#ffffff",
        font=("Microsoft YaHei", 11),
        relief="flat",
        padx=20,
        pady=8,
        cursor="hand2",
    ).pack(pady=(8, 22))

    win.protocol("WM_DELETE_WINDOW", on_close)

    # 屏幕居中
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    root.mainloop()


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------
def run() -> None:
    cfg = load_config()
    interval = cfg.get("poll_interval", 3)

    current_date = date.today()
    last_alerted: dict = {}  # {task_name: done_count_at_last_alert}
    mtime_daily = None
    mtime_json = None

    print(f"[TaskMonitor] 启动  |  轮询间隔 {interval}s")
    print(f"[TaskMonitor] Daily:     {cfg['daily_notes_path']}")
    print(f"[TaskMonitor] data.json: {cfg['data_json_path']}")

    while True:
        try:
            today = date.today()

            # 跨夜重置
            if today != current_date:
                current_date = today
                last_alerted.clear()
                mtime_daily = mtime_json = None
                print(f"[TaskMonitor] 跨夜 → 重置为 {current_date}")

            # 读取 mtime
            try:
                new_mtime_daily = daily_note_path(cfg, current_date).stat().st_mtime
            except FileNotFoundError:
                new_mtime_daily = None

            try:
                new_mtime_json = Path(cfg["data_json_path"]).stat().st_mtime
            except FileNotFoundError:
                new_mtime_json = None

            # 只要有文件变化才重新解析
            if new_mtime_daily != mtime_daily or new_mtime_json != mtime_json:
                mtime_daily = new_mtime_daily
                mtime_json = new_mtime_json

                quotas = parse_quotas(cfg, current_date)
                pomo = count_pomodoros(cfg, current_date)

                alerts = []
                pending = []

                for task_name, quota in quotas.items():
                    done = task_done_count(task_name, pomo)
                    if done >= quota:
                        prev = last_alerted.get(task_name)
                        if prev is None or done > prev:
                            alerts.append((task_name, done, quota))
                            last_alerted[task_name] = done
                    else:
                        pending.append((task_name, done, quota))

                # 每次文件变化都打印当前状态
                print(f"\n[TaskMonitor] {current_date}  ─────────────────────────────")
                for task_name, quota in quotas.items():
                    done = task_done_count(task_name, pomo)
                    bar = "█" * done + "░" * max(0, quota - done)
                    status = "⚠ OVER" if done >= quota else "OK"
                    print(f"  [{status}]  {done}/{quota}  {bar}  {task_name}")
                print()

                if alerts:
                    print(f"[TaskMonitor] 触发警告: {[t[0] for t in alerts]}")
                    show_alert(alerts, pending)

        except Exception as e:
            print(f"[TaskMonitor] 异常 (已忽略): {e}")

        time.sleep(interval)


if __name__ == "__main__":
    run()
