#!/usr/bin/env python3
"""Append sessions 5-12 (deep content) to docs/content.json."""

import json
from pathlib import Path

CONTENT_PATH = Path(__file__).resolve().parent.parent / "docs" / "content.json"

NEW_SESSIONS = [
    {
        "n": 5, "mod": 2, "id": 5, "module": 2,
        "title": "Memoria de Agentes",
        "sub": "Los 4 tipos de memoria de un agente",
        "duration": "60 min", "hours": 1.3,
        "objs": [
            "Distinguir los 4 tipos de memoria: working, episodic, semantic, procedural",
            "Diseñar schema multi-tenant con pgvector",
            "Implementar Agentic RAG",
            "Decidir qué guardar y qué descartar"
        ],
        "reading": "Agent Memory Architectures 2026 + RAG Architecture for AI Agents 2026",
        "exercise": "Diseña el flujo Agentic RAG de tu proyecto con pgvector. Define collections, embedding strategy y política de retención.",
        "deep": {
            "intro": "Un LLM puro no tiene memoria: cada llamada es independiente. Para que un agente tenga **identidad coherente** a lo largo del tiempo, necesita memoria explícita. Pero memoria no es una cosa: son **cuatro cosas distintas** que se diseñan separadas.\n\n**Los 4 tipos (analogía con cognición humana):**\n\n1. **Working memory** — el contexto de la conversación actual. Vive en la ventana del LLM. Se pierde al terminar.\n2. **Episodic memory** — recuerdos específicos de eventos pasados. \"La semana pasada el usuario me dijo que prefiere TypeScript.\"\n3. **Semantic memory** — conocimiento general acumulado. \"FleetPro tiene 3 servicios principales: API, worker, scheduler.\"\n4. **Procedural memory** — cómo hacer cosas (skills aprendidas). \"Cuando un servicio cae, primero reviso deploys recientes.\"\n\nLa pregunta práctica no es \"¿uso memoria?\" sino \"¿qué tipo de memoria necesito y cómo la almaceno?\". Cada tipo se implementa con stack distinto: working en la ventana de contexto, episodic en una DB transaccional con timestamps, semantic en una vector DB para retrieval semántico, procedural típicamente en código (skills o tools).\n\nEl error #1 es vectorizar todo en pgvector y rezar. Vamos a cubrir cómo decidir qué guardar dónde.",
            "sections": [
                {
                    "title": "RAG vs Agentic RAG",
                    "body": "**RAG clásico:** el sistema busca documentos relevantes ANTES de llamar al LLM y los inyecta como contexto. Una sola búsqueda, un solo retrieval. Sirve para chatbots simples sobre docs.\n\n**Agentic RAG:** el agente decide CUÁNDO buscar, QUÉ buscar, y puede iterar. Si encontró algo parcial, busca con queries refinadas. Si no encontró nada, explora colecciones distintas.\n\nVentajas de Agentic RAG: maneja queries complejas, descubre lo que no sabía que buscaba, evita retrievals innecesarios. Desventajas: más caro (múltiples llamadas), más complejo de debuggear.\n\nUsa Agentic RAG cuando: queries son complejas o multi-hop. Usa RAG clásico cuando: queries son simples y predecibles.",
                    "code": [
                        {
                            "lang": "python",
                            "label": "Agentic RAG con pgvector",
                            "src": "import psycopg\nfrom anthropic import Anthropic\n\nclient = Anthropic()\nconn = psycopg.connect(\"postgresql://...\")\n\nSEARCH_TOOL = {\n    \"name\": \"search_knowledge\",\n    \"description\": (\n        \"Busca en la base de conocimiento semántica. \"\n        \"Devuelve top 5 fragmentos relevantes. \"\n        \"Úsala iterativamente: si el primer resultado no resuelve, refina la query.\"\n    ),\n    \"input_schema\": {\n        \"type\": \"object\",\n        \"properties\": {\n            \"query\": {\"type\": \"string\", \"description\": \"Búsqueda en lenguaje natural\"},\n            \"collection\": {\"type\": \"string\", \"enum\": [\"docs\", \"incidents\", \"runbooks\"]}\n        },\n        \"required\": [\"query\"]\n    }\n}\n\ndef search_knowledge(query: str, collection: str = \"docs\", tenant_id: str = None):\n    embedding = embed(query)  # OpenAI ada-002 o voyage-3\n    rows = conn.execute(\n        \"SELECT content, source, 1 - (embedding <=> %s) AS score \"\n        \"FROM knowledge WHERE collection = %s AND tenant_id = %s \"\n        \"ORDER BY embedding <=> %s LIMIT 5\",\n        (embedding, collection, tenant_id, embedding)\n    ).fetchall()\n    return [{\"content\": r[0], \"source\": r[1], \"score\": r[2]} for r in rows]"
                        }
                    ]
                },
                {
                    "title": "Schema multi-tenant para pgvector",
                    "body": "Cuando guardas memoria semántica de varios clientes, debes aislar estrictamente. Una embedding del cliente A NO debe aparecer en búsquedas del cliente B. La forma canónica: **tenant_id en cada fila + Row-Level Security (RLS)**.\n\nNo confíes solo en filtros de aplicación. Si tu código tiene un bug y olvida el WHERE tenant_id, vas a leakear datos. RLS en la DB es defense in depth: aunque la app falle, la DB rechaza la query.",
                    "code": [
                        {
                            "lang": "sql",
                            "label": "Schema pgvector multi-tenant con RLS",
                            "src": "-- Habilitar pgvector\nCREATE EXTENSION IF NOT EXISTS vector;\n\nCREATE TABLE knowledge (\n  id           BIGSERIAL PRIMARY KEY,\n  tenant_id    UUID NOT NULL,\n  collection   TEXT NOT NULL,\n  content      TEXT NOT NULL,\n  source       TEXT,\n  embedding    VECTOR(1536) NOT NULL,\n  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),\n  decay_until  TIMESTAMPTZ  -- política de retención: NULL = forever\n);\n\nCREATE INDEX idx_knowledge_tenant ON knowledge(tenant_id);\nCREATE INDEX idx_knowledge_embedding ON knowledge\n  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);\n\n-- Row-Level Security: defense in depth\nALTER TABLE knowledge ENABLE ROW LEVEL SECURITY;\nCREATE POLICY tenant_isolation ON knowledge\n  USING (tenant_id = current_setting('app.tenant_id')::uuid);\n\n-- En cada request, setea el tenant_id ANTES de queries:\n-- SET LOCAL app.tenant_id = 'uuid-del-tenant';"
                        }
                    ]
                },
                {
                    "title": "Política de retención: qué descartar",
                    "body": "Guardar todo es tentador pero costoso. La memoria crece, el vector DB se ralentiza, los embeddings caducan (el modelo de embedding cambia).\n\nPolíticas concretas:\n\n- **Working memory:** vive en el contexto, se descarta automáticamente al final del turno.\n- **Episodic memory:** retén 30-90 días para eventos rutinarios; permanente para eventos críticos (incidentes, decisiones de usuario).\n- **Semantic memory:** sin TTL pero re-embedeable (si cambias modelo de embedding, re-procesas).\n- **Procedural memory:** en código, versionado con el resto del repo.\n\nUna heurística útil: `decay_until` por fila. Cronjob nocturno borra filas con `decay_until < NOW()`. Para episodic memory, `decay_until = created_at + interval '30 days'` por default; ciertos eventos críticos lo extienden o lo dejan NULL."
                }
            ],
            "gotchas": [
                { "title": "Vectorizar todo sin filtro", "desc": "Mete cualquier texto en pgvector, asume que retrieval va a funcionar. Resultados terribles.", "fix": "Cada item necesita: contenido limpio (no HTML/ruido), metadata (source, timestamp), y razón clara para estar ahí. Si no sabrás cuándo recuperarlo, no lo guardes." },
                { "title": "Sin tenant_id en queries", "desc": "Olvidas `WHERE tenant_id = X` y leakeas datos entre clientes. Bug que destruye empresas.", "fix": "RLS en la DB. Aunque la app olvide el filtro, postgres bloquea. Defense in depth no-negociable." },
                { "title": "Ignorar el chunk size", "desc": "Chunks demasiado grandes (5000 chars) o demasiado pequeños (50) destruyen relevancia.", "fix": "Sweet spot 300-800 chars con overlap de 50. Para docs estructurados, chunkea por sección. Mide recall@5 con golden set." },
                { "title": "Olvidar el decaimiento", "desc": "Tu DB crece sin parar. Búsquedas se vuelven lentas. Embeddings viejos pueden estar caducados.", "fix": "Política `decay_until` por tipo de memoria. Cronjob nocturno limpia. Re-embed cuando cambies modelo." }
            ],
            "quiz": [
                {
                    "q": "¿Cuál de estos NO es un tipo canónico de memoria de agente?",
                    "options": ["Working memory", "Episodic memory", "Visual memory", "Procedural memory"],
                    "correct": 2,
                    "explain": "Los 4 tipos canónicos son working, episodic, semantic y procedural. 'Visual memory' no es estándar en la literatura de agentes."
                },
                {
                    "q": "¿Cuál es la diferencia clave entre RAG clásico y Agentic RAG?",
                    "options": ["Agentic RAG usa Claude, RAG usa GPT", "En Agentic RAG el agente decide cuándo y qué buscar iterativamente", "Agentic RAG es más barato", "No hay diferencia"],
                    "correct": 1,
                    "explain": "RAG clásico hace UN retrieval antes de llamar al LLM. Agentic RAG deja que el agente busque iterativamente, refinando queries según resultados."
                },
                {
                    "q": "¿Por qué necesitas RLS además de filtrar por tenant_id en la app?",
                    "options": ["RLS es más rápido", "Defense in depth: si la app olvida el filtro, la DB lo bloquea", "Es requisito legal", "RLS reemplaza tenant_id"],
                    "correct": 1,
                    "explain": "Defense in depth. Un bug en la app puede olvidar el WHERE; RLS en la DB es la segunda capa. Multi-tenant data leak destruye empresas."
                },
                {
                    "q": "Tu base de conocimiento crece a 10M filas y las búsquedas son lentas. ¿Primer paso?",
                    "options": ["Migrar a otra base de datos", "Aplicar política de retención (decay_until) y limpiar datos viejos", "Comprar hardware más caro", "Reducir embeddings a menos dimensiones"],
                    "correct": 1,
                    "explain": "Antes de migrar o comprar hardware, define qué guardas y qué descartas. Política de retención por tipo de memoria. La mayoría de las veces, 70% de los datos no se vuelven a buscar."
                },
                {
                    "q": "¿Qué tipo de memoria vive en el contexto del LLM y se descarta al terminar?",
                    "options": ["Episodic", "Semantic", "Working", "Procedural"],
                    "correct": 2,
                    "explain": "Working memory es la ventana de contexto del LLM en el turno actual. Es transitoria — para persistir, hay que mover a episodic o semantic."
                }
            ],
            "references": [
                { "title": "Agent Memory Architectures: Vector vs Graph vs Episodic", "url": "https://www.digitalapplied.com/blog/agent-memory-architectures-vector-graph-episodic", "kind": "blog", "relevance": "primary" },
                { "title": "RAG Architecture for AI Agents 2026", "url": "https://rapidclaw.dev/blog/rag-architecture-ai-agents-guide-2026", "kind": "blog", "relevance": "primary" },
                { "title": "pgvector (repo oficial)", "url": "https://github.com/pgvector/pgvector", "kind": "repo", "relevance": "primary" },
                { "title": "Vector Database Benchmarks 2026", "url": "https://callsphere.ai/blog/vector-database-benchmarks-2026-pgvector-qdrant-weaviate-milvus-lancedb", "kind": "blog", "relevance": "supporting" }
            ]
        }
    },
    {
        "n": 6, "mod": 2, "id": 6, "module": 2,
        "title": "Router de Modelos",
        "sub": "Haiku, Sonnet, Opus — y la regla 70/20/10",
        "duration": "45 min", "hours": 1.0,
        "objs": [
            "Asignar el modelo correcto a cada tarea según costo y capacidad",
            "Calcular el ahorro real de prompt caching (hasta 90%)",
            "Modelar unit economics de un sistema agéntico",
            "Aplicar el principio 'small first, escalate when needed'"
        ],
        "reading": "Claude API Pricing oficial + Anthropic Engineering sobre selección de modelo",
        "exercise": "Calcula unit economics completos de tu proyecto a 100, 1K y 10K usuarios. Decide modelo por tarea.",
        "deep": {
            "intro": "Los tres modelos de Claude tienen un orden de magnitud de diferencia en precio. Opus puede costar 50-100× más que Haiku. **Esa diferencia define si tu negocio funciona o no.**\n\n**Regla 70/20/10** (heurística operativa de equipos que ya han escalado):\n\n- **70% del tráfico → Haiku.** Tareas simples: clasificación, extracción, formato, validación, resumen corto. Haiku es sorprendentemente bueno cuando el prompt está bien diseñado.\n- **20% del tráfico → Sonnet.** Razonamiento medio, código de complejidad moderada, conversación con cierta complejidad.\n- **10% del tráfico → Opus.** Decisiones críticas, planificación profunda, código complejo, edge cases que importan.\n\nEsto es una distribución, no una regla rígida. Pero si tu sistema usa Sonnet/Opus para 100% de las llamadas, casi seguro estás quemando dinero.\n\n**Y el segundo descubrimiento:** prompt caching reduce el costo del input hasta 90%. Si tus prompts tienen partes comunes (system prompt grande, ejemplos repetidos), caching cambia las matemáticas radicalmente.",
            "sections": [
                {
                    "title": "Cuándo usar cada modelo",
                    "body": "**Haiku** es para:\n- Clasificación, routing, intent detection.\n- Extracción de campos de un texto.\n- Validación rápida de input.\n- Resúmenes muy cortos.\n- Cualquier tarea con prompt + few-shot que ya funcionaba en GPT-3.5.\n\n**Sonnet** es para:\n- Conversación con contexto.\n- Código de complejidad media (200-500 líneas).\n- Análisis de un documento.\n- La mayoría de chatbots de soporte.\n- Tareas que necesitan razonamiento de 2-3 pasos.\n\n**Opus** es para:\n- Decisiones con consecuencias serias (médico, legal, financiero).\n- Planificación compleja con muchos constraints.\n- Código de arquitectura.\n- Razonamiento sobre situaciones ambiguas.\n- Casos donde la diferencia entre 95% y 98% de accuracy justifica el costo 5×.",
                    "code": [
                        {
                            "lang": "python",
                            "label": "Router de modelos simple",
                            "src": "MODEL_FOR_TASK = {\n    \"classify\":     \"claude-haiku-4-5\",\n    \"extract\":      \"claude-haiku-4-5\",\n    \"summarize\":    \"claude-haiku-4-5\",\n    \"converse\":     \"claude-sonnet-4-6\",\n    \"code_review\":  \"claude-sonnet-4-6\",\n    \"plan\":         \"claude-opus-4-7\",\n    \"critical\":     \"claude-opus-4-7\",\n}\n\ndef route_to_model(task: str) -> str:\n    return MODEL_FOR_TASK.get(task, \"claude-haiku-4-5\")  # default barato\n\n# Patrón escalonado: empieza barato, sube si confianza es baja\ndef escalate_if_needed(query: str) -> str:\n    haiku_resp = call_model(query, \"claude-haiku-4-5\")\n    if haiku_resp[\"confidence\"] > 0.85:\n        return haiku_resp[\"answer\"]\n    # No confiable — sube a Sonnet\n    sonnet_resp = call_model(query, \"claude-sonnet-4-6\")\n    return sonnet_resp[\"answer\"]"
                        }
                    ]
                },
                {
                    "title": "Prompt caching: el descuento del 90%",
                    "body": "Si tu sistema usa el mismo system prompt (con ejemplos, reglas, etc.) en todas las llamadas, Anthropic puede **cachearlo** y cobrarte 90% menos por los tokens cacheados en llamadas subsecuentes.\n\n**Cómo activarlo:**\n```python\nresponse = client.messages.create(\n    model=\"claude-sonnet-4-6\",\n    system=[\n        {\"type\": \"text\", \"text\": LARGE_SYSTEM_PROMPT, \"cache_control\": {\"type\": \"ephemeral\"}}\n    ],\n    messages=[{\"role\": \"user\", \"content\": user_query}]\n)\n```\n\nReglas:\n- El cache vive ~5 minutos (ephemeral) o 1 hora (extended, beta).\n- Necesita mínimo ~1024 tokens cacheables para activar.\n- Primer hit: cobras 25% más por escribir al cache. Hits subsecuentes: 90% menos.\n\n**Break-even:** si reusas el mismo system prompt >4 veces en 5 minutos, ya ahorras. En agentes en producción esto es trivialmente cierto."
                },
                {
                    "title": "Unit economics: la matemática que tienes que saber",
                    "body": "Calcula el costo por usuario antes de scale-up. Ejemplo realista de un chatbot SaaS:\n\n**Por interacción del usuario:**\n- 1 routing call (Haiku, 100 tokens in / 20 out): ~$0.0001\n- 1 respuesta principal (Sonnet, 2000 in / 500 out): ~$0.015\n- 1 recap personalizado (Haiku, 1000 in / 200 out): ~$0.002\n- **Total:** ~$0.017 por interacción.\n\n**Por usuario activo mensual** (asumiendo 30 interacciones/mes):\n- Sin caching: 30 × $0.017 = **$0.51/MAU**\n- Con caching del system prompt: 30 × $0.011 ≈ **$0.33/MAU**\n\nA 10,000 MAU = $3,300/mes en API costs. Si cobras $10/usuario/mes, queda $66,700/mes de margen bruto. Si cobras $5, queda $36,700. Si cobras $1, **pierdes dinero**.\n\nEste cálculo decide tu modelo de negocio."
                }
            ],
            "gotchas": [
                { "title": "Default a Opus por miedo a errores", "desc": "Usas Opus para todo 'por si acaso'. Quemas dinero 50× más rápido que con Haiku.", "fix": "Empieza con Haiku. Mide accuracy en un golden set. Solo sube a Sonnet/Opus si Haiku falla y la diferencia justifica el costo." },
                { "title": "Sin tracking de costo por request", "desc": "No sabes qué llamadas son caras. Imposible optimizar.", "fix": "Loguea cada llamada con: model, input_tokens, output_tokens, latency, task_id. Dashboard semanal de costo por tarea." },
                { "title": "No usar prompt caching", "desc": "Dejas 90% de ahorro en la mesa.", "fix": "Si tu system prompt es >1024 tokens y reusas en múltiples llamadas, agrega `cache_control: ephemeral`. Es una línea." },
                { "title": "Asumir que más caro = más rápido", "desc": "Opus es más capaz pero también más lento. Para tareas latency-sensitive, Haiku puede ser mejor.", "fix": "Mide latencia P50/P95 por modelo en tu workload. Haiku suele ser 2-3× más rápido que Opus." }
            ],
            "quiz": [
                {
                    "q": "Según la regla 70/20/10, ¿qué porcentaje de tráfico debería ir a Haiku?",
                    "options": ["10%", "20%", "70%", "100%"],
                    "correct": 2,
                    "explain": "70% Haiku, 20% Sonnet, 10% Opus. La mayoría de tareas (clasificar, extraer, resumir) son perfectas para Haiku."
                },
                {
                    "q": "¿Cuánto ahorras con prompt caching en llamadas con cache hit?",
                    "options": ["10%", "50%", "90% en tokens cacheados", "100%"],
                    "correct": 2,
                    "explain": "Hasta 90% menos en los tokens cacheados (en cache hits). La primera escritura cobra 25% más, pero a partir del segundo hit ahorras 90%."
                },
                {
                    "q": "Para clasificar emails (SPAM/NOT_SPAM), ¿qué modelo usas?",
                    "options": ["Opus", "Sonnet", "Haiku", "Depende del idioma"],
                    "correct": 2,
                    "explain": "Clasificación es el caso de uso ideal para Haiku. Es rápido, barato y con buen prompt achieve >95% accuracy."
                },
                {
                    "q": "¿Cuándo NO usar prompt caching?",
                    "options": ["Cuando el system prompt es <1024 tokens", "Cuando reusas el mismo prompt frecuentemente", "Cuando trabajas con Claude", "Nunca, siempre úsalo"],
                    "correct": 0,
                    "explain": "Caching tiene un mínimo de ~1024 tokens cacheables. Si tu system prompt es más corto, no se activa."
                },
                {
                    "q": "Tu chatbot cuesta $0.51/MAU sin caching. ¿Cómo bajarías el costo primero?",
                    "options": ["Migrar a otro proveedor", "Activar prompt caching", "Reducir features", "Subir precios"],
                    "correct": 1,
                    "explain": "Prompt caching es la primera optimización. Es trivial de activar y reduce 30-40% del costo en sistemas con system prompts repetidos."
                }
            ],
            "references": [
                { "title": "Claude API Pricing (oficial)", "url": "https://platform.claude.com/docs/en/about-claude/pricing", "kind": "anthropic-docs", "relevance": "primary" },
                { "title": "Prompt caching docs", "url": "https://platform.claude.com/docs/en/build-with-claude/prompt-caching", "kind": "anthropic-docs", "relevance": "primary" },
                { "title": "Claude API Pricing 2026 Guide (Finout)", "url": "https://www.finout.io/blog/anthropic-api-pricing", "kind": "blog", "relevance": "supporting" }
            ]
        }
    },
    {
        "n": 7, "mod": 2, "id": 7, "module": 2,
        "title": "Orchestrator-Workers",
        "sub": "Cuándo realmente necesitas multi-agente",
        "duration": "50 min", "hours": 1.1,
        "objs": [
            "Diseñar el rol del Orchestrator y los Workers",
            "Decidir multi-agente vs single-agent con criterios objetivos",
            "Detectar anti-patrones: over-orchestration, workers tontos",
            "Implementar handoffs entre agentes"
        ],
        "reading": "Building Effective Agents — patrón Orchestrator-Workers (PDF de patrones)",
        "exercise": "Diseña el Orchestrator de tu sistema con 3+ workers, especificando handoffs y criterios de delegación.",
        "deep": {
            "intro": "Multi-agente es el patrón más sobreusado en sistemas que no lo necesitan. Equipos saltan a 'orchestrator con 5 workers' porque suena sofisticado, sin haber agotado un agente lineal bien diseñado primero.\n\n**Cuándo necesitas multi-agente, de verdad:**\n\n1. **La tarea es muy grande y satura el contexto.** Si un solo agente con contexto de 200K tokens se confunde porque acumula demasiada historia, divide.\n2. **Subtareas requieren especialización fuerte.** Si una requiere razonamiento y otra requiere precisión numérica, distintos system prompts ayudan.\n3. **Paralelizable.** Si las subtareas son independientes, paralelizarlas baja la latencia 3-5×.\n4. **Necesitas role-play estructurado.** Debates, simulaciones, A/B de perspectivas distintas.\n\n**Cuándo NO lo necesitas:** la mayoría de las veces. Un buen system prompt + tools + ciclo ReAct resuelve el 80% de problemas que la gente intenta resolver con multi-agente.",
            "sections": [
                {
                    "title": "Anatomía del Orchestrator",
                    "body": "El Orchestrator es un agente con un objetivo distinto: **descomponer la tarea y delegar**, no resolver directamente. Su system prompt enfatiza:\n\n- Cuáles workers tiene disponibles y qué hace cada uno.\n- Criterios para delegar a uno u otro.\n- Cómo agregar resultados de varios workers.\n- Cuándo terminar.\n\nLos Workers son agentes (o llamadas LLM) especializados con system prompts enfocados. Su salida es predictible (idealmente JSON estructurado) para que el Orchestrator pueda agregar.\n\n**Modelo:** Orchestrator suele ser Sonnet u Opus (necesita razonar sobre la tarea completa). Workers suelen ser Haiku (cada uno tiene scope estrecho).",
                    "code": [
                        {
                            "lang": "python",
                            "label": "Patrón Orchestrator-Workers básico",
                            "src": "from anthropic import Anthropic\nimport json\n\nclient = Anthropic()\n\nORCHESTRATOR_PROMPT = \"\"\"<role>\nEres el Orchestrator de un sistema de diagnóstico de incidentes.\nDescompones la tarea y delegas a workers especializados.\n</role>\n\n<workers>\n- log_analyzer: analiza logs y extrae errores relevantes\n- deploy_checker: revisa deploys recientes y cambios en config\n- metric_checker: revisa metrics de CPU, memoria, latencia\n</workers>\n\n<rules>\n- Delega a UN worker a la vez. Espera el resultado antes de delegar al siguiente.\n- Si dos workers son independientes, puedes paralelizarlos.\n- Después de 3-5 workers, sintetiza diagnóstico final.\n</rules>\"\"\"\n\ndef run_worker(worker_name: str, task: str) -> dict:\n    worker_prompts = {\n        \"log_analyzer\":    \"Analiza logs. Devuelve JSON: {errors: [...], severity: ...}\",\n        \"deploy_checker\":  \"Revisa deploys recientes. Devuelve JSON: {deploys: [...]}\",\n        \"metric_checker\":  \"Revisa metrics. Devuelve JSON: {anomalies: [...]}\"\n    }\n    resp = client.messages.create(\n        model=\"claude-haiku-4-5\", max_tokens=600,\n        system=worker_prompts[worker_name],\n        messages=[{\"role\": \"user\", \"content\": task}]\n    )\n    return json.loads(resp.content[0].text)\n\ndef orchestrate(incident: str) -> str:\n    # Orchestrator decide qué workers usar\n    plan = client.messages.create(\n        model=\"claude-sonnet-4-6\", max_tokens=400,\n        system=ORCHESTRATOR_PROMPT,\n        messages=[{\"role\": \"user\", \"content\": f\"INCIDENTE: {incident}\\n\\nDecide qué workers invocar (JSON list).\"}]\n    )\n    plan = json.loads(plan.content[0].text)\n\n    # Ejecuta workers (paralelo si posible)\n    results = {w: run_worker(w, incident) for w in plan[\"workers\"]}\n\n    # Síntesis final\n    final = client.messages.create(\n        model=\"claude-sonnet-4-6\", max_tokens=800,\n        system=ORCHESTRATOR_PROMPT,\n        messages=[{\"role\": \"user\", \"content\":\n                   f\"INCIDENTE: {incident}\\n\\nRESULTADOS:\\n{json.dumps(results, indent=2)}\\n\\nDiagnostica.\"}]\n    )\n    return final.content[0].text"
                        }
                    ]
                },
                {
                    "title": "Handoffs entre agentes: el contrato",
                    "body": "Cuando un agente le pasa trabajo a otro, define **explícitamente**:\n\n1. **Qué se le pasa.** Schema del input (ideally JSON con campos tipados).\n2. **Qué devuelve.** Schema del output. Si es texto libre, especifica formato/idioma.\n3. **Qué errores puede emitir.** Códigos de error estructurados.\n4. **Quién decide si retry.** El orchestrator, no el worker.\n\nSin contrato claro, los handoffs se vuelven misteriosos: el worker devuelve algo que el orchestrator no esperaba, el flujo se rompe en formas difíciles de debuggear."
                },
                {
                    "title": "Anti-patrones de multi-agente",
                    "body": "Tres anti-patrones aparecen una y otra vez:\n\n**Over-orchestration:** delegas a 5 workers algo que un solo agente con buen prompt resolvía. Costo 5×, latencia 5×, debug 10×.\n\n**Workers tontos:** workers que solo pasan datos sin razonar. Si tu 'worker' es básicamente una función → es una tool, no un agente.\n\n**Comunicación implícita:** orchestrator y workers asumen estructura sin contratos. Cuando algo cambia, todo se rompe.\n\n**Sin observabilidad:** no tracas trace IDs entre agentes. Cuando hay un problema, no puedes seguir qué pasó. Trace ID compartido es no-negociable."
                }
            ],
            "gotchas": [
                { "title": "Saltar a multi-agente sin probar single-agent", "desc": "Empezar con orchestrator es overengineering. Pago triple por incertidumbre triple.", "fix": "Construye single-agent primero. Solo divide cuando observes confusión por saturación de contexto o falta de especialización." },
                { "title": "Workers sin observabilidad compartida", "desc": "Cada worker tiene sus propios logs. Cuando algo falla, no puedes correlacionar.", "fix": "Trace ID compartido en todos los workers. Mismo trace_id en logs/metrics/traces. OpenTelemetry para correlación." },
                { "title": "Orchestrator usando Haiku", "desc": "El orchestrator necesita razonar sobre toda la tarea. Haiku falla en sintetizar resultados de 3+ workers.", "fix": "Orchestrator = Sonnet o Opus. Workers = Haiku (scope pequeño). El presupuesto se justifica porque hay 1 orchestrator vs N workers." },
                { "title": "Pasar todo el contexto a cada worker", "desc": "Cada worker recibe 50KB de contexto que no necesita. Costos explotan.", "fix": "Cada worker recibe SOLO el contexto relevante a su scope. El orchestrator filtra antes de delegar." }
            ],
            "quiz": [
                {
                    "q": "¿Cuándo NO necesitas multi-agente?",
                    "options": ["Cuando la tarea es muy grande", "Cuando un single-agent bien diseñado puede resolver la tarea", "Cuando hay subtareas paralelas", "Cuando necesitas especialización fuerte"],
                    "correct": 1,
                    "explain": "Si un single-agent con buen prompt y tools resuelve, no agregues multi-agente. La complejidad no justifica el costo."
                },
                {
                    "q": "¿Qué modelo es típicamente correcto para el Orchestrator?",
                    "options": ["Haiku (es solo coordinación)", "Sonnet o Opus (necesita razonar sobre toda la tarea)", "GPT-4", "Es indiferente"],
                    "correct": 1,
                    "explain": "El Orchestrator razona sobre la tarea completa, descompone, y sintetiza. Necesita capacidad de razonamiento alta. Workers especializados pueden ser Haiku."
                },
                {
                    "q": "¿Qué define el contrato de un handoff entre agentes?",
                    "options": ["Solo el input", "Schema input + schema output + errores posibles", "Solo el modelo a usar", "Solo la timeout"],
                    "correct": 1,
                    "explain": "Sin schema explícito de input/output y catálogo de errores, los handoffs se rompen impredeciblemente. Define el contrato como API entre microservicios."
                },
                {
                    "q": "Tu sistema tiene 7 'workers' que solo extraen datos sin razonar. ¿Qué son?",
                    "options": ["Agentes válidos", "Probablemente deberían ser tools, no agentes", "Workers correctos", "Sistema bien diseñado"],
                    "correct": 1,
                    "explain": "Si un 'worker' no razona y solo ejecuta lógica deterministica, es una tool. Multi-agente con workers tontos = overhead sin beneficio."
                },
                {
                    "q": "¿Cómo correlacionas qué pasó entre 5 agentes que colaboran?",
                    "options": ["Logs separados por agente", "Trace ID compartido (OpenTelemetry)", "Timestamps", "No se puede"],
                    "correct": 1,
                    "explain": "Trace ID compartido propagado entre todas las llamadas. OpenTelemetry GenAI Conventions es el estándar. Sin esto, debug es imposible."
                }
            ],
            "references": [
                { "title": "Building Effective Agents — Orchestrator-Workers", "url": "https://www.anthropic.com/research/building-effective-agents", "kind": "anthropic-research", "relevance": "primary" },
                { "title": "Architecture Patterns (PDF)", "url": "https://resources.anthropic.com/hubfs/Building%20Effective%20AI%20Agents-%20Architecture%20Patterns%20and%20Implementation%20Frameworks.pdf", "kind": "anthropic-pdf", "relevance": "primary" },
                { "title": "Multi-agent vs Single-agent (Naitive)", "url": "https://blog.naitive.cloud/building-effective-agents/", "kind": "blog", "relevance": "supporting" }
            ]
        }
    },
    {
        "n": 8, "mod": 3, "id": 8, "module": 3,
        "title": "Los 5 Guards de PulseCore",
        "sub": "La implementación completa del corazón del sistema",
        "duration": "55 min", "hours": 1.2,
        "objs": [
            "Mapear cada Guard a su patrón agéntico y modelo óptimo",
            "Diseñar guardrails finales para acciones críticas",
            "Diseñar el ciclo Learner offline",
            "Conectar los Guards entre sí (event bus, memoria compartida)"
        ],
        "reading": "Architecture Patterns and Implementation Frameworks (PDF Anthropic)",
        "exercise": "Diseña el contrato entre 2 Guards de tu sistema: eventos, payload, error handling, idempotencia.",
        "deep": {
            "intro": "PulseCore es el sistema agéntico que vas a construir. Tiene cinco agentes especializados (\"Guards\") que colaboran para monitorear, diagnosticar y remediar incidentes en infraestructura del cliente.\n\nLos cinco Guards:\n\n1. **HealthGuard** — monitorea continuamente la salud de servicios. Detecta cuándo algo está mal.\n2. **Diagnostician** — cuando HealthGuard detecta problema, investiga la causa raíz.\n3. **Remediator** — propone (y opcionalmente ejecuta) acciones correctivas.\n4. **Auditor** — registra cada decisión y acción con trazabilidad completa.\n5. **Learner** — offline, analiza incidentes pasados y mejora system prompts y runbooks.\n\nCada Guard tiene su patrón. HealthGuard es polling simple (workflow). Diagnostician es Orchestrator-Workers (multi-investigación paralela). Remediator es Evaluator-Optimizer (genera plan, evalúa, refina). Auditor es append-only (sin LLM, solo persistencia). Learner es batch offline con Opus.\n\nEsta arquitectura es ejemplar porque **mezcla patrones según necesidad** — no fuerza todo a multi-agente.",
            "sections": [
                {
                    "title": "Cada Guard, su patrón y su modelo",
                    "body": "| Guard | Patrón | Modelo | Por qué |\n|---|---|---|---|\n| HealthGuard | Polling + Single Agent | Haiku | Tarea repetitiva, debe ser barata, escalable a miles de servicios |\n| Diagnostician | Orchestrator-Workers | Sonnet (orch), Haiku (workers) | Investigación paralela: logs + deploys + metrics simultáneo |\n| Remediator | Evaluator-Optimizer | Sonnet | Acciones críticas: necesita revisión antes de ejecutar |\n| Auditor | Append-only (no LLM) | — | Persistencia inmutable, debe ser determinista |\n| Learner | Batch offline | Opus | 1 corrida/día, profundidad de razonamiento sobre histórico |\n\nNota crucial: solo el Learner usa Opus, y solo offline. La pipeline en vivo (HealthGuard → Diagnostician → Remediator) es Haiku + Sonnet. Esto mantiene costos bajos."
                },
                {
                    "title": "Guardrails finales para Remediator",
                    "body": "Remediator puede ejecutar acciones que afectan producción del cliente. **Nunca debe ejecutar sin guardrails finales.** Tres capas:\n\n1. **Whitelist de acciones.** Remediator solo puede invocar tools de un set aprobado. Cada tool tiene scope explícito (qué afecta, qué no).\n\n2. **Human-in-the-loop para acciones críticas.** Reiniciar un servicio: ok automático. Borrar datos: requiere aprobación humana. La línea la decide el dueño del cliente.\n\n3. **Dry-run primero.** Antes de ejecutar, Remediator describe qué va a hacer. Si la simulación falla validaciones (impacto > threshold), pausa para humano.",
                    "code": [
                        {
                            "lang": "python",
                            "label": "Guardrails finales en Remediator",
                            "src": "ACTIONS_REQUIRING_APPROVAL = {\n    \"delete_data\", \"modify_billing\", \"change_dns\",\n    \"rollback_production\", \"scale_to_zero\"\n}\nSAFE_ACTIONS = {\n    \"restart_service\", \"clear_cache\", \"increase_replicas\"\n}\n\ndef execute_remediation(plan: dict, tenant_id: str) -> dict:\n    action = plan[\"action\"]\n    impact = plan[\"estimated_impact\"]\n\n    # 1. Whitelist check\n    if action not in (SAFE_ACTIONS | ACTIONS_REQUIRING_APPROVAL):\n        return {\"success\": False, \"reason\": \"action not allowed\"}\n\n    # 2. Dry-run\n    simulation = simulate_action(action, plan[\"params\"], tenant_id)\n    if simulation[\"users_affected\"] > 100:\n        return {\"success\": False, \"reason\": \"impact too high\",\n                \"requires\": \"human_approval\"}\n\n    # 3. Human gate para acciones críticas\n    if action in ACTIONS_REQUIRING_APPROVAL:\n        approval = request_human_approval(plan)\n        if not approval[\"approved\"]:\n            return {\"success\": False, \"reason\": \"human rejected\"}\n\n    # 4. Ejecuta de verdad\n    result = execute(action, plan[\"params\"])\n    return {\"success\": True, \"result\": result, \"audit_id\": log_action(plan)}"
                        }
                    ]
                },
                {
                    "title": "El ciclo Learner offline",
                    "body": "Learner corre cada noche. Lee todos los incidentes del día (vía Auditor). Identifica patrones:\n\n- ¿Hubo incidentes recurrentes con la misma causa?\n- ¿Qué prompts del Diagnostician llevaron a diagnóstico incorrecto?\n- ¿Qué acciones del Remediator necesitaron rollback?\n\nGenera dos outputs:\n\n1. **Patch propuesto al system prompt** del Guard relevante (ej. \"Cuando hay timeout, considerar deploys recientes ANTES de alertar\").\n2. **Nueva entrada en el runbook** semántico (memoria semantica, para Agentic RAG).\n\nLos patches no se aplican automáticamente. Llegan a un humano (tú) para revisión. Una vez aprobados, se commitean al repo y se reflejan en producción en el siguiente deploy.\n\nEsto es learning con humano en el loop — el sistema mejora pero no muta solo."
                }
            ],
            "gotchas": [
                { "title": "Guards muy acoplados", "desc": "Si HealthGuard llama directamente a Diagnostician (in-process), no puedes escalar ni testear independientemente.", "fix": "Event bus entre Guards (Redis pubsub, Postgres NOTIFY, o Kafka). Cada Guard publica eventos; otros se suscriben. Coupling bajo, escalado independiente." },
                { "title": "Remediator sin guardrails finales", "desc": "Le das tools de write y rezas. Tarde o temprano, ejecuta algo destructivo.", "fix": "Whitelist + dry-run + human gate para acciones críticas. Sin atajos. Tu cliente confía en que no rompes producción." },
                { "title": "Learner sin revisión humana", "desc": "Auto-patcheas prompts en producción. Bug de Learner → prompts corruptos en todos los clientes.", "fix": "Learner propone, tú revisas, deploy normal. Process change debe pasar code review como cualquier otro." },
                { "title": "Auditor con LLM", "desc": "Algunos equipos ponen LLM en el Auditor 'para resumir'. Pierde inmutabilidad y reproducibilidad.", "fix": "Auditor es código puro: append-only, JSON estructurado, índices por tenant_id y timestamp. Sin LLM. El resumen lo hace el Diagnostician si hace falta." }
            ],
            "quiz": [
                {
                    "q": "¿Qué modelo usa el HealthGuard?",
                    "options": ["Opus", "Sonnet", "Haiku (barato, repetitivo, escalable)", "GPT-4"],
                    "correct": 2,
                    "explain": "HealthGuard hace polling constante de cientos de servicios. Necesita ser barato. Haiku con buen prompt es perfecto."
                },
                {
                    "q": "¿Cuál es el único Guard que usa Opus?",
                    "options": ["HealthGuard", "Diagnostician", "Remediator", "Learner (offline, batch)"],
                    "correct": 3,
                    "explain": "Learner corre 1 vez al día, razona profundamente sobre histórico. Justifica Opus. El resto de la pipeline en vivo es Haiku/Sonnet para mantener costos."
                },
                {
                    "q": "¿Qué patrón usa el Diagnostician?",
                    "options": ["Single agent", "Evaluator-Optimizer", "Orchestrator-Workers (paralelo: logs + deploys + metrics)", "Prompt chaining"],
                    "correct": 2,
                    "explain": "Diagnostician investiga múltiples ángulos en paralelo (logs, deploys, metrics). Orchestrator-Workers es el patrón natural: 1 orchestrator + 3 workers especializados."
                },
                {
                    "q": "¿Por qué Remediator NO debe ejecutar acciones críticas automáticamente?",
                    "options": ["Es más lento", "Necesita guardrails: whitelist + dry-run + human gate para acciones destructivas", "Le falta capacidad", "Por costo"],
                    "correct": 1,
                    "explain": "Acciones que afectan producción del cliente requieren defense in depth. Sin guardrails, un bug del agente puede causar incidentes peores que el original."
                },
                {
                    "q": "El Learner detecta un patrón nuevo y propone cambio al system prompt. ¿Qué pasa?",
                    "options": ["Se aplica automáticamente", "Se descarta", "Llega a un humano para revisión antes de aplicarse", "Solo se logea"],
                    "correct": 2,
                    "explain": "Learning con humano en el loop. Auto-mutar prompts sin revisión es riesgo no-aceptable. Process change debe pasar code review."
                }
            ],
            "references": [
                { "title": "Architecture Patterns (PDF)", "url": "https://resources.anthropic.com/hubfs/Building%20Effective%20AI%20Agents-%20Architecture%20Patterns%20and%20Implementation%20Frameworks.pdf", "kind": "anthropic-pdf", "relevance": "primary" },
                { "title": "Building Effective Agents", "url": "https://www.anthropic.com/research/building-effective-agents", "kind": "anthropic-research", "relevance": "primary" }
            ]
        }
    },
    {
        "n": 9, "mod": 3, "id": 9, "module": 3,
        "title": "Multi-tenant y Seguridad",
        "sub": "Aislamiento RLS sin un solo bug que rompa todo",
        "duration": "50 min", "hours": 1.1,
        "objs": [
            "Aplicar defense-in-depth: RLS + filtros de app + tenant_id en contexto del agente",
            "Configurar PostgreSQL RLS para multi-tenancy",
            "Detectar vulnerabilidades de aislamiento",
            "Diseñar audit_log a prueba de manipulación"
        ],
        "reading": "AWS Multi-tenant Data Isolation con PostgreSQL RLS + sample repo",
        "exercise": "Diseña setup RLS completo para una tabla sensible. Define policies para SELECT, INSERT, UPDATE, DELETE.",
        "deep": {
            "intro": "Multi-tenant en SaaS B2B significa **un solo schema/DB compartido entre N clientes**. Es la arquitectura más común porque es la más simple de operar. Pero un solo bug de aislamiento — un `WHERE tenant_id = X` olvidado — y leakeas datos entre clientes. Tu empresa puede no sobrevivir ese incidente.\n\nLa solución es **defense in depth**: tres capas que se validan independientemente. Si una falla, las otras protegen.\n\n**Las 3 capas:**\n\n1. **Database (RLS).** Row-Level Security en Postgres. La DB se niega a devolver filas de otros tenants, aunque la query no tenga WHERE.\n2. **Application.** Filtros explícitos por tenant_id en cada query. Tests unitarios que verifican.\n3. **Agente.** El tenant_id viaja en el system prompt y en el contexto de tools. El agente nunca toca DB; pide acción vía tool; tool valida tenant_id antes de ejecutar.\n\nNinguna capa es suficiente sola. Las tres juntas hacen el aislamiento robusto.",
            "sections": [
                {
                    "title": "PostgreSQL RLS: setup canónico",
                    "body": "Row-Level Security en Postgres permite definir policies que filtran filas automáticamente. La policy usa una expresión SQL que debe ser TRUE para que la fila sea visible.\n\nEl truco: la policy usa una variable de sesión (`current_setting('app.tenant_id')`). Tu aplicación setea esa variable al inicio de cada request, antes de cualquier query. Si olvidas setear, la query no devuelve nada (porque NULL != tenant_id).",
                    "code": [
                        {
                            "lang": "sql",
                            "label": "RLS setup completo",
                            "src": "-- 1. Tabla con tenant_id\nCREATE TABLE incidents (\n  id          BIGSERIAL PRIMARY KEY,\n  tenant_id   UUID NOT NULL,\n  title       TEXT NOT NULL,\n  severity    TEXT NOT NULL,\n  status      TEXT NOT NULL DEFAULT 'open',\n  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()\n);\nCREATE INDEX idx_incidents_tenant ON incidents(tenant_id);\n\n-- 2. Habilita RLS\nALTER TABLE incidents ENABLE ROW LEVEL SECURITY;\n\n-- 3. Policies por operación\nCREATE POLICY tenant_select ON incidents\n  FOR SELECT\n  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);\n\nCREATE POLICY tenant_insert ON incidents\n  FOR INSERT\n  WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);\n\nCREATE POLICY tenant_update ON incidents\n  FOR UPDATE\n  USING (tenant_id = current_setting('app.tenant_id', true)::uuid)\n  WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);\n\nCREATE POLICY tenant_delete ON incidents\n  FOR DELETE\n  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);\n\n-- 4. En la app, al inicio de cada request:\n-- SET LOCAL app.tenant_id = 'uuid-del-tenant';"
                        },
                        {
                            "lang": "python",
                            "label": "Middleware FastAPI que setea tenant_id",
                            "src": "from fastapi import Request, HTTPException\nfrom contextvars import ContextVar\nimport asyncpg\n\n_tenant_ctx: ContextVar[str] = ContextVar(\"tenant_id\")\n\nasync def set_tenant_middleware(request: Request, call_next):\n    tenant_id = request.headers.get(\"x-tenant-id\")\n    if not tenant_id:\n        raise HTTPException(401, \"missing tenant\")\n    _tenant_ctx.set(tenant_id)\n    return await call_next(request)\n\nasync def get_db_conn():\n    \"\"\"Conexión que setea tenant_id automáticamente.\"\"\"\n    conn = await asyncpg.connect(DATABASE_URL)\n    await conn.execute(\n        \"SET LOCAL app.tenant_id = $1\",\n        _tenant_ctx.get()\n    )\n    return conn\n\n# Cualquier query a través de get_db_conn() está filtrada por RLS\n# Aunque olvides WHERE tenant_id, postgres bloquea"
                        }
                    ]
                },
                {
                    "title": "Tenant_id en el contexto del agente",
                    "body": "El LLM nunca debe decidir tenant_id por sí mismo. **Siempre** viene del contexto de la sesión (autenticación del usuario), nunca del input del usuario.\n\nDos prácticas:\n\n1. **System prompt menciona tenant_id implícitamente:** \"Estás operando en el contexto del cliente actual. Nunca preguntes ni asumas un tenant distinto.\"\n\n2. **Tools reciben tenant_id automáticamente, no como argumento del LLM.** Tu código añade `tenant_id=session.tenant_id` antes de ejecutar la tool. El LLM no puede especificarlo.",
                    "code": [
                        {
                            "lang": "python",
                            "label": "Tool con tenant_id automático (no del LLM)",
                            "src": "def execute_tool(tool_name: str, args_from_llm: dict, session: Session) -> dict:\n    \"\"\"Ejecuta una tool. tenant_id viene de la sesión, NO del LLM.\"\"\"\n    if tool_name == \"search_incidents\":\n        # El LLM solo pasa query. tenant_id lo inyectamos NOSOTROS.\n        return search_incidents(\n            query=args_from_llm[\"query\"],\n            tenant_id=session.tenant_id  # ← crucial: del contexto, no del modelo\n        )\n    # Si el LLM intenta especificar tenant_id en args, lo ignoramos:\n    if \"tenant_id\" in args_from_llm:\n        log_security_event(\"LLM tried to set tenant_id\", session)\n        del args_from_llm[\"tenant_id\"]"
                        }
                    ]
                },
                {
                    "title": "Audit log append-only",
                    "body": "Cada acción del agente que afecta datos del cliente debe registrarse en un log inmutable. \"Inmutable\" significa: nadie (ni tú) puede modificar filas existentes. Solo insert.\n\nUsos:\n- Compliance: SOC 2, GDPR exigen auditabilidad.\n- Debug: cuando algo va mal, sabes exactamente qué hizo el agente.\n- Forensic: si hay sospecha de leak, puedes reconstruir.\n- Trust: tu cliente puede ver qué hiciste a sus datos.\n\n**Implementación:** tabla con tenant_id, agent_name, action, params (JSONB), result, timestamp. Trigger en Postgres que rechaza UPDATE/DELETE. Backup a S3 cada hora."
                }
            ],
            "gotchas": [
                { "title": "RLS habilitado pero sin policies", "desc": "Si habilitas RLS pero no creas policies, ningún tenant puede leer nada. La DB queda inaccesible.", "fix": "Verifica que hay 4 policies por tabla (SELECT, INSERT, UPDATE, DELETE) y que las queries pasan tests." },
                { "title": "Usar SET en lugar de SET LOCAL", "desc": "`SET app.tenant_id = X` persiste en la conexión. Si tu pool reusa conexiones, el siguiente request hereda el tenant anterior.", "fix": "Siempre `SET LOCAL` — vive solo en la transacción actual. Si tu app no usa transacciones, envuelve en BEGIN/COMMIT." },
                { "title": "Confiar solo en filtros de app", "desc": "Un bug en código olvida WHERE tenant_id, y leakeas. Tests no siempre lo capturan.", "fix": "RLS + filtros + tests. Defense in depth no-negociable. Aunque tests pasen, RLS te salva del bug que no tested." },
                { "title": "Audit_log mutable", "desc": "Bug o malicia puede editar el log. Pierde valor forensic.", "fix": "Trigger Postgres que rechaza UPDATE/DELETE en la tabla. Backup periódico a S3 con object lock." }
            ],
            "quiz": [
                {
                    "q": "¿Qué hace RLS en PostgreSQL?",
                    "options": ["Encripta datos", "Filtra filas automáticamente según policies", "Hace backup", "Acelera queries"],
                    "correct": 1,
                    "explain": "Row-Level Security define policies que filtran qué filas son visibles. Aunque la query no tenga WHERE, la DB aplica la policy."
                },
                {
                    "q": "¿Cuántas capas tiene defense in depth para multi-tenant?",
                    "options": ["1: solo RLS", "2: app + RLS", "3: RLS + app + agente", "5: una por cada Guard"],
                    "correct": 2,
                    "explain": "Las 3 capas: DB (RLS), app (filtros), agente (tenant_id en contexto). Cada una se valida independientemente. Si una falla, las otras protegen."
                },
                {
                    "q": "¿Quién especifica el tenant_id en el agente?",
                    "options": ["El LLM lo decide", "El usuario lo manda en el input", "El sistema lo inyecta desde la sesión autenticada", "Es opcional"],
                    "correct": 2,
                    "explain": "Nunca el LLM, nunca el input del usuario. tenant_id viene de la sesión autenticada y se inyecta automáticamente en tools."
                },
                {
                    "q": "¿Por qué usar SET LOCAL en lugar de SET?",
                    "options": ["Es más rápido", "SET LOCAL vive solo en la transacción, evitando leak entre requests con pool", "Es más legible", "SET no funciona en Postgres"],
                    "correct": 1,
                    "explain": "SET persiste en la conexión. Si tu pool reusa conexiones, el siguiente request hereda el tenant anterior. SET LOCAL vive solo en la transacción actual."
                },
                {
                    "q": "¿Por qué el audit_log debe ser append-only?",
                    "options": ["Por performance", "Por inmutabilidad: debug, compliance, forensic, trust", "Por costo", "No es necesario"],
                    "correct": 1,
                    "explain": "Audit log mutable pierde valor forensic. Compliance (SOC 2, GDPR), debug, y trust del cliente requieren inmutabilidad. Trigger Postgres rechaza UPDATE/DELETE."
                }
            ],
            "references": [
                { "title": "Multi-tenant data isolation con PostgreSQL RLS (AWS)", "url": "https://aws.amazon.com/blogs/database/multi-tenant-data-isolation-with-postgresql-row-level-security/", "kind": "blog", "relevance": "primary" },
                { "title": "AWS SaaS Factory: PostgreSQL RLS sample", "url": "https://github.com/aws-samples/aws-saas-factory-postgresql-rls", "kind": "repo", "relevance": "primary" },
                { "title": "PostgreSQL RLS docs", "url": "https://www.postgresql.org/docs/current/ddl-rowsecurity.html", "kind": "docs", "relevance": "supporting" }
            ]
        }
    },
    {
        "n": 10, "mod": 3, "id": 10, "module": 3,
        "title": "Auditoría y Observabilidad",
        "sub": "Traces, metrics y logs de cada agente",
        "duration": "45 min", "hours": 1.0,
        "objs": [
            "Implementar OpenTelemetry GenAI Semantic Conventions",
            "Diseñar spans con atributos GenAI completos",
            "Definir alertas operacionales: latencia, costo, error rate",
            "Propagar traces en arquitecturas Orchestrator-Workers"
        ],
        "reading": "OpenTelemetry for LLMs Guide 2026",
        "exercise": "Diseña dashboard de observabilidad con 6 métricas clave + define 3 alertas con thresholds y owners.",
        "deep": {
            "intro": "Sin observabilidad, tu sistema agéntico es una caja negra. **Si no puedes ver qué pasó, no puedes mejorarlo, no puedes debuggear, no puedes confiar en él.**\n\nLa observabilidad de agentes tiene 3 pilares (igual que cualquier sistema distribuido moderno):\n\n1. **Traces** — el flujo de una request a través de agentes y tools. Cada llamada al LLM, cada tool, cada handoff entre agentes es un span.\n2. **Metrics** — agregados sobre el tiempo: latencia P50/P95/P99, costo por request, error rate, tokens consumidos.\n3. **Logs** — eventos discretos con contexto: prompts completos, responses, errores.\n\nEl estándar de la industria: **OpenTelemetry GenAI Semantic Conventions**. Define exactamente qué atributos debe tener un span de LLM (modelo, tokens, finish_reason, etc.) para que tu observability stack (Datadog, Grafana, etc.) los entienda.",
            "sections": [
                {
                    "title": "Spans con GenAI Semantic Conventions",
                    "body": "Un span de llamada a Claude debe incluir como mínimo:\n\n- `gen_ai.system = anthropic`\n- `gen_ai.request.model = claude-sonnet-4-6`\n- `gen_ai.request.max_tokens = 1024`\n- `gen_ai.request.temperature = 0.0`\n- `gen_ai.usage.input_tokens = 1234`\n- `gen_ai.usage.output_tokens = 567`\n- `gen_ai.response.finish_reason = end_turn`\n- `gen_ai.cost.usd = 0.018`  (calculado por tu código)\n\nCon estos atributos, tu observability backend (Grafana, Datadog, Honeycomb, etc.) puede mostrarte: costo total por endpoint, latencia por modelo, ratio de truncation, etc.",
                    "code": [
                        {
                            "lang": "python",
                            "label": "Instrumentar llamada Claude con OpenTelemetry",
                            "src": "from opentelemetry import trace\nfrom anthropic import Anthropic\n\ntracer = trace.get_tracer(__name__)\nclient = Anthropic()\n\nPRICING = {\n    \"claude-haiku-4-5\":  {\"in\": 1.0,  \"out\": 5.0},   # $/M tokens\n    \"claude-sonnet-4-6\": {\"in\": 3.0,  \"out\": 15.0},\n    \"claude-opus-4-7\":   {\"in\": 5.0,  \"out\": 25.0},\n}\n\ndef cost_usd(model: str, input_t: int, output_t: int) -> float:\n    p = PRICING[model]\n    return (input_t * p[\"in\"] + output_t * p[\"out\"]) / 1_000_000\n\ndef call_claude_instrumented(model: str, system: str, messages: list) -> dict:\n    with tracer.start_as_current_span(\"claude.messages.create\") as span:\n        span.set_attribute(\"gen_ai.system\", \"anthropic\")\n        span.set_attribute(\"gen_ai.request.model\", model)\n        span.set_attribute(\"gen_ai.request.max_tokens\", 1024)\n\n        resp = client.messages.create(\n            model=model, max_tokens=1024,\n            system=system, messages=messages\n        )\n\n        usage = resp.usage\n        span.set_attribute(\"gen_ai.usage.input_tokens\", usage.input_tokens)\n        span.set_attribute(\"gen_ai.usage.output_tokens\", usage.output_tokens)\n        span.set_attribute(\"gen_ai.response.finish_reason\", resp.stop_reason)\n        span.set_attribute(\"gen_ai.cost.usd\",\n                           cost_usd(model, usage.input_tokens, usage.output_tokens))\n\n        return resp"
                        }
                    ]
                },
                {
                    "title": "Trace propagation en Orchestrator-Workers",
                    "body": "En arquitecturas multi-agente, cada handoff debe propagar el trace ID. Sin esto, una request que pasa por orchestrator → 3 workers → síntesis se ve como 5 spans desconectados.\n\nOpenTelemetry maneja esto vía **context propagation**. El trace ID se inyecta en headers HTTP entre servicios. Si todos están in-process (mismo Python), la propagación es automática vía ContextVar.\n\n**Resultado:** en tu dashboard, puedes ver la cascada completa: orchestrator → log_analyzer (paralelo con deploy_checker, paralelo con metric_checker) → síntesis. Latencia total, costo total, qué worker tomó más tiempo. Indispensable para optimizar."
                },
                {
                    "title": "Alertas operacionales que importan",
                    "body": "No alertes de todo — alerta de lo que tiene acción clara. Estas tres son no-negociables:\n\n**1. Costo diario > threshold.** Alerta si el costo del día supera 1.5× el promedio semanal. Captura runaway agents (loop infinito) y bugs que llaman LLM en cascada.\n\n**2. Latencia P95 > SLO.** Alerta si la latencia P95 de tus endpoints agénticos sube >25% del baseline. Detecta degradación de modelo o tools lentas.\n\n**3. Error rate > 1%.** Alerta si más del 1% de las llamadas terminan en error (excluyendo errores del cliente). Detecta bugs de prompt, cambios de modelo, problemas de tool.\n\nCada alerta necesita: **threshold**, **owner** (quién responde), **runbook** (qué hacer). Sin runbook, la alerta es ruido."
                }
            ],
            "gotchas": [
                { "title": "Sin trace correlation entre agentes", "desc": "Cada agente loguea independiente. Cuando hay bug, no puedes reconstruir el flujo.", "fix": "OpenTelemetry context propagation. Todos los agentes participan del mismo trace. Trace ID en cada log entry." },
                { "title": "Métricas sin baseline", "desc": "Alertas como '>5s' sin saber qué es normal. False positives constantes.", "fix": "Mide baseline 2-4 semanas. Threshold = baseline + 25%. Recalibra cada release." },
                { "title": "Alertas sin owner", "desc": "Pager dispara, nadie responde. Eventualmente ignoran el pager.", "fix": "Cada alerta tiene un owner asignado (humano o equipo). Runbook con primer paso de troubleshooting. Auditoría mensual: ¿qué alertas se silencian?" },
                { "title": "Logear prompts completos sin redacción", "desc": "PII del cliente termina en tus logs. GDPR/SOC 2 violation.", "fix": "Política de redacción: emails, IDs, contenido sensible se redactan antes de logear. Logs de prompts solo en debug mode con permisos." }
            ],
            "quiz": [
                {
                    "q": "¿Cuáles son los 3 pilares de observabilidad?",
                    "options": ["Logs, metrics, dashboards", "Traces, metrics, logs", "Alertas, runbooks, dashboards", "Errores, warnings, info"],
                    "correct": 1,
                    "explain": "Traces (flujo de request), metrics (agregados temporales), logs (eventos discretos). Cada uno responde preguntas distintas."
                },
                {
                    "q": "¿Qué atributo OpenTelemetry indica el modelo usado?",
                    "options": ["gen_ai.model.name", "gen_ai.request.model", "ai.model", "anthropic.model"],
                    "correct": 1,
                    "explain": "GenAI Semantic Conventions usa `gen_ai.request.model` para el modelo solicitado. Estándar de la industria — funciona en cualquier observability backend."
                },
                {
                    "q": "¿Cuál es el primer alerta no-negociable para un sistema agéntico?",
                    "options": ["UI lenta", "Costo diario > threshold (captura runaway loops)", "Color del logo", "Tamaño de imagen"],
                    "correct": 1,
                    "explain": "Costo runaway es la categoría de bug más cara. Un agente en loop infinito puede gastar cientos de dólares en horas. Alert es no-negociable."
                },
                {
                    "q": "¿Qué pasa si propagas trace IDs entre orchestrator y workers?",
                    "options": ["Nada importante", "Puedes ver la cascada completa en dashboard, debuggear más fácil", "Aumenta el costo", "Slow down"],
                    "correct": 1,
                    "explain": "Sin propagación, cada agente es un trace separado. Con propagación, ves el flujo completo: orchestrator → workers → síntesis. Indispensable para optimizar y debug."
                },
                {
                    "q": "Una alerta dispara sin owner ni runbook. ¿Qué pasa eventualmente?",
                    "options": ["Se resuelve sola", "El equipo la silencia y empieza a ignorar todas las alertas", "Es buena práctica", "No afecta nada"],
                    "correct": 1,
                    "explain": "Alertas sin acción clara generan alert fatigue. El equipo aprende a ignorar el pager. Cuando llega una alerta crítica, nadie responde."
                }
            ],
            "references": [
                { "title": "OpenTelemetry for LLMs (Guide 2026)", "url": "https://openobserve.ai/blog/opentelemetry-for-llms/", "kind": "blog", "relevance": "primary" },
                { "title": "GenAI Semantic Conventions", "url": "https://opentelemetry.io/docs/specs/semconv/gen-ai/", "kind": "docs", "relevance": "primary" },
                { "title": "AI Agent Monitoring in Production", "url": "https://openobserve.ai/blog/ai-agent-monitoring/", "kind": "blog", "relevance": "supporting" }
            ]
        }
    },
    {
        "n": 11, "mod": 3, "id": 11, "module": 3,
        "title": "Setup técnico del entorno",
        "sub": "Del Mac Mini M4 al primer 'docker compose up'",
        "duration": "45 min", "hours": 1.0,
        "objs": [
            "Configurar stack: Postgres + pgvector + FastAPI + Claude Agent SDK",
            "Diseñar primera migration con Alembic",
            "Configurar observabilidad end-to-end",
            "Levantar smoke test funcional"
        ],
        "reading": "Claude Agent SDK Quickstart (platform.claude.com) + best practices",
        "exercise": "Levanta el stack local y ejecuta un smoke test del primer agente con tool real.",
        "deep": {
            "intro": "Para construir PulseCore vas a necesitar un stack local que sea **representativo de producción** pero corra en tu Mac. El objetivo: 1 comando (`docker compose up`) y todo funciona.\n\nStack mínimo:\n\n- **PostgreSQL 16 con pgvector.** Almacenamiento principal y memoria semántica.\n- **FastAPI (Python 3.12).** API + workers.\n- **Anthropic Python SDK / Claude Agent SDK.** Para invocar Claude con tools.\n- **OpenTelemetry SDK + Grafana Tempo + Loki + Prometheus.** Observabilidad local.\n- **Alembic.** Migrations.\n- **Docker Compose.** Orquestación local.\n\nVamos a construirlo en este orden. El smoke test al final: un endpoint `/healthcheck` que invoca un agente Haiku que llama una tool, retorna OK.",
            "sections": [
                {
                    "title": "docker-compose.yml: el stack completo",
                    "body": "Un solo archivo orquesta toda la infraestructura local. Cada servicio expone su puerto, comparte volúmenes para persistencia, y depende del orden correcto.",
                    "code": [
                        {
                            "lang": "yaml",
                            "label": "docker-compose.yml mínimo",
                            "src": "version: '3.9'\nservices:\n  postgres:\n    image: pgvector/pgvector:pg16\n    environment:\n      POSTGRES_USER: pulsecore\n      POSTGRES_PASSWORD: dev\n      POSTGRES_DB: pulsecore\n    ports: ['5432:5432']\n    volumes: ['pgdata:/var/lib/postgresql/data']\n    healthcheck:\n      test: ['CMD', 'pg_isready', '-U', 'pulsecore']\n      interval: 5s\n      timeout: 5s\n      retries: 5\n\n  api:\n    build: .\n    environment:\n      DATABASE_URL: postgresql://pulsecore:dev@postgres:5432/pulsecore\n      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}\n      OTEL_EXPORTER_OTLP_ENDPOINT: http://tempo:4317\n    ports: ['8000:8000']\n    depends_on:\n      postgres: { condition: service_healthy }\n\n  tempo:\n    image: grafana/tempo:latest\n    ports: ['3200:3200', '4317:4317']\n    command: ['-config.file=/etc/tempo.yaml']\n\n  grafana:\n    image: grafana/grafana:latest\n    ports: ['3000:3000']\n    environment:\n      GF_AUTH_ANONYMOUS_ENABLED: 'true'\n      GF_AUTH_ANONYMOUS_ORG_ROLE: Admin\n\nvolumes:\n  pgdata:"
                        }
                    ]
                },
                {
                    "title": "Alembic migration #1: schema base",
                    "body": "Cada cambio de schema vive en un archivo de migration. Versionado, reproducible, rollbackeable. La primera migration crea las tablas con RLS habilitado.",
                    "code": [
                        {
                            "lang": "python",
                            "label": "alembic/versions/001_initial.py",
                            "src": "\"\"\"Initial schema with RLS\"\"\"\nfrom alembic import op\nimport sqlalchemy as sa\n\nrevision = '001'\ndown_revision = None\n\ndef upgrade():\n    op.execute('CREATE EXTENSION IF NOT EXISTS vector')\n    op.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto')\n\n    op.create_table('tenants',\n        sa.Column('id', sa.dialects.postgresql.UUID, primary_key=True,\n                  server_default=sa.text('gen_random_uuid()')),\n        sa.Column('name', sa.String, nullable=False),\n        sa.Column('created_at', sa.DateTime(timezone=True),\n                  server_default=sa.text('NOW()'))\n    )\n\n    op.create_table('incidents',\n        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),\n        sa.Column('tenant_id', sa.dialects.postgresql.UUID,\n                  sa.ForeignKey('tenants.id'), nullable=False, index=True),\n        sa.Column('title', sa.String, nullable=False),\n        sa.Column('severity', sa.String, nullable=False),\n        sa.Column('status', sa.String, nullable=False, server_default='open'),\n        sa.Column('created_at', sa.DateTime(timezone=True),\n                  server_default=sa.text('NOW()'))\n    )\n\n    # Habilita RLS\n    op.execute('ALTER TABLE incidents ENABLE ROW LEVEL SECURITY')\n    op.execute('''\n        CREATE POLICY tenant_isolation ON incidents\n        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)\n    ''')\n\ndef downgrade():\n    op.drop_table('incidents')\n    op.drop_table('tenants')"
                        }
                    ]
                },
                {
                    "title": "Smoke test: el primer agente funcional",
                    "body": "El smoke test es el primer endpoint que invoca el ciclo completo: API recibe request → invoca Claude con una tool → Claude responde con tool_use → ejecutas la tool → devuelves resultado a Claude → Claude responde final. Si esto funciona, el stack está vivo.",
                    "code": [
                        {
                            "lang": "python",
                            "label": "app/main.py — endpoint smoke test",
                            "src": "from fastapi import FastAPI\nfrom anthropic import Anthropic\nimport datetime\n\napp = FastAPI()\nclient = Anthropic()\n\nTOOLS = [{\n    \"name\": \"get_current_time\",\n    \"description\": \"Devuelve la hora actual UTC en ISO 8601.\",\n    \"input_schema\": {\"type\": \"object\", \"properties\": {}}\n}]\n\ndef execute_tool(name: str, args: dict) -> str:\n    if name == \"get_current_time\":\n        return datetime.datetime.utcnow().isoformat() + \"Z\"\n    raise ValueError(f\"unknown tool {name}\")\n\n@app.get(\"/smoke\")\ndef smoke_test():\n    messages = [{\"role\": \"user\", \"content\": \"¿Qué hora es?\"}]\n    while True:\n        resp = client.messages.create(\n            model=\"claude-haiku-4-5\", max_tokens=512,\n            tools=TOOLS, messages=messages\n        )\n        if resp.stop_reason == \"tool_use\":\n            # Claude pidió usar una tool — ejecutamos\n            tool_block = next(b for b in resp.content if b.type == \"tool_use\")\n            result = execute_tool(tool_block.name, tool_block.input)\n            messages += [\n                {\"role\": \"assistant\", \"content\": resp.content},\n                {\"role\": \"user\", \"content\": [{\n                    \"type\": \"tool_result\",\n                    \"tool_use_id\": tool_block.id,\n                    \"content\": result\n                }]}\n            ]\n            continue\n        # Claude respondió final\n        return {\"answer\": resp.content[0].text}"
                        }
                    ]
                }
            ],
            "gotchas": [
                { "title": "No usar Docker, instalar todo nativo", "desc": "Postgres + pgvector + observability stack instalado nativo es pesadilla de reproducción.", "fix": "Docker Compose desde el día 1. Tu repo + .env + docker-compose.yml = stack reproducible." },
                { "title": "ANTHROPIC_API_KEY en el código", "desc": "Commit accidental → key expuesta → cobros inesperados.", "fix": "Variables de entorno. `.env` en .gitignore. Para producción: secrets de cloud provider (AWS Secrets Manager, etc.)" },
                { "title": "Sin healthcheck en docker-compose", "desc": "Servicios arrancan en orden pero no esperan a que el anterior esté listo. Tests random fallan.", "fix": "Cada servicio crítico (Postgres) con healthcheck. Otros servicios con `depends_on: { condition: service_healthy }`." },
                { "title": "Migrations escritas a mano sin Alembic", "desc": "Schema drift entre dev/prod. Imposible rollback.", "fix": "Alembic. Cada cambio = una migration. CI valida que migrations apliquen en clean DB." }
            ],
            "quiz": [
                {
                    "q": "¿Qué imagen Docker incluye pgvector?",
                    "options": ["postgres:16", "pgvector/pgvector:pg16", "mysql:latest", "redis:alpine"],
                    "correct": 1,
                    "explain": "La imagen oficial `pgvector/pgvector:pg16` incluye Postgres 16 con la extensión pgvector preinstalada. Ahorra setup."
                },
                {
                    "q": "¿Dónde NO debe vivir tu ANTHROPIC_API_KEY?",
                    "options": ["En .env (gitignored)", "En código fuente", "En secrets manager de cloud", "En variables de entorno"],
                    "correct": 1,
                    "explain": "Nunca en código. Commit accidental = key expuesta = cobros inesperados. Usa .env (gitignored) localmente y secrets manager en cloud."
                },
                {
                    "q": "¿Para qué sirve `healthcheck` en docker-compose?",
                    "options": ["Acelera el arranque", "Permite a otros servicios esperar a que este esté listo (depends_on: service_healthy)", "Es decorativo", "Reduce el tamaño de imagen"],
                    "correct": 1,
                    "explain": "Sin healthcheck, `depends_on` solo espera a que el container arranque, no a que esté listo. Con healthcheck + service_healthy, espera a que la app responda."
                },
                {
                    "q": "¿Cuál es el rol de Alembic?",
                    "options": ["Migrations de schema versionadas y reversibles", "Backup de DB", "Cache de queries", "Observabilidad"],
                    "correct": 0,
                    "explain": "Alembic versiona los cambios de schema en archivos Python. Cada cambio = upgrade + downgrade. CI valida que las migrations apliquen limpiamente."
                },
                {
                    "q": "En el smoke test, ¿qué hace `stop_reason == 'tool_use'`?",
                    "options": ["Termina", "Indica que Claude pidió ejecutar una tool — tu código la ejecuta y reanuda el loop", "Es un error", "Es opcional"],
                    "correct": 1,
                    "explain": "Cuando Claude decide usar una tool, retorna `stop_reason='tool_use'`. Tu código ejecuta la tool, añade el resultado al mensaje, y llama Claude de nuevo. Loop hasta `stop_reason='end_turn'`."
                }
            ],
            "references": [
                { "title": "Claude Agent SDK Quickstart", "url": "https://platform.claude.com/docs/en/agent-sdk/quickstart", "kind": "anthropic-docs", "relevance": "primary" },
                { "title": "pgvector GitHub", "url": "https://github.com/pgvector/pgvector", "kind": "repo", "relevance": "primary" },
                { "title": "Alembic docs", "url": "https://alembic.sqlalchemy.org/", "kind": "docs", "relevance": "supporting" },
                { "title": "FastAPI docs", "url": "https://fastapi.tiangolo.com/", "kind": "docs", "relevance": "supporting" }
            ]
        }
    },
    {
        "n": 12, "mod": 3, "id": 12, "module": 3,
        "title": "Primer commit con Claude Code",
        "sub": "El Bloque 1 — HealthGuard básico end-to-end",
        "duration": "60 min", "hours": 1.3,
        "objs": [
            "Aplicar best practices de Claude Code: CLAUDE.md, planning, TDD",
            "Delegar investigación a subagents",
            "Escribir el prompt completo para Claude Code del primer bloque",
            "Definir criterios de aceptación del siguiente bloque"
        ],
        "reading": "Best practices for Claude Code (Anthropic Engineering) + Claude Code Advanced Patterns PDF",
        "exercise": "Diseña tu plan personal de 12 semanas para llegar a beta privada. Bloque por bloque.",
        "deep": {
            "intro": "Claude Code es la herramienta más poderosa que tienes para construir PulseCore. Pero usado mal, te da código que parece correcto y no lo es. Usado bien, te da código de producción con tests, observabilidad y documentación.\n\n**Tres prácticas no-negociables de Anthropic Engineering:**\n\n1. **CLAUDE.md** — documento corto que Claude lee cada sesión. Convenciones del codebase, comandos típicos, lo que importa. Si tu CLAUDE.md tiene más de 200 líneas, Claude ignora la mitad.\n\n2. **Subagents para investigar.** Cuando Claude necesita leer mucho contexto del codebase, delega a subagents. Ellos investigan en su propio contexto y reportan resumen. Tu conversación principal queda limpia.\n\n3. **Plan antes de implementar.** Pide explícitamente: \"Antes de escribir código, dame un plan paso a paso. Espera mi aprobación.\" Es la diferencia entre 10 minutos de código y 2 horas de debug.",
            "sections": [
                {
                    "title": "CLAUDE.md: el contrato del codebase",
                    "body": "CLAUDE.md vive en la raíz de tu repo. Cada sesión de Claude Code lo lee. Lo importante: que sea **corto y útil**.\n\nSecciones canónicas:\n\n- **Setup.** Cómo arrancar local (1-2 comandos).\n- **Convenciones.** Estilo de código, naming, estructura de carpetas.\n- **Comandos típicos.** `make test`, `make lint`, `make migrate`.\n- **No-go zones.** Qué NO debe tocar Claude sin pedirte primero.\n\nEvita: documentar el código en sí (eso va en docstrings), historia del proyecto, valores corporativos. CLAUDE.md es para que Claude tome buenas decisiones operativas, no para inspirar.",
                    "code": [
                        {
                            "lang": "markdown",
                            "label": "CLAUDE.md ejemplar para PulseCore",
                            "src": "# CLAUDE.md\n\n## Setup local\n```\ndocker compose up -d\nmake migrate\nmake test\n```\n\n## Convenciones\n- Python 3.12, FastAPI, async-first.\n- Snake_case para funciones y variables. PascalCase para clases.\n- Tipos explícitos en TODA función pública.\n- Tests en `tests/` mirroring estructura de `app/`.\n\n## Comandos\n- `make test` — pytest con cobertura\n- `make lint` — ruff + mypy strict\n- `make migrate` — alembic upgrade head\n- `make new-migration name=...` — genera migration template\n\n## Estructura\n```\napp/\n  agents/      ← 5 Guards de PulseCore\n  tools/       ← tools que invocan agentes\n  db/          ← SQLAlchemy models + RLS\n  obs/         ← OpenTelemetry instrumentation\n  main.py      ← FastAPI entrypoint\n```\n\n## NO toques sin preguntar\n- `app/db/migrations/` (excepto si te pido nueva migration)\n- `secrets.env` (gitignored)\n- `app/agents/remediator.py` (tiene guardrails que requieren review)\n\n## Test antes de commit\nSi cambias agentes, corre `make test-agents` (incluye eval set de regresión)."
                        }
                    ]
                },
                {
                    "title": "Subagents para investigar",
                    "body": "Cuando Claude necesita entender una parte del codebase para hacer un cambio, naturalmente lee muchos archivos. Cada archivo consume tu contexto. Conversación se llena de archivos en lugar de plan.\n\nLa solución: **delegar a un subagent**. Le pides: *\"Antes de implementar X, usa un subagent para investigar cómo funciona Y en este codebase. Reporta resumen.\"* El subagent abre su propio contexto, lee todo lo que necesita, y vuelve con un resumen ejecutivo.\n\nResultado: tu conversación principal queda limpia. Claude opera con resumen, no con 50 archivos. Decisiones mejores, menos tokens consumidos, menos confusión.",
                    "code": [
                        {
                            "lang": "text",
                            "label": "Patrón de delegación a subagent",
                            "src": "Tu prompt:\n\n\"Quiero modificar Diagnostician para que use Tool Search Tool cuando hay >15 tools.\n\nAntes de implementar:\n1. Usa un subagent para investigar cómo está configurado Diagnostician actualmente.\n   El subagent debe leer app/agents/diagnostician.py y archivos relacionados\n   (tools/, system prompts). Reporta:\n   - Cuántas tools tiene hoy\n   - Cómo se cargan (estático vs dinámico)\n   - Tests existentes que cubren load de tools\n\n2. Una vez tengamos el resumen, propone un plan de cambio.\n   Espera mi aprobación antes de escribir código.\n\n3. Si tienes dudas en el medio, pregunta. No asumas.\"\n\nClaude responde:\n\"OK. Lanzo subagent para investigar Diagnostician...\"\n[subagent corre, vuelve con resumen]\n\"Aquí está el resumen: ... ¿procedo con plan?\""
                        }
                    ]
                },
                {
                    "title": "Plan antes de implementar — el patrón que ahorra horas",
                    "body": "El instinto malo: prompts como *\"implementa X\"* y Claude empieza a escribir código. 30 minutos después tienes 500 líneas que no funcionan y no sabes por qué.\n\nEl instinto bueno: *\"Antes de implementar X, dame un plan paso a paso. Para cada paso: archivos a modificar, función específica, lo que cambia. NO escribas código aún. Espera mi aprobación del plan.\"*\n\nClaude responde con plan. Tú lees, identificas el paso que está mal, lo corriges. Una vez aprobado, dices *\"procede con el plan, paso 1\"*. Implementa solo eso. Verifica. Pasa al 2.\n\n**Bloque por bloque, cada bloque deja el sistema funcional pero no completo.** Acumulas funcionalidad sin nunca romper lo previo. Es la diferencia entre un proyecto que termina y uno que se atasca."
                }
            ],
            "gotchas": [
                { "title": "CLAUDE.md gigante", "desc": "500 líneas con historia del proyecto, valores, todo. Claude ignora la mitad.", "fix": "Máximo 200 líneas. Solo lo operativo: setup, convenciones, comandos, no-go zones. Lo demás vive en README.md (para humanos)." },
                { "title": "No usar subagents", "desc": "Cargas todo el contexto en tu conversación. Después de 10 mensajes, Claude se confunde.", "fix": "Para tareas que requieren investigación previa, delega. Tu conversación se mantiene en plan + implementación, no en lectura de archivos." },
                { "title": "Pegar diffs de Claude sin leerlos", "desc": "Vibe coding: ejecutas todo lo que dice Claude. Eventualmente algo crítico se rompe.", "fix": "Lee cada diff. Si no entiendes una línea, pregunta. Claude Code es asistente, no autoridad." },
                { "title": "Sin tests antes de commitear", "desc": "Avanzas bloque por bloque pero sin tests, cada bloque puede romper el anterior silenciosamente.", "fix": "TDD modificado: primer paso de cada bloque es escribir el test que valida el comportamiento. Después implementación. Después: corres TODOS los tests." }
            ],
            "quiz": [
                {
                    "q": "¿Qué tan largo debe ser tu CLAUDE.md?",
                    "options": ["Lo más largo posible", "Máximo 200 líneas, solo operativo", "1 línea", "Sin importancia"],
                    "correct": 1,
                    "explain": "Claude ignora CLAUDE.md grandes. Máximo 200 líneas con setup, convenciones, comandos, no-go zones. Historia y valores van en README.md."
                },
                {
                    "q": "¿Qué hacen los subagents en Claude Code?",
                    "options": ["Versión más cara de Claude", "Investigan en su propio contexto y reportan resumen, manteniendo tu conversación limpia", "Backup", "Solo para coding"],
                    "correct": 1,
                    "explain": "Subagents corren en contexto separado. Investigan, leen archivos, sintetizan. Reportan resumen. Tu conversación principal queda enfocada en plan + implementación."
                },
                {
                    "q": "¿Cuál es el patrón correcto antes de implementar?",
                    "options": ["Implementar primero y refactorizar", "Pedir plan paso a paso, aprobar, implementar bloque por bloque", "Generar todo de una vez", "No planificar"],
                    "correct": 1,
                    "explain": "Plan primero, aprobación, bloque por bloque. Cada bloque deja el sistema funcional. Ahorra horas de debug."
                },
                {
                    "q": "Tu bloque 3 rompió funcionalidad del bloque 1. ¿Cómo lo evitaste?",
                    "options": ["Con suerte", "Tests automatizados que corren después de cada bloque", "Code review de humano", "Imposible evitarlo"],
                    "correct": 1,
                    "explain": "Test suite que corre después de cada bloque. Si bloque 3 rompió bloque 1, el test del bloque 1 falla. Captura regresión antes de commit."
                },
                {
                    "q": "¿Qué pasa si pegas diffs de Claude sin leerlos?",
                    "options": ["Funciona siempre", "Eventualmente algo crítico se rompe — Claude no es infalible", "Es la mejor práctica", "Más rápido"],
                    "correct": 1,
                    "explain": "Vibe coding (ejecutar todo lo que Claude propone sin revisar) eventualmente introduce bugs serios. Claude es asistente, no autoridad. Cada diff necesita lectura."
                }
            ],
            "references": [
                { "title": "Best practices for Claude Code", "url": "https://code.claude.com/docs/en/best-practices", "kind": "anthropic-docs", "relevance": "primary" },
                { "title": "Claude Code Advanced Patterns (PDF)", "url": "https://resources.anthropic.com/hubfs/Claude%20Code%20Advanced%20Patterns_%20Subagents,%20MCP,%20and%20Scaling%20to%20Real%20Codebases.pdf", "kind": "anthropic-pdf", "relevance": "primary" },
                { "title": "Claude Code plugins README", "url": "https://github.com/anthropics/claude-code/blob/main/plugins/README.md", "kind": "repo", "relevance": "supporting" },
                { "title": "Building agents with the Claude Agent SDK", "url": "https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk", "kind": "anthropic-engineering", "relevance": "supporting" }
            ]
        }
    }
]


def main():
    data = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    data["sessions"].extend(NEW_SESSIONS)
    data["updatedAt"] = "2026-05-16"
    CONTENT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )
    print(f"OK · {len(data['sessions'])} sessions total in content.json")


if __name__ == "__main__":
    main()
