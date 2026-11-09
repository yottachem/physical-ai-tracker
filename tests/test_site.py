import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("site_build", Path(__file__).parents[1] / "site" / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_half_and_equity():
    assert build.half("2026-08-03") == "2026 H2" and build.half("2026-03") == "2026 H1" and build.half("2026") == "2026"
    assert build.month("2026-07-21") == "Jul 2026" and build.month("2026-01") == "Jan 2026"
    assert build.is_equity({"type": "funding", "round": "Series B", "detail": "$75M Series B"})
    assert not build.is_equity({"type": "funding", "round": "Bridge loan (Hyundai)", "detail": ""})
    assert not build.is_equity({"type": "funding", "round": "", "detail": "$20M ARPA-H award"})


def test_build_renders_every_page(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "DIST", tmp_path / "dist")
    build.main(preview=True)
    pages = {p.name for p in (tmp_path / "dist").glob("*.html")}
    assert pages == {"index.html", "feed.html", "funding.html", "hiring.html", "methods.html", "status.html"}
    assert len(list((tmp_path / "dist" / "company").glob("*.html"))) == len(build.load_companies())
    assert "news.google.com" not in (tmp_path / "dist" / "feed.html").read_text()
