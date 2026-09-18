---
name: game-create
description: >
  Multi-agent web-game creation workflow. Collects a game brief, designs a small
  front-end game, reviews it as a player, designs its screens with Stitch, fans
  out parallel module developers, integrates them into one runnable game, runs
  one full QA pass, repairs failures in bounded rounds, then serves it on a local
  HTTP server and hands back the URL. Use when asked to "make a game",
  "做个游戏", "写个小游戏", "game demo", or "游戏创作".
---

# Game Create

Turn a short game brief into a **playable browser game served on localhost**.

**Announce at start:** "我先问几个关于游戏的偏好问题，然后会做设计、请设计师用 Stitch 出界面、派多个开发者并行写模块，再集成、QA 测试，最后在本机起一个服务把链接给你。"

## The flow

```
Phase 0  Brief        main session  — questionnaire → brief.json
Phase 1  Design       game-designer → design.json + design.md
Phase 2  Review       game-critic   → review.md        ← 玩家视角，先评审再动手
Phase 3  Repair       game-designer → design.json (fixed)   [only if P0/P1]
         Re-review    game-critic   → review.md (appended)  [bounded rounds]
Phase 4  UI           ui-designer   → stitch.json + ui-spec.md   (Stitch MCP)
Phase 5  Build        dev-core · dev-player · dev-input · dev-ui   ← parallel, 4 children
Phase 6  Integrate    dev-manager   → index.html + src/main.js + integration-report.md
Phase 7  QA           qa-tester     → qa-report.md + qa-report.json
Phase 8  Repair loop  owning developer → dev-manager re-integrate → qa-tester re-run
Phase 9  Deploy       game-deployer → server.json + URL
Phase 10 Deliver      main session  — hand the URL to the user
```

The parent owns every phase transition, the run directory, and the final
delivery. All seven roles are leaves (`spawning: false`).

Phases are **sequential** except Phase 5, which is the single fan-out point. Each
phase consumes the previous phase's artifact — sequencing here is the design, not
a compromise.

---

## Runtime

Every role pins the same model in its own frontmatter:
`model: deepseek/deepseek-flash`, except `ui-designer` and `qa-tester`, which pin
`deepseek/deepseek-v4-flash-vision-exp` so they can read screen images.

The spawn templates below pass the same ID explicitly — **a tool argument always
overrides frontmatter**, so if the model ever changes, change it in both places.

Set `thinking` on every spawn. It is the only per-role runtime difference:

| Child | Thinking | Why |
| --- | --- | --- |
| `game-designer` | `high` | The one step where reasoning quality decides the game |
| `game-critic` | `medium` | Judgement plus mechanical lint |
| `ui-designer` | `medium` | Design decisions, then mechanical tool calls |
| `game-developer` | `high` | Code that must satisfy an interface exactly |
| `dev-manager` | `high` | Integration is where parallel work breaks |
| `qa-tester` | `medium` | Systematic checking, not invention |
| `game-deployer` | `low` | Mechanical: serve, curl, report |

Omitting `thinking` inherits the parent level — a discouraged fallback.

Before the first run, confirm the IDs resolve: `/subagent list` must show all
seven roles with source `project`. Do not guess a model id at launch time.

## 确认门与升级（关键）

**不要把问题攒到最后。** 任何会改变游戏能不能做、或者需要用户拍板的缺口，**当轮就停下来问**。最终交付里的待确认项只应该是**仍未解决**的条目。

### 什么算「必须当场问」

- 游戏类型 / 核心玩法本身没定，做出来大概率不是用户想要的
- 评审给出的 **P0 修不好**（设计层面自相矛盾，需要用户取舍）
- **Stitch 有屏幕返回 `unavailable`** —— 是继续用自绘方案，还是换一个界面方向
- 范围冲突：用户要的玩法放不进"无后端、单屏、3 分钟内"的 demo 规格
- QA 两轮修复后仍有 P0

### 什么不算（记录即可，不要打断）

- 某个数值的调参（速度、刷新率）
- 已标为待确认、且不影响能否玩起来的空缺
- 用户本来就会自己试出来的手感问题

### 怎么问

**一次问完，最多 3 条。** 每条给出：问题 + 为什么重要 + 你建议怎么办。

### 子代理求助

子代理真正卡住时用 `caller_ping` 向父会话求助；父会话决定自己回答还是升级给用户。不要为了等答案而轮询。

## Fire-and-forget completion

`subagent` is fire-and-forget. After each spawn:

1. End the parent turn.
2. Let automatic completion delivery resume the parent with the child's result.
3. Continue from that delivered result.

Do **not** poll, list, sleep, tail session files, or wait-loop for child status.

> Exception, one place only: the **Stitch** wait rule in Phase 4 is a 300-second
> sleep *inside* the `ui-designer` child's own turn, not the parent polling for a
> child. See Phase 4.

## Run directory

Pick a slug from the game and date, for example `2026-09-17-neon-runner`, and use
one run directory for everything: `.pi/games/2026-09-17-neon-runner/`.

Pass the **full absolute run directory path** in every child task. Children do
not share the parent's memory of it.

Artifact shapes are pinned in
[`references/contracts.md`](references/contracts.md) — read it before Phase 1.

```
.pi/games/<slug>/
├── brief.json              Phase 0
├── design.json  design.md  Phase 1 (+ Phase 3 repair)
├── review.md              Phase 2 (+ Phase 3 re-review, appended)
├── stitch.json  ui-spec.md Phase 4
├── src/{core,player,input,ui,main}.js · styles.css · index.html · package.json  Phase 5–6
├── build-report.json  integration-report.md   Phase 6
├── qa-report.json  qa-report.md               Phase 7
└── server.json                                Phase 9
```

---

## Phase 0 — Brief (main session)

Ask the player directly, in the main session. One round of questions — this is a
conversation, not a form. Cover:

- genre or a reference game they like (`打砖块 / 下沉跑酷 / 弹幕 / 解谜`)
- the one-sentence fantasy: what should the player feel? (`手忙脚乱 / 掌控感 / 一次比一次更远`)
- visual direction (`像素复古 / 极简编辑风 / 霓虹街机`)
- difficulty (`轻松 / 有挑战 / 硬核`)
- controls (`键盘 / 键盘+手柄`)
- language for on-screen copy (`中文 / English`)

Write `brief.json` per the contract, then **confirm it with the user before
spending any design budget** — this is the cheapest place to fix a
misunderstanding.

## Phase 1 — Design

```typescript
subagent({
  name: "Design game",
  agent: "game-designer",
  model: "deepseek/deepseek-flash",
  thinking: "high",
  task: `Mode: first-pass.
Run directory: <ABSOLUTE run dir>
Read: brief.json, and .pi/skills/game-create/references/contracts.md
Write design.json and design.md into the run directory.
Keep it demo-sized: front-end only, single screen, session_seconds <= 180,
vanilla ES modules on canvas, no build step, no network, no external assets.
Every control declares real key codes plus an arcade/Gamepad mapping.
Declare acceptance criteria a script can check against observable state.
Return: artifact paths, one-line pitch, intent list, screen ids, criteria count,
open_questions.`,
});
```

## Phase 2 — Review (as a player, before any code)

```typescript
subagent({
  name: "Review design",
  agent: "game-critic",
  model: "deepseek/deepseek-flash",
  thinking: "medium",
  task: `Mode: first-pass.
Run directory: <ABSOLUTE run dir>
Read brief.json, design.json, design.md.
First run: python3 .pi/skills/game-design-check/validate_design.py <run dir>/design.json
Treat that as evidence, not a verdict, then apply your full checklist.
Write review.md.
Return only the verdict line and the P0/P1 findings.`,
});
```

Triage:

- **P0** → must fix before any build work
- **P1** → fix, unless the user explicitly accepts the trade-off
- **P2** → record, continue
- **needs the user to decide** → ask now (确认门)

**→ 确认门 A**：如果 P0 是「玩法本身不成立」或者需要用户取舍，**当场问**，不要带着一个自己都知道不行的玩法往下做。

## Phase 3 — Repair the design (bounded rounds)

Only if the review returned P0/P1. Never re-run the whole pipeline for one fix.

```typescript
subagent({
  name: "Fix design: <finding ids>",
  agent: "game-designer",
  model: "deepseek/deepseek-flash",
  thinking: "high",
  task: `Mode: repair. 目标修复，不要重构。
Run directory: <ABSOLUTE run dir>
Read review.md, then fix ONLY these findings: <P1-1, P1-3>
Constraints:
- 只改涉及到的字段，其他字段逐字不变
- 不新增实体 / 关卡 / 意图来补偿
- 同步更新 design.md —— 两个文件必须一致
- 修不好的条目保留在 open_questions，不要偷偷删掉
Return: 每条 finding 对应改了哪个字段，old → new。`,
});
```

Then a **separate re-review** — this is the step that normally gets skipped:

```typescript
subagent({
  name: "Re-review design",
  agent: "game-critic",
  model: "deepseek/deepseek-flash",
  thinking: "medium",
  task: `Mode: re-audit.
Run directory: <ABSOLUTE run dir>
Read review.md first. Findings under repair: <P1-1, P1-3>
1) 逐条给出 CLOSED / PARTIAL / NOT FIXED，并附上证明的字段与值。
2) 主动找**修复引入的回归**：对比整份 design.json，不只是被改的字段。
   任何「不在修复范围内却变了」的地方，一律当回归上报。
把 Re-audit 段**追加**进 review.md，不要覆盖首轮。
Return: verdict + 闭合表 + 回归。`,
});
```

**Loop budget:** at most **2** repair → re-review rounds. Each round reports what
closed **and what it opened**. A round that closes one finding and opens two is a
**failed round** and must be reported as one. After 2 rounds with P0/P1 still
open: **stop and ask the user**, do not loop.

## Phase 4 — UI design (Stitch MCP)

```typescript
subagent({
  name: "Design screens (Stitch)",
  agent: "ui-designer",
  model: "deepseek/deepseek-v4-flash-vision-exp",
  thinking: "medium",
  task: `Run directory: <ABSOLUTE run dir>
Read brief.json, design.json, design.md, review.md.
Create one Stitch project, create its design system FIRST, then generate one
screen per design.json.screens entry at the game.viewport aspect ratio.
STITCH TIMEOUT RULE: a late/empty/error response from generate_screen_from_text
does NOT mean failure and must NEVER be retried. Sleep 300, then pull with
list_screens; if the screen is there, use it. Only after 10 further 30s polls is
a screen 'unavailable' — and then you design that one screen yourself.
Write stitch.json and ui-spec.md (tokens + per-screen layout + element→intent
bindings + component states). No external images, no web fonts.
Return: artifact paths, project id, design system id, per-screen status, tokens,
and any screen you designed yourself.`,
});
```

**→ 确认门 B**：`stitch.json` 里任何 `status: "unavailable"` 的屏幕都是需要用户知道的取舍点，当轮说明。

Do not re-fire a Stitch generation for a screen that already landed — duplicates
are worse than a self-designed screen.

## Phase 5 — Build (parallel fan-out)

Four children, four files, zero overlap. Launch all four, then end the turn.

```typescript
// 1
subagent({
  name: "Build core",
  agent: "game-developer",
  model: "deepseek/deepseek-flash",
  thinking: "high",
  task: `Module: core. You own EXACTLY <run dir>/src/core.js — write no other file.
Run directory: <ABSOLUTE run dir>
Read design.json and .pi/skills/game-create/references/contracts.md.
Implement the game loop, state machine, spawner, scoring and difficulty ramp.
Export createCore(...) exactly as the contract specifies. Import-safe: no DOM or
global access at import time. All randomness through the injected rng.
Verify: node --check src/core.js  &&  node --input-type=module -e "await import('./src/core.js')"
Return: file path, exported interface, assumed values, both commands' output.`,
});

// 2
subagent({
  name: "Build player",
  agent: "game-developer",
  model: "deepseek/deepseek-flash",
  thinking: "high",
  task: `Module: player. You own EXACTLY <run dir>/src/player.js — write no other file.
Run directory: <ABSOLUTE run dir>
Read design.json and .pi/skills/game-create/references/contracts.md.
Implement the player entity: movement, physics, collision resolution, lives.
Export createPlayer(...) exactly as the contract specifies. Import-safe.
Verify: node --check src/player.js  &&  node --input-type=module -e "await import('./src/player.js')"
Return: file path, exported interface, assumed values, both commands' output.`,
});

// 3
subagent({
  name: "Build input",
  agent: "game-developer",
  model: "deepseek/deepseek-flash",
  thinking: "high",
  task: `Module: input. You own EXACTLY <run dir>/src/input.js — write no other file.
Run directory: <ABSOLUTE run dir>
Read design.json and .pi/skills/game-create/references/contracts.md.
Implement keyboard + Gamepad (arcade) handling mapped onto the intent vocabulary.
Export createInput(...), INTENTS and DEFAULT_KEYMAP exactly as the contract
specifies. Every intent in design.json.controls must have a keyboard binding AND
a gamepad binding. Import-safe: no listeners attached at import time.
Verify: node --check src/input.js  &&  node --input-type=module -e "await import('./src/input.js')"
Return: file path, the exported keymap as a compact table, assumed values.`,
});

// 4
subagent({
  name: "Build UI",
  agent: "game-developer",
  model: "deepseek/deepseek-flash",
  thinking: "high",
  task: `Module: ui. You own EXACTLY <run dir>/src/ui.js and <run dir>/styles.css.
Run directory: <ABSOLUTE run dir>
Read design.json, ui-spec.md, and .pi/skills/game-create/references/contracts.md.
Implement HUD, menus, overlays and the game-over screen to the ui-spec tokens
(they are CSS custom properties — put them in styles.css).
Export createUI(...) exactly as the contract specifies. Import-safe. No external
images, no web fonts, no webfont CDN.
Verify: node --check src/ui.js  &&  node --input-type=module -e "await import('./src/ui.js')"
Return: file paths, exported interface, every ui-spec element you did NOT
implement, assumed values.`,
});
```

If a developer reports an `assumed` value that contradicts the design, say so
**now** rather than letting integration discover it.

## Phase 6 — Integrate

```typescript
subagent({
  name: "Integrate game",
  agent: "dev-manager",
  model: "deepseek/deepseek-flash",
  thinking: "high",
  task: `Integrate the four modules into one runnable game.
Run directory: <ABSOLUTE run dir>
Read design.json, ui-spec.md, all of src/*.js, and
.pi/skills/game-create/references/contracts.md.
Write index.html, src/main.js, package.json ({"type":"module"}), and
integration-report.md.
Expose the mandatory headless test hook globalThis.__game
({ready, init, step, state, setIntent, reset}) — QA drives the game through it,
so state() must return plain JSON.
Adapt interface mismatches at the wiring layer only; never rewrite a module
another developer owns.
Then run: python3 .pi/skills/game-build-check/check_build.py <run dir>
Fix every P0 it reports.
Return: files written, the check summary line, mismatches, assumed values, and
what is still not wired.`,
});
```

## Phase 7 — QA (one pass, all tests, one report)

```typescript
subagent({
  name: "QA pass",
  agent: "qa-tester",
  model: "deepseek/deepseek-v4-flash-vision-exp",
  thinking: "medium",
  task: `Run the complete QA pass. One pass, every checklist item, one report.
Run directory: <ABSOLUTE run dir>
Run: python3 .pi/skills/game-qa/qa_playtest.py <run dir> --json
Then apply the full checklist in your role definition — keyboard and arcade
intent coverage, playability, screen flow, acceptance criteria one by one.
Write qa-report.md (and qa-report.json is produced by the script).
Do not fix anything. Never mark an unchecked item as passed.
Return: verdict, failing checks with their evidence numbers, UNVERIFIED list,
and which module owns each failure (core|player|input|ui|integration).`,
});
```

## Phase 8 — Repair loop (bounded)

If QA returns FAIL, spawn **only the owning developer** for the failing module —
plus `dev-manager` again if the failure is `integration`. Never re-run all four.

```typescript
subagent({
  name: "Fix: <module> <finding ids>",
  agent: "game-developer",     // or dev-manager when the failure is integration
  model: "deepseek/deepseek-flash",
  thinking: "high",
  task: `Targeted repair, 不要重构。
Run directory: <ABSOLUTE run dir>
Read qa-report.md, then fix ONLY these findings: <P0-1, P1-2>
Constraints:
- 只改你负责的文件，其他模块一个字都不动
- 不新增功能、不重命名导出、不调接口
- 修不好的条目如实报告，不要偷偷绕过或让测试恒真
Return: 每条 finding 的改法与验证命令。`,
});
```

Then `dev-manager` re-integrates if module exports changed, and `qa-tester`
re-runs a **fresh full pass** (not just the failed checks — a fix that breaks a
neighbouring check is the classic regression).

**Loop budget:** at most **2** repair rounds. Report each round's closure and
regressions. After 2 rounds with P0 still open: **ask the user**; do not loop.

## Phase 9 — Deploy

```typescript
subagent({
  name: "Serve game",
  agent: "game-deployer",
  model: "deepseek/deepseek-flash",
  thinking: "low",
  task: `Serve the finished game and prove it is reachable.
Run directory: <ABSOLUTE run dir>
Run: python3 .pi/skills/game-serve/serve_game.py <run dir> --port 8080
Then curl index.html, /, and src/main.js and every referenced asset — all 200.
Bind 127.0.0.1 only.
Write server.json.
Return: the URL to open, the port, the HTTP status codes, and any defect you saw.`,
});
```

## Phase 10 — Deliver

Verify before handing anything over:

1. Was `brief.json` confirmed by the user?
2. Did the critic run **before** the build (Phase 2 precedes Phase 5)?
3. Every P0/P1 either closed or explicitly surfaced to the user?
4. Any repair round: was closure verified **and** was a regression check run?
5. `stitch.json` — does every screen have a status, and is no screen falsely
   marked `ok`?
6. Did all four module developers deliver, with their verification commands?
7. `check_build.py` — zero P0?
8. `qa-report.md` — verdict PASS, every acceptance criterion checked with a
   number, UNVERIFIED list empty or explained?
9. `__game` hook present and `state()` JSON-serialisable?
10. `curl` on the served URL returned 200 for `index.html`, `/` and `src/main.js`?
11. Is the server bound to `127.0.0.1` (not `0.0.0.0`)?
12. Was every question that needed the user asked **when it appeared**?

Then give the user:

- the **URL** to open;
- the one-line pitch and the controls (keyboard + gamepad);
- how to stop the server (`python3 .pi/skills/game-serve/serve_game.py <run dir> --stop`);
- the run directory path with the artifacts;
- any unresolved finding, and every UNVERIFIED item.

## Style rules

- **Never claim a game works because the code looks right.** Evidence is a QA
  report with numbers, or a 200 from curl — otherwise it is unverified.
- **One screen, one session, under 3 minutes.** A demo that cannot be shown
  inside a screen recording is a failed delivery.
- **No network, ever, at runtime.** No CDN, no remote font, no analytics. A
  remote reference is a P0, not a nit.
- **Parallel only where files do not overlap.** Phase 5 fans out because each
  child owns a distinct file; everything else stays sequential.
- Prefer a visible gap over a confident guess, every single time.
