from __future__ import annotations

import asyncio
import os
import sys

# 将项目根目录加入模块搜索路径，确保可以直接运行此文件
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from backend.bot import WeChatBot
from backend.shared_config import get_app_config_path


async def main():
    config_path = get_app_config_path()
    bot = WeChatBot(config_path)
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
