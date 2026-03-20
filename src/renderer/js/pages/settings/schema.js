export const FIELD_DEFS = [
    ['setting-self-name', 'bot', 'self_name', 'text'],
    ['setting-reply-suffix', 'bot', 'reply_suffix', 'text'],
    ['setting-group-at-only', 'bot', 'group_reply_only_when_at', 'checkbox'],
    ['setting-system-prompt-editable', 'bot', 'system_prompt', 'text'],
    ['setting-emoji-policy', 'bot', 'emoji_policy', 'text'],
    ['setting-voice-to-text', 'bot', 'voice_to_text', 'checkbox'],
    ['setting-voice-to-text-fail-reply', 'bot', 'voice_to_text_fail_reply', 'text'],
    ['setting-memory-db-path', 'bot', 'memory_db_path', 'text'],
    ['setting-memory-context-limit', 'bot', 'memory_context_limit', 'number'],
    ['setting-memory-ttl-sec', 'bot', 'memory_ttl_sec', 'number', { nullable: true }],
    ['setting-memory-cleanup-interval-sec', 'bot', 'memory_cleanup_interval_sec', 'number'],
    ['setting-context-rounds', 'bot', 'context_rounds', 'number'],
    ['setting-context-max-tokens', 'bot', 'context_max_tokens', 'number'],
    ['setting-history-max-chats', 'bot', 'history_max_chats', 'number'],
    ['setting-history-ttl-sec', 'bot', 'history_ttl_sec', 'number', { nullable: true }],
    ['setting-poll-interval-min-sec', 'bot', 'poll_interval_min_sec', 'number'],
    ['setting-poll-interval-max-sec', 'bot', 'poll_interval_max_sec', 'number'],
    ['setting-poll-interval-backoff-factor', 'bot', 'poll_interval_backoff_factor', 'number'],
    ['setting-min-reply-interval-sec', 'bot', 'min_reply_interval_sec', 'number'],
    ['setting-merge-user-messages-sec', 'bot', 'merge_user_messages_sec', 'number'],
    ['setting-merge-user-messages-max-wait-sec', 'bot', 'merge_user_messages_max_wait_sec', 'number'],
    ['setting-reply-chunk-size', 'bot', 'reply_chunk_size', 'number'],
    ['setting-reply-chunk-delay-sec', 'bot', 'reply_chunk_delay_sec', 'number'],
    ['setting-reply-deadline-sec', 'bot', 'reply_deadline_sec', 'number'],
    ['setting-max-concurrency', 'bot', 'max_concurrency', 'number'],
    ['setting-natural-split-enabled', 'bot', 'natural_split_enabled', 'checkbox'],
    ['setting-natural-split-min-chars', 'bot', 'natural_split_min_chars', 'number'],
    ['setting-natural-split-max-chars', 'bot', 'natural_split_max_chars', 'number'],
    ['setting-natural-split-max-segments', 'bot', 'natural_split_max_segments', 'number'],
    ['setting-required-wechat-version', 'bot', 'required_wechat_version', 'text'],
    ['setting-silent-mode-required', 'bot', 'silent_mode_required', 'checkbox'],
    ['setting-config-reload-sec', 'bot', 'config_reload_sec', 'number'],
    ['setting-reload-ai-client-on-change', 'bot', 'reload_ai_client_on_change', 'checkbox'],
    ['setting-reload-ai-client-module', 'bot', 'reload_ai_client_module', 'checkbox'],
    ['setting-keepalive-idle-sec', 'bot', 'keepalive_idle_sec', 'number'],
    ['setting-reconnect-max-retries', 'bot', 'reconnect_max_retries', 'number'],
    ['setting-reconnect-backoff-sec', 'bot', 'reconnect_backoff_sec', 'number'],
    ['setting-reconnect-max-delay-sec', 'bot', 'reconnect_max_delay_sec', 'number'],
    ['setting-group-include-sender', 'bot', 'group_include_sender', 'checkbox'],
    ['setting-send-exact-match', 'bot', 'send_exact_match', 'checkbox'],
    ['setting-send-fallback-current-chat', 'bot', 'send_fallback_current_chat', 'checkbox'],
    ['setting-filter-mute', 'bot', 'filter_mute', 'checkbox'],
    ['setting-ignore-official', 'bot', 'ignore_official', 'checkbox'],
    ['setting-ignore-service', 'bot', 'ignore_service', 'checkbox'],
    ['setting-allow-filehelper-self-message', 'bot', 'allow_filehelper_self_message', 'checkbox'],
    ['setting-personalization-enabled', 'bot', 'personalization_enabled', 'checkbox'],
    ['setting-profile-update-frequency', 'bot', 'profile_update_frequency', 'number'],
    ['setting-contact-prompt-update-frequency', 'bot', 'contact_prompt_update_frequency', 'number'],
    ['setting-remember-facts-enabled', 'bot', 'remember_facts_enabled', 'checkbox'],
    ['setting-max-context-facts', 'bot', 'max_context_facts', 'number'],
    ['setting-profile-inject-in-prompt', 'bot', 'profile_inject_in_prompt', 'checkbox'],
    ['setting-vector-memory-enabled', 'bot', 'rag_enabled', 'checkbox'],
    ['setting-vector-memory-embedding-model', 'bot', 'vector_memory_embedding_model', 'text'],
    ['setting-export-rag-enabled', 'bot', 'export_rag_enabled', 'checkbox'],
    ['setting-export-rag-auto-ingest', 'bot', 'export_rag_auto_ingest', 'checkbox'],
    ['setting-export-rag-dir', 'bot', 'export_rag_dir', 'text'],
    ['setting-export-rag-top-k', 'bot', 'export_rag_top_k', 'number'],
    ['setting-export-rag-max-chunks-per-chat', 'bot', 'export_rag_max_chunks_per_chat', 'number'],
    ['setting-control-commands-enabled', 'bot', 'control_commands_enabled', 'checkbox'],
    ['setting-control-command-prefix', 'bot', 'control_command_prefix', 'text'],
    ['setting-control-reply-visible', 'bot', 'control_reply_visible', 'checkbox'],
    ['setting-quiet-hours-enabled', 'bot', 'quiet_hours_enabled', 'checkbox'],
    ['setting-quiet-hours-start', 'bot', 'quiet_hours_start', 'text'],
    ['setting-quiet-hours-end', 'bot', 'quiet_hours_end', 'text'],
    ['setting-quiet-hours-reply', 'bot', 'quiet_hours_reply', 'text'],
    ['setting-usage-tracking-enabled', 'bot', 'usage_tracking_enabled', 'checkbox'],
    ['setting-daily-token-limit', 'bot', 'daily_token_limit', 'number'],
    ['setting-token-warning-threshold', 'bot', 'token_warning_threshold', 'number'],
    ['setting-emotion-detection-enabled', 'bot', 'emotion_detection_enabled', 'checkbox'],
    ['setting-emotion-detection-mode', 'bot', 'emotion_detection_mode', 'text'],
    ['setting-emotion-inject-in-prompt', 'bot', 'emotion_inject_in_prompt', 'checkbox'],
    ['setting-emotion-log-enabled', 'bot', 'emotion_log_enabled', 'checkbox'],
    ['setting-whitelist-enabled', 'bot', 'whitelist_enabled', 'checkbox'],
    ['setting-agent-enabled', 'agent', 'enabled', 'checkbox'],
    ['setting-agent-graph-mode', 'agent', 'graph_mode', 'text'],
    ['setting-agent-retriever-top-k', 'agent', 'retriever_top_k', 'number'],
    ['setting-agent-retriever-threshold', 'agent', 'retriever_score_threshold', 'number'],
    ['setting-agent-embedding-cache-ttl', 'agent', 'embedding_cache_ttl_sec', 'number'],
    ['setting-agent-max-parallel-retrievers', 'agent', 'max_parallel_retrievers', 'number'],
    ['setting-agent-background-facts', 'agent', 'background_fact_extraction_enabled', 'checkbox'],
    ['setting-agent-emotion-fast-path', 'agent', 'emotion_fast_path_enabled', 'checkbox'],
    ['setting-agent-langsmith-enabled', 'agent', 'langsmith_enabled', 'checkbox'],
    ['setting-agent-langsmith-project', 'agent', 'langsmith_project', 'text'],
    ['setting-agent-langsmith-endpoint', 'agent', 'langsmith_endpoint', 'text', { nullable: true }],
    ['setting-log-level', 'logging', 'level', 'text'],
    ['setting-log-format', 'logging', 'format', 'text'],
    ['setting-log-file', 'logging', 'file', 'text'],
    ['setting-log-max-bytes', 'logging', 'max_bytes', 'number'],
    ['setting-log-backup-count', 'logging', 'backup_count', 'number'],
    ['setting-log-message-content', 'logging', 'log_message_content', 'checkbox'],
    ['setting-log-reply-content', 'logging', 'log_reply_content', 'checkbox'],
];

export const LIST_FIELD_DEFS = [
    ['setting-ignore-names', 'bot', 'ignore_names'],
    ['setting-ignore-keywords', 'bot', 'ignore_keywords'],
    ['setting-control-allowed-users', 'bot', 'control_allowed_users'],
    ['setting-whitelist', 'bot', 'whitelist'],
];

export const MAP_FIELD_DEFS = [
    ['setting-system-prompt-overrides', 'bot', 'system_prompt_overrides', '|'],
    ['setting-emoji-replacements', 'bot', 'emoji_replacements', '='],
];

export const RANGE_FIELD_DEFS = [
    ['setting-random-delay-min-sec', 'setting-random-delay-max-sec', 'bot', 'random_delay_range_sec'],
    ['setting-natural-split-delay-min-sec', 'setting-natural-split-delay-max-sec', 'bot', 'natural_split_delay_sec'],
];

export const FIELD_META_BY_ID = new Map();

FIELD_DEFS.forEach(([id, section, path, type, options = {}]) => {
    FIELD_META_BY_ID.set(id, { id, section, path, type, options, kind: 'field' });
});

LIST_FIELD_DEFS.forEach(([id, section, path]) => {
    FIELD_META_BY_ID.set(id, { id, section, path, kind: 'list' });
});

MAP_FIELD_DEFS.forEach(([id, section, path, separator]) => {
    FIELD_META_BY_ID.set(id, { id, section, path, separator, kind: 'map' });
});

RANGE_FIELD_DEFS.forEach(([minId, maxId, section, path]) => {
    FIELD_META_BY_ID.set(minId, { id: minId, pairId: maxId, section, path, kind: 'range' });
    FIELD_META_BY_ID.set(maxId, { id: maxId, pairId: minId, section, path, kind: 'range' });
});
