// Run with `npm test` (node --test, no extra packages). Reads the committed seed, so it
// needs no network. Checks that the browser-side inbox agrees with the pipeline.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { loadInbox } from "./data.ts";
import { alertKeys, buildCards, buildInbox } from "./inbox.ts";
import { crore, pct, price } from "./format.ts";
import type { Item } from "./types.ts";

const root = path.resolve(process.cwd(), "..");
const alertsDoc = JSON.parse(fs.readFileSync(path.join(root, "data/seed/push/alerts.json"), "utf8"));

test("default window reproduces alerts.json", () => {
  const data = loadInbox();
  const hours = (Date.parse(alertsDoc.window.to) - Date.parse(alertsDoc.window.from)) / 3_600_000;
  assert.equal(alertsDoc.window.to, data.snapshot_at);
  const view = buildInbox(data, hours, alertsDoc.rules);

  const expectedPrice = alertsDoc.alerts.filter((a: { type: string }) => a.type === "price").map((a: { id: string }) => a.id);
  assert.deepEqual(view.priceAlerts.map((a) => a.key).sort(), [...expectedPrice].sort());

  const expectedFiling = alertsDoc.alerts
    .filter((a: { type: string }) => a.type === "filing")
    .map((a: { filing_id: string }) => a.filing_id)
    .sort();
  const cards = [...view.needs, ...view.worth, ...view.routine].filter((c) => c.alert);
  assert.deepEqual(cards.map((c) => c.lead.id).sort(), expectedFiling);
  assert.equal(alertKeys(view).length, alertsDoc.alerts.length);
});

test("repeats collapse into one card led by the highest score, newest on ties", () => {
  const base: Omit<Item, "id" | "datetime" | "score" | "group_key"> = { symbol: "X", category: "fund_raise",
    category_label: "Fund raise", kind: "event", pending: false, method: "rule", tier: "worth_knowing", reasons: [],
    reaction: null, pdf_url: null, results_symbol: null, management: null, headline: "h", score_parts: [] };
  const items: Item[] = [
    { ...base, id: "a", datetime: "2026-11-10T10:00:00+05:30", score: 55, group_key: "g" },
    { ...base, id: "b", datetime: "2026-11-11T10:00:00+05:30", score: 55, group_key: "g" },
    { ...base, id: "c", datetime: "2026-11-09T10:00:00+05:30", score: 60, group_key: "h" },
  ];
  const cards = buildCards(items, []);
  assert.deepEqual(cards.map((c) => [c.lead.id, c.members.length]), [["c", 1], ["b", 2]]);
});

test("same-day results card is led by the earliest rule match", () => {
  const base: Omit<Item, "id" | "datetime" | "method"> = { symbol: "X", category: "results", category_label: "Results",
    kind: "event", pending: false, tier: "needs_attention", reasons: [], reaction: null, pdf_url: null,
    results_symbol: null, management: null, headline: "h", score: 80, group_key: "X|results|2026-11-07", score_parts: [] };
  const items: Item[] = [
    { ...base, id: "press", datetime: "2026-11-07T17:28:00+05:30", method: "context" },
    { ...base, id: "statement", datetime: "2026-11-07T17:18:00+05:30", method: "rule" },
    { ...base, id: "outcome", datetime: "2026-11-07T17:11:00+05:30", method: "rule" },
  ];
  assert.equal(buildCards(items, ["results"])[0].lead.id, "outcome");
});

test("every figure is formatted, nulls show a dash", () => {
  assert.equal(pct(3.364), "+3.36%");
  assert.equal(pct(-2.1), "−2.10%");
  assert.equal(pct(null), "–");
  assert.equal(crore(49244), "₹49,244 cr");
  assert.equal(crore(258898), "₹2,58,898 cr");
  assert.equal(price(1234.5), "1,234.50");
});

test("a results card leads with the metric that moved most, with its label", async () => {
  const { resultsHeadlines } = await import("./present.ts");
  const data = loadInbox();
  const card = buildInbox(data, 168).needs.find((c) => c.lead.symbol === "TATACHEM" && c.results_symbol);
  assert.ok(card, "Tata Chemicals results card in the 7d window");
  const heads = resultsHeadlines(card, data);
  assert.equal(heads[0].label, "PAT");
  assert.ok(heads[0].yoy < -100);
  assert.equal(heads[1].label, "Revenue");
});

test("ask questions fill placeholders and drop ones without a value", async () => {
  const { askQuestions } = await import("./present.ts");
  const ask = { max_questions: 2, results: ["Why did {metric} change {change}?", "Call notes for {name}?", "Third {name}?"], default: ["About {name}?"] };
  assert.deepEqual(askQuestions(ask, "results", { metric: "PAT", change: "−132.5%", name: "Tata Chemicals" }), [
    "Why did PAT change −132.5%?",
    "Call notes for Tata Chemicals?",
  ]);
  assert.deepEqual(askQuestions(ask, "results", { name: "X" }), ["Call notes for X?", "Third X?"]);
  assert.deepEqual(askQuestions(ask, "dividend", { name: "X" }), ["About X?"]);
});
