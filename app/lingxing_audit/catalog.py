from __future__ import annotations

from .models import ProbeDefinition

# All entries are read-only query methods. The runner filters parameters against the
# installed SDK signature before calling a method.
PROBES: tuple[ProbeDefinition, ...] = (
    ProbeDefinition("token", "认证", "访问令牌", "AccessToken", "验证 AppID/AppSecret、IP 白名单和 Token 获取"),
    ProbeDefinition("marketplaces", "基础数据", "亚马逊市场", "basic.Marketplaces", "确认基础数据权限"),
    ProbeDefinition("sellers", "基础数据", "亚马逊店铺", "basic.Sellers", "获取店铺 SID 和店铺字段"),
    ProbeDefinition(
        "products", "商品", "本地产品", "product.Products", "核对 SKU、产品、品牌和分类字段",
        {"offset": 0, "length": 20, "page": 1, "page_size": 20},
    ),
    ProbeDefinition(
        "listings", "销售", "Listing", "sales.Listings", "核对 ASIN、MSKU、价格、库存和负责人字段",
        {"offset": 0, "length": 20, "page": 1, "page_size": 20},
        ("sellers",),
    ),
    ProbeDefinition(
        "orders", "销售", "平台订单", "sales.Orders", "核对销量、销售额、订单和商品明细字段",
        {"offset": 0, "length": 20, "page": 1, "page_size": 20, "date_type": "order_time"},
        ("sellers",),
    ),
    ProbeDefinition(
        "after_sales", "售后", "售后订单", "sales.AfterSalesOrders", "核对退货、退款和售后原因字段",
        {"offset": 0, "length": 20, "page": 1, "page_size": 20},
        ("sellers",),
    ),
    ProbeDefinition(
        "fba_inventory", "库存", "FBA库存", "warehouse.FbaInventory", "核对可售、在途、预留和库存状态字段",
        {"offset": 0, "length": 20, "page": 1, "page_size": 20},
        ("sellers",),
    ),
    ProbeDefinition(
        "inventory_health", "库存", "FBA库龄", "source.FbaInventoryHealth", "核对库龄、超龄和库存健康字段",
        {"offset": 0, "length": 20, "page": 1, "page_size": 20},
        ("sellers",),
    ),
    ProbeDefinition("ad_profiles", "广告", "广告账号", "ads.AdProfiles", "获取 profile_id 并确认广告权限"),
    ProbeDefinition(
        "sp_product_report", "广告", "SP商品广告报表", "ads.SpProductReports", "核对曝光、点击、花费、销售和转化字段",
        {"offset": 0, "length": 20, "page": 1, "page_size": 20},
        ("ad_profiles",),
    ),
    ProbeDefinition(
        "income_statement_asin", "利润", "ASIN利润报表", "finance.IncomeStatementAsins", "核对销售额、利润、广告费、仓储费和退款字段",
        {"offset": 0, "length": 20, "page": 1, "page_size": 20},
        ("sellers",),
    ),
)
