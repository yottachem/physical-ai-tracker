from datetime import date, timedelta

from ingest import news

TODAY = date.today()
RSS = f"""<rss><channel>
<item><title>Acme opens Boston facility</title><link>https://acme.com/news/boston</link>
<pubDate>{(TODAY - timedelta(days=1)).strftime('%a, %d %b %Y')} 12:00:00 GMT</pubDate></item>
<item><title>Old post</title><link>https://acme.com/news/old</link><pubDate>Mon, 06 Jan 2025 12:00:00 GMT</pubDate></item>
</channel></rss>"""
ATOM = f"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Acme ships v2</title>
<link rel="alternate" href="https://acme.com/blog/v2"/><published>{TODAY.isoformat()}T09:00:00Z</published></entry></feed>"""


class Resp:
    def __init__(self, text):
        self.content = text.encode()

    def raise_for_status(self):
        pass


def test_newsroom_rss_and_atom(monkeypatch):
    c = {"name": "Acme", "newsroom_feed": "https://acme.com/feed"}
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: Resp(RSS))
    assert news.newsroom(c, 7) == [{"title": "Acme opens Boston facility", "summary": "",
                                   "url": "https://acme.com/news/boston",
                                   "date": (TODAY - timedelta(days=1)).isoformat(), "publisher": "Acme"}]
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: Resp(ATOM))
    assert [(i["title"], i["url"]) for i in news.newsroom(c, 7)] == [("Acme ships v2", "https://acme.com/blog/v2")]


def test_newsroom_without_feed_fetches_nothing(monkeypatch):
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: 1 / 0)
    assert news.newsroom({"name": "Acme", "newsroom_feed": None}, 7) == []


def test_exclude_and_context():
    potato = {"news": {"terms": ['"Potato"'], "context": ["scientist", "AI"], "exclude": ["Potato Lab"]}}
    assert news.relevant(potato, "Potato Just Launched the Tool It Wishes It Had as a Lab Scientist")
    assert not news.relevant(potato, "Netflix drops trailer for K-drama 'The Potato Lab'")
    assert not news.relevant(potato, "Instant mashed potatoes started in a USDA lab")  # no context word
    assert news.excluded(potato, "The Potato Lab episodes 1-2 recap")
