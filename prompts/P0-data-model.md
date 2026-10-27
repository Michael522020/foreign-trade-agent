# P0 — 领域数据模型与状态机

> 前置检查：无。这是全链路唯一无依赖项。
> 若 `src/models/` 已存在实体定义，先读完再判断是「扩展」还是「重构」，不要直接覆盖。

## 目标

定义外贸获客系统的核心实体、字段、约束与状态机。**只做模型层**，不做采集、不做触达、不做界面。

这一阶段做错的代价最高：后面的线索、触达、询盘、报价全部建立在这里。宁可多花时间把字段敲准。

## 任务

### 1. 实体与字段

至少包含以下实体。字段必须覆盖括号内的内容，可增不可减：

- `Company`（企业）
  `id, name, name_local, country, region, website, domain, industry, hs_codes[], employee_band, annual_revenue_band, buyer_type(IMPORTER/DISTRIBUTOR/BRAND/TRADER/END_USER), source, source_url, collected_at`

- `Contact`（联系人）
  `id, company_id, full_name, role(见规则文件第8节枚举), email, email_status(verified/risky/invalid/unknown), phone, phone_e164, whatsapp_consent(bool), linkedin_url, language, timezone, source, source_url, collected_at, last_contacted_at`

- `Lead`（线索 = Company+Contact 的一次开发机会）
  `id, company_id, contact_id, product_interest, icp_score, score_breakdown(json), stage, owner, created_at, updated_at`

- `Product`（我方产品，注意这里是卖方自己的产品）
  `id, sku, name_en, hs_code, category, moq_default, lead_time_days_default, certifications[](引用 cert_id), cost_breakdown_ref`

- `Certification`（认证台账）
  `id, type(CE/FDA/RoHS/REACH/UL/ISO9001/BSCI/FSC/CARB/...), cert_no, issued_by, valid_from, valid_to, covered_skus[], document_ref, status(valid/expired/pending)`

- `Inquiry`（询盘）
  `id, lead_id, channel, raw_text, received_at, inquiry_type(见规则文件第7节), urgency, missing_info[], assigned_to, first_response_at`

- `Quotation`（报价）
  `id, inquiry_id, customer_id, product_sku, quantity, incoterm, destination_port, payment_terms, unit_price, currency, cost_breakdown(json), fx_rate, fx_rate_source, fx_rate_at, valid_until, status(draft/pending_review/approved/sent/expired)`

- `Suppression`（抑制名单，见合规规则第3节）

- `Interaction`（交互流水）
  `id, lead_id, channel, direction, occurred_at, content_ref, outcome, next_action_at`

- `ComplianceAudit`（合规审计，见合规规则第6节）

### 2. 状态机（必须显式实现，不允许用字符串散落各处）

**Lead 主状态机**
```
RAW → ENRICHED → SCORED → QUEUED → CONTACTED → REPLIED → INQUIRY
                                                      ↘ BOUNCED
                                                      ↘ NOT_INTERESTED
                                                      ↘ NURTURE
INQUIRY → QUOTING → SAMPLE → NEGOTIATING → WON
                                        ↘ LOST
任意状态 → SUPPRESSED（终态，不可逆）
```

**Inquiry 状态机**
```
NEW → TRIAGED → NEEDS_INFO → QUOTED → SAMPLE_SENT → ORDER_CONFIRMED → CLOSED
              ↘ ARCHIVED（SPAM_BLAST / COMPETITOR_PROBE）
```

**Quotation 状态机**
```
DRAFT → PENDING_REVIEW → APPROVED → SENT → ACCEPTED → EXPIRED
                       ↘ REJECTED
```

要求：
- 状态转移写在**一处**（`src/models/state_machine.py`），其他模块只能调用 `transition(entity, event)`。
- 非法转移必须抛 `InvalidTransition`，并带上 `from_state / to_state / allowed_from`。
- 终态（`SUPPRESSED`/`WON`/`LOST`/`CLOSED`）不可再转移。

### 3. 约束（用 pydantic validator + 数据库约束双写）

- `Contact.email` 必须通过语法校验；`email_status != verified` 的不能进入 `QUEUED`。这条约束放在**模型层**，不是业务层——让它在任何入口都生效。
- `Quotation.valid_until > created_at`；过期后状态自动转 `EXPIRED`（用定时任务，不要靠查询时判断）。
- `Quotation` 的 `incoterm` 在 `{CFR, CIF, DAP, DDP}` 时必须填 `destination_port`；在 `{EXW, FOB}` 时必须为空。
- `payment_terms` 属于 `{DP, DA, OA}` 时，`Quotation.status` 不允许离开 `DRAFT`（见规则文件第4节）。
- `Quotation.cost_breakdown` 的加总必须等于 `unit_price × quantity`（含币种换算容差 0.5%）。不一致直接拒绝入库。
- 同一 `(company_id, email)` 唯一。

### 4. 迁移与种子

- Alembic 初始迁移，跑一次 `alembic upgrade head` 必须干净通过。
- `config/example.yaml`：放示例配置，**每个数值后面加注释 `# 示例值，上线前必须由业务确认`**。
- `seeds/` 只放**结构**（枚举值、认证类型、HS 编码样例 3 条），不放"看起来真实"的客户。

## 验收（你自己执行并粘贴真实输出）

```bash
python -m pytest tests/models/ -v
python -m mypy --strict src/models/
alembic upgrade head && alembic downgrade base && alembic upgrade head
```

必须包含以下反例测试，全部通过：
1. `DP/DA/OA` 条款的报价，尝试 `transition` 到 `PENDING_REVIEW` → 抛 `InvalidTransition`
2. `CIF` 但不填 `destination_port` → pydantic 校验失败
3. `cost_breakdown` 加总与 `unit_price × quantity` 差 5% → 拒绝入库
4. `SUPPRESSED` 状态的 lead 尝试转 `CONTACTED` → 抛 `InvalidTransition`
5. 重复 `(company_id, email)` → 唯一约束报错

## 不要做的事

- 不要写采集逻辑、不要写邮件模板、不要写 Web 界面。
- 不要为"以后可能用到"加字段。加一个字段就要能说清它填什么、谁填、什么时候用。
- 不要把 `Incoterms` 做成自由文本。用 Enum，且只启用规则文件第2节那 6 个。
