from usage_bridge.log import get_logger


def test_logger_writes_only_to_file(tmp_path, capfd):
    get_logger(tmp_path, "info").info("hello")
    assert "hello" in (tmp_path / "logs" / "usage-bridge.log").read_text(encoding="utf-8")
    assert capfd.readouterr() == ("", "")


def test_logger_rotates(tmp_path):
    log = get_logger(tmp_path, "info")
    for _ in range(3000):
        log.info("x" * 500)
    assert (tmp_path / "logs" / "usage-bridge.log.1").exists()


def test_log_open_failure_is_silent(tmp_path, capfd):
    log = get_logger(tmp_path, 'info')
    (tmp_path / 'logs' / 'usage-bridge.log').mkdir()
    log.info('cannot open a directory as a log')
    assert capfd.readouterr() == ('', '')


def test_log_rotation_failure_is_silent(tmp_path, monkeypatch, capfd):
    log = get_logger(tmp_path, 'info')
    handler = log.handlers[0]
    def denied(*args):
        raise PermissionError('rotation denied')
    monkeypatch.setattr(handler, 'shouldRollover', denied)
    log.info('rotation error')
    assert capfd.readouterr() == ('', '')
