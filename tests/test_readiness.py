import backend.core.readiness as readiness_module
from scripts import check as check_script


def _passing_check(key, label, message='ok'):
    return readiness_module._build_check(
        key,
        label,
        passed=True,
        message=message,
    )


def _base_config(presets=None):
    return {
        'bot': {
            'required_wechat_version': readiness_module.OFFICIAL_SUPPORTED_WECHAT_VERSION,
            'silent_mode_required': True,
        },
        'api': {
            'presets': presets if presets is not None else [
                {
                    'name': 'OpenAI',
                    'api_key': 'sk-test',
                },
            ],
        },
    }


def _build_report(**kwargs):
    options = {
        'config_loader': lambda: _base_config(),
        'process_counter': lambda: 1,
        'wechat_path_getter': lambda: r'C:\Program Files\Tencent\WeChat\WeChat.exe',
        'wechat_version_getter': lambda _path: readiness_module.OFFICIAL_SUPPORTED_WECHAT_VERSION,
        'supported_versions_getter': lambda: [readiness_module.OFFICIAL_SUPPORTED_WECHAT_VERSION],
    }
    options.update(kwargs)
    return readiness_module.build_readiness_report(
        **options,
    )


def test_readiness_blocks_when_not_admin(monkeypatch):
    monkeypatch.setattr(
        readiness_module,
        '_check_python_version',
        lambda: _passing_check('python_version', 'Python 版本'),
    )
    monkeypatch.setattr(
        readiness_module,
        '_check_dependencies',
        lambda packages=(): _passing_check('dependencies', '依赖安装'),
    )

    report = _build_report(admin_checker=lambda: False)

    admin_check = next(check for check in report['checks'] if check['key'] == 'admin_permission')
    assert report['ready'] is False
    assert report['blocking_count'] == 1
    assert admin_check['blocking'] is True
    assert admin_check['status'] == 'failed'
    assert admin_check['action'] == 'restart_as_admin'


def test_readiness_blocks_when_wechat_not_running(monkeypatch):
    monkeypatch.setattr(
        readiness_module,
        '_check_python_version',
        lambda: _passing_check('python_version', 'Python 版本'),
    )
    monkeypatch.setattr(
        readiness_module,
        '_check_dependencies',
        lambda packages=(): _passing_check('dependencies', '依赖安装'),
    )

    report = _build_report(admin_checker=lambda: True, process_counter=lambda: 0)

    process_check = next(check for check in report['checks'] if check['key'] == 'wechat_process')
    assert report['ready'] is False
    assert report['blocking_count'] == 1
    assert process_check['action'] == 'open_wechat'
    assert process_check['status'] == 'failed'


def test_readiness_blocks_when_wechat_version_incompatible(monkeypatch):
    monkeypatch.setattr(
        readiness_module,
        '_check_python_version',
        lambda: _passing_check('python_version', 'Python 版本'),
    )
    monkeypatch.setattr(
        readiness_module,
        '_check_dependencies',
        lambda packages=(): _passing_check('dependencies', '依赖安装'),
    )

    report = _build_report(
        admin_checker=lambda: True,
        wechat_version_getter=lambda _path: '4.0.0.0',
        supported_versions_getter=lambda: [readiness_module.OFFICIAL_SUPPORTED_WECHAT_VERSION],
    )

    version_check = next(check for check in report['checks'] if check['key'] == 'wechat_compatibility')
    assert report['ready'] is False
    assert report['blocking_count'] == 1
    assert version_check['blocking'] is True
    assert version_check['status'] == 'failed'


def test_readiness_blocks_when_no_valid_preset(monkeypatch):
    monkeypatch.setattr(
        readiness_module,
        '_check_python_version',
        lambda: _passing_check('python_version', 'Python 版本'),
    )
    monkeypatch.setattr(
        readiness_module,
        '_check_dependencies',
        lambda packages=(): _passing_check('dependencies', '依赖安装'),
    )

    report = readiness_module.build_readiness_report(
        config_loader=lambda: _base_config(presets=[]),
        admin_checker=lambda: True,
        process_counter=lambda: 1,
        wechat_path_getter=lambda: r'C:\Program Files\Tencent\WeChat\WeChat.exe',
        wechat_version_getter=lambda _path: readiness_module.OFFICIAL_SUPPORTED_WECHAT_VERSION,
        supported_versions_getter=lambda: [readiness_module.OFFICIAL_SUPPORTED_WECHAT_VERSION],
    )

    preset_check = next(check for check in report['checks'] if check['key'] == 'api_config')
    assert report['ready'] is False
    assert report['blocking_count'] == 1
    assert preset_check['action'] == 'open_settings'
    assert preset_check['status'] == 'failed'


def test_readiness_passes_when_all_core_checks_pass(monkeypatch):
    monkeypatch.setattr(
        readiness_module,
        '_check_python_version',
        lambda: _passing_check('python_version', 'Python 版本'),
    )
    monkeypatch.setattr(
        readiness_module,
        '_check_dependencies',
        lambda packages=(): _passing_check('dependencies', '依赖安装'),
    )

    report = _build_report(admin_checker=lambda: True)

    assert report['ready'] is True
    assert report['blocking_count'] == 0
    assert report['summary']['title']
    assert any(action['action'] == 'retry' for action in report['suggested_actions'])


def test_readiness_service_caches_and_returns_copies():
    call_count = {'value': 0}
    now = {'value': 100.0}

    def builder(*, now_provider):
        call_count['value'] += 1
        return {
            'success': True,
            'ready': False,
            'blocking_count': 1,
            'checks': [],
            'suggested_actions': [],
            'summary': {
                'title': f'run-{call_count["value"]}',
                'detail': 'detail',
            },
            'checked_at': now_provider(),
        }

    service = readiness_module.ReadinessService(
        ttl_sec=5.0,
        builder=builder,
        time_provider=lambda: now['value'],
    )

    first = service.get_report()
    second = service.get_report()
    first['summary']['title'] = 'mutated'

    assert call_count['value'] == 1
    assert second['summary']['title'] == 'run-1'

    now['value'] += 6.0
    third = service.get_report()

    assert call_count['value'] == 2
    assert third['summary']['title'] == 'run-2'


def test_check_script_supports_json_output(monkeypatch, capsys):
    monkeypatch.setattr(
        check_script.readiness_service,
        'get_report',
        lambda force_refresh=True: {
            'success': True,
            'ready': False,
            'blocking_count': 1,
            'checks': [
                {
                    'key': 'admin_permission',
                    'label': '管理员权限',
                    'status': 'failed',
                    'blocking': True,
                    'message': '未以管理员身份运行',
                    'hint': '请提升权限',
                }
            ],
            'suggested_actions': [],
            'summary': {'title': '阻塞 1 项', 'detail': 'detail'},
        },
    )

    result = check_script.run_check(json_output=True, force_refresh=False)

    payload = capsys.readouterr().out
    assert result == 1
    assert '"ready": false' in payload
    assert '"blocking_count": 1' in payload
