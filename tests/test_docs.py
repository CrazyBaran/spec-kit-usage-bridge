import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(p):
    return (ROOT / p).read_text(encoding="utf-8")


def test_readme_sections():
    r = read("README.md")
    catalog_command = (
        "specify extension catalog add --name usage-bridge --install-allowed "
        "https://github.com/CrazyBaran/spec-kit-usage-bridge/releases/latest/download/catalog.json"
    )
    assert catalog_command in r
    assert "specify extension add usage-bridge" in r and "--from" in r
    for name in ("token-analyzer", "Cost Tracker", "token-budget"):
        assert name in r
    assert "transcript parsing, segmenting and pricing" in r and "docs/limitations.md" in r
    assert "not affiliated" in r and "WARNING" not in r


def test_limitations_list():
    lim = read("docs/limitations.md")
    assert len(re.findall(r"^\d+\. ", lim, flags=re.M)) == 15 and "Upstream candidates" in lim


def test_changelog_and_release_doc():
    assert "## [0.1.0]" in read("CHANGELOG.md") and "f4078277e79c007993e0cb595bb95f924a2a8777" in read("CHANGELOG.md")
    rel = read("docs/release.md")
    assert "tools/update-vendor.py" in rel and "catalog.json" in rel and "specify extension update usage-bridge" in rel
