# Artifact contracts

Downstream steps parse these files. Conform to them literally. When a value is
genuinely unknown, write `null` — **never** a plausible-looking guess.

All artifacts live under the run directory:

```
.pi/games/YYYY-MM-DD-<slug>/
├── brief.json
├── design.json          design.md
├── review.md
├── stitch.json          ui-spec.md
├── src/core.js  src/player.js  src/input.js  src/ui.js  src/main.js
├── styles.css   index.html   package.json
├── build-report.json    integration-report.md
├── qa-report.json       qa-report.md
└── server.json
```

---

## `brief.json` — Phase 0, written by the parent from the questionnaire

```json
{
  "title": "Neon Runner",
  "slug": "neon-runner",
  "genre": "endless runner",
  "reference": "类似 Chrome 小恐龙，但节奏更快",
  "fantasy": "手忙脚乱但每次都想再试一次",
  "visual_direction": "极简编辑风，深色底 + 单色强调",
  "difficulty": "balanced",
  "controls": ["keyboard", "gamepad"],
  "language": "zh",
  "hard_constraints": [
    "单屏，不做关卡选择",
    "不要任何外部图片资源"
  ],
  "must_have": ["分数", "重开"],
  "must_avoid": ["登录", "排行榜服务"],
  "notes": "手机浏览器也要能看，但操作以键盘为主"
}
```

`difficulty` is one of `casual` / `balanced` / `hardcore`.
`language` is `zh` or `en` — it sets the on-screen copy, not the artifacts.

---

## `design.json` — Phase 1, written by `game-designer`

```json
{
  "game": {
    "slug": "neon-runner",
    "title": "霓虹跑者",
    "genre": "endless runner",
    "one_liner": "在一条不断加速的走廊里躲开障碍，跑得越远分越高",
    "session_seconds": 120,
    "platform": "web",
    "tech": ["html", "css", "vanilla-js-esm", "canvas"],
    "viewport": { "w": 960, "h": 540 }
  },
  "core_loop": {
    "goal": "尽可能久地活下去，分数随时间与躲避难度上升",
    "win": null,
    "lose": "生命值归零",
    "difficulty_curve": [
      { "at_seconds": 0, "speed": 260, "spawn_interval_ms": 1400, "obstacle_types": ["low"] },
      { "at_seconds": 45, "speed": 340, "spawn_interval_ms": 900, "obstacle_types": ["low", "high"] },
      { "at_seconds": 90, "speed": 430, "spawn_interval_ms": 620, "obstacle_types": ["low", "high", "gap"] }
    ]
  },
  "entities": [
    {
      "id": "player",
      "kind": "player",
      "role": "玩家角色，只能跳跃",
      "behaviour": "受重力下落，落地时可在下一帧再次跳跃",
      "params": { "w": 34, "h": 48, "jump_velocity": -520, "gravity": 1500, "max_lives": 3 }
    },
    {
      "id": "obstacle-low",
      "kind": "hazard",
      "role": "地面障碍，需要跳跃躲开",
      "behaviour": "从右侧匀速进入，离开左侧后移除",
      "params": { "w": 22, "h": 40, "speed_offset": 0 }
    }
  ],
  "controls": [
    { "intent": "action", "keys": ["Space", "ArrowUp", "KeyW"],
      "arcade": ["GAMEPAD_A", "GAMEPAD_DPAD_UP"], "description": "跳跃" },
    { "intent": "pause", "keys": ["Escape", "KeyP"], "arcade": ["GAMEPAD_START"],
      "description": "暂停 / 继续" },
    { "intent": "restart", "keys": ["Enter", "KeyR"], "arcade": ["GAMEPAD_START"],
      "description": "结算界面重新开始" }
  ],
  "scoring": {
    "rules": [
      { "event": "survive_second", "points": 10, "notes": "随时间累积" },
      { "event": "perfect_dodge", "points": 25, "notes": "障碍与玩家擦身而过" }
    ],
    "high_score": false,
    "reset_on_restart": true
  },
  "levels": [
    {
      "id": "endless",
      "name": "无尽走廊",
      "objective": "生存到时间上限或生命耗尽",
      "spawn_table": [
        { "entity_id": "obstacle-low", "weight": 3, "from_seconds": 0 },
        { "entity_id": "obstacle-high", "weight": 2, "from_seconds": 45 }
      ]
    }
  ],
  "screens": [
    { "id": "menu", "purpose": "标题、操作提示、开始" },
    { "id": "playing", "purpose": "游戏画面 + HUD（分数、生命）" },
    { "id": "paused", "purpose": "暂停浮层，可继续" },
    { "id": "gameover", "purpose": "最终分数、最高分、重开" }
  ],
  "scope": {
    "in": ["单屏无尽跑酷", "键盘与手柄操作", "分数与生命", "暂停与重开"],
    "out": ["后端", "账号", "联网排行榜", "关卡编辑器", "音效资源文件"]
  },
  "acceptance_criteria": [
    "菜单界面上按 action 键能进入 playing",
    "playing 状态下 action 键让玩家 y 坐标在一次 step 后变小（产生跳跃）",
    "按 pause 键后 state().screen 变为 'paused'，再按一次回到 'playing'",
    "生命值降到 0 后 state().screen 变为 'gameover'",
    "gameover 界面上按 restart 后 state().score 归零且 screen 回到 'playing'",
    "运行期间不发出任何网络请求"
  ],
  "open_questions": []
}
```

**Rules**

- `game.session_seconds` ≤ 180. This is a demo, not a game jam entry.
- `game.tech` is fixed to `["html","css","vanilla-js-esm","canvas"]`. No
  framework, no bundler, no build step.
- `screens` must contain at least `menu`, `playing`, `gameover`. Ids are stable —
  every later phase keys off them.
- Every control has `intent` (one of the vocabulary below), at least one `keys`
  entry, and at least one `arcade` entry. A control with a description and no key
  code is a defect.
- **Intent vocabulary is closed:** `left`, `right`, `up`, `down`, `action`,
  `pause`, `restart`. A new intent breaks the input module and the QA harness.
- `entities[].params` carries every tunable number. Prose never carries a value
  the code must honour.
- `acceptance_criteria` are **observable-state** statements. "手感好" is not a
  criterion; "按 action 后 y 变小" is.
- `scope.out` must explicitly exclude backend, network and external assets.

---

## `review.md` — Phase 2 / re-audit, written by `game-critic`

```markdown
## P0
- **[design.json › screens]** 缺 `paused` 界面，但控制表声明了 `pause` 意图。
  最小修法：新增 `paused` screen 条目。

## P1
- **[design.json › core_loop.difficulty_curve]** 45 秒才第一次加难度，
  演示视频里前 45 秒是静止的。最小修法：把第二档提前到 25 秒。

## P2
- ...

## Re-audit
| Finding | 结论 | 证据 |
| --- | --- | --- |
| P1-1 | CLOSED | 第二档 at_seconds: 25 |

### Regressions
none found

### 未能验证
- 音效：设计里没有音效资源

VERDICT: NEEDS WORK (P0: 1, P1: 1)
```

---

## `stitch.json` — Phase 4, written by `ui-designer`

```json
{
  "project_id": "<stitch project id>",
  "design_system_id": "<stitch design system id>",
  "screens": [
    { "screen_id": "menu", "stitch_screen_id": "<stitch screen id>",
      "status": "ok", "source": "stitch" },
    { "screen_id": "playing", "stitch_screen_id": "<stitch screen id>", "status": "late", "source": "stitch" },
    { "screen_id": "gameover", "stitch_screen_id": null, "status": "unavailable", "source": "self" }
  ]
}
```

**Rules**

- One entry per `design.json.screens` id. **Never omit a screen** because it
  failed to arrive — `unavailable` is a recorded outcome, not a gap.
- `status`: `ok` (returned in the call), `late` (the 300-second pull found it),
  `unavailable` (never landed; `source` must then be `self`).
- Never mark `ok` for a screen you did not receive. This file is the only record
  that the demo's Stitch integration behaved.

---

## `ui-spec.md` — Phase 4, written by `ui-designer`

Free-form markdown, but it must contain, in this order:

1. **Design tokens** — a fenced `css` block of `:root` custom properties (palette,
   type scale, spacing, radius, canvas size, z-index layers).
2. **Screens** — one section per screen id, listing layout regions with sizes and
   every element with its binding (intent name or a `design.json` state field).
3. **Component states** — default / hover / active / disabled, plus paused and
   game-over variants.
4. **Motion** — the meaningful transitions only.
5. **Responsive** — the single canvas scale rule.
6. **Assets** — an explicit statement that no external image and no web font is
   used.
7. **Do not** — the list of things the developer must not add.

A developer who has never seen Stitch must be able to build the screens from this
file alone.

---

## Module interface — Phase 5, the contract the four developers implement

All modules are **ES modules** loaded directly by the browser. No bundler.

Shared rules: import-safe (no DOM/global/side effect at import time), no network,
randomness through an injected `rng` (default `Math.random`), no `eval`.

### `src/core.js`

```js
export function createCore({ config, rng = Math.random, player, ui }) -> {
  update(dtMs),        // advance one frame
  state(),             // { screen, score, elapsedMs, entities: [...], difficulty: {...} }
  start(), pause(), resume(), restart(),
  spawnTick(dtMs),     // exported so the harness can drive spawning alone
}
```

### `src/player.js`

```js
export function createPlayer({ config, rng = Math.random }) -> {
  update(dtMs, input, world),   // world = { bounds, entities }
  jump(),                       // apply the action intent
  reset(),
  state(),                      // { x, y, vx, vy, w, h, grounded, lives, alive }
}
```

### `src/input.js`

```js
export const INTENTS = ['left','right','up','down','action','pause','restart'];
export const DEFAULT_KEYMAP = { action: ['Space','ArrowUp','KeyW'], pause: ['Escape','KeyP'], ... };

export function createInput({ target, keymap = DEFAULT_KEYMAP, onIntent }) -> {
  attach(), detach(),
  gamepadIntent(),              // poll Gamepad API → intent name or null
  setIntent(name, on),          // harness entry point, bypasses DOM events
  reset(),
}
```

`DEFAULT_KEYMAP` must cover **every** intent declared in `design.json.controls`.
Gamepad buttons map onto the same intent names (`GAMEPAD_A` → `action`, …).

### `src/ui.js`

```js
export function createUI({ root, tokens, copy }) -> {
  render(state),      // full redraw from plain state
  mount(screenId),    // show exactly one screen
  toast(text, ms),
  destroy(),
}
```

`render` reads **only** the plain state object passed in — it must never reach
into `core` or `player`.

### `src/main.js` (dev-manager only)

```js
globalThis.__game = {
  ready: true,
  init(opts = {}),     // opts: { seed } — constructs all four modules fresh
  step(dtMs),          // exactly one frame, no rAF
  state(),             // PLAIN JSON — the QA harness asserts on this
  setIntent(name, on),
  reset(),
};
```

- `state()` returns `{ screen, score, lives, elapsedMs, entities: [...], player: {...} }`
  with **no** functions, class instances, or canvas handles.
- When `__game` exists, the real `requestAnimationFrame` loop must **not** also
  run during a harness session, or frames will be counted twice.

---

## `qa-report.json` — Phase 7, written by `qa_playtest.py` (not by a model)

```json
{
  "generated_at": "2026-09-17T04:10:00Z",
  "tool": ".pi/skills/game-qa/qa_playtest.py",
  "game_dir": "/abs/path/.pi/games/2026-09-17-neon-runner",
  "summary": { "P0": 0, "P1": 1, "P2": 2, "checks": 24, "passed": 21, "unverified": 1 },
  "checks": [
    { "id": "hook.present", "severity": "P0", "result": "pass",
      "evidence": "__game.ready === true" },
    { "id": "intent.action.effective", "severity": "P0", "result": "fail",
      "evidence": "y delta 0.00 after 5 steps with intent action" }
  ],
  "unverified": [],
  "errors": []
}
```

Results are `pass` / `fail` / `unverified`. **`unverified` is never `pass`.**

---

## `server.json` — Phase 9, written by `serve_game.py`

```json
{
  "url": "http://127.0.0.1:8080/index.html",
  "port": 8080,
  "root": "/abs/path/.pi/games/2026-09-17-neon-runner",
  "pid": 12345,
  "started_at": "2026-09-17T04:20:00Z",
  "checks": { "index.html": 200, "src/main.js": 200 }
}
```
