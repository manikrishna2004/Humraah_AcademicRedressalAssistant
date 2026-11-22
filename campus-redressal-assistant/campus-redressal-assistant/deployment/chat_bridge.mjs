// FastAPI owns the local sessions and data retrieval. This bridge runs the same
// pure reducer and renderer used by the hosted Worker.
import { createTurnEngine } from "../web/turn-engine.js";
import { composeGuidance, mergeInterpretations, suggestInterpretation } from "../web/model-adapter.js";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const { operation, intake, state, event, change, plan, relatedPlan, schema, candidate } = JSON.parse(input);
const engine = createTurnEngine(intake);
const model = { key: process.env.HUMRAAH_ANTHROPIC_API_KEY, id: process.env.HUMRAAH_MODEL };
let result;
if (operation === "interpret") {
  const rules = engine.interpret(state, event);
  const normalized = engine.normalize(event.text);
  result = { rules, candidate: event.choice || event.topic ? null : await suggestInterpretation(model, intake, state, normalized, schema) };
} else if (operation === "transition") {
  const rules = engine.interpret(state, event);
  const parsed = mergeInterpretations(rules, candidate, engine.normalize(event.text), state?.pending_question);
  result = engine.transition(state, event, parsed, rules);
} else if (operation === "finish") {
  const wording = change.intent === "describe" && change.state.needs_replan && plan?.supported
    ? await composeGuidance(model, plan, change.main.tag) : null;
  result = engine.finish(change, plan, relatedPlan, wording);
} else {
  throw new Error("Unknown conversation operation");
}
process.stdout.write(JSON.stringify(result));
