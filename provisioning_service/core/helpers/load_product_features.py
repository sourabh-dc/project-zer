"""
Load Product Features from Excel

This script reads product_postgres.xlsx and populates the following tables:
- colours
- sizes
- fits
- uos_labels
- colour_groups
"""

import os
import uuid
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from provisioning_service.Models import Colour, Size, Fit, UosLabel, ColourGroup
from provisioning_service.core.db_config import SessionLocal
from provisioning_service.utils.logger import logger


# Path to the Excel file
EXCEL_FILE_PATH = Path(__file__).parent.parent.parent / "product_postgres.xlsx"


def load_colours(db: Session, df: pd.DataFrame) -> int:
    """Load colours from DataFrame into database"""
    count = 0
    for _, row in df.iterrows():
        try:
            # Check if colour already exists by source_internal_id or name
            source_id = str(row.get('source_internal_id', '')).strip() if pd.notna(row.get('source_internal_id')) else None
            name = str(row.get('name', '')).strip() if pd.notna(row.get('name')) else None

            if not name:
                continue

            existing = None
            if source_id:
                existing = db.query(Colour).filter(Colour.source_internal_id == source_id).first()
            if not existing and name:
                existing = db.query(Colour).filter(Colour.name == name).first()

            if existing:
                # Update existing record
                existing.name = name
                existing.abbreviation = str(row.get('abbreviation', '')).strip() if pd.notna(row.get('abbreviation')) else None
                existing.colour_group = str(row.get('colour_group', '')).strip() if pd.notna(row.get('colour_group')) else None
                existing.source_internal_id = source_id
            else:
                # Create new record
                colour = Colour(
                    colour_id=uuid.uuid4(),
                    name=name,
                    abbreviation=str(row.get('abbreviation', '')).strip() if pd.notna(row.get('abbreviation')) else None,
                    colour_group=str(row.get('colour_group', '')).strip() if pd.notna(row.get('colour_group')) else None,
                    source_internal_id=source_id
                )
                db.add(colour)
                count += 1
        except Exception as e:
            logger.error(f"Error loading colour row: {e}")
            continue

    db.commit()
    return count


def load_sizes(db: Session, df: pd.DataFrame) -> int:
    """Load sizes from DataFrame into database"""
    count = 0
    for _, row in df.iterrows():
        try:
            source_id = str(row.get('source_internal_id', '')).strip() if pd.notna(row.get('source_internal_id')) else None
            name = str(row.get('name', '')).strip() if pd.notna(row.get('name')) else None

            if not name:
                continue

            existing = None
            if source_id:
                existing = db.query(Size).filter(Size.source_internal_id == source_id).first()
            if not existing and name:
                existing = db.query(Size).filter(Size.name == name).first()

            if existing:
                existing.name = name
                existing.abbreviation = str(row.get('abbreviation', '')).strip() if pd.notna(row.get('abbreviation')) else None
                existing.sort_order = int(row.get('sort_order', 0)) if pd.notna(row.get('sort_order')) else 0
                existing.source_internal_id = source_id
            else:
                size = Size(
                    size_id=uuid.uuid4(),
                    name=name,
                    abbreviation=str(row.get('abbreviation', '')).strip() if pd.notna(row.get('abbreviation')) else None,
                    sort_order=int(row.get('sort_order', 0)) if pd.notna(row.get('sort_order')) else 0,
                    source_internal_id=source_id
                )
                db.add(size)
                count += 1
        except Exception as e:
            logger.error(f"Error loading size row: {e}")
            continue

    db.commit()
    return count


def load_fits(db: Session, df: pd.DataFrame) -> int:
    """Load fits from DataFrame into database"""
    count = 0
    for _, row in df.iterrows():
        try:
            name = str(row.get('name', '')).strip() if pd.notna(row.get('name')) else None

            if not name:
                continue

            existing = db.query(Fit).filter(Fit.name == name).first()

            if existing:
                existing.active = bool(row.get('active', True)) if pd.notna(row.get('active')) else True
            else:
                fit = Fit(
                    fit_id=uuid.uuid4(),
                    name=name,
                    active=bool(row.get('active', True)) if pd.notna(row.get('active')) else True
                )
                db.add(fit)
                count += 1
        except Exception as e:
            logger.error(f"Error loading fit row: {e}")
            continue

    db.commit()
    return count


def load_uos_labels(db: Session, df: pd.DataFrame) -> int:
    """Load UOS labels from DataFrame into database"""
    count = 0
    for _, row in df.iterrows():
        try:
            name = str(row.get('name', '')).strip() if pd.notna(row.get('name')) else None
            source_id = str(row.get('source_id', '')).strip() if pd.notna(row.get('source_id')) else None

            if not name:
                continue

            existing = None
            if source_id:
                existing = db.query(UosLabel).filter(UosLabel.source_id == source_id).first()
            if not existing and name:
                existing = db.query(UosLabel).filter(UosLabel.name == name).first()

            if existing:
                existing.name = name
                existing.label_type = str(row.get('label_type', '')).strip() if pd.notna(row.get('label_type')) else None
                existing.source_id = source_id
            else:
                label = UosLabel(
                    name=name,
                    label_type=str(row.get('label_type', '')).strip() if pd.notna(row.get('label_type')) else None,
                    source_id=source_id
                )
                db.add(label)
                count += 1
        except Exception as e:
            logger.error(f"Error loading UOS label row: {e}")
            continue

    db.commit()
    return count


def load_colour_groups(db: Session, df: pd.DataFrame) -> int:
    """Load colour groups from DataFrame into database"""
    count = 0
    for _, row in df.iterrows():
        try:
            colour_name = str(row.get('colour_name', '')).strip() if pd.notna(row.get('colour_name')) else None
            colour_group = str(row.get('colour_group', '')).strip() if pd.notna(row.get('colour_group')) else None

            if not colour_name or not colour_group:
                continue

            existing = db.query(ColourGroup).filter(
                ColourGroup.colour_name == colour_name,
                ColourGroup.colour_group == colour_group
            ).first()

            if not existing:
                cg = ColourGroup(
                    colour_name=colour_name,
                    colour_group=colour_group
                )
                db.add(cg)
                count += 1
        except Exception as e:
            logger.error(f"Error loading colour group row: {e}")
            continue

    db.commit()
    return count


def load_all_product_features(excel_path: Optional[str] = None) -> dict:
    """
    Load all product features from Excel file.

    Args:
        excel_path: Optional path to Excel file. Defaults to product_postgres.xlsx

    Returns:
        Dictionary with counts of loaded records per table
    """
    file_path = Path(excel_path) if excel_path else EXCEL_FILE_PATH

    if not file_path.exists():
        logger.error(f"Excel file not found: {file_path}")
        raise FileNotFoundError(f"Excel file not found: {file_path}")

    logger.info(f"Loading product features from: {file_path}")

    results = {
        "colours": 0,
        "sizes": 0,
        "fits": 0,
        "uos_labels": 0,
        "colour_groups": 0
    }

    try:
        # Read all sheets from Excel
        excel_file = pd.ExcelFile(file_path)
        sheet_names = excel_file.sheet_names
        logger.info(f"Found sheets: {sheet_names}")

        with SessionLocal() as db:
            # Load colours
            if 'colours' in sheet_names:
                df_colours = pd.read_excel(excel_file, sheet_name='colours')
                results["colours"] = load_colours(db, df_colours)
                logger.info(f"Loaded {results['colours']} new colours")
            else:
                logger.warning("Sheet 'colours' not found in Excel file")

            # Load sizes
            if 'sizes' in sheet_names:
                df_sizes = pd.read_excel(excel_file, sheet_name='sizes')
                results["sizes"] = load_sizes(db, df_sizes)
                logger.info(f"Loaded {results['sizes']} new sizes")
            else:
                logger.warning("Sheet 'sizes' not found in Excel file")

            # Load fits
            if 'fits' in sheet_names:
                df_fits = pd.read_excel(excel_file, sheet_name='fits')
                results["fits"] = load_fits(db, df_fits)
                logger.info(f"Loaded {results['fits']} new fits")
            else:
                logger.warning("Sheet 'fits' not found in Excel file")

            # Load UOS labels
            if 'uos_labels' in sheet_names:
                df_uos = pd.read_excel(excel_file, sheet_name='uos_labels')
                results["uos_labels"] = load_uos_labels(db, df_uos)
                logger.info(f"Loaded {results['uos_labels']} new UOS labels")
            else:
                logger.warning("Sheet 'uos_labels' not found in Excel file")

            # Load colour groups
            if 'colour_groups_ref' in sheet_names:
                df_cg = pd.read_excel(excel_file, sheet_name='colour_groups_ref')
                results["colour_groups"] = load_colour_groups(db, df_cg)
                logger.info(f"Loaded {results['colour_groups']} new colour groups")
            else:
                logger.warning("Sheet 'colour_groups' not found in Excel file")

        logger.info(f"Product features loading complete: {results}")
        return results

    except Exception as e:
        logger.error(f"Error loading product features: {e}")
        raise


def load_product_features_on_startup():
    """
    Load product features on application startup.
    Call this function from main.py during app initialization.
    """
    try:
        results = load_all_product_features()
        total = sum(results.values())
        if total > 0:
            logger.info(f"Loaded {total} new product feature records on startup")
        else:
            logger.info("No new product feature records to load (all already exist)")
        return results
    except FileNotFoundError:
        logger.warning("Product features Excel file not found, skipping load")
        return None
    except Exception as e:
        logger.error(f"Failed to load product features on startup: {e}")
        return None


# CLI entry point
if __name__ == "__main__":
    import sys

    print("Loading product features from Excel...")

    # Allow custom path from command line
    custom_path = sys.argv[1] if len(sys.argv) > 1 else None

    try:
        results = load_all_product_features(custom_path)
        print("\n=== Loading Complete ===")
        print(f"Colours:       {results['colours']} new records")
        print(f"Sizes:         {results['sizes']} new records")
        print(f"Fits:          {results['fits']} new records")
        print(f"UOS Labels:    {results['uos_labels']} new records")
        print(f"Colour Groups: {results['colour_groups']} new records")
        print(f"Total:         {sum(results.values())} new records")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

