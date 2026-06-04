# -*- coding:utf-8 -*-
"""Start and inspect the mitmproxy setup for Dianping mini-program capture."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_PROXY_PORT = 9092
DEFAULT_WEB_PORT = 9093
DEFAULT_UPSTREAM = "http://127.0.0.1:7890/"


def port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def mitm_processes() -> list[tuple[int, str]]:
    result = subprocess.run(["pgrep", "-af", "mitm"], capture_output=True, text=True, check=False)
    processes = []
    for line in result.stdout.splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        cmd = parts[1]
        if "mitmweb" in cmd or "mitmdump" in cmd:
            processes.append((pid, cmd))
    return processes


def stop_mitm_processes() -> None:
    current_pid = os.getpid()
    for pid, cmd in mitm_processes():
        if pid == current_pid:
            continue
        print(f"停止旧 mitm 进程: pid={pid} {cmd}")
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue
    deadline = time.time() + 5
    while time.time() < deadline:
        if not mitm_processes():
            return
        time.sleep(0.2)


def build_command(args: argparse.Namespace) -> list[str]:
    scripts = [ROOT_DIR / "dianping_interceptor.py"]
    if args.queue:
        scripts.append(ROOT_DIR / "mitm_queue_interceptor.py")
    cmd = [
        "mitmweb",
        "--listen-port",
        str(args.proxy_port),
        "--web-port",
        str(args.web_port),
        "--set",
        "ssl_insecure=true",
    ]
    for script in scripts:
        cmd.extend(["-s", str(script)])
    if args.upstream:
        cmd.extend(["--mode", f"upstream:{args.upstream}"])
    return cmd


def print_status(proxy_port: int, web_port: int) -> None:
    print(f"proxy 127.0.0.1:{proxy_port}: {'OK' if port_open('127.0.0.1', proxy_port) else '未监听'}")
    print(f"web   127.0.0.1:{web_port}: {'OK' if port_open('127.0.0.1', web_port) else '未监听'}")
    processes = mitm_processes()
    if processes:
        for pid, cmd in processes:
            print(f"mitm pid={pid}: {cmd}")
    else:
        print("mitm进程: 无")


def main() -> int:
    parser = argparse.ArgumentParser(description="启动/检查大众点评 mitmproxy 采集服务")
    parser.add_argument("--proxy-port", type=int, default=DEFAULT_PROXY_PORT)
    parser.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT)
    parser.add_argument("--upstream", default=DEFAULT_UPSTREAM, help="上游代理；空字符串表示不用")
    parser.add_argument("--queue", action="store_true", help="同时加载队列式评论请求改写脚本")
    parser.add_argument("--replace", action="store_true", help="停止旧 mitmweb 后重新启动")
    parser.add_argument("--status", action="store_true", help="只检查状态")
    args = parser.parse_args()

    if args.status:
        print_status(args.proxy_port, args.web_port)
        return 0

    if args.replace:
        stop_mitm_processes()

    if port_open("127.0.0.1", args.proxy_port) or port_open("127.0.0.1", args.web_port):
        print("端口已被占用。当前状态：")
        print_status(args.proxy_port, args.web_port)
        print("如果要替换旧服务，运行：python3 mitm_manager.py --queue --replace")
        return 2

    cmd = build_command(args)
    print("启动:")
    print(" ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
