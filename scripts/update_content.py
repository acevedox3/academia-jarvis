#!/usr/bin/env python3
"""
Weekly content updater for Academia Jarvis (multi-provider).

DEFAULT: Google Gemini 2.5 Flash (~$0.10-0.15 per weekly run, ~$5-8/year)
Override via env vars: PROVIDER=anthropic|openai|google · MODEL=...

Pipeline:
1. Fetches Anthropic's official sources (docs, blog, engineering, MCP, pricing).
2. Asks the configured LLM to diff our content vs the fresh state.
3. Classifies update as 'minor' (auto-merge) or 'major' (PR for review).
4. Updates www/content.json with the patch.
5. Writes .update_classification and .update_summary.md for the workflow.
"""

import json
import os
import sys
import datetime
import re
from pathlib import Path

import requests

# Import multi-provider adapter (relative to this script)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from providers import chat, PROVIDERS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONTENT_PATH = ROOT / "www" / "content.json"
CLASSIFICATION_FILE = ROOT / ".update_classification"
SUMMARY_FILE = ROOT / ".update_summary.md"

# Provider configuration (env override)
PROVIDER = os.environ.get("PROVIDER", "google")
MODEL = os.environ.get("MODEL", PROVIDERS[PROVIDER]["cheap_model"])

# Sources we monitor for changes (curated, lightweight)
SOURCES = [
    {"id": "building-effective-agents",
     "url": "https://www.anthropic.com/research/building-effective-agents",
     "kind": "anthropic-research", "weight": "high"},
    {"id": "advanced-tool-use",
     "url": "https://www.anthropic.com/engineering/advanced-tool-use",
     "kind": "anthropic-engineering", "weight": "high"},
    {"id": "claude-code-best-practices",
     "url": "https://code.claude.com/docs/en/best-practices",
     "kind": "claude-code-docs", "weight": "medium"},
    {"id": "agent-sdk-overview",
     "url": "https://code.claude.com/docs/en/agent-sdk/overview",
     "kind": "claude-code-docs", "weight": "medium"},
    {"id": "mcp-intro",
     "url": "https://modelcontextprotocol.io/docs/getting-started/intro",
     "kind": "mcp-docs", "weight": "high"},
    {"id": "claude-pricing",
     "url": "https://platform.claude.com/docs/en/about-claude/pricing",
     "kind": "anthropic-docs", "weight": "high"},
    {"id": "building-with-agent-sdk",
     "url": "https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk",
     "kind": "anthropic-engineering", "weight": "medium"},
]

MAX_FETCH_CHARS = 8000


def fetch_source(src: dict) -> str:
    try:
        r = requests.get(src["url"], timeout=20,
                         headers={"User-Agent": "academia-jarvis-bot/1.0"})
        if r.status_code != 200:
            return ""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text[:MAX_FETCH_CHARS]
    except Exception as e:
        print(f"[fetch_source] {src['id']}: error {e}", file=sys.stderr)
        return ""


def load_content() -> dict:
    return json.loads(CONTENT_PATH.read_text(encoding="utf-8"))


def save_content(data: dict) -> None:
    CONTENT_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )


SYSTEM_PROMPT = """Eres el editor automático de "Academia Jarvis", un plan de estudio sobre construcción de agentes IA basado en documentación oficial de Anthropic.

Tu tarea: comparar el contenido actual con páginas oficiales recién escaneadas, y proponer actualizaciones precisas.

REGLAS ESTRICTAS:
1. Solo propones cambios respaldados por evidencia directa de las fuentes. No inventes.
2. Clasificas cada cambio como:
   - "minor": agregar link nuevo, actualizar precio, corregir typo, agregar paper a biblioteca. Auto-merge.
   - "major": reescribir sesión, cambiar objetivos, añadir/quitar sesión completa. Requiere revisión humana.
3. Si no hay cambios sustantivos, devuelves changes=[].
4. Mantienes el tono, idioma (español) y estructura JSON existentes.
5. Cuando agregues un recurso, especifica categoría exacta del array `resources`.

OUTPUT REQUERIDO: JSON estricto:
{
  "summary": "Resumen 1-2 líneas",
  "classification": "minor" | "major" | "none",
  "changes": [{"type": "...", "path": "...", "before": ..., "after": ..., "rationale": "..."}],
  "patched_content": <objeto content completo con cambios aplicados>
}"""


def call_llm(current: dict, sources_text: dict) -> dict:
    user_msg = (
        "CONTENIDO ACTUAL (JSON):\n```json\n"
        + json.dumps(current, ensure_ascii=False, indent=2)[:18000]
        + "\n```\n\nFUENTES ESCANEADAS HOY:\n"
    )
    for src_id, body in sources_text.items():
        if not body:
            continue
        user_msg += f"\n--- {src_id} ---\n{body[:4500]}\n"

    user_msg += "\n\nPropón el patch siguiendo el formato JSON requerido."

    print(f"Calling {PROVIDER}/{MODEL}...")
    result = chat(
        provider=PROVIDER,
        model=MODEL,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=4096,
        json_mode=True,
    )
    if result.get('cost_usd') is not None:
        print(f"Cost: ${result['cost_usd']:.4f}  "
              f"(in={result['usage']['input_tokens']}t, out={result['usage']['output_tokens']}t)")

    raw = result['text'].strip()
    m = re.search(r"\{[\s\S]+\}", raw)
    if not m:
        return {"summary": "No diff produced", "classification": "none", "changes": [], "patched_content": current}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"[parse] JSON error: {e}", file=sys.stderr)
        return {"summary": "Parse error", "classification": "none", "changes": [], "patched_content": current}


def main() -> int:
    mode = os.environ.get("UPDATE_MODE", "hybrid")
    print(f"Mode: {mode} · Provider: {PROVIDER} · Model: {MODEL}")
    print(f"Fetching {len(SOURCES)} sources...")
    sources_text = {src["id"]: fetch_source(src) for src in SOURCES}
    print(f"Fetched: {sum(1 for v in sources_text.values() if v)} of {len(SOURCES)} ok")

    current = load_content()

    result = call_llm(current, sources_text)

    classification = result.get("classification", "none")
    summary = result.get("summary", "(no summary)")
    changes = result.get("changes", []) or []
    patched = result.get("patched_content")

    print(f"Classification: {classification}")
    print(f"Summary: {summary}")
    print(f"Changes: {len(changes)}")

    CLASSIFICATION_FILE.write_text(classification.strip(), encoding="utf-8")

    md = f"# Weekly content update — {datetime.date.today().isoformat()}\n\n"
    md += f"**Provider:** `{PROVIDER}/{MODEL}`\n\n"
    md += f"**Classification:** `{classification}`\n\n"
    md += f"**Summary:** {summary}\n\n"
    if changes:
        md += "## Changes\n\n"
        for i, c in enumerate(changes, 1):
            md += f"### {i}. {c.get('type', '?')} — {c.get('path', '?')}\n"
            if c.get("rationale"):
                md += f"> {c['rationale']}\n\n"
            if "before" in c:
                md += f"**Antes:**\n```\n{json.dumps(c['before'], ensure_ascii=False)[:400]}\n```\n"
            if "after" in c:
                md += f"**Después:**\n```\n{json.dumps(c['after'], ensure_ascii=False)[:400]}\n```\n\n"
    else:
        md += "Sin cambios sustantivos esta semana.\n"
    SUMMARY_FILE.write_text(md, encoding="utf-8")

    if mode == "dry-run":
        print("DRY RUN mode — not writing content.json")
        return 0

    if classification == "none" or not patched:
        print("No update applied")
        return 0

    today = datetime.date.today().isoformat()
    patched.setdefault("version", current.get("version", "v1.0.0"))
    v = patched["version"].lstrip("v").split(".")
    if len(v) == 3:
        try:
            v[2] = str(int(v[2]) + 1)
            patched["version"] = "v" + ".".join(v)
        except Exception:
            pass
    patched["updatedAt"] = today

    save_content(patched)
    print(f"content.json updated. Classification: {classification}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
