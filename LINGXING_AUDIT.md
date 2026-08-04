# 领星 OpenAPI 第一阶段接口盘点

## 目标

本阶段只读取领星数据，不修改店铺、商品、广告、库存或财务数据。

盘点范围：

- AppID/AppSecret 与 IP 白名单；
- 亚马逊市场和店铺；
- 本地产品、Listing、订单；
- 售后订单；
- FBA 库存和库龄；
- 广告账号及 SP 商品广告报表；
- ASIN 利润报表。

## 运行环境

领星接口盘点使用独立的可选 SDK，要求当前项目虚拟环境为 Python 3.10 或更高版本。原有竞品监控依赖仍保存在 `requirements.txt`，领星 SDK 单独保存在 `requirements-lingxing.txt`，因此领星依赖安装失败不会改变原有程序的依赖定义。

第一次运行 `领星接口盘点.bat` 时，脚本会检查 Python 版本并按需安装领星 SDK。已安装后不会重复安装。

## 配置

在项目根目录 `.env` 中填写：

```text
LINGXING_APP_ID=真实AppID
LINGXING_APP_SECRET=真实AppSecret
LINGXING_BASE_URL=https://openapi.lingxing.com
```

可选配置：

```text
LINGXING_SID=店铺SID
LINGXING_AUDIT_LOOKBACK_DAYS=7
LINGXING_AUDIT_TIMEOUT_SECONDS=60
```

`.env` 已加入 Git 忽略规则，不应提交到仓库。

## 运行

首次更新后先运行：

```text
首次安装.bat
```

然后双击：

```text
领星接口盘点.bat
```

也可以在 PowerShell 中运行：

```powershell
.\.venv\Scripts\python.exe -m app.lingxing_audit.cli
```

## 输出

每次运行生成独立目录：

```text
data\lingxing_audit\YYYYMMDD-HHMMSS\
```

其中包括：

- `audit-report.md`：人工阅读的接口可用性报告；
- `audit-report.json`：后续程序读取的结构化报告；
- `samples\*.json`：每个成功接口的脱敏样本；
- `latest.txt`：最近一次运行编号。

Token、AppSecret、签名和其他敏感字段会在写盘前替换为 `***redacted***`。客户端初始化或接口调用错误中出现的真实 AppID/AppSecret 也会在写入报告前替换。

## 状态含义

- `success`：接口调用成功；
- `authentication_failed`：凭证错误；
- `permission_denied`：权限或 IP 白名单问题；
- `needs_parameters`：接口存在，但还需要店铺、广告账号或其他参数；
- `parameter_error`：当前试探参数与账号接口版本不匹配；
- `sdk_method_missing`：当前 SDK 没有对应方法；
- `network_error` / `timeout` / `rate_limited`：网络、超时或限流。

第一阶段的产物用于确认后续日报、周报和月报可以直接获得哪些字段，不生成正式经营报告，也不调用 DeepSeek。
