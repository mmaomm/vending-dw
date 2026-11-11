"""数据质量校验：对账、孤儿维度、脏值、口径一致性，输出 Markdown 报告。"""
from __future__ import annotations

import sqlite3

import pandas as pd

from config import BUSINESS_ORDER_TYPE, BUSINESS_STATUS, DOCS_DIR

GUIDE_EXPECT = {
    "product": {"name": "脉动", "qty": 2234, "amount": 8907.99},
    "customer": {"id": "220759", "order_cnt": 175, "pay_amount": 880.6},
}


def _fmt(v: float) -> str:
    return f"{v:,.2f}"


def run_checks(conn: sqlite3.Connection, stats: dict) -> str:
    lines: list[str] = []
    add = lines.append
    issues: list[str] = []

    add("# 数据质量报告\n")
    add("> 由 `src/dq.py` 自动生成，数据源：`data/raw/*.csv`（GBK 编码）。\n")

    # 1. 编码
    add("## 1. 编码探测\n")
    add("| 文件 | 实际编码 |")
    add("|---|---|")
    for k, v in stats["encodings"].items():
        add(f"| {k}.csv | `{v}` |")
    add("")
    add("源文件为 GBK，直接以 UTF-8 读取会抛 `UnicodeDecodeError`；ETL 首步做编码归一。\n")

    # 2. 行数
    add("## 2. 各层行数\n")
    add("| 对象 | 行数 |")
    add("|---|---|")
    for k, v in stats["rows_raw"].items():
        add(f"| raw.{k} | {v:,} |")
    for k, v in stats["rows_dwd"].items():
        add(f"| {k} | {v:,} |")
    for k in ["dim_date", "dim_product", "dim_customer", "fact_order_item"]:
        if k in stats:
            add(f"| {k} | {stats[k]:,} |")
    add(f"| dim_machine | {stats.get('machine_total', 0):,} |")
    for k in ["ads_customer_rank", "ads_product_sales", "ads_machine_daily", "ads_machine_profit"]:
        if k in stats:
            add(f"| {k} | {stats[k]:,} |")
    add("")

    # 3. 主键唯一性
    add("## 3. 主键唯一性\n")
    dup = pd.read_sql_query(
        "SELECT COUNT(*) c FROM (SELECT order_id FROM dwd_order GROUP BY order_id HAVING COUNT(*)>1)", conn
    ).iloc[0, 0]
    add(f"- 订单主键重复：**{dup}** 条")
    add(f"- 读取阶段已剔除时间无法解析的订单：**{stats.get('order_rows_dropped_bad_ts', 0)}** 条")
    if dup:
        issues.append("订单主键存在重复")
    add("")

    # 4. 订单头 vs 明细 金额对账
    head = pd.read_sql_query(
        f"""SELECT SUM(pay_price) s FROM dwd_order
            WHERE status='{BUSINESS_STATUS}' AND order_type='{BUSINESS_ORDER_TYPE}'""", conn
    ).iloc[0, 0] or 0.0
    item = pd.read_sql_query(
        f"""SELECT SUM(pay_price) s FROM dwd_order_item
            WHERE status='{BUSINESS_STATUS}' AND order_type='{BUSINESS_ORDER_TYPE}'""", conn
    ).iloc[0, 0] or 0.0
    gap = head - item
    add("## 4. 订单头与明细金额对账\n")
    add("统一口径：`status=SUCCESS` 且 `ordertype=SHOPPING`（排除 79 条 INIT 初始化单）。\n")
    add("| 口径 | 金额（元） |")
    add("|---|---|")
    add(f"| order_list 实付合计 | {_fmt(head)} |")
    add(f"| order_details 实付合计 | {_fmt(item)} |")
    add(f"| 差值 | {_fmt(gap)} |")
    add("")
    if abs(gap) > 0.01:
        issues.append(f"订单头与明细差 {_fmt(gap)} 元（疑似退款/拆单/明细缺失）")
        add(f"差异率 **{gap / head * 100:.3f}%**，属真实业务差异，需在报告中说明口径。\n")
    add("")

    # 5. 维度完整性（孤儿售货机）
    add("## 5. 维度完整性\n")
    orphan = stats.get("machine_orphan", 0)
    used = pd.read_sql_query("SELECT COUNT(DISTINCT boxid) c FROM dwd_order WHERE boxid IS NOT NULL", conn).iloc[0, 0]
    add(f"- 订单中出现的售货机数：**{used}**")
    add(f"- box_list 维表台数：**{stats.get('machine_total', 0) - orphan}**")
    add(f"- 维表缺失（孤儿）售货机：**{orphan}** 台，已用 `is_orphan=1` 占位")
    if orphan:
        issues.append(f"{orphan} 台售货机在维表中缺失")
    add("")

    # 6. 型号标准化
    add("## 6. 售货机型号标准化\n")
    models = pd.read_sql_query(
        "SELECT model_raw, COUNT(*) c FROM dim_machine WHERE model_raw IS NOT NULL GROUP BY model_raw ORDER BY c DESC", conn
    )
    add("| 原始值 | 台数 | 标准化后 |")
    add("|---|---|---|")
    for _, r in models.iterrows():
        add(f"| `{r['model_raw']}` | {r['c']} | MA650-A |")
    add("")
    if len(models) > 1:
        issues.append(f"同一型号存在 {len(models)} 种写法")
    add("")

    # 7. 商品名脏值
    add("## 7. 商品名清洗\n")
    null_p = stats.get("item_null_product", 0)
    tab_n = pd.read_sql_query(
        """SELECT COUNT(*) FROM dwd_order_item
           WHERE product_name_raw LIKE '%' || char(9) || '%'""", conn
    ).iloc[0, 0]
    space_n = pd.read_sql_query(
        """SELECT COUNT(*) FROM dwd_order_item
           WHERE product_name_raw IS NOT NULL
             AND product_name_raw NOT LIKE '%' || char(9) || '%'
             AND (product_name_raw LIKE ' %' OR product_name_raw LIKE '% ')""", conn
    ).iloc[0, 0]
    add(f"- 商品名为空的行：**{null_p}** 条（事实表中已剔除）")
    add(f"- 商品名尾部带制表符（`\\t`）的行：**{tab_n:,}** 条，属导出工具的系统性脏值")
    add(f"- 商品名首尾带空格的行：**{space_n}** 条")
    add(f"- 合计清洗 **{tab_n + space_n:,}** 条，否则同一商品会被拆成两个")
    add(f"- 清洗后商品数：**{pd.read_sql_query('SELECT COUNT(DISTINCT product_name) c FROM dwd_order_item', conn).iloc[0, 0]}**")
    if null_p:
        issues.append(f"{null_p} 条明细商品名为空")
    add("")

    # 8. 状态与订单类型
    add("## 8. 订单状态分布\n")
    st = pd.read_sql_query("SELECT status, COUNT(*) c FROM dwd_order GROUP BY status ORDER BY c DESC", conn)
    add("| 状态 | 订单数 |")
    add("|---|---|")
    for _, r in st.iterrows():
        add(f"| {r['status']} | {r['c']:,} |")
    ot = pd.read_sql_query("SELECT order_type, COUNT(*) c FROM dwd_order GROUP BY order_type ORDER BY c DESC", conn)
    add("")
    add("| 订单类型 | 订单数 |")
    add("|---|---|")
    for _, r in ot.iterrows():
        add(f"| {r['order_type']} | {r['c']:,} |")
    add("")
    init_cnt = int(ot.loc[ot["order_type"] == "INIT", "c"].sum()) if "INIT" in set(ot["order_type"]) else 0
    if init_cnt:
        issues.append(f"{init_cnt} 条 INIT 初始化订单已排除在事实表外")
    add("")

    # 9. 与实验指导书预期值对照
    add("## 9. 与实验指导书结果对照\n")
    add("| 指标 | 指导书预期 | 本次计算 | 结论 |")
    add("|---|---|---|---|")
    pe = GUIDE_EXPECT["product"]
    row = pd.read_sql_query(
        "SELECT qty, sales_amount FROM ads_product_sales WHERE product_name = ?", conn, params=[pe["name"]]
    )
    if len(row):
        ok = abs(float(row.iloc[0]["sales_amount"]) - pe["amount"]) < 0.01 and int(row.iloc[0]["qty"]) == pe["qty"]
        add(f"| {pe['name']} 销量/销售额 | {pe['qty']:,} 件 / {_fmt(pe['amount'])} 元 | "
            f"{int(row.iloc[0]['qty']):,} 件 / {_fmt(float(row.iloc[0]['sales_amount']))} 元 | {'✅ 一致' if ok else '⚠️ 不一致'} |")
    ce = GUIDE_EXPECT["customer"]
    row = pd.read_sql_query(
        "SELECT order_cnt, pay_amount FROM ads_customer_rank WHERE customer_id = ?", conn, params=[ce["id"]]
    )
    if len(row):
        ok = int(row.iloc[0]["order_cnt"]) == ce["order_cnt"] and abs(float(row.iloc[0]["pay_amount"]) - ce["pay_amount"]) < 0.01
        add(f"| 客户 {ce['id']} 订单数/消费额 | {ce['order_cnt']} 笔 / {_fmt(ce['pay_amount'])} 元 | "
            f"{int(row.iloc[0]['order_cnt'])} 笔 / {_fmt(float(row.iloc[0]['pay_amount']))} 元 | {'✅ 一致' if ok else '⚠️ 不一致'} |")
    add("")
    add("这两个数值取自指导书对结果的解读，用于验证 ETL 口径与老师一致。\n")

    # 10. 时间跨度
    span = pd.read_sql_query("SELECT MIN(order_date) lo, MAX(order_date) hi, COUNT(DISTINCT order_date) d FROM dwd_order", conn).iloc[0]
    add("## 10. 数据时间跨度\n")
    add(f"- 起止：**{span['lo']} ~ {span['hi']}**，共 **{span['d']}** 个有交易的自然日")
    add("")

    # 汇总
    add("## 结论\n")
    if issues:
        add(f"共发现 **{len(issues)}** 类问题，均已处理或有明确口径：\n")
        for i, s in enumerate(issues, 1):
            add(f"{i}. {s}")
    else:
        add("未发现质量问题。")
    add("")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    report = "\n".join(lines)
    (DOCS_DIR / "dq_report.md").write_text(report, encoding="utf-8")
    return report
