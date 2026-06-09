from pathlib import Path

from scripts.check_frontend_backend_contract import (
    HighSideEffectPostEndpoint,
    check_frontend_backend_contract,
    parse_api_service_request_endpoints,
    parse_ipc_allowlist,
)


def test_contract_check_passes_for_minimal_aligned_sources(tmp_path: Path):
    backend, ipc, api_service = _write_contract_sources(
        tmp_path,
        backend_source="""
from quart import Quart

app = Quart(__name__)

_IDEMPOTENT_ENDPOINTS = {
    ("POST", "/api/send"),
}

@app.route("/api/status", methods=["GET"])
async def status():
    return {}

@app.route("/api/send", methods=["POST"])
async def send():
    return {}
""",
        ipc_source="""
const ALLOWED_BACKEND_PATHS = new Set([
    '/api/status',
    '/api/send',
]);
const ALLOWED_BACKEND_PATH_PATTERNS = [
    /^\\/api\\/items\\/[^/?#]+\\/run$/,
];
""",
        api_service_source="""
class ApiService {
    constructor() {
        this.idempotentPostEndpoints = new Set([
            '/api/send',
        ]);
    }

    async getStatus() {
        return this.request(`/api/status${this._buildQueryString({ refresh: true })}`);
    }

    async sendMessage() {
        return this.request('/api/send', { method: 'POST' });
    }
}
""",
    )

    result = check_frontend_backend_contract(
        backend_source=backend,
        ipc_source=ipc,
        api_service_source=api_service,
        high_side_effect_post_endpoints=[
            HighSideEffectPostEndpoint("/api/send", "sends a message"),
        ],
    )

    assert result.ok
    assert result.api_service_fixed_paths == frozenset({"/api/status", "/api/send"})


def test_contract_check_reports_ipc_path_without_backend_route(tmp_path: Path):
    backend, ipc, api_service = _write_contract_sources(
        tmp_path,
        backend_source="""
from quart import Quart

app = Quart(__name__)

@app.route("/api/status", methods=["GET"])
async def status():
    return {}
""",
        ipc_source="""
const ALLOWED_BACKEND_PATHS = new Set([
    '/api/status',
    '/api/orphan',
]);
const ALLOWED_BACKEND_PATH_PATTERNS = [];
""",
        api_service_source="""
class ApiService {
    constructor() {
        this.idempotentPostEndpoints = new Set([]);
    }
}
""",
    )

    result = check_frontend_backend_contract(
        backend_source=backend,
        ipc_source=ipc,
        api_service_source=api_service,
        high_side_effect_post_endpoints=[],
    )

    assert _issue_codes(result) == {"ipc_path_missing_backend_route"}
    assert result.issues[0].path == "/api/orphan"


def test_contract_check_reports_api_service_path_without_ipc_allowlist(tmp_path: Path):
    backend, ipc, api_service = _write_contract_sources(
        tmp_path,
        backend_source="""
from quart import Quart

app = Quart(__name__)

@app.route("/api/status", methods=["GET"])
async def status():
    return {}

@app.route("/api/hidden", methods=["GET"])
async def hidden():
    return {}
""",
        ipc_source="""
const ALLOWED_BACKEND_PATHS = new Set([
    '/api/status',
]);
const ALLOWED_BACKEND_PATH_PATTERNS = [];
""",
        api_service_source="""
class ApiService {
    constructor() {
        this.idempotentPostEndpoints = new Set([]);
    }

    async hidden() {
        return this.request('/api/hidden');
    }
}
""",
    )

    result = check_frontend_backend_contract(
        backend_source=backend,
        ipc_source=ipc,
        api_service_source=api_service,
        high_side_effect_post_endpoints=[],
    )

    assert _issue_codes(result) == {"api_service_path_missing_ipc_allowlist"}
    assert result.issues[0].path == "/api/hidden"


def test_contract_check_reports_high_side_effect_post_without_idempotency(tmp_path: Path):
    backend, ipc, api_service = _write_contract_sources(
        tmp_path,
        backend_source="""
from quart import Quart

app = Quart(__name__)

_IDEMPOTENT_ENDPOINTS = set()

@app.route("/api/send", methods=["POST"])
async def send():
    return {}
""",
        ipc_source="""
const ALLOWED_BACKEND_PATHS = new Set([
    '/api/send',
]);
const ALLOWED_BACKEND_PATH_PATTERNS = [];
""",
        api_service_source="""
class ApiService {
    constructor() {
        this.idempotentPostEndpoints = new Set([]);
    }

    async sendMessage() {
        return this.request('/api/send', { method: 'POST' });
    }
}
""",
    )

    result = check_frontend_backend_contract(
        backend_source=backend,
        ipc_source=ipc,
        api_service_source=api_service,
        high_side_effect_post_endpoints=[
            HighSideEffectPostEndpoint("/api/send", "sends a message"),
        ],
    )

    assert _issue_codes(result) == {"high_side_effect_post_missing_idempotency"}
    assert result.issues[0].path == "/api/send"


def test_parse_helpers_cover_fixed_paths_query_templates_and_regex(tmp_path: Path):
    _backend, ipc, api_service = _write_contract_sources(
        tmp_path,
        backend_source="""
from quart import Quart
app = Quart(__name__)
""",
        ipc_source="""
const ALLOWED_BACKEND_PATHS = new Set([
    '/api/status',
]);
const ALLOWED_BACKEND_PATH_PATTERNS = [
    /^\\/api\\/items\\/[^/?#]+\\/run$/,
];
""",
        api_service_source="""
class ApiService {
    async getStatus() {
        return this.request(`/api/status${this._buildQueryString({ refresh: true })}`);
    }

    async dynamicItem(id) {
        return this.request(`/api/items/${id}/run`, { method: 'POST' });
    }
}
""",
    )

    fixed_paths, patterns = parse_ipc_allowlist(ipc)
    endpoints = parse_api_service_request_endpoints(api_service)

    assert fixed_paths == {"/api/status"}
    assert any(pattern.pattern.fullmatch("/api/items/abc/run") for pattern in patterns)
    assert [item.path for item in endpoints] == ["/api/status"]
    assert endpoints[0].line > 0


def test_repository_contract_check_passes():
    result = check_frontend_backend_contract()

    assert result.ok, [f"{issue.code}:{issue.path}" for issue in result.issues]


def _write_contract_sources(
    tmp_path: Path,
    *,
    backend_source: str,
    ipc_source: str,
    api_service_source: str,
) -> tuple[Path, Path, Path]:
    backend = tmp_path / "api.py"
    ipc = tmp_path / "ipc.js"
    api_service = tmp_path / "ApiService.js"
    backend.write_text(backend_source.lstrip(), encoding="utf-8")
    ipc.write_text(ipc_source.lstrip(), encoding="utf-8")
    api_service.write_text(api_service_source.lstrip(), encoding="utf-8")
    return backend, ipc, api_service


def _issue_codes(result) -> set[str]:
    return {issue.code for issue in result.issues}
