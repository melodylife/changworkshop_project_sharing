# omp-titlebanner

A tiny [oh-my-pi (omp)](https://github.com/earendil-works/pi) extension that prints a centered, colored title banner when a session starts — so you can tell at a glance which profile you are in.

If you run several omp profiles (`dev`, `research`, `work`, …), every window otherwise looks the same. This adds a distinct, zero-maintenance identity to each one.

```
████  █████ █   █
█   █ █     █   █
█   █ ████  █   █
█   █ █      █ █
████  █████   █

          Programming · omp-dev
```

## Features

- **Per-profile by design** — each omp profile loads its own copy, so dev/research/work never share state.
- **Zero config** — with no settings at all, the banner is generated from the profile name using a built-in 5-row block font.
- **Custom art** — supply any ASCII/Unicode art instead of the generated text.
- **Width-aware centering** — CJK and fullwidth characters count as 2 cells, so Chinese labels stay centered.
- **Narrow-terminal fallback** — collapses to a single colored line when the art would not fit.
- **No model calls** — the banner is a custom message with `triggerTurn: false`, so it costs nothing.
- **Headless-safe** — skipped automatically in RPC/headless runs where there is no transcript.

## Requirements

- A recent `omp` (oh-my-pi) build with extension support (`session_start` + `registerMessageRenderer`). Built against the 18.x extension API.
- No npm install and no build step. omp loads the TypeScript file directly through jiti.

## Install

omp stores each profile in its own isolated agent directory:

```
~/.omp/profiles/<profile>/agent/
```

Copy `banner.ts` into that profile's `extensions/` folder:

```bash
# dev profile
mkdir -p ~/.omp/profiles/dev/agent/extensions
cp banner.ts ~/.omp/profiles/dev/agent/extensions/banner.ts

# research profile
mkdir -p ~/.omp/profiles/research/agent/extensions
cp banner.ts ~/.omp/profiles/research/agent/extensions/banner.ts
```

Start the profile and the banner appears:

```bash
omp --profile dev
omp --profile research
```

> Profiles are independent: the same `banner.ts` in two profiles can show different titles through their own `banner.config.json`, or through the environment variables below.

For the default (no-profile) agent, use `~/.omp/agent/extensions/banner.ts`.

## Configuration

Configuration is optional. Precedence, highest first:

1. Environment variables
2. `banner.config.json` in the active profile's `extensions/` directory
3. Built-in defaults

Example `banner.config.json`:

```json
{
  "title": "DEV",
  "label": "Programming · omp-dev",
  "color": "success",
  "art": null,
  "minWidth": 40
}
```

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `enabled` | boolean | `true` | Set `false` to keep the file but hide the banner |
| `title` | string | profile name, uppercased | Text drawn with the built-in block font |
| `label` | string | `oh-my-pi · <profile>` | Small caption under the art |
| `color` | string | `accent` | Theme color name for the big text |
| `art` | string | generated from `title` | Pre-rendered art; overrides the font |
| `minWidth` | number | art width + 4 | Below this terminal width, print one line instead |

Valid `color` values are omp theme color names, including `accent`, `success`, `warning`, `error`, `text`, `muted`, and `dim`.

### Environment variables

| Variable | Equivalent to |
| --- | --- |
| `OMP_BANNER_TITLE` | `title` |
| `OMP_BANNER_LABEL` | `label` |
| `OMP_BANNER_COLOR` | `color` |
| `OMP_BANNER_ART` | `art` (use `\n` for line breaks) |
| `OMP_BANNER_CONFIG` | Absolute path to a config file |
| `OMP_BANNER_DISABLE=1` | Disables the banner |

Environment variables are handy inside a shell alias:

```bash
alias omp-dev='OMP_BANNER_TITLE=DEV OMP_BANNER_LABEL="Programming · omp-dev" OMP_BANNER_COLOR=success omp --profile dev'
```

### Custom art

Put any multi-line string in `art`. For example, the classic box-drawing style:

```json
{
  "title": "DEV",
  "label": "Programming · omp-dev",
  "color": "success",
  "art": "██████╗ ███████╗██╗   ██╗\n██╔══██╗██╔════╝██║   ██║\n██║  ██║█████╗  ██║   ██║\n██║  ██║██╔══╝  ╚██╗ ██╔╝\n██████╔╝███████╗ ╚████╔╝ \n╚═════╝ ╚══════╝  ╚═══╝"
}
```

When `art` is set, `title` is only used for the narrow-terminal fallback. Each line is centered independently based on its visible width.

See [`examples/`](examples/) for ready-to-copy configs.

## How it works

The extension uses only public omp extension APIs:

1. `pi.registerMessageRenderer("profile-banner", …)` registers a renderer for a custom message type. The renderer returns line strings for the current terminal width.
2. `pi.on("session_start", …)` sends that message once per session.
3. `pi.sendMessage(..., { triggerTurn: false })` displays it without starting a model turn.

Nothing is written to the session context, no files are modified, and the extension has no dependencies.

```
banner.ts
├── FONT          5×5 block glyphs (A–Z, 0–9, space, - _ . /)
├── bigText()     title → ASCII art
├── displayWidth  CJK-aware cell width
├── center()      per-line centering
├── readConfig()  env > banner.config.json > defaults
└── default export
    ├── registerMessageRenderer
    └── session_start → sendMessage(triggerTurn: false)
```

## Troubleshooting

**The banner does not appear**

- Confirm the file is at `~/.omp/profiles/<profile>/agent/extensions/banner.ts`.
- Make sure you launched that profile (`omp --profile <profile>`).
- Check `OMP_BANNER_DISABLE` and `enabled: false`.
- RPC/headless sessions intentionally show no banner.

**The art is off-center**

Terminal cell width differs for some glyphs. Stick to the built-in block font, or keep custom art in pure ASCII (no CJK) if your terminal is unusual.

**A config typo breaks nothing**

`banner.config.json` parse errors are printed to stderr and ignored; the defaults are used instead.

## Uninstall

Delete `banner.ts` (and optionally `banner.config.json`) from the profile's `extensions/` directory.

## License

MIT — see [LICENSE](LICENSE).
