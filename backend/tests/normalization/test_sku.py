import pytest

from acme.normalization.sku import SkuCatalog, key, match_sku


@pytest.fixture
def catalog(seeded_db):
    return SkuCatalog.load(seeded_db)


@pytest.mark.parametrize("raw, sku, method", [
    ("WidgetA", "WidgetA", "exact"),
    ("widget a", "WidgetA", "exact"),  # case, spaces, and punctuation ignored
    ("Widget-B", "WidgetB", "exact"),
    ("Widget A", "WidgetA", "exact"),
    ("Gadget X", "GadgetX", "exact"),
    ("FakeItem", "FakeItem", "exact"),  # zero stock still resolves
])
def test_resolves(catalog, raw, sku, method):
    assert match_sku(raw, catalog) == (sku, method)


def test_alias_table_lookup(seeded_db):
    seeded_db.execute("INSERT INTO item_aliases (alias, sku) VALUES ('Blue Widget', 'WidgetB')")
    assert match_sku("blue widget", SkuCatalog.load(seeded_db)) == ("WidgetB", "alias")


def test_fuzzy_at_or_above_90(catalog):
    sku, method = match_sku("GadgettX", catalog)
    assert sku == "GadgetX" and method.startswith("fuzzy:") and float(method[6:]) >= 90


@pytest.mark.parametrize("raw", ["SuperGizmo", "MegaSprocket", "WidgetC", "WidgetА"])
def test_stays_unknown(catalog, raw):
    assert match_sku(raw, catalog) == (None, "none")


def test_key():
    assert key(" Widget-A. ") == "widgeta" and key("WidgetА") != "widgeta"
