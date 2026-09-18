/**
 * Registers the game-creation slash commands for the game-create workflow.
 *
 * Same mechanism pi-herdr-agents uses for /plan: the command injects the
 * workflow skill text into the parent session as a user message, and the
 * parent session runs the orchestration through `subagent()` calls.
 *
 *   /game-create <brief, e.g. genre, style, difficulty, controls>
 *   /game-creator / /game-planner   (aliases)
 *   /game-create    (no args -> starts the Phase 0 questionnaire)
 *
 * Registering the plausible alias names up front removes "command not found".
 *
 * Auto-discovered from .pi/extensions/ once the project is trusted.
 * Reload with /reload inside Pi after editing.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const SKILL_PATH = fileURLToPath(
  new URL("../skills/game-create/SKILL.md", import.meta.url),
);

/** Every name this workflow answers to. The first is the documented one. */
const COMMAND_NAMES = ["game-create", "game-creator", "game-planner"] as const;

const DESCRIPTION =
  "Create a small web game end-to-end: <genre, style, difficulty, controls>";

/** Strip the YAML frontmatter: the parent only needs the procedure body. */
function loadSkillBody(path: string): string {
  const raw = readFileSync(path, "utf8");
  return raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n*/, "").trim();
}

export default function gameCreateExtension(pi: ExtensionAPI) {
  const handler = async (args: string, ctx: { ui: { notify(msg: string, kind?: string): void } }) => {
    let body: string;
    try {
      body = loadSkillBody(SKILL_PATH);
    } catch (error) {
      ctx.ui.notify(
        `Could not read the game-create skill at ${SKILL_PATH}: ${
          error instanceof Error ? error.message : String(error)
        }`,
        "error",
      );
      return;
    }

    const task = args.trim();
    const opening = task
      ? task
      : "The user did not supply a brief. Start at Phase 0 and ask the " +
        "questionnaire in this session, then continue the workflow.";

    pi.sendUserMessage(
      `<skill name="game-create" location="${SKILL_PATH}">\n${body}\n</skill>\n\n${opening}`,
    );
  };

  for (const name of COMMAND_NAMES) {
    pi.registerCommand(name, {
      description: name === COMMAND_NAMES[0]
        ? DESCRIPTION
        : `${DESCRIPTION} (alias of /${COMMAND_NAMES[0]})`,
      handler,
    });
  }
}
