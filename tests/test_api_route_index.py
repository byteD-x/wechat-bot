from pathlib import Path

from scripts.generate_api_route_index import (
    build_markdown,
    generate_route_index,
    parse_api_routes,
)


def test_parse_api_routes_extracts_default_and_explicit_methods(tmp_path: Path):
    source = tmp_path / "api_sample.py"
    source.write_text(
        """
from quart import Quart

app = Quart(__name__)

@app.route("/api/ping")
async def ping():
    return {}

@app.route("/api/items", methods=["POST", "GET"])
def items():
    return {}

@other.route("/api/not-app", methods=["DELETE"])
def ignored():
    return {}
""",
        encoding="utf-8",
    )

    routes = parse_api_routes(source)

    assert [(item.path, item.methods, item.handler) for item in routes] == [
        ("/api/items", ("GET", "POST"), "items"),
        ("/api/ping", ("GET",), "ping"),
    ]
    assert all(item.line > 0 for item in routes)


def test_build_markdown_uses_route_metadata(tmp_path: Path):
    source = tmp_path / "api_sample.py"
    source.write_text(
        """
from quart import Quart

app = Quart(__name__)

@app.route("/api/ping")
async def ping():
    return {}
""",
        encoding="utf-8",
    )
    routes = parse_api_routes(source)

    markdown = build_markdown(routes, source_path="backend/api.py")

    assert "- Source: `backend/api.py`" in markdown
    assert "- Route count: `1`" in markdown
    assert "| `GET` | `/api/ping` | `ping` | `backend/api.py:" in markdown


def test_api_route_index_document_matches_generated_output(tmp_path: Path):
    output = tmp_path / "API_ROUTE_INDEX.md"

    generated = generate_route_index(
        source_path="backend/api.py",
        output_path=output,
    )
    current = Path("docs/API_ROUTE_INDEX.md").read_text(encoding="utf-8")

    assert output.read_text(encoding="utf-8") == generated
    assert current == generated
