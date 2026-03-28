import pytest

from backend.core.auth.providers import BaseAuthProvider
from backend.core.auth.service import AuthFlowRunner, AuthSupportError


class _FakeProvider(BaseAuthProvider):
    def __init__(self, provider_id: str) -> None:
        self.id = provider_id
        self.provider_id = provider_id
        self.label = provider_id

    def status(self, settings=None):
        return {"success": True}

    def start_browser_flow(self, settings=None):
        return {"success": True, "flow_state": {"step": "start"}}

    def cancel_flow(self, flow_state=None, settings=None):
        return {"success": True, "cancelled": True}

    def submit_callback(self, flow_state=None, payload=None, settings=None):
        return {"success": True, "completed": True, "flow_state": {"step": "done"}}


def test_auth_flow_runner_cancel_rejects_provider_mismatch_and_keeps_flow():
    runner = AuthFlowRunner()
    provider_a = _FakeProvider("provider_a")
    provider_b = _FakeProvider("provider_b")
    start_result = runner.start(provider_a, settings={"name": "preset-a"})
    flow_id = start_result["flow_id"]

    with pytest.raises(AuthSupportError, match="provider does not match"):
        runner.cancel(provider_b, flow_id)

    cancel_result = runner.cancel(provider_a, flow_id)
    assert cancel_result["success"] is True
    assert cancel_result["flow_id"] == flow_id
    assert cancel_result["provider_id"] == "provider_a"


def test_auth_flow_runner_submit_rejects_provider_mismatch_without_consuming_flow():
    runner = AuthFlowRunner()
    provider_a = _FakeProvider("provider_a")
    provider_b = _FakeProvider("provider_b")
    start_result = runner.start(provider_a, settings={"name": "preset-a"})
    flow_id = start_result["flow_id"]

    with pytest.raises(AuthSupportError, match="provider does not match"):
        runner.submit(provider_b, flow_id, payload={"code": "1234"})

    submit_result = runner.submit(provider_a, flow_id, payload={"code": "1234"})
    assert submit_result["success"] is True
    assert submit_result["completed"] is True
    assert submit_result["flow_id"] == flow_id
    assert submit_result["provider_id"] == "provider_a"

    with pytest.raises(AuthSupportError, match="expired"):
        runner.submit(provider_a, flow_id, payload={"code": "1234"})
