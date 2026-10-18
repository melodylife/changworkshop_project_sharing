/**
 * omp-titlebanner
 * ---------------
 * A tiny oh-my-pi (omp) extension that prints a centered, colored title
 * banner at session start, so you can tell profiles apart at a glance.
 *
 * Each omp profile has its own isolated agent directory:
 *
 *     ~/.omp/profiles/<profile>/agent/extensions/banner.ts
 *
 * Drop this file there and omp loads it automatically when that profile
 * starts. Nothing else is required: if you do not supply any configuration,
 * the banner is generated from the active profile name.
 *
 * Optional configuration (same directory or OMP_BANNER_CONFIG):
 *
 *     banner.config.json
 *
 *     {
 *       "title": "DEV",
 *       "label": "Programming · omp-dev",
 *       "color": "success",
 *       "art": null,
 *       "minWidth": 40
 *     }
 *
 * Environment variables override the file:
 *
 *     OMP_BANNER_TITLE, OMP_BANNER_LABEL, OMP_BANNER_COLOR,
 *     OMP_BANNER_ART, OMP_BANNER_CONFIG, OMP_BANNER_DISABLE=1
 *
 * The extension only uses public omp extension APIs:
 *   - pi.registerMessageRenderer() to draw a custom message
 *   - pi.on("session_start")         to emit it once per session
 *   - pi.sendMessage({ triggerTurn: false }) so it never calls the model
 *
 * Built against the omp 18.x extension API.
 */

import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
// Type-only: erased before the file is loaded, so no package install is needed.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** Custom message type. Change it only if it collides with another extension. */
const MESSAGE_TYPE = "profile-banner";

interface BannerConfig {
  /** Set false to disable the banner without removing the extension. */
  enabled?: boolean;
  /** Big text. Defaults to the uppercased profile name. */
  title?: string;
  /** Small caption under the big text. */
  label?: string;
  /** Theme color name: accent, success, warning, error, text, muted, dim... */
  color?: string;
  /** Pre-rendered ASCII/Unicode art. When set, `title` is not drawn. */
  art?: string;
  /** Terminal width below which the banner collapses to a single line. */
  minWidth?: number;
}

/* -------------------------------------------------------------------------- */
/* Built-in 5-row block font                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Every glyph is exactly 5x5 cells so the generated art keeps a fixed grid.
 * Adding a glyph is just another entry here.
 */
const FONT: Record<string, string[]> = {
  A: [" ███ ", "█   █", "█████", "█   █", "█   █"],
  B: ["████ ", "█   █", "████ ", "█   █", "████ "],
  C: [" ████", "█    ", "█    ", "█    ", " ████"],
  D: ["████ ", "█   █", "█   █", "█   █", "████ "],
  E: ["█████", "█    ", "████ ", "█    ", "█████"],
  F: ["█████", "█    ", "████ ", "█    ", "█    "],
  G: [" ████", "█    ", "█  ██", "█   █", " ███ "],
  H: ["█   █", "█   █", "█████", "█   █", "█   █"],
  I: ["█████", "  █  ", "  █  ", "  █  ", "█████"],
  J: ["  ███", "   █ ", "   █ ", "█  █ ", " ██  "],
  K: ["█   █", "█  █ ", "███  ", "█  █ ", "█   █"],
  L: ["█    ", "█    ", "█    ", "█    ", "█████"],
  M: ["█   █", "██ ██", "█ █ █", "█   █", "█   █"],
  N: ["█   █", "██  █", "█ █ █", "█  ██", "█   █"],
  O: [" ███ ", "█   █", "█   █", "█   █", " ███ "],
  P: ["████ ", "█   █", "████ ", "█    ", "█    "],
  Q: [" ███ ", "█   █", "█   █", "█  █ ", " ██ █"],
  R: ["████ ", "█   █", "████ ", "█  █ ", "█   █"],
  S: [" ████", "█    ", " ███ ", "    █", "████ "],
  T: ["█████", "  █  ", "  █  ", "  █  ", "  █  "],
  U: ["█   █", "█   █", "█   █", "█   █", " ███ "],
  V: ["█   █", "█   █", "█   █", " █ █ ", "  █  "],
  W: ["█   █", "█   █", "█ █ █", "██ ██", "█   █"],
  X: ["█   █", " █ █ ", "  █  ", " █ █ ", "█   █"],
  Y: ["█   █", " █ █ ", "  █  ", "  █  ", "  █  "],
  Z: ["█████", "   █ ", "  █  ", " █   ", "█████"],
  "0": [" ███ ", "█  ██", "█ █ █", "██  █", " ███ "],
  "1": ["  █  ", " ██  ", "  █  ", "  █  ", "█████"],
  "2": [" ███ ", "█   █", "  ██ ", " █   ", "█████"],
  "3": ["████ ", "    █", " ███ ", "    █", "████ "],
  "4": ["█   █", "█   █", "█████", "    █", "    █"],
  "5": ["█████", "█    ", "████ ", "    █", "████ "],
  "6": [" ███ ", "█    ", "████ ", "█   █", " ███ "],
  "7": ["█████", "    █", "   █ ", "  █  ", "  █  "],
  "8": [" ███ ", "█   █", " ███ ", "█   █", " ███ "],
  "9": [" ███ ", "█   █", " ████", "    █", " ███ "],
  "-": ["     ", "     ", "█████", "     ", "     "],
  _: ["     ", "     ", "     ", "     ", "█████"],
  ".": ["     ", "     ", "     ", "     ", "  █  "],
  "/": ["    █", "   █ ", "  █  ", " █   ", "█    "],
  " ": ["     ", "     ", "     ", "     ", "     "],
  "?": [" ███ ", "█   █", "  ██ ", "     ", "  █  "],
};

/** Render text as 5 rows of block letters. Unknown characters become "?". */
function bigText(text: string): string {
  const glyphs = [...text.toUpperCase()].map((ch) => FONT[ch] ?? FONT["?"]);
  return Array.from({ length: 5 }, (_, row) =>
    glyphs.map((glyph) => glyph[row]).join(" "),
  ).join("\n");
}

/* -------------------------------------------------------------------------- */
/* Width-aware centering                                                       */
/* -------------------------------------------------------------------------- */

/**
 * Approximate terminal display width.
 * CJK, Hangul, fullwidth forms and the usual wide ranges count as 2 cells,
 * everything else as 1. Without this, Chinese labels sit visibly off-center.
 */
function displayWidth(s: string): number {
  let width = 0;
  for (const ch of s) {
    const c = ch.codePointAt(0) ?? 0;
    const wide =
      c >= 0x1100 &&
      (c <= 0x115f ||
        c === 0x2329 ||
        c === 0x232a ||
        (c >= 0x2e80 && c <= 0xa4cf) ||
        (c >= 0xac00 && c <= 0xd7a3) ||
        (c >= 0xf900 && c <= 0xfaff) ||
        (c >= 0xfe30 && c <= 0xfe4f) ||
        (c >= 0xff00 && c <= 0xff60) ||
        (c >= 0xffe0 && c <= 0xffe6));
    width += wide ? 2 : 1;
  }
  return width;
}

/** Center one line inside `width` cells, ignoring invisible trailing spaces. */
function center(line: string, width: number): string {
  const visible = line.replace(/\s+$/, "");
  const pad = Math.max(0, Math.floor((width - displayWidth(visible)) / 2));
  return " ".repeat(pad) + visible;
}

/* -------------------------------------------------------------------------- */
/* Configuration                                                               */
/* -------------------------------------------------------------------------- */

/** Current profile name, from env or argv (`--profile foo` / `--profile=foo`). */
function activeProfile(): string | undefined {
  const fromEnv = process.env.OMP_PROFILE?.trim();
  if (fromEnv) return fromEnv;

  const argv = process.argv;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--profile" && argv[i + 1]) return argv[i + 1];
    if (argv[i].startsWith("--profile=")) return argv[i].slice("--profile=".length);
  }
  return undefined;
}

/** Directory that holds this profile's extensions. */
function extensionsDir(): string {
  const profile = activeProfile();
  const agentDir = profile
    ? join(homedir(), ".omp", "profiles", profile, "agent")
    : join(homedir(), ".omp", "agent");
  return join(agentDir, "extensions");
}

function readConfig(): BannerConfig {
  const explicit = process.env.OMP_BANNER_CONFIG?.trim();
  const path = explicit || join(extensionsDir(), "banner.config.json");
  if (!existsSync(path)) return {};

  try {
    return JSON.parse(readFileSync(path, "utf8")) as BannerConfig;
  } catch (error) {
    // Never break startup because of a typo in the config file.
    console.error(`[omp-titlebanner] cannot read ${path}: ${String(error)}`);
    return {};
  }
}

/** Env var wins, then the config file, then the fallback. */
function pick(envName: string, fileValue: string | undefined, fallback: string): string {
  return process.env[envName]?.trim() || fileValue?.trim() || fallback;
}

/* -------------------------------------------------------------------------- */
/* Extension                                                                   */
/* -------------------------------------------------------------------------- */

export default function profileBanner(pi: ExtensionAPI) {
  const config = readConfig();
  const profile = activeProfile() ?? "default";

  const derivedTitle = profile.toUpperCase().replace(/[^A-Z0-9 ._/-]/g, "") || "OMP";
  const title = pick("OMP_BANNER_TITLE", config.title, derivedTitle);
  const label = pick("OMP_BANNER_LABEL", config.label, `oh-my-pi · ${profile}`);
  const color = pick("OMP_BANNER_COLOR", config.color, "accent");

  // OMP_BANNER_ART uses literal "\n" escapes so it can live on one env line.
  const envArt = process.env.OMP_BANNER_ART?.replace(/\\n/g, "\n");
  const art = (envArt || config.art || bigText(title)).replace(/\s+$/, "");
  const minWidth = config.minWidth ?? displayWidth(art.split("\n")[0] ?? "") + 4;

  pi.registerMessageRenderer(MESSAGE_TYPE, (_message, _options, theme) => ({
    render: (width: number) => {
      // Narrow terminal: do not wrap ASCII art into unreadable garbage.
      if (width < minWidth) {
        return [theme.fg(color, center(title, width)), theme.fg("muted", center(label, width))];
      }
      return [
        ...art.split("\n").map((line) => theme.fg(color, center(line, width))),
        "",
        theme.fg("muted", center(label, width)),
      ];
    },
    invalidate: () => {},
  }));

  pi.on("session_start", async (_event, ctx) => {
    // Headless/RPC runs have no transcript to draw into.
    if (!ctx.hasUI) return;
    if (process.env.OMP_BANNER_DISABLE === "1" || config.enabled === false) return;

    pi.sendMessage(
      { customType: MESSAGE_TYPE, content: title, display: true, details: { title, label, color } },
      // Show the banner without spending a model turn on it.
      { triggerTurn: false },
    );
  });
}
