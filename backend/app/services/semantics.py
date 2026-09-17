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
