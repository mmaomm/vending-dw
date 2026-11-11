"""项目配置与数据库工具函数。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "out"
DOCS_DIR = ROOT / "docs"
SQL_DIR = ROOT / "sql"
DB_PATH = ROOT / "data" / "dw.db"

ORDER_LIST = RAW_DIR / "order_list.csv"
ORDER_DETAILS = RAW_DIR / "order_details.csv"
BOX_LIST = RAW_DIR / "box_list.csv"

# 源文件实际是 GBK；按顺序探测，兼容未来换成 UTF-8 的情况
ENCODINGS = ("utf-8-sig", "gb18030")

# 售货机型号的 5 种写法归一
MODEL_NORMALIZE = {
    "MA650-A": "MA650-A",
    "MA650A": "MA650-A",
    "MA-650A": "MA650-A",
    "MA650": "MA650-A",
    "MA": "MA650-A",
}

# 业务口径：只有“支付成功”的“购物订单”才计入事实
BUSINESS_STATUS = "SUCCESS"
BUSINESS_ORDER_TYPE = "SHOPPING"

CURRENT_FLAG = "9999-12-31"


def connect() -> sqlite3.Connection:
    """连接（必要时创建）数据仓库。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """执行 sql/schema.sql 建表。"""
    conn.executescript((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.commit()


def bulk_insert(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> int:
    """把 DataFrame 按列名批量写入表，返回写入行数。"""
    if df is None or df.empty:
        return 0
    cols = [c for c in df.columns]
    placeholders = ",".join("?" * len(cols))
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
    rows = [tuple(None if pd.isna(v) else v for v in rec) for rec in df[cols].itertuples(index=False, name=None)]
    conn.executemany(sql, rows)
    conn.commit()
    return len(rows)


def read_source(path: Path, **kwargs) -> tuple[pd.DataFrame, str]:
    """按探测到的编码读取源 CSV，返回 (DataFrame, 实际编码)。"""
    last_err: Exception | None = None
    for enc in ENCODINGS:
        try:
            df = pd.read_csv(path, dtype=str, encoding=enc, low_memory=False, **kwargs)
            # 抽样校验：确保解码没有产生替换字符
            sample = "".join(str(x) for x in df.head(50).values.ravel())[:5000]
            if "\ufffd" not in sample:
                return df, enc
        except (UnicodeDecodeError, UnicodeError) as exc:  # noqa: PERF203
            last_err = exc
            continue
    raise RuntimeError(f"无法解码 {path.name}，最后一次错误：{last_err}")


def to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def mask_mobile(value: object) -> str | None:
    """手机号脱敏：138****8888。"""
    if value is None or pd.isna(value):
        return None
    s = str(value).strip().replace('"', "").replace("'", "")
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return None
    if len(digits) >= 11:
        return f"{digits[:3]}****{digits[-4:]}"
    if len(digits) > 4:
        return f"{digits[:3]}****{digits[-2:]}"
    return "****"
