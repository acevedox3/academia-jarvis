# Academia Jarvis v6 — Agente Profesor sobre TTS

Esta versión añade un agente profesor (Claude Haiku 4.5) que enriquece la lectura automática con explicaciones pedagógicas.

## Qué se agregó

1. **Nuevo worker `/profesor`** en `worker/profesor.js` (+ `wrangler.profesor.toml`). Dos modos:
   - `mode: "enrich"` — reescribe cada sección añadiendo señales, analogías, preguntas retóricas.
   - `mode: "comments"` — genera 2–5 comentarios cortos por sección para intercalar al final con voz distinta.
2. **UI en el player TTS**: dos selectores nuevos.
   - **Profesor: `Apagado / Enriquecido / En vivo / Ambos`**
   - **Voz Profesor**: 8 opciones (LatAm + España, M y F)
3. **Cache local** de enriquecimientos y comentarios en `localStorage` (clave `academia-jarvis-profesor-cache-v1`). Cada sección × cada modo se genera una sola vez.
4. **Badge de costo** aproximado por sesión (centavos USD).

## Voces por defecto

- **Narrador**: `es-US-Neural2-A` (femenina LatAm, voz neutra clara)
- **Profesor**: `es-US-Neural2-B` (masculina LatAm, autoridad cercana)

El contraste M/F entre las dos voces hace que el oído distinga al instante quién habla.

## Despliegue (3 pasos)

### 1. Desplegar el worker del profesor

```bash
cd worker/
wrangler secret put ANTHROPIC_API_KEY --config wrangler.profesor.toml
wrangler deploy --config wrangler.profesor.toml
```

Esto crea: `https://academia-jarvis-profesor.<TU_SUBDOMINIO>.workers.dev/profesor`

### 2. Actualizar `CONFIG.PROFESOR_URL` en `docs/index.html`

Línea ~1400. Si tu subdominio de workers es `angeljarvis`, ya queda con la URL correcta:

```js
PROFESOR_URL: 'https://academia-jarvis-profesor.angeljarvis.workers.dev/profesor',
```

### 3. Deploy del frontend

```bash
./Deploy-To-GitHub.sh
```

## Costos estimados (con Claude Haiku 4.5)

| Modo | Por sección | Por sesión completa |
|------|-------------|---------------------|
| Enriquecido | ~$0.005 | ~$0.06 (12 secc.) |
| En vivo | ~$0.002 | ~$0.024 |
| Ambos | ~$0.007 | ~$0.084 |

Cada cálculo es **una sola vez por usuario por sesión** porque se cachea en su `localStorage`. Re-escuchar es gratis. Si quieres compartir cache entre dispositivos, mover el cache a KV/R2 es una extensión natural.

## ⚠ Acción de seguridad pendiente

En `wrangler-tts.toml` (raíz del bundle anterior) dejaste tu Google API key en texto plano dentro de un comentario:

```
AIzaSyAnoEPMX-vuPTWMBUqBWRw9uK2ihov6rZl
```

**Rota esa key en Google Cloud Console y guárdala solo como secret de Wrangler.** El nuevo `wrangler.profesor.toml` ya no contiene secretos en plano.

## Cómo funciona en runtime

1. Usuario abre una sesión y pulsa "🎧 Escuchar".
2. Si el modo profesor está en `off`, todo igual que antes.
3. Si está en `enrich`, `live` o `both`:
   - El frontend itera sobre `intro` y `sections[]` del JSON.
   - Para cada sección, si falta en cache, llama a `/profesor` con el modo correspondiente.
   - Construye la cola de chunks: cada uno con su voz asignada (narrador o profesor).
   - Reproduce con el TTS existente; los chunks del profesor van a la voz de profesor; los del narrador a la del narrador.
4. Cambiar de modo en plena reproducción reconstruye la cola y reanuda.
5. Cambiar de voz solo refresca los chunks correspondientes a esa voz.

## Modelo "comments" — nota de diseño

La implementación inicial agrupa los comentarios al final de cada sección, no intercalados párrafo a párrafo dentro del texto del narrador. Esto se hizo así porque:

- Es predecible y suena como "cierre del profesor" por sección, que es un patrón pedagógico válido.
- Evita romper el flujo de la lectura del narrador en medio de una idea.
- Simplifica el cache (solo dos entradas por sección: enriched + comments).

Si más adelante quieres intercalación fina párrafo-a-párrafo, hay que reescribir `appendProfesorComments()` para que parta el `body` por párrafos, los inserte en la cola en orden, e inserte cada comentario después del párrafo indicado por `afterParagraph`. El backend ya devuelve la metadata necesaria.
