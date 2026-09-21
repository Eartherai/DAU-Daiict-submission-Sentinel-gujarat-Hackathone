"""The store's stats cache must actually be capable of returning a hit.

The TTL was three seconds while the computation it guarded took about four
against 798k observations, so every entry had expired by the time the next
caller arrived: the cache never returned a hit once, and every page load paid
the full eighteen-query bill. A cache whose TTL is shorter than its own work
is not a slow cache, it is a disabled one.
"""

import time

from saakshya.store.repository import Store


def test_ttl_is_long_enough_to_ever_be_useful(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'ttl.db'}")
    store.create_all()
    # Not a performance assertion — a coherence one. Whatever the TTL is, it
    # has to exceed the time the guarded work plausibly takes on a live store.
    assert store._stats_ttl_s >= 10.0


def test_a_second_call_is_served_from_the_cache(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'hit.db'}")
    store.create_all()
    first = store.stats()
    marker = object()
    # Poison the underlying table access: if the second call recomputes it
    # would have to touch the engine, and the cached dict is returned as-is.
    cached_at, payload = store._stats_cache
    payload["__probe__"] = marker
    again = store.stats()
    assert again.get("__probe__") is marker
    assert again["observations"] == first["observations"]


def test_an_expired_entry_is_recomputed(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'exp.db'}")
    store.create_all()
    store.stats()
    cached_at, payload = store._stats_cache
    payload["__probe__"] = object()
    # Age the entry past its TTL.
    store._stats_cache = (cached_at - store._stats_ttl_s - 1.0, payload)
    fresh = store.stats()
    assert "__probe__" not in fresh


def test_object_type_is_indexed(tmp_path):
    """Several stats queries filter on object_type; unindexed it is a scan."""
    store = Store(f"sqlite:///{tmp_path / 'ix.db'}")
    store.create_all()
    with store.engine.connect() as c:
        from sqlalchemy import text
        names = {r[0] for r in c.execute(text(
            "select name from sqlite_master where type='index' "
            "and tbl_name='observations'"))}
    assert "ix_obs_object_type" in names
