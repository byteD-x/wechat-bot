from __future__ import annotations

from enum import Enum


class AuthMethodType(str, Enum):
    API_KEY = "api_key"
    OAUTH = "oauth"
    LOCAL_IMPORT = "local_import"
    WEB_SESSION = "web_session"


class CredentialSource(str, Enum):
    MANUAL_INPUT = "manual_input"
    OAUTH_CALLBACK = "oauth_callback"
    LOCAL_CLI = "local_cli"
    LOCAL_APP = "local_app"
    LOCAL_EXTENSION = "local_extension"
    LOCAL_CONFIG_FILE = "local_config_file"
    SYSTEM_KEYCHAIN = "system_keychain"
    BROWSER_SESSION = "browser_session"
    IMPORTED_SESSION = "imported_session"


class AuthStatus(str, Enum):
    NOT_CONFIGURED = "not_configured"
    AVAILABLE_TO_IMPORT = "available_to_import"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FOLLOWING_LOCAL_AUTH = "following_local_auth"
    IMPORTED = "imported"
    EXPIRED = "expired"
    INVALID = "invalid"
    ERROR = "error"


class SyncPolicy(str, Enum):
    MANUAL = "manual"
    IMPORT_COPY = "import_copy"
    FOLLOW = "follow"
