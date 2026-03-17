from typing import List, Dict, Optional, Any, Tuple
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime

class EmotionResult(BaseModel):
    """情感检测结果"""
    emotion: str
    confidence: float = Field(ge=0.0, le=1.0)
    intensity: int = Field(ge=1, le=5)
    keywords_matched: Tuple[str, ...] = Field(default_factory=tuple)
    suggested_tone: str = ""

    model_config = ConfigDict(frozen=True)

class UserProfile(BaseModel):
    """用户画像"""
    wx_id: str
    nickname: str = ""
    relationship: str = "unknown"
    personality: str = ""
    preferences: Dict[str, Any] = Field(default_factory=dict)
    context_facts: List[str] = Field(default_factory=list)
    last_emotion: str = "neutral"
    emotion_history: List[Dict[str, Any]] = Field(default_factory=list)
    profile_summary: str = ""
    contact_prompt: str = ""
    contact_prompt_updated_at: int = 0
    contact_prompt_source: str = ""
    contact_prompt_last_message_count: int = 0
    message_count: int = 0
    updated_at: int = 0

    # 允许通过下标访问以兼容旧代码
    def __getitem__(self, item):
        return getattr(self, item)

    def get(self, item, default=None):
        return getattr(self, item, default)

class MessageEvent(BaseModel):
    """消息事件"""
    type: str # message type
    content: str
    sender: str
    chat_name: str
    is_group: bool
    msg_type: int
    timestamp: float
    raw_item: Optional[Any] = None
    image_path: Optional[str] = None # 图片路径

    model_config = ConfigDict(arbitrary_types_allowed=True)
