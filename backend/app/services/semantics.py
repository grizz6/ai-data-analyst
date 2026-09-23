"""Work out what a column means, not just its dtype.

An order number stored as an integer is still an identifier. Averaging it,
correlating it, or flagging its "outliers" produces numbers that look
precise and mean nothing, so identifiers are kept out of the statistics.
"""

import re

import pandas as pd

# Any word equal to "id" marks an identifier: customer_id, customerId, "Order ID", id_number.
ID_WORDS = {"id"}
# These only count as the last word: product_sku, zip, postcode, phone, api_key, uuid.
ID_SUFFIX_WORDS = {"uuid", "guid", "key", "sku", "zip", "zipcode", "postcode", "phone"}
# A whole-number column that counts 1, 2, 3... with no gaps is a row number.
MIN_ROWS_FOR_ROW_COUNTER = 20

_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def name_words(name: str) -> list[str]:
    """Split snake_case, camelCase, and spaced names into lowercase words."""
    return [w.lower() for w in _WORD.findall(str(name))]


def looks_like_identifier_name(name: str) -> bool:
    words = name_words(name)
    if not words:
        return False
    return any(w in ID_WORDS for w in words) or words[-1] in ID_SUFFIX_WORDS


def is_row_counter(series: pd.Series) -> bool:
    values = series.dropna()
    if len(values) < MIN_ROWS_FOR_ROW_COUNTER or not pd.api.types.is_numeric_dtype(values):
        return False
    if pd.api.types.is_bool_dtype(values) or not (values % 1 == 0).all():
        return False
    return values.is_unique and values.max() - values.min() == len(values) - 1


def identifier_columns(df: pd.DataFrame) -> list[str]:
    return [
        str(col)
        for col in df.columns
        if looks_like_identifier_name(col) or is_row_counter(df[col])
    ]


# ---------------------------------------------------------------------------
# Categories: text whose values repeat.
# ---------------------------------------------------------------------------

# Past this many distinct values, and with most rows unique, a text column is a
# name or free text rather than a category.
CATEGORY_MAX_UNIQUE = 50
CATEGORY_MAX_UNIQUE_SHARE = 0.5


def is_categorical(series: pd.Series) -> bool:
    values = series.dropna()
    unique = values.nunique()
    if unique < 2:
        return False
    return unique <= CATEGORY_MAX_UNIQUE or unique / len(values) <= CATEGORY_MAX_UNIQUE_SHARE


def label_key(value: str) -> str:
    """How a person reads a label: case, surrounding spaces, and doubled spaces don't matter."""
    return " ".join(str(value).split()).casefold()


def label_variants(series: pd.Series) -> dict[str, list[str]]:
    """Labels written more than one way, keyed by the most common spelling.

    Only exact case and whitespace differences count. "NY" and "New York" are
    left alone, because deciding those are the same needs knowledge this code
    doesn't have.
    """
    counts = series.dropna().astype(str).value_counts()
    groups: dict[str, list[str]] = {}
    for spelling in counts.index:  # most common first
        groups.setdefault(label_key(spelling), []).append(spelling)
    return {spellings[0]: spellings for spellings in groups.values() if len(spellings) > 1}


# ---------------------------------------------------------------------------
# Numbers stored as text: "$1,200", "45%", "(300)", " 12.5 ".
# ---------------------------------------------------------------------------

_NUMERIC_TEXT = re.compile(r"^[-+]?\(?[-+]?[$€£¥]?\s*\d[\d,]*(\.\d+)?\s*%?\)?$")
_LEADING_ZERO = re.compile(r"^0\d")
# Share of the non-empty values that must look numeric before converting. The rest
# ("N/A", "-", "unknown") become missing, which is what they mean.
NUMERIC_TEXT_THRESHOLD = 0.9


def parse_numeric_text(series: pd.Series) -> pd.Series | None:
    """The column as numbers if it is numbers stored as text, otherwise None.

    Currency symbols, thousands separators and % are stripped (45% becomes 45),
    and accounting-style (300) becomes -300. Text with leading zeros such as
    "00123" is left alone: that's a code, and converting would destroy it.
    """
    if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
        return None
    text = series.dropna().astype(str).str.strip()
    text = text[text != ""]
    if text.empty or text.str.match(_LEADING_ZERO).any():
        return None
    looks_numeric = text.str.match(_NUMERIC_TEXT)
    if looks_numeric.mean() < NUMERIC_TEXT_THRESHOLD:
        return None

    def to_number(value) -> float | None:
        if pd.isna(value):
            return None
        raw = str(value).strip()
        if not _NUMERIC_TEXT.match(raw):
            return None
        negative = raw.startswith("(") and raw.endswith(")")
        digits = re.sub(r"[()$€£¥,%\s]", "", raw)
        try:
            number = float(digits)
        except ValueError:
            return None
        return -number if negative else number

    return series.map(to_number).astype("float64")
