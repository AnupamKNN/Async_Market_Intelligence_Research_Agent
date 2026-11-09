from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
from ucimlrepo import fetch_ucirepo

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"

REQUIRED_COLUMNS = {
    "InvoiceNo",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "UnitPrice",
    "CustomerID",
    "Country",
}

DATASETS: dict[str, dict[str, Any]] = {
    "online_retail": {
        "uci_id": 352,
        "filename": "online_retail.csv",
        "display_name": "Online Retail",
        "repository_url": "https://archive.ics.uci.edu/dataset/352/online+retail",
        "doi": "10.24432/C5BW33",
    },
    "online_retail_ii": {
        "uci_id": 502,
        "filename": "online_retail_ii.csv",
        "display_name": "Online Retail II",
        "repository_url": "https://archive.ics.uci.edu/dataset/502/online+retail+ii",
        "doi": "10.24432/C5CG6D",
        "download_url": ("https://archive.ics.uci.edu/static/public/502/online%2Bretail%2Bii.zip"),
    },
}


def calculate_sha256(file_path: Path) -> str:
    """Calculate the SHA-256 checksum of a file."""

    digest = hashlib.sha256()

    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def validate_columns(dataframe: pd.DataFrame) -> None:
    """Validate the expected retail dataset schema."""

    missing_columns = REQUIRED_COLUMNS.difference(dataframe.columns)

    if missing_columns:
        raise ValueError(f"Unexpected dataset schema. Missing columns: {sorted(missing_columns)}")


def save_metadata(metadata: dict[str, Any], dataset_name: str) -> None:
    """Persist dataset metadata alongside the raw dataset."""

    metadata_path = RAW_DATA_DIR / f"{dataset_name}_metadata.json"

    with metadata_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=4, default=str)

    LOGGER.info("Metadata saved to: %s", metadata_path)


def download_online_retail() -> None:
    """Download Online Retail through the UCI Python repository."""

    config = DATASETS["online_retail"]

    LOGGER.info("Fetching %s from UCI...", config["display_name"])

    dataset = fetch_ucirepo(id=config["uci_id"])
    dataframe = dataset.data.original

    if dataframe is None or dataframe.empty:
        raise ValueError("Online Retail returned an empty dataset.")

    validate_columns(dataframe)

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = RAW_DATA_DIR / config["filename"]
    dataframe.to_csv(csv_path, index=False)

    metadata = {
        "dataset_name": config["display_name"],
        "uci_id": config["uci_id"],
        "uci_reported_records": getattr(dataset.metadata, "num_instances", None),
        "downloaded_records": len(dataframe),
        "columns": list(dataframe.columns),
        "repository_url": config["repository_url"],
        "doi": config["doi"],
        "license": "CC BY 4.0",
        "data_file": config["filename"],
    }

    save_metadata(metadata, "online_retail")

    LOGGER.info("Online Retail downloaded: %s records.", len(dataframe))


def download_online_retail_ii() -> None:
    """Download Online Retail II directly from the official UCI archive."""

    config = DATASETS["online_retail_ii"]

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    archive_path = RAW_DATA_DIR / "online_retail_ii_download.zip"
    workbook_path = RAW_DATA_DIR / "online_retail_II.xlsx"
    csv_path = RAW_DATA_DIR / config["filename"]

    LOGGER.info("Downloading Online Retail II from UCI...")
    LOGGER.info("Source: %s", config["download_url"])

    urllib.request.urlretrieve(config["download_url"], archive_path)

    LOGGER.info("Download complete. Extracting Excel workbook...")

    with zipfile.ZipFile(archive_path, "r") as archive:
        excel_files = [name for name in archive.namelist() if name.lower().endswith(".xlsx")]

        if not excel_files:
            raise FileNotFoundError("No Excel workbook was found in the UCI archive.")

        excel_member = next(
            (name for name in excel_files if Path(name).name.lower() == "online_retail_ii.xlsx"),
            excel_files[0],
        )

        with archive.open(excel_member) as source:
            with workbook_path.open("wb") as destination:
                shutil.copyfileobj(source, destination)

    LOGGER.info("Reading Excel worksheets...")

    sheets = pd.read_excel(
        workbook_path,
        sheet_name=None,
        engine="openpyxl",
    )

    if not sheets:
        raise ValueError("Online Retail II workbook contains no worksheets.")

    # Map UCI Excel workbook headers to our canonical schema.
    source_to_canonical = {
        "Invoice": "InvoiceNo",
        "Price": "UnitPrice",
        "Customer ID": "CustomerID",
    }

    normalized_sheets = {}

    for sheet_name, sheet_dataframe in sheets.items():
        normalized_dataframe = sheet_dataframe.rename(columns=source_to_canonical)

        validate_columns(normalized_dataframe)

        normalized_sheets[sheet_name] = normalized_dataframe

    # Concatenate only after every worksheet has been normalized.
    dataframe = pd.concat(
        normalized_sheets.values(),
        ignore_index=True,
    )

    if dataframe.empty:
        raise ValueError("Online Retail II returned an empty dataset.")

    validate_columns(dataframe)

    LOGGER.info(
        "Combining %s worksheets: %s records.",
        len(sheets),
        len(dataframe),
    )

    dataframe.to_csv(
        csv_path,
        index=False,
        encoding="utf-8",
    )

    metadata = {
        "dataset_name": config["display_name"],
        "uci_id": config["uci_id"],
        "uci_reported_records": 1_067_371,
        "downloaded_records": len(dataframe),
        "columns": list(dataframe.columns),
        "source_worksheets": list(sheets.keys()),
        "repository_url": config["repository_url"],
        "download_url": config["download_url"],
        "doi": config["doi"],
        "license": "CC BY 4.0",
        "source_workbook": workbook_path.name,
        "source_workbook_sha256": calculate_sha256(workbook_path),
        "data_file": config["filename"],
    }

    save_metadata(metadata, "online_retail_ii")

    archive_path.unlink(missing_ok=True)

    LOGGER.info(
        "Online Retail II downloaded successfully: %s records.",
        len(dataframe),
    )
    LOGGER.info("CSV saved to: %s", csv_path)
    LOGGER.info("Original workbook retained at: %s", workbook_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download market intelligence datasets from UCI.")

    parser.add_argument(
        "--dataset",
        choices=[*DATASETS.keys(), "all"],
        default="all",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    if args.dataset in ("online_retail", "all"):
        download_online_retail()

    if args.dataset in ("online_retail_ii", "all"):
        download_online_retail_ii()


if __name__ == "__main__":
    main()
