from veriquill.github.cache import ResponseCache


def test_cache_round_trip(tmp_path):
    cache = ResponseCache(tmp_path)
    assert cache.get("https://api.github.com/users/octocat") is None

    cache.set("https://api.github.com/users/octocat", etag='W/"abc"', payload={"login": "octocat"})
    hit = cache.get("https://api.github.com/users/octocat")

    assert hit is not None
    assert hit.etag == 'W/"abc"'
    assert hit.payload == {"login": "octocat"}


def test_distinct_urls_do_not_collide(tmp_path):
    cache = ResponseCache(tmp_path)
    cache.set("https://api.github.com/a", etag="1", payload={"v": "a"})
    cache.set("https://api.github.com/b", etag="2", payload={"v": "b"})
    assert cache.get("https://api.github.com/a").payload == {"v": "a"}
    assert cache.get("https://api.github.com/b").payload == {"v": "b"}
