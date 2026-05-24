# Operations Manual — OpenCode Agent Runbook

> **角色**: 你是 Investment Assistant OS 的执行引擎。本文件给你操作指令——执行什么、怎么执行、输出什么。
> **上下文策略**: 先加载 compiled rules（~3K tokens），不要加载完整 SOP（~30K tokens）。仅在规则有歧义或需要深度解释时，才按需加载 SOP 散文。

---

## 加载序列（每次任务启动）

### 必加载 (Phase 0 — Context Bootstrap)
```
1. output/state/system_state.json       ← 当前系统状态（评分/仓位/预警/版本）
2. sop/compiled/rules_L1.json           ← L1 评分规则（US/CN/JP 所有因子阈值）
3. sop/compiled/rules_L2.json           ← L2 评分规则（动量/价值/成长/盈利/规模）
4. sop/compiled/rules_L3.json           ← L3 评分规则（情绪温度 + 量化风险）
5. sop/compiled/weight_matrix.json      ← 全部权重（L1-L3层级 + 因子内 + 交叉验证修正）
6. sop/compiled/position_map.json       ← 评分→仓位映射 + 恒科四象限限仓
7. sop/compiled/triggers.json           ← 15个触发条件阈值 + 推送规则
8. sop/compiled/data_source_map.json    ← 因子→数据源→验证规则
```

### 按需加载
```
sop/三层多因子投研框架.md           ← 评分需要定性判断时
sop/评分可解释性手册.md              ← FF5 解读有歧义时
sop/ai_investment_sop.md           ← 执行 11 阶段完整分析时
sop/原油分析框架.md                  ← 油价突破 $105 或金油比 >25 时
sop/中金黄金三因子分析SOP.md          ← 黄金独立分析时
sop/加密分析框架.md                  ← 稳定币配置分析时
schemas/.schema.json               ← 输出 JSON 格式校验时
```

---

## Phase 1: 数据拉取

### 1.0 一键数据管线（推荐）

```bash
# Step A: ETF 日线数据 → /tmp/
cd repo_skills/skills/tickflow/python
uv run python ../../../scripts/pipeline/fetch_etf_data.py --days=500

# Step B: CN 宏观数据 → output/data/raw_macro_{date}.json
cd repo_skills/scripts/pipeline
uv run python fetch_macro.py
```

如果上述两步均成功，则 `/tmp/` 下有所有 ETF 和指数的 CSV，`output/data/` 下有宏观 JSON。

### 1.1 补充 web_search 指标（管线未覆盖）

| 指标 | 获取方式 |
|------|---------|
| VIX | `web_search` "VIX today" |
| AAII Survey | `web_search` "AAII sentiment survey latest" |
| 非农就业预期 | `web_search` "nonfarm payrolls consensus estimate" |
| 30Y UST | `web_search` 或 FMP API |
| 南向/北向资金 | cn_financial_pro 或 Wind 终端 |
| 信用利差 | FMP API |

### 1.2 量化计算（VaR + FF5 回归）

**前置条件**: Phase 1.0 已成功生成 `/tmp/*_daily.csv`。

```bash
# US FF5 + VaR/CVaR/动量/回撤
cd repo_skills/skills/tickflow/python
uv run python p1_upgrade.py

# CN-FF 因子回归
uv run python cn_ff_regression.py
```

输出文件（自动日期命名）：
- `~/.openclaw/workspace/analysis/p1_upgrade_results_{YYYYMMDD}.json`
- `~/.openclaw/workspace/analysis/cn_ff_results_{YYYYMMDD}.json`

p1_upgrade JSON 包含的字段：`individual.{ticker}.var`（VaR/CVaR/趋势）、`drawdown`（回撤/恢复天数）、`momentum`（1/3/6/12月收益）、`ff5_loadings`（α + 5因子β + t-stats + R²）、`l3_risk_scores`（1-5）、`l2_scores`（基于β的风格评分）

cn_ff JSON 包含：per-ETF 的 R²（vs US FF5）、CN R² 改善幅度、α、CN1-7 因子 loadings + t-stats + significance

---

## Phase 2: 评分

评分流程 — 读取 Phase 1 的原始数据和计算结果，应用 `sop/compiled/rules_L*.json` 中的规则，填入对应的 JSON Schema。

### 2.1 L1 宏观评分 → `scores_L1_{YYYYMMDD}.json`

**Schema**: `schemas/scores_L1.schema.json`
**规则**: `sop/compiled/rules_L1.json`

**步骤**:
1. 从 `raw_macro_latest.json` 读取宏观指标值
2. 按 `rules_L1.json` 每个 factor 的 `scoring_rules` 逐条打分
3. 填写 `data.indicators`（原始值 + 单位和参照）
4. 填写 `rationale`（为什么是这个分数，定性判断）
5. 计算 `us.composite` = 5因子加权平均, `cn.composite` = 5因子加权平均
6. 计算 `composite.value` = us×0.60 + cn×0.40
7. 填写 `assessment`（一句话宏观判断）

**注意**:
- `rules_L1.json` 中的 `_qualitative_note` 是软约束。例如：就业评分即使超预期 2x，但 3 月均值仅 48K/月 → 不给满分 5
- 油价交叉验证规则（`rules_L1.json` `us.cross_validation`）:
  - 布伦特 > $105 → 强制重评通胀因子
  - 油价↑ + 10Y↑ + 黄金↑ 三者同涨 → L1 US 必须下调 ≥0.5

### 2.2 L2 风格因子评分 → `scores_L2_{YYYYMMDD}.json`

**Schema**: `schemas/scores_L2.schema.json`
**规则**: `sop/compiled/rules_L2.json`

**步骤**:
1. 从 `p1_upgrade_results_{YYYYMMDD}.json` 读取 FF5 回归结果和动量数据
2. 从 `cn_ff_results_{YYYYMMDD}.json` 读取 CN-FF 回归结果
3. 按 ETF 选择正确的因子体系：
   - QQQ.US → US FF5
   - 159682.SZ → CN_FF
   - 513130.SH → CN_FF(80%) + US FF5(20%) 混合
   - 513310.SH → US FF5(60%) + CN_FF(40%) 混合
4. 按 `rules_L2.json` 每个 factor 的 `per_etf_scoring` 规则打分
5. 填充每个 factor 的 `per_asset.{ticker}.ff5_beta` / `ff5_t_stat` / `ff5_significant`
6. 等权平均 → factor.score → composite

**注意**:
- 如果 FF5 β 不显著 (t_stat < 1.96)，取中性分数 3
- HSTECH 非对称暴露修正：正常市场 US 暴露 15%，压力市场跳至 40%。判断当前是否压力市场（VIX>25 或 CN PMI<49 或 QQQ 从高点回撤>10%均可视为压力）
- `rules_L2.json` `exposure_matrix` 记录了各 ETF 的 US/CN 暴露

### 2.3 L3 情绪 + 风险评分 → `scores_L3_{YYYYMMDD}.json`

**Schema**: `schemas/scores_L3.schema.json`
**规则**: `sop/compiled/rules_L3.json`

**情绪评分**（权重 0.50）:
1. 从数据拉取获取 VIX, Put/Call, AAII Spread, DXY 趋势, 信用利差
2. 按 `rules_L3.json` `sentiment.factors` 逐条评分
3. 注意 VIX 和 AAII 的方向性：VIX<12=自满风险(1分)，AAII>+20%=逆向过热(5分)

**风险评分**（权重 0.50）:
1. 从 `p1_upgrade_results_{YYYYMMDD}.json` 读取 per-ETF VaR/CVaR/回撤
2. 按 `rules_L3.json` `risk.factors` 逐条评分
3. 等权平均所有 ETF → 因子分数 → composite

### 2.4 综合评分 → `scores_composite_{YYYYMMDD}.json`

**Schema**: `schemas/scores_composite.schema.json`
**规则**: `sop/compiled/weight_matrix.json` + `sop/compiled/position_map.json`

**步骤**:
1. 读取 scores_L1, L2, L3 的 composite 值
2. 加权计算: `composite = L1×0.40 + L2×0.30 + L3×0.30`
3. 包含显式计算过程: `formula` 字段填入具体数值代入
4. 在 `position_map.json` 查找 score → position band
5. 填充 per-asset 分配建议（参考 `position_map.json` `hstech_quadrant_position_limits` 和 `us_cn_allocation_guidelines`）
6. 填写 `assessment`：整体市场状态、核心驱动因子、置信度、主要风险
7. 填写 `scenario_analysis`：上行触发条件、下行触发条件、下一个关键数据

---

## Phase 3: 预警检查

**Schema**: `schemas/alert.schema.json`
**规则**: `sop/compiled/triggers.json`

对 `triggers.json` 中的 15 个触发条件逐条检查：

```
FOR each trigger in triggers.json:
  从 raw_macro 或 raw_market 读取 current_value
  IF current_value meets condition:
    IF NOT (same trigger already alerted within 24h AND deterioration < 20%):
      IF NOT (level == yellow AND yellow_push_count_today >= 1):
        生成 alert.json → output/alerts/
        包含 recommended_action（不能为空）
        包含 throttling 元数据
```

**推送节制规则** (`triggers.json` `push_throttling`):
- 同一触发 24h 内不重复（恶化 >20% 例外）
- 黄色预警每日 ≤ 1 条
- 禁止推送不含操作建议的预警

---

## Phase 4: 状态更新

每次评分/预警完成后，更新 `system_state.json`：

```json
{
  "timestamp": "当前UTC时间",
  "scores": {
    "composite": <综合分数>,
    "L1": <L1分数>, "L2": <L2分数>, "L3": <L3分数>,
    "last_updated": "当前时间"
  },
  "position": {
    "band_label": "<姿态标签>",
    "central_pct": <仓位中枢>,
    "current_actual_pct": <如已知实际仓位>,
    "per_asset": { ... }
  },
  "alerts": { "active_count": <N>, "active_list": [...] },
  "sop_versions": {
    "three_layer_framework": "v1.4",
    "ai_investment_sop": "v2.0",
    ...
  },
  "narrative_context": "<一句话当前核心叙事 — 不超过500字符>",
  "next_scheduled": {
    "next_macro_update": "<下次L1评分时间>",
    "next_data_release": { "date": "<日期>", "event": "<事件>" }
  }
}
```

---

## Phase 5: 输出结论

给用户输出 Markdown 结论报告，按以下固定结构：

```markdown
## 每日评分报告 — {YYYYMMDD}

### L1 宏观环境 — {US分数}/{CN分数} → {L1综合}

| 因子 | US | CN | 关键驱动 |
|------|:--:|:--:|----------|
| ... | | | |

**宏观判断**: <一句话>

### L2 风格因子 — {L2综合}

| 因子 | 分数 | 含义 |
|------|:----:|------|
| 动量 | | |
| 价值 | | |
| 成长 | | |
| 盈利 | | |
| 规模 | | |

**风格判断**: <一句话>

### L3 情绪与风险 — {L3综合}

情绪 {分数} | 风险 {分数} | VIX {value} | VaR趋势 {方向}

### 综合评估

**积分: {L1}×0.40 + {L2}×0.30 + {L3}×0.30 = {最终分数}**

**仓位中枢: {X%-Y%}（{姿态}）**
**较上次: {变化}**

### 当前仓位建议

| 资产 | 代码 | 角色 | 建议 | 上限% | 理由 |
|------|------|------|------|-------|------|
| ... | ... | 进攻/防御/现金 | 增持/持有/减持 | | |

### 活跃预警

| 触发 | 级别 | 当前值 | 阈值 | 建议操作 |
|------|:----:|--------|------|----------|
| ... | 🔴 | | | |

### 情景推演

| 情景 | 概率 | 仓位调整 |
|------|:----:|----------|
| 上行: <条件> | % | |
| 下行: <条件> | % | |
```

---

## 关键规则

1. **数据优先于定性判断**：评分必须有原始数据支撑
2. **交叉验证**：市场数据 TickFlow 主，qveris 验证；宏观数据 qveris 主，标注官方发布机构
3. **可解释性**：每个分数必须有 `rationale`（为什么是这个分数，不是更高/更低）
4. **安全边际**：仓位上限 85%，回撤 10%=审查，15%=暂停
5. **降级留痕**：数据源不可用标注「临时数据源」，TickFlow 恢复后修正
6. **状态持久化**：每次评分后必须更新 `system_state.json`
