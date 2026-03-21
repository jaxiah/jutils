#!/usr/bin/env python3
"""
clang_format_dir.py — 批量 clang-format 格式化

递归扫描目录下所有 C/C++/CUDA/GLSL/HLSL 源文件并用 clang-format 原地格式化.
要求目录下存在 .clang-format, 否则跳过该目录. 多线程并行加速.

用法
----
    python clang_format_dir.py src/                  # 格式化 src/ 下所有文件
    python clang_format_dir.py src/ include/ -j 16   # 多目录, 16 线程

设计要点
--------
- queue + threading 多线程, 默认 8 线程, 上限为文件总数
- clang-format 使用 -style=file, 读取各文件所在目录向上搜索到的 .clang-format
- tqdm 进度条按目录分段显示

Changelog
---------
2026-03-21  重构: argparse CLI; 修复 shell=True; 规范文件头; 支持多目录和 -j 参数
"""

import queue
import subprocess
import sys
import threading
from pathlib import Path

from tqdm import tqdm

EXTS = {
    ".h",
    ".hh",
    ".hpp",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".cl",
    ".cu",
    ".cuh",
    ".vert",
    ".frag",
    ".comp",
    ".hlsl",
    ".glsl",
}


def _worker(file_queue: "queue.Queue[Path]", pbar: tqdm) -> None:
    while True:
        try:
            path = file_queue.get_nowait()
        except queue.Empty:
            break
        try:
            subprocess.run(["clang-format", "-style=file", "-i", str(path)], check=True)
        except subprocess.CalledProcessError as e:
            print(f"[error] {path}: {e}", file=sys.stderr)
        except FileNotFoundError:
            print("clang-format not found in PATH.", file=sys.stderr)
            sys.exit(1)
        finally:
            file_queue.task_done()
            pbar.update(1)


def format_dir(root: Path, jobs: int) -> None:
    if not (root / ".clang-format").exists():
        print(f"[skip] no .clang-format in {root}", file=sys.stderr)
        return

    files = [p for p in root.rglob("*") if p.suffix in EXTS]
    if not files:
        print(f"[skip] no matching files in {root}", file=sys.stderr)
        return

    file_queue: "queue.Queue[Path]" = queue.Queue()
    for f in files:
        file_queue.put(f)

    with tqdm(total=len(files), desc=str(root)) as pbar:
        threads = [threading.Thread(target=_worker, args=(file_queue, pbar), daemon=True) for _ in range(min(jobs, len(files)))]
        for t in threads:
            t.start()
        file_queue.join()
        for t in threads:
            t.join()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Batch clang-format for C/C++/CUDA/GLSL source trees.")
    parser.add_argument("dirs", nargs="+", metavar="DIR", help="Directory/directories to format.")
    parser.add_argument("-j", "--jobs", type=int, default=8, metavar="N", help="Number of parallel threads (default: 8).")
    args = parser.parse_args()

    for d in args.dirs:
        root = Path(d)
        if not root.is_dir():
            print(f"[error] not a directory: {d}", file=sys.stderr)
            continue
        format_dir(root, args.jobs)


if __name__ == "__main__":
    main()
