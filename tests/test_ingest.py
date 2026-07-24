import pandas as pd

from sales_agent.ingest import deal_key, load_mapping, map_columns, normalize_rows


def test_map_columns_recognizes_aliases():
    lookup = load_mapping()
    df = pd.DataFrame(columns=["Opportunity Name", "Account Name", "Amount",
                               "Close Date", "Stage", "Owner", "Forecast Category"])
    mapped = map_columns(df, lookup)
    assert mapped is not None
    assert set(mapped.columns) == {
        "deal_name", "account", "amount", "close_date", "stage", "owner", "forecast_category"
    }


def test_map_columns_rejects_non_deal_tables():
    lookup = load_mapping()
    df = pd.DataFrame(columns=["Region", "Headcount", "Notes"])
    assert map_columns(df, lookup) is None


def test_normalize_rows_coerces_and_quarantines():
    df = pd.DataFrame([
        {"deal_name": "Good Deal", "account": "Acme", "amount": "$120,000",
         "close_date": "2026-03-31", "stage": "Proposal", "owner": "A", "forecast_category": "Commit"},
        {"deal_name": "Bad Amount", "account": "Acme", "amount": "n/a",
         "close_date": "2026-03-31", "stage": None, "owner": None, "forecast_category": None},
        {"deal_name": None, "account": "Acme", "amount": 5,
         "close_date": None, "stage": None, "owner": None, "forecast_category": None},
    ])
    good, rejects = normalize_rows(df)
    assert len(good) == 1 and len(rejects) == 2
    assert good[0]["amount"] == 120000.0
    assert str(good[0]["close_date"]) == "2026-03-31"
    reasons = [r for _, r in rejects]
    assert any("amount" in r for r in reasons)
    assert any("deal_name" in r for r in reasons)


def test_deal_key_stable_and_case_insensitive():
    assert deal_key("Acme", "Big Deal") == deal_key("  acme ", "big deal")
    assert deal_key("Acme", "Big Deal") != deal_key("Acme", "Other Deal")
