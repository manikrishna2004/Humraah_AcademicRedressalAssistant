async function read(response) {
  if (!response.ok) throw new Error("Humraah is temporarily unavailable. Try again.");
  return response.json();
}

export const getIntake = () => fetch("./api/options").then(read);

export function getPlan(input) {
  return fetch("./api/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }).then(read);
}
