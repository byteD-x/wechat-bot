"""
情感检测模块 - 分析用户消息的情绪并提供响应建议。

本模块提供两种情感检测模式：
- keywords: 基于关键词的快速检测（低延迟，适合大多数场景）
- ai: 使用 AI 进行精准分析（更准确，但有额外 API 调用开销）

人性化增强功能：
- 时间感知：根据时间段调整问候语（早安/晚安等）
- 情绪趋势分析：分析用户情绪变化趋势
- 对话风格适应：学习并适应用户的沟通风格
- 关系演进：基于互动次数自动调整关系亲密度

主要类:
    EmotionResult: 情感检测结果的数据类

主要函数:
    detect_emotion_keywords: 基于关键词检测情绪
    get_emotion_analysis_prompt: 生成 AI 情感分析的 prompt
    parse_emotion_ai_response: 解析 AI 返回的情感分析结果
    get_time_aware_prompt_addition: 生成时间感知的提示词
    analyze_conversation_style: 分析用户对话风格

使用示例:
    >>> from emotion import detect_emotion_keywords
    >>> result = detect_emotion_keywords("今天太开心了！")
    >>> print(result.emotion)  # "happy"
    >>> print(result.intensity)  # 4
"""

from __future__ import annotations

import re
import json
import os
from ..schemas import EmotionResult
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, FrozenSet, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════════════════
#                               数据类定义
# ═══════════════════════════════════════════════════════════════════════════════


# EmotionResult 已迁移至 backend/schemas.py


# ═══════════════════════════════════════════════════════════════════════════════
#                            情绪关键词与配置
# ═══════════════════════════════════════════════════════════════════════════════

# 加载外部配置
_config_path = os.path.join(os.path.dirname(__file__), "emotions.json")
_EMOTION_CONFIG = {}
try:
    with open(_config_path, "r", encoding="utf-8") as f:
        _EMOTION_CONFIG = json.load(f)
except Exception as e:
    # 简单的 fallback 或记录错误
    print(f"Error loading emotions.json: {e}")

# 情绪类型及对应的关键词和表情
EMOTION_KEYWORDS: Dict[str, List[str]] = _EMOTION_CONFIG.get("keywords", {})

# 情绪对应的回复语气建议
EMOTION_RESPONSE_GUIDE: Dict[str, str] = {
    "happy": "配合轻松愉快的语气，可以分享喜悦，使用积极的回应",
    "sad": "温暖关心，表示理解和同情，不要说教或轻描淡写",
    "angry": "先共情理解对方的感受，不要激化情绪，适当安抚",
    "anxious": "冷静安抚，表示理解，适当给出建议或帮助",
    "excited": "积极回应，配合热情，一起分享期待的心情",
    "tired": "表示关心体谅，语气轻松温和，不要施加压力",
    "confused": "耐心解释，语气友好，帮助理清思路",
    "neutral": "正常交流即可，保持自然",
}

# 情绪强度词（修饰词影响强度判断）
INTENSITY_MODIFIERS: Dict[str, int] = {
    "非常": 2, "特别": 2, "超级": 2, "太": 2, "好": 1,
    "有点": -1, "有些": -1, "稍微": -1, "略": -1,
    "真的": 1, "真是": 1, "简直": 2, "完全": 2,
}

# 预编译：将关键词列表转为 tuple 以加速迭代（比 set 迭代更快）
_EMOTION_KEYWORDS_TUPLE: Dict[str, Tuple[str, ...]] = {
    emotion: tuple(kw.lower() for kw in keywords)
    for emotion, keywords in EMOTION_KEYWORDS.items()
}

# 缓存的中性结果，避免重复创建
_NEUTRAL_RESULT = EmotionResult(
    emotion="neutral",
    confidence=0.5,
    intensity=1,
    keywords_matched=(),
    suggested_tone=EMOTION_RESPONSE_GUIDE["neutral"],
)

# 预编译 Emoji 正则表达式
_EMOJI_PATTERN = re.compile(r'[\U0001F300-\U0001F9FF]')


def detect_emotion_keywords(text: str) -> EmotionResult:
    """
    基于关键词检测情绪。
    
    优化：使用 tuple 进行迭代查找（比 set 更快），
    预分配结果避免重复对象创建。
    """
    if not text:
        return _NEUTRAL_RESULT

    return _detect_emotion_keywords_cached(text.lower())


@lru_cache(maxsize=2048)
def _detect_emotion_keywords_cached(text_lower: str) -> EmotionResult:
    """带缓存的关键词情感识别。"""
    if not text_lower:
        return _NEUTRAL_RESULT

    # 使用列表推导式替代循环，更高效
    emotion_scores: Dict[str, Tuple[int, List[str]]] = {}
    
    for emotion, keywords in _EMOTION_KEYWORDS_TUPLE.items():
        # 遍历 keywords，检查是否包含在 text 中
        matched = [kw for kw in keywords if kw in text_lower]
        if matched:
            emotion_scores[emotion] = (len(matched), matched)

    if not emotion_scores:
        return _NEUTRAL_RESULT

    # 选择匹配最多的情绪（使用 max 的 key 参数直接获取）
    best_emotion = max(emotion_scores, key=lambda e: emotion_scores[e][0])
    match_count, matched_keywords = emotion_scores[best_emotion]

    # 计算置信度（使用 min 避免超过 0.9）
    confidence = min(0.9, 0.5 + match_count * 0.15)

    # 计算强度（使用 next + generator 找到第一个匹配的修饰词）
    base_intensity = min(5, 1 + match_count)
    modifier_delta = next(
        (mod_value for modifier, mod_value in INTENSITY_MODIFIERS.items() 
         if modifier in text_lower),
        0
    )
    intensity = max(1, min(5, base_intensity + modifier_delta))

    return EmotionResult(
        emotion=best_emotion,
        confidence=confidence,
        intensity=intensity,
        keywords_matched=tuple(matched_keywords),
        suggested_tone=EMOTION_RESPONSE_GUIDE.get(
            best_emotion, EMOTION_RESPONSE_GUIDE["neutral"]
        ),
    )


def get_emotion_response_guide(emotion: str) -> str:
    """获取情绪对应的回复语气建议"""
    return EMOTION_RESPONSE_GUIDE.get(
        emotion.lower(), EMOTION_RESPONSE_GUIDE["neutral"]
    )


def get_emotion_analysis_prompt(message: str) -> str:
    """生成用于 AI 情感分析的 prompt"""
    return f'''你是一个情绪识别器。请读取用户消息并只输出一个 JSON 对象，不要输出任何额外文字或 Markdown 代码块。

约束：
- emotion 只能是以下之一：happy / sad / angry / anxious / excited / tired / confused / neutral
- confidence 必须是 0.0-1.0 的数字
- intensity 必须是 1-5 的整数
- suggested_tone 用一句话描述建议的回复语气
- 如无法判断，emotion=neutral，confidence=0.5，intensity=3

用户消息：{message}

只输出如下 JSON（字段名必须一致）：
{{
  "emotion": "neutral",
  "confidence": 0.5,
  "intensity": 3,
  "reasoning": "简短说明判断理由",
  "suggested_tone": "建议的回复语气"
}}'''


def parse_emotion_ai_response(response: str) -> Optional[EmotionResult]:
    """解析 AI 返回的情感分析结果"""
    
    # 尝试提取 JSON (支持嵌套结构)
    # 查找第一个 { 和最后一个 }
    start = response.find('{')
    end = response.rfind('}')
    
    if start != -1 and end != -1 and end > start:
        json_str = response[start : end + 1]
    else:
        # 如果没有找到大括号，尝试直接解析整个字符串
        json_str = response

    try:
        data = json.loads(json_str)
        if not isinstance(data, dict):
            return None
        emotion = str(data.get("emotion", "neutral")).lower()
        if emotion not in EMOTION_RESPONSE_GUIDE:
            emotion = "neutral"

        confidence = float(data.get("confidence", 0.7))
        confidence = max(0.0, min(1.0, confidence))

        intensity = int(data.get("intensity", 3))
        intensity = max(1, min(5, intensity))

        suggested_tone = str(data.get("suggested_tone", ""))
        if not suggested_tone:
            suggested_tone = EMOTION_RESPONSE_GUIDE.get(emotion, "")

        return EmotionResult(
            emotion=emotion,
            confidence=confidence,
            intensity=intensity,
            keywords_matched=[],
            suggested_tone=suggested_tone,
        )
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def get_fact_extraction_prompt(
    user_message: str, assistant_reply: str, existing_facts: List[str]
) -> str:
    """生成用于提取用户事实信息的 prompt"""
    existing_str = "\n".join(f"- {f}" for f in existing_facts) if existing_facts else "（暂无）"
    return f'''分析以下对话，提取用户透露的重要个人信息（如生日、职业、偏好、计划等）。

用户消息："{user_message}"
助手回复："{assistant_reply}"

已知的用户信息：
{existing_str}

请返回 JSON 格式（如果没有新信息则返回空数组）：
{{
  "new_facts": ["事实1", "事实2"],
  "relationship_hint": "friend/close_friend/family/colleague/stranger/null",
  "personality_traits": ["特征1", "特征2"]
}}

只返回 JSON，不要其他文字。如果没有可提取的信息，返回 {{"new_facts": [], "relationship_hint": null, "personality_traits": []}}'''


def parse_fact_extraction_response(
    response: str
) -> Tuple[List[str], Optional[str], List[str]]:
    """解析 AI 返回的事实提取结果"""
    
    json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
    if not json_match:
        return [], None, []

    try:
        data = json.loads(json_match.group())
        new_facts = data.get("new_facts", [])
        if not isinstance(new_facts, list):
            new_facts = []
        new_facts = [str(f).strip() for f in new_facts if str(f).strip()]

        relationship = data.get("relationship_hint")
        if relationship and str(relationship).lower() not in (
            "friend", "close_friend", "family", "colleague", "stranger"
        ):
            relationship = None

        traits = data.get("personality_traits", [])
        if not isinstance(traits, list):
            traits = []
        traits = [str(t).strip() for t in traits if str(t).strip()]

        return new_facts, relationship, traits
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return [], None, []


# ═══════════════════════════════════════════════════════════════════════════════
#                          人性化增强功能
# ═══════════════════════════════════════════════════════════════════════════════

# 时间段定义
TIME_PERIODS = {
    "early_morning": (5, 7),    # 清晨
    "morning": (7, 11),         # 上午
    "noon": (11, 13),           # 中午
    "afternoon": (13, 18),      # 下午
    "evening": (18, 22),        # 晚上
    "night": (22, 24),          # 深夜
    "late_night": (0, 5),       # 凌晨
}

# 时间问候语
TIME_GREETINGS = _EMOTION_CONFIG.get("time_greetings", {})

# 对话风格特征
CONVERSATION_STYLES = _EMOTION_CONFIG.get("conversation_styles", {})


def get_time_period(hour: Optional[int] = None) -> str:
    """获取当前时间段"""
    if hour is None:
        hour = datetime.now().hour
    for period, (start, end) in TIME_PERIODS.items():
        if period == "late_night":
            if 0 <= hour < 5:
                return period
        elif start <= hour < end:
            return period
    return "afternoon"


def get_time_context(hour: Optional[int] = None) -> Dict[str, str]:
    """获取时间相关的上下文信息"""
    now = datetime.now()
    if hour is None:
        hour = now.hour

    period = get_time_period(hour)
    weekday = now.weekday()
    is_weekend = weekday >= 5

    context = {
        "period": period,
        "period_cn": {
            "early_morning": "清晨",
            "morning": "上午",
            "noon": "中午",
            "afternoon": "下午",
            "evening": "晚上",
            "night": "深夜",
            "late_night": "凌晨",
        }.get(period, ""),
        "is_weekend": "是" if is_weekend else "否",
        "weekday_cn": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][weekday],
        "should_rest_hint": period in ("night", "late_night"),
    }
    return context


def get_time_aware_prompt_addition() -> str:
    """生成时间感知的 prompt 附加内容"""
    ctx = get_time_context()
    parts = [f"【当前时间】{ctx['weekday_cn']} {ctx['period_cn']}"]

    if ctx["should_rest_hint"]:
        parts.append("注意：现在较晚，如用户聊天时间长可适当提醒休息")

    if ctx["is_weekend"] == "是":
        parts.append("今天是周末，用户可能较为轻松")

    return "\n".join(parts)


def analyze_conversation_style(messages: List[Dict[str, str]]) -> Dict[str, any]:
    """分析用户的对话风格"""
    if not messages:
        return {"style": "unknown", "avg_length": 0, "emoji_usage": "low"}

    user_messages = [m.get("content", "") for m in messages if m.get("role") == "user"]
    if not user_messages:
        return {"style": "unknown", "avg_length": 0, "emoji_usage": "low"}

    # 计算平均长度
    total_length = sum(len(m) for m in user_messages)
    avg_length = total_length / len(user_messages)

    # 统计风格标记
    casual_count = 0
    formal_count = 0
    emoji_count = 0

    casual_markers = (CONVERSATION_STYLES.get("casual") or {}).get("markers") or []
    formal_markers = (CONVERSATION_STYLES.get("formal") or {}).get("markers") or []
    if not isinstance(casual_markers, (list, tuple)):
        casual_markers = []
    if not isinstance(formal_markers, (list, tuple)):
        formal_markers = []

    for msg in user_messages:
        for marker in casual_markers:
            if marker in msg:
                casual_count += 1
        for marker in formal_markers:
            if marker in msg:
                formal_count += 1
        emoji_count += len(_EMOJI_PATTERN.findall(msg))

    # 判断风格
    style = "balanced"
    if casual_count > formal_count * 2:
        style = "casual"
    elif formal_count > casual_count * 2:
        style = "formal"

    length_style = "medium"
    if avg_length < 20:
        length_style = "brief"
    elif avg_length > 40:
        length_style = "detailed"

    emoji_usage = "low"
    emoji_ratio = emoji_count / len(user_messages) if user_messages else 0
    if emoji_ratio > 0.5:
        emoji_usage = "high"
    elif emoji_ratio > 0.2:
        emoji_usage = "medium"

    return {
        "style": style,
        "length_style": length_style,
        "avg_length": round(avg_length, 1),
        "emoji_usage": emoji_usage,
        "casual_markers": casual_count,
        "formal_markers": formal_count,
    }


def get_style_adaptation_hint(style_info: Dict) -> str:
    """根据用户风格生成适应建议"""
    hints = []

    style = style_info.get("style", "balanced")
    if style == "casual":
        hints.append("用户风格随意，可使用轻松语气、适当加入语气词")
    elif style == "formal":
        hints.append("用户风格正式，保持礼貌用语")

    length_style = style_info.get("length_style", "medium")
    if length_style == "brief":
        hints.append("用户习惯简短表达，回复也宜简洁")
    elif length_style == "detailed":
        hints.append("用户表达详细，可提供更完整的回应")

    emoji_usage = style_info.get("emoji_usage", "low")
    if emoji_usage == "high":
        hints.append("用户常用表情，可适当使用表情回应")

    return "；".join(hints) if hints else ""


def analyze_emotion_trend(emotion_history: List[Dict]) -> Dict[str, any]:
    """分析用户情绪趋势"""
    if not emotion_history or len(emotion_history) < 2:
        return {"trend": "stable", "dominant": "neutral", "variance": "low"}

    emotions = [e.get("emotion", "neutral") for e in emotion_history]
    recent = emotions[-3:] if len(emotions) >= 3 else emotions

    # 统计情绪分布
    emotion_counts: Dict[str, int] = {}
    for e in emotions:
        emotion_counts[e] = emotion_counts.get(e, 0) + 1

    dominant = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "neutral"

    # 判断趋势
    positive = {"happy", "excited"}
    negative = {"sad", "angry", "anxious", "tired"}

    recent_positive = sum(1 for e in recent if e in positive)
    recent_negative = sum(1 for e in recent if e in negative)

    if recent_negative > recent_positive:
        trend = "declining"
    elif recent_positive > recent_negative:
        trend = "improving"
    else:
        trend = "stable"

    # 判断波动
    unique_recent = len(set(recent))
    variance = "high" if unique_recent >= 3 else ("medium" if unique_recent == 2 else "low")

    return {
        "trend": trend,
        "dominant": dominant,
        "variance": variance,
        "recent_emotions": recent,
    }


def get_emotion_trend_hint(trend_info: Dict) -> str:
    """根据情绪趋势生成建议"""
    trend = trend_info.get("trend", "stable")
    dominant = trend_info.get("dominant", "neutral")
    variance = trend_info.get("variance", "low")

    hints = []

    if trend == "declining":
        hints.append("用户近期情绪有下降趋势，多给予关心和正面回应")
    elif trend == "improving":
        hints.append("用户情绪在好转，可以配合积极的氛围")

    if variance == "high":
        hints.append("用户情绪波动较大，回应时注意察言观色")

    if dominant in ("sad", "anxious"):
        hints.append(f"用户近期多为{dominant}情绪，注意温和关怀")

    return "；".join(hints) if hints else ""


def get_relationship_evolution_hint(
    message_count: int, current_relationship: str
) -> Optional[str]:
    """根据互动次数建议关系升级"""
    if current_relationship == "unknown":
        if message_count >= 5:
            return "stranger"  # 互动几次后至少是陌生人
    elif current_relationship == "stranger":
        if message_count >= 30:
            return "friend"  # 互动30次后可能是朋友
    elif current_relationship == "friend":
        if message_count >= 100:
            return "close_friend"  # 互动100次后可能是好友

    return None  # 不需要更新

