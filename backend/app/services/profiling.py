import pandas as pd

from app.models.schemas import ColumnProfile


def profile_columns(df: pd.DataFrame) -> list[ColumnProfile]:
    profiles: list[ColumnProfile] = []
    n = len(df)

    for col in df.columns:
        series = df[col]
        null_count = int(series.isna().sum())
        non_null = n - null_count
        unique_count = int(series.nunique(dropna=True))
        samples = (
            series.dropna()
            .astype(str)
            .head(5)
            .tolist()
        )

        profiles.append(
            ColumnProfile(
                name=str(col),
                dtype=str(series.dtype),
                non_null_count=non_null,
                null_count=null_count,
                null_pct=round((null_count / n) * 100, 2) if n else 0.0,
                unique_count=unique_count,
                sample_values=samples,
            )
        )

    return profiles
