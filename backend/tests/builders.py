"""Dataset builders with defects planted at known positions.

Each test asserts the pipeline finds exactly what was planted, no more and
no less.
"""

from io import BytesIO

import numpy as np
import pandas as pd


def workbook(**sheets: pd.DataFrame) -> bytes:
    """An .xlsx file with one sheet per keyword argument, in order."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
    return buffer.getvalue()


def with_nulls(n: int, null_count: int) -> list[float | None]:
    """A numeric column of length n whose first `null_count` values are missing."""
    return [None] * null_count + [float(i) for i in range(n - null_count)]


def correlated_pair(n: int, r: float, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Two columns whose sample Pearson correlation is exactly r.

    The noise vector is orthogonalized against x before mixing, so the
    result does not depend on the random draw.
    """
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    e = rng.normal(size=n)
    x = (x - x.mean()) / x.std()
    e = e - e.mean()
    e = e - (e @ x) / (x @ x) * x
    e = e / e.std()
    y = r * x + np.sqrt(1 - r**2) * e
    return x, y


def with_outliers(n_normal: int, outliers: list[float], seed: int = 0) -> list[float]:
    """Values uniform in [40, 60] plus the given outliers appended at the end.

    Tukey fences for the uniform part sit near 30 and 70, so anything far
    outside that range is an outlier and nothing inside it is.
    """
    rng = np.random.default_rng(seed)
    return list(rng.uniform(40, 60, size=n_normal)) + outliers


def weekly_series(first_half: float, second_half: float, weeks: int = 20) -> pd.DataFrame:
    dates = pd.date_range("2024-01-07", periods=weeks, freq="W")
    values = [first_half] * (weeks // 2) + [second_half] * (weeks - weeks // 2)
    return pd.DataFrame({"date": dates, "sales": values})
