/**
 * Registers /trip-plan for the trip-plan workflow.
 *
 * Same mechanism pi-herdr-agents uses for /plan: the command injects the
 * workflow skill text into the parent session as a user message, and the
 * parent session runs the orchestration through `subagent()` calls.
 *
 *   /trip-plan <destination, dates, party, pace, interests>
 *   /trip-plan    (no args -> starts the Phase 0 questionnaire)
 *
 * Auto-discovered from .pi/extensions/ once the project is trusted.
 * Reload with /reload inside Pi after editing.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const SKILL_PATH = fileURLToPath(
  new URL("../skills/trip-plan/SKILL.md", import.meta.url),
);

/** Strip the YAML frontmatter: the parent only needs the procedure body. */
function loadSkillBody(path: string): string {
  const raw = readFileSync(path, "utf8");
  return raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n*/, "").trim();
}

export default function tripPlanExtension(pi: ExtensionAPI) {
  pi.registerCommand("trip-plan", {
    description:
      "Plan a trip end-to-end: /trip-plan <destination, dates, party, pace, interests>",
    handler: async (args, ctx) => {
      let body: string;
      try {
        body = loadSkillBody(SKILL_PATH);
      } catch (error) {
        ctx.ui.notify(
          `Could not read the trip-plan skill at ${SKILL_PATH}: ${
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
        `<skill name="trip-plan" location="${SKILL_PATH}">\n${body}\n</skill>\n\n${opening}`,
      );
    },
  });
}
