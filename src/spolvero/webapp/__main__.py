"""`python -m spolvero.webapp` —— 启动控制台（**手动启动工作台就用这一条**）。

    python -m spolvero.webapp                  # 默认 http://127.0.0.1:8760/
    python -m spolvero.webapp --port 8770      # 换端口（8760 被占了就用这个）

参数在这里自己解析，不依赖 `spol studio`：控制台是给人手动开的，
少一层入口就少一处"为什么起不来"。
"""

from __future__ import annotations

import argparse

from .app import main

if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="python -m spolvero.webapp",
                                description="Spolvero 工作台（Web 控制台）")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8760)
    p.add_argument("--debug", action="store_true")
    a = p.parse_args()
    raise SystemExit(main(host=a.host, port=a.port, debug=a.debug))
