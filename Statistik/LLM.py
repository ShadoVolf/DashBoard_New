# Statistik/LLM.py
"""Мост к LM Studio (OpenAI-совместимый API).

Реализует:
  * summarize_msk()   - вариант A: интерпретация готовой статистики;
  * nl_query()        - вариант B: NL-запрос через tool calling;
  * save_report_pdf() - сохранение отчёта в PDF (reportlab).

Модель: mistral-7b-instruct-v0.2
Сервер: http://172.16.20.16:1234
Контекст: 8192 токенов.

Особенности mistral-7b-instruct-v0.2:
  * chat-template не поддерживает роль 'system'
    -> _prepare_messages() сливает system в первое user-сообщение;
  * LM Studio принимает response_format только 'json_schema' или 'text'
    -> ENFORCE_JSON_MODE='json_schema', с fallback на 'text'.
"""

import json
import os
import queue
import re
import threading
import time
from typing import Callable
import Statistik.Data
import requests

# ------------------------------- config -------------------------------

# --------------------------- провайдеры LLM ---------------------------

LLM_PROVIDERS = {
'Gemma_4_e': {
        'label': 'google/gemma-4-e4b (172.16.20.16)',
        'model': 'google/gemma-4-e4b',
        'host':  'http://172.16.20.16:1234',
        'needs_system_merge': True,
    },
'gemma_4_2': {
        'label': 'gemma-4-e4b-it (172.16.36.76)',
        'model': 'gemma-4-e4b-it',
        'host':  'http://172.16.36.76:1234',
        'needs_system_merge': True,
    },
}

_ACTIVE_PROVIDER_KEY = 'gemma_4_2'

LMSTUDIO_CHAT_URL   = LLM_PROVIDERS[_ACTIVE_PROVIDER_KEY]['host'] + "/v1/chat/completions"
LMSTUDIO_MODELS_URL = LLM_PROVIDERS[_ACTIVE_PROVIDER_KEY]['host'] + "/v1/models"
MODEL_NAME          = LLM_PROVIDERS[_ACTIVE_PROVIDER_KEY]['model']

REQUEST_TIMEOUT = 180

# ---- бюджет контекста ----
MAX_CONTEXT_TOKENS = 8192
OUTPUT_RESERVE     = 1200
MAX_INPUT_TOKENS   = MAX_CONTEXT_TOKENS - OUTPUT_RESERVE
DEFAULT_MAX_TOKENS = 2024

# Mistral-7B-Instruct-v0.2 не имеет нативного tool-calling
SUPPORTS_NATIVE_TOOLS = False

# ---- режим JSON-грамматики ----
#   "json_schema" - современный LM Studio (default)
#   None          - без грамматики (чистый text, полагаемся на few-shot)
# При 400 с упоминанием 'response_format' _chat() сам переключит на None.
ENFORCE_JSON_MODE = "json_schema"

# ---- лог ----
LOG_TO_CONSOLE = True
LOG_VERBOSE    = False

# ---- ограничения ----
MAX_STEPS             = 10
MAX_TOOL_RESULT_CHARS = 8000


# ---------------------------- подготовка messages ---------------------

_NEEDS_SYSTEM_MERGE = False   # поднимем в True при первом же 400

# ---------------------------- выбор провайдера -------------------------

def get_active_provider() -> str:
    """Ключ текущего провайдера ('mistral' | 'qwen')."""
    return _ACTIVE_PROVIDER_KEY


def get_provider_keys():
    """Список ключей доступных провайдеров (порядок сохраняется)."""
    return list(LLM_PROVIDERS.keys())


def get_provider_label(key: str) -> str:
    """Человеко-читаемое имя провайдера для UI."""
    return LLM_PROVIDERS.get(key, {}).get('label', key)


def get_active_model_name() -> str:
    """Имя активной модели (для отображения)."""
    return MODEL_NAME


def set_provider(key: str) -> bool:
    """Переключить активный провайдер LLM (URL, модель, режим)."""
    global _ACTIVE_PROVIDER_KEY, LMSTUDIO_CHAT_URL, LMSTUDIO_MODELS_URL
    global MODEL_NAME, _NEEDS_SYSTEM_MERGE, ENFORCE_JSON_MODE

    if key not in LLM_PROVIDERS:
        return False

    _ACTIVE_PROVIDER_KEY = key
    info = LLM_PROVIDERS[key]
    LMSTUDIO_CHAT_URL   = info['host'] + "/v1/chat/completions"
    LMSTUDIO_MODELS_URL = info['host'] + "/v1/models"
    MODEL_NAME          = info['model']
    _NEEDS_SYSTEM_MERGE = False
    ENFORCE_JSON_MODE   = "json_schema"
    _log(f'[LLM] provider -> {key} ({MODEL_NAME} @ {info["host"]})')
    return True


def _model_needs_system_merge() -> bool:
    info = LLM_PROVIDERS.get(_ACTIVE_PROVIDER_KEY, {})
    if 'needs_system_merge' in info:
        return bool(info['needs_system_merge'])
    # fallback — если флага нет
    m = (MODEL_NAME or "").lower()
    if "lmstudio-community" in m or "qwen" in m:
        return False
    return ("mistral" in m) and ("v0.1" in m or "v0.2" in m)

def _model_needs_system_merge_1() -> bool:
    """Mistral-7B-Instruct-v0.1/v0.2 (оригинальный шаблон) не умеют system."""
    m = (MODEL_NAME or "").lower()
    if "lmstudio-community" in m:
        return False      # у их сборок шаблон исправлен
    return ("mistral" in m) and ("v0.1" in m or "v0.2" in m)


def _merge_roles(messages):
    """Слить system/tool в user; оставить только user и assistant.

    Mistral-7B-Instruct-v0.2 Jinja-template падает на system/tool.
    Слияние в первое user-сообщение - стандартный workaround
    (см. https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.2).
    """
    out = []
    pending = []      # накопленный system/tool текст

    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""

        if role in ("system", "tool"):
            pending.append(content)
            continue

        if role == "user":
            merged = ("\n\n".join(pending) + "\n\n" + content
                      if pending else content)
            pending = []
            out.append({"role": "user", "content": merged})
            continue

        # assistant
        out.append({"role": "assistant", "content": content})

    # если что-то осталось (не было user после system) - прилепим к user
    if pending:
        if out:
            for i in range(len(out) - 1, -1, -1):
                if out[i]["role"] == "user":
                    out[i]["content"] = (out[i]["content"] + "\n\n"
                                         + "\n\n".join(pending))
                    break
        else:
            out.append({"role": "user",
                        "content": "\n\n".join(pending)})
    return out


def _prepare_messages(messages):
    global _NEEDS_SYSTEM_MERGE
    if _NEEDS_SYSTEM_MERGE or _model_needs_system_merge():
        return _merge_roles(messages)
    return messages


# ---------------------------- low-level API ----------------------------

def _clean(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"</?think>", "", text)
    text = re.sub(r"<\|[^|]*\|>", "", text)
    return text.strip()


def _log(msg: str):
    if LOG_TO_CONSOLE:
        try:
            print(msg, flush=True)
        except Exception:
            pass


def _preview(text, n: int = 200) -> str:
    s = str(text or "").replace("\n", " ")
    return s if len(s) <= n else s[:n] + "..."


def _estimate_tokens(text) -> int:
    if not text:
        return 0
    return max(1, len(str(text)) // 2)


def _messages_tokens(messages) -> int:
    return sum(_estimate_tokens(m.get("content", "")) + 6 for m in messages)


def _trim_messages(messages, max_tokens: int):
    if _messages_tokens(messages) <= max_tokens:
        return messages

    msgs = [dict(m) for m in messages]

    if len(msgs) <= 2:
        for m in msgs:
            c = m.get("content", "") or ""
            limit = max_tokens * 2
            if len(c) > limit:
                m["content"] = c[:limit] + "...[truncated]"
        return msgs

    trimmed = [msgs[0]]
    tail = msgs[1:]
    while tail and _messages_tokens(trimmed + tail) > max_tokens:
        tail.pop(0)
    for m in tail:
        c = m.get("content", "") or ""
        if len(c) > 1500:
            m["content"] = c[:1500] + "...[truncated]"
    return trimmed + tail


# Схема, в которую GBNF загонит ответ mistral. Не strict - разрешаем
# либо {"tool":..., "args":{...}}, либо {"answer": "..."}.
_JSON_SCHEMA = {
    "name": "tool_or_answer",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "tool":   {"type": "string"},
            "args":   {"type": "object"},
            "answer": {"type": "string"},
        },
        "additionalProperties": False,
    },
}


def _chat(messages, tools=None, temperature=0.2, max_tokens=None,
          force_json=False, _retry_level=0):
    """POST в LM Studio.

    force_json -> пробуем response_format:
        "json_schema"  ->  {"type":"json_schema", "json_schema": {...}}
        None           ->  без response_format
    На 400 с упоминанием response_format откатываемся на None.

    _retry_level:
        0 - обычный вызов
        1 - повтор без response_format
        2 - повтор с _merge_roles (после "Only user and assistant"
            ошибки Jinja-шаблона)
    """
    global ENFORCE_JSON_MODE, _NEEDS_SYSTEM_MERGE

    if max_tokens is None:
        max_tokens = DEFAULT_MAX_TOKENS

    # при ошибке шаблона ролей - форсируем merge
    if _retry_level >= 2:
        _NEEDS_SYSTEM_MERGE = True

    messages = _prepare_messages(messages)
    messages = _trim_messages(messages, MAX_INPUT_TOKENS)

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    json_mode = (force_json and ENFORCE_JSON_MODE == "json_schema")
    if json_mode:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": _JSON_SCHEMA,
        }

    est = _messages_tokens(messages)
    roles = ",".join(sorted({m.get("role") for m in messages}))
    _log(f"[LLM->] POST model={MODEL_NAME} msgs={len(messages)} "
         f"roles=[{roles}] est_tokens={est} max_tok={max_tokens} "
         f"tools={'yes' if tools else 'no'} "
         f"json={'yes' if json_mode else 'no'} retry={_retry_level}")
    last_user = next((m for m in reversed(messages)
                      if m.get("role") == "user"), None)
    if last_user:
        _log(f"[LLM->] user: {_preview(last_user.get('content'), 200)}")

    t0 = time.time()
    try:
        r = requests.post(LMSTUDIO_CHAT_URL, json=payload,
                          timeout=REQUEST_TIMEOUT)
    except Exception as e:
        _log(f"[LLM!!] request error after {time.time()-t0:.1f}s: {e}")
        raise

    elapsed = time.time() - t0

    # ---------- обработка 400 ----------
    if r.status_code == 400:
        try:
            body = r.text or ""
        except Exception:
            body = ""

        # (a) сервер не принял response_format - откатываемся
        if ("response_format" in body or "json_object" in body
                or "json_schema" in body) and _retry_level < 1:
            _log(f"[LLM!!] 400 on response_format - retry without it: "
                 f"{body[:200]}")
            ENFORCE_JSON_MODE = None
            return _chat(messages, tools=tools, temperature=temperature,
                         max_tokens=max_tokens, force_json=False,
                         _retry_level=1)

        # (b) шаблон не поддерживает system - сливаем в user
        if ("Only user and assistant" in body
                or "jinja template" in body.lower()
                or "roles are supported" in body) and _retry_level < 2:
            _log(f"[LLM!!] template rejects roles - merging system->user: "
                 f"{body[:200]}")
            return _chat(messages, tools=tools, temperature=temperature,
                         max_tokens=max_tokens, force_json=force_json,
                         _retry_level=2)

        _log(f"[LLM!!] HTTP 400 after {elapsed:.1f}s: {body[:300]}")
        r.raise_for_status()

    if r.status_code != 200:
        _log(f"[LLM!!] HTTP {r.status_code} after {elapsed:.1f}s: "
             f"{r.text[:300]}")
        r.raise_for_status()

    data = r.json()
    usage = data.get("usage", {}) or {}
    msg = data["choices"][0]["message"]
    content = _clean(msg.get("content") or "")
    reasoning = msg.get("reasoning_content") or ""
    tool_calls = msg.get("tool_calls") or []

    _log(f"[LLM<-] {elapsed:.1f}s HTTP {r.status_code} "
         f"in={usage.get('prompt_tokens', '?')} "
         f"out={usage.get('completion_tokens', '?')} "
         f"content={len(content)}ch reason={len(reasoning)}ch "
         f"tool_calls={len(tool_calls)}")
    if content:
        _log(f"[LLM<-] answer: {_preview(content, 300)}")
    for i, tc in enumerate(tool_calls):
        fn = tc.get("function", {})
        _log(f"[LLM<-] tool_call[{i}]: {fn.get('name')}"
             f"({_preview(fn.get('arguments', ''), 150)})")

    return {
        "content": content,
        "reasoning": reasoning,
        "tool_calls": tool_calls,
        "raw": msg,
        "usage": usage,
    }


def check_available():
    try:
        r = requests.get(LMSTUDIO_MODELS_URL, timeout=5)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        return True, r.json()
    except Exception as e:
        return False, str(e)


# ================================================================
# ВАРИАНТ A - интерпретация готовой статистики
# ================================================================

SYSTEM_ANALYST = (
    "Ты инженер-статистик, работающий с измерениями кварцевых резонаторов. "
    "Ты получаешь ТОЛЬКО готовые числа. КАТЕГОРИЧЕСКИ запрещено выдумывать "
    "или досчитывать цифры - используй только те, что даны. "
    "Отвечай по-русски, 3-5 предложений, без рассуждений вслух. "
    "Структура: (1) общий вывод по выходу годных, (2) главный риск/проблема, "
    "(3) конкретная рекомендация, что проверить."
)


def _fmt_stat(stat: dict) -> str:
    if not stat:
        return "нет данных"
    keys = ['Count', 'Out', 'Bad_Count', 'Anomal_count',
            'Max', 'Min', 'Mean', 'Median', 'StDev',
            'Lower_bound', 'Upper_bound']
    out = []
    for k in keys:
        v = stat.get(k)
        if isinstance(v, (int, float)):
            out.append(f"{k}={v:.4g}")
        else:
            out.append(f"{k}={v}")
    return ", ".join(out)


def _fmt_norms(norms: dict, field: str) -> str:
    if not norms:
        return "нормы не заданы"
    nmin = norms.get(field + 'min')
    nmax = norms.get(field + 'max')
    if nmin is None and nmax is None:
        return "нормы не заданы"
    return f"норма: min={nmin}, max={nmax}"


def summarize_msk(msk_name: str, slot_label: str, field: str,
                  stat: dict, norms: dict) -> str:
    user = (
        f"МСК: {msk_name}\n"
        f"Параметр: {slot_label} ({field})\n"
        f"Статистика: {_fmt_stat(stat)}\n"
        f"{_fmt_norms(norms, field)}\n\n"
        "Дай короткий инженерный комментарий."
    )
    try:
        res = _chat([
            {"role": "system", "content": SYSTEM_ANALYST},
            {"role": "user",   "content": user},
        ], temperature=0.15, max_tokens=400)
        return res["content"] or "(пустой ответ)"
    except Exception as e:
        return f"[LLM ошибка] {e}"


# ================================================================
# ВАРИАНТ B - NL-запрос через tool calling
# ================================================================

TOOLS = [
    {"type": "function", "function": {
        "name": "list_msks",
        "description": "Вернуть список МСК, добавленных в набор.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "list_slots",
        "description": "Вернуть список слотов (каналов): "
                       "номер, тип, активность, количество записей.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "list_specs",
        "description": "Найти спецификации по подстроке имени. "
                       "Поле search ОБЯЗАТЕЛЬНО: пустой запрос "
                       "возвращает первые 20 по алфавиту и бесполезен. "
                       "Передавайте подстроку, например '569' или "
                       "'РК569'.",
        "parameters": {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Подстрока для поиска "
                                   "(например 'РК507-98,415')",
                },
            },
            "required": ["search"],
        },
    }},
    {"type": "function", "function": {
        "name": "load_spec",
        "description": "Загрузить спецификацию и последние N МСК для "
                       "неё. Использовать, когда пользователь называет "
                       "спецификацию (вида 'РК507-98,415М-220') и нужно "
                       "получить данные. После загрузки get_stat без "
                       "msk даст агрегат по всем загруженным МСК.",
        "parameters": {
            "type": "object",
            "properties": {
                "spec_name": {
                    "type": "string",
                    "description": "Имя спецификации",
                },
                "last_n": {
                    "type": "integer",
                    "description": "Сколько последних МСК загрузить "
                                   "(0 = без ограничения; по "
                                   "умолчанию 10)",
                },
                "period_days": {
                    "type": "integer",
                    "description": "За сколько дней брать МСК "
                                   "(0 = без фильтра; по "
                                   "умолчанию 30)",
                },
            },
            "required": ["spec_name"],
        },
    }},
    {"type": "function", "function": {
        "name": "get_stat",
        "description": (
            "Статистика (Max/Min/Mean/Median/StDev/Out/Count/"
            "Bad_Count/Anomal_count) по параметру. "
            "СЛОТ задаётся одним из трёх способов (приоритет сверху "
            "вниз): (1) явный slot_name — берётся как есть; "
            "(2) measure_type — 'ПСИ', 'До настройки', "
            "'После настройки', 'После отжига', 'Настройка' — "
            "инструмент найдёт первый слот с этим типом; "
            "(3) НИЧЕГО не передано — берётся PSI-слот "
            "(Measure_Type=6). Именно в PSI Fr/Fs/FL всегда заполнены, "
            "т.к. psidata.F алиасируется во все три колонки. "
            "Поэтому для запросов вида 'FL для МСК X' без явного типа "
            "лучше НЕ передавать ни slot_name, ни measure_type — "
            "запрос уйдёт в PSI и вернёт реальные числа. "
            "Если указаны и slot_name, и measure_type — они должны "
            "соответствовать друг другу. "
            "Поле field — ОДНО значение за вызов. Если нужно два "
            "параметра — сделайте два вызова get_stat."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "description": (
                        "Ровно ОДНО значение из enum. Строка, "
                        "НЕ массив. Пример: \"FL\", а не [\"FL\"]."
                    ),
                    "enum": ["Fr", "Fs", "FL", "R",
                             "C0", "C1", "L1", "Q"],
                },
                "slot_name": {
                    "type": "integer",
                    "description": (
                        "Номер слота (1, 2, 3, ...). Опционально: "
                        "если не указан — слот определяется по "
                        "measure_type, либо берётся PSI-слот."
                    ),
                },
                "measure_type": {
                    "type": "string",
                    "description": (
                        "Тип измерения: 'ПСИ', 'До настройки', "
                        "'После настройки', 'После отжига', "
                        "'Настройка'. Используется, когда slot_name "
                        "не указан."
                    ),
                },
                    "period_days": {
                        "type": "integer",
                        "description": (
                            "За сколько дней брать МСК при автозагрузке "
                            "спецификации. Используй: 7 — 'неделя', 30 — "
                            "'месяц', 90 — '3 месяца', 180 — 'полгода', "
                            "365 — 'год'. 0 = без ограничения. Если пользователь "
                            "сказал 'за 3 месяца' — ОБЯЗАТЕЛЬНО передай 90, "
                            "иначе загрузятся 30 (default)."
                        ),
                    },

                "msk": {
                    "type": "string",
                    "description": "Имя МСК (опционально; если не "
                                   "задано — агрегат по всем "
                                   "загруженным МСК).",
                },
            },
            "required": ["field"],
        },
    }},
    {"type": "function", "function": {
        "name": "get_norms",
        "description": "Вернуть нормы текущей спецификации для всех "
                       "параметров.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "drop_anomalies",
        "description": (
            "Удалить аномальные значения (IQR 1.5x) из данных "
            "слота/МСК. Двухшаговый: сначала confirm=false — только "
            "подсчёт; затем confirm=true — реальное удаление. "
            "ВНИМАНИЕ: confirm=true необратим. "
            "Слот задаётся так же, как в get_stat: явный slot_name "
            "ИЛИ measure_type, ИЛИ (если ничего не указано) "
            "PSI-слот по умолчанию. "
            "Поле field — ОДНО значение за вызов."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "description": (
                        "Ровно ОДНО значение из enum. Строка, "
                        "НЕ массив. Пример: \"FL\", а не [\"FL\"]."
                    ),
                    "enum": ["Fr", "Fs", "FL", "R",
                             "C0", "C1", "L1", "Q"],
                },
                "slot_name": {
                    "type": "integer",
                    "description": ("Номер слота (опционально). "
                                    "Если не указан — слот "
                                    "определяется по measure_type "
                                    "или берётся PSI."),
                },
                "measure_type": {
                    "type": "string",
                    "description": ("Тип измерения: 'ПСИ', "
                                    "'До настройки', "
                                    "'После настройки', "
                                    "'После отжига', 'Настройка'."),
                },
                "msk": {
                    "type": "string",
                    "description": ("Имя МСК (опционально; иначе "
                                    "весь слот)."),
                },
                "confirm": {
                    "type": "boolean",
                    "description": ("false — подсчёт, true — "
                                    "удаление"),
                    "default": False,
                },
            },
            "required": ["field"],
        },
    }},
]


def _tools_description() -> str:
    parts = []
    for t in TOOLS:
        fn = t["function"]
        args = list(fn["parameters"].get("properties", {}).keys())
        parts.append(f"- {fn['name']}: {fn['description']} args={args}")
    return "\n".join(parts)

def _tool_system_prompt(msk_list=None, field=None) -> str:
    ctx = ""
    if msk_list:
        sample = ', '.join(str(m) for m in msk_list[:10])
        extra = f" ... (всего {len(msk_list)})" if len(msk_list) > 10 else ""
        ctx += f"\nЗагруженные МСК: {sample}{extra}"
    else:
        ctx += "\nЗагруженные МСК: ПУСТО (ни одна МСК не добавлена)"
    if field:
        ctx += f"\nТекущий параметр: {field}"

    return (
        "Ты вызываешь инструменты через JSON. Отвечай ТОЛЬКО валидным "
        "JSON-объектом, без markdown, без текста вне JSON.\n"
        + ctx +
        "\n\nФОРМАТЫ:\n"
        "Вызов: {\"tool\": \"<имя>\", \"args\": {<dict>}}\n"
        "Ответ: {\"answer\": \"<текст>\"}\n\n"
        "ПРИМЕРЫ:\n"
        "П: какие МСК?\n"
        "Т: {\"tool\": \"list_msks\", \"args\": {}}\n"
        "П: какие слоты?\n"
        "Т: {\"tool\": \"list_slots\", \"args\": {}}\n"
        "П: найди спецификацию РК507\n"
        "Т: {\"tool\": \"list_specs\", \"args\": {\"search\": "
        "\"РК507\"}}\n"
        "П: загрузи спецификацию РК507-98,415М-220, последние 10 МСК\n"
        "Т: {\"tool\": \"load_spec\", \"args\": {\"spec_name\": "
        "\"РК507-98,415М-220\", \"last_n\": 10}}\n"
        "П: статистика FL в слоте 3\n"
        "Т: {\"tool\": \"get_stat\", \"args\": {\"slot_name\": 3, "
        "\"field\": \"FL\"}}\n"
        "П: нормы\n"
        "Т: {\"tool\": \"get_norms\", \"args\": {}}\n\n"
        "Инструменты:\n" + _tools_description() + "\n\n"
         "КРИТИЧНЫЕ ПРАВИЛА:\n"
        "1. slot_name - целое число (1, 2, 3). Если не указан - 1.\n"
        "2. field - один из: Fr, Fs, FL, R, C0, C1, L1, Q.\n"
        "3. args - всегда dict {ключ: значение}, НЕ массив.\n"
        "4. Параметры даты:\n"
        "   - period_days (default=30) - за сколько дней брать МСК\n"
        "   - last_n (default=0) - макс. число МСК, 0 = без лимита\n"
        "   - 'за месяц' -> period_days=30, last_n=0\n"
        "   - 'последние 5 МСК' -> period_days=0, last_n=5\n"
        "5. НЕ выдумывай параметры: нет 'count', 'period', 'date', "
        "'month'. Их не существует.\n"
        "6. Перед get_stat: если слот неизвестен - list_slots; если "
        "МСК неизвестна - list_msks.\n"
        "7. Не повторяй одинаковые вызовы.\n"
        "8. По-русски.\n\n"
        "СПЕЦИФИКАЦИИ vs МСК:\n"
        "9. Спецификация - НЕ МСК. Либо load_spec, либо передай имя "
        "спецификации в get_stat.msk - автозагрузка сработает.\n"
        "10. Если get_stat вернул 'не найдена' - list_specs.\n"
        "11. После load_spec: get_stat без msk даёт агрегат по всем "
        "загруженным МСК.\n\n"
        "АНОМАЛИИ:\n"
        "12. drop_anomalies - ДВУХШАГОВЫЙ. Сначала confirm=false "
        "(только подсчёт), покажи результат пользователю, спроси "
        "подтверждение. Только после явного согласия - confirm=true.\n"
        "13. confirm=true НЕОБРАТИМ: данные удаляются из текущего "
        "набора. Не вызывай без явного запроса пользователя.\n"
        "14. Если инструмент вернул 'error' и 'hint' - передай "
        "суть обоих в ответе.""15. Если get_stat вернул 'available_fields' — значит слот "
        "НЕ пустой, а просто выбранный параметр в БД пуст. НЕ говори "
        "'МСК не загружены' и НЕ предлагай load_spec — назови реальную "
        "причину и предложи один из 'available_fields'.\n"
        "СЛОТ и ТИП ИЗМЕРЕНИЯ:\n"
        "15. slot_name — НЕобязательный. Если пользователь называет "
        "ТИП измерения ('ПСИ', 'До настройки', 'После отжига', "
        "'Настройка', etc.) — передавай measure_type, а slot_name "
        "оставь пустым. Инструмент сам найдёт слот с этим типом.\n"
        "16. Если пользователь НЕ указал ни тип, ни слот — ничего не "
        "передавай: по умолчанию будет выбран PSI-слот (там FL, Fs, Fr "
        "гарантированно заполнены — psidata.F алиасируется во все три).\n"
        "17. Если slot_name и measure_type заданы вместе — они ДОЛЖНЫ "
        "соответствовать друг другу, иначе инструмент вернёт ошибку.\n"
        "18. Для запросов вида 'FL для РК...': если явно не сказано "
        "'до настройки' / 'после отжига' — это скорее всего PSI, "
        "вызывай measure_type='ПСИ' (или вообще не указывай тип — "
        "пойдёт в PSI-слот по умолчанию).\n"
        "19. slot_name — ТОЛЬКО число (1, 2, 3, ...). Имя МСК "
        "('РК569Б-10М', '26-5105', ...) передаётся в поле msk. "
        "Если пользователь назвал МСК — она идёт в msk, НЕ в "
        "slot_name. Слот при этом либо не указывай (уйдёт в PSI), "
        "либо задай через measure_type.\n"
        "20. field — СТРОКА, а не массив. Пиши \"FL\", не "
        "[\"FL\"]. Если нужно два параметра — сделай два вызова "
        "get_stat.\n"

    )

def _parse_json_block(text: str):
    if not text:
        return None
    text = _clean(text)
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None
def _prompt_based_nl_query(
        user_text: str,
        execute_tool: Callable[[str, dict], dict],
        max_steps: int = MAX_STEPS,
        msk_list=None,
        field=None,
) -> str:
    """Tool calling через JSON-протокол в промпте (для mistral-v0.2).

    Логика одного шага:
      1. Спросить у модели JSON: {"tool": ..., "args": ...} или
         {"answer": "..."}.
      2. Если tool - проверить, не повтор ли; вызвать исполнитель;
         отдать результат обратно модели вместе с tail-подсказкой.
         - tool вернул error+count=0 -> "не выдумывай, скажи нет данных";
         - tool вернул error         -> "исправь аргументы по схеме";
         - tool вернул ok            -> "дай финальный answer".
      3. Если answer - вернуть строку.
      4. Если ни то ни другое - вернуть сырой content.

    Защита:
      * repeat-детектор по (name, args) -> форсирует финальный ответ,
        чтобы модель не жгла 3 шага на один и тот же вызов;
      * приоритет tool над answer (безопаснее взять реальные данные,
        если модель вернула оба поля).
    """
    messages = [
        {"role": "system",
         "content": _tool_system_prompt(msk_list, field)},
        {"role": "user", "content": user_text},
    ]
    seen_calls = set()

    for _step in range(max_steps):
        try:
            res = _chat(messages, temperature=0.0, force_json=True)
        except Exception as e:
            return f"[LLM ошибка] {e}"

        parsed = _parse_json_block(res["content"])
        if parsed is None:
            # модель не выдала JSON - возвращаем как есть
            return res["content"] or "(пустой ответ)"

        if not isinstance(parsed, dict):
            return res["content"] or "(не удалось разобрать ответ)"

        tool_name = parsed.get("tool")
        answer = parsed.get("answer")

        # ---------- вызов инструмента ----------
        if tool_name:
            args = parsed.get("args")
            if args is None:
                args = {}

            try:
                key = (tool_name,
                       json.dumps(args, sort_keys=True, default=str))
            except Exception:
                key = (tool_name, str(args))

            # ---- repeat-детектор ----
            if key in seen_calls:
                _log(f"[LLM!!] repeat {tool_name}({args}) - "
                     f"forcing final answer")
                messages.append({"role": "assistant",
                                 "content": res["content"]})
                messages.append({
                    "role": "user",
                    "content": (
                        "Не повторяй этот вызов. Ответь СЕЙЧАС финальным "
                        "JSON {\"answer\": \"...\"} по уже полученным "
                        "данным, либо сообщи, что ответить невозможно."
                    ),
                })
                try:
                    final = _chat(messages, temperature=0.0,
                                  max_tokens=600, force_json=True)
                    fp = _parse_json_block(final["content"])
                    if fp and "answer" in fp:
                        return str(fp["answer"])
                    return final["content"] or "(нет ответа)"
                except Exception as e:
                    return f"[LLM ошибка] {e}"

            seen_calls.add(key)
            _log(f"[LLM..] call tool {tool_name}({args})")

            # ---- вызов исполнителя ----
            try:
                result = execute_tool(tool_name, args)
            except Exception as e:
                result = {"error": str(e)}

            # ---- классификация результата ----
            is_error = (isinstance(result, dict) and "error" in result)
            is_empty = (isinstance(result, dict)
                        and _safe_count(result) == 0)

            payload = json.dumps(result, ensure_ascii=False,
                                 default=str)[:MAX_TOOL_RESULT_CHARS]

            messages.append({"role": "assistant",
                             "content": res["content"]})

            # ---- tail-подсказка ----
            if is_error and is_empty:
                tail = (
                    "\n\nВНИМАНИЕ: данных нет (count=0). "
                    "НЕ выдумывай числа. Ответь финальным "
                    "{\"answer\": \"Данных нет: <причина>\"} "
                    "или вызови другой инструмент "
                    "(list_slots / list_msks), если не знаешь, "
                    "куда смотреть."
                )
            elif is_error:
                tail = (
                    "\n\nERROR: " + str(result["error"]) + "\n"
                    "Исправь аргументы согласно схеме и повтори, "
                    "или дай финальный ответ "
                    "{\"answer\": \"...\"} с объяснением проблемы."
                )
            else:
                tail = "\n\nДай финальный ответ {\"answer\": \"...\"}."

            messages.append({
                "role": "user",
                "content": f"Результат {tool_name}: {payload}{tail}",
            })
            continue

        # ---------- готовый ответ ----------
        if answer is not None:
            return str(answer)

        # ни tool, ни answer - отдаём сырой content
        return res["content"] or "(не удалось разобрать ответ)"

    return "(достигнут лимит шагов tool calling)"

def _safe_count(result) -> int:
    """Достать count из результата инструмента, не падая на мусоре.

    Возвращает:
      * 0   - если count==0;
      * -1  - если count нет или он не парсится (значит, это не
              «пустой результат», а «просто нет поля count»,
              классифицировать как is_empty нельзя).
    """
    if not isinstance(result, dict):
        return -1
    raw = result.get("count", result.get("Count"))
    if raw is None:
        return -1
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1

def _prompt_based_nl_query_3(
        user_text: str,
        execute_tool: Callable[[str, dict], dict],
        max_steps: int = MAX_STEPS,
        msk_list=None,
        field=None,
) -> str:
    messages = [
        {"role": "system",
         "content": _tool_system_prompt(msk_list, field)},
        {"role": "user", "content": user_text},
    ]
    seen_calls = set()

    for _ in range(max_steps):
        try:
            res = _chat(messages, temperature=0.0, force_json=True)
        except Exception as e:
            return f"[LLM ошибка] {e}"

        parsed = _parse_json_block(res["content"])
        if parsed is None:
            return res["content"] or "(пустой ответ)"

        tool_name = parsed.get("tool") if isinstance(parsed, dict) else None
        answer = parsed.get("answer") if isinstance(parsed, dict) else None

        # приоритет инструменту (безопаснее - берём реальные данные)
        if tool_name:
            args = parsed.get("args") or {}
            try:
                key = (tool_name, json.dumps(args, sort_keys=True,
                                             default=str))
            except Exception:
                key = (tool_name, str(args))

            if key in seen_calls:
                _log(f"[LLM!!] repeat {tool_name}({args}) - forcing "
                     f"final answer")
                messages.append({"role": "assistant",
                                 "content": res["content"]})
                messages.append({
                    "role": "user",
                    "content": (
                        "Не повторяй этот вызов. Ответь СЕЙЧАС финальным "
                        "JSON {\"answer\": \"...\"} по уже полученным "
                        "данным, либо сообщи, что ответить невозможно."
                    ),
                })
                try:
                    final = _chat(messages, temperature=0.0, max_tokens=600,
                                  force_json=True)
                    fp = _parse_json_block(final["content"])
                    if fp and "answer" in fp:
                        return str(fp["answer"])
                    return final["content"] or "(нет ответа)"
                except Exception as e:
                    return f"[LLM ошибка] {e}"

            seen_calls.add(key)
            _log(f"[LLM..] call tool {tool_name}({args})")

            try:
                result = execute_tool(tool_name, args)
            except Exception as e:
                result = {"error": str(e)}

            is_error = (isinstance(result, dict) and "error" in result)
            payload = json.dumps(result, ensure_ascii=False,
                                 default=str)[:MAX_TOOL_RESULT_CHARS]

            messages.append({"role": "assistant",
                             "content": res["content"]})
            if is_error:
                tail = ("\n\nERROR: " + str(result["error"]) +
                        "\nИсправь аргументы согласно схеме и повтори, "
                        "или дай финальный ответ {\"answer\": \"...\"}.")
            else:
                tail = "\n\nДай финальный ответ {\"answer\": \"...\"}."
            messages.append({
                "role": "user",
                "content": f"Результат {tool_name}: {payload}{tail}",
            })
            continue

        if answer is not None:
            return str(answer)

        return res["content"] or "(не удалось разобрать ответ)"

    return "(достигнут лимит шагов tool calling)"


def _native_nl_query(
        user_text: str,
        execute_tool: Callable[[str, dict], dict],
        max_steps: int = MAX_STEPS,
        msk_list=None,
        field=None,
) -> str:
    """Нативный tool calling. Для mistral-v0.2 не используется
    (SUPPORTS_NATIVE_TOOLS=False)."""
    ctx = ""
    if msk_list:
        sample = ', '.join(str(m) for m in msk_list[:10])
        extra = f" ... (всего {len(msk_list)})" if len(msk_list) > 10 else ""
        ctx += f"\nДоступные МСК: {sample}{extra}"
    if field:
        ctx += f"\nТекущий параметр: {field}"

    messages = [
        {"role": "system",
         "content": ("Ты ассистент системы статистики кварцевых резонаторов. "
                     "Используй инструменты, не выдумывай числа, "
                     "отвечай по-русски кратко." + ctx)},
        {"role": "user", "content": user_text},
    ]
    seen_calls = set()

    for _ in range(max_steps):
        try:
            res = _chat(messages, tools=TOOLS)
        except Exception as e:
            return f"[LLM ошибка] {e}"

        if not res["tool_calls"]:
            return res["content"] or "(пустой ответ)"

        messages.append({
            "role": "assistant",
            "content": res["content"],
            "tool_calls": res["tool_calls"],
        })
        for tc in res["tool_calls"]:
            name = tc["function"]["name"]
            raw = tc["function"].get("arguments", "{}")
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                args = {}

            try:
                key = (name, json.dumps(args, sort_keys=True, default=str))
            except Exception:
                key = (name, str(args))

            if key in seen_calls:
                _log(f"[LLM!!] repeat {name}({args}) - skip")
                result = {"error": "repeated call - do not call again"}
            else:
                seen_calls.add(key)
                _log(f"[LLM..] call tool {name}({args})")
                try:
                    result = execute_tool(name, args)
                except Exception as e:
                    result = {"error": str(e)}

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", name),
                "name": name,
                "content": json.dumps(result, ensure_ascii=False,
                                      default=str)[:MAX_TOOL_RESULT_CHARS],
            })

    return "(достигнут лимит шагов tool calling)"


def nl_query(
        user_text: str,
        execute_tool: Callable[[str, dict], dict],
        msk_list=None,
        field=None,
        msk_names=None,
) -> str:
    """Точка входа варианта B.

    Args:
        user_text: вопрос пользователя.
        execute_tool: callable(name, args) -> dict.
        msk_list: список загруженных МСК (для контекста и валидации).
        field: текущий выбранный параметр в UI (например 'Fr').
        msk_names: алиас msk_list (обратная совместимость).
    """
    if msk_names is not None and msk_list is None:
        msk_list = msk_names

    if SUPPORTS_NATIVE_TOOLS:
        return _native_nl_query(user_text, execute_tool,
                                msk_list=msk_list, field=field)
    return _prompt_based_nl_query(user_text, execute_tool,
                                  msk_list=msk_list, field=field)


# ================================================================
# PDF-отчёт
# ================================================================

_FONT_CANDIDATES = [
    "C:\\Windows\\Fonts\\arial.ttf",
    "C:\\Windows\\Fonts\\calibri.ttf",
    "C:\\Windows\\Fonts\\segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
def save_report_pdf(text, path, plots=None, table=None):
    """Сохранить PDF: текст -> таблица(ы) -> графики.

    table может быть:
      * None          — без таблиц;
      * dict          — одна таблица;
      * list[dict]    — несколько таблиц подряд (например, сводная
                        + по каждой МСК).
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import (SimpleDocTemplate, Paragraph,
                                        Spacer, Image, Table, TableStyle)
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return False, "reportlab не установлен (pip install reportlab)"

    font_path = next((p for p in _FONT_CANDIDATES
                      if os.path.exists(p)), None)
    if not font_path:
        return False, "не найден TTF-шрифт с кириллицей"

    try:
        pdfmetrics.registerFont(TTFont("ReportFont", font_path))
    except Exception as e:
        return False, f"ошибка шрифта: {e}"

    try:
        import io

        doc = SimpleDocTemplate(
            path, pagesize=A4,
            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        )

        styles = getSampleStyleSheet()
        body_style = ParagraphStyle(
            'BodyRU', parent=styles['Normal'],
            fontName='ReportFont', fontSize=9, leading=12)
        h_style = ParagraphStyle(
            'HRU', parent=styles['Heading2'],
            fontName='ReportFont', fontSize=11, leading=14,
            spaceBefore=4, spaceAfter=4)

        def _esc(s):
            return (str(s).replace("&", "&amp;")
                    .replace("<", "&lt;").replace(">", "&gt;"))

        story = []

        # ---------- текст ----------
        for raw in (text or "").split("\n"):
            if not raw.strip():
                story.append(Spacer(1, 4))
                continue
            if raw.startswith("## "):
                story.append(Paragraph(_esc(raw[3:]), h_style))
            elif raw.startswith("# "):
                story.append(Paragraph(_esc(raw[2:]), h_style))
            else:
                story.append(Paragraph(_esc(raw), body_style))

        # ---------- таблицы: поддержка dict и list[dict] ----------
        if isinstance(table, dict):
            tables_iter = [table]
        elif isinstance(table, list):
            tables_iter = [t for t in table if isinstance(t, dict)]
        else:
            tables_iter = []

        for tbl in tables_iter:
            if not tbl or not tbl.get('rows'):
                continue

            if tbl.get('title'):
                story.append(Spacer(1, 8))
                story.append(Paragraph(_esc(tbl['title']), h_style))

            headers = tbl.get('headers') or []
            rows = tbl.get('rows') or []
            data = []
            if headers:
                data.append([Paragraph(_esc(h), body_style) for h in headers])
            for r in rows:
                data.append([Paragraph(_esc(c), body_style) for c in r])

            avail = A4[0] - 3 * cm
            col_widths = tbl.get('col_widths')
            if not col_widths:
                ncol = len(data[0]) if data else 1
                col_widths = [avail / ncol] * ncol

            t = Table(data, colWidths=col_widths,
                      repeatRows=1 if headers else 0)

            style_cmds = [
                ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]
            if headers:
                style_cmds.append(
                    ('BACKGROUND', (0, 0), (-1, 0),
                     colors.HexColor('#e8e8e8')))
            t.setStyle(TableStyle(style_cmds))
            story.append(t)
            story.append(Spacer(1, 8))

        # ---------- графики ----------
        avail_w = A4[0] - 3 * cm
        for fig in (plots or []):
            try:
                buf = io.BytesIO()
                fig.savefig(buf, format='png', dpi=200)
                buf.seek(0)
                from reportlab.lib.utils import ImageReader
                img = ImageReader(buf)
                iw, ih = img.getSize()
                scale = avail_w / iw
                story.append(Spacer(1, 6))
                story.append(Image(buf, width=iw * scale,
                                   height=ih * scale))
                story.append(Spacer(1, 6))
            except Exception as e:
                _log(f'[save_report_pdf] figure: {e}')

        doc.build(story)
        return True, path
    except Exception as e:
        return False, str(e)

def save_report_pdf_44(text, path, plots=None, table=None):
    """Сохранить PDF: текст -> таблица -> графики.
    ...
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import (SimpleDocTemplate, Paragraph,
                                        Spacer, Image, Table, TableStyle)
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return False, "reportlab не установлен (pip install reportlab)"

    font_path = next((p for p in _FONT_CANDIDATES
                      if os.path.exists(p)), None)
    if not font_path:
        return False, "не найден TTF-шрифт с кириллицей"

    try:
        pdfmetrics.registerFont(TTFont("ReportFont", font_path))
    except Exception as e:
        return False, f"ошибка шрифта: {e}"

    try:
        import io

        doc = SimpleDocTemplate(
            path, pagesize=A4,
            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        )

        styles = getSampleStyleSheet()
        body_style = ParagraphStyle(
            'BodyRU', parent=styles['Normal'],
            fontName='ReportFont', fontSize=9, leading=12)
        h_style = ParagraphStyle(
            'HRU', parent=styles['Heading2'],
            fontName='ReportFont', fontSize=11, leading=14,
            spaceBefore=4, spaceAfter=4)

        def _esc(s):
            return (str(s).replace("&", "&amp;")
                    .replace("<", "&lt;").replace(">", "&gt;"))

        story = []

        # ---------- текст ----------
        for raw in (text or "").split("\n"):
            if not raw.strip():
                story.append(Spacer(1, 4))
                continue
            if raw.startswith("## "):
                story.append(Paragraph(_esc(raw[3:]), h_style))
            elif raw.startswith("# "):
                story.append(Paragraph(_esc(raw[2:]), h_style))
            else:
                story.append(Paragraph(_esc(raw), body_style))

        # ---------- таблица ----------
        if table and table.get('rows'):
            if table.get('title'):
                story.append(Spacer(1, 8))
                story.append(Paragraph(_esc(table['title']), h_style))

            headers = table.get('headers') or []
            rows = table.get('rows') or []
            data = []
            if headers:
                data.append([Paragraph(_esc(h), body_style) for h in headers])
            for r in rows:
                data.append([Paragraph(_esc(c), body_style) for c in r])

            avail = A4[0] - 3 * cm
            col_widths = table.get('col_widths')
            if not col_widths:
                ncol = len(data[0]) if data else 1
                col_widths = [avail / ncol] * ncol

            t = Table(data, colWidths=col_widths,
                      repeatRows=1 if headers else 0)

            style_cmds = [
                ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]
            if headers:
                style_cmds.append(
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8e8e8')))
            t.setStyle(TableStyle(style_cmds))
            story.append(t)
            story.append(Spacer(1, 8))

        # ---------- графики ----------
        avail_w = A4[0] - 3 * cm
        for fig in (plots or []):
            try:
                buf = io.BytesIO()
                fig.savefig(buf, format='png', dpi=200)
                buf.seek(0)
                from reportlab.lib.utils import ImageReader
                img = ImageReader(buf)
                iw, ih = img.getSize()
                scale = avail_w / iw
                story.append(Spacer(1, 6))
                story.append(Image(buf, width=iw * scale,
                                   height=ih * scale))
                story.append(Spacer(1, 6))
            except Exception as e:
                _log(f'[save_report_pdf] figure: {e}')

        doc.build(story)
        return True, path
    except Exception as e:
        return False, str(e)
def save_report_pdf_19(text, path, plots=None, table=None):
    """Сохранить PDF: текст -> таблица -> графики.

    Args:
        text:  текст отчёта.
        path:  путь к PDF.
        plots: list[matplotlib.figure.Figure].
        table: dict | None:
            {
              'title':   'Таблица 1. Статистика',
              'headers': ['Слот', 'Поле', 'N', ...],
              'rows':    [['1', 'FL', '81', ...], ...],
              'col_widths': None | [cm, cm, ...],
            }
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import (SimpleDocTemplate, Paragraph,
                                        Spacer, Image, Table, TableStyle)
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return False, "reportlab не установлен (pip install reportlab)"

    font_path = next((p for p in _FONT_CANDIDATES
                      if os.path.exists(p)), None)
    if not font_path:
        return False, "не найден TTF-шрифт с кириллицей"

    try:
        pdfmetrics.registerFont(TTFont("ReportFont", font_path))
    except Exception as e:
        return False, f"ошибка шрифта: {e}"

    try:
        import io

        doc = SimpleDocTemplate(
            path, pagesize=A4,
            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        )

        styles = getSampleStyleSheet()
        body_style = ParagraphStyle(
            'BodyRU', parent=styles['Normal'],
            fontName='ReportFont', fontSize=9, leading=12)
        h_style = ParagraphStyle(
            'HRU', parent=styles['Heading2'],
            fontName='ReportFont', fontSize=11, leading=14,
            spaceBefore=4, spaceAfter=4)

        def _esc(s):
            return (str(s).replace("&", "&amp;")
                    .replace("<", "&lt;").replace(">", "&gt;"))

        story = []

        # ---------- текст ----------
        for raw in (text or "").split("\n"):
            if not raw.strip():
                story.append(Spacer(1, 4))
                continue
            if raw.startswith("## "):
                story.append(Paragraph(_esc(raw[3:]), h_style))
            elif raw.startswith("# "):
                story.append(Paragraph(_esc(raw[2:]), h_style))
            else:
                story.append(Paragraph(_esc(raw), body_style))

        # ---------- таблица ----------
        if table and table.get('rows'):
            if table.get('title'):
                story.append(Spacer(1, 8))
                story.append(Paragraph(_esc(table['title']), h_style))

            headers = table.get('headers') or []
            rows = table.get('rows') or []
            data = []
            if headers:
                data.append([Paragraph(_esc(h), body_style) for h in headers])
            for r in rows:
                data.append([Paragraph(_esc(c), body_style) for c in r])

            avail = A4[0] - 3 * cm
            col_widths = table.get('col_widths')
            if not col_widths:
                ncol = len(data[0]) if data else 1
                col_widths = [avail / ncol] * ncol

            t = Table(data, colWidths=col_widths,
                      repeatRows=1 if headers else 0)

            style_cmds = [
                ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]
            if headers:
                style_cmds.append(
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8e8e8')))
            t.setStyle(TableStyle(style_cmds))
            story.append(t)
            story.append(Spacer(1, 8))

        # ---------- графики ----------
        avail_w = A4[0] - 3 * cm
        for fig in (plots or []):
            try:
                buf = io.BytesIO()
                fig.savefig(buf, format='png', dpi=200)
                buf.seek(0)
                from reportlab.lib.utils import ImageReader
                img = ImageReader(buf)
                iw, ih = img.getSize()
                scale = avail_w / iw
                story.append(Spacer(1, 6))
                story.append(Image(buf, width=iw * scale,
                                   height=ih * scale))
                story.append(Spacer(1, 6))
            except Exception as e:
                _log(f'[save_report_pdf] figure: {e}')

        doc.build(story)
        return True, path
    except Exception as e:
        return False, str(e)

def save_report_pdf_1(text: str, path: str, plots=None):
    """Сохранить текст + (опционально) список matplotlib.Figure в PDF.

    Args:
        text:  текст отчёта (может быть пустым, если plots заданы).
        path:  путь к PDF.
        plots: list[matplotlib.figure.Figure] - графики после текста.

    Возвращает (ok: bool, path_or_error).
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib.utils import ImageReader
        from reportlab.lib.units import cm
    except ImportError:
        return False, "reportlab не установлен (pip install reportlab)"

    font_path = next((p for p in _FONT_CANDIDATES
                      if os.path.exists(p)), None)
    if not font_path:
        return False, "не найден TTF-шрифт с кириллицей"

    try:
        pdfmetrics.registerFont(TTFont("ReportFont", font_path))
    except Exception as e:
        return False, f"ошибка регистрации шрифта: {e}"

    try:
        import io

        c = canvas.Canvas(path, pagesize=A4)
        W, H = A4
        margin = 1.5 * cm
        fs = 9
        lh = 12
        max_w = W - 2 * margin
        c.setFont("ReportFont", fs)
        y = H - margin

        def _wrap(line):
            words = line.split(" ")
            out, cur = [], ""
            for w in words:
                test = (cur + " " + w) if cur else w
                if c.stringWidth(test, "ReportFont", fs) <= max_w:
                    cur = test
                else:
                    if cur:
                        out.append(cur)
                    cur = w
            if cur:
                out.append(cur)
            return out or [""]

        for raw in (text or "").split("\n"):
            for line in _wrap(raw):
                c.drawString(margin, y, line)
                y -= lh
                if y < margin:
                    c.showPage()
                    c.setFont("ReportFont", fs)
                    y = H - margin

        for fig in (plots or []):
            try:
                buf = io.BytesIO()
                fig.savefig(buf, format='png', dpi=200)
                buf.seek(0)
                img = ImageReader(buf)
                iw, ih = img.getSize()
                avail_w = W - 2 * margin
                scale = avail_w / iw
                draw_w = iw * scale
                draw_h = ih * scale
                if y < margin + draw_h:
                    c.showPage()
                    c.setFont("ReportFont", fs)
                    y = H - margin
                y_img = y - draw_h
                c.drawImage(img, margin, y_img,
                            width=draw_w, height=draw_h,
                            preserveAspectRatio=True, mask='auto')
                y = y_img - 0.5 * cm
                if y < margin:
                    c.showPage()
                    c.setFont("ReportFont", fs)
                    y = H - margin
            except Exception as e:
                _log(f'[save_report_pdf] figure: {e}')

        c.save()
        return True, path
    except Exception as e:
        return False, str(e)

def save_report_pdf_1(text: str, path: str):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib.units import cm
    except ImportError:
        return False, "reportlab не установлен (pip install reportlab)"

    font_path = next((p for p in _FONT_CANDIDATES
                      if os.path.exists(p)), None)
    if not font_path:
        return False, "не найден TTF-шрифт с кириллицей"

    try:
        pdfmetrics.registerFont(TTFont("ReportFont", font_path))
    except Exception as e:
        return False, f"ошибка регистрации шрифта: {e}"

    try:
        c = canvas.Canvas(path, pagesize=A4)
        W, H = A4
        margin = 1.5 * cm
        fs = 9
        lh = 12
        max_w = W - 2 * margin
        c.setFont("ReportFont", fs)
        y = H - margin

        def _wrap(line):
            words = line.split(" ")
            out, cur = [], ""
            for w in words:
                test = (cur + " " + w) if cur else w
                if c.stringWidth(test, "ReportFont", fs) <= max_w:
                    cur = test
                else:
                    if cur:
                        out.append(cur)
                    cur = w
            if cur:
                out.append(cur)
            return out or [""]

        for raw in text.split("\n"):
            for line in _wrap(raw):
                c.drawString(margin, y, line)
                y -= lh
                if y < margin:
                    c.showPage()
                    c.setFont("ReportFont", fs)
                    y = H - margin
        c.save()
        return True, path
    except Exception as e:
        return False, str(e)

# ================================================================
# Научный стиль matplotlib + построение графика статистики
# ================================================================

_MPL_LOCK = threading.Lock()


def _setup_mpl_style():
    """Настроить matplotlib в стиле научной публикации."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception as e:
        _log(f'[LLM] matplotlib недоступен: {e}')
        return False

    with _MPL_LOCK:
        plt.rcParams.update({
            'font.family': 'serif',
            'font.serif': ['DejaVu Serif',
                           'Times New Roman', 'Times'],
            'font.size': 9,
            'axes.linewidth': 0.8,
            'axes.labelsize': 10,
            'axes.titlesize': 10,
            'axes.grid': True,
            'grid.color': '0.85',
            'grid.linewidth': 0.4,
            'grid.linestyle': '-',
            'xtick.labelsize': 8,
            'ytick.labelsize': 8,
            'legend.fontsize': 7,
            'figure.dpi': 150,
            'savefig.dpi': 200,
            'savefig.bbox': 'tight',
            'lines.linewidth': 1.0,
        })
    return True


def _make_stat_plot(slot, field, clear, msk, stat, title):
    """Построить график распределения. Возвращает matplotlib.Figure | None.

    Компоненты:
      * гистограмма плотности;
      * KDE-кривая;
      * вертикальные линии среднего/медианы;
      * затенённая зона ±1σ;
      * вертикальные линии SPC-норм (пунктир);
      * плашка с N / выход годных / брак / аномалии.
    """
    if not _setup_mpl_style():
        return None

    try:
        import numpy as np
        import pandas as pd
        import matplotlib.pyplot as plt

        df = Statistik.Data.Data.get_data(slot)
        if df is None or df.empty or field not in df.columns:
            return None

        # ---- фильтрация по МСК ----
        if msk is not None:
            msk_list = Statistik.Data.Data.get_msk_list()
            if msk in msk_list:
                msk_slot = msk_list[msk]
                mrow = msk_slot[msk_slot['Name'] == slot]
                if not mrow.empty:
                    try:
                        mid = int(mrow['Mes_ID'].iloc[0])
                    except Exception:
                        mid = 0
                    if mid != 0 and 'Measure_ID' in df.columns:
                        df = df[df['Measure_ID'] == mid]
                    elif 'MSK' in df.columns:
                        # Подстрочный поиск — см. get_pdf в Operations.py
                        mask = df['MSK'].astype(str).str.contains(
                            str(msk), na=False, case=False,
                            regex=False)
                        df = df[mask]

        # ---- значения ----
        vals = pd.to_numeric(df[field], errors='coerce').dropna()
        vals = vals[vals < 1e12]

        if clear and len(vals) > 2:
            Q1 = vals.quantile(0.25)
            Q3 = vals.quantile(0.75)
            IQR = Q3 - Q1
            vals = vals[(vals >= Q1 - 1.5 * IQR) &
                        (vals <= Q3 + 1.5 * IQR)]

        if len(vals) < 3:
            return None

        with _MPL_LOCK:
            fig, ax = plt.subplots(figsize=(6.5, 3.4))

            # гистограмма
            ax.hist(vals, bins='auto', density=True, alpha=0.25,
                    color='0.55', edgecolor='0.35', linewidth=0.5,
                    label='Гистограмма')

            # KDE
            try:
                from scipy.stats import gaussian_kde
                if vals.nunique() >= 2:
                    kde = gaussian_kde(vals)
                    xs = np.linspace(vals.min(), vals.max(), 500)
                    ax.plot(xs, kde(xs), 'k-', linewidth=1.2,
                            label='KDE')
            except Exception:
                pass

            mean = float(vals.mean())
            median = float(vals.median())
            std = float(vals.std())

            ax.axvline(mean, color='C0', linestyle='-', linewidth=1.0,
                       label=f'Среднее = {mean:.4g}')
            ax.axvline(median, color='C1', linestyle='--', linewidth=1.0,
                       label=f'Медиана = {median:.4g}')
            if std > 0:
                ax.axvspan(mean - std, mean + std, color='C0',
                           alpha=0.08, label=f'±1σ = ±{std:.3g}')

            norms = Statistik.Data.Data.get_spc_norm(field) or {}
            for nlabel, key in (('Норма сверху', field + 'max'),
                                ('Норма снизу', field + 'min')):
                raw = norms.get(key)
                if raw is None:
                    continue
                try:
                    nv = float(raw)
                    ax.axvline(nv, color='C3', linestyle=':',
                               linewidth=1.2,
                               label=f'{nlabel} = {nv:.4g}')
                except (TypeError, ValueError):
                    pass

            n = int(stat.get('Count', 0) or 0)
            out = float(stat.get('Out', 0) or 0)
            bad = int(stat.get('Bad_Count', 0) or 0)
            anomal = int(stat.get('Anomal_count', 0) or 0)
            box_text = (f'N = {n}\n'
                        f'Выход годных = {out:.1f}%\n'
                        f'Брак = {bad}\n'
                        f'Аномалий = {anomal}')
            ax.text(0.985, 0.97, box_text, transform=ax.transAxes,
                    va='top', ha='right', fontsize=7.5,
                    bbox=dict(boxstyle='round,pad=0.4',
                              facecolor='white', edgecolor='0.6',
                              linewidth=0.5))

            ax.set_xlabel(field)
            ax.set_ylabel('Плотность вероятности')
            ax.set_title(title)
            ax.legend(loc='upper left', fontsize=7, framealpha=0.9)
            for spine in ax.spines.values():
                spine.set_linewidth(0.7)
            fig.tight_layout()
            return fig
    except Exception as e:
        _log(f'[_make_stat_plot] {e}')
        return None


def close_figures(plots):
    """Закрыть matplotlib-фигуры, освободить память."""
    if not plots:
        return
    try:
        import matplotlib.pyplot as plt
        for f in plots:
            try:
                plt.close(f)
            except Exception:
                pass
    except Exception:
        pass


def open_file(path):
    """Открыть файл системным viewer'ом."""
    try:
        import sys
        import subprocess
        abspath = os.path.abspath(path)
        if sys.platform.startswith('win'):
            os.startfile(abspath)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', abspath])
        else:
            subprocess.Popen(['xdg-open', abspath])
        return True
    except Exception as e:
        _log(f'[open_file] {e}')
        return False

# ================================================================
# Async-воркер для DearPyGui
# ================================================================

class AsyncTask:
    def __init__(self):
        self._q: "queue.Queue" = queue.Queue()

    def submit(self, fn, *args, **kwargs):
        def _run():
            try:
                self._q.put(("ok", fn(*args, **kwargs)))
            except Exception as e:
                self._q.put(("err", str(e)))
        threading.Thread(target=_run, daemon=True).start()

    def poll(self):
        try:
            return self._q.get_nowait()
        except queue.Empty:
            return None