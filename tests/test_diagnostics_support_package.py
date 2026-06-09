import json
from pathlib import Path

from scripts import inspect_diagnostics_support_package as inspector


FIXTURE_PATH = Path("tests/fixtures/diagnostics_support_package_minimal.json")


def test_inspect_minimal_package_reports_readiness_blocker():
    report = inspector.inspect_support_package(FIXTURE_PATH)

    assert report["success"] is True
    assert report["diagnostic_id"] == "diag-local-minimal"
    assert report["redaction_passed"] is True
    assert report["warnings"] == []
    assert report["readiness"]["ready"] is False
    assert report["readiness"]["blocking_count"] == 1
    assert report["readiness"]["blocking_items"] == [
        {
            "key": "admin_permission",
            "label": "Administrator permission",
            "status": "failed",
            "message": "The desktop app is not running as administrator.",
            "hint": "Restart the app with elevated permission.",
            "action": "restart_as_admin",
        }
    ]
    assert report["update"]["available"] is True
    assert report["update"]["latest_version"] == "1.1.0"
    assert report["logs"]["error_count"] == 1
    assert "wechat_disconnected" in report["logs"]["backend_errors"][0]


def test_cli_json_output_is_parseable(capsys):
    result = inspector.main([str(FIXTURE_PATH), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["diagnostic_id"] == "diag-local-minimal"
    assert payload["readiness"]["blocking_items"][0]["key"] == "admin_permission"


def test_missing_sections_emit_clear_warnings():
    report = inspector.inspect_package({"diagnostic_id": "diag-missing"})

    assert report["redaction_passed"] is True
    assert "manifest section is missing or invalid" in report["warnings"]
    assert "snapshot section is missing or invalid" in report["warnings"]
    assert "readiness section is missing or invalid" in report["warnings"]
    assert "update section is missing or invalid" in report["warnings"]
    assert "logs section is missing or invalid" in report["warnings"]


def test_sensitive_input_marks_redaction_failed_without_leaking_values(tmp_path, capsys):
    hidden_api_key = "sk" + "-" + "thisShouldNeverAppear1234567890"
    hidden_token = "token" + "=" + "thisShouldNeverAppear"
    hidden_session = "oauth_session=sessionShouldNeverAppear"
    hidden_chat_text = "private chat body should not appear"
    hidden_path = "C:" + r"\Users\Alice\wechat-chat\data\bot.log"
    package_path = tmp_path / "support.json"
    package_path.write_text(
        json.dumps(
            {
                "diagnostic_id": "diag-sensitive",
                "generated_at": "2026-06-06T10:20:30.000Z",
                "manifest": {
                    "schema_version": 1,
                    "package_type": "diagnostics_support_package",
                    "automatic_upload": False,
                    "full_logs_included": False,
                },
                "snapshot": {
                    "runtime": {
                        "status": {
                            "diagnostics": {
                                "detail": "api_key" + f"={hidden_api_key}",
                            },
                            "last_message": hidden_chat_text,
                        },
                        "readiness": {
                            "ready": False,
                            "checks": [
                                {
                                    "key": "api_config",
                                    "label": "API config",
                                    "status": "failed",
                                    "blocking": True,
                                    "message": "token" + f"={hidden_token}",
                                    "hint": hidden_session,
                                    "action": "open_settings",
                                }
                            ],
                        },
                    },
                    "update": {
                        "enabled": True,
                        "error": f"installer at {hidden_path}",
                    },
                    "logs": [
                        f"ERROR raw_content=\"{hidden_chat_text}\" {hidden_path}",
                    ],
                    "config": {
                        "effective": {
                            "api": {
                                "presets": [
                                    {
                                        "name": "OpenAI",
                                        "api_key": hidden_api_key,
                                    }
                                ]
                            }
                        }
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = inspector.main([str(package_path), "--json"])
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert result == 1
    assert payload["redaction_passed"] is False
    assert payload["redaction"]["input_findings_count"] > 0
    assert hidden_api_key not in output
    assert hidden_token not in output
    assert hidden_session not in output
    assert hidden_chat_text not in output
    assert hidden_path not in output
    assert str(tmp_path) not in output
    assert "credential" in {item["category"] for item in payload["redaction"]["findings"]}
