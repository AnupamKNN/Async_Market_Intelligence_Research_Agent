from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
INTERIM_DIR = PROJECT_ROOT / "data" / "interim"

SOURCE_WORKBOOK = RAW_DIR / "online_retail_II.xlsx"
OUTPUT_FILE = INTERIM_DIR / "online_retail_ii_canonical.csv"

COLUMN_MAPPING = {
    "Invoice": "InvoiceNo",
    "Price": "UnitPrice",
    "Customer ID": "CustomerID",
}

COLUMNS = [
    "InvoiceNo",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "UnitPrice",
    "CustomerID",
    "Country",
]

IDENTIFIER_COLUMNS = [
    "InvoiceNo",
    "StockCode",
    "CustomerID",
]


def normalize_sheet(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Normalize a UCI worksheet into the canonical retail schema."""

    dataframe = dataframe.rename(columns=COLUMN_MAPPING).copy()

    missing_columns = set(COLUMNS).difference(dataframe.columns)

    if missing_columns:
        raise ValueError(f"Worksheet is missing columns: {sorted(missing_columns)}")

    dataframe = dataframe[COLUMNS].copy()

    for column in IDENTIFIER_COLUMNS:
        dataframe[column] = dataframe[column].astype("string").str.strip()

    for column in ["Description", "Country"]:
        dataframe[column] = dataframe[column].astype("string").str.strip()

    dataframe["InvoiceDate"] = pd.to_datetime(
        dataframe["InvoiceDate"],
        errors="coerce",
    )

    dataframe["Quantity"] = pd.to_numeric(
        dataframe["Quantity"],
        errors="coerce",
    ).astype("float64")

    dataframe["UnitPrice"] = pd.to_numeric(
        dataframe["UnitPrice"],
        errors="coerce",
    ).astype("float64")

    if dataframe["InvoiceDate"].isna().any():
        raise ValueError("Invalid invoice dates found during normalization.")

    return dataframe


def get_hash_counts(dataframe: pd.DataFrame) -> pd.Series:
    """Get occurrence counts for exact normalized records."""

    hashes = pd.util.hash_pandas_object(
        dataframe[COLUMNS],
        index=False,
    )

    return hashes.value_counts()


def verify_overlap(
    first_sheet: pd.DataFrame,
    second_sheet: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, int]:
    """Verify that records in the shared date window match exactly."""

    first_start = first_sheet["InvoiceDate"].min()
    first_end = first_sheet["InvoiceDate"].max()

    second_start = second_sheet["InvoiceDate"].min()
    second_end = second_sheet["InvoiceDate"].max()

    overlap_start = max(first_start, second_start)
    overlap_end = min(first_end, second_end)

    first_mask = first_sheet["InvoiceDate"].between(
        overlap_start,
        overlap_end,
    )

    second_mask = second_sheet["InvoiceDate"].between(
        overlap_start,
        overlap_end,
    )

    first_overlap = first_sheet.loc[first_mask]
    second_overlap = second_sheet.loc[second_mask]

    first_counts = get_hash_counts(first_overlap)
    second_counts = get_hash_counts(second_overlap)

    comparison = pd.concat(
        [
            first_counts.rename("first"),
            second_counts.rename("second"),
        ],
        axis=1,
    ).fillna(0)

    mismatches = comparison[comparison["first"] != comparison["second"]]

    if not mismatches.empty:
        raise ValueError(
            "Worksheet overlap is not an exact one-to-one match. "
            f"Found {len(mismatches)} mismatching record hashes. "
            "Canonicalization stopped to prevent data loss."
        )

    LOGGER.info("Verified overlap window: %s to %s", overlap_start, overlap_end)
    LOGGER.info("First worksheet overlap: %s rows", len(first_overlap))
    LOGGER.info("Second worksheet overlap: %s rows", len(second_overlap))

    return second_mask, first_mask, len(second_overlap)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    if not SOURCE_WORKBOOK.exists():
        raise FileNotFoundError(f"Source workbook not found: {SOURCE_WORKBOOK}")

    LOGGER.info("Reading original UCI workbook...")

    sheets = pd.read_excel(
        SOURCE_WORKBOOK,
        sheet_name=None,
        engine="openpyxl",
    )

    first_sheet = normalize_sheet(sheets["Year 2009-2010"])
    second_sheet = normalize_sheet(sheets["Year 2010-2011"])

    LOGGER.info("First worksheet records: %s", len(first_sheet))
    LOGGER.info("Second worksheet records: %s", len(second_sheet))

    # Verify before removing anything.
    second_overlap_mask, _, overlap_duplicates = verify_overlap(
        first_sheet,
        second_sheet,
    )

    # Preserve the first worksheet's records in the shared period.
    # Remove only the proven matching occurrences from the second sheet.
    second_sheet_clean = second_sheet.loc[~second_overlap_mask].copy()

    canonical = pd.concat(
        [first_sheet, second_sheet_clean],
        ignore_index=True,
    )

    original_count = len(first_sheet) + len(second_sheet)

    if len(canonical) != original_count - overlap_duplicates:
        raise RuntimeError("Canonical record-count reconciliation failed.")

    INTERIM_DIR.mkdir(parents=True, exist_ok=True)

    canonical.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8",
    )

    metadata: dict[str, Any] = {
        "source": "UCI Online Retail II",
        "source_workbook": SOURCE_WORKBOOK.name,
        "output_file": OUTPUT_FILE.name,
        "original_record_count": original_count,
        "worksheet_record_counts": {
            "Year 2009-2010": len(first_sheet),
            "Year 2010-2011": len(second_sheet),
        },
        "cross_worksheet_duplicate_occurrences_removed": (overlap_duplicates),
        "canonical_record_count": len(canonical),
        "within_worksheet_duplicates_removed": 0,
        "within_worksheet_duplicates_preserved": True,
        "column_names": COLUMNS,
        "date_min": str(canonical["InvoiceDate"].min()),
        "date_max": str(canonical["InvoiceDate"].max()),
        "canonicalization_method": (
            "Verify exact occurrence-level matches in the shared "
            "date window, retain the first worksheet's records, "
            "and remove matching occurrences from the second worksheet."
        ),
    }

    metadata_path = INTERIM_DIR / "canonicalization_metadata.json"

    with metadata_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=4)

    LOGGER.info("Canonical dataset created: %s", OUTPUT_FILE)
    LOGGER.info("Original records: %s", original_count)
    LOGGER.info("Overlap duplicates removed: %s", overlap_duplicates)
    LOGGER.info("Canonical records: %s", len(canonical))
    LOGGER.info("Metadata saved: %s", metadata_path)


if __name__ == "__main__":
    main()
