/**
 * Academia Jarvis — /improve endpoint (multi-provider)
 *
 * Recibe el estado de aprendizaje del usuario y devuelve:
 *   - recap personalizado (3-4 líneas)
 *   - glosario adaptativo (1-3 términos nuevos)
 *   - próxima acción concreta
 *
 * DEFAULT: Google Gemini 2.5 Flash (10× más barato que Claude Haiku)
 * Override por request: { provider: 'anthropic', model: 'claude-haiku-4-5' }
 *
 * Costo aprox por request:
 *   - gemini-2.5-flash:    ~$0.001 (10× más barato)
 *   - claude-haiku-4-5:    ~$0.01
 *   - gpt-5-mini:          ~$0.002
 *
 * Variables (wrangler secret put):
 *   - GOOGLE_API_KEY     (requerido si usas default)
 *   - ANTHROPIC_API_KEY  (opcional)
 *   - OPENAI_API_KEY     (opcional)
 *   - ALLOWED_ORIGIN     (opcional)
 *   - DEFAULT_PROVIDER   (opcional, default 'google')
 *   - DEFAULT_MODEL      (opcional, default 'gemini-2.5-flash')
 */

import { chat, resolveProvider } from './lib/providers.js';

const FALLBACK_PROVIDER = { provider: 'google', model: 'gemini-2.5-flash' };

function corsHeaders(allowed) {
  const allow = (allowed && allowed !== '*') ? allowed : '*';
  return {
    'Access-Control-Allow-Origin': allow,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

const SYSTEM_PROMPT = `Eres el tutor personal de "Academia Jarvis", un programa de 8 semanas para construir agentes de IA basado en la documentación oficial de Anthropic (Building Effective Agents).

El usuario acaba de completar una sesión. Tu tarea: generar UNA respuesta breve, motivante y específica.

REGLAS ESTRICTAS:
1. Responde SOLO con JSON válido — sin markdown, sin código, sin explicaciones extra.
2. Idioma: español.
3. Recap: máximo 280 caracteres. Captura el insight más importante de la sesión, conectado al contexto del usuario.
4. Glosario: 0-3 términos NUEVOS (no incluyas los que ya están en glossarySoFar). Solo si la sesión introduce términos relevantes.
5. nextAction: máximo 200 caracteres. Una sola acción concreta, factible en <30 minutos, ajustada a su progreso.
6. Tono: profesional pero cálido. Como un mentor con experiencia.

FORMATO JSON REQUERIDO:
{
  "recap": "string max 280 chars",
  "glossary": [{"term": "string", "definition": "string max 120 chars"}],
  "nextAction": "string max 200 chars"
}`;

function userMessage(state) {
  return `Sesión completada: "${state.sessionTitle}"

Objetivos de la sesión:
${(state.sessionObjectives || []).map(o => `- ${o}`).join('\n')}

Ejercicio que acaba de hacer:
${state.sessionExercise || '(sin ejercicio)'}

Progreso del usuario:
- Sesiones completadas (de 12): ${(state.completedSessions || []).length} → [${(state.completedSessions || []).join(', ')}]
- Semanas completadas (de 8): ${(state.completedWeeks || []).length} → [${(state.completedWeeks || []).join(', ')}]
- Términos ya en su glosario: ${(state.glossarySoFar || []).join(', ') || '(ninguno aún)'}

Genera el JSON exacto según el formato.`;
}

export default {
  async fetch(request, env) {
    const cors = corsHeaders(env.ALLOWED_ORIGIN);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors });
    }

    const url = new URL(request.url);
    if (url.pathname !== '/improve' || request.method !== 'POST') {
      return new Response(JSON.stringify({ error: 'POST /improve only' }), {
        status: 404, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }

    let body;
    try { body = await request.json(); } catch {
      return new Response(JSON.stringify({ error: 'Invalid JSON' }), {
        status: 400, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }

    if (!body.sessionTitle) {
      return new Response(JSON.stringify({ error: 'Missing sessionTitle' }), {
        status: 400, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }

    const { provider, model } = resolveProvider(env, body, FALLBACK_PROVIDER);

    try {
      const result = await chat(env, {
        provider, model,
        system: SYSTEM_PROMPT,
        messages: [{ role: 'user', content: userMessage(body) }],
        maxTokens: 600,
        temperature: 0.3,
        jsonMode: true,
      });
      const match = result.text.match(/\{[\s\S]*\}/);
      if (!match) throw new Error('No JSON in response');
      const improvement = JSON.parse(match[0]);
      if (improvement.recap?.length > 320) improvement.recap = improvement.recap.slice(0, 320);
      if (improvement.nextAction?.length > 240) improvement.nextAction = improvement.nextAction.slice(0, 240);
      if (!Array.isArray(improvement.glossary)) improvement.glossary = [];
      improvement.source = `${provider}/${model}`;
      improvement.costUsd = result.costUsd;
      improvement.generatedAt = new Date().toISOString();
      return new Response(JSON.stringify(improvement), {
        status: 200, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: String(e.message || e), provider, model }), {
        status: 500, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }
  },
};
