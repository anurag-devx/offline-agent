from offline_agent.engine.toolkits.web import domain_allowed


def test_domain_rules():
    assert domain_allowed("en.wikipedia.org", ["wikipedia.org"])
    assert not domain_allowed("evilwikipedia.org", ["wikipedia.org"])
    assert domain_allowed("x.com", ["https://x.com/path"])
    assert not domain_allowed("x.com", [])
