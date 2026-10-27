# P3 — 触达素材生成（只生成，不发送）

> 前置检查：`Lead.stage == SCORED`，且 `Contact.role != UNKNOWN`，且 `icp_score.confidence >= 0.6`。
> 任一不满足 → 该 lead 不得进入生成队列，记录 `skip_reason`。

## 目标

为每个 lead 生成一封**业务员愿意直接用**的英文开发信 + 一段中文「为什么这么写」的说明。
产物写入 `outbox/{date}/{lead_id}.json`，`status=pending_review`。**绝不发送。**

## 核心机制：事实白名单（approved_facts）

这是整个 P3 最重要的设计。开发信里**每一个具体承诺**都必须有来源。

```python
@dataclass
class OutreachContext:
    lead_id: str
    contact_name: str
    contact_role: str
    company_name: str
    country: str
    language: str
    # 白名单事实：key 是事实 id，value 是原文 + 出处
    approved_facts: dict[str, dict]   # {"moq": {"value": 500, "unit": "pcs", "src": "config/product.yaml"}}
    pain_hypothesis: str              # 来自 P2，必须引用具体证据
    evidence: list[str]               # 例如 ["近90天进口3批", "前三大供应商占比42%"]
    forbidden_topics: list[str]       # 例如 ["价格", "DDP条款"]
```

生成后校验：正文中出现的每个数字+单位组合，必须能在 `approved_facts` 里找到。
找不到 → 该草稿标 `REJECTED_UNAPPROVED_FACT`，**不进 outbox**，并回传具体是哪句话。

这条校验比任何提示词都管用。它把"AI 编造 MOQ"从"靠运气"变成"结构上不可能"。

## 开发信结构（五段，缺一不可）

1. **为什么是你**（1 句）——引用 evidence 里最具体的一条。
   `Noticed you've taken 3 shipments of {category} since August.`
2. **我是谁**（1 句）——公司 + 一句差异点，不写"leading manufacturer"这类空话。
3. **我能解决什么**（1–2 句）——对应 `pain_hypothesis`，必须具体。
4. **低成本下一步**（1 句）——只要一个动作。不是"请回复"，而是"要不要我发一份 XX 给你"。
5. **退订**（1 句）——`If this isn't relevant, just reply "no" and I won't follow up.`

硬约束：
- 全文 **75–125 词**
- 首封**无链接、无图片、无附件、无 HTML**
- 主题行 ≤ 6 词，不含 "Re:"/"Fwd:"/"Free"/"Guarantee"/全大写/感叹号
- 不写价格（除非 `approved_facts` 有 `price_range` 且已审批）
- 不声称任何认证（除非 `Certification.status == valid` 且覆盖该 SKU，见领域规则第5节）

## 按市场调语气（不是翻译，是重写）

| 市场 | 风格 | 该做什么 | 不该做什么 |
|---|---|---|---|
| 德国/北欧 | 直接、参数导向 | 先给规格和认证，价格明码 | 寒暄、感叹号、夸张形容词 |
| 美国 | 简短、结果导向 | 一句话说清省多少/快多少 | 长段落、绕弯子 |
| 英国 | 克制、礼貌 | 用 "would you be open to..." | 过度热情 |
| 中东 | 关系先行 | 先建立个人连接，再谈生意 | 第一封就发目录 |
| 拉美 | 葡/西语、灵活 | 本地语言 + 付款方式灵活 | 纯英文模板 |
| 东南亚 | 价格敏感、务实 | 直接给阶梯价区间 | 长篇公司介绍 |
| 日本 | 极正式 | 敬语、公司介绍详细 | 催促、催促式跟进 |

**规则**：`language` 字段不是英文时，正文必须用目标语言。系统里不允许"英文模板 + 自动翻译"，翻译腔在 B2B 场景里等于降低可信度。

## 跟进序列

| 封次 | 间隔 | 角度 | 长度 |
|---|---|---|---|
| 1 | D0 | 证据 + 痛点 + 低门槛 CTA | 75–125 词 |
| 2 | D4 | 换一个 angle（案例/数据/样品） | ≤ 80 词 |
| 3 | D10 | 一句价值 + 一句问句 | ≤ 50 词 |
| 4 | D21 | 明确的"最后一次" | ≤ 40 词 |

- **最多 4 封**。超过 4 封，投诉率上升的幅度大于回复率。
- 任意一封产生回复 → 立刻停止序列（这是硬逻辑，不是建议）。
- 第 2 封起可以带链接（1 个，且指向具体产品页，不是首页）。
- 序列里**不允许**出现"Did you see my last email?"这类催促。

## 交付物格式

```json
{
  "lead_id": "...",
  "status": "pending_review",
  "subject": "...",
  "body": "...",
  "word_count": 98,
  "language": "en",
  "facts_used": ["moq", "lead_time"],
  "evidence_cited": ["近90天进口3批"],
  "why_this_works_zh": "客户近90天有3批该品类进口，说明在采购期；前三大供应商占比42%，说明在比价。所以第二段直接打'多供应商管理成本'，不问价格。",
  "risk_flags": [],
  "sequence": [{"step": 2, "due_offset_days": 4, "angle": "case_study"}]
}
```

`why_this_works_zh` 不是装饰。业务员看不懂为什么这么写，就会改回模板，系统就白做了。

## 验收

```bash
python -m pytest tests/outreach/ -v
python -m src.cli draft --queue daily --owner sales01 --dry-run
```

必须覆盖：
1. 正文含 `MOQ 500 pcs` 但 `approved_facts` 无 `moq` → `REJECTED_UNAPPROVED_FACT`
2. 正文声称 `CE certified` 但台账无有效证书 → 拒绝
3. `role=UNKNOWN` 的 lead → 生成队列中不出现
4. 首封含 `http` → 被剥离或拒绝（取决于配置，默认拒绝）
5. 词数 130 → 触发压缩重试，二次仍超限则 `REJECTED_TOO_LONG`
6. `language=pt` → 正文为葡萄牙语（验收时人工抽检 3 条）

## 不要做的事

- 不要调用任何真实发送 API。代码里出现 `smtplib.SMTP(...).sendmail` 即视为违规。
- 不要生成"通用模板 + 变量替换"。模板化文案的回复率已降到 1% 以下，做了等于没做。
- 不要在正文里写公司成立年份、厂房面积、员工人数 —— 这些买家不关心，且容易被拿去比价。
- 不要让 LLM 自己决定"要不要发"。它只生成，判定在 `SendGate`。
