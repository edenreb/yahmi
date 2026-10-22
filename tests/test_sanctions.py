"""Sanctions-list screening on an invented list (no real names in tests)."""
from datetime import datetime, timedelta, timezone

from yahmi.sanctions import Sanctions, check_sanctions

NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
DATA = {
    "meta": {"un": {"generated": "2026-10-20T00:00:00Z", "fetched_at": NOW}, "uae_ltl": {"fetched_at": NOW}},
    "entries": [
        {"list": "UN", "kind": "entity", "ref": "XX.001", "names": ["Zorbax Holdings International", "Zorbax Intl Group"], "listed_on": "2020-01-01"},
        {"list": "UAE_LTL", "kind": "entity", "ref": "7", "names": ["Qelvin Relief Foundation", "مؤسسة كيلفين للإغاثة"], "listed_on": ""},
        {"list": "UN", "kind": "individual", "ref": "XX.002", "names": ["Brandor Quill Vexley Marsh", "Brandor Marsh"], "listed_on": ""},
    ],
}
S = Sanctions(DATA)


def level(name):
    return [f.level for f in check_sanctions(name, S) if f.check == "sanctions"]


def test_exact_entity_is_red_and_cites_list_and_reference():
    f = check_sanctions("ZORBAX HOLDINGS INTERNATIONAL L.L.C", S)[0]
    assert f.level == "red" and "UN Security Council" in f.message and "XX.001" in f.message and "not proof" in f.message
    assert "UN Security Council Consolidated List" in f.source


def test_alias_arabic_and_suffix_variants_match():
    assert level("Zorbax Intl Group LLC") == ["red"]
    assert level("مؤسسة كيلفين للإغاثة") == ["red"]
    assert level("Qelvin Relief Foundation FZE") == ["red"]


def test_similar_entity_name_is_amber_not_red():
    assert level("Zorbax Holdings Internationl") == ["amber"]     # one typo
    assert level("Qelvin Relief Foundation Dubai Trading") != ["red"]


def test_individuals_need_three_words_and_never_red():
    assert level("Brandor Quill Vexley Marsh") == ["amber"]
    assert level("Brandor Marsh") == ["green"]                      # two-word personal names collide too often: no match is raised
    assert level("Mohammed Ali") == ["green"]


def test_ordinary_supplier_names_do_not_match():
    for n in ["Falcon Building Materials LLC", "Al Noor Trading", "Blue Creek Logistics LLC", "Zorbax", "Holdings International"]:
        assert level(n) == ["green"] or level(n) == [], n
    assert level("Falcon Building Materials LLC") == ["green"]


def test_nothing_without_a_list_or_a_name():
    assert check_sanctions("Zorbax Holdings International", None) == [] and check_sanctions(None, S) == []


def test_stale_lists_are_flagged():
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
    s2 = Sanctions({"meta": {"un": {"fetched_at": old}, "uae_ltl": {"fetched_at": old}}, "entries": DATA["entries"]})
    assert [f.check for f in check_sanctions("Falcon Building Materials LLC", s2)] == ["sanctions", "sanctions_stale"]
