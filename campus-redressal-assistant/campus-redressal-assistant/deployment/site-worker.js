import { createTurnEngine } from "../web/turn-engine.js";
import { composeGuidance, mergeInterpretations, suggestInterpretation, validateInterpretation } from "../web/model-adapter.js";
import { directoryTerms, planRoute, withContacts } from "../web/plan-data.js";
import { assets, intake, directoryRows, directoryVersion, schema } from "./generated-site-data.js";

const SESSION_MS = 20 * 60 * 1000;
const MAX_TURNS = 60;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const engine = createTurnEngine(intake);
let seedPromise;

function json(body, status = 200) {
  return Response.json(body, { status, headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
}

function error(detail, status) {
  return json({ detail }, status);
}

function ensureDirectory(db) {
  seedPromise ??= (async () => {
    if (await db.prepare("SELECT 1 FROM campus_contacts WHERE snapshot = ? LIMIT 1").bind(directoryVersion).first()) return;
    const fields = Object.keys(directoryRows[0]);
    const sql = `INSERT OR IGNORE INTO campus_contacts (${fields.join(", ")}, snapshot)
      VALUES (${fields.map(() => "?").join(", ")}, ?)`;
    await db.batch(directoryRows.map((row) => db.prepare(sql).bind(...fields.map((key) => row[key]), directoryVersion)));
  })().catch((failure) => {
    seedPromise = undefined;
    throw failure;
  });
  return seedPromise;
}

async function getPlan(db, input) {
  const { plan, routes } = planRoute(intake, input);
  if (!plan) return intake.fallback;
  await ensureDirectory(db);
  const sql = intake.directory.routeSql
    .replace("WHERE kind = $kind AND department = $department", "WHERE kind = ?1 AND department = ?2 AND snapshot = ?3");
  const contacts = await Promise.all(routes.map(async ([kind, unit]) => {
    const lookup = (dept) => db.prepare(sql).bind(kind, dept, directoryVersion).first();
    return await lookup(unit) ?? (unit !== "General" ? await lookup("General") : null);
  }));
  return withContacts(intake, plan, input.department, contacts.filter(Boolean));
}

async function directory(db, url) {
  await ensureDirectory(db);
  const term = directoryTerms((url.searchParams.get("q") ?? "").slice(0, 100));
  const sql = intake.directory.searchSql.replaceAll("$term", "?1")
    .replace("WHERE", "WHERE snapshot = ?2 AND (").replace("ORDER BY", ") ORDER BY");
  const { results } = await db.prepare(sql).bind(term, directoryVersion).all();
  return json({ contacts: results });
}

async function turn(request, env) {
  const content = await request.text();
  if (content.length > 7500) return error("Enter a shorter message.", 422);
  let input;
  try {
    input = JSON.parse(content);
  } catch {
    return error("Enter a question to continue.", 422);
  }
  const { session = null, revision = 0, text, rewind, choice, topic } = input ?? {};
  if (typeof text !== "string" || !text.trim() || text.length > 700 ||
      !Number.isSafeInteger(revision) || revision < 0 || session !== null && (typeof session !== "string" || !UUID.test(session)) ||
      rewind != null && !Number.isSafeInteger(rewind) || choice != null && typeof choice !== "string" ||
      topic != null && !Object.hasOwn(intake.issues, topic) || !session && (revision || choice || rewind != null)) {
    return error("Check the question or choose an offered answer.", 422);
  }

  const expires = Date.now() - SESSION_MS;
  const db = env.DB;
  let row;
  if (session) {
    row = await db.prepare("SELECT history, revision FROM chat_sessions WHERE id = ? AND touched >= ?")
      .bind(session, expires).first();
    if (!row) return error("This conversation has expired. Start a new question.", 404);
    if (row.revision !== revision) return error("That turn has changed. Try again from the latest reply.", 409);
  } else {
    await db.prepare("DELETE FROM chat_sessions WHERE touched < ?").bind(expires).run();
  }
  const history = row ? JSON.parse(row.history) : [];
  const position = rewind ?? history.length;
  if (position < 0 || position > history.length || position >= MAX_TURNS || topic && position) {
    return error("Choose a reply to edit or start a new question.", 422);
  }
  const previous = history[position - 1];
  const state = previous?.state ?? null;
  if (choice && !state?.pending_question?.choices.some(([value]) => value === choice)) {
    return error("Choose one of the offered answers.", 422);
  }
  const event = { text: text.trim(), choice, topic };
  const rules = engine.interpret(state, event);
  const normalized = engine.normalize(event.text);
  const model = { key: env.HUMRAAH_ANTHROPIC_API_KEY, id: env.HUMRAAH_MODEL };
  const proposal = choice || topic ? null : await suggestInterpretation(model, intake, state, normalized, schema);
  const candidate = validateInterpretation(schema, proposal, intake.departments);
  const interpretation = mergeInterpretations(rules, candidate, normalized, state?.pending_question);
  const change = engine.transition(state, event, interpretation, rules);

  let plan = null;
  let related = null;
  if (!change.state.pending_question) {
    [plan, related] = change.state.needs_replan || !previous?.plan
      ? await Promise.all([getPlan(db, change.main), change.related && getPlan(db, change.related)])
      : [previous.plan, previous.related];
  }
  const wording = change.intent === "describe" && change.state.needs_replan && plan?.supported
    ? await composeGuidance(model, plan, change.main.tag) : null;
  const result = engine.finish(change, plan, related, wording);
  const id = session ?? crypto.randomUUID();
  const nextHistory = JSON.stringify([...history.slice(0, position), { state: change.state, plan, related }]);
  const touched = Date.now();
  if (session) {
    const update = await db.prepare("UPDATE chat_sessions SET revision = ?, touched = ?, history = ? WHERE id = ? AND revision = ?")
      .bind(revision + 1, touched, nextHistory, id, revision).run();
    if (!update.meta.changes) return error("That turn has changed. Try again from the latest reply.", 409);
  } else {
    await db.prepare("INSERT INTO chat_sessions VALUES (?, ?, ?, ?)").bind(id, 1, touched, nextHistory).run();
  }
  return json({ ...result, session: id, revision: revision + 1, position });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    try {
      if (request.method === "GET" && path === "/api/options") {
        const { issues, scenarios, departments } = intake;
        return json({ issues, scenarios, departments });
      }
      if (request.method === "GET" && path === "/api/directory") return await directory(env.DB, url);
      if (request.method === "POST" && path === "/api/chat/turn") return await turn(request, env);
      if (request.method === "DELETE" && path.startsWith("/api/chat/")) {
        const id = path.slice("/api/chat/".length);
        if (UUID.test(id)) await env.DB.prepare("DELETE FROM chat_sessions WHERE id = ?").bind(id).run();
        return new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });
      }
      const asset = assets[path === "/" ? "/index.html" : path];
      if (!asset || !["GET", "HEAD"].includes(request.method)) return error("Page not found.", 404);
      return new Response(request.method === "HEAD" ? null : Uint8Array.fromBase64(asset.body), {
        headers: { "Content-Type": asset.type, "Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff" },
      });
    } catch (failure) {
      console.error("Humraah request failed", path.startsWith("/api/chat/") ? "/api/chat" : path, failure.message);
      return error("Humraah guidance is temporarily unavailable. Try again.", 503);
    }
  },
};
