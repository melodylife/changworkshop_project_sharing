# 审核修改报告 — pi_agent_subagent_workflow

- **日期**: 2026-09-18（第 2 轮，含第 1 轮结果）
- **范围**: `game_creator/` + `tour_planner/` 全部 18 个文件（含新增的 workflow/ 目录）
- **原则**: 只改**注释与文档文本**；未改动任何可执行代码逻辑、函数签名、命令行行为、契约字段名
- **备份**:
  - 第 1 轮前原始版本 → `/tmp/pi_agent_subagent_workflow.bak/`
  - 第 2 轮前（目录重构后）→ `/tmp/pi_agent_subagent_workflow.bak2/`

> 说明：本报告**不复制**被移除的敏感原值（代理地址、真实地名等），只做定性描述，避免报告本身成为泄露源。

---

## 一、第 2 轮新增改动

### 1.1 代理配置 — 已全部移除（本次要求）

| 文件 | 移除内容 |
|------|----------|
| `tour_planner/agents/researcher.md` | 整个 `## Network` 段落（第 1 轮改写、本轮按你的要求彻底删除）：代理环境变量说明 + curl 示例 |
| `tour_planner/workflow/SKILL.md` | Phase 1 中「HTTP 默认走本地代理 / `--no-proxy` / 失败回退」整段说明 |
| `tour_planner/workflow/references/contracts.md` | `images/manifest.json` 示例中的 `network` 字段（含硬编码代理地址与 `via_proxy` 标记） |

结果：全仓库不再出现任何代理地址、代理环境变量或代理开关。

### 1.2 新增/重构文件中的私人信息

| 文件 | 位置 | 原内容（性质） | 处理后 |
|------|------|----------------|--------|
| `tour_planner/workflow/references/contracts.md` | `brief.json` 示例 | **真实出行信息**：目的地/出发地、日期区间、同行人特殊需求说明、预算与必看清单（均为一次真实规划的内容） | 全部改为占位符：`<city, country>` / `<home city>` / `YYYY-MM-DD` / `<体力 / 饮食等同行需求>` / `<必看清单>` 等 |
| 同上 | `research/*.json` 示例 | 同一真实行程的 POI、坐标、季节描述 | 改为 `<POI 名称>` + 中性数值占位 + `<一句话说明为什么选它>` |
| 同上 | `itinerary.json` 示例 | 真实行程标题、目的地、时区、具体景点与午餐点、真实 open_questions | 全部占位化（`<行程标题>` / `<景点名称>` / `<IANA tz>` / `<未能确认的条目>`） |
| 同上 | `images/manifest.json` 示例 | 真实景点名、真实日期、真实 Commons 文件名 | 改为占位符；`network` 字段已删 |
| `tour_planner/workflow/SKILL.md` | 产物目录示例 | 真实目的地 slug（含真实出行月份） | 改为 `YYYY-MM-DD-<slug>` |
| 同上 | Phase 4c 说明 | 「实测中……引入了两处新问题」——绑定到个人一次真实运行 | 改为通用表述「一次定向修复**很可能**同时引入新问题（例如……）」 |
| `game_creator/workflow/game-create/references/contracts.md` | `stitch.json` 示例 | 三个**真实 Stitch 账户 ID**（project / design-system / screen id） | 替换为 `<stitch project id>` / `<stitch design system id>` / `<stitch screen id>` |

### 1.3 结构变化（你已做的重构，我按新路径复核）

- `game_creator/game-create.ts` → `game_creator/workflow/game-create.ts`（第 1 轮改过的版本已保留）
- `tour_planner/trip-plan.ts` → `tour_planner/workflow/trip-plan.ts`（同上）
- 新增 `game_creator/workflow/game-create/SKILL.md`、`.../references/contracts.md`
- 新增 `tour_planner/workflow/SKILL.md`、`.../references/contracts.md`

---

## 二、第 1 轮改动（保留，仍有效）

| 文件 | 改动 |
|------|------|
| `tour_planner/agents/researcher.md` | 真实行程目录示例 → `.pi/plans/<slug>/research/poi.json`（本轮 Network 段已整体删除） |
| `tour_planner/agents/itinerary-critic.md` | `re-audit` 示例块中真实地名/日期 → `Day 2 / Day 3` 通用表述 |
| `tour_planner/agents/itinerary-designer.md` | 「offline and **in China**」→「in any region where a font CDN is unreachable」 |
| `tour_planner/workflow/trip-plan.ts` | 头部注释中的真实出行计划命令示例 → 参数占位符；注释压缩 |
| `game_creator/workflow/game-create.ts` | 删除暴露内部工程结构的「sibling 项目」段落；注释压缩 |

---

## 三、按约定保留的内容（附理由）

| 内容 | 保留理由 |
|------|----------|
| `game-deployer.md` / game SKILL.md / game contracts.md 中的 `127.0.0.1` | 是**演示服务器自身的 loopback 绑定**（通用写法，且明确要求「只绑回环」），不是个人代理配置 |
| `ui-designer.md` 中的 `stitch_*` MCP 工具名 | 第三方工具标准接口名，属工作流说明 |
| `itinerary-designer.md` 的 `The Verge / 少数派` 风格参考 | 通用视觉参考，无可识别个人信息 |
| 所有 `.pi/...` 路径 | pi 框架通用约定路径，非本机绝对路径 |
| 各文件 frontmatter 的 `model:` 字段 | **判断项**，见下 |

---

## 四、需要你决定的一件事

**`model:` 字段（`deepseek/deepseek-flash`、`deepseek/deepseek-v4-flash-vision-exp`）我没有改。**

- 原因：这是 agent 定义必需的运行时配置，改了会改变实际行为；且它出现在 **7 个 agent frontmatter + 2 个 SKILL.md 的 25 处 spawn 模板**里，改一处漏一处反而更糟。
- 若该目录要公开分享：建议全局把 `deepseek/deepseek-flash` 等替换为占位符（如 `<your-model-id>`），并同步改两处（frontmatter + spawn 模板）。你说一声我可以一次性替换。

---

## 五、详细复核结果

| 检查项 | 结果 |
|--------|------|
| 代理地址 / 代理环境变量 / 代理开关 | ✅ 0 命中 |
| 绝对用户路径（`/Users/...`） | ✅ 0 命中 |
| 用户名 / 邮箱 / 频道名 / 密钥字段（`api_key`/`token`/`password`/`secret`） | ✅ 0 命中（仅英文单词 `tokens` 的正常语义） |
| 真实地名 / 真实日期 / 真实账户 ID | ✅ 0 命中（已全部占位化） |
| 第一人称个人信息（我的/我们/本人） | ✅ 0 命中 |
| 家庭 / 亲属信息（父母、长辈、妻儿、同行人身体情况等） | ✅ 0 命中（已改为通用占位符）|
| 文档内 fenced `json` 代码块语法 | ✅ 10/10 全部合法（脚本校验） |
| `127.0.0.1` 出现处 | ✅ 全部为演示服务器 loopback 绑定，保留 |
| 文件总数 | 18 个（+本报告 = 19） |
| 代码逻辑改动 | 无（仅注释与文档文本） |

---

## 六、建议

1. 公开发布前，按第四节统一替换 `model:` 字段。
2. 在项目里加一个 pre-commit 检查，阻止代理地址 / 绝对路径 / 真实地名再次被写进 agent 定义。
