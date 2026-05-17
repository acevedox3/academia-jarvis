#!/usr/bin/env python3
"""
Multi-provider adapter para Python.

Mismo concepto que worker/lib/providers.js, pero para usar desde scripts/GitHub Actions.

Uso:
    from providers import chat, PROVIDERS

    result = chat(
        provider='google',
        model='gemini-2.5-flash',
        system='Eres un asistente...',
        messages=[{'role':'user','content':'...'}],
        max_tokens=600,
        json_mode=True
    )
    # → {'text': str, 'usage': {'input_tokens', 'output_tokens'}, 'model', 'cost_usd', 'provider'}

Env vars: ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY
"""

import os
import json
from typing import Optional
import requests

PRICING = {
    # Anthropic
    'claude-haiku-4-5':       {'in': 1.00, 'out': 5.00},
    'claude-haiku-4-5-20251001': {'in': 1.00, 'out': 5.00},
    'claude-sonnet-4-6':      {'in': 3.00, 'out': 15.00},
    'claude-opus-4-7':        {'in': 5.00, 'out': 25.00},
    # OpenAI
    'gpt-5':                  {'in': 3.00, 'out': 12.00},
    'gpt-5-mini':             {'in': 0.25, 'out': 2.00},
    'gpt-5-nano':             {'in': 0.10, 'out': 0.40},
    'gpt-4o':                 {'in': 2.50, 'out': 10.00},
    'gpt-4o-mini':            {'in': 0.15, 'out': 0.60},
    # Google
    'gemini-2.5-flash':       {'in': 0.10, 'out': 0.40},
    'gemini-2.5-flash-lite':  {'in': 0.075, 'out': 0.30},
    'gemini-2.5-pro':         {'in': 1.25, 'out': 5.00},
}

PROVIDERS = {
    'anthropic': {
        'label': 'Anthropic Claude',
        'default_model': 'claude-sonnet-4-6',
        'cheap_model':   'claude-haiku-4-5',
        'env_key': 'ANTHROPIC_API_KEY',
    },
    'openai': {
        'label': 'OpenAI GPT',
        'default_model': 'gpt-5',
        'cheap_model':   'gpt-5-mini',
        'env_key': 'OPENAI_API_KEY',
    },
    'google': {
        'label': 'Google Gemini',
        'default_model': 'gemini-2.5-pro',
        'cheap_model':   'gemini-2.5-flash',
        'env_key': 'GOOGLE_API_KEY',
    },
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    p = PRICING.get(model)
    if not p:
        return None
    return (input_tokens * p['in'] + output_tokens * p['out']) / 1_000_000


def chat(provider='anthropic', model=None, system=None, messages=None,
         max_tokens=1024, temperature=None, json_mode=False, timeout=60):
    """Llamada unificada a cualquiera de los 3 proveedores."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider {provider}")
    if model is None:
        model = PROVIDERS[provider]['default_model']
    env_key = PROVIDERS[provider]['env_key']
    api_key = os.environ.get(env_key)
    if not api_key:
        raise RuntimeError(f"Missing env var {env_key}")

    if provider == 'anthropic':
        result = _anthropic_chat(api_key, model, system, messages, max_tokens, temperature, timeout)
    elif provider == 'openai':
        result = _openai_chat(api_key, model, system, messages, max_tokens, temperature, json_mode, timeout)
    elif provider == 'google':
        result = _google_chat(api_key, model, system, messages, max_tokens, temperature, json_mode, timeout)

    result['provider'] = provider
    result['model'] = model
    result['cost_usd'] = cost_usd(model, result['usage']['input_tokens'], result['usage']['output_tokens'])
    return result


def _anthropic_chat(api_key, model, system, messages, max_tokens, temperature, timeout):
    body = {'model': model, 'max_tokens': max_tokens, 'messages': messages}
    if system: body['system'] = system
    if temperature is not None: body['temperature'] = temperature
    r = requests.post(
        'https://api.anthropic.com/v1/messages',
        headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
        json=body, timeout=timeout
    )
    r.raise_for_status()
    data = r.json()
    return {
        'text': (data.get('content') or [{}])[0].get('text', ''),
        'usage': {
            'input_tokens': data.get('usage', {}).get('input_tokens', 0),
            'output_tokens': data.get('usage', {}).get('output_tokens', 0),
        },
        'finish_reason': data.get('stop_reason', 'unknown'),
    }


def _openai_chat(api_key, model, system, messages, max_tokens, temperature, json_mode, timeout):
    msgs = []
    if system: msgs.append({'role': 'system', 'content': system})
    msgs.extend(messages)
    body = {'model': model, 'messages': msgs, 'max_completion_tokens': max_tokens}
    if temperature is not None: body['temperature'] = temperature
    if json_mode: body['response_format'] = {'type': 'json_object'}
    r = requests.post(
        'https://api.openai.com/v1/chat/completions',
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json=body, timeout=timeout
    )
    r.raise_for_status()
    data = r.json()
    choice = (data.get('choices') or [{}])[0]
    return {
        'text': choice.get('message', {}).get('content', '') or '',
        'usage': {
            'input_tokens': data.get('usage', {}).get('prompt_tokens', 0),
            'output_tokens': data.get('usage', {}).get('completion_tokens', 0),
        },
        'finish_reason': choice.get('finish_reason', 'unknown'),
    }


def _google_chat(api_key, model, system, messages, max_tokens, temperature, json_mode, timeout):
    contents = [{
        'role': 'model' if m['role'] == 'assistant' else m['role'],
        'parts': [{'text': m['content']}]
    } for m in messages]
    body = {
        'contents': contents,
        'generationConfig': {'maxOutputTokens': max_tokens}
    }
    if system:
        body['systemInstruction'] = {'parts': [{'text': system}]}
    if temperature is not None:
        body['generationConfig']['temperature'] = temperature
    if json_mode:
        body['generationConfig']['responseMimeType'] = 'application/json'
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}'
    r = requests.post(url, json=body, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    cand = (data.get('candidates') or [{}])[0]
    text = ''.join(p.get('text', '') for p in (cand.get('content') or {}).get('parts', []))
    meta = data.get('usageMetadata', {})
    return {
        'text': text,
        'usage': {
            'input_tokens': meta.get('promptTokenCount', 0),
            'output_tokens': meta.get('candidatesTokenCount', 0),
        },
        'finish_reason': cand.get('finishReason', 'unknown'),
    }
