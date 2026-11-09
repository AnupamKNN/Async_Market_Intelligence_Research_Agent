from __future__ import annotations

import gc
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
INTERIM_DIR = PROJECT_ROOT / "data" / "interim"

DATASETS = {
    "online_retail": RAW_DIR / "online_retail.csv",
    "online_retail_ii": RAW_DIR / "online_retail_ii.csv",
}

REQUIRED_COLUMNS = [
    "InvoiceNo",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "UnitPrice",
    "CustomerID",
    "Country",
]

ID_COLUMNS = ["InvoiceNo", "StockCode", "CustomerID"]


def load_dataset(path: Path) -> pd.DataFrame:
    """Load a retail CSV while preserving identifier columns as strings."""

    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    dataframe = pd.read_csv(
        path,
        dtype={column: "string" for column in ID_COLUMNS},
    )

    missing_columns = set(REQUIRED_COLUMNS).difference(dataframe.columns)

    if missing_columns:
        raise ValueError(f"{path.name} is missing columns: {sorted(missing_columns)}")

    return dataframe[REQUIRED_COLUMNS]


def profile_dataset(dataframe: pd.DataFrame) -> tuple[dict[str, Any], pd.Series]:
    """Generate data quality metrics without modifying the original data."""

    dates = pd.to_datetime(
        dataframe["InvoiceDate"],
        format="mixed",
        errors="coerce",
    )

    quantity = pd.to_numeric(dataframe["Quantity"], errors="coerce")
    unit_price = pd.to_numeric(dataframe["UnitPrice"], errors="coerce")

    invoice_numbers = dataframe["InvoiceNo"].astype("string").str.strip()

    cancellation_mask = invoice_numbers.str.upper().str.startswith(
        "C",
        na=False,
    )

    missing_values = dataframe.isna().sum()

    report = {
        "record_count": int(len(dataframe)),
        "column_count": int(len(dataframe.columns)),
        "columns": list(dataframe.columns),
        "memory_usage_mb": round(
            dataframe.memory_usage(deep=True).sum() / (1024**2),
            2,
        ),
        "missing_values": {column: int(count) for column, count in missing_values.items()},
        "duplicate_full_rows": int(dataframe.duplicated().sum()),
        "unique_invoices": int(dataframe["InvoiceNo"].nunique()),
        "unique_products": int(dataframe["StockCode"].nunique()),
        "unique_customers": int(dataframe["CustomerID"].nunique()),
        "unique_countries": int(dataframe["Country"].nunique()),
        "date_min": str(dates.min()) if dates.notna().any() else None,
        "date_max": str(dates.max()) if dates.notna().any() else None,
        "invalid_dates": int(dates.isna().sum()),
        "invalid_quantity_values": int((quantity.isna() & dataframe["Quantity"].notna()).sum()),
        "invalid_price_values": int((unit_price.isna() & dataframe["UnitPrice"].notna()).sum()),
        "negative_quantity_rows": int((quantity < 0).sum()),
        "zero_quantity_rows": int((quantity == 0).sum()),
        "negative_price_rows": int((unit_price < 0).sum()),
        "zero_price_rows": int((unit_price == 0).sum()),
        "cancellation_invoice_rows": int(cancellation_mask.sum()),
        "quantity_sum": float(quantity.sum()),
        "unit_price_min": (float(unit_price.min()) if unit_price.notna().any() else None),
        "unit_price_max": (float(unit_price.max()) if unit_price.notna().any() else None),
    }

    return report, dates


def normalize_identifier(series: pd.Series) -> pd.Series:
    """Normalize numeric-looking identifiers represented as strings."""

    normalized = series.astype("string").str.strip()

    return normalized.str.replace(
        r"^(\d+)\.0$",
        r"\1",
        regex=True,
    )


def calculate_row_hashes(
    dataframe: pd.DataFrame,
    dates: pd.Series,
) -> pd.Series:
    """Create consistent hashes for exact record comparison."""

    normalized = pd.DataFrame(index=dataframe.index)

    for column in ID_COLUMNS:
        normalized[column] = normalize_identifier(dataframe[column])

    normalized["Description"] = dataframe["Description"].astype("string").str.strip()
    normalized["Quantity"] = pd.to_numeric(dataframe["Quantity"], errors="coerce").astype("float64")
    normalized["InvoiceDate"] = dates
    normalized["UnitPrice"] = pd.to_numeric(dataframe["UnitPrice"], errors="coerce").astype(
        "float64"
    )
    normalized["Country"] = dataframe["Country"].astype("string").str.strip()

    return pd.util.hash_pandas_object(
        normalized[REQUIRED_COLUMNS],
        index=False,
    )


def audit_overlap(
    retail_hash_counts: pd.Series,
    retail_dates: pd.Series,
    ii_dataframe: pd.DataFrame,
    ii_dates: pd.Series,
) -> dict[str, Any]:
    """Compare exact records inside the two datasets' shared date window."""

    overlap_start = retail_dates.min()
    overlap_end = retail_dates.max()

    ii_mask = ii_dates.between(overlap_start, overlap_end)

    ii_overlap = ii_dataframe.loc[ii_mask]

    ii_overlap_dates = ii_dates.loc[ii_mask]

    ii_hash_counts = calculate_row_hashes(
        ii_overlap,
        ii_overlap_dates,
    ).value_counts()

    common = pd.concat(
        [
            retail_hash_counts.rename("retail_count"),
            ii_hash_counts.rename("retail_ii_count"),
        ],
        axis=1,
    ).dropna()

    matched_rows = int(common.min(axis=1).sum()) if not common.empty else 0

    return {
        "comparison_type": "exact matching across all eight normalized columns",
        "overlap_window_start": str(overlap_start),
        "overlap_window_end": str(overlap_end),
        "online_retail_rows": int(len(retail_dates)),
        "online_retail_ii_rows_in_overlap_window": int(len(ii_overlap)),
        "shared_unique_record_hashes": int(len(common)),
        "one_to_one_matched_row_occurrences": matched_rows,
        "unmatched_online_retail_rows": int(len(retail_dates) - matched_rows),
        "unmatched_online_retail_ii_rows_in_window": int(len(ii_overlap) - matched_rows),
    }


def save_json(report: dict[str, Any], filename: str) -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)

    output_path = INTERIM_DIR / filename

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=4, default=str)

    LOGGER.info("Report saved: %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    profiles = {}

    LOGGER.info("Profiling Online Retail...")

    retail = load_dataset(DATASETS["online_retail"])
    retail_profile, retail_dates = profile_dataset(retail)

    profiles["online_retail"] = retail_profile

    # Retain only row-hash counts for the overlap audit.
    retail_hash_counts = calculate_row_hashes(
        retail,
        retail_dates,
    ).value_counts()

    del retail
    gc.collect()

    LOGGER.info("Profiling Online Retail II...")

    retail_ii = load_dataset(DATASETS["online_retail_ii"])
    retail_ii_profile, retail_ii_dates = profile_dataset(retail_ii)

    profiles["online_retail_ii"] = retail_ii_profile

    LOGGER.info("Auditing exact record overlap...")

    overlap_report = audit_overlap(
        retail_hash_counts,
        retail_dates,
        retail_ii,
        retail_ii_dates,
    )

    save_json(profiles, "retail_data_profile.json")
    save_json(overlap_report, "retail_overlap_audit.json")

    print("\n========== DATASET PROFILES ==========")
    print(json.dumps(profiles, indent=2))

    print("\n========== OVERLAP AUDIT ==========")
    print(json.dumps(overlap_report, indent=2))

    LOGGER.info("Profiling and overlap audit completed.")


if __name__ == "__main__":
    main()
