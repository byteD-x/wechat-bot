"""
消息处理工具模块 - 提供消息解析、清洗、分段和 emoji 处理等功能。
"""

import re
import logging
from typing import Optional, Tuple, Any, List, Dict

# 预编译的消息类型标记集合
NON_TEXT_TYPE_MARKERS = frozenset((
    "voice", "audio", "video", "file", "gif",
    "emoji", "system", "location", "link", "merge", "card", "note", "tickle",
))
VOICE_TYPE_MARKERS: frozenset = frozenset(("voice", "audio"))

DEFAULT_SUFFIX = "\n（由AI回复，模型使用{alias}）"
EMOJI_PLACEHOLDER = "[表情]"
VOICE_PLACEHOLDER = "[语音]"
STREAM_PUNCTUATION: frozenset = frozenset("。！？.!?；;\n")

# 自然分段的分隔符优先级（从高到低）
NATURAL_SPLIT_PRIORITY = [
    "\n\n",     # 段落分隔
    "\n",       # 换行
    "。",       # 中文句号
    "！",       # 中文感叹号
    "？",       # 中文问号
    ".",        # 英文句号
    "!",        # 英文感叹号
    "?",        # 英文问号
    "；",       # 中文分号
    ";",        # 英文分号
    "，",       # 中文逗号（低优先级）
    ",",        # 英文逗号（低优先级）
]

# emoji 到微信表情的映射
EMOJI_REPLACEMENTS = {
    # 笑脸类
    "\U0001F602": "[笑哭]",
    "\U0001F923": "[笑哭]",
    "\U0001F60A": "[微笑]",
    "\U0001F604": "[笑]",
    "\U0001F601": "[呲牙]",
    "\U0001F606": "[大笑]",
    "\U0001F605": "[尴尬]",
    "\U0001F609": "[眨眼]",
    "\U0001F60E": "[酷]",
    "\U0001F60D": "[色]",
    "\U0001F618": "[飞吻]",
    "\U0001F617": "[亲亲]",
    "\U0001F619": "[亲亲]",
    "\U0001F61A": "[亲亲]",
    "\U0001F642": "[微笑]",
    "\U0001F643": "[微笑]",
    "\U0001F970": "[爱心]",
    "\U0001F60B": "[馋]",
    "\U0001F61B": "[吐舌]",
    "\U0001F61C": "[坏笑]",
    "\U0001F61D": "[吐舌]",
    "\U0001F911": "[财迷]",
    "\U0001F917": "[拥抱]",
    "\U0001F929": "[惊喜]",
    "\U0001F973": "[派对]",
    # 悲伤类
    "\U0001F62D": "[大哭]",
    "\U0001F622": "[流泪]",
    "\U0001F62A": "[困]",
    "\U0001F630": "[冷汗]",
    "\U0001F625": "[难过]",
    "\U0001F613": "[汗]",
    "\U0001F61E": "[失望]",
    "\U0001F629": "[疲惫]",
    "\U0001F62B": "[累]",
    # 愤怒/惊讶类
    "\U0001F620": "[发怒]",
    "\U0001F621": "[发怒]",
    "\U0001F624": "[哼]",
    "\U0001F92C": "[爆炸]",
    "\U0001F631": "[惊恐]",
    "\U0001F632": "[惊讶]",
    "\U0001F633": "[脸红]",
    "\U0001F628": "[害怕]",
    "\U0001F627": "[担心]",
    "\U0001F626": "[难过]",
    # 表情类
    "\U0001F914": "[疑问]",
    "\U0001F644": "[白眼]",
    "\U0001F612": "[鄙视]",
    "\U0001F610": "[无语]",
    "\U0001F611": "[无语]",
    "\U0001F636": "[沉默]",
    "\U0001F60F": "[坏笑]",
    "\U0001F4A4": "[睡]",
    "\U0001F634": "[睡]",
    "\U0001F637": "[口罩]",
    "\U0001F912": "[生病]",
    "\U0001F915": "[受伤]",
    # 手势类
    "\U0001F44D": "[强]",
    "\U0001F44E": "[弱]",
    "\U0001F64F": "[合十]",
    "\U0001F4AA": "[拳头]",
    "\U0001F44F": "[鼓掌]",
    "\U0001F44B": "[挥手]",
    "\U0001F44C": "[OK]",
    "\U0001F44A": "[拳头]",
    "\U0001F91D": "[握手]",
    "\U0001F91E": "[祝福]",
    "\U0001F918": "[摇滚]",
    "\U0001F919": "[电话]",
    "\U0001F91F": "[爱你]",
    "\u270C\uFE0F": "[胜利]",
    "\U0001F596": "[举手]",
    # 其他常用
    "\U0001F525": "[火]",
    "\U0001F4A5": "[爆炸]",
    "\U0001F4AF": "[100]",
    "\U00002764": "[爱心]",
    "\U0001F495": "[心心]",
    "\U0001F494": "[心碎]",
    "\U0001F496": "[爱心]",
    "\U0001F497": "[爱心]",
    "\U0001F498": "[爱心]",
    "\U0001F499": "[爱心]",
    "\U0001F49A": "[爱心]",
    "\U0001F49B": "[爱心]",
    "\U0001F49C": "[爱心]",
    "\U0001F31F": "[星星]",
    "\U00002B50": "[星星]",
    "\U0001F389": "[庆祝]",
    "\U0001F38A": "[礼花]",
    "\U0001F4A9": "[便便]",
    "\U0001F47B": "[鬼]",
    "\U0001F480": "[骷髅]",
    "\U0001F47F": "[恶魔]",
    "\U0001F63A": "[猫笑]",
    "\U0001F63B": "[猫爱]",
    "\U0001F63F": "[猫哭]",
}

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "]"
)

HUMANIZE_PATTERNS = [
    re.compile(r"^作为(一个|一名)?(ai|人工智能|智能助手|助手|语言模型)[^。！？\n]*[。！？]?", re.I),
    re.compile(r"(?:我是|身为|作为)(ai|人工智能|智能助手|助手|语言模型)[^。！？\n]*[。！？]?", re.I),
    re.compile(r"(希望|很高兴).{0,10}(能|可以).{0,6}(帮到|帮助).{0,6}(你|您)[^。！？\n]*[。！？]?", re.I),
    re.compile(r"(如果|如有).{0,10}(疑问|问题|需要).{0,12}(随时|欢迎|可以).{0,10}(提问|问我|联系我|告诉我)[^。！？\n]*[。！？]?", re.I),
    re.compile(r"(如需|需要).{0,8}(更多|进一步).{0,6}(帮助|支持)[^。！？\n]*[。！？]?", re.I),
]


__all__ = [
    "NON_TEXT_TYPE_MARKERS",
    "VOICE_TYPE_MARKERS",
    "DEFAULT_SUFFIX",
    "EMOJI_PLACEHOLDER",
    "VOICE_PLACEHOLDER",
    "STREAM_PUNCTUATION",
    "EMOJI_REPLACEMENTS",
    "EMOJI_PATTERN",
    "split_group_message",
    "is_text_message",
    "is_voice_message",
    "parse_voice_to_text_result",
    "is_at_me",
    "strip_at_text",
    "build_reply_suffix",
    "refine_reply_text",
    "sanitize_reply_text",
    "split_reply_chunks",
    "split_reply_naturally",
]


def split_group_message(text: str) -> Tuple[Optional[str], str]:
    """
    分离群消息中的发送者昵称和内容。
    
    wxauto 在 Windows 端获取的群消息通常格式为 "昵称: 内容" 或 "昵称：\n内容"。
    """
    # 常见群聊格式是“发送者:\\n消息”或“发送者: 消息”。
    for sep in (":\n", "：\n", ": ", "： "):
        if sep in text:
            head, tail = text.split(sep, 1)
            if head.strip() and tail.strip():
                return head.strip(), tail.strip()
    return None, text


def is_text_message(msg_type: Optional[str], content: str) -> bool:
    """判断是否为文本消息（包括图片，因为我们会处理）"""
    if not content or not isinstance(content, str):
        return False
    if msg_type is None:
        return True
    
    t = str(msg_type).lower()
    
    # 图片被视为文本消息的一种（为了通过过滤器）
    if "image" in t or "pic" in t:
        return True

    for marker in NON_TEXT_TYPE_MARKERS:
        if marker in t:
            # 语音也是特殊情况，需要转录
            if marker in ("voice", "audio"):
                return False  # converters.py 会单独处理语音
            return False
            
    return True


def is_image_message(msg_type: Optional[str]) -> bool:
    """判断是否为图片消息"""
    if msg_type is None:
        return False
    t = str(msg_type).lower()
    return "image" in t or "pic" in t


def is_voice_message(msg_type: Optional[str]) -> bool:
    """判断是否为语音消息。"""
    if msg_type is None:
        return False
    text_type = str(msg_type).lower()
    return any(marker in text_type for marker in VOICE_TYPE_MARKERS)


def parse_voice_to_text_result(result: Any) -> Tuple[Optional[str], Optional[str]]:
    """解析语音转文字结果，返回 (文本, 错误信息)。"""
    if result is None:
        return None, "empty"
    if isinstance(result, dict):
        text = result.get("text") or result.get("content") or ""
        if not text and isinstance(result.get("data"), dict):
            text = result["data"].get("text") or result["data"].get("content") or ""
        text = str(text).strip() if text else ""
        if text:
            return text, None

        error = result.get("error")
        if isinstance(error, dict):
            error = error.get("message") or error.get("error") or ""

        message = error or result.get("message") or ""
        message = str(message).strip() if message else ""
        return None, message or "unknown"
    text = str(result).strip()
    if not text:
        return None, "empty"
    return text, None


def is_at_me(text: str, self_name: str) -> bool:
    """判断消息是否包含 @自己。"""
    if not self_name:
        return False
    markers = [f"@{self_name}\u2005", f"@{self_name} ", f"@{self_name}"]
    return any(marker in text for marker in markers)


def strip_at_text(text: str, self_name: str) -> str:
    """移除消息开头的 @自己 部分。"""
    if not self_name:
        return text
    markers = [f"@{self_name}\u2005", f"@{self_name} ", f"@{self_name}"]
    for marker in markers:
        if text.startswith(marker):
            return text[len(marker) :].strip()
    return text


def build_reply_suffix(template: str, model: str, alias: str) -> str:
    """构建回复后缀（小尾巴）。"""
    try:
        return template.format(model=model, alias=alias)
    except Exception:
        logging.warning("reply_suffix 模板错误，已回退默认值。")
        return DEFAULT_SUFFIX.format(alias=alias or model, model=model)


def refine_reply_text(text: str) -> str:
    if not text:
        return text
    original = text
    result = text.strip()
    for pattern in HUMANIZE_PATTERNS:
        result = pattern.sub("", result).strip()
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result if result else original


def sanitize_reply_text(
    text: str, policy: str, replacements: Optional[Dict[str, str]] = None
) -> str:
    """
    根据策略清理或替换回复文本中的 emoji。
    
    策略：
    - keep/raw: 不处理
    - strip/remove: 移除所有 emoji
    - mixed/wechat_mixed: 将标准 emoji 转换为 [微笑] 等文本格式，保留未匹配的
    - wechat: 将标准 emoji 转换，未匹配的替换为 [表情]
    """
    if not text:
        return text
    mode = (policy or "").strip().lower()
    if mode in ("keep", "raw", "none"):
        return text

    if mode in ("strip", "remove"):
        text = text.replace("\uFE0F", "").replace("\uFE0E", "").replace("\u200D", "")
        return EMOJI_PATTERN.sub("", text)

    emoji_map = dict(EMOJI_REPLACEMENTS)
    custom_replacements: Dict[str, str] = {}
    if isinstance(replacements, dict):
        for key, value in replacements.items():
            if isinstance(key, str) and isinstance(value, str) and key:
                emoji_map[key] = value
                custom_replacements[key] = value

    if custom_replacements:
        for key in sorted(custom_replacements, key=len, reverse=True):
            text = text.replace(key, custom_replacements[key])

    if mode in ("mixed", "wechat_mixed", "wechat-keep"):
        text = text.replace("\uFE0F", "").replace("\uFE0E", "").replace("\u200D", "")

        def repl_mixed(match: re.Match) -> str:
            ch = match.group(0)
            return emoji_map.get(ch, ch)

        return EMOJI_PATTERN.sub(repl_mixed, text)

    text = text.replace("\uFE0F", "").replace("\uFE0E", "").replace("\u200D", "")

    def repl_wechat(match: re.Match) -> str:
        ch = match.group(0)
        return emoji_map.get(ch, EMOJI_PLACEHOLDER)

    return EMOJI_PATTERN.sub(repl_wechat, text)


def split_reply_chunks(text: str, max_len: int) -> List[str]:
    """
    将长回复按长度和标点符号切分为多段。
    
    优先在标点符号处切分，避免截断句子。
    """
    if not text:
        return []
    if max_len <= 0 or len(text) <= max_len:
        if not text.strip():
            return []
        return [text.rstrip()]
    chunks: List[str] = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(text_len, start + max_len)
        split_at = None
        for idx in range(end - 1, start, -1):
            if text[idx] in STREAM_PUNCTUATION:
                split_at = idx + 1
                break
        if split_at is None or split_at <= start:
            split_at = end
        chunk = text[start:split_at].rstrip()
        if chunk.strip():
            chunks.append(chunk)
        start = split_at
    return chunks


def split_reply_naturally(
    text: str,
    min_chars: int = 30,
    max_chars: int = 150,
    max_segments: int = 5,
) -> List[str]:
    """
    自然分段算法。
    
    模拟人类的聊天发送习惯，根据标点符号权重和长度动态分段。
    """
    if not text or not text.strip():
        return []
    
    text = text.strip()
    
    # 如果文本较短，不分段
    if len(text) <= min_chars * 1.5:
        return [text]
    
    segments: List[str] = []
    remaining = text
    
    while remaining and len(segments) < max_segments:
        remaining = remaining.strip()
        if not remaining:
            break
            
        # 如果剩余内容较短，直接作为最后一段
        if len(remaining) <= max_chars:
            segments.append(remaining)
            break
        
        # 寻找最佳分割点
        best_split = None
        best_priority = len(NATURAL_SPLIT_PRIORITY)
        
        # 在 min_chars 到 max_chars 范围内寻找分隔符
        search_start = min_chars
        search_end = min(len(remaining), max_chars)
        
        for priority, delimiter in enumerate(NATURAL_SPLIT_PRIORITY):
            # 从后往前搜索，优先选择靠近 max_chars 的位置
            for pos in range(search_end - 1, search_start - 1, -1):
                if remaining[pos:pos + len(delimiter)] == delimiter:
                    if priority < best_priority or (priority == best_priority and best_split and pos > best_split):
                        best_split = pos + len(delimiter)
                        best_priority = priority
                        break
            
            if best_split is not None and priority < 6:
                break
        
        if best_split is None:
            best_split = max_chars
        
        segment = remaining[:best_split].strip()
        if segment:
            segments.append(segment)
        remaining = remaining[best_split:]
    
    remaining = remaining.strip()
    if remaining:
        if segments:
            segments[-1] = f"{segments[-1]}\n{remaining}"
        else:
            segments.append(remaining)
    
    return segments
