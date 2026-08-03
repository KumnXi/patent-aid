"""
项目通用启动器 - 解决终端卡住问题

功能：
1. 强制行缓冲（print 立即显示）
2. 全局超时保护（防止无限卡死）
3. 网络请求超时兜底

使用方式（在所有脚本开头导入）：
    from scripts.runner import setup
    setup()  # 一行搞定
"""

import sys
import io
import signal
import socket

def setup(encoding='utf-8', timeout_seconds=600):
    """初始化运行环境
    
    Args:
        encoding: 输出编码
        timeout_seconds: 全局超时（秒），默认10分钟
    """
    # 1. 强制 stdout 行缓冲 + UTF-8
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding=encoding, line_buffering=True)
    else:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding=encoding, line_buffering=True
        )
    
    # 2. stderr 也设置
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding=encoding, line_buffering=True)
    
    # 3. 全局超时保护（仅非Windows或支持signal的环境）
    if timeout_seconds and hasattr(signal, 'SIGALRM'):
        def _timeout_handler(signum, frame):
            print(f"\n[TIMEOUT] 脚本执行超过 {timeout_seconds} 秒，强制退出")
            sys.exit(1)
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout_seconds)
    
    # 4. 设置默认 socket 超时（防止网络请求无限等待）
    socket.setdefaulttimeout(30)
    
    # 5. 确保项目根目录在 path 中
    if '.' not in sys.path:
        sys.path.insert(0, '.')
