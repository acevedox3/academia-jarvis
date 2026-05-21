# Academia Jarvis · App iPad v5 (TTS + Módulo I expandido)

Construido sobre tu HTML Coursera-style. Contenido profundo por sesión. Tutor en vivo **con soporte de 3 proveedores LLM** (Anthropic, OpenAI, Google). **TTS con Google Cloud Neural2** para escuchar las sesiones en voz alta. Auto-actualización semanal. App nativa iOS vía Capacitor.

## URLs en producción

| Servicio | URL | Estado |
|---|---|---|
| TTS Worker | `https://academia-jarvis-tts.angeljarvis.workers.dev` | ✅ Live |
| Chat Worker | `https://academia-jarvis-chat.<subdomain>.workers.dev` | Pendiente desplegar |
| Improve Worker | `https://academia-jarvis-improve.<subdomain>.workers.dev` | Pendiente desplegar |
| GitHub Pages | `https://<TU-USUARIO>.github.io/academia-jarvis/` | Configurar tras push |

## Cómo desplegar la app (3 caminos)

**1. GitHub + Pages (recomendado):** Doble-click `Deploy-To-GitHub.command` después de poner tu repo URL. La GitHub Action `deploy-pages.yml` publica `docs/` automáticamente.

**2. Hosting estático manual:** Sube todo el contenido de `docs/` a Netlify, Vercel, Cloudflare Pages, o cualquier servidor estático. No requiere build step.

**3. iPad nativo:** `npm install && npm run sync && npm run open:ios` → Xcode → signing → build a tu iPad. Detalles abajo.

## Multi-provider — qué proveedor usa qué endpoint

| Endpoint | Default | Por qué | Override |
|---|---|---|---|
| `/improve` (recap por sesión) | **Gemini 2.5 Flash** | 10× más barato que Haiku, calidad suficiente | Body: `{ provider, model }` |
| `/chat` (tutor en vivo) | **Claude Sonnet 4.6** | Mejor en código y agentes, alineado con la academia | Drop-down en UI o body |
| Updater semanal | **Gemini 2.5 Flash** | Tarea de escaneo + diff, barata | Env var `PROVIDER`/`MODEL` |

**Costos comparados** (Mayo 2026):

| Modelo | Input ($/M) | Output ($/M) | Mejor para |
|---|---|---|---|
| `gemini-2.5-flash` | $0.10 | $0.40 | Tareas simples, 10× más barato que Haiku |
| `gemini-2.5-pro` | $1.25 | $5.00 | Context largo (2M tokens), razonamiento medio |
| `claude-haiku-4-5` | $1.00 | $5.00 | Balance código/costo |
| `claude-sonnet-4-6` | $3.00 | $15.00 | Código complejo, agentes |
| `claude-opus-4-7` | $5.00 | $25.00 | Razonamiento profundo, decisiones críticas |
| `gpt-5-mini` | $0.25 | $2.00 | Razonamiento simple |
| `gpt-5` | $3.00 | $12.00 | Razonamiento profundo |
| `gpt-5-nano` | $0.10 | $0.40 | Ultra-barato como Gemini Flash |

**Verifica precios actualizados:** Anthropic [platform.claude.com/pricing](https://platform.claude.com/docs/en/about-claude/pricing) · OpenAI [platform.openai.com/pricing](https://platform.openai.com/docs/pricing) · Google [ai.google.dev/pricing](https://ai.google.dev/pricing).

---

## Las 4 capas de coordinación

Cada sesión tiene un `id` numérico. Ese ID es la llave que coordina todo:

```
SESIÓN N
  │
  ├── Capa A · STATIC (content.json)
  │     deep.intro / sections / gotchas / quiz / references
  │
  ├── Capa B · CONTEXT (tutor en vivo sabe currentSession=N)
  │     Worker /chat recibe userContext con sesión activa
  │
  ├── Capa C · ACTIONS (al completar sesión)
  │     Worker /improve recibe sessionId=N → recap personalizado
  │
  └── Capa D · MEMORY (acumulada en localStorage)
        glossary, sessionImprovements, progress
```

---

## Estructura del repositorio

```
academia-app-v3/
├── docs/                         ← GitHub Pages sirve esta carpeta (convención GH Pages)
│   ├── index.html                ← tu diseño Coursera + tabs modal + chat embebido
│   ├── content.json              ← 12 sesiones con deep + 8 weeks + 3 projects + 10 rules + 30 resources
│   ├── manifest.json             ← PWA manifest
│   ├── sw.js                     ← service worker (offline)
│   └── icons/                    ← 19 PNGs para iOS + PWA
├── icons/                        ← copia para Xcode AppIcon.appiconset
├── scripts/
│   ├── append_sessions.py        ← (usado una vez para generar las 12 sesiones; ya corrió)
│   ├── gen_icons.py              ← regenera iconos desde diseño base
│   └── update_content.py         ← updater semanal (corre en GH Action)
├── worker/
│   ├── worker.js                 ← /improve endpoint (Claude Haiku)
│   ├── chat.js                   ← /chat endpoint (Claude Sonnet)
│   ├── wrangler.improve.toml
│   └── wrangler.chat.toml
├── .github/workflows/
│   └── update-content.yml        ← cron semanal lunes 7am UTC
├── capacitor.config.json         ← bundle ID: com.angel.academiajarvis
├── package.json
└── README.md                     ← este archivo
```

---

## Despliegue completo (haz una sola vez)

### Paso 1 · Subir a GitHub

```bash
cd academia-app-v3
git init
git add .
git commit -m "feat: Academia Jarvis v3"
git branch -M main
git remote add origin https://github.com/acevedox3/academia-jarvis.git
git push -u origin main
```

### Paso 2 · Habilitar GitHub Pages

Settings → Pages → Source: Deploy from a branch → Branch: `main`, Folder: `/www` → Save.

En ~1 minuto tu academia está online en `https://acevedox3.github.io/academia-jarvis/`.

### Paso 3 · Configurar updates automáticos

Settings → Secrets and variables → Actions → New repository secret. Agrega **al menos uno** de:

- `GOOGLE_API_KEY` — obtén en [aistudio.google.com](https://aistudio.google.com) (gratis para empezar, recomendado para updater)
- `ANTHROPIC_API_KEY` — obtén en [console.anthropic.com](https://console.anthropic.com)
- `OPENAI_API_KEY` — obtén en [platform.openai.com](https://platform.openai.com)

El default es Gemini Flash (más barato). Si solo configuras ANTHROPIC, edita `.github/workflows/update-content.yml` y cambia `PROVIDER` a `anthropic`.

El GitHub Action corre automáticamente cada lunes a las 7am UTC. Para probarlo ahora: Actions → Weekly content update → Run workflow → elige `provider` y `mode: dry-run`.

### Paso 4 · Desplegar los dos workers en Cloudflare

```bash
npm install -g wrangler
wrangler login                    # navegador → login con cuenta Cloudflare (gratis)

cd worker

# Configura secrets para CADA worker. Para cada uno, agrega los proveedores
# que quieras tener disponibles. MÍNIMO uno; los 3 si quieres el switcher completo.

# Worker 1 — /improve (default Gemini Flash, 10× más barato)
wrangler secret put GOOGLE_API_KEY    --config wrangler.improve.toml   # default
wrangler secret put ANTHROPIC_API_KEY --config wrangler.improve.toml   # opcional
wrangler secret put OPENAI_API_KEY    --config wrangler.improve.toml   # opcional
wrangler deploy --config wrangler.improve.toml

# Worker 2 — /chat (default Claude Sonnet, mejor en código)
wrangler secret put ANTHROPIC_API_KEY --config wrangler.chat.toml      # default
wrangler secret put OPENAI_API_KEY    --config wrangler.chat.toml      # opcional
wrangler secret put GOOGLE_API_KEY    --config wrangler.chat.toml      # opcional
wrangler deploy --config wrangler.chat.toml
```

Salida: dos URLs `https://academia-jarvis-{improve,chat}.TUSUBDOMINIO.workers.dev/...`. Copia ambas.

**Cambiar default por Worker (sin código):** edita `wrangler.improve.toml` o `wrangler.chat.toml` y cambia las variables `DEFAULT_PROVIDER` y `DEFAULT_MODEL`. Re-deploy.

**Endpoint extra disponible:** `GET /providers` en el worker de chat devuelve qué proveedores tienes configurados. Útil para verificar setup.

### Paso 5 · Editar las URLs en index.html

Abre `docs/index.html`, busca el bloque CONFIG (línea ~1080 aprox) y reemplaza:

```javascript
const CONFIG = {
  CONTENT_URL: 'https://raw.githubusercontent.com/acevedox3/academia-jarvis/main/docs/content.json',
  IMPROVE_URL: 'https://academia-jarvis-improve.TUSUBDOMINIO.workers.dev/improve',
  CHAT_URL:    'https://academia-jarvis-chat.TUSUBDOMINIO.workers.dev/chat',
  // ...resto sin cambios
};
```

Commit y push. GitHub Pages se actualiza solo.

### Paso 6 · Compilar la app iOS con Capacitor

Requisitos: Mac con Xcode + CocoaPods (`sudo gem install cocoapods`).

```bash
cd academia-app-v3
npm install
npx cap add ios
npm run sync
npx cap open ios
```

En Xcode:
1. Target App → Signing & Capabilities → Team: tu Apple Developer account.
2. Bundle ID: `com.angel.academiajarvis` (debe coincidir con `capacitor.config.json`).
3. Conecta iPad por cable, selecciónalo como destino.
4. Pulsa Run (▶).

Primera vez: en iPad → Ajustes → General → VPN y administración de dispositivos → confiar perfil.

---

## Cómo funciona la coordinación por sesión

### Al abrir una sesión

1. Usuario hace tap en una fila de sesión en el syllabus.
2. `openSessionModal(id)` carga `content.json[sessions][id-1].deep`.
3. Renderiza 6 tabs: Resumen / Profundo / Código / Errores / Quiz / Refs.
4. `currentSessionId = id` (global) → el chat ya sabe en qué sesión está parado.

### Al chatear con el tutor

1. Usuario abre chat (FAB azul, esquina inferior derecha).
2. Pregunta cualquier cosa.
3. El cliente envía a `/chat` el `userContext` con:
   - `currentSession`: en qué sesión estás parado
   - `completedSessions`: qué ya sabes
   - `glossaryTerms`: términos que has aprendido
   - `sessions`: catálogo completo
4. Claude Sonnet responde alineado a tu sesión activa y nivel.

### Al completar una sesión

1. Usuario toca "Marcar como completada" en el modal.
2. `toggleFromModal(id)` ejecuta `toggle(id)` (guarda en localStorage).
3. Llama `callImprove(id)` → POST a `/improve` con tu estado.
4. Claude Haiku responde con: `recap` + `glossary` (nuevos términos) + `nextAction`.
5. Se guarda en `state.sessionImprovements[id]`.
6. La próxima vez que abras esa sesión, ves tu recap personalizado en el tab Resumen.

### Memoria acumulada

Cada `improve` añade términos nuevos al `state.glossary` (sin duplicar). Cuando el tutor responde, ve tu glosario completo — no te re-explica lo que ya sabes.

---

## Actualización del contenido

### Manual

Edita `docs/content.json`. Commit. Push. App se actualiza en próxima apertura.

### Automática (semanal)

GitHub Action lunes 7am UTC ejecuta `scripts/update_content.py`:
1. Escanea 7 fuentes oficiales de Anthropic.
2. Claude Haiku compara vs `content.json` actual.
3. Clasifica cambios: `minor` → auto-merge directo a `main`. `major` → abre PR para tu revisión.
4. Email te llega cuando hay PR.

Costo: ~$5-10/año en API calls (Haiku).

---

## Costos operativos

| Servicio | Tier gratis | Pagas si |
|---|---|---|
| GitHub Pages | Ilimitado | — |
| GitHub Actions | 2000 min/mes | corres >2000 min/mes |
| Cloudflare Workers | 100K req/día | superas 100K |
| Anthropic API — `/improve` por sesión | — | ~$0.01-0.02 × sesiones completadas |
| Anthropic API — `/chat` tutor en vivo | — | ~$0.03-0.08 × pregunta (Sonnet) |
| Anthropic API — updater semanal | — | ~$5-10/año |
| Apple Developer | — | $99/año (ya tienes) |

**Total año 1 (uso ligero):** $25-50. **Uso intenso del chat:** $80-150.

---

## Estructura del `content.json`

Schema completo de una sesión con `deep`:

```json
{
  "n": 1, "mod": 1, "id": 1, "module": 1,
  "title": "Qué es un agente de IA",
  "sub": "LLM vs workflow vs agente verdadero",
  "duration": "45 min", "hours": 1.0,
  "objs": ["...", "..."],
  "reading": "Building Effective Agents...",
  "exercise": "Diseña conceptualmente...",
  "deep": {
    "intro": "Markdown largo (600-800 palabras)",
    "sections": [
      {
        "title": "Los 3 componentes irreducibles",
        "body": "Markdown con explicación",
        "code": [{"lang": "python", "label": "...", "src": "código"}]
      }
    ],
    "gotchas": [{"title": "...", "desc": "...", "fix": "..."}],
    "quiz": [{"q": "...", "options": ["a","b","c","d"], "correct": 1, "explain": "..."}],
    "references": [{"title": "...", "url": "...", "kind": "anthropic-research", "relevance": "primary"}]
  }
}
```

Si quieres editar manualmente: añade/modifica el objeto `deep` de la sesión que te interese. El resto del sistema lo detecta sin cambios.

---

## Cómo obtener las 3 API keys

**Google AI Studio (Gemini)** — recomendado para empezar, generoso tier gratuito.
1. Ve a [aistudio.google.com](https://aistudio.google.com).
2. Login con tu Google account.
3. Click "Get API key" → "Create API key in new project".
4. Copia la key (empieza con `AIza...`).

**OpenAI**
1. Ve a [platform.openai.com](https://platform.openai.com).
2. Login → Settings → API keys → "Create new secret key".
3. Copia la key (empieza con `sk-...`). Requiere cargar mínimo $5 de crédito.

**Anthropic**
1. Ve a [console.anthropic.com](https://console.anthropic.com).
2. Login → API Keys → "Create Key".
3. Copia la key (empieza con `sk-ant-...`). Requiere cargar mínimo $5 de crédito.

**Tip:** todas tienen tier gratuito o créditos iniciales. Para empezar, basta con Google (gratis) y una de las otras dos.

## Cómo usar el selector de modelo en la app

1. Abre el chat (FAB azul abajo-derecha).
2. Drop-down en la cabecera: cambia entre Claude/GPT/Gemini.
3. Cada respuesta muestra abajo `provider/model · $costo`.
4. Tu elección se guarda automáticamente en localStorage.

Casos de uso típicos:
- **Aprender comparando:** misma pregunta a Claude, GPT y Gemini → compara respuestas.
- **Ahorro:** cambia a Gemini Flash para preguntas casuales (50× más barato).
- **Profundidad:** Opus o GPT-5 para preguntas críticas.

## Próximas capas (ver ROADMAP en el bundle anterior)

- **Capa 5:** auto-generación de sesiones nuevas cuando el crawler detecta tema emergente.
- **Capa 6:** modo examen + certificado PDF.
- **Capa 7:** notas tipo Notion sincronizadas a repo privado.

Costo incremental: $20-50/año por capa.

---

*Hecho para Angel Trujillo · 2026 · v3.0*
