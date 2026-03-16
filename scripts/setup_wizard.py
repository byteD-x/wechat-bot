#!/usr/bin/env python3
"""
微信机器人首次配置向导。

运行方式:
    python setup_wizard.py

功能:
    - 交互式选择 API 预设
    - 填写 API 密钥
    - 自动生成 api_keys.py
    - 测试 API 连接
    - 配置基础参数
"""

import os
import sys
import asyncio
from typing import Optional, Dict, Any
import json

# 项目根目录（bot 目录的父目录）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 添加到 Python 路径
sys.path.insert(0, PROJECT_ROOT)

# ═══════════════════════════════════════════════════════════════════════════════
#                               预设信息
# ═══════════════════════════════════════════════════════════════════════════════

PRESETS = [
    {
        "name": "Doubao",
        "display": "豆包 (Doubao) - 字节跳动",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-seed-1-8-251228",
        "price_hint": "￥0.002/千tokens，性价比高",
        "key_url": "https://console.volcengine.com/ark",
    },
    {
        "name": "DeepSeek",
        "display": "DeepSeek - 深度求索",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "price_hint": "￥0.001/千tokens，国产高性价比",
        "key_url": "https://platform.deepseek.com/api_keys",
    },
    {
        "name": "OpenAI",
        "display": "OpenAI GPT-4o-mini",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "price_hint": "$0.15/百万tokens，全球领先",
        "key_url": "https://platform.openai.com/api-keys",
    },
    {
        "name": "Zhipu",
        "display": "智谱 GLM-4.5",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4.5-air",
        "price_hint": "￥0.001/千tokens，清华系",
        "key_url": "https://open.bigmodel.cn/usercenter/apikeys",
    },
    {
        "name": "Moonshot",
        "display": "Moonshot Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "price_hint": "￥0.012/千tokens，长文本处理强",
        "key_url": "https://platform.moonshot.cn/console/api-keys",
    },
    {
        "name": "SiliconFlow",
        "display": "SiliconFlow (第三方聚合)",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3",
        "price_hint": "多模型聚合平台",
        "key_url": "https://cloud.siliconflow.cn/account/ak",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
#                               工具函数
# ═══════════════════════════════════════════════════════════════════════════════


def clear_screen():
    """清屏"""
    os.system("cls" if os.name == "nt" else "clear")


def print_header():
    """打印头部"""
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║          🤖 微信 AI 机器人 - 首次配置向导                    ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()


def print_step(step: int, title: str):
    """打印步骤标题"""
    print(f"\n{'─' * 60}")
    print(f"  📌 步骤 {step}: {title}")
    print(f"{'─' * 60}\n")


def input_with_default(prompt: str, default: str = "") -> str:
    """带默认值的输入"""
    if default:
        result = input(f"{prompt} [{default}]: ").strip()
        return result if result else default
    return input(f"{prompt}: ").strip()


def input_choice(prompt: str, options: list, default: int = 1) -> int:
    """选择输入"""
    while True:
        try:
            choice = input(f"{prompt} [1-{len(options)}，默认{default}]: ").strip()
            if not choice:
                return default
            idx = int(choice)
            if 1 <= idx <= len(options):
                return idx
        except ValueError:
            pass
        print("❌ 无效选择，请重新输入")


def input_confirm(prompt: str, default: bool = True) -> bool:
    """确认输入"""
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        result = input(f"{prompt} {hint}: ").strip().lower()
        if not result:
            return default
        if result in ("y", "yes", "是"):
            return True
        if result in ("n", "no", "否"):
            return False
        print("❌ 请输入 y 或 n")


# ═══════════════════════════════════════════════════════════════════════════════
#                               API 测试
# ═══════════════════════════════════════════════════════════════════════════════


async def test_api_connection(
    base_url: str, api_key: str, model: str
) -> tuple[bool, str]:
    """测试 API 连接"""
    try:
        import httpx
    except ImportError:
        return False, "缺少 httpx 依赖，请运行: pip install httpx"

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 5,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return True, "连接成功"
            elif resp.status_code == 401:
                return False, "API 密钥无效"
            elif resp.status_code == 404:
                return False, "模型不存在或接口地址错误"
            else:
                return False, f"HTTP {resp.status_code}: {resp.text[:100]}"
    except httpx.TimeoutException:
        return False, "连接超时，请检查网络"
    except Exception as e:
        return False, f"连接失败: {str(e)}"


# ═══════════════════════════════════════════════════════════════════════════════
#                               文件生成
# ═══════════════════════════════════════════════════════════════════════════════


def generate_api_keys_file(preset_name: str, api_key: str) -> str:
    """生成 api_keys.py 文件内容"""
    return f'''"""
自动生成的 API 密钥配置文件。
由 setup_wizard.py 于配置向导中创建。

⚠️ 此文件包含敏感信息，请勿提交到版本控制！
"""

API_KEYS = {{
    "default": "{api_key}",
    "presets": {{
        "{preset_name}": "{api_key}",
    }},
}}
'''


def save_api_keys(preset_name: str, api_key: str) -> bool:
    """保存 api_keys.py 到 data 目录"""
    content = generate_api_keys_file(preset_name, api_key)
    data_dir = os.path.join(PROJECT_ROOT, "data")
    os.makedirs(data_dir, exist_ok=True)
    api_keys_path = os.path.join(data_dir, "api_keys.py")
    try:
        with open(api_keys_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"❌ 保存失败: {e}")
        return False


def update_config_preset(preset_name: str) -> bool:
    """更新 data/config_override.json 中的 active_preset（不直接改源码配置）。"""
    override_dir = os.path.join(PROJECT_ROOT, "data")
    os.makedirs(override_dir, exist_ok=True)
    override_path = os.path.join(override_dir, "config_override.json")

    try:
        overrides = {}
        if os.path.exists(override_path):
            with open(override_path, "r", encoding="utf-8") as f:
                overrides = json.load(f) or {}
        if not isinstance(overrides, dict):
            overrides = {}

        api = overrides.get("api")
        if not isinstance(api, dict):
            api = {}
        api["active_preset"] = str(preset_name)
        overrides["api"] = api

        tmp_path = override_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(overrides, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, override_path)
        return True
    except Exception as e:
        print(f"⚠️ 更新 config_override.json 失败: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#                               主流程
# ═══════════════════════════════════════════════════════════════════════════════


async def run_wizard():
    """运行配置向导"""
    clear_screen()
    print_header()

    print("欢迎使用微信 AI 机器人！")
    print("本向导将帮助您完成首次配置，整个过程约需 2 分钟。\n")

    api_keys_path = os.path.join(PROJECT_ROOT, "data", "api_keys.py")
    if os.path.exists(api_keys_path):
        if not input_confirm("⚠️ 检测到已有配置文件，是否覆盖？", default=False):
            print("\n取消配置，保留现有设置。")
            return

    # ───────────────────────────────────────────────────────────────────────────
    # 步骤 1: 选择 API 服务商
    # ───────────────────────────────────────────────────────────────────────────
    print_step(1, "选择 AI 服务商")

    print("请选择您要使用的 AI 服务（推荐豆包或 DeepSeek）:\n")
    for i, preset in enumerate(PRESETS, 1):
        print(f"  {i}. {preset['display']}")
        print(f"     💰 {preset['price_hint']}\n")

    choice = input_choice("请选择", PRESETS, default=1)
    selected_preset = PRESETS[choice - 1]
    print(f"\n✅ 已选择: {selected_preset['display']}")

    # ───────────────────────────────────────────────────────────────────────────
    # 步骤 2: 输入 API 密钥
    # ───────────────────────────────────────────────────────────────────────────
    print_step(2, "输入 API 密钥")

    print(f"请输入您的 {selected_preset['name']} API 密钥。")
    print(f"获取地址: {selected_preset['key_url']}")
    print("（如果还没有，请先到官网申请）\n")

    api_key = ""
    while not api_key:
        api_key = input("API 密钥: ").strip()
        if not api_key:
            print("❌ 密钥不能为空")

    # 隐藏显示密钥
    masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
    print(f"\n✅ 密钥已记录: {masked_key}")

    # ───────────────────────────────────────────────────────────────────────────
    # 步骤 3: 测试连接
    # ───────────────────────────────────────────────────────────────────────────
    print_step(3, "测试 API 连接")

    print("正在测试连接，请稍候...")
    success, message = await test_api_connection(
        selected_preset["base_url"],
        api_key,
        selected_preset["model"],
    )

    if success:
        print(f"✅ {message}")
    else:
        print(f"❌ {message}")
        if not input_confirm("连接失败，是否仍要保存配置？", default=False):
            print("\n配置已取消。")
            return

    # ───────────────────────────────────────────────────────────────────────────
    # 步骤 4: 保存配置
    # ───────────────────────────────────────────────────────────────────────────
    print_step(4, "保存配置")

    if save_api_keys(selected_preset["name"], api_key):
        print("✅ 已生成 api_keys.py")
    else:
        print("❌ 保存失败")
        return

    if update_config_preset(selected_preset["name"]):
        print(f"✅ 已将 active_preset 设为 '{selected_preset['name']}'")

    # ───────────────────────────────────────────────────────────────────────────
    # 完成
    # ───────────────────────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  🎉 配置完成！")
    print("═" * 60)
    print(f"""
您的配置摘要:
  • AI 服务: {selected_preset["display"]}
  • 模型: {selected_preset["model"]}
  • 配置文件: data/api_keys.py

下一步:
  1. 确保微信 PC 版 3.9.x 已登录
  2. 运行机器人: python run.py
  3. 如有问题运行: python run.py check

祝您使用愉快！ 🚀
""")


def main():
    """入口函数"""
    if sys.version_info < (3, 8):
        print("❌ 需要 Python 3.8 或更高版本")
        sys.exit(1)

    try:
        asyncio.run(run_wizard())
    except KeyboardInterrupt:
        print("\n\n已取消配置。")
        sys.exit(0)


if __name__ == "__main__":
    main()
