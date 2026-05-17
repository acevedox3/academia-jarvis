/**
 * Multi-provider adapter for LLM APIs.
 *
 * Soporta:
 *   - anthropic  (Claude Haiku/Sonnet/Opus)   — api.anthropic.com
 *   - openai     (GPT-5 / GPT-5 mini / nano)  — api.openai.com
 *   - google     (Gemini 2.5 Flash/Pro)       — generativelanguage.googleapis.com
 *
 * Uso:
 *   import { chat, PROVIDERS, PRICING } from './lib/providers.js';
 *
 *   const result = await chat(env, {
 *     provider: 'google',
 *     model:    'gemini-2.5-flash',
 *     system:   'Eres un asistente...',
 *     messages: [{role: 'user', content: '...'}],
 *     maxTokens: 1024,
 *     jsonMode: true,         // opcional, fuerza JSON
 *     temperature: 0.0
 *   });
 *   // → { text, usage: {inputTokens, outputTokens}, model, costUsd, provider }
 *
 * Las claves se leen del env: ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY
 */

// ============================================================
// PRICING (USD per million tokens, mayo 2026)
// ============================================================
export const PRICING = {
  // Anthropic
  'claude-haiku-4-5':       { in: 1.00,  out: 5.00  },
  'claude-haiku-4-5-20251001': { in: 1.00, out: 5.00 },
  'claude-sonnet-4-6':      { in: 3.00,  out: 15.00 },
  'claude-opus-4-7':        { in: 5.00,  out: 25.00 },
  'claude-opus-4-6':        { in: 5.00,  out: 25.00 },

  // OpenAI (estimados — verifica platform.openai.com/pricing)
  'gpt-5':                  { in: 3.00,  out: 12.00 },
  'gpt-5-mini':             { in: 0.25, out: 2.00 },
  'gpt-5-nano':             { in: 0.10, out: 0.40 },
  'gpt-4o':                 { in: 2.50, out: 10.00 },
  'gpt-4o-mini':            { in: 0.15, out: 0.60 },

  // Google (estimados — verifica ai.google.dev/pricing)
  'gemini-2.5-flash':       { in: 0.10, out: 0.40 },
  'gemini-2.5-flash-lite':  { in: 0.075, out: 0.30 },
  'gemini-2.5-pro':         { in: 1.25, out: 5.00 },
  'gemini-2.0-flash':       { in: 0.10, out: 0.40 },
};

// ============================================================
// PROVIDERS catalog
// ============================================================
export const PROVIDERS = {
  anthropic: {
    label: 'Anthropic Claude',
    defaultModel: 'claude-sonnet-4-6',
    cheapModel:   'claude-haiku-4-5',
    models: ['claude-haiku-4-5', 'claude-sonnet-4-6', 'claude-opus-4-7'],
    envKey: 'ANTHROPIC_API_KEY',
  },
  openai: {
    label: 'OpenAI GPT',
    defaultModel: 'gpt-5',
    cheapModel:   'gpt-5-mini',
    models: ['gpt-5-nano', 'gpt-5-mini', 'gpt-5', 'gpt-4o', 'gpt-4o-mini'],
    envKey: 'OPENAI_API_KEY',
  },
  google: {
    label: 'Google Gemini',
    defaultModel: 'gemini-2.5-pro',
    cheapModel:   'gemini-2.5-flash',
    models: ['gemini-2.5-flash-lite', 'gemini-2.5-flash', 'gemini-2.5-pro'],
    envKey: 'GOOGLE_API_KEY',
  },
};

export function costUsd(model, inputTokens, outputTokens) {
  const p = PRICING[model];
  if (!p) return null;
  return (inputTokens * p.in + outputTokens * p.out) / 1_000_000;
}

// ============================================================
// MAIN: chat()
// ============================================================
export async function chat(env, opts) {
  const provider = opts.provider || 'anthropic';
  const model = opts.model || PROVIDERS[provider]?.defaultModel;
  if (!model) throw new Error(`Unknown provider ${provider}`);

  const apiKey = env[PROVIDERS[provider].envKey];
  if (!apiKey) {
    throw new Error(`Missing ${PROVIDERS[provider].envKey} in env`);
  }

  let result;
  switch (provider) {
    case 'anthropic': result = await anthropicChat(apiKey, model, opts); break;
    case 'openai':    result = await openaiChat(apiKey, model, opts); break;
    case 'google':    result = await googleChat(apiKey, model, opts); break;
    default: throw new Error(`Unknown provider ${provider}`);
  }
  result.provider = provider;
  result.model = model;
  result.costUsd = costUsd(model, result.usage.inputTokens, result.usage.outputTokens);
  return result;
}

// ============================================================
// ANTHROPIC adapter
// ============================================================
async function anthropicChat(apiKey, model, opts) {
  const body = {
    model,
    max_tokens: opts.maxTokens || 1024,
    messages: opts.messages,
  };
  if (opts.system) body.system = opts.system;
  if (opts.temperature !== undefined) body.temperature = opts.temperature;

  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`Anthropic ${res.status}: ${t.slice(0, 300)}`);
  }
  const data = await res.json();
  return {
    text: data.content?.[0]?.text || '',
    usage: {
      inputTokens: data.usage?.input_tokens || 0,
      outputTokens: data.usage?.output_tokens || 0,
    },
    finishReason: data.stop_reason || 'unknown',
    raw: data,
  };
}

// ============================================================
// OPENAI adapter (Chat Completions format)
// ============================================================
async function openaiChat(apiKey, model, opts) {
  const messages = [];
  if (opts.system) messages.push({ role: 'system', content: opts.system });
  for (const m of opts.messages) messages.push({ role: m.role, content: m.content });

  const body = {
    model,
    messages,
    max_completion_tokens: opts.maxTokens || 1024,
  };
  if (opts.temperature !== undefined) body.temperature = opts.temperature;
  if (opts.jsonMode) body.response_format = { type: 'json_object' };

  const res = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`OpenAI ${res.status}: ${t.slice(0, 300)}`);
  }
  const data = await res.json();
  return {
    text: data.choices?.[0]?.message?.content || '',
    usage: {
      inputTokens: data.usage?.prompt_tokens || 0,
      outputTokens: data.usage?.completion_tokens || 0,
    },
    finishReason: data.choices?.[0]?.finish_reason || 'unknown',
    raw: data,
  };
}

// ============================================================
// GOOGLE GEMINI adapter
// ============================================================
async function googleChat(apiKey, model, opts) {
  // Gemini usa "contents" array con roles user/model (no assistant)
  const contents = opts.messages.map(m => ({
    role: m.role === 'assistant' ? 'model' : m.role,
    parts: [{ text: m.content }],
  }));

  const body = {
    contents,
    generationConfig: {
      maxOutputTokens: opts.maxTokens || 1024,
    },
  };
  if (opts.system) {
    body.systemInstruction = { parts: [{ text: opts.system }] };
  }
  if (opts.temperature !== undefined) {
    body.generationConfig.temperature = opts.temperature;
  }
  if (opts.jsonMode) {
    body.generationConfig.responseMimeType = 'application/json';
  }

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`Google ${res.status}: ${t.slice(0, 300)}`);
  }
  const data = await res.json();
  const candidate = data.candidates?.[0];
  const text = candidate?.content?.parts?.map(p => p.text).join('') || '';
  return {
    text,
    usage: {
      inputTokens: data.usageMetadata?.promptTokenCount || 0,
      outputTokens: data.usageMetadata?.candidatesTokenCount || 0,
    },
    finishReason: candidate?.finishReason || 'unknown',
    raw: data,
  };
}

// ============================================================
// Helper: resolve provider+model from optional request body + env defaults
// ============================================================
export function resolveProvider(env, body, fallback) {
  const provider = body?.provider || env.DEFAULT_PROVIDER || fallback.provider;
  const model = body?.model || env.DEFAULT_MODEL || fallback.model;
  return { provider, model };
}
