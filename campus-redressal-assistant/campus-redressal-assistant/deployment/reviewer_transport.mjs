import { createTurnEngine } from "../web/turn-engine.js";
import { directoryTerms, planRoute, withContacts } from "../web/plan-data.js";

let data;
let database;

export function getIntake() {
  data ??= fetch(new URL("./demo-data.json", import.meta.url)).then((response) => {
    if (!response.ok) throw new Error("Humraah guidance is temporarily unavailable.");
    return response.json();
  });
  return data;
}

async function loadDirectory() {
  const script = document.createElement("script");
  script.src = new URL("./vendor/sql-wasm.js", import.meta.url);
  const ready = new Promise((resolve, reject) => {
    script.onload = resolve;
    script.onerror = () => reject(new Error("The campus directory could not be loaded."));
  });
  document.head.append(script);
  const [bytes] = await Promise.all([
    fetch(new URL("./campus-directory.sqlite", import.meta.url)).then(async (response) => {
      if (!response.ok) throw new Error("The campus directory could not be loaded.");
      return new Uint8Array(await response.arrayBuffer());
    }),
    ready,
  ]);
  const SQL = await globalThis.initSqlJs({
    locateFile: (name) => new URL(`./vendor/${name}`, import.meta.url).href,
  });
  return new SQL.Database(bytes);
}

function getDatabase() {
  database ??= loadDirectory().catch((error) => {
    database = undefined;
    throw error;
  });
  return database;
}

function select(db, sql, parameters) {
  const query = db.prepare(sql);
  try {
    query.bind(parameters);
    const rows = [];
    while (query.step()) rows.push(query.getAsObject());
    return rows;
  } finally {
    query.free();
  }
}

export function searchDirectory(db, directory, term) {
  const normalized = directoryTerms(term);
  return select(db, directory.searchSql, { $term: normalized });
}

export function lookupPlan(intake, db, input) {
  const { directory } = intake;
  const { plan, routes } = planRoute(intake, input);
  if (!plan) return intake.fallback;
  const contacts = [];
  for (const [kind, unit] of routes) {
    const search = (department) => select(db, directory.routeSql, { $kind: kind, $department: department })[0];
    const contact = search(unit) ?? (unit !== "General" ? search("General") : undefined);
    if (contact) contacts.push(contact);
  }
  return withContacts(intake, plan, input.department, contacts);
}

export async function getPlan(input) {
  const intake = await getIntake();
  return input.tag ? lookupPlan(intake, await getDatabase(), input) : intake.fallback;
}

export async function getDirectory(term) {
  const [intake, db] = await Promise.all([getIntake(), getDatabase()]);
  return searchDirectory(db, intake.directory, term);
}


const sessions = new Map();

export async function sendTurn({ session, revision = 0, rewind, ...event }) {
  const intake = await getIntake();
  const engine = createTurnEngine(intake);
  const id = session ?? crypto.randomUUID();
  const previous = sessions.get(id) ?? { revision: 0, turns: [] };
  if (previous.revision !== revision) throw new Error("That turn has changed. Try again from the latest reply.");
  const position = rewind ?? previous.turns.length;
  const change = engine.transition(previous.turns[position - 1], event);
  const [plan, relatedPlan] = change.state.pending_question ? [] : await Promise.all([
    getPlan(change.main), change.related ? getPlan(change.related) : null,
  ]);
  const current = sessions.get(id);
  if (session && (!current || current.revision !== revision)) throw new Error("This conversation has changed.");
  sessions.set(id, { revision: revision + 1, turns: [...previous.turns.slice(0, position), change.state] });
  return { ...engine.finish(change, plan, relatedPlan), session: id, revision: revision + 1, position };
}

export function closeChat(session) {
  sessions.delete(session);
}
