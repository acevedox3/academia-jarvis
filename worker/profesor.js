/**
 * Academia Jarvis — /profesor endpoint (Profesor narrador, Claude Haiku 4.5)
 *
 * Dos modos pedagógicos:
 *
 *   mode: 'enrich'
 *     Reescribe el texto de la sección añadiendo explicaciones, analogías,
 *     señalizadores de atención y pequeñas pausas pedagógicas. Devuelve
 *     un solo texto continuo que el TTS lee con la voz del narrador.
 *     Resultado: { enriched: "..." }
 *
 *   mode: 'comments'
 *     Lee el texto original y genera 2-5 comentarios cortos del profesor
 *     para intercalar entre párrafos. Cada comentario es una frase de
 *     introducción, énfasis, analogía o pregunta retórica. Se reproducen
 *     con una voz distinta (la del profesor) para crear contraste auditivo.
 *     Resultado: { comments: [{ afterParagraph: int, text: "..." }] }
 *
 * Variables (wrangler secret put):
 *   - ANTHROPIC_API_KEY (requerido)
 *   - ALLOWED_ORIGIN    (opcional, default '*')
 */

import { chat } from './lib/providers.js';

const DEFAULT_PROVIDER = 'anthropic';
const DEFAULT_MODEL = 'claude-haiku-4-5';

function corsHeaders(allowed) {
  const allow = (allowed && allowed !== '*') ? allowed : '*';
  return {
    'Access-Control-Allow-Origin': allow,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

// ============================================================
// PROMPTS
// ============================================================

const SYSTEM_ENRICH = `Eres un profesor experto en agentes de IA dando clase en vivo a un alumno adulto profesional. Tu voz va a ser leída en voz alta por un sintetizador (Google Neural2 español), así que escribes para el oído, no para el ojo.

Tu tarea: tomar un fragmento de texto académico de la "Academia Jarvis" (programa basado en Building Effective Agents de Anthropic) y reescribirlo como una versión narrada pedagógica, intercalando explicaciones que ayuden a entender mejor.

REGLAS DE REESCRITURA:
1. Conserva TODOS los hechos, datos, citas, papers, nombres propios y conceptos técnicos del texto original. No inventes nada nuevo.
2. Añade frases de señalización antes de ideas importantes: "fíjate bien en esto", "aquí viene la idea clave", "presta atención porque esto es lo que diferencia un juguete de un producto", etc. Usa estas con moderación, no más de una cada dos o tres párrafos.
3. Después de un concepto difícil, añade una explicación breve en lenguaje más simple, una analogía cotidiana, o un ejemplo concreto. Marca la transición con frases naturales como "te lo explico con una analogía", "dicho de otra forma", "piénsalo así".
4. Al final de cada subtema, lanza una pregunta retórica que invite a pensar, sin esperar respuesta. Ejemplo: "¿qué pasaría si no tuvieras este componente? Sigamos."
5. Escribe en español neutro latinoamericano, segunda persona singular (tú), tono cercano pero profesional, como un mentor con experiencia.
6. NO uses markdown: nada de asteriscos, almohadillas, viñetas, ni código entre backticks. Solo prosa pura con puntos y comas. El TTS lee carácter por carácter, así que cualquier símbolo arruina el audio.
7. NO uses encabezados ni listas. Convierte cualquier lista del original en prosa con conectores ("primero, segundo, por último", "en primer lugar, también, finalmente").
8. La versión enriquecida puede ser entre 1.2 y 1.7 veces más larga que el original, no más. Si el original es muy corto (menos de 200 palabras), puede crecer hasta 2x.
9. Mantén la estructura argumental del original: no reordenes ideas, no quites secciones, no agregues opiniones tuyas que contradigan al texto.
10. Responde SOLO con el texto enriquecido, sin preámbulos, sin "claro, aquí tienes", sin comillas alrededor, sin explicar qué hiciste.`;

const SYSTEM_COMMENTS = `Eres un profesor experto en agentes de IA dando clase en vivo. Estás escuchando junto a tu alumno la lectura de un fragmento de la "Academia Jarvis" y vas a intercalar comentarios cortos entre los párrafos para enriquecer su comprensión.

Tu voz va a ser leída por un sintetizador con una voz distinta a la del narrador principal, así que cuando interrumpes, el alumno reconoce de inmediato que eres tú quien habla. Por eso tus comentarios deben sentirse como las palabras de un profesor en clase, no como notas escritas.

REGLAS DE INTERVENCIÓN:
1. Decide en qué momentos interrumpir. El texto te llega como una lista de párrafos numerados desde 0. Tú devuelves un array con objetos del tipo { "afterParagraph": N, "text": "..." }, donde N es el índice del párrafo después del cual quieres que se inserte tu comentario.
2. Genera entre 2 y 5 comentarios para todo el fragmento. Si el fragmento es muy corto (1-2 párrafos), genera solo 1 comentario al final. No interrumpas en cada párrafo, eso cansa.
3. Cada comentario tiene entre 1 y 3 frases, máximo unos 60 a 90 palabras. Suficiente para añadir valor, no tanto como para romper el flujo.
4. Variedad de tipos de intervención: usa al menos dos tipos distintos entre los siguientes. Énfasis (resalta por qué algo es importante), analogía (compara con algo cotidiano), advertencia (señala un error común o un mito), pregunta socrática (invita a pensar sin dar respuesta), conexión (relaciona con otra sesión o concepto), aterrizaje práctico (cómo se ve esto en código real o en producción).
5. Habla siempre en segunda persona singular (tú), tono cercano, profesional, como mentor con experiencia. Español neutro latinoamericano.
6. NO uses markdown ni símbolos. Solo prosa hablable: puntos, comas, signos de interrogación.
7. NO repitas literalmente lo que ya dijo el texto. Aporta valor agregado: explica el por qué, el contexto, la implicación, o conecta con algo más.
8. Conserva los hechos del texto. No inventes datos, papers, autores ni citas.
9. Tu primer comentario suele ir después del párrafo 0 (apertura, encuadre) o después de un párrafo donde aparezca un concepto técnico difícil.
10. Responde SOLO con JSON válido en este formato exacto:
{ "comments": [ { "afterParagraph": 0, "text": "..." }, { "afterParagraph": 2, "text": "..." } ] }

Sin markdown alrededor, sin explicaciones, sin texto antes o después del JSON.`;

// ============================================================
// HELPERS
// ============================================================

function splitParagraphs(text) {
  // Divide por dobles saltos de línea (párrafos) o por punto seguido si no hay saltos
  if (!text) return [];
  const byBlank = text.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
  if (byBlank.length >= 2) return byBlank;
  // Fallback: dividir por oraciones agrupándolas de 2 en 2
  const sentences = text.split(/(?<=[.!?])\s+/).filter(Boolean);
  const grouped = [];
  for (let i = 0; i < sentences.length; i += 2) {
    grouped.push(sentences.slice(i, i + 2).join(' '));
  }
  return grouped;
}

function userMessageEnrich({ sessionTitle, sectionTitle, text }) {
  return `Sesión: ${sessionTitle || '(sin título)'}
Sección: ${sectionTitle || '(sin título)'}

Texto original a enriquecer:
"""
${text}
"""

Devuelve solo el texto enriquecido, en prosa pura, sin markdown, sin comillas alrededor.`;
}

function userMessageComments({ sessionTitle, sectionTitle, text }) {
  const paragraphs = splitParagraphs(text);
  const numbered = paragraphs.map((p, i) => `[Párrafo ${i}]: ${p}`).join('\n\n');
  return `Sesión: ${sessionTitle || '(sin título)'}
Sección: ${sectionTitle || '(sin título)'}

El narrador va a leer estos párrafos en orden. Decide después de cuáles intervenir.

${numbered}

Devuelve el JSON con los comentarios. Los índices "afterParagraph" deben estar entre 0 y ${paragraphs.length - 1}.`;
}

// ============================================================
// MAIN
// ============================================================

export default {
  async fetch(request, env) {
    const cors = corsHeaders(env.ALLOWED_ORIGIN);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors });
    }

    const url = new URL(request.url);
    if (url.pathname !== '/profesor' || request.method !== 'POST') {
      return new Response(JSON.stringify({ error: 'POST /profesor only' }), {
        status: 404, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }

    let body;
    try { body = await request.json(); } catch {
      return new Response(JSON.stringify({ error: 'Invalid JSON' }), {
        status: 400, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }

    const mode = body.mode;
    const text = (body.text || '').trim();
    const sectionTitle = (body.sectionTitle || '').trim();
    const sessionTitle = (body.sessionTitle || '').trim();

    if (!mode || (mode !== 'enrich' && mode !== 'comments')) {
      return new Response(JSON.stringify({ error: "mode must be 'enrich' or 'comments'" }), {
        status: 400, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }
    if (!text) {
      return new Response(JSON.stringify({ error: 'Missing text' }), {
        status: 400, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }
    if (text.length > 12000) {
      return new Response(JSON.stringify({ error: 'Text too long (max 12000 chars). Split into smaller sections.' }), {
        status: 400, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }

    const provider = body.provider || DEFAULT_PROVIDER;
    const model = body.model || DEFAULT_MODEL;

    try {
      if (mode === 'enrich') {
        const result = await chat(env, {
          provider, model,
          system: SYSTEM_ENRICH,
          messages: [{ role: 'user', content: userMessageEnrich({ sessionTitle, sectionTitle, text }) }],
          maxTokens: 4000,
          temperature: 0.55,
        });
        return new Response(JSON.stringify({
          enriched: result.text.trim(),
          source: `${provider}/${model}`,
          costUsd: result.costUsd,
          usage: result.usage,
          generatedAt: new Date().toISOString(),
        }), { status: 200, headers: { ...cors, 'Content-Type': 'application/json' } });
      }

      // mode === 'comments'
      const paragraphs = splitParagraphs(text);
      const result = await chat(env, {
        provider, model,
        system: SYSTEM_COMMENTS,
        messages: [{ role: 'user', content: userMessageComments({ sessionTitle, sectionTitle, text }) }],
        maxTokens: 1500,
        temperature: 0.6,
        jsonMode: true,
      });
      const match = result.text.match(/\{[\s\S]*\}/);
      if (!match) throw new Error('Profesor: no JSON in response');
      const parsed = JSON.parse(match[0]);
      const comments = Array.isArray(parsed.comments) ? parsed.comments : [];
      // Sanitiza y filtra comentarios inválidos
      const clean = comments
        .filter(c => typeof c.afterParagraph === 'number'
                  && c.afterParagraph >= 0
                  && c.afterParagraph < paragraphs.length
                  && typeof c.text === 'string'
                  && c.text.trim().length > 0)
        .map(c => ({
          afterParagraph: Math.floor(c.afterParagraph),
          text: c.text.trim(),
        }))
        .sort((a, b) => a.afterParagraph - b.afterParagraph);

      return new Response(JSON.stringify({
        comments: clean,
        paragraphCount: paragraphs.length,
        source: `${provider}/${model}`,
        costUsd: result.costUsd,
        usage: result.usage,
        generatedAt: new Date().toISOString(),
      }), { status: 200, headers: { ...cors, 'Content-Type': 'application/json' } });

    } catch (e) {
      return new Response(JSON.stringify({ error: String(e.message || e), mode, provider, model }), {
        status: 500, headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }
  },
};
