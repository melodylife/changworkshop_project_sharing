---
name: trip-plan
description: >
  Multi-agent trip planning workflow. Collects a travel brief, materializes
  destination evidence, fans out parallel researchers, synthesizes a structured
  itinerary, audits its feasibility, then renders one self-contained HTML
  report. Use when asked to "plan a trip", "make an itinerary", "做个行程",
  "旅行计划", or "帮我规划旅行". Requires the pi-herdr-agents extension running
  inside herdr.
---

# Trip Plan

Turn a short travel brief into a **self-contained HTML trip report**.

**Announce at start:** "我先问几个问题，然后会派几个研究员并行去搜集目的地资料，再排行程、做可行性检查，最后生成一份 HTML 行程报告。"

## The flow

```
Phase 0  Brief       main session — questionnaire → brief.json
Phase 1  Evidence    main session — .pi/skills/trip-evidence/collect_evidence.py → evidence.json
Phase 2  Research    3 parallel `researcher` children → research/*.json
Phase 3  Synthesize  itinerary-synthesizer → itinerary.json + itinerary.md
Phase 4  Audit       itinerary-critic → critique.md     ← before pretty, not after
Phase 5  Render      itinerary-designer → design.md + shell.html
                     itinerary-generator → trip.html
Phase 6  Deliver     main session — checklist, then hand the file over
```

The parent owns every phase transition, the artifact directory, and the final
delivery. All five roles are leaves.

Phases are **sequential**. Each one consumes the previous phase's artifact, so
do not parallelize across them. (Phase 2 is the only fan-out point.)

---

## Runtime

All five roles pin the same model in their own frontmatter:
`model: deepseek/deepseek-flash`.

So a spawn that omits `model` still runs on `deepseek/deepseek-flash`. The spawn
templates below pass the same ID explicitly — **a tool argument always overrides
frontmatter**, so if you ever change the model, change it in both places.

Set `thinking` on every spawn. It is the only per-role runtime difference here:

| Child | Thinking | Why |
| --- | --- | --- |
| `researcher` | `low` | Bounded fact collection; volume, not depth |
| `itinerary-synthesizer` | `high` | The one step where reasoning quality decides the trip |
| `itinerary-critic` | `medium` | Mostly mechanical checks plus judgement |
| `itinerary-designer` | `medium` | Design-system decisions |
| `itinerary-generator` | `medium` | Faithful application, not invention |

Omitting `thinking` inherits the parent level — a discouraged fallback.

Before the first run, confirm the ID resolves: `/subagent list` shows each role
and its source, and the model list confirms `deepseek/deepseek-flash` is
authenticated. Do not guess an ID at launch time.

## 确认门与升级（关键）

**不要把问题攒到最后。** 任何一个会改变行程可行性、或需要用户拍板的缺口，**当轮就停下来问**。最终报告里的「需要你确认」只应该是**仍未解决**的条目，不是一堆积压问题的倾倒场。

### 什么算「必须当场问」

- 预约 / 购票要求未知，且影响能否成行
- 关键景点开放时间未知，而行程把到达时间卡在临界点
- 价格缺失，而预算是硬约束
- **数据源整体失败**（证据缺一大块），后续判断都建在沙子上
- 天气让某天的户外安排不可行
- P0 修不好

### 什么不算（记录即可，不要打断）

- 次要景点的时间精度
- 已标为 `待确认`、且不影响行程结构的空缺
- 用户下单前本来就会自己核实的信息

### 怎么问

**一次问完，最多 3 条。** 每条给出：问题 + 为什么重要 + 你建议怎么办。不要把 14 条一口气倒出来。

### 子代理求助

子代理真正卡住时可以用 `caller_ping` 向父会话求助。父会话收到后决定自己回答，还是升级给用户。不要为了等答案而轮询。

### 升级路径

```
子代理发现缺口 → 在结果里如实报告（不自行编造、不静默跳过）
      ↓
父会话在阶段边界判断：material？
      ├ 是 → 立即暂停，最多 3 条问用户，拿到答复再继续
      └ 否 → 记进 open_questions，继续
      ↓
最终报告只列**仍未解决**的条目，按「阻塞 / 影响体验 / 仅记录」三档
```

## Fire-and-forget completion

`subagent` is fire-and-forget. After each spawn:

1. End the parent turn.
2. Let automatic completion delivery resume the parent with the child's result.
3. Continue from that delivered result.

Do **not** poll, list, sleep, tail session files, or wait-loop for child status.

## Artifact directory

Pick a slug from the destination and start date, for example
`YYYY-MM-DD-<slug>`, and use one run directory for everything:
`.pi/plans/YYYY-MM-DD-<slug>/`. Pass absolute or repo-relative paths explicitly
in every child task. Shapes are defined in
[`references/contracts.md`](references/contracts.md) — read it before Phase 2.

Keep the **full absolute run directory path** in every child task. Children do
not share the parent's memory of it.

---

## Phase 0 — Brief (main session)

Ask the traveller directly, in the main session. Keep it to one round of
questions — this is a conversation, not a form. Cover:

- destination and origin
- exact start and end dates
- party size, ages, and mobility or dietary needs
- budget level
- pace: relaxed / balanced / packed
- interests, must-see, must-avoid
- any hard constraint (closed days, no early starts, no long walks)

Write `brief.json` per the contract. Ask the user to confirm it before spending
any research budget — this is the cheapest place to fix a misunderstanding.

## Phase 1 — Evidence (main session)

Run the evidence script. It is free and needs no API key:

```bash
python3 .pi/skills/trip-evidence/collect_evidence.py \
  --city "<destination>" --start <YYYY-MM-DD> --end <YYYY-MM-DD> \
  --radius 6000 \
  --out .pi/plans/<slug>/evidence.json
```

Then read `evidence.json` and check its `errors` array.

**→ 确认门 A（现在就问，不要等）**：只要有数据源整体失败（AQI 被拦、Overpass 镜像不可用、POI 被截断），当场告诉用户，并问要不要定向补查。不要带着一个已知的大洞往下跑 —— 后面每一步都会建在沙子上。

This is the **evidence materialization** step: children receive pinned facts
instead of each re-fetching (and re-failing) on their own.

## Phase 2 — Research (fan out)

Spawn **three researchers in parallel**, one per class. Launch all three, then
end the turn. Each writes its own artifact:

```typescript
subagent({
  name: "Research: POI",
  agent: "researcher",
  model: "deepseek/deepseek-flash",
  thinking: "low",
  task: `Class: poi. Destination: <destination>.
Centre: <lat>,<lon> Radius: 6000m. Dates: <start>..<end>.
Interests from the brief: <interests>.
Hard constraints: <constraints>.
Use the request shapes in `.pi/skills/trip-evidence/collect_evidence.py`. Overpass requires a
User-Agent header.
Write raw findings to .pi/plans/<slug>/research/poi.json
Return under 4000 characters: counts, top-ranked items with one-line reasons,
and every unknown. Do not paste raw API output.`,
});

subagent({
  name: "Research: Weather",
  agent: "researcher",
  model: "deepseek/deepseek-flash",
  thinking: "low",
  task: `Class: weather. Destination: <destination>. Dates: <start>..<end>.
Centre: <lat>,<lon>.
Write raw findings to .pi/plans/<slug>/research/weather.json
Return under 4000 characters: daily high/low/precipitation, which days are
best for outdoor vs indoor, and every unknown.`,
});

subagent({
  name: "Research: Food",
  agent: "researcher",
  model: "deepseek/deepseek-flash",
  thinking: "low",
  task: `Class: food. Destination: <destination>.
Centre: <lat>,<lon> Radius: 6000m. Dates: <start>..<end>.
Dietary constraints from the brief: <dietary>.
Write raw findings to .pi/plans/<slug>/research/food.json
Return under 4000 characters: counts, top-ranked items by area, and every
unknown.`,
});
```

If a researcher returns `errors` or thin coverage, say so **now**.

**→ 确认门 B**：把三个 researcher 的 `unknowns` 汇总，挑出**会改变可行性**的那些（预约要求、检票口开放时间、票价、天气导致的户外风险），当场问用户；其余记进 `open_questions`。

Do not silently re-run a researcher with a different model — a stated gap is
better than hidden retry loops. If a gap is worth filling, say what it is and ask
before spending the budget.

## Phase 3 — Synthesize

```typescript
subagent({
  name: "Synthesize itinerary",
  agent: "itinerary-synthesizer",
  model: "deepseek/deepseek-flash",
  thinking: "high",
  task: `Build the itinerary.
Run directory: .pi/plans/<slug>/
Read: brief.json, evidence.json, research/poi.json, research/weather.json,
research/food.json
Conform exactly to .pi/skills/trip-plan/references/contracts.md.
Write itinerary.json and itinerary.md into the run directory.
Every stop needs lat/lon, duration_min and transport. Never invent a value.
Return: artifact paths, day-by-day one-line shape, stop count, open_questions.`,
});
```

## Phase 4 — Audit → repair → re-audit（有界循环）

Run this **before** rendering. Once the plan is pretty, nobody questions it.

### 4a · 首轮审计

```typescript
subagent({
  name: "Feasibility audit",
  agent: "itinerary-critic",
  model: "deepseek/deepseek-flash",
  thinking: "medium",
  task: `Mode: first-pass.
Audit .pi/plans/<slug>/itinerary.json for physical feasibility.
Run: python3 .pi/skills/trip-validate/validate_itinerary.py .pi/plans/<slug>/itinerary.json
Treat its output as evidence, not a verdict, then apply your full checklist.
Write .pi/plans/<slug>/critique.md.
Return only the verdict line and the P0/P1 findings.`,
});
```

Triage:

- **P0**（不可行 / 违反硬约束）→ 必须修
- **P1**（会损坏行程）→ 修，除非用户明确接受这个取舍
- **P2** → 记入报告的「需要你确认」，继续
- **需要用户拍板的** → **立即问**（见确认门）

### 4b · 定向修复

**不要让整条流水线重跑。** 给 synthesizer 一个**指名道姓的**修复任务：哪一天、哪个 stop、最小改法是什么，以及**不要动什么**。

```typescript
subagent({
  name: "Fix: <day> <stop>",
  agent: "itinerary-synthesizer",
  model: "deepseek/deepseek-flash",
  thinking: "high",
  task: `目标修复，不要重构。
Run directory: .pi/plans/<slug>/
Read critique.md, then fix ONLY these findings: <P1-1, P1-3>
Constraints:
- 只改涉及到的天与 stop，其他天逐字不变
- 不新增 stop
- 同步更新 itinerary.md —— 两个文件必须一致
- 任何无法在不违反契约的前提下修好的条目，保留在 open_questions，不要偷偷删掉
Report: 改了哪些 stop，以及每条 finding 的对应改法。`,
});
```

**关键**：修复任务里必须写「**不要动什么**」。没有这句话，synthesizer 会顺手重排整份行程，然后你得到一批全新的、从没人审计过的问题。

### 4c · 增量复审（最容易被跳过的一步）

```typescript
subagent({
  name: "Re-audit after fix",
  agent: "itinerary-critic",
  model: "deepseek/deepseek-flash",
  thinking: "medium",
  task: `Mode: re-audit.
Run directory: .pi/plans/<slug>/
Previous findings: 先读 critique.md。本轮修复目标：<P1-1, P1-3>
1) 逐条给出 CLOSED / PARTIAL / NOT FIXED，并附上证明数字。
2) 主动寻找**修复引入的回归**：把被改动的那几天逐 stop 对比，重读整天，
   并确认 itinerary.md 与 itinerary.json 仍然一致。
   任何「不在修复范围内却变了」的地方，一律当作回归上报。
把 Re-audit 段**追加**进 critique.md，不要覆盖首轮。
Return: verdict + 闭合表 + 回归。`,
});
```

**为什么必须单独做这一步**：一次定向修复很可能同时引入新问题（例如把午餐排到 15:35，或让文档内部自相矛盾）。**只验证「原来的问题修好了」，就会把新问题一起放行。**

### 4d · 循环预算

- 最多 **2 轮** 修复 → 复审
- 每轮都要报告：闭合了什么、**新开了什么**
- 一轮「闭合 1 条、新开 2 条」= **失败的一轮**，必须如实说明
- 2 轮后仍有 P0/P1 → **停下来问用户**，不要无限循环

## Phase 5 — Render

顺序：**取图 → 设计 → 填内容 → 内联图片**。首尾两步是脚本，中间两步是子代理。

### 5a · 取图（脚本 · 字节不进模型）

```bash
python3 .pi/skills/trip-images/fetch_images.py \
  --itinerary .pi/plans/<slug>/itinerary.json \
  --out-dir .pi/plans/<slug>/images --max-width 640
```

只取**已经进入 `itinerary.json` 的 stop**（约 15 张），不是研究阶段那 40 个候选 —— 这是成本控制的第一道闸。图片字节全程不经过模型上下文。

然后读 `images/manifest.json` 看覆盖情况：命中几张、缺哪几张。缺的 stop 就不放图，**不要用占位图凑**。

### 5b · 设计系统

Design first, then content. The generator reads the designer's output.

```typescript
subagent({
  name: "Design system",
  agent: "itinerary-designer",
  model: "deepseek/deepseek-flash",
  thinking: "medium",
  task: `Design the report for .pi/plans/<slug>/.
Read brief.json, itinerary.json, itinerary.md.
Write design.md and shell.html into the run directory.

Section order is fixed and the itinerary comes FIRST:
  #top 标题块 → #itinerary 行程 → #decisions 需要你确认（折叠）
  → #prep 行前准备 → #credits 署名
Put nothing between the title block and day one. The decisions section sits
after the itinerary, collapsed, with a real header row (count + what is inside)
so it is still discoverable. Design a **decision card** component: 问题 → 选项(每个
写 好处/代价) → 建议. No data sources, file names or audit codes anywhere in it.

Editorial, typography-driven, muted palette. System font stack, CJK-first.
Everything inline — no CDN, no external font, no remote image.
Return: artifact paths, palette, section order + ids, slot markers.`,
});

// after the designer's result arrives:

subagent({
  name: "Render report",
  agent: "itinerary-generator",
  model: "deepseek/deepseek-flash",
  thinking: "medium",
  task: `Render the final report for .pi/plans/<slug>/.
Read design.md, shell.html, itinerary.json, itinerary.md, brief.json,
critique.md.
Write .pi/plans/<slug>/trip.html — one self-contained file.
Content comes only from itinerary.json. Unknowns render as 待确认.

Section order from design.md: #top → #itinerary → #decisions → #prep → #credits.
The itinerary goes FIRST with nothing before it. Everything still open
(open_questions, open P0/P1) goes into #decisions AFTER the itinerary, wrapped in
<details> and collapsed. One card per decision: 问题一句 → 2–3 个选项（每个写
好处/代价）→ 建议。**Rewrite them as choices — never paste an open_questions
string或 critic finding, and never mention data sources, file names or audit
codes.** #prep is a one-line-per-item packing checklist.

Keep the OpenStreetMap (ODbL) and Wikivoyage (CC BY-SA) credits footer.
Run the five self-checks in your role definition and report the results.`,
});
```

### 5d · 内联图片（脚本 · 收尾）

```bash
python3 .pi/skills/trip-images/embed_images.py \
  .pi/plans/<slug>/trip.html --in-place
```

generator 只写 `src="images/…"`；这一步把字节换成 data URI，最终文件才真正 self-contained。

**必须由父会话执行，绝不能让 generator 自己贴 base64** —— 那会把 1MB 量级的文本两次灌进模型上下文，纯粹烧钱。

## Phase 6 — Deliver

Before handing the file over, verify:

1. Phase 0 brief was confirmed by the user?
2. Phase 1 `evidence.json` `errors` were reported **at the time**, not at the end?
3. All three researchers delivered, and material gaps were raised as they appeared?
4. Every stop in `itinerary.json` has coordinates?
5. The critic ran **before** rendering, and every P0/P1 is either closed or explicitly surfaced?
6. After any repair round: was closure verified **and** was a regression check run?
7. `images/manifest.json` read, and missing images omitted rather than faked?
8. `embed_images.py` run, and no `images/` reference left in the final file?
9. Does the itinerary come **first**, with nothing between the title block and
   day one?
10. Is the 需要你确认 section collapsed, **after** the itinerary, and still
    discoverable (header row with a count)?
11. Is every open item written as a **choice** — 问题 / 选项(好处·代价) / 建议 —
    with no data sources, file names or audit codes?
12. Is 行前准备 a one-line-per-item checklist?
13. Credits footer present, including per-image author + licence?
14. Nothing in the report claims a price, opening hour, or travel time that the
    source data did not state?
15. Was every question that needed the user asked **when it appeared**, rather
    than batched into the final message?

Then give the user the path to `trip.html` plus a short summary: day-by-day
one-liners, any `open_questions`, and every unresolved critic finding.

## Style rules

- **Never invent** prices, opening hours, travel times, or addresses. Use `null`
  and surface it as `待确认`.
- **Coordinates or it does not exist.** A stop without `lat`/`lon` cannot be
  mapped and cannot be audited for transit time.
- **Visa, entry, and safety information is out of scope.** State plainly that it
  must be confirmed through official channels. Do not let a child generate it.
- Prefer a visible gap over a confident guess, every single time.
