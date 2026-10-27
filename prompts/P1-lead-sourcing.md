# P1 — 线索采集与清洗

> 前置检查：`src/models/` 必须存在 `Company / Contact / Lead / Suppression`，且 `alembic upgrade head` 通过。
> 缺任何一个 → **停下，报告缺什么，不要自己创建模型**。

## 目标

把外贸公司现有的**真实线索来源**接进系统，做去重、验证、抑制过滤，输出干净的 `Lead` 队列。

不谈采集技术，先谈一件事：**来源决定质量**。

## 五个来源，各自的采集语义

### 1. 海关数据（进口记录）
输入形态：CSV（服务商导出），字段各异。

必须归一化到的字段：
```
raw_importer_name, raw_importer_address, country,
hs_code, product_desc, quantity, quantity_unit, amount_usd,
ship_date, supplier_name, supplier_country, port_of_discharge, bl_no(可空)
```

业务规则（很重要，做错了排序就全错）：
- **一条进口记录 ≠ 一个客户。** 同一买家多次进口必须聚合到 `Company`，聚合键 = 归一化后的 `importer_name + country`。
- `last_ship_date` 距今 **≤ 90 天 → 处于采购窗口期**；91–180 天 → 可能换供应商；> 365 天 → 降级为观察。
- 供应商集中度：该买家前 3 大供应商占其总量的比例。> 70% 说明供应关系稳定，切入难；< 50% 说明在多方比价，**切入机会高**。
- **不要**用 `amount_usd` 直接当客户价值。金额大可能是低毛利大宗。

### 2. 展会名单（名片/登记表/主办方名录）
- 必须记录 `event_name` + `event_date`；`collected_at` 用展会日期，不是导入日期（决定跟进优先级）。
- 名片上无邮箱、只有手机的，走 `phone` 字段，标记 `contact_channel=PERSONAL_MEETING`（见面过的信任度最高，优先级最高）。
- 展会名录通常**禁止转售**，只允许自用。系统里记一份 `data_usage_scope`。

### 3. B2B 平台询盘（阿里国际站 / 中国制造网 / 环球资源）
- 询盘正文、客户国家、产品、数量要原样保留到 `Inquiry.raw_text`。
- 平台常隐去客户邮箱（站内信），此时只能记 `channel=PLATFORM_INBOX`，**不要尝试反查或猜测邮箱**。
- 有 `buyer_member_since`、`response_rate` 这类字段就存下来，是很好的资格信号。

### 4. 独立站询盘表单
- 来源 URL、落地页、UTM 全存。
- 表单里的留言是**最有价值的信息源**，不要只存邮箱丢掉正文。

### 5. 手工导入（业务员的 Excel）
- 必须提供模板列，导入时校验；缺列 → 拒绝整批并给出缺失列名。
- 允许 `overrides` 字段，让业务员写"这个客户我跟过，别自动发"。这类备注优先级最高。

## 任务

### 1. 适配器模式

```python
class SourceAdapter(Protocol):
    source_name: str
    def parse(self, path: Path) -> list[RawRecord]: ...
    def normalize(self, rec: RawRecord) -> NormalizedRecord: ...
    def dedupe_key(self, rec: NormalizedRecord) -> str: ...
```

每个来源一个 adapter，放 `src/ingest/adapters/`。
**不允许写一个巨大的 `if source == ...` 分支函数。**

### 2. 企业名归一化（决定去重质量）

必须处理：
- 后缀剥离：`Co., Ltd` / `Co.,Ltd.` / `LLC` / `GmbH` / `S.A.` / `Pvt Ltd` / `Inc`
- 大小写、全半角、多空格
- 常见变体：`&` ↔ `and`、`Int'l` ↔ `International`
- **不做**激进模糊匹配（"ABC Trading" 和 "ABC Trading Group" 是不是同一家，交给人工确认队列，不要自动合并）

去重策略：
- 强键：`normalized_domain`（有官网时）
- 中键：`normalized_name + country`
- 弱键：`phone_e164` / `email`
命中强/中键 → 自动合并；只命中弱键 → 进 `merge_candidates` 表待人工确认。

### 3. 邮箱验证（分三档，不要只做正则）

```
syntax      正则 + 长度 + 域名存在
mx          域名有 MX 记录
smtp_probe  （可选，注意：部分服务商会封 IP，且探测本身有声誉风险）
```
输出 `email_status ∈ {verified, risky, invalid, unknown}`。
规则：`role-based` 邮箱（`info@` `sales@` `contact@`）标记 `is_role_based=True`——这类地址回复率低于个人邮箱，但合法性和合规风险更低（GDPR 视角）。

### 4. 抑制过滤（硬闸门）

入库前查 `Suppression`：
- 邮箱/电话/域名任一命中 → 直接丢弃并记 `drop_reason=SUPPRESSED`
- 不允许"先入库再过滤"。**在写库之前查**。

### 5. 幂等

同一文件重复导入不能产生重复数据。
用 `(source, source_record_id)` 或 `hash(归一化后关键字段)` 做幂等键。

## 验收

```bash
python -m pytest tests/ingest/ -v
python -m src.cli ingest --source customs_csv --file tests/fixtures/customs_sample.csv --dry-run
```

必须覆盖：
1. 同一买家 5 条进口记录 → 聚合成 1 个 `Company`，`import_count=5`，`last_ship_date` 取最大值
2. 同一文件导入两次 → `Company` 数量不变（幂等）
3. 邮箱在抑制名单 → 不入库，`drop_reason=SUPPRESSED`
4. 缺 `hs_code` 的行 → 进入 `quarantine` 表，附原因，不静默跳过
5. `ABC Trading Co., Ltd` 与 `abc trading limited` → 归一化后同名，命中中键

`--dry-run` 必须输出：解析行数 / 通过数 / 隔离数 / 去重合并数 / 抑制命中数。

## 不要做的事

- 不要反查平台隐去的客户邮箱（违反平台协议，且数据不可靠）。
- 不要用模糊匹配自动合并企业。合并错了比不合并更糟——业务员会对着错误的采购历史写开发信。
- 不要在采集阶段做评分。评分是 P2 的事，混在一起会导致"数据清洗逻辑"和"业务判断逻辑"互相污染。
