# P2 — 线索富化与 ICP 评分

> 前置检查：`src/ingest/` 可用，`Lead` 表有数据（≥ 20 条真实或 fixture 数据）。
> P1 的 adapter 若未跑通 → 停下。

## 目标

把 `RAW` 状态的线索变成 `SCORED`，产出可解释的 0–100 分，并按分数排序成业务员今天能用的队列。

**这一阶段的核心不是"AI 判断"，是"把判断理由结构化"。** 分数如果说不清为什么，业务员不会信，也就不会用。

## 富化（Enrichment）——只做可溯源的部分

| 字段 | 来源 | 缺失时 |
|---|---|---|
| `buyer_type` | 官网 About/Products、LinkedIn 公司页、海关记录里的供应商结构 | `UNKNOWN` |
| `employee_band` | LinkedIn、官网 | `UNKNOWN` |
| `annual_revenue_band` | 公开财报、行业数据库 | `UNKNOWN` |
| `role` | LinkedIn 职位、官网团队页 | `UNKNOWN` |
| `hs_codes[]` 匹配度 | 买家进口 HS 与我方 HS 的交集 | `NO_MATCH` |
| `payment_behavior_hint` | 海关记录中的贸易条款（如有） | `UNKNOWN` |

**硬规则：`UNKNOWN` 不是 0 分，也不是猜测值。**
缺失字段必须显式标记，评分时**跳过该维度并降低总分置信度**，不允许用行业均值填充——那会让"数据缺失的客户"和"确实不匹配的客户"混在一起。

## 评分模型

总分 100，六个维度。**所有权重放在 `config/scoring.yaml`，不写死在代码里。**

| 维度 | 权重 | 评分依据 | 数据来源 |
|---|---|---|---|
| `demand_fit` 需求匹配 | 30 | HS 编码重合度；进口该品类的频率；近 12 个月是否有采购 | 海关数据 |
| `window` 采购窗口 | 20 | `last_ship_date` 距今：≤90天=满分，91–180=0.6，181–365=0.3，>365=0.1 | 海关数据 |
| `switchability` 可切换性 | 15 | 供应商集中度（前3占比 <50% 满分，>70% 低分）；供应商数量 | 海关数据 |
| `role_access` 决策可达性 | 15 | 是否找到采购/寻源/老板角色；邮箱是否为个人邮箱 | 富化 |
| `scale_fit` 规模匹配 | 10 | 采购量与我方产能/起订量的匹配；过大或过小都扣分 | 海关 + 富化 |
| `reachability` 可达性 | 10 | 邮箱 verified=1.0，risky=0.4，unknown=0.2；有 WhatsApp 同意 +0.2 | 验证结果 |

```python
@dataclass
class ScoreResult:
    total: float                  # 0-100
    breakdown: dict[str, float]   # 每维度得分
    confidence: float             # 0-1，按可用维度加权
    reasons: list[str]            # 中文，给业务员看，每条必须带数字
    missing: list[str]            # 缺失维度
```

`reasons` 的要求（这是能否被使用的关键）：
- ✅ `近 90 天内进口该品类 3 批，处于采购窗口期`
- ✅ `前 3 大供应商占比 42%，正在多方比价`
- ❌ `客户匹配度高`（没有信息量）
- ❌ `AI 认为该客户很有潜力`（不可验证）

## 队列生成

业务员每天打开系统，应该看到 **20–30 条**，不是 2000 条。

`daily_queue` 生成规则：
1. 排除 `SUPPRESSED` / `NOT_INTERESTED` / `NURTURE`（未到唤醒日）
2. `stage == SCORED` 且 `confidence >= 0.6`
3. 按 `total` 降序，同分按 `window` 降序
4. **硬上限 30 条/人/天**（超过这个数字，业务员一定不会认真看）
5. 同一公司只出现一次（取最高分 contact）
6. 每位业务员每日新客户数 ≤ 15，其余额度用于跟进（这是真实业务节奏，不是技术限制）

## 验收

```bash
python -m pytest tests/scoring/ -v
python -m src.cli queue --owner sales01 --date 2026-10-27 --format table
```

必须覆盖：
1. 完全无富化数据的 lead → `confidence < 0.6`，**不进入** daily_queue，且 `missing` 列出全部维度
2. `last_ship_date` 为 400 天前 → `window` 得分 = 0.1 档，不是 0
3. 供应商集中度 85% → `switchability` 明显低分，且 `reasons` 里写明"供应关系稳定，切入难度高"
4. 权重从 yaml 改成总和 ≠ 100 → 启动时报 `ConfigError`，不静默归一化
5. 队列条数超过 30 → 截断，且日志记录被截断的条数

## 不要做的事

- 不要用 LLM 直接输出一个 0–100 的分数。LLM 可以用来**抽取**（从官网文本里抽 `buyer_type`、从职位名映射 `role`），但**打分必须是确定性公式**，否则同样数据跑两次结果不同，业务员会失去信任。
- 不要为了让分数分布"好看"而调参。分数分布偏斜是真实业务的反映。
- 不要在没有 `confidence` 的情况下使用 `total`。60 分低置信和 60 分高置信，对业务员意味着完全不同的动作。
