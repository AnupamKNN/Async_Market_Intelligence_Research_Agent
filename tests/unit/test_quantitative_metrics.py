
import pytest

from market_intelligence.orchestration.graph import (
    calculate_quantitative_metrics,
)


@pytest.fixture
def internal_data():
    return {
        "sales_summary": {
            "positive_line_value": "200.00",
            "negative_adjustment_value": "-20.00",
            "net_line_value": "180.00",
            "net_quantity": 50,
            "transaction_lines": 10,
        },
        "dataset_overview": {
            "unique_invoices": 8,
            "unique_products": 5,
            "unique_customers": 7,
            "unique_countries": 2,
        },
        "top_products": [
            {"stock_code": "A", "net_line_value": "90.00"},
            {"stock_code": "B", "net_line_value": "45.00"},
            {"stock_code": "C", "net_line_value": "9.00"},
        ],
    }


def test_calculates_and_reconciles_metrics(internal_data):
    result = calculate_quantitative_metrics(internal_data)

    assert result["status"] == "validated"
    assert result["reconciliation_passed"] is True
    assert result["reconciliation_difference"] == "0.00"

    assert result["source_metrics"]["net_quantity"] == "50"
    assert result["source_metrics"]["unique_invoices"] == 8

    derived = result["derived_metrics"]

    assert derived["retrieved_products_count"] == 3
    assert derived["retrieved_products_net_line_value"] == "144.00"
    assert derived["retrieved_products_share_of_net_line_value_pct"] == "80.00"

    assert result["validation_checks"][
        "retrieved_products_sorted_by_net_line_value"
    ] is True


def test_detects_reconciliation_failure(internal_data):
    internal_data["sales_summary"]["net_line_value"] = "175.00"

    result = calculate_quantitative_metrics(internal_data)

    assert result["status"] == "reconciliation_failed"
    assert result["reconciliation_passed"] is False
    assert result["reconciliation_difference"] == "5.00"


def test_detects_unsorted_products(internal_data):
    internal_data["top_products"] = [
        {"stock_code": "A", "net_line_value": "45.00"},
        {"stock_code": "B", "net_line_value": "90.00"},
    ]

    result = calculate_quantitative_metrics(internal_data)

    assert result["validation_checks"][
        "retrieved_products_sorted_by_net_line_value"
    ] is False


def test_handles_missing_sales_summary():
    result = calculate_quantitative_metrics({})

    assert result["status"] == "not_available"
    assert "reason" in result


def test_handles_zero_net_line_value(internal_data):
    internal_data["sales_summary"].update(
        {
            "positive_line_value": "10",
            "negative_adjustment_value": "-10",
            "net_line_value": "0",
        }
    )

    result = calculate_quantitative_metrics(internal_data)

    assert result["reconciliation_passed"] is True
    assert (
        result["derived_metrics"][
            "retrieved_products_share_of_net_line_value_pct"
        ]
        is None
    )


def test_rejects_invalid_numeric_values(internal_data):
    internal_data["top_products"][0]["net_line_value"] = "invalid"

    with pytest.raises(ValueError, match="Invalid numeric field"):
        calculate_quantitative_metrics(internal_data)
