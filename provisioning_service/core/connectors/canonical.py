"""
Canonical identity resolution (deck slice 3).

Deterministic first, AI-assist later:
- normalize_name(): strip legal suffixes/punctuation, fold accents, uppercase
- confidence scoring: exact normalized match = 100, token-overlap fuzzy = 0-99
- below REVIEW_THRESHOLD → review queue, never auto-canonical (deck rule)

AI extraction/classification plugs in at ``extract_attributes`` — kept
deterministic here; the LLM never invents prices, qty, ids, or spend.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, Optional, Tuple

REVIEW_THRESHOLD = 85      # below this → review queue
AUTO_MATCH_THRESHOLD = 97  # at/above this → auto-link (exact-ish)

_LEGAL_SUFFIXES = {
    "ltd", "limited", "ltd.", "plc", "llc", "inc", "inc.", "gmbh", "sarl",
    "oy", "oyj", "ab", "bv", "b.v.", "sa", "s.a.", "ag", "co", "co.",
    "company", "corp", "corporation", "uk", "group", "holdings",
}


def normalize_name(name: str) -> str:
    """'METSÄ TISSUE LTD' / 'Metsa Tissue' / 'metsa tissue oy' → 'METSA TISSUE'."""
    if not name:
        return ""
    # Fold accents: ä→a, ö→o, ü→u
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    folded = re.sub(r"[^a-zA-Z0-9 ]", " ", folded)
    tokens = [t for t in folded.upper().split() if t.lower() not in _LEGAL_SUFFIXES]
    return " ".join(tokens)


def match_confidence(candidate_norm: str, existing_norm: str) -> int:
    """0-100 confidence that two normalized names are the same entity."""
    if not candidate_norm or not existing_norm:
        return 0
    if candidate_norm == existing_norm:
        return 100
    ratio = SequenceMatcher(None, candidate_norm, existing_norm).ratio()
    # Token overlap bonus: shared distinctive tokens lift confidence
    cand_tokens = set(candidate_norm.split())
    exist_tokens = set(existing_norm.split())
    if cand_tokens and exist_tokens:
        overlap = len(cand_tokens & exist_tokens) / max(len(cand_tokens), len(exist_tokens))
        ratio = max(ratio, overlap * 0.95)
    return int(round(ratio * 100))


def extract_attributes(description: str) -> Dict[str, Any]:
    """Deterministic attribute extraction from a raw item description.

    'NIT GLOVE BLU PF LG' → {material: nitrile, colour: blue,
    powder_free: True, size: L}. AI-assist plugs in here later — same
    output shape, confidence attached per attribute.
    """
    attrs: Dict[str, Any] = {}
    if not description:
        return attrs
    tokens = description.upper().split()
    text = " ".join(tokens)

    materials = {"NIT": "nitrile", "LAT": "latex", "VIN": "vinyl", "PE": "polyethylene"}
    for tok, mat in materials.items():
        if tok in tokens:
            attrs["material"] = mat
            break

    colours = {"BLU": "blue", "BLK": "black", "WHT": "white", "CLR": "clear", "GRN": "green"}
    for tok, col in colours.items():
        if tok in tokens:
            attrs["colour"] = col
            break

    if "PF" in tokens or "POWDER FREE" in text or "POWDER-FREE" in text:
        attrs["powder_free"] = True

    for size in ("XS", "S", "M", "L", "XL", "XXL"):
        if size in tokens:
            attrs["size"] = size
            break

    return attrs


def classify(attrs: Dict[str, Any], description: str) -> Optional[str]:
    """Best-effort category from extracted attributes + keywords."""
    text = (description or "").upper()
    if attrs.get("material") in ("nitrile", "latex", "vinyl") or "GLOVE" in text:
        return "Personal Protective Equipment"
    if "PAPER" in text or "A4" in text:
        return "Office Supplies"
    if "PEN" in text or "PENCIL" in text:
        return "Office Supplies"
    if "CLEAN" in text or "SPRAY" in text or "DETERGENT" in text:
        return "Cleaning & Janitorial"
    if "TOWEL" in text or "TISSUE" in text:
        return "Hygiene & Washroom"
    return None
