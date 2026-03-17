from typing import List, Dict, Optional, Any, Union, Literal
from pydantic import BaseModel, Field, field_validator
from backend.wechat_versions import OFFICIAL_SUPPORTED_WECHAT_VERSION

class PresetConfig(BaseModel):
    name: str
    provider_id: Optional[str] = None
    alias: str
    base_url: str
    api_key: str
    model: str
    timeout_sec: int = 10
    max_retries: int = 2
    temperature: float = 0.6
    max_tokens: int = 512
    max_completion_tokens: Optional[int] = None
    reasoning_effort: Optional[str] = None
    embedding_model: Optional[str] = None  # 新增
    allow_empty_key: bool = False

class ApiConfig(BaseModel):
    base_url: str = 'https://api.openai.com/v1'
    api_key: str = "YOUR_API_KEY"
    model: str = 'gpt-5-mini'
    embedding_model: Optional[str] = None  # 新增
    alias: str = '小欧'
    timeout_sec: int = 8
    max_retries: int = 1
    temperature: float = 0.6
    max_tokens: int = 512
    max_completion_tokens: Optional[int] = None
    reasoning_effort: Optional[str] = None
    allow_empty_key: bool = False
    active_preset: str = 'Doubao'
    presets: List[PresetConfig] = Field(default_factory=list)

class BotConfig(BaseModel):
    # Identity
    self_name: str = '知有'
    system_prompt: str = ""
    system_prompt_overrides: Dict[str, str] = Field(default_factory=dict)
    
    # Reply format
    reply_suffix: str = "\n （🤖💬 AI代言中～）"
    emoji_policy: Literal['wechat', 'strip', 'keep', 'mixed'] = 'mixed'
    emoji_replacements: Dict[str, str] = Field(default_factory=dict)
    
    # Transport
    transport_backend: Literal['hook_wcferry'] = 'hook_wcferry'
    silent_mode_required: bool = False
    required_wechat_version: str = OFFICIAL_SUPPORTED_WECHAT_VERSION
    # Voice
    voice_to_text: bool = True
    voice_to_text_fail_reply: str = ""
    voice_transcription_model: str = "gpt-4o-mini-transcribe"
    voice_transcription_timeout_sec: float = 30.0
    
    # Memory
    memory_db_path: str = "data/chat_memory.db"
    memory_context_limit: int = 12
    memory_ttl_sec: Optional[float] = None
    memory_cleanup_interval_sec: float = 0.0
    # Context
    context_rounds: int = 4
    context_max_tokens: int = 1200
    history_max_chats: int = 120
    history_ttl_sec: Optional[float] = None
    
    # Polling & Delay
    poll_interval_min_sec: float = 0.05
    poll_interval_max_sec: float = 1.0
    poll_interval_backoff_factor: float = 1.2
    min_reply_interval_sec: float = 0.1
    random_delay_range_sec: List[float] = Field(default_factory=lambda: [0.1, 0.3])

    # Merging
    merge_user_messages_sec: float = 0.0
    merge_user_messages_max_wait_sec: float = 0.0

    # Reply sending
    reply_chunk_size: int = 500
    reply_chunk_delay_sec: float = 0.0

    # Natural split
    natural_split_enabled: bool = False
    natural_split_min_chars: int = 30
    natural_split_max_chars: int = 120
    natural_split_max_segments: int = 3
    natural_split_delay_sec: List[float] = Field(default_factory=lambda: [0.3, 0.8])
    reply_deadline_sec: float = Field(default=0.0, ge=0.0)
    
    # Concurrency
    max_concurrency: int = 5
    keepalive_idle_sec: float = 0.0
    
    # Filtering
    filter_mute: bool = False
    ignore_official: bool = True
    ignore_service: bool = True
    allow_filehelper_self_message: bool = True
    ignore_names: List[str] = Field(default_factory=list)
    ignore_keywords: List[str] = Field(default_factory=list)

    # Whitelist
    whitelist_enabled: bool = False
    whitelist: List[str] = Field(default_factory=list)
    
    # Other
    reload_ai_client_on_change: bool = True
    config_reload_sec: float = 2.0
    config_reload_mode: Literal['auto', 'polling', 'watchdog'] = 'auto'
    config_reload_debounce_ms: int = 500
    reload_ai_client_module: bool = False
    keepalive_idle_sec: float = 0.0
    reconnect_max_retries: int = 3
    reconnect_backoff_sec: float = 2.0
    reconnect_max_delay_sec: float = 20.0

    # Group control
    group_reply_only_when_at: bool = False
    group_include_sender: bool = True

    # Send control
    send_exact_match: bool = True
    send_fallback_current_chat: bool = False

    # Personalization
    personalization_enabled: bool = True
    profile_update_frequency: int = 10
    contact_prompt_update_frequency: int = 10
    remember_facts_enabled: bool = True
    max_context_facts: int = 20
    profile_inject_in_prompt: bool = True
    rag_enabled: bool = False
    export_rag_enabled: bool = True
    export_rag_dir: str = "data/chat_exports/聊天记录"
    export_rag_auto_ingest: bool = True
    export_rag_max_chunks_per_chat: int = 500
    export_rag_chunk_messages: int = 6
    export_rag_top_k: int = 3
    export_rag_min_score: float = 1.0
    export_rag_max_context_chars: int = 900
    export_rag_prefer_recent: bool = True

    # Control commands
    control_commands_enabled: bool = True
    control_command_prefix: str = "/"
    control_allowed_users: List[str] = Field(default_factory=list)
    control_reply_visible: bool = True

    # Quiet hours
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "07:00"
    quiet_hours_reply: str = ""

    # Usage tracking
    usage_tracking_enabled: bool = True
    daily_token_limit: int = 0
    token_warning_threshold: float = 0.8

    # Emotion
    emotion_detection_enabled: bool = True
    emotion_detection_mode: str = "ai"
    emotion_inject_in_prompt: bool = True
    emotion_log_enabled: bool = True

    @field_validator("transport_backend", mode="before")
    @classmethod
    def _normalize_transport_backend(cls, value):
        backend = str(value or "hook_wcferry").strip().lower()
        if backend == "compat_ui":
            return "hook_wcferry"
        return "hook_wcferry" if not backend else backend

class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "data/logs/bot.log"
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 5
    format: Literal['text', 'json'] = 'text'
    log_message_content: bool = False
    log_reply_content: bool = False

class AgentConfig(BaseModel):
    enabled: bool = True
    graph_mode: str = "state_graph"
    langsmith_enabled: bool = False
    langsmith_project: str = "wechat-chat"
    langsmith_endpoint: Optional[str] = None
    langsmith_api_key: Optional[str] = None
    retriever_top_k: int = 3
    retriever_score_threshold: float = 1.0
    retriever_rerank_mode: Literal['auto', 'lightweight', 'cross_encoder'] = 'lightweight'
    retriever_cross_encoder_model: Optional[str] = None
    retriever_cross_encoder_device: Optional[str] = None
    embedding_cache_ttl_sec: float = 300.0
    background_fact_extraction_enabled: bool = True
    emotion_fast_path_enabled: bool = True
    max_parallel_retrievers: int = 3

class AppConfig(BaseModel):
    api: ApiConfig
    bot: BotConfig
    logging: LoggingConfig
    agent: AgentConfig = Field(default_factory=AgentConfig)
