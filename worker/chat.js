/**
 * Academia Jarvis — /chat endpoint (tutor en vivo, multi-provider)
 *
 * Recibe:
 *   - messages: historial completo
 *   - userContext: estado del estudiante
 *   - provider, model: opcionales para override
 *
 * DEFAULT: Anthropic Claude Sonnet 4.6 (mejor para código y agentes)
 * Alternativas vía request body:
 *   { provider: 'openai',  model: 'gpt-5' }
 *   { provider: 'google',  model: 'gemini-2.5-pro' }
 *
 * Costo aprox por pregunta (con historial ~10 mensajes):
 *   - claude-sonnet-4-6:  ~$0.05
 *   - gpt-5:              ~$0.04
 *   - gemini-2.5-pro:     ~$0.015
 *   - gemini-2.5-flash:   ~$0.002
 *
 * Variables (wrangler secret put):
 *   - ANTHROPIC_API_KEY  (requerido si usas default)
 *   - OPENAI_API_KEY     (opcional)
 *   - GOOGLE_API_KEY     (opcional)
 *   - ALLOWED_ORIGIN     (opcional)
 *   - DEFAULT_PROVIDER, DEFAULT_MODEL (opcionales)
 */

import { chat, resolveProvider, PROVIDERS } from './lib/providers.js';

const FALLBACK_PROVIDER = { provider: 'anthropic', model: 'claude-sonnet-4-6' };
const MAX_HISTORY = 20;

function corsHeaders(allowed) {
  const allow = (allowed && allowed !== '*') ? allowed : '*';
  return {
    'Access-Control-Allow-Origin': allow,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

const SYSTEM_PROMPT_TEMPLATE = `Eres el tutor personal de "Academia Jarvis", un programa de 8 semanas para construir agentes de IA basado en la documentación oficial de Anthropic.

Tu estudiante es Angel Trujillo. Está siguiendo el programa y puede preguntarte cualquier cosa sobre agentes IA, frameworks, Claude SDK, MCP, patrones de Anthropic, código, debugging, decisiones de arquitectura, etc.

ESTILO DE RESPUESTA:
1. Directo, sin preámbulos largos. Si la pregunta es factual, responde la cosa primero, contexto después.
2. Cita fuentes oficiales cuando aplique: Anthropic docs, papers, repos. Marca con [Anthropic], [paper], [docs].
3. Si la pregunta toca algo que ya cubre el programa, menciona la sesión específica (ej. "esto lo profundizamos en la Sesión 5").
4. Si pregunta algo fuera del scope pero relevante (comparar con OpenAI, framework X), respóndelo igual — eres el tutor universal de agentes.
5. Cuando recomiendes código, da TypeScript o Python según contexto. Compatible con Claude Agent SDK cuando aplique.
6. Idioma: español. Términos técnicos en inglés cuando son nombres propios.
7. Markdown ligero permitido: \`código inline\`, **negritas**, listas. Sin headers grandes (#, ##).
8. Si no sabes algo con certeza, dilo. No inventes URLs, números, ni citas.

CONTEXTO DEL ESTUDIANTE:
- Sesiones completadas: {completedSessions} / 12
- Semanas completadas: {completedWeeks} / 8
- Glosario adquirido: {glossaryTerms}
- Sesión actual de enfoque: {currentSession}
- Versión del contenido: {contentVersion}

PROGRAMA DE 12 SESIONES (referencia):
{sessionsSummary}

PRINCIPIOS BASE DEL PROGRAMA (Anthropic):
1. Simplicidad progresiva (prompt → tool → workflow → agente → multi-agente)
2. Tools = 80% del éxito
3. Objetivo medible primero
4. Limita iteraciones (max 10-20) y timeout (60s)
5. Modelo más barato que funcione (Haiku → Sonnet → Opus)
6. Observabilidad desde el día 0
7. Aislamiento en capas (RLS + filtros + tenant_id)
8. Few-shot diversos > perfectos
9. Subagents para investigar
10. CLAUDE.md corto y útil`;

function buildSystemPrompt(userCtx) {
  const completedSessions = userCtx.completedSessions || [];
  const completedWeeks = userCtx.completedWeeks || [];
  const glossary = userCtx.glossaryTerms || [];
  const sessions = userCtx.sessions || [];

  const sessionsSummary = sessions.length
    ? sessions.map(s => `  ${String(s.n).padStart(2, '0')}. ${s.title} — ${s.sub}`).join('\n')
    : '  (catálogo no disponible)';

  return SYSTEM_PROMPT_TEMPLATE
    .replace('{completedSessions}', completedSessions.length)
    .replace('{completedWeeks}', completedWeeks.length)
    .replace('{glossaryTerms}', glossary.length ? glossary.slice(0, 30).join(', ') : '(vacío)')
    .replace('{currentSession}', userCtx.currentSession || 'ninguna específica')
    .replace('{contentVersion}', userCtx.contentVersion || 'v1')
    .replace('{sessionsSummary}', sessionsSummary);
}

export default {
  async fetch(request, env) {
    const cors = corsHeaders(env.ALLOWED_ORIGIN);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors });
    }

    const url = new URL(request.url);

    // GET /providers — devuelve catálogo de proveedores/modelos disponibles
    if (url.pathname === '/providers' && request.method === 'GET') {
      const available = {};
      for (const [key, prov] of Object.entries(PROVIDERS)) {
        if (env[prov.envKey]) {
          available[key] = {
            label: prov.label,
            defaultModel: prov.defaultModel,
            cheapModel: prov.cheapModel,
            models: prov.models,
          };
        }
      }
      return new Response(JSON.stringify({ available, default: FALLBACK_PROVIDER }), {
        status: 200, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }

    if (url.pathname !== '/chat' || request.method !== 'POST') {
      return new Response(JSON.stringify({ error: 'POST /chat or GET /providers only' }), {
        status: 404, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }

    let body;
    try { body = await request.json(); } catch {
      return new Response(JSON.stringify({ error: 'Invalid JSON' }), {
        status: 400, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }

    const { messages = [], userContext = {} } = body;
    if (!Array.isArray(messages) || messages.length === 0) {
      return new Response(JSON.stringify({ error: 'Missing messages[]' }), {
        status: 400, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }

    const trimmed = messages.slice(-MAX_HISTORY);
    const valid = trimmed.every(m => m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string' && m.content.length > 0);
    if (!valid) {
      return new Response(JSON.stringify({ error: 'Invalid message shape' }), {
        status: 400, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }

    const { provider, model } = resolveProvider(env, body, FALLBACK_PROVIDER);

    try {
      const system = buildSystemPrompt(userContext);
      const result = await chat(env, {
        provider, model,
        system,
        messages: trimmed,
        maxTokens: 1500,
      });
      return new Response(JSON.stringify({
        reply: result.text,
        usage: result.usage,
        provider: result.provider,
        model: result.model,
        costUsd: result.costUsd,
        finishReason: result.finishReason,
        ts: new Date().toISOString(),
      }), {
        status: 200, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: String(e.message || e), provider, model }), {
        status: 500, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }
  },
};
