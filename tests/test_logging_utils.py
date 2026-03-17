import logging

from backend.utils.logging import (
    HealthcheckAccessLogFilter,
    build_stage_log_message,
    configure_http_access_log_filters,
    format_log_fields,
)


def test_healthcheck_access_log_filter_hides_status_poll_noise():
    record = logging.LogRecord(
        name="hypercorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="127.0.0.1:11203 GET /api/status 1.1 200 2618 1000",
        args=(),
        exc_info=None,
    )

    assert HealthcheckAccessLogFilter().filter(record) is False


def test_healthcheck_access_log_filter_hides_logs_poll_noise():
    record = logging.LogRecord(
        name="hypercorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="127.0.0.1:11203 GET /api/logs 1.1 200 2618 1000",
        args=(),
        exc_info=None,
    )

    assert HealthcheckAccessLogFilter().filter(record) is False


def test_healthcheck_access_log_filter_hides_messages_poll_noise():
    record = logging.LogRecord(
        name="hypercorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="localhost:11203 GET /api/messages 1.1 200 2618 1000",
        args=(),
        exc_info=None,
    )

    assert HealthcheckAccessLogFilter().filter(record) is False


def test_healthcheck_access_log_filter_keeps_other_api_logs():
    record = logging.LogRecord(
        name="hypercorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="127.0.0.1:11203 POST /api/start 1.1 200 128 3200",
        args=(),
        exc_info=None,
    )

    assert HealthcheckAccessLogFilter().filter(record) is True


def test_healthcheck_access_log_filter_keeps_non_local_requests():
    record = logging.LogRecord(
        name="hypercorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="10.0.0.8:11203 GET /api/logs 1.1 200 2618 1000",
        args=(),
        exc_info=None,
    )

    assert HealthcheckAccessLogFilter().filter(record) is True


def test_configure_http_access_log_filters_is_idempotent():
    target_logger = logging.getLogger("hypercorn.access")
    original_filters = list(target_logger.filters)
    try:
        target_logger.filters = []

        configure_http_access_log_filters()
        configure_http_access_log_filters()

        matched = [
            item for item in target_logger.filters
            if isinstance(item, HealthcheckAccessLogFilter)
        ]
        assert len(matched) == 1
    finally:
        target_logger.filters = original_filters


def test_format_log_fields_skips_none_and_normalizes_values():
    rendered = format_log_fields(
        {
            "trace": "f-1234",
            "empty": None,
            "ok": True,
            "meta": {"step": "recv"},
        }
    )

    assert "trace=f-1234" in rendered
    assert "empty=" not in rendered
    assert "ok=true" in rendered
    assert 'meta={"step": "recv"}' in rendered


def test_build_stage_log_message_formats_prefix_and_details():
    rendered = build_stage_log_message("EVENT.RECEIVED", trace="f-1234", chat="文件传输助手")

    assert rendered.startswith("[EVENT.RECEIVED] ")
    assert "trace=f-1234" in rendered
    assert "chat=文件传输助手" in rendered
