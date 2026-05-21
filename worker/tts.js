/**
 * Academia Jarvis — /tts endpoint
 *
 * Genera audio MP3 usando Google Cloud Text-to-Speech (Neural2 español).
 * Cachea agresivamente en Cloudflare R2 → re-escuchas no consumen cuota.
 *
 * Free tier Google Cloud: 1,000,000 caracteres/mes en voces Neural2.
 * Costo después: $16 por millón de caracteres.
 *
 * Voces recomendadas (español):
 *   - es-US-Neural2-A (femenina, neutra clara)
 *   - es-US-Neural2-B (masculina, neutra)
 *   - es-US-Neural2-C (femenina, cálida)
 *   - es-ES-Neural2-A,B,C,D,E,F (España)
 *   - es-MX (México) — disponibles vía Polyglot
 *
 * Variables (wrangler secret put):
 *   - GOOGLE_TTS_API_KEY  (requerido)
 *   - ALLOWED_ORIGIN      (opcional, default '*')
 *
 * R2 binding (configurado en wrangler.tts.toml):
 *   - AUDIO_CACHE
 */

const GOOGLE_TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize";

const DEFAULTS = {
  voice: "es-US-Neural2-A",
  languageCode: "es-US",
  speakingRate: 1.0,
  pitch: 0.0,
};

function corsHeaders(allowed) {
  const allow = (allowed && allowed !== "*") ? allowed : "*";
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
  };
}

async function sha256Hex(text) {
  const encoder = new TextEncoder();
  const data = encoder.encode(text);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(hashBuffer))
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");
}

function base64ToArrayBuffer(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

async function callGoogleTTS(apiKey, text, voice, languageCode, speakingRate, pitch) {
  const body = {
    input: { text },
    voice: { languageCode, name: voice },
    audioConfig: {
      audioEncoding: "MP3",
      speakingRate,
      pitch,
      sampleRateHertz: 24000,
    },
  };
  const res = await fetch(`${GOOGLE_TTS_URL}?key=${apiKey}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Google TTS ${res.status}: ${text.slice(0, 400)}`);
  }
  const data = await res.json();
  if (!data.audioContent) throw new Error("Google TTS returned no audioContent");
  return base64ToArrayBuffer(data.audioContent);
}

export default {
  async fetch(request, env) {
    const cors = corsHeaders(env.ALLOWED_ORIGIN);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }

    const url = new URL(request.url);

    // GET /tts/voices — lista voces disponibles
    if (url.pathname === "/tts/voices" && request.method === "GET") {
      return new Response(JSON.stringify({
        voices: [
          { code: "es-US-Neural2-A", label: "Femenina · Neutra (LatAm)", language: "es-US" },
          { code: "es-US-Neural2-B", label: "Masculina · Neutra (LatAm)", language: "es-US" },
          { code: "es-US-Neural2-C", label: "Femenina · Cálida (LatAm)", language: "es-US" },
          { code: "es-ES-Neural2-A", label: "Femenina · España", language: "es-ES" },
          { code: "es-ES-Neural2-B", label: "Masculina · España", language: "es-ES" },
          { code: "es-ES-Neural2-C", label: "Femenina · España (2)", language: "es-ES" },
          { code: "es-ES-Neural2-D", label: "Femenina · España (3)", language: "es-ES" },
          { code: "es-ES-Neural2-E", label: "Masculina · España (2)", language: "es-ES" },
          { code: "es-ES-Neural2-F", label: "Masculina · España (3)", language: "es-ES" },
        ],
        default: DEFAULTS.voice,
      }), { status: 200, headers: { ...cors, "Content-Type": "application/json" } });
    }

    if (url.pathname !== "/tts" || request.method !== "POST") {
      return new Response(JSON.stringify({ error: "POST /tts or GET /tts/voices only" }), {
        status: 404, headers: { ...cors, "Content-Type": "application/json" },
      });
    }

    if (!env.GOOGLE_TTS_API_KEY) {
      return new Response(JSON.stringify({ error: "Server misconfigured: missing GOOGLE_TTS_API_KEY" }), {
        status: 500, headers: { ...cors, "Content-Type": "application/json" },
      });
    }

    let body;
    try { body = await request.json(); } catch {
      return new Response(JSON.stringify({ error: "Invalid JSON" }), {
        status: 400, headers: { ...cors, "Content-Type": "application/json" },
      });
    }

    const text = (body.text || "").trim();
    if (!text) {
      return new Response(JSON.stringify({ error: "Missing text" }), {
        status: 400, headers: { ...cors, "Content-Type": "application/json" },
      });
    }
    if (text.length > 5000) {
      return new Response(JSON.stringify({ error: "Text too long (max 5000 chars per request). Split into smaller chunks." }), {
        status: 400, headers: { ...cors, "Content-Type": "application/json" },
      });
    }

    const voice = body.voice || DEFAULTS.voice;
    const languageCode = body.languageCode || (voice.startsWith("es-ES") ? "es-ES" : voice.startsWith("es-MX") ? "es-MX" : "es-US");
    const speakingRate = Math.max(0.25, Math.min(4.0, Number(body.speakingRate) || DEFAULTS.speakingRate));
    const pitch = Math.max(-20, Math.min(20, Number(body.pitch) || DEFAULTS.pitch));

    // Cache key — incluye texto + voz + velocidad + pitch para que distintas combinaciones sean distintas
    const cacheKey = await sha256Hex(`v1:${voice}:${speakingRate}:${pitch}:${text}`);
    const r2Key = `tts/${cacheKey}.mp3`;

    // Cache hit
    if (env.AUDIO_CACHE) {
      try {
        const cached = await env.AUDIO_CACHE.get(r2Key);
        if (cached) {
          return new Response(cached.body, {
            status: 200,
            headers: {
              ...cors,
              "Content-Type": "audio/mpeg",
              "X-Cache": "HIT",
              "Cache-Control": "public, max-age=2592000, immutable",
            },
          });
        }
      } catch (e) {
        // R2 error — log y sigue a generación
        console.warn("R2 read error:", e.message);
      }
    }

    // Cache miss — genera con Google TTS
    let audioBuffer;
    try {
      audioBuffer = await callGoogleTTS(
        env.GOOGLE_TTS_API_KEY, text, voice, languageCode, speakingRate, pitch
      );
    } catch (e) {
      return new Response(JSON.stringify({ error: String(e.message || e) }), {
        status: 500, headers: { ...cors, "Content-Type": "application/json" },
      });
    }

    // Guarda en R2 (no bloquea respuesta)
    if (env.AUDIO_CACHE) {
      env.AUDIO_CACHE.put(r2Key, audioBuffer, {
        httpMetadata: { contentType: "audio/mpeg" },
      }).catch(e => console.warn("R2 write error:", e.message));
    }

    return new Response(audioBuffer, {
      status: 200,
      headers: {
        ...cors,
        "Content-Type": "audio/mpeg",
        "X-Cache": "MISS",
        "X-Chars-Used": String(text.length),
        "Cache-Control": "public, max-age=2592000, immutable",
      },
    });
  },
};
