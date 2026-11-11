"""ADS 应用层：实验2 的 4 个任务，全部落表 + 导出 CSV。"""
from __future__ import annotations

import sqlite3

import pandas as pd

from config import BUSINESS_ORDER_TYPE, BUSINESS_STATUS, OUT_DIR, bulk_insert


def build_ads(conn: sqlite3.Connection) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stats: dict = {}

    # ---- 任务1：分组聚合客户订单（口径：订单信息表） ----
    cust = pd.read_sql_query(
        f"""
        SELECT customer_id,
               MAX(mobile_masked) AS mobile_masked,
               COUNT(*)           AS order_cnt,
               SUM(pay_price)     AS pay_amount
        FROM dwd_order
        WHERE status = '{BUSINESS_STATUS}' AND customer_id IS NOT NULL
        GROUP BY customer_id
        ORDER BY pay_amount DESC, order_cnt DESC
        """,
        conn,
    )
    cust["pay_amount"] = cust["pay_amount"].round(2)
    bulk_insert(conn, "ads_customer_rank", cust)
    stats["ads_customer_rank"] = len(cust)

    # ---- 任务2：计算各商品销售金额（口径：订单详情表） ----
    prod = pd.read_sql_query(
        f"""
        SELECT product_name,
               SUM(amount)    AS qty,
               SUM(pay_price) AS sales_amount
        FROM dwd_order_item
        WHERE status = '{BUSINESS_STATUS}'
          AND order_type = '{BUSINESS_ORDER_TYPE}'
          AND product_name IS NOT NULL
        GROUP BY product_name
        ORDER BY sales_amount DESC
        """,
        conn,
    )
    prod["sales_amount"] = prod["sales_amount"].round(2)
    bulk_insert(conn, "ads_product_sales", prod)
    stats["ads_product_sales"] = len(prod)

    # ---- 任务3：统计各售货机日销售金额 ----
    daily = pd.read_sql_query(
        f"""
        SELECT boxid,
               order_date AS sale_date,
               SUM(pay_price) AS sales_amount
        FROM dwd_order_item
        WHERE status = '{BUSINESS_STATUS}'
          AND order_type = '{BUSINESS_ORDER_TYPE}'
          AND boxid IS NOT NULL
        GROUP BY boxid, order_date
        ORDER BY boxid, sale_date
        """,
        conn,
    )
    daily["sales_amount"] = daily["sales_amount"].round(2)
    bulk_insert(conn, "ads_machine_daily", daily)
    stats["ads_machine_daily"] = len(daily)

    # ---- 任务4：整理各售货机情况（利润 + 客单价） ----
    mach = pd.read_sql_query(
        f"""
        SELECT i.boxid,
               COALESCE(m.name, '未知售货机')  AS machine_name,
               COALESCE(m.address, '')         AS address,
               SUM(i.profit)                   AS profit,
               COUNT(DISTINCT i.order_num)     AS order_cnt,
               SUM(i.pay_price)                AS sales_amount
        FROM dwd_order_item i
        LEFT JOIN dim_machine m ON m.boxid = i.boxid
        WHERE i.status = '{BUSINESS_STATUS}'
          AND i.order_type = '{BUSINESS_ORDER_TYPE}'
          AND i.boxid IS NOT NULL
        GROUP BY i.boxid
        ORDER BY profit DESC
        """,
        conn,
    )
    mach["profit"] = mach["profit"].round(2)
    mach["sales_amount"] = mach["sales_amount"].round(2)
    mach["avg_order_value"] = (mach["sales_amount"] / mach["order_cnt"]).round(2)
    mach = mach[["boxid", "machine_name", "address", "profit", "order_cnt",
                 "sales_amount", "avg_order_value"]]
    bulk_insert(conn, "ads_machine_profit", mach)
    stats["ads_machine_profit"] = len(mach)

    # ---- 导出 ----
    for table, df in [
        ("ads_customer_rank", cust),
        ("ads_product_sales", prod),
        ("ads_machine_daily", daily),
        ("ads_machine_profit", mach),
    ]:
        df.to_csv(OUT_DIR / f"{table}.csv", index=False, encoding="utf-8-sig")

    stats["_frames"] = {"cust": cust, "prod": prod, "daily": daily, "mach": mach}
    return stats
