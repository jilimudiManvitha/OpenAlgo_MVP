"""Category identity, transactional refresh and real supplied-file coverage."""

import copy
import csv
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from database.engine_factory import create_db_engine
from services.stock_categories import SOURCE_DIR, load_catalog, save_catalog


def test_supplied_index_sets_and_industry_partition():
    catalog = load_catalog()
    categories = catalog["categories"]
    for key, expected in (
        ("nifty50", 50),
        ("niftynext50", 50),
        ("nifty500", 500),
        ("niftylargemidcap250", 250),
        ("niftymidsmallcap400", 400),
    ):
        assert len(categories[key]["symbols"]) == expected
    with (SOURCE_DIR / "ind_nifty500list.csv").open() as handle:
        source = list(csv.DictReader(handle))
    assert set(categories["nifty500"]["symbols"]) == {r["Symbol"] for r in source}
    for row in source:
        matching = [
            c
            for c in categories.values()
            if c["kind"] == "industry" and row["Symbol"] in c["symbols"]
        ]
        assert len(matching) == 1
        assert matching[0]["label"] == "Sector · " + row["Industry"]
    assert "NIFTY AUTO" not in catalog["instruments"]
    assert "DONE" not in catalog["instruments"]
    assert "IIFLWAM" not in categories["nifty500"]["symbols"]
    assert "IIFLWAM" in categories["reference_nifty500_symbols_txt"]["symbols"]
    assert len(categories["cement"]["symbols"]) == 31
    assert "BVCL" in categories["cement"]["symbols"]
    assert "KOTAKBANK" in categories["niftybank"]["symbols"]
    assert len([f for f in catalog["files"] if f["status"] == "excluded_price_history"]) == 6
    assert not catalog["issues"]


def test_unknown_names_and_bad_symbols_fail_before_writing(tmp_path):
    path = tmp_path / "ind_nifty50list.csv"
    path.write_text("Symbol,Series\nABC,EQ\nABC,EQ\nEXCLUDED,BE\n")
    assert load_catalog(tmp_path)["categories"]["nifty50"]["symbols"] == ["ABC"]
    (tmp_path / "Dhan - Nifty Bank.csv").write_text("Name\nUnknown invented bank\n")
    with pytest.raises(ValueError, match="Unresolved stock names"):
        load_catalog(tmp_path)
    path.write_text("Symbol,Series\nNOT A TICKER,EQ\n")
    with pytest.raises(ValueError, match="Invalid NSE equity symbol"):
        load_catalog(tmp_path)


def test_atomic_idempotent_import_preserves_unrelated_categories(tmp_path):
    (tmp_path / "ind_nifty50list.csv").write_text("Symbol,Series\nABC,EQ\nDEF,EQ\n")
    catalog = load_catalog(tmp_path)
    engine = create_db_engine("sqlite:///" + str(tmp_path / "catalog.db"))
    try:
        save_catalog(engine, catalog)
        save_catalog(engine, catalog)
        with engine.begin() as c:
            assert c.execute(text("SELECT count(*) FROM stock_category_memberships")).scalar() == 2
            payload = json.loads(
                c.execute(text("SELECT payload FROM scanner_live_categories")).scalar()
            )
            payload["custom"] = {"symbols": ["OTHER"]}
            c.execute(
                text("UPDATE scanner_live_categories SET payload=:p"), {"p": json.dumps(payload)}
            )
        bad = copy.deepcopy(catalog)
        bad["categories"]["nifty50"]["symbols"] = ["ABC", "ABC"]
        with pytest.raises(IntegrityError):
            save_catalog(engine, bad)
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM stock_category_memberships")).scalar() == 2
        (tmp_path / "ind_nifty50list.csv").write_text("Symbol,Series\nDEF,EQ\n")
        save_catalog(engine, load_catalog(tmp_path))
        with engine.connect() as c:
            assert c.execute(
                text("SELECT symbol FROM stock_category_memberships")
            ).scalars().all() == ["DEF"]
            payload = json.loads(
                c.execute(text("SELECT payload FROM scanner_live_categories")).scalar()
            )
            assert payload["custom"] == {"symbols": ["OTHER"]}
            assert payload["nifty50"]["symbols"] == ["DEF"]
    finally:
        engine.dispose()
