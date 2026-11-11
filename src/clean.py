"""DWD 明细层：读取 GBK 源文件、清洗、落地。"""
from __future__ import annotations

import re
import sqlite3

import pandas as pd

from config import (
    BOX_LIST,
    ORDER_DETAILS,
    ORDER_LIST,
    bulk_insert,
    mask_mobile,
    read_source,
    to_number,
)

_WS = re.compile(r"\s+")


def _norm_ts(series: pd.Series) -> pd.Series:
    """统一成 YYYY-MM-DD HH:MM:SS 字符串。"""
    ts = pd.to_datetime(series, errors="coerce")
    return ts.dt.strftime("%Y-%m-%d %H:%M:%S")


def clean_product_name(value: object) -> str | None:
    """商品名清洗：去首尾空白、去制表符、压缩内部空白、去引号。"""
    if value is None or pd.isna(value):
        return None
    s = str(value).replace('"', "").replace("\t", " ").strip()
    s = _WS.sub(" ", s)
    if s in {"", "-", "null", "NULL", "None", "nan"}:
        return None
    return s


def build_dwd(conn: sqlite3.Connection) -> dict:
    stats: dict = {}

    ol_raw, enc_ol = read_source(ORDER_LIST)
    od_raw, enc_od = read_source(ORDER_DETAILS)
    bl_raw, enc_bl = read_source(BOX_LIST)
    stats["encodings"] = {"order_list": enc_ol, "order_details": enc_od, "box_list": enc_bl}
    stats["rows_raw"] = {"order_list": len(ol_raw), "order_details": len(od_raw), "box_list": len(bl_raw)}

    # ---------------- 订单头 ----------------
    ol = pd.DataFrame(
        {
            "order_id": ol_raw["id"].astype(str).str.strip(),
            "created_ts": _norm_ts(ol_raw["createdtime"]),
            "customer_id": ol_raw["customerid"].astype(str).str.strip(),
            "mobile_masked": ol_raw["customermobile"].map(mask_mobile),
            "total_price": to_number(ol_raw["totalprice"]),
            "pay_price": to_number(ol_raw["paytotalprice"]),
            "discount_price": to_number(ol_raw["discounttotalprice"]),
            "status": ol_raw["status"].astype(str).str.strip().str.upper(),
            "source": ol_raw["source"].astype(str).str.strip(),
            "order_type": ol_raw["ordertype"].astype(str).str.strip().str.upper(),
            "boxid": ol_raw["boxid"].astype(str).str.strip(),
            "payed_time": _norm_ts(ol_raw["payedtime"]),
            "order_num": ol_raw["ordernum"].astype(str).str.strip(),
            "external_order_num": ol_raw["externalordernum"],
        }
    )
    before = len(ol)
    ol = ol[ol["created_ts"].notna()].copy()
    ol["order_date"] = ol["created_ts"].str.slice(0, 10)
    ol["boxid"] = ol["boxid"].replace({"nan": None, "": None, "None": None})
    ol["customer_id"] = ol["customer_id"].replace({"nan": None, "": None, "None": None})
    stats["order_rows_dropped_bad_ts"] = before - len(ol)
    stats["order_dup_id"] = int(ol["order_id"].duplicated().sum())
    ol = ol.drop_duplicates(subset=["order_id"], keep="first")

    # ---------------- 订单明细 ----------------
    od = pd.DataFrame(
        {
            "created_ts": _norm_ts(od_raw["createdtime"]),
            "customer_id": od_raw["customerid"].astype(str).str.strip(),
            "boxid": od_raw["boxid"].astype(str).str.strip(),
            "order_num": od_raw["ordernum"].astype(str).str.strip(),
            "status": od_raw["status"].astype(str).str.strip().str.upper(),
            "order_type": od_raw["ordertype"].astype(str).str.strip().str.upper(),
            "product_name_raw": od_raw["productname"],
            "product_name": od_raw["productname"].map(clean_product_name),
            "amount": to_number(od_raw["amount"]).fillna(0).astype("int64"),
            "cost_price": to_number(od_raw["costprice"]),
            "sale_price": to_number(od_raw["saleprice"]),
            "total_price": to_number(od_raw["producttotalprice"]),
            "discount_price": to_number(od_raw["productdiscountprice"]),
            "pay_price": to_number(od_raw["productpaytotalprice"]),
        }
    )
    before = len(od)
    od = od[od["created_ts"].notna()].copy()
    od["order_date"] = od["created_ts"].str.slice(0, 10)
    od["boxid"] = od["boxid"].replace({"nan": None, "": None, "None": None})
    od["customer_id"] = od["customer_id"].replace({"nan": None, "": None, "None": None})
    od["product_name_raw"] = od["product_name_raw"].where(od["product_name_raw"].notna(), None)
    od["profit"] = od["pay_price"] - od["amount"] * od["cost_price"] - od["discount_price"]
    od.insert(0, "detail_id", range(1, len(od) + 1))
    stats["item_rows_dropped_bad_ts"] = before - len(od)
    stats["item_null_product"] = int(od["product_name"].isna().sum())

    # ---------------- 原始维表 ----------------
    bl = pd.DataFrame(
        {
            "boxid": bl_raw["boxid"].astype(str).str.strip(),
            "name": bl_raw["name"],
            "address": bl_raw["address"],
            "serial_number": bl_raw["serialnumber"],
            "status": bl_raw["status"].astype(str).str.strip().str.upper(),
            "model_raw": bl_raw["modelnumber"].astype(str).str.strip(),
        }
    )
    bl.to_sql("_raw_machine", conn, if_exists="replace", index=False)

    bulk_insert(conn, "dwd_order", ol)
    bulk_insert(conn, "dwd_order_item", od)
    stats["rows_dwd"] = {"dwd_order": len(ol), "dwd_order_item": len(od)}
    return stats
