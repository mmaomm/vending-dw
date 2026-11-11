"""一键跑完整条链路：DWD -> DIM/FACT -> ADS -> 数据质量报告。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import ads        # noqa: E402
import clean      # noqa: E402
import config     # noqa: E402
import dq         # noqa: E402
import dw         # noqa: E402


def main() -> None:
    t0 = time.time()
    print("=" * 62)
    print("无人售货机零售数据仓库 · 全量构建")
    print("=" * 62)

    conn = config.connect()
    config.init_schema(conn)
    print("[1/4] 结构初始化完成")

    stats = clean.build_dwd(conn)
    print(f"[2/4] DWD 完成：订单 {stats['rows_dwd']['dwd_order']:,} 行，"
          f"明细 {stats['rows_dwd']['dwd_order_item']:,} 行")

    stats.update(dw.build_dw(conn))
    print(f"[3/4] 维度/事实完成：dim_product {stats['dim_product']:,} 行（SCD2 版本），"
          f"fact {stats['fact_order_item']:,} 行，孤儿机器 {stats['machine_orphan']} 台")

    stats.update(ads.build_ads(conn))
    print(f"[4/4] ADS 完成：客户 {stats['ads_customer_rank']:,} / 商品 {stats['ads_product_sales']:,} / "
          f"日销 {stats['ads_machine_daily']:,} / 机器 {stats['ads_machine_profit']:,}")

    dq.run_checks(conn, stats)
    print("数据质量报告 -> docs/dq_report.md")

    frames = stats.pop("_frames")
    print("\n--- 结果预览 ---")
    print("\nTop5 客户消费：")
    print(frames["cust"].head(5).to_string(index=False))
    print("\nTop5 商品销售额：")
    print(frames["prod"].head(5).to_string(index=False))
    print("\nTop5 售货机利润：")
    print(frames["mach"][["boxid", "machine_name", "profit", "avg_order_value"]].head(5).to_string(index=False))

    conn.close()
    print(f"\n耗时 {time.time() - t0:.1f}s，数据库 -> data/dw.db，结果 CSV -> data/out/")


if __name__ == "__main__":
    main()
