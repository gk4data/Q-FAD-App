import os
from datetime import datetime
from pathlib import Path

def save_to_csv(df, base_dir=None, prefix='stockrsi2'):
    if base_dir is None:
        base_dir = Path.home() / "Trading" / "Backend Data"
    else:
        base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    if 'Date' in df.columns and len(df) > 0:
        date_str = df['Date'].dt.date.iloc[0].strftime('%d%m%Y')
    else:
        date_str = datetime.now().strftime('%d%m%Y')

    filename = base_dir / f"{prefix}_{date_str}.csv"
    df.to_csv(filename, index=False)
    return str(filename)
