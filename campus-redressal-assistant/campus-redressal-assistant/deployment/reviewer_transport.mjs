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
  const normalized = term.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  return select(db, directory.searchSql, { $term: normalized });
}

export function lookupPlan(intake, db, input) {
  if (!input.tag) return intake.fallback;
  const { directory } = intake;
  const status = input.sent === null ? "unknown" : input.sent ? "yes" : "no";
  const isEscalation = input.tag === "escalation";
  const kinds = isEscalation ? directory.escalation[status] : directory.routes[input.tag] ?? [];
  const plan = intake.plans[`${input.tag}|${isEscalation ? status : ""}`];
  if (!plan) return intake.fallback;

  const contacts = [];
  for (const kind of kinds) {
    const unit = kind === "department" && input.department ? input.department : "General";
    const search = (department) => select(db, directory.routeSql, { $kind: kind, $department: department })[0];
    const contact = search(unit) ?? (unit !== "General" ? search("General") : undefined);
    if (contact) contacts.push(contact);
  }
  return { ...plan, contacts, department: input.department };
}

export async function getPlan(input) {
  const intake = await getIntake();
  return input.tag ? lookupPlan(intake, await getDatabase(), input) : intake.fallback;
}

export async function getDirectory(term) {
  const [intake, db] = await Promise.all([getIntake(), getDatabase()]);
  return searchDirectory(db, intake.directory, term);
}
