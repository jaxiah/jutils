#!/usr/bin/env python3
"""
tasknotes_quota_monitor.py — Obsidian TaskNotes 番茄钟配额守护进程

每 N 秒轮询日记文件与 TaskNotes data.json 的 mtime，当某任务完成的番茄钟
数量达到或超出当日配额时，弹出 tkinter 置顶窗口强制打断，并展示尚有盈余
的任务引导切换。弹窗需手动关闭，确保打断效果。

设计要点
--------
- 输入 A：DailyNotes/YYYY-MM-DD.md，提取 `- [[任务名]] : N` 格式的配额声明。
- 输入 B：TaskNotes/data.json，统计今日 type=work、completed=true 的条目。
- 匹配：用路径后缀匹配（endswith("{task}.md")），消除路径前缀差异造成的误判。
- 防骚扰：内存字典记录每个任务上次警告时的完成数，只有完成数继续增加才再次触发。
- 跨夜：零点后自动切换至次日日记路径，清空警告历史。
- 容错：文件不存在或 JSON 读写冲突时静默跳过，等待下一个轮询周期。
- 配额变更：日记保存后若配额变动，受影响任务立即用新配额重新评估。

Config
------
首次运行时自动生成 tasknotes_quota_monitor.config.json，填入路径后重新运行。

Changelog
---------
2026-03-21  per-script config 自动生成；从 monitor.py 重命名
2026-03-21  日记配额变更时清除对应任务的警告历史，立即重新评估
2026-03-21  区分"额度已用完"（done==quota）与"严重超时"（done>quota）
2026-03-21  initial implementation
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
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "daily_notes_path": "填入你的 Obsidian 日记目录路径，例如 D:/JNote/daily",
    "data_json_path": "填入 TaskNotes data.json 的完整路径，例如 D:/JNote/.obsidian/plugins/tasknotes/data.json",
    "poll_interval": 3,
}


def load_config() -> dict:
    path = Path(__file__).with_suffix(".config.json")
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.exit(f"已生成配置文件 {path.name}，请填入路径后重新运行。")
    return json.loads(path.read_text(encoding="utf-8"))


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
        msg = f"🛑  [{task_name}]\n{'额度已用完' if done == quota else f'已花费 {done}/{quota} 个番茄钟，严重超时！'}"
        tk.Label(
            win,
            text=msg,
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
    last_quotas: dict = {}  # {task_name: quota}，用于检测配额变化
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
            daily_changed = new_mtime_daily != mtime_daily
            if daily_changed or new_mtime_json != mtime_json:
                mtime_daily = new_mtime_daily
                mtime_json = new_mtime_json

                quotas = parse_quotas(cfg, current_date)
                pomo = count_pomodoros(cfg, current_date)

                # 日记变化时，配额有变动的任务清除警告记录，让其重新评估
                if daily_changed:
                    for task_name, quota in quotas.items():
                        if last_quotas.get(task_name) != quota:
                            last_alerted.pop(task_name, None)
                last_quotas = quotas

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
                    status = "⚠ FULL" if done == quota else ("✘ OVER" if done > quota else "OK   ")
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
