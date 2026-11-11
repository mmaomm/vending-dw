# 数据字典

## 1. 源表 `order_list.csv`（订单头，30,835 行）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 订单 ID（主键） |
| createdtime | string | 下单时间 |
| customerid | string | 客户 ID |
| customermobile | string | 手机号（入库即脱敏） |
| totalprice | float | 订单总金额 |
| paytotalprice | float | 实际支付金额 |
| discounttotalprice | float | 优惠金额 |
| status | string | WAIT 待支付 / SUCCESS 支付成功 / FAIL 支付失败 |
| source | string | ALIPAY_SHOPPING / WECHAT_SHOPPING |
| ordertype | string | SHOPPING 购物单 / INIT 初始化单 |
| boxid | string | 售货机 ID |
| payedtime | string | 支付时间 |
| ordernum | string | 订单号 |
| externalordernum | string | 支付宝/微信订单号 |

## 2. 源表 `order_details.csv`（订单行，40,237 行）

在订单头字段之外，增加商品维度：

| 字段 | 类型 | 说明 |
|---|---|---|
| productname | string | 商品名称（**6,902 行尾部带 `\t`**） |
| amount | int | 购买数量 |
| costprice | float | 成本价 |
| saleprice | float | 销售价 |
| producttotalprice | float | 商品总金额 |
| productdiscountprice | float | 商品优惠金额 |
| productpaytotalprice | float | 商品实际支付金额 |
| rfidstatus | string | 标签状态 COMMON / SOLD / INVALID |

## 3. 源表 `box_list.csv`（售货机维，55 台）

| 字段 | 类型 | 说明 |
|---|---|---|
| boxid | string | 售货机 ID |
| address | string | 投放地址（部分值尾部带 `\t`） |
| name | string | 售货机名称 |
| serialnumber | string | 设备编号 |
| status | string | ONLINE / OFFLINE / BREAKDOWN |
| modelnumber | string | 型号（**5 种写法**，归一为 `MA650-A`） |

## 4. 衍生表

### `dim_product`（SCD2）

| 字段 | 说明 |
|---|---|
| product_key | 代理键，每次价格变化产生新版本 |
| product_name | 清洗后的商品名 |
| sale_price | 该版本售价 |
| valid_from / valid_to | 生效区间；`9999-12-31` 表示当前版本 |
| is_current | 1 = 当前版本 |

### `dim_machine`

| 字段 | 说明 |
|---|---|
| machine_key | 代理键 |
| city | 从 address 解析出的城市 |
| model_norm | 标准化型号 |
| is_orphan | 1 = 订单中出现但维表缺失，用占位行保证事实表外键完整 |

### `fact_order_item`（粒度：订单行）

| 字段 | 说明 |
|---|---|
| fact_key | 代理键 |
| date_key / product_key / machine_key / customer_key | 维度外键 |
| quantity | 购买数量 |
| pay_price | 商品实付金额 |
| cost_price | 成本价 |
| profit | `pay_price − quantity × cost_price − discount_price` |

## 5. 指标口径

| 指标 | 公式 | 数据来源 |
|---|---|---|
| 客户消费金额 | `SUM(pay_price)`，按 customer_id 聚合 | `dwd_order`（SUCCESS + SHOPPING） |
| 客户订单数 | `COUNT(*)` | `dwd_order` |
| 商品销售金额 | `SUM(pay_price)`，按 product_name 聚合 | `dwd_order_item`（SUCCESS + SHOPPING + 商品名非空） |
| 商品销售数量 | `SUM(amount)` | 同上 |
| 售货机日销售金额 | `SUM(pay_price)`，按 boxid + order_date 聚合 | `dwd_order_item` |
| 售货机利润 | `SUM(profit)`，按 boxid 聚合 | `dwd_order_item` |
| 客单价 | `售货机销售金额 ÷ COUNT(DISTINCT order_num)` | `ads_machine_profit` |

> 注意：任务 1 走订单头（`order_list`），任务 2/3/4 走明细（`order_details`），这是课程设定的口径，两表合计差 871.49 元，原因见 `docs/dq_report.md` 第 4 节。
