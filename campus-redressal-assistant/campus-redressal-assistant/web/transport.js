async function read(response) {
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(typeof detail?.detail === "string"
      ? detail.detail : "Humraah is temporarily unavailable. Try again.");
  }
  return response.json();
}

export const getIntake = () => fetch("./api/options").then(read);

export function sendTurn(input) {
  return fetch("./api/chat/turn", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }).then(read);
}

export function closeChat(session) {
  return fetch(`./api/chat/${encodeURIComponent(session)}`, { method: "DELETE" }).catch(() => {});
}

export async function getDirectory(term) {
  const path = new URL("./api/directory", window.location.href);
  path.searchParams.set("q", term);
  return (await read(await fetch(path))).contacts;
}
