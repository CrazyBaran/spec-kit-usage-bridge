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
