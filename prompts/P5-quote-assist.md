# P5 — 报价辅助（强人工闸门）

> 前置检查：`Inquiry.inquiry_type == REAL_RFQ`，且五要素齐全，且 `Product.cost_breakdown` 与 `Certification` 台账可用。
> 缺任何一项 → 只能生成"索取信息"的回复，不得进入报价环节。

## 这是全系统风险最高的一步

报价错了，三种后果：
- 报高了 → 丢单
- 报低了 → 亏钱（且客户会拿这个价压后续所有订单）
- 报错了条款 → 后续扯皮、索赔、甚至收不回款

**因此：AI 不计算价格。AI 只做四件事——查表、组装、自检、标注不确定。**

## 明确的职责切分

| 谁 | 做什么 |
|---|---|
| 系统（确定性代码） | 按 `cost_breakdown` 逐项求和；按 HS 编码查退税率；按当日汇率换算；按配置的毛利规则加成；生成 PI/Quotation 草稿 |
| LLM | 从询盘正文里**抽取**参数（数量、规格、包装要求、目的地、交期）；把这些参数映射到产品 SKU；检查客户要求是否存在内部冲突 |
| 人（业务员/经理） | 决定最终报价；决定是否给折扣；决定付款条件；签字 |

**LLM 输出的数字，一律视为"待核对的抽取结果"，不是"价格"。**

## 报价计算（确定性代码）

```python
def compute_quote(req: QuoteRequest, cfg: QuoteConfig, fx: FxRate) -> QuoteDraft:
    cb = load_cost_breakdown(req.sku, req.quantity)   # 来自配置/ERP，不来自 LLM
    items = {
        "material":      cb.material,
        "labor":         cb.labor,
        "packaging":     cb.packaging(req.packaging_spec),
        "inland":        cb.inland_freight,
        "clearance":     cb.export_clearance,
        "main_freight":  freight_lookup(req.incoterm, req.destination, req.volume),  # 仅 CFR/CIF/DAP/DDP
        "insurance":     cb.insured_value * 1.10 * INSURANCE_RATE if req.incoterm == "CIF" else 0,
        "bank":          cb.subtotal * bank_rate(req.payment_terms),
        "cert_amort":    cb.cert_cost / req.quantity,
    }
    rebate = lookup_export_rebate(req.hs_code)        # 查表，不硬编码
    floor  = (sum(items.values()) - rebate) * (1 + cfg.fx_buffer) * fx.rate
    price  = floor * (1 + cfg.target_margin)
    return QuoteDraft(items=items, floor=floor, price=price,
                      fx_rate=fx.rate, fx_source=fx.source, fx_at=fx.timestamp,
                      valid_until=now() + cfg.quote_validity_days)
```

要求：
- 每一步都能回溯。`cost_breakdown` 快照必须存进 `Quotation`，因为成本会变，报价要能复现。
- 汇率必须存**报价时刻的值 + 来源 + 时间戳**。不允许用"当前汇率"。
- `freight_lookup` 查不到运价 → 抛 `MissingFreightRate`，**不要给估算值**。
- 退税率为 0（该品类不退税）→ 正常处理，不是异常。

## 六道自检（不通过则状态停在 `DRAFT`）

1. `unit_price × quantity` 与 `cost_breakdown` 加总一致（容差 0.5%）
2. `valid_until` 在未来，且 ≤ 配置上限（默认 30 天）
3. `incoterm` 与 `destination_port` 匹配（CIF/CFR/DAP/DDP 必须有港口）
4. `payment_terms` 不在 `{DP, DA, OA}`；如是 → 拒绝，转人工评估
5. 客户要求的认证，在 `Certification` 台账中 `status=valid` 且覆盖该 SKU；否则在草稿里标 `cert_gap`，**不允许写"we have XX certificate"**
6. 客户要求交期 vs `lead_time_days + 生产排期` 是否可行；不可行 → 标 `lead_time_risk`，不给承诺日期

## 人类审批界面要显示什么

业务员看到的不是一张报价单，是一个**决策面板**：

```
客户：ABC Trading GmbH（德国，采购经理，历史：近90天进口3批）
需求：{sku} × 5000 pcs，CIF Hamburg，TT 30/70
────────────────────────────────
底价：USD 2.84/pc    建议报价：USD 3.41/pc
成本构成（可展开）：材料 1.62 / 加工 0.48 / 包装 0.21 / 海运 0.39 / ...
汇率：7.12（来源：中国银行，2026-10-27 09:30）
退税：13%（HS 9403.60，查表）
────────────────────────────────
⚠ 提示：
  · 客户要求 CE，台账中该证书有效期至 2027-03，覆盖当前 SKU ✓
  · 客户要求 25 天交期，当前排期最早 32 天 → 交期风险
  · 该客户上次从越南供应商采购，价格敏感度未知
────────────────────────────────
[ 调整为 ___ ]  [ 通过并生成 PI ]  [ 退回补充信息 ]
```

**关键设计**：`⚠ 提示` 里的每一条都必须有数据来源支撑。没有来源的"建议"不要放上去——业务员信一次错的，就再也不看了。

## PI 生成

PI 必须包含：
```
卖方抬头 / 买方抬头（与 PO 一致）
PI No. / 日期 / 有效期
产品：型号、描述、数量、单价、金额
贸易术语：CIF Hamburg (Incoterms 2020)
付款条件：TT 30% deposit, 70% against BL copy
交货期：收到定金后 XX 天内
包装：标准出口包装 / 定制（附说明）
港口：Shanghai → Hamburg
银行信息（与合同一致）
备注：认证声明（仅限台账有效的）、不可抗力、争议解决
```

生成后**必须**做一致性检查：PI 里的数量/金额/条款，与 `Quotation` 记录逐字段比对。任何不一致 → 拒绝生成。

## 验收

```bash
python -m pytest tests/quote/ -v
python -m src.cli quote draft --inquiry-id INV-0001 --dry-run
```

必须覆盖：
1. `payment_terms=OA` → 抛 `UnsupportedPaymentTerms`，不生成草稿
2. 汇率缺失 → 抛 `MissingFxRate`，不估算
3. 运价缺失（CIF 但无运价表） → 抛 `MissingFreightRate`
4. 客户要 CE 但台账无覆盖 → 草稿标 `cert_gap`，且正文搜索不到 "CE certified"
5. 交期 25 天 vs 排期 32 天 → 标 `lead_time_risk`，不输出"25 days"承诺
6. 手工改动 `unit_price` 后 `cost_breakdown` 未同步 → 自检失败，退回 DRAFT

## 不要做的事

- 不要让 LLM 生成任何金额。一个字都不行。
- 不要用行业平均运费、平均退税率、平均汇率兜底。缺数据就报错——报错是好事，它阻止了一次亏钱的报价。
- 不要自动发送 PI。PI 是准合同，必须人签字。
- 不要给 DDP 自动报价（涉及目的国关税/VAT，见领域规则第2节）。
