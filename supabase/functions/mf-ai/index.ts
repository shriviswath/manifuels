// ManiFuels — assistant gateway (Supabase Edge Function `mf-ai`)        MF_AI_V1
//
// The only job of this function is to hold the language-model key and decide
// who may use it. It never reads a single business record: the app works out
// every figure on the phone, with the same code that draws the Reports page,
// and sends the model only the short results it needs to word an answer.
//
//   phone ──(signed-in session)──► mf-ai ──(provider key)──► language model
//                                    │
//                                    └─ mf_ai_gate()  owner / manager only,
//                                                     daily and per-minute limits
//
// Deploy: Supabase → Edge Functions → Deploy a new function → Via Editor,
// name it exactly `mf-ai`, paste this whole file, leave "Verify JWT" ON.
// Secret (Edge Functions → Secrets):  GROQ_API_KEY = your key from console.groq.com
// Run db/021_ai_assistant.sql after it. Full steps: docs/AI_ASSISTANT_SETUP.md
//
// Optional secrets — only to change provider or models later, no code change:
//   MF_AI_BASE_URL  any OpenAI-compatible endpoint   (default: Groq)
//   MF_AI_KEY       its key                          (default: GROQ_API_KEY)
//   MF_AI_MODELS    comma-separated, tried in order  (default below)
//
// No imports on purpose: nothing to fetch at deploy time, nothing to go stale.

const BASE_URL = (Deno.env.get("MF_AI_BASE_URL") || "https://api.groq.com/openai/v1").replace(/\/+$/, "");
const API_KEY = Deno.env.get("MF_AI_KEY") || Deno.env.get("GROQ_API_KEY") || "";
// Tried in order. Each model has its own free allowance at the provider, so
// the second one is real extra capacity, not just a spare.
const MODELS = (Deno.env.get("MF_AI_MODELS") || "openai/gpt-oss-120b,openai/gpt-oss-20b")
  .split(",").map((s) => s.trim()).filter(Boolean);
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") || "";
const SUPABASE_ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY") || "";

// Hard ceilings, whatever the phone asks for.
const MAX_BODY = 64_000; // bytes of request
const MAX_MESSAGES = 40;
const MAX_TOOLS = 24;
const MAX_OUT_TOKENS = 900;
const PROVIDER_TIMEOUT_MS = 25_000;

const CORS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Max-Age": "86400",
};

function reply(status: number, body: unknown, extra: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json", "Cache-Control": "no-store", ...extra },
  });
}

// Calls a database function AS THE CALLER (their session token), so the
// database — not this function, and not the browser — decides who they are.
async function rpc(fn: string, auth: string, args: unknown) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/rpc/${fn}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", apikey: SUPABASE_ANON_KEY, Authorization: auth },
    body: JSON.stringify(args ?? {}),
  });
  const text = await r.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch (_e) { data = text; }
  return { ok: r.ok, status: r.status, data };
}

type Msg = { role: string; content?: unknown; tool_calls?: unknown; tool_call_id?: unknown; name?: unknown };

// Only the shapes the app sends are let through; anything else is refused
// rather than forwarded to the provider on the station's key.
function cleanMessages(input: unknown): Msg[] | string {
  if (!Array.isArray(input) || !input.length) return "messages missing";
  if (input.length > MAX_MESSAGES) return "conversation too long";
  const out: Msg[] = [];
  for (const m of input) {
    if (!m || typeof m !== "object") return "bad message";
    const role = String((m as Msg).role || "");
    if (!["system", "user", "assistant", "tool"].includes(role)) return "bad role";
    const content = (m as Msg).content;
    if (content != null && typeof content !== "string") return "content must be text";
    if (typeof content === "string" && content.length > 14_000) return "message too long";
    const msg: Msg = { role, content: content ?? (role === "assistant" ? null : "") };
    if (role === "assistant" && Array.isArray((m as Msg).tool_calls)) {
      const calls = [];
      for (const c of (m as { tool_calls: unknown[] }).tool_calls.slice(0, 4)) {
        const cc = c as { id?: unknown; function?: { name?: unknown; arguments?: unknown } };
        const name = String(cc?.function?.name || "");
        if (!/^[a-z_]{1,40}$/.test(name)) return "bad tool call";
        calls.push({ id: String(cc.id || "").slice(0, 80), type: "function",
          function: { name, arguments: String(cc.function?.arguments ?? "{}").slice(0, 2000) } });
      }
      if (calls.length) msg.tool_calls = calls;
    }
    if (role === "tool") msg.tool_call_id = String((m as Msg).tool_call_id || "").slice(0, 80);
    out.push(msg);
  }
  return out;
}

function cleanTools(input: unknown): unknown[] | string {
  if (input == null) return [];
  if (!Array.isArray(input)) return "bad tools";
  if (input.length > MAX_TOOLS) return "too many tools";
  const out = [];
  for (const t of input) {
    const f = (t as { function?: { name?: unknown; description?: unknown; parameters?: unknown } })?.function;
    const name = String(f?.name || "");
    if (!/^[a-z_]{1,40}$/.test(name)) return "bad tool name";
    out.push({ type: "function", function: {
      name, description: String(f?.description || "").slice(0, 600),
      parameters: (f?.parameters && typeof f.parameters === "object") ? f.parameters : { type: "object", properties: {} },
    } });
  }
  return out;
}

type Attempt = { status: number; body: unknown; retryAfter: number; model: string };

async function ask(model: string, messages: Msg[], tools: unknown[]): Promise<Attempt> {
  const payload: Record<string, unknown> = {
    model, messages, temperature: 0.2, max_completion_tokens: MAX_OUT_TOKENS, stream: false,
  };
  if (tools.length) { payload.tools = tools; payload.tool_choice = "auto"; }
  // The gpt-oss models think before answering; that thinking is billed as
  // output. "low" is plenty for picking a tool and wording a figure.
  if (/gpt-oss/.test(model)) { payload.reasoning_effort = "low"; payload.include_reasoning = false; }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), PROVIDER_TIMEOUT_MS);
  try {
    const r = await fetch(`${BASE_URL}/chat/completions`, {
      method: "POST", signal: ctl.signal,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${API_KEY}` },
      body: JSON.stringify(payload),
    });
    const text = await r.text();
    let body: unknown = null;
    try { body = JSON.parse(text); } catch (_e) { body = { raw: text.slice(0, 300) }; }
    return { status: r.status, body, model, retryAfter: Math.ceil(Number(r.headers.get("retry-after")) || 0) };
  } catch (e) {
    return { status: 0, body: { error: { message: String((e as Error)?.message || e) } }, model, retryAfter: 0 };
  } finally {
    clearTimeout(timer);
  }
}

function errCode(a: Attempt): string {
  const e = (a.body as { error?: { code?: unknown; type?: unknown } })?.error;
  return String(e?.code || e?.type || "");
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return reply(405, { error: "method" });

  const auth = req.headers.get("Authorization") || "";
  if (!/^Bearer\s+\S+/.test(auth)) return reply(401, { error: "signin" });

  const raw = await req.text();
  if (raw.length > MAX_BODY) return reply(413, { error: "too_big" });
  let body: Record<string, unknown>;
  try { body = JSON.parse(raw || "{}"); } catch (_e) { return reply(400, { error: "bad_json" }); }

  // "Is it set up, and may I use it?" — answered without spending a model call.
  if (body.ping) {
    const s = await rpc("mf_ai_status", auth, {});
    if (!s.ok) return reply(503, { error: "not_set_up", detail: "db/021_ai_assistant.sql has not been run" });
    return reply(200, { ...(s.data as object), configured: !!API_KEY, models: MODELS });
  }

  const messages = cleanMessages(body.messages);
  if (typeof messages === "string") return reply(400, { error: "bad_request", detail: messages });
  const tools = cleanTools(body.tools);
  if (typeof tools === "string") return reply(400, { error: "bad_request", detail: tools });

  // Who is asking, and are they within the limits? Decided in the database.
  const gate = await rpc("mf_ai_gate", auth, {});
  if (!gate.ok) {
    if (gate.status === 401) return reply(401, { error: "signin" });
    return reply(503, { error: "not_set_up", detail: "db/021_ai_assistant.sql has not been run" });
  }
  const g = (gate.data || {}) as { ok?: boolean; error?: string; id?: number; left_today?: number; retry_after?: number };
  if (!g.ok) {
    if (g.error === "limit_minute" || g.error === "limit_user_day" || g.error === "limit_station_day") {
      return reply(429, { error: g.error, retry_after: g.retry_after || 60 }, { "Retry-After": String(g.retry_after || 60) });
    }
    return reply(403, { error: g.error || "forbidden" });
  }
  const done = (status: number, model: string, u?: { prompt_tokens?: number; completion_tokens?: number; prompt_tokens_details?: { cached_tokens?: number } }) =>
    rpc("mf_ai_done", auth, {
      p_id: g.id, p_status: status, p_model: model,
      p_in: u?.prompt_tokens ?? 0, p_out: u?.completion_tokens ?? 0, p_cached: u?.prompt_tokens_details?.cached_tokens ?? 0,
    }).catch(() => null);

  if (!API_KEY) { await done(503, ""); return reply(503, { error: "not_configured", detail: "GROQ_API_KEY secret is not set" }); }

  // Walk the model list. A busy or rate-limited model hands over to the next;
  // a malformed tool call from the model gets one more try on the same model.
  let last: Attempt | null = null;
  let waited = 0;
  for (const model of MODELS) {
    for (let attempt = 0; attempt < 2; attempt++) {
      const a = await ask(model, messages, tools as unknown[]);
      last = a;
      if (a.status === 200) {
        const b = a.body as { choices?: { message?: { content?: unknown; tool_calls?: unknown } }[]; usage?: Record<string, unknown> };
        const m = b.choices?.[0]?.message;
        if (!m) break;
        await done(200, model, b.usage as never);
        return reply(200, {
          message: { role: "assistant", content: typeof m.content === "string" ? m.content : "", tool_calls: Array.isArray(m.tool_calls) ? m.tool_calls : undefined },
          model, left_today: g.left_today ?? null,
          usage: b.usage ? { in: b.usage.prompt_tokens, out: b.usage.completion_tokens } : null,
        });
      }
      if (a.status === 429) { waited = waited ? Math.min(waited, a.retryAfter || 30) : (a.retryAfter || 30); break; }
      if (a.status === 400 && /tool_use_failed|failed_generation/.test(errCode(a)) && attempt === 0) continue;
      if (a.status === 401 || a.status === 403) {
        await done(a.status, model);
        return reply(503, { error: "not_configured", detail: "the provider rejected the key" });
      }
      break; // 4xx/5xx/timeouts: try the next model
    }
  }
  const st = last?.status || 0;
  await done(st || 599, last?.model || "");
  if (st === 429) return reply(429, { error: "limit_provider", retry_after: waited || 30 }, { "Retry-After": String(waited || 30) });
  return reply(502, { error: "provider", detail: `model answered ${st || "nothing"}${errCode(last as Attempt) ? " (" + errCode(last as Attempt) + ")" : ""}` });
});
