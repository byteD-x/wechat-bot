"""
聊天记录分析与个性化 Prompt 生成工具。

功能：
    1. 从 chat_exports/聊天记录 目录读取 CSV 聊天记录
    2. 统计每个联系人的消息数量
    3. 找出聊天最多的 Top N 联系人
    4. 为每个 Top N 联系人生成个性化 system_prompt
    5. 保存生成的 prompt 到对应目录

使用方法：
    python prompt_generator.py                  # 完整执行（需要 AI API）
    python prompt_generator.py --dry-run        # 仅统计，不调用 AI
    python prompt_generator.py --top 5          # 只处理 Top 5 联系人
    python prompt_generator.py --limit 100      # 每个联系人最多分析 100 条消息（默认不限制）
"""

import os
import sys
import json
import logging
import argparse
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

# 添加项目根目录 to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import project modules
from backend.config import CONFIG, _apply_api_keys
from backend.core.ai_client import AIClient
from backend.core.factory import apply_ai_runtime_settings
from tools.prompt_gen.csv_loader import (
    EXCLUDED_CONTACTS,
    NON_TEXT_TYPES,
    extract_contact_name,
    load_chat_from_csv,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 路径配置
CHAT_EXPORTS_DIR = "chat_exports"
CHAT_RECORDS_SUBDIR = "聊天记录"
CHAT_RECORDS_BASE = os.path.join(CHAT_EXPORTS_DIR, CHAT_RECORDS_SUBDIR)

META_PROMPT_TEMPLATE = """
你是一个专业的对话风格分析师。请根据以下与"{contact_name}"的聊天记录进行深度分析，生成一个高度个性化的 system_prompt。
目标：让 AI 完美模仿「主人」（知有）的身份与此人进行微信对话，让对方完全感觉在和真人聊天。

【聊天记录样本】
{chat_history_text}

【分析维度要求】
请从以下维度进行深入分析：
1. 语言特征：用词习惯、句式结构、标点符号使用
2. 情感表达：表情包频率、情绪词汇、互动温度
3. 关系特征：亲密度、互动模式、共同话题
4. 网络用语：谐音梗、缩写词（如 yyds、xswl、emo）、方言习惯
5. 时间特征：聊天活跃时段、回复速度习惯

【输出要求】
- 直接输出内容，不要包含 ```markdown 等代码块标记
- 不要有任何解释性文字，直接输出配置
- 严格遵循模板结构，保持 markdown 格式

---
# 身份
你是「知有」本人在微信上的分身。你不是 AI 助手，而是主人本人在回复消息。
对方不知道这是代答，你的目标是让 TA 感觉在和主人真人聊天。

# 核心规则
## 1. 风格复刻
- 称呼方式：对方称你为（具体分析），你称对方为（具体分析）
- 用词偏好：高频词汇列表，语气词（「呢」「呀」「嘛」等），口头禅/网络用语
- 句子风格：句子长度特征、标点习惯、省略主语习惯、换行习惯
- 表情习惯：最常用的5个表情/表情包，使用频率（高/中/低），插入位置习惯
- 关系亲疏：关系类型（闺蜜/兄弟/同事/普通朋友等），互动特点描述

## 2. 回复规范
- 长度：1-3句话，模仿真实微信聊天节奏
- 格式：禁用列表/编号/标题，纯自然口语
- 语气：（根据分析填写：轻松随意/幽默吐槽/关心温暖/毒舌互怼等）

## 3. 个性化注意事项
- 聊到（高频话题1）时，应该（对应回应策略）
- 对方经常说（口头禅/网络用语），回应时可用（类似表达）
- 关系特点补充说明（如：可互损但避免过度、需要给予更多关心等）

## 4. 绝对禁止
- ❌ 暴露 AI 身份
- ❌ 自称「AI」「助手」
- ❌ 过度热情或客服语气
---
"""

def count_messages_per_contact(base_dir: str) -> List[Tuple[str, str, int, int]]:
    """
    遍历所有联系人目录，统计消息数量。

    Args:
        base_dir: 聊天记录根目录

    Returns:
        列表，每项为 (联系人名, 目录路径, 总消息数, 文本消息数)
    """
    stats = []

    if not os.path.exists(base_dir):
        logger.error(f"Chat records directory not found: {base_dir}")
        return stats

    for contact_dir in os.listdir(base_dir):
        dir_path = os.path.join(base_dir, contact_dir)
        if not os.path.isdir(dir_path):
            continue

        # 提取联系人名（去掉括号里的 wxid）
        contact_name = extract_contact_name(contact_dir)

        # 跳过系统账号
        if contact_name in EXCLUDED_CONTACTS:
            continue

        # 查找 CSV 文件
        csv_files = [f for f in os.listdir(dir_path) if f.endswith('.csv')]
        if not csv_files:
            continue

        csv_path = os.path.join(dir_path, csv_files[0])
        records = load_chat_from_csv(csv_path)

        total_count = len(records)
        text_count = sum(1 for r in records if r['msg_type'] == '文本')

        if total_count > 0:
            stats.append((contact_name, dir_path, total_count, text_count))

    # 按总消息数降序排序
    stats.sort(key=lambda x: x[2], reverse=True)
    return stats


def get_top_contacts(stats: List[Tuple[str, str, int, int]], limit: int = 10) -> List[Tuple[str, str, int, int]]:
    """获取消息数最多的 Top N 联系人。"""
    return stats[:limit]


def format_history_for_prompt(records: List[Dict[str, Any]], limit: int = 50) -> str:
    """
    格式化聊天记录用于 prompt。
    
    优化：合并同一发送者的连续消息，减少 Token 消耗并提供更连贯的上下文。
    只包含文本消息，最多取最近 limit 条。
    """
    # 过滤只保留文本消息
    text_records = [r for r in records if r['msg_type'] == '文本']

    # 取最近的 N 条（limit=0 表示不限制）
    if limit > 0 and len(text_records) > limit:
        recent_records = text_records[-limit:]
    else:
        recent_records = text_records

    lines = []
    if not recent_records:
        return ""

    current_role = None
    current_content_buffer = []

    for msg in recent_records:
        role = "主人" if msg['role'] == 'assistant' else "对方"
        content = msg['content']
        # 截断过长消息
        if len(content) > 100:
            content = content[:100] + "..."
            
        if role == current_role:
            # 同一角色，累积消息
            current_content_buffer.append(content)
        else:
            # 角色切换，先输出上一角色的缓冲内容
            if current_role is not None:
                merged_content = " ".join(current_content_buffer)
                lines.append(f"{current_role}: {merged_content}")
            
            # 开始新角色
            current_role = role
            current_content_buffer = [content]

    # 输出最后一段缓冲内容
    if current_role is not None and current_content_buffer:
        merged_content = " ".join(current_content_buffer)
        lines.append(f"{current_role}: {merged_content}")

    return "\n".join(lines)


async def generate_personalized_prompt(
    ai_client: AIClient,
    contact_name: str,
    records: List[Dict[str, Any]],
    limit: int = 50
) -> Optional[str]:
    """
    调用 AI 生成个性化 prompt。

    Args:
        ai_client: AI 客户端
        contact_name: 联系人名称
        records: 聊天记录列表
        limit: 用于分析的消息数量上限

    Returns:
        生成的 system_prompt 文本
    """
    history_text = format_history_for_prompt(records, limit)
    if not history_text.strip():
        logger.warning(f"No text messages found for {contact_name}")
        return None

    prompt = META_PROMPT_TEMPLATE.format(
        contact_name=contact_name,
        chat_history_text=history_text
    )

    temp_chat_id = f"prompt_gen_{int(datetime.now().timestamp())}"

    try:
        response = await ai_client.generate_reply(
            chat_id=temp_chat_id,
            user_text=prompt,
            system_prompt="你是一个专业的对话风格分析师。请严格按照要求输出配置文本，不要输出任何额外的解释。"
        )
        return response
    except Exception as e:
        logger.error(f"Failed to generate prompt for {contact_name}: {e}")
        return None


async def main():
    parser = argparse.ArgumentParser(
        description="分析聊天记录并为 Top N 联系人生成个性化 prompt"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅统计，不调用 AI 生成 prompt"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="处理聊天最多的 N 个联系人（默认：10）"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="每个联系人分析的消息数量上限（默认：0 表示不限制）"
    )
    args = parser.parse_args()

    # 1. 统计所有联系人的消息数量
    logger.info(f"Scanning chat records from: {CHAT_RECORDS_BASE}")
    all_stats = count_messages_per_contact(CHAT_RECORDS_BASE)
    logger.info(f"Found {len(all_stats)} contacts with chat history")

    if not all_stats:
        logger.error("No chat records found!")
        return

    # 2. 获取 Top N 联系人
    top_contacts = get_top_contacts(all_stats, args.top)

    print("\n" + "=" * 60)
    print(f"Top {len(top_contacts)} 聊天最多的联系人：")
    print("=" * 60)
    for i, (name, dir_path, total, text) in enumerate(top_contacts, 1):
        print(f"  {i:2d}. {name:<20} 总消息: {total:5d}  文本: {text:5d}")
    print("=" * 60 + "\n")

    if args.dry_run:
        logger.info("Dry run mode - skipping AI prompt generation")
        return

    # 3. 初始化 AI 客户端
    _apply_api_keys(CONFIG)

    api_cfg = CONFIG.get("api", {}).copy()
    bot_cfg = CONFIG.get("bot", {})

    # 解析活动预设
    active_preset_name = api_cfg.get("active_preset")
    if active_preset_name:
        presets = api_cfg.get("presets", [])
        target_preset = next(
            (p for p in presets if p.get("name") == active_preset_name),
            None
        )
        if target_preset:
            logger.info(f"Using active preset: {active_preset_name}")
            api_cfg.update(target_preset)

    try:
        ai_client = AIClient(
            base_url=api_cfg.get("base_url"),
            api_key=api_cfg.get("api_key"),
            model=api_cfg.get("model"),
            timeout_sec=60,
            max_retries=api_cfg.get("max_retries", 2),
            model_alias=api_cfg.get("alias"),
        )
        apply_ai_runtime_settings(ai_client, api_cfg, bot_cfg, allow_api_override=True)
        ai_client.timeout_sec = 60.0
        ai_client.max_completion_tokens = 4096
        ai_client.max_tokens = 4096

        logger.info(f"AI Client initialized: {ai_client.model} @ {ai_client.base_url}")

        if not await ai_client.probe():
            logger.error("AI Client probe failed!")
            return

    except Exception as e:
        logger.error(f"Failed to initialize AI Client: {e}")
        return

    # 4. 为每个 Top N 联系人生成 prompt
    prompts_summary = {}

    for i, (contact_name, dir_path, total, text) in enumerate(top_contacts, 1):
        logger.info(f"[{i}/{len(top_contacts)}] Processing: {contact_name}")

        # 加载聊天记录
        csv_files = [f for f in os.listdir(dir_path) if f.endswith('.csv')]
        if not csv_files:
            continue

        csv_path = os.path.join(dir_path, csv_files[0])
        records = load_chat_from_csv(csv_path)

        # 生成 prompt
        logger.info(f"  Generating personalized prompt...")
        generated_prompt = await generate_personalized_prompt(
            ai_client, contact_name, records, args.limit
        )

        if generated_prompt:
            # 保存到联系人目录
            prompt_file = os.path.join(dir_path, "system_prompt.txt")
            with open(prompt_file, "w", encoding="utf-8") as f:
                f.write(generated_prompt)

            prompts_summary[contact_name] = {
                "dir": dir_path,
                "total_messages": total,
                "text_messages": text,
                "prompt": generated_prompt,
            }
            logger.info(f"  ✓ Prompt saved to: {prompt_file}")
        else:
            logger.warning(f"  ✗ Failed to generate prompt")

    # 5. 保存汇总
    if prompts_summary:
        # 构建更结构化的 JSON 输出
        output_data = {
            "metadata": {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "description": f"Top {len(prompts_summary)} 联系人个性化 Prompt 汇总",
                "usage": "将 prompt 字段内容复制到 config.py 的 system_prompt_overrides 中使用"
            },
            "contacts": {
                name: {
                    "stats": {
                        "total_messages": data["total_messages"],
                        "text_messages": data["text_messages"],
                        "directory": data["dir"]
                    },
                    "prompt": data["prompt"]
                }
                for name, data in prompts_summary.items()
            }
        }
        
        summary_file = os.path.join(CHAT_EXPORTS_DIR, "top10_prompts_summary.json")
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Summary saved to: {summary_file}")

        # 生成 prompt_overrides.py 供 config.py 加载
        overrides_file = "prompt_overrides.py"
        with open(overrides_file, "w", encoding="utf-8") as f:
            f.write('"""\n')
            f.write('自动生成的个性化 Prompt 覆盖配置。\n')
            f.write(f'生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write(f'联系人数量：{len(prompts_summary)}\n')
            f.write('\n')
            f.write('此文件由 prompt_generator.py 自动生成，请勿手动编辑。\n')
            f.write('要更新，请重新运行：python prompt_generator.py\n')
            f.write('"""\n\n')
            f.write('# 个性化 Prompt 覆盖字典\n')
            f.write('# 键为联系人名称，值为对应的 system_prompt\n')
            f.write('PROMPT_OVERRIDES = {\n')
            for name, data in prompts_summary.items():
                # 转义字符串中的特殊字符
                prompt_escaped = data["prompt"].replace('\\', '\\\\').replace('"""', '\\"\\"\\"')
                f.write(f'    "{name}": """{prompt_escaped}""",\n\n')
            f.write('}\n')
        logger.info(f"Overrides file saved to: {overrides_file}")

    # 关闭 AI 客户端
    await ai_client.close()

    print("\n" + "=" * 60)
    print(f"完成！已为 {len(prompts_summary)} 个联系人生成个性化 prompt")
    print(f"Prompt 覆盖文件已保存到：prompt_overrides.py")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
