"""生成 README 预览图：Top10 商品销售额（横向条形）+ 月度销售趋势（折线）。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from config import BUSINESS_ORDER_TYPE, BUSINESS_STATUS, DB_PATH, DOCS_DIR

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


W, H = 1440, 720
BG = (255, 255, 255)
INK = (33, 37, 41)
MUTED = (120, 128, 136)
ACCENT = (52, 110, 235)
ACCENT2 = (235, 126, 52)
GRID = (232, 236, 241)


def draw_bar_panel(d: ImageDraw.ImageDraw, df: pd.DataFrame) -> None:
    x0, y0, x1 = 40, 128, 640
    f_title, f_lbl, f_val = _font(26), _font(17), _font(16)
    d.text((x0, 40), "Top10 商品销售额（元）", font=f_title, fill=INK)
    d.text((x0, 78), "口径：order_details 支付成功明细汇总", font=_font(15), fill=MUTED)

    vmax = float(df["sales_amount"].max())
    bar_h, gap = 34, 14
    label_w = 200
    for i, r in enumerate(df.itertuples(index=False)):
        y = y0 + i * (bar_h + gap)
        d.text((x0, y + 6), str(r.product_name)[:14], font=f_lbl, fill=INK)
        w = (x1 - x0 - label_w) * (float(r.sales_amount) / vmax)
        d.rounded_rectangle([x0 + label_w, y, x0 + label_w + max(w, 2), y + bar_h],
                            radius=6, fill=ACCENT)
        d.text((x0 + label_w + w + 8, y + 7), f"{r.sales_amount:,.0f}", font=f_val, fill=MUTED)


def draw_line_panel(d: ImageDraw.ImageDraw, df: pd.DataFrame) -> None:
    x0, y0, x1, y1 = 860, 140, 1400, 560
    f_title, f_lbl, f_val = _font(26), _font(16), _font(15)
    d.text((860, 40), "月度销售趋势（元）", font=f_title, fill=INK)
    d.text((860, 78), "口径：order_list 支付成功订单实付金额", font=_font(15), fill=MUTED)

    vmax = float(df["amount"].max()) * 1.15
    months = list(df["month"])
    pts = []
    step = (x1 - x0) / max(len(df) - 1, 1)
    for i, r in enumerate(df.itertuples(index=False)):
        px = x0 + i * step
        py = y1 - (float(r.amount) / vmax) * (y1 - y0)
        pts.append((px, py))

    for g in range(4):
        gy = y0 + (y1 - y0) * g / 3
        d.line([x0, gy, x1, gy], fill=GRID, width=1)
        d.text((x0 - 72, gy - 9), f"{vmax * (1 - g / 3):,.0f}", font=f_val, fill=MUTED)

    if len(pts) > 1:
        d.line(pts, fill=ACCENT2, width=3, joint="curve")
    for (px, py), r in zip(pts, df.itertuples(index=False)):
        d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=ACCENT2)
        d.text((px - 12, y1 + 12), str(r.month)[2:], font=f_val, fill=MUTED)
        d.text((px - 22, py - 30), f"{float(r.amount) / 1000:.1f}k", font=_font(13), fill=MUTED)


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    top = pd.read_sql_query(
        "SELECT product_name, sales_amount FROM ads_product_sales ORDER BY sales_amount DESC LIMIT 10", conn
    )
    months = pd.read_sql_query(
        f"""SELECT substr(order_date,1,7) AS month, SUM(pay_price) AS amount
            FROM dwd_order
            WHERE status='{BUSINESS_STATUS}' AND order_type='{BUSINESS_ORDER_TYPE}'
            GROUP BY 1 ORDER BY 1""",
        conn,
    )
    conn.close()

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    draw_bar_panel(d, top)
    draw_line_panel(d, months)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out = DOCS_DIR / "preview.png"
    img.save(out, "PNG", optimize=True)
    print(f"preview -> {out}  ({out.stat().st_size / 1024:.0f} KB)")
    print(f"月份数 {len(months)}，Top1 {top.iloc[0]['product_name']} {top.iloc[0]['sales_amount']:,.2f}")


if __name__ == "__main__":
    main()
