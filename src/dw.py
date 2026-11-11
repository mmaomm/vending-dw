"""维度与事实：星型模型构建（含商品 SCD2）。"""
from __future__ import annotations

import sqlite3

import pandas as pd

from config import BUSINESS_ORDER_TYPE, BUSINESS_STATUS, CURRENT_FLAG, MODEL_NORMALIZE, bulk_insert


def build_dim_date(conn: sqlite3.Connection) -> int:
    rng = pd.read_sql_query(
        "SELECT MIN(order_date) AS lo, MAX(order_date) AS hi FROM dwd_order", conn
    ).iloc[0]
    days = pd.date_range(rng["lo"], rng["hi"], freq="D")
    df = pd.DataFrame({"full_date": days.strftime("%Y-%m-%d")})
    df["date_key"] = days.strftime("%Y%m%d").astype(int)
    df["year"] = days.year
    df["month"] = days.month
    df["day"] = days.day
    df["quarter"] = days.quarter
    df["weekday_num"] = days.weekday
    df["weekday_name"] = days.day_name().map(
        {"Monday": "周一", "Tuesday": "周二", "Wednesday": "周三", "Thursday": "周四",
         "Friday": "周五", "Saturday": "周六", "Sunday": "周日"}
    )
    df["is_weekend"] = (days.weekday >= 5).astype(int)
    df = df[["date_key", "full_date", "year", "month", "day", "quarter",
             "weekday_num", "weekday_name", "is_weekend"]]
    return bulk_insert(conn, "dim_date", df)


def build_dim_product(conn: sqlite3.Connection) -> int:
    """商品维，SCD2：同一商品不同售价视为不同版本。"""
    q = f"""
        SELECT product_name, sale_price, MIN(created_ts) AS first_seen
        FROM dwd_order_item
        WHERE status = '{BUSINESS_STATUS}'
          AND order_type = '{BUSINESS_ORDER_TYPE}'
          AND product_name IS NOT NULL
        GROUP BY product_name, sale_price
        ORDER BY product_name, first_seen
    """
    df = pd.read_sql_query(q, conn)
    if df.empty:
        return 0
    df["valid_from"] = df["first_seen"].str.slice(0, 10)
    df = df.sort_values(["product_name", "valid_from"]).reset_index(drop=True)
    df["valid_to"] = df.groupby("product_name")["valid_from"].shift(-1)
    df["is_current"] = df["valid_to"].isna().astype(int)
    df["valid_to"] = df["valid_to"].fillna(CURRENT_FLAG)
    df["product_key"] = range(1, len(df) + 1)
    df = df[["product_key", "product_name", "sale_price", "valid_from", "valid_to", "is_current"]]
    return bulk_insert(conn, "dim_product", df)


def build_dim_machine(conn: sqlite3.Connection) -> dict:
    """售货机维：以 box_list 为基准，补齐订单里出现但维表缺失的机器。"""
    bl = pd.read_sql_query("SELECT * FROM _raw_machine", conn)
    bl["model_norm"] = bl["model_raw"].map(MODEL_NORMALIZE).fillna(bl["model_raw"])
    bl["city"] = bl["address"].fillna("").str.extract(r"省(.*?)市", expand=False)
    bl["is_orphan"] = 0

    known = set(bl["boxid"])
    used = pd.read_sql_query(
        "SELECT DISTINCT boxid FROM dwd_order WHERE boxid IS NOT NULL", conn
    )["boxid"]
    orphans = [b for b in used if b not in known]
    if orphans:
        extra = pd.DataFrame({
            "boxid": orphans,
            "name": "未知售货机（维表缺失）",
            "address": None,
            "serial_number": None,
            "status": "UNKNOWN",
            "model_raw": None,
            "model_norm": None,
            "city": None,
            "is_orphan": 1,
        })
        bl = pd.concat([bl, extra], ignore_index=True)

    bl = bl.drop_duplicates(subset=["boxid"], keep="first").reset_index(drop=True)
    bl["machine_key"] = range(1, len(bl) + 1)
    bl = bl[["machine_key", "boxid", "name", "address", "city", "model_raw",
             "model_norm", "status", "serial_number", "is_orphan"]]
    bulk_insert(conn, "dim_machine", bl)
    return {"machine_total": len(bl), "machine_orphan": int(bl["is_orphan"].sum())}


def build_dim_customer(conn: sqlite3.Connection) -> int:
    q = f"""
        SELECT customer_id,
               MAX(mobile_masked)  AS mobile_masked,
               MIN(order_date)     AS first_order_date,
               MAX(order_date)     AS last_order_date,
               COUNT(*)            AS order_cnt,
               SUM(pay_price)      AS total_pay
        FROM dwd_order
        WHERE status = '{BUSINESS_STATUS}' AND customer_id IS NOT NULL
        GROUP BY customer_id
    """
    df = pd.read_sql_query(q, conn)
    if df.empty:
        return 0
    df = df.sort_values("customer_id").reset_index(drop=True)
    df["customer_key"] = range(1, len(df) + 1)
    df = df[["customer_key", "customer_id", "mobile_masked", "first_order_date",
             "last_order_date", "order_cnt", "total_pay"]]
    return bulk_insert(conn, "dim_customer", df)


def build_fact(conn: sqlite3.Connection) -> int:
    """事实表：粒度 = 订单行。只保留支付成功的购物订单且商品名非空。"""
    q = f"""
        SELECT i.detail_id, i.order_num, i.order_date, i.created_ts,
               i.product_name, i.sale_price, i.amount,
               i.total_price, i.pay_price, i.discount_price, i.cost_price, i.profit,
               i.boxid, i.customer_id
        FROM dwd_order_item i
        WHERE i.status = '{BUSINESS_STATUS}'
          AND i.order_type = '{BUSINESS_ORDER_TYPE}'
          AND i.product_name IS NOT NULL
    """
    df = pd.read_sql_query(q, conn)
    if df.empty:
        return 0

    prod = pd.read_sql_query(
        "SELECT product_key, product_name, sale_price, valid_from, valid_to FROM dim_product", conn
    )
    df = df.merge(prod, on=["product_name", "sale_price"], how="left")
    # 若价格在该版本区间外（极少见），回退到该商品的当前版本
    if df["product_key"].isna().any():
        cur = prod[prod["valid_to"] == CURRENT_FLAG][["product_name", "product_key"]]
        cur = cur.rename(columns={"product_key": "product_key_fb"})
        df = df.merge(cur, on="product_name", how="left")
        df["product_key"] = df["product_key"].fillna(df["product_key_fb"])
        df = df.drop(columns=[c for c in ["product_key_fb"] if c in df.columns])

    mach = pd.read_sql_query("SELECT machine_key, boxid FROM dim_machine", conn)
    cust = pd.read_sql_query("SELECT customer_key, customer_id FROM dim_customer", conn)
    df = df.merge(mach, on="boxid", how="left").merge(cust, on="customer_id", how="left")

    df["date_key"] = df["order_date"].str.replace("-", "", regex=False).astype(int)
    df["fact_key"] = range(1, len(df) + 1)
    out = df[["fact_key", "order_num", "order_date", "date_key", "product_key",
              "machine_key", "customer_key", "amount", "total_price", "pay_price",
              "discount_price", "cost_price", "profit"]].rename(columns={"amount": "quantity"})
    return bulk_insert(conn, "fact_order_item", out)


def build_dw(conn: sqlite3.Connection) -> dict:
    stats = {"dim_date": build_dim_date(conn)}
    stats["dim_product"] = build_dim_product(conn)
    stats.update(build_dim_machine(conn))
    stats["dim_customer"] = build_dim_customer(conn)
    stats["fact_order_item"] = build_fact(conn)
    return stats
