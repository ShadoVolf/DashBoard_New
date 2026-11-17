"""LLM-интеграция: ассистент (NL-запросы) и генератор PDF-отчётов."""

import os
import queue
from datetime import datetime

import pandas as pd
import dearpygui.dearpygui as dpg

import Statistik.Data
import Statistik.LLM as LLM
from Statistik.Operations import (
    get_pdf,
    get_msk,
    load_data,
    get_spc_norms,
    get_resonator_nom_list,
)

from .dashboard_helpers import show_message


def _log(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass

# --- папка для отчётов (в корне проекта) ---
_REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'Отчеты',
)


def _ensure_reports_dir() -> str:
    try:
        os.makedirs(_REPORTS_DIR, exist_ok=True)
        return _REPORTS_DIR
    except Exception as e:
        _log(f'[_ensure_reports_dir] {e}')
        return '.'


def _report_path(filename: str) -> str:
    """Полный путь к файлу отчёта в папке «Отчеты»."""
    return os.path.join(_ensure_reports_dir(), filename)
# ===========================================================================
# Контекст последнего NL-запроса (для сбора графиков)
# ===========================================================================
_LAST_REPORT_CONTEXT = {'plots': [], 'items': [], 'field': None}
# ===========================================================================
# Async-состояние
# ===========================================================================
_ASSISTANT_TASK = LLM.AsyncTask()
_ASSISTANT_BUSY = False

_REPORT_TASK = LLM.AsyncTask()
_REPORT_BUSY = False
_REPORT_CANCEL = False
_REPORT_PROGRESS: "queue.Queue" = queue.Queue()


# ===========================================================================
# Окно ассистента
# ===========================================================================
# ===========================================================================
# Автозагрузка по спецификации (работа с БД, без dpg - фоновый поток)
# ===========================================================================
# в dashboard_llm.py, рядом с _find_specs

# Кириллические буквы, визуально совпадающие с латинскими
_HOMOGLYPHS = str.maketrans(
    'авекмнорстухАВЕКМНОРСТУХ',
    'abekmhopctyxABEKMHOPCTYX',
)


def _norm_spec_name(s: str) -> str:
    """Нормализация имени спецификации для fuzzy-поиска.

    * кириллица → латиница для гомоглифов (М/М, К/K, ...);
    * убрать пробелы, дефисы, подчёркивания;
    * запятая → точка (десятичный разделитель плавает).
    """
    s = str(s).translate(_HOMOGLYPHS)
    return (s.lower()
             .replace(' ', '')
             .replace('-', '')
             .replace('_', '')
             .replace(',', '.'))


def _find_spec(spec_name):
    if not spec_name:
        return None
    try:
        all_specs = get_resonator_nom_list()
    except Exception as e:
        print(f'[_find_spec] {e}')
        return None

    if spec_name in all_specs:
        return spec_name

    nq = _norm_spec_name(spec_name)
    for s in all_specs:
        if _norm_spec_name(s) == nq:
            return s

    # substring (Cyr/Lat уже нормализованы — 'РК569Б-10M' == 'РК569Б-10М')
    q_low = _norm_spec_name(spec_name)
    for s in all_specs:
        s_low = _norm_spec_name(s)
        if q_low in s_low or s_low in q_low:
            return s
    return None

def _find_specs(search_text, limit=20):
    try:
        all_specs = get_resonator_nom_list()
    except Exception as e:
        print(f'[_find_specs] {e}')
        return []
    if not search_text:
        return list(all_specs)[:limit]
    q = _norm_spec_name(search_text)
    matches = [s for s in all_specs if q in _norm_spec_name(s)]
    return matches[:limit]


def _auto_load_spec(spec_name, last_n=0, period_days=30):
    """Загрузить спецификацию и её МСК за период.

    Возвращает:
      {spec, loaded: [{msk, status}], errors: [], error: str|None,
       used_period_days, used_last_n, msk_dates: {msk: 'YYYY-MM-DD ...'}}
    """
    result = {
        "spec": spec_name,
        "loaded": [],
        "errors": [],
        "used_period_days": period_days,
        "used_last_n": last_n,
        "msk_dates": {},
    }

    try:
        msk_df = get_msk(spec_name)
    except Exception as e:
        result["error"] = f"Ошибка БД: {e}"
        return result

    if msk_df is None or msk_df.empty:
        result["error"] = f"Спецификация {spec_name!r} не найдена"
        return result

    try:
        get_spc_norms(spec_name)
    except Exception as e:
        result["errors"].append(f"нормы: {e}")

    # сортировка по дате запуска
    try:
        if 'дата запуска' in msk_df.columns:
            msk_df = msk_df.copy()
            msk_df['_dt'] = pd.to_datetime(msk_df['дата запуска'],
                                           errors='coerce')
            msk_df = msk_df.sort_values('_dt', ascending=False,
                                        na_position='last')
    except Exception as e:
        result["errors"].append(f"сортировка: {e}")

    try:
        period_days = int(period_days)
    except (TypeError, ValueError):
        period_days = 30
    try:
        last_n = int(last_n)
    except (TypeError, ValueError):
        last_n = 0

    # фильтр по периоду
    if period_days > 0 and '_dt' in msk_df.columns:
        try:
            from datetime import datetime as _dt_now, timedelta
            cutoff = _dt_now.now() - timedelta(days=period_days)
            before = len(msk_df)
            filtered = msk_df[msk_df['_dt'] >= cutoff]
            if filtered.empty:
                _log(f'[_auto_load_spec] за {period_days} дн. нет данных, '
                     f'fallback на последние 10')
                msk_df = msk_df.head(10)
            else:
                msk_df = filtered
            _log(f'[_auto_load_spec] период {period_days} дн.: '
                 f'{before} -> {len(msk_df)}')
        except Exception as e:
            result["errors"].append(f"фильтр по дате: {e}")

    if last_n > 0:
        msk_df = msk_df.head(last_n)
        result["used_last_n"] = last_n
    else:
        result["used_last_n"] = 0

    if msk_df.empty:
        result["error"] = f"Нет МСК для {spec_name!r} в выбранном периоде"
        return result

    # загрузка
    active_slot_list = Statistik.Data.Data.get_active_data()
    for _, row in msk_df.iterrows():
        msk = str(row.get('мскРеал', row.get('мск', ''))).strip()
        if not msk:
            continue

        raw_date = row.get('дата запуска') if 'дата запуска' in row else None
        try:
            if raw_date is not None and pd.notna(raw_date):
                result["msk_dates"][msk] = str(raw_date)
        except Exception:
            pass

        if msk in Statistik.Data.Data.get_msk_list():
            result["loaded"].append({"msk": msk, "status": "already"})
            continue
        try:
            current_slot_list = active_slot_list.copy()
            current_slot_list['Mes_ID'] = 0
            current_slot_list['Use'] = True
            load_data(msk, current_slot_list)
            result["loaded"].append({"msk": msk, "status": "loaded"})
        except Exception as e:
            result["loaded"].append({"msk": msk, "status": "error",
                                     "reason": str(e)})

    return result


# ===========================================================================
# Обновление UI после NL-запроса (главный поток)
# ===========================================================================
def _refresh_ui_after_llm(dpg_):
    """Перерисовать таблицы/графики - LLM могла загрузить данные."""
    try:
        from .dashboard_slots import (repaint_signal_window,
                                      repaint_action_window)
        from .dashboard_results import update_result, update_msk_result
    except ImportError as e:
        print(f'[_refresh_ui_after_llm] import: {e}')
        return

    try:
        if dpg_.does_item_exist('view_msk'):
            repaint_signal_window(None, None, dpg_)
        if dpg_.does_item_exist('actions'):
            repaint_action_window(None, None, dpg_)
        if dpg_.does_item_exist('result_table'):
            update_result(dpg_)
        if dpg_.does_item_exist('result_msk_table'):
            update_msk_result(dpg_)
    except Exception as e:
        print(f'[_refresh_ui_after_llm] {e}')
def _on_provider_changed(sender, data, dpg_):
    """Переключение активной модели LLM по выбору пользователя."""
    keys = LLM.get_provider_keys()
    label_to_key = {LLM.get_provider_label(k): k for k in keys}
    key = label_to_key.get(data)
    if not key:
        return
    if LLM.set_provider(key):
        if dpg_.does_item_exist('llm_active_model_text'):
            dpg_.set_value('llm_active_model_text',
                           LLM.get_active_model_name())
        if dpg_.does_item_exist('llm_status_text'):
            dpg_.set_value('llm_status_text', '')

def create_assistant_window(dpg_, pos=None, size=None):
    """Создать/показать/переместить окно ассистента.

    pos, size = None → раскладка DashBoard (rmsk-ячейка, справа от
        таблицы результатов) — тот путь, по которому приходит вызов
        из create_main_windows().
    pos, size заданы → явная геометрия (из пакета Assistant: слева,
        26 %×80 %, под окном «Данные пользователя»).
    """
    # ---------- 1. Геометрия ----------
    from .dashboard_helpers import _layout
    L = _layout()

    if pos is not None and size is not None:
        asst_x, asst_y = pos
        asst_w, asst_h = size
    else:
        asst_x = L.get('asst_x', 400)
        asst_y = L.get('rmsk_y', 80)
        asst_w = max(500, L.get('asst_w', 500))
        asst_h = L.get('rmsk_h', 373)

    INPUT_H, BTN_ROW, SEP_H, CHROME_H = 28, 30, 8, 28
    BOTTOM_RESERVED = SEP_H + INPUT_H + BTN_ROW + CHROME_H
    MIN_WINDOW_H = BOTTOM_RESERVED + 140
    if asst_h < MIN_WINDOW_H:
        asst_h = MIN_WINDOW_H

    # ---------- 2. Окно уже создано: показать + переместить ----------
    if dpg_.does_item_exist('assistant'):
        try:
            dpg_.configure_item(
                'assistant',
                show=True,
                pos=(asst_x, asst_y),
                width=asst_w,
                height=asst_h,
            )
        except Exception:
            try:
                dpg_.configure_item('assistant', show=True)
            except Exception:
                pass
        if dpg_.does_item_exist('result_msk_window'):
            try:
                dpg_.configure_item('result_msk_window', show=False)
            except Exception:
                pass
        return

    # ---------- 3. Создание ----------
    with dpg_.window(
            label="Ассистент (LLM)",
            width=asst_w, height=asst_h,
            pos=(asst_x, asst_y),
            tag='assistant',
            min_size=(420, MIN_WINDOW_H),
            on_close=lambda: dpg_.configure_item('assistant',
                                                 show=False)):

        # ---- строка 1: выбор модели ----
        with dpg_.group(horizontal=True):
            dpg_.add_text("Модель:", color=(170, 170, 170))
            keys = LLM.get_provider_keys()
            labels = [LLM.get_provider_label(k) for k in keys]
            dpg_.add_combo(labels, tag='llm_provider_combo',
                           default_value=LLM.get_provider_label(
                               LLM.get_active_provider()),
                           width=300,
                           callback=_on_provider_changed, user_data=dpg_)
            dpg_.add_button(label="Проверить", callback=check_llm,
                            user_data=dpg_, tag='llm_check_btn')
            dpg_.add_text("", tag='llm_status_text',
                          color=(200, 200, 200))

        # ---- строка 2: активная модель ----
        with dpg_.group(horizontal=True):
            dpg_.add_text("Активная:", color=(170, 170, 170))
            dpg_.add_text(LLM.get_active_model_name(),
                          tag='llm_active_model_text',
                          color=(200, 220, 255))

        dpg_.add_separator()

        # ---- лог ----
        with dpg_.child_window(tag='assistant_log',
                               width=-1, height=-BOTTOM_RESERVED):
            dpg_.add_text(
                "Задайте вопрос. Примеры:\n"
                "  - \"Какие МСК добавлены?\"\n"
                "  - \"Покажи статистику по Fr в слоте 1\"\n"
                "  - \"Выход годных по Q в слоте 2 для МСК <имя>\"",
                color=(150, 150, 150))

        dpg_.add_separator()

        dpg_.add_input_text(
            tag='assistant_input', width=-1,
            on_enter=True,
            callback=run_nl_query, user_data=dpg_,
            hint='Ваш вопрос... (Enter - отправить)',
        )

        with dpg_.group(horizontal=True):
            dpg_.add_button(label='Спросить', tag='assistant_ask_btn',
                            callback=run_nl_query, user_data=dpg_)
            dpg_.add_button(label='Очистить лог',
                            callback=clear_assistant_log, user_data=dpg_)
            dpg_.add_text("", tag='assistant_status',
                          color=(255, 220, 150))
def _clear_assistant_input(dpg_):
    """Очистить поле ввода и вернуть в него фокус."""
    try:
        if dpg_.does_item_exist('assistant_input'):
            dpg_.set_value('assistant_input', '')
            try:
                dpg_.focus_item('assistant_input')
            except Exception:
                pass
    except Exception:
        pass




def show_assistant_window(sender, data, dpg_):
    create_assistant_window(dpg_)


def check_llm(sender, data, dpg_):
    if not dpg_.does_item_exist('llm_status_text'):
        return
    try:
        ok, info = LLM.check_available()
        if ok:
            n = len(info.get('data', []))
            dpg_.set_value('llm_status_text',
                           f'OK: соединение, моделей: {n}')
        else:
            dpg_.set_value('llm_status_text',
                           f'ERR: {str(info)[:80]}')
    except Exception as e:
        dpg_.set_value('llm_status_text', f'ERR: {e}')

def _append_assistant_log(dpg_, text, color=None):
    if not dpg_.does_item_exist('assistant_log'):
        _log(f'[_append_assistant_log] assistant_log MISSING, '
             f'text dropped: {str(text)[:80]}')
        return
    kw = {'wrap': 660}
    if color is not None:
        kw['color'] = color
    try:
        with dpg_.group(parent='assistant_log'):
            dpg_.add_text(text, **kw)
        try:
            dpg_.set_y_scroll('assistant_log', -1.0)
        except Exception:
            pass
    except Exception as e:
        _log(f'[_append_assistant_log] add_text error: {e}; '
             f'text={str(text)[:80]}')




def clear_assistant_log(sender, data, dpg_):
    if dpg_.does_item_exist('assistant_log'):
        dpg_.delete_item('assistant_log', children_only=True)


# ===========================================================================
# Исполнитель инструментов
# ===========================================================================
def _make_tool_executor(field, clear, msk_names=None, context=None):
    """Исполнитель инструментов: чтение, автозагрузка, drop_anomalies.

    Разрешение слота в get_stat / drop_anomalies:
      1. Явный slot_name (int) -> как есть.
      2. slot_name отсутствует + measure_type ('ПСИ',
         'До настройки', ...) -> первый слот с этим типом.
      3. Ни slot_name, ни measure_type -> PSI-слот
         (Measure_Type=6). Именно там Fr/Fs/FL заполнены:
         psidata.F алиасируется в Fr/Fs/FL в Data.append_data.
         Fallback — первый активный слот.

    Автокоррекция аргументов (Mistral/Gemma quirk):
      * field: ["FL"] -> "FL" (первый непустой string);
      * measure_type: ["ПСИ"] -> "ПСИ";
      * slot_name: [3] -> 3;
      * slot_name = "РК569Б-10М" (не число) + msk не задан ->
        slot_name интерпретируется как msk, слот выбирается
        по measure_type / PSI.

    При Count==0 различаем:
      * слот пуст (slot_has_data=False);
      * поле в слоте пусто (field_missing=True + available_fields
        + other_slots_with_field);
      * комбинация msk+слот пуста.

    Автозагрузка спецификации (load_spec или get_stat.msk=spec):
      get_stat возвращает period_days_used и msks_loaded —
      фактический период и число МСК. Модель должна использовать
      period_days_used в ответе, а не выдумывать «за N месяцев».

    В context (dict, если передан):
      - plots         list[Figure]
      - items         list[dict]
      - analyzed_msks set[str]
      - loaded_specs  list[dict]
    """
    msk_set = set(str(m) for m in (msk_names or []))

    _FIELD_ALIASES = {
        'f': 'Fr', 'fr': 'Fr', 'fs': 'Fs', 'fl': 'FL', 'r': 'R',
        'c0': 'C0', 'c1': 'C1', 'cq': 'C1',
        'l': 'L1', 'l1': 'L1', 'q': 'Q',
    }

    def _as_field(v, default):
        # Mistral/Gemma иногда заворачивают скаляр в массив:
        # field: ["Fl"] или field: ["Fl", "R"].
        if isinstance(v, (list, tuple)):
            picked = None
            for item in v:
                if isinstance(item, str) and item.strip():
                    picked = item
                    break
            if picked is None:
                return default
            v = picked

        if not isinstance(v, str):
            return default
        v = v.strip()
        if not v:
            return default
        low = v.lower()
        if low in _FIELD_ALIASES:
            return _FIELD_ALIASES[low]
        base = v.split()[0]
        return _FIELD_ALIASES.get(base.lower(), v)

    def _extract_measure_type(args_dict):
        for k in ('measure_type', 'measurement_type',
                  'measure', 'type', 'замер', 'тип'):
            v = args_dict.get(k)
            if isinstance(v, (list, tuple)):
                for item in v:
                    if isinstance(item, str) and item.strip():
                        return item.strip()
            elif isinstance(v, str) and v.strip():
                return v.strip()
        return None

    # ------------------------------------------------------------------
    # Разрешение слота по типу измерения
    # ------------------------------------------------------------------
    def _find_slot_by_measure_type(measure_type_name):
        """Найти первый слот с указанным типом измерения.

        Возвращает (slot:int|None, actual_type_name:str|None):
          * (slot, name)  — нашли;
          * (None, name)  — тип есть, но ни один слот не активен;
          * (None, None)  — тип не найден в measure_type_list.
        """
        if not measure_type_name:
            return None, None
        try:
            active = Statistik.Data.Data.get_active_data()
            mts = Statistik.Data.Data.get_measure_type_list()
        except Exception as e:
            _log(f'[_find_slot_by_measure_type] {e}')
            return None, None

        mt_low = str(measure_type_name).lower().strip()
        match_id = None
        match_name = None
        for _, row in mts.iterrows():
            name = str(row['Name'])
            name_low = name.lower()
            if (name_low == mt_low
                    or mt_low in name_low
                    or name_low in mt_low):
                match_id = int(row['ID'])
                match_name = name
                break

        if match_id is None:
            return None, None

        for _, srow in active.iterrows():
            if int(srow['Value']) == match_id:
                return int(srow['Name']), match_name
        return None, match_name

    def _get_default_psi_slot():
        """PSI-слот (Measure_Type=6), иначе — первый активный."""
        slot, _ = _find_slot_by_measure_type('ПСИ')
        if slot is not None:
            return slot
        try:
            active = Statistik.Data.Data.get_active_data()
            if not active.empty:
                return int(active.iloc[0]['Name'])
        except Exception:
            pass
        return 1

    def _slot_actual_type_name(slot):
        try:
            active = Statistik.Data.Data.get_active_data()
            mts = Statistik.Data.Data.get_measure_type_list()
            srow = active[active['Name'] == slot]
            if srow.empty:
                return None
            t_id = int(srow.iloc[0]['Value'])
            trow = mts[mts['ID'] == t_id]
            if trow.empty:
                return None
            return trow['Name'].to_string(index=False)
        except Exception:
            return None

    def _as_slot(v, measure_type=None):
        """Разрешить слот по приоритету:
          1) явный slot_name (int);
          2) measure_type -> первый слот этого типа;
          3) ни того, ни другого -> PSI-слот / первый активный.
        """
        # Модель может прислать slot_name списком: [3] или [3, 4]
        if isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, (int, str)) and str(item).strip():
                    v = item
                    break
            else:
                v = None

        # ---- явного слот нет ----
        if v is None:
            if measure_type:
                slot, tname = _find_slot_by_measure_type(measure_type)
                if slot is not None:
                    return slot, None
                try:
                    all_types = [
                        r['Name'] for _, r in
                        Statistik.Data.Data.get_measure_type_list()
                        .iterrows()
                    ]
                except Exception:
                    all_types = []
                if tname is None:
                    return None, {
                        "error": (f"Тип измерения {measure_type!r} "
                                  f"не найден"),
                        "available_types": all_types,
                        "hint": ("Укажите тип из available_types "
                                 "или задайте slot_name явно."),
                    }
                return None, {
                    "error": (f"Тип {tname!r} есть в справочнике, "
                              f"но ни один слот не активен с этим "
                              f"типом"),
                    "hint": ("Создайте слот с этим типом в окне "
                             "'Действия' или укажите slot_name явно."),
                }
            return _get_default_psi_slot(), None

        # ---- явный слот ----
        if isinstance(v, bool):
            return None, {
                "error": "slot_name должен быть целым числом "
                         "(1, 2, 3, ...), а не boolean",
                "hint": 'Например: {"slot_name": 3, "field": "FL"}',
            }
        if isinstance(v, int):
            slot = v
        elif isinstance(v, float) and v.is_integer():
            slot = int(v)
        elif isinstance(v, str):
            try:
                slot = int(v.strip())
            except ValueError:
                return None, {
                    "error": f"slot_name должен быть ЦЕЛЫМ числом "
                             f"(1, 2, 3, ...). Получено: {v!r}.",
                    "hint": ("slot_name - номер канала (1, 2, 3, ...), "
                             "НЕ имя МСК/спецификации. Если не знаете "
                             "номер - вызовите list_slots."),
                }
        else:
            return None, {
                "error": f"slot_name: неподдерживаемый тип "
                         f"{type(v).__name__}",
                "hint": 'Передайте целое число: {"slot_name": 3}',
            }

        if slot == 0:
            return _as_slot(None, measure_type)

        try:
            active = Statistik.Data.Data.get_active_data()
            valid = sorted(int(x) for x in active['Name'].tolist())
        except Exception:
            valid = [1, 2, 3]
        if slot not in valid:
            return None, {
                "error": f"Слот {slot} не существует",
                "available_slots": valid,
                "hint": (f"Доступные слоты: {valid}. По умолчанию 1, 2, 3. "
                         f"Новый создаётся кнопкой 'Добавить' в "
                         f"'Действия'."),
            }

        # ---- если указан ещё и тип — проверяем совместимость ----
        if measure_type:
            actual_type = _slot_actual_type_name(slot)
            if actual_type is not None:
                mt_low = str(measure_type).lower().strip()
                at_low = actual_type.lower()
                if not (at_low == mt_low
                        or mt_low in at_low
                        or at_low in mt_low):
                    return None, {
                        "error": (f"Слот {slot} имеет тип "
                                  f"'{actual_type}', а не "
                                  f"'{measure_type}'"),
                        "slot_actual_type": actual_type,
                        "hint": ("Укажите либо правильный slot_name, "
                                 "либо только measure_type "
                                 "(тогда слот подберётся "
                                 "автоматически)."),
                    }
        return slot, None

    def _get_int(args_dict, keys, default):
        for k in keys:
            if k in args_dict:
                try:
                    return int(args_dict[k])
                except (TypeError, ValueError):
                    pass
        return default

    def _get_bool(args_dict, keys, default=False):
        for k in keys:
            if k in args_dict:
                v = args_dict[k]
                if isinstance(v, bool):
                    return v
                if isinstance(v, str):
                    return v.strip().lower() in ('1', 'true', 'yes', 'y')
                return bool(v)
        return default

    def _scan_other_slots_for_field(f, exclude_slot):
        """Найти другие слоты, где параметр f реально заполнен.

        Для PSI-слотов FL/Fs уже алиасированы на F в append_data,
        поэтому проверка `f in df.columns and notna` корректно
        показывает PSI как «заполненный по FL», хотя в final_plating
        такой колонки нет.
        """
        result = []
        try:
            active = Statistik.Data.Data.get_active_data()
            mts = Statistik.Data.Data.get_measure_type_list()
        except Exception as e:
            _log(f'[get_stat] other_slots scan (active_data): {e}')
            return result

        for _, srow in active.iterrows():
            try:
                other_slot = int(srow['Name'])
            except (TypeError, ValueError):
                continue
            if other_slot == exclude_slot:
                continue

            other_df = Statistik.Data.Data.get_data(other_slot)
            if (other_df is None or other_df.empty
                    or f not in other_df.columns):
                continue

            nn = pd.to_numeric(other_df[f], errors='coerce').dropna()
            if len(nn) == 0:
                continue

            mt_id = int(srow['Value'])
            mt_row = mts[mts['ID'] == mt_id]
            mt_name = (mt_row['Name'].to_string(index=False)
                       if not mt_row.empty else f'тип {mt_id}')
            result.append({
                'slot': other_slot,
                'type': mt_name,
                'rows': int(len(nn)),
            })
        return result

    def _exec(name, args):
        try:
            # ---------- args ----------
            if isinstance(args, list):
                return {"error": "args должен быть JSON-объектом (dict), "
                                 "НЕ массивом",
                        "example": '{"field": "FL", '
                                   '"measure_type": "ПСИ", '
                                   '"msk": "РК569Б-10М"}',
                        "you_sent": args}
            if args is None:
                args = {}
            if not isinstance(args, dict):
                return {"error": f"args должен быть dict, "
                                 f"получено {type(args).__name__}"}

            # ---------- list_msks ----------
            if name == "list_msks":
                msks = list(Statistik.Data.Data.get_msk_list().keys())
                if not msks:
                    return {"msks": [],
                            "note": "Нет загруженных МСК. Используйте "
                                    "load_spec."}
                return msks

            # ---------- list_slots ----------
            if name == "list_slots":
                df = Statistik.Data.Data.get_active_data()
                mts = Statistik.Data.Data.get_measure_type_list()
                out = []
                for _, row in df.iterrows():
                    mt = mts[mts['ID'] == row['Value']]
                    mt_name = (mt['Name'].to_string(index=False)
                               if not mt.empty else '?')
                    out.append({'slot': int(row['Name']),
                                'type': mt_name,
                                'use': bool(row.get('Use', False)),
                                'count': int(row.get('Count', 0))})
                return out

            # ---------- list_specs ----------
            if name == "list_specs":
                search = (args.get('search')
                          or args.get('query')
                          or '').strip()
                if not search:
                    return {
                        "error": "search обязателен",
                        "hint": (
                            "Пустой search возвращает первые 20 "
                            "спецификаций по алфавиту — это бесполезно. "
                            "Передайте подстроку имени, например "
                            "{\"search\": \"569\"} или "
                            "{\"search\": \"РК569\"}."
                        ),
                    }
                specs = _find_specs(search, limit=20)
                if not specs:
                    return {"specs": [],
                            "note": f"Спецификации по запросу "
                                    f"{search!r} не найдены"}
                return specs

            # ---------- load_spec ----------
            if name == "load_spec":
                spec_name = (args.get('spec_name')
                             or args.get('name')
                             or args.get('spec'))
                if not spec_name:
                    return {
                        "error": "spec_name обязателен",
                        "hint": ('Например: '
                                 '{"spec_name": "РК507-98,415М-220", '
                                 '"period_days": 90}'),
                    }

                actual = _find_spec(str(spec_name))
                if not actual:
                    candidates = _find_specs(str(spec_name), limit=10)
                    return {"error": f"Спецификация {spec_name!r} "
                                     f"не найдена",
                            "candidates": candidates,
                            "hint": "Уточните имя через list_specs."}

                period_days = _get_int(args,
                                       ('period_days', 'period', 'days'),
                                       30)
                last_n = _get_int(args, ('last_n', 'count', 'limit'), 0)

                result = _auto_load_spec(actual,
                                         last_n=last_n,
                                         period_days=period_days)
                if result.get("error"):
                    return {"error": result["error"]}

                loaded = [x for x in result["loaded"]
                          if x["status"] in ("loaded", "already")]
                if not loaded:
                    return {"error": f"Не удалось загрузить ни одной "
                                     f"МСК для {actual!r}",
                            "details": result}

                msk_set.update(x["msk"] for x in loaded)

                if context is not None:
                    context.setdefault('loaded_specs', []).append({
                        'spec': actual,
                        'period_days': result.get('used_period_days'),
                        'last_n': result.get('used_last_n'),
                        'msk_dates': result.get('msk_dates', {}),
                    })

                return {
                    "spec": actual,
                    "loaded_count": len(loaded),
                    "loaded": loaded,
                    "period_days_used": result.get('used_period_days'),
                    "last_n": last_n,
                    "note": (f"Загружено {len(loaded)} МСК "
                             f"(период: {result.get('used_period_days')} "
                             f"дн., лимит: {last_n or 'без ограничения'}). "
                             f"get_stat без slot_name/measure_type "
                             f"даст агрегат по PSI-слоту."),
                }

            # ---------- get_stat ----------
            if name == "get_stat":
                raw_slot = args.get('slot_name', args.get('slot'))
                measure_type = _extract_measure_type(args)

                # Mistral/Gemma иногда кладут имя МСК в slot_name.
                # Если slot_name — нечисловая строка, а msk не задан —
                # интерпретируем её как имя МСК, слот выберем по
                # measure_type / PSI.
                if (isinstance(raw_slot, str)
                        and raw_slot.strip()
                        and not raw_slot.strip().lstrip('-').isdigit()
                        and not args.get('msk')):
                    _log(f"[get_stat] slot_name={raw_slot!r} — не "
                         f"число, интерпретируем как msk")
                    args = dict(args)
                    args['msk'] = raw_slot.strip()
                    args.pop('slot_name', None)
                    args.pop('slot', None)
                    raw_slot = None

                slot, err = _as_slot(raw_slot, measure_type)
                if err is not None:
                    return err

                f = _as_field(args.get('field'), field)

                msk_raw = args.get('msk')
                if isinstance(msk_raw, str):
                    msk_raw = msk_raw.strip() or None
                msk = msk_raw

                # Запоминаем, что автозагрузка была — чтобы вернуть
                # модели фактический period_days_used.
                auto_period_days = None
                auto_msks_loaded = 0

                if msk and msk not in msk_set:
                    actual_spec = _find_spec(msk)
                    if actual_spec:
                        period_days = _get_int(
                            args, ('period_days', 'period', 'days'), 30)
                        last_n = _get_int(
                            args, ('last_n', 'count', 'limit'), 0)
                        load_res = _auto_load_spec(
                            actual_spec,
                            last_n=last_n,
                            period_days=period_days,
                        )
                        loaded = [x for x in load_res["loaded"]
                                  if x["status"] in ("loaded", "already")]
                        if loaded:
                            msk_set.update(x["msk"] for x in loaded)
                            auto_period_days = load_res.get(
                                'used_period_days')
                            auto_msks_loaded = len(loaded)
                            if context is not None:
                                context.setdefault(
                                    'loaded_specs', []).append({
                                    'spec': actual_spec,
                                    'period_days': auto_period_days,
                                    'last_n': load_res.get('used_last_n'),
                                    'msk_dates':
                                        load_res.get('msk_dates', {}),
                                })
                            msk = None
                            _log(f"[LLM..] auto-loaded spec "
                                 f"{actual_spec!r}: {len(loaded)} MSK "
                                 f"(period={auto_period_days}d)")
                        else:
                            return {
                                "error": f"Спецификация {actual_spec!r} "
                                         f"найдена, но МСК не загрузились",
                                "details": load_res,
                                "hint": "Проверьте наличие запущенных МСК.",
                            }
                    else:
                        msk_low = msk.lower()
                        matches = [m for m in msk_set
                                   if msk_low in m.lower()
                                   or m.lower() in msk_low]
                        if matches:
                            msk = matches[0]
                        else:
                            candidates = _find_specs(msk, limit=10)
                            return {
                                "error": f"МСК/спецификация {msk!r} "
                                         f"не найдена",
                                "candidates": candidates,
                                "available_msks": sorted(msk_set)[:15],
                                "hint": "list_msks или list_specs.",
                            }

                _, _, stat = get_pdf(slot, f, clear, msk)

                # ─── Count == 0: различаем «слот пуст», «поле пустое»,
                #     «комбинация msk+слот пуста» ───
                if int(stat.get('Count', 0) or 0) == 0:
                    df_slot = Statistik.Data.Data.get_data(slot)

                    # (1) Слот содержит данные → выясняем, что именно пусто
                    if df_slot is not None and not df_slot.empty:
                        available = []
                        for col in ('Fr', 'Fs', 'FL', 'R',
                                    'C0', 'C1', 'L1', 'Q'):
                            if col in df_slot.columns:
                                nn = pd.to_numeric(
                                    df_slot[col], errors='coerce'
                                ).dropna()
                                if len(nn) > 0:
                                    available.append(col)

                        field_missing = (f in df_slot.columns
                                         and f not in available)
                        slot_type = _slot_actual_type_name(slot)

                        if field_missing:
                            other_slots = _scan_other_slots_for_field(
                                f, exclude_slot=slot
                            )
                            msg = (f"Параметр {f} в слоте {slot} "
                                   f"({slot_type or '?'}) пуст: "
                                   f"в этом слоте нет значений "
                                   f"(строк: {len(df_slot)}). "
                                   f"Заполнены: "
                                   f"{', '.join(available) or '—'}.")

                            hint_parts = [
                                f"Слот {slot} НЕ пустой — в нём "
                                f"{len(df_slot)} строк. Параметр {f} "
                                f"для этого слота не измерялся."
                            ]
                            if other_slots:
                                slots_str = ', '.join(
                                    f"слот {s['slot']} ({s['type']}, "
                                    f"{s['rows']} строк)"
                                    for s in other_slots
                                )
                                hint_parts.append(
                                    f"Параметр {f} ЗАПОЛНЕН в других "
                                    f"слотах: {slots_str}. Повтори "
                                    f"get_stat с measure_type или "
                                    f"slot_name из этого списка. "
                                    f"Если это PSI — там {f} считается "
                                    f"по колонке F из psidata."
                                )
                            else:
                                hint_parts.append(
                                    f"В других слотах параметр {f} "
                                    f"тоже пуст. Для FL можно включить "
                                    f"'Настройка без ёмкости (FL = Fr)' "
                                    f"в окне 'Действия'."
                                )

                            return {
                                "error": msg,
                                "count": 0,
                                "slot": slot,
                                "slot_type": slot_type,
                                "slot_has_data": True,
                                "field_missing": True,
                                "slot_rows": int(len(df_slot)),
                                "available_fields": available,
                                "other_slots_with_field": other_slots,
                                "hint": " ".join(hint_parts),
                            }

                        return {
                            "error": (f"Нет данных для slot={slot} "
                                      f"({slot_type or '?'}), "
                                      f"field={f}"
                                      + (f", msk={msk}" if msk else "")),
                            "count": 0,
                            "slot": slot,
                            "slot_type": slot_type,
                            "slot_has_data": True,
                            "slot_rows": int(len(df_slot)),
                            "available_fields": available,
                            "hint": ("Слот содержит данные, но для этой "
                                     "комбинации параметр/МСК пуст. "
                                     "Проверьте msk (list_msks) или "
                                     "field — available_fields "
                                     "покажет, что реально заполнено."),
                        }

                    return {
                        "error": f"Нет данных (slot={slot}, field={f})",
                        "count": 0,
                        "slot": slot,
                        "slot_has_data": False,
                        "hint": ("Слот пуст. Загрузите МСК (load_spec) "
                                 "или выберите другой слот (list_slots)."),
                    }

                # ---------- контекст для PDF ----------
                if context is not None:
                    slot_type = _slot_actual_type_name(slot) or '?'
                    title = f'Слот {slot} ({slot_type}), {f}'
                    if msk:
                        title += f', МСК {msk}'
                        context.setdefault('analyzed_msks',
                                           set()).add(msk)
                    else:
                        title += ' (все МСК)'
                        for m in msk_set:
                            context.setdefault('analyzed_msks',
                                               set()).add(m)

                    try:
                        fig = LLM._make_stat_plot(slot, f, clear, msk,
                                                  stat, title)
                        if fig is not None:
                            context['plots'].append(fig)
                    except Exception as e:
                        _log(f'[get_stat] plot: {e}')

                    context.setdefault('items', []).append({
                        'title': title,
                        'slot': slot,
                        'field': f,
                        'msk': msk,
                        'stat': dict(stat),
                    })

                # ---------- добавляем period_days_used, если была
                # автозагрузка (иначе модель не знает фактический
                # период и выдумывает «за 3 месяца» из запроса) ----------
                if auto_period_days is not None:
                    result = dict(stat)
                    result['period_days_used'] = auto_period_days
                    result['msks_loaded'] = auto_msks_loaded
                    return result
                return stat

            # ---------- get_norms ----------
            if name == "get_norms":
                result = {}
                for k, v in Statistik.Data.Data.spc_norm.items():
                    if k == 'Status' or not isinstance(v, dict):
                        continue
                    cleaned = {kk: vv for kk, vv in v.items()
                               if vv is not None}
                    if cleaned:
                        result[k] = cleaned
                if not result:
                    return {"error": "нормы не загружены",
                            "hint": "Загрузите спецификацию через "
                                    "load_spec."}
                return result

            # ---------- drop_anomalies ----------
            if name == "drop_anomalies":
                raw_slot = args.get('slot_name', args.get('slot'))
                measure_type = _extract_measure_type(args)

                if (isinstance(raw_slot, str)
                        and raw_slot.strip()
                        and not raw_slot.strip().lstrip('-').isdigit()
                        and not args.get('msk')):
                    _log(f"[drop_anomalies] slot_name={raw_slot!r} — "
                         f"не число, интерпретируем как msk")
                    args = dict(args)
                    args['msk'] = raw_slot.strip()
                    args.pop('slot_name', None)
                    args.pop('slot', None)
                    raw_slot = None

                slot, err = _as_slot(raw_slot, measure_type)
                if err is not None:
                    return err

                f = _as_field(args.get('field'), field)
                msk_raw = args.get('msk')
                if isinstance(msk_raw, str):
                    msk_raw = msk_raw.strip() or None
                msk = msk_raw
                confirm = _get_bool(args, ('confirm',), False)

                df = Statistik.Data.Data.get_data(slot)
                if df is None or df.empty or f not in df.columns:
                    return {"error": f"Нет данных (slot={slot}, field={f})",
                            "removed": 0, "count": 0}

                subset = df
                outside = None
                if msk:
                    msk_list = Statistik.Data.Data.get_msk_list()
                    if msk not in msk_list:
                        return {"error": f"МСК {msk!r} не загружена"}
                    msk_slot = msk_list[msk]
                    mrow = msk_slot[msk_slot['Name'] == slot]
                    if mrow.empty:
                        return {"error": f"МСК {msk!r} не содержит "
                                         f"слот {slot}"}
                    try:
                        mid = int(mrow['Mes_ID'].iloc[0])
                    except Exception:
                        mid = 0
                    if mid != 0 and 'Measure_ID' in df.columns:
                        mask = df['Measure_ID'] == mid
                    elif 'MSK' in df.columns:
                        # Подстрочный поиск: psidata.MSK содержит
                        # маски вида '26-6130****', поэтому точное
                        # сравнение с '26-6130' не сработает.
                        mask = df['MSK'].astype(str).str.contains(
                            str(msk), na=False, case=False,
                            regex=False)
                    else:
                        return {"error": "Не удалось отфильтровать по МСК"}
                    subset = df[mask]
                    outside = df[~mask]

                vals = pd.to_numeric(subset[f], errors='coerce')
                valid = vals.dropna()
                valid = valid[valid < 1e12]
                if len(valid) < 3:
                    return {"removed": 0,
                            "remaining": int(len(subset)),
                            "note": "мало данных для IQR (< 3)"}

                Q1 = float(valid.quantile(0.25))
                Q3 = float(valid.quantile(0.75))
                IQR = Q3 - Q1
                lo = Q1 - 1.5 * IQR
                hi = Q3 + 1.5 * IQR
                anom_mask = (vals < lo) | (vals > hi)
                anom_count = int(anom_mask.sum())

                if not confirm:
                    return {
                        "action": "dry_run",
                        "slot": slot,
                        "field": f,
                        "msk": msk,
                        "would_remove": anom_count,
                        "total": int(len(subset)),
                        "bounds": [lo, hi],
                        "note": "Это подсчёт. Для удаления повтори с "
                                "confirm=true. Удаление НЕОБРАТИМО.",
                    }

                keep_mask = ~anom_mask
                new_subset = subset[keep_mask]
                if outside is not None:
                    new_df = pd.concat([outside, new_subset])
                else:
                    new_df = new_subset
                Statistik.Data.Data.set_data(slot, new_df)

                return {
                    "action": "removed",
                    "slot": slot,
                    "field": f,
                    "msk": msk,
                    "removed": anom_count,
                    "remaining": int(len(new_subset)),
                    "note": "Аномалии удалены. Данные для этого "
                            "слота/МСК обновлены.",
                }

            return {"error": f"неизвестный инструмент: {name}"}

        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    return _exec
def _make_tool_executor_7(field, clear, msk_names=None, context=None):
    """Исполнитель инструментов: чтение, автозагрузка, drop_anomalies.

    Разрешение слота в get_stat / drop_anomalies:
      1. Явный slot_name -> используется как есть (с проверкой
         существования; если задан ещё measure_type — проверяется
         совместимость типа).
      2. slot_name отсутствует + задан measure_type ('ПСИ',
         'До настройки', 'После настройки', ...) -> ищется первый
         слот с этим типом.
      3. Ни slot_name, ни measure_type -> берётся PSI-слот
         (Measure_Type=6). Именно там Fr/Fs/FL всегда заполнены:
         psidata.F алиасируется в Fr/Fs/FL в Data.append_data,
         независимо от того, что в final_plating колонка FL пустая.
         Fallback — первый активный слот.

    В context (dict, если передан):
      - plots         list[Figure]
      - items         list[dict]
      - analyzed_msks set[str]
      - loaded_specs  list[dict]
    """
    msk_set = set(str(m) for m in (msk_names or []))

    _FIELD_ALIASES = {
        'f': 'Fr', 'fr': 'Fr', 'fs': 'Fs', 'fl': 'FL', 'r': 'R',
        'c0': 'C0', 'c1': 'C1', 'cq': 'C1',
        'l': 'L1', 'l1': 'L1', 'q': 'Q',
    }

    def _as_field(v, default):
        if not isinstance(v, str):
            return default
        v = v.strip()
        if not v:
            return default
        low = v.lower()
        if low in _FIELD_ALIASES:
            return _FIELD_ALIASES[low]
        base = v.split()[0]
        return _FIELD_ALIASES.get(base.lower(), v)

    # ------------------------------------------------------------------
    # Разрешение слота по типу измерения
    # ------------------------------------------------------------------
    def _find_slot_by_measure_type(measure_type_name):
        """Найти первый слот с указанным типом измерения.

        Возвращает (slot:int|None, actual_type_name:str|None):
          * (slot, name)  — нашли;
          * (None, name)  — тип существует, но ни один слот не активен;
          * (None, None)  — тип не найден в measure_type_list.
        """
        if not measure_type_name:
            return None, None
        try:
            active = Statistik.Data.Data.get_active_data()
            mts = Statistik.Data.Data.get_measure_type_list()
        except Exception as e:
            _log(f'[_find_slot_by_measure_type] {e}')
            return None, None

        mt_low = str(measure_type_name).lower().strip()
        match_id = None
        match_name = None
        for _, row in mts.iterrows():
            name = str(row['Name'])
            name_low = name.lower()
            if (name_low == mt_low
                    or mt_low in name_low
                    or name_low in mt_low):
                match_id = int(row['ID'])
                match_name = name
                break

        if match_id is None:
            return None, None

        for _, srow in active.iterrows():
            if int(srow['Value']) == match_id:
                return int(srow['Name']), match_name
        return None, match_name

    def _get_default_psi_slot():
        """PSI-слот (Measure_Type=6), иначе — первый активный слот.

        PSI важен, потому что там Fr/Fs/FL гарантированно
        заполнены (F из psidata алиасируется во все три).
        """
        slot, _ = _find_slot_by_measure_type('ПСИ')
        if slot is not None:
            return slot
        try:
            active = Statistik.Data.Data.get_active_data()
            if not active.empty:
                return int(active.iloc[0]['Name'])
        except Exception:
            pass
        return 1

    def _slot_actual_type_name(slot):
        """Название типа измерения для слота (или None)."""
        try:
            active = Statistik.Data.Data.get_active_data()
            mts = Statistik.Data.Data.get_measure_type_list()
            srow = active[active['Name'] == slot]
            if srow.empty:
                return None
            t_id = int(srow.iloc[0]['Value'])
            trow = mts[mts['ID'] == t_id]
            if trow.empty:
                return None
            return trow['Name'].to_string(index=False)
        except Exception:
            return None

    def _as_slot(v, measure_type=None):
        """Разрешить слот по приоритету:
          1) явный slot_name (int/str) -> как есть;
          2) measure_type -> первый слот с этим типом;
          3) ни того, ни другого -> PSI-слот (или первый активный).

        Если заданы оба (slot_name + measure_type) и типы
        не совпадают -> ошибка.
        """
        # Модель может прислать slot_name списком: [3] или [3, 4]
        if isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, (int, str)) and str(item).strip():
                    v = item
                    break
            else:
                v = None
        # ---- явного слот нет ----
        if v is None:
            if measure_type:
                slot, tname = _find_slot_by_measure_type(measure_type)
                if slot is not None:
                    return slot, None
                # тип не найден или слотов этого типа нет
                try:
                    all_types = [
                        r['Name'] for _, r in
                        Statistik.Data.Data.get_measure_type_list()
                        .iterrows()
                    ]
                except Exception:
                    all_types = []
                if tname is None:
                    return None, {
                        "error": (f"Тип измерения {measure_type!r} "
                                  f"не найден"),
                        "available_types": all_types,
                        "hint": ("Укажите тип из available_types "
                                 "или задайте slot_name явно."),
                    }
                return None, {
                    "error": (f"Тип {tname!r} есть в справочнике, "
                              f"но ни один слот не активен с этим "
                              f"типом"),
                    "hint": ("Создайте слот с этим типом в окне "
                             "'Действия' или укажите slot_name явно."),
                }
            # по умолчанию — PSI-слот
            return _get_default_psi_slot(), None

        # ---- явный слот ----
        if isinstance(v, bool):
            return None, {
                "error": "slot_name должен быть целым числом "
                         "(1, 2, 3, ...), а не boolean",
                "hint": 'Например: {"slot_name": 3, "field": "FL"}',
            }
        if isinstance(v, int):
            slot = v
        elif isinstance(v, float) and v.is_integer():
            slot = int(v)
        elif isinstance(v, str):
            try:
                slot = int(v.strip())
            except ValueError:
                return None, {
                    "error": f"slot_name должен быть ЦЕЛЫМ числом "
                             f"(1, 2, 3, ...). Получено: {v!r}.",
                    "hint": ("slot_name - номер канала (1, 2, 3, ...), "
                             "НЕ имя МСК/спецификации. Если не знаете "
                             "номер - вызовите list_slots."),
                }
        else:
            return None, {
                "error": f"slot_name: неподдерживаемый тип "
                         f"{type(v).__name__}",
                "hint": 'Передайте целое число: {"slot_name": 3}',
            }

        if slot == 0:
            # 0 = "по умолчанию" — идём по ветке measure_type / PSI
            return _as_slot(None, measure_type)

        try:
            active = Statistik.Data.Data.get_active_data()
            valid = sorted(int(x) for x in active['Name'].tolist())
        except Exception:
            valid = [1, 2, 3]
        if slot not in valid:
            return None, {
                "error": f"Слот {slot} не существует",
                "available_slots": valid,
                "hint": (f"Доступные слоты: {valid}. По умолчанию 1, 2, 3. "
                         f"Новый создаётся кнопкой 'Добавить' в "
                         f"'Действия'."),
            }

        # ---- если указан ещё и тип — проверяем совместимость ----
        if measure_type:
            actual_type = _slot_actual_type_name(slot)
            if actual_type is not None:
                mt_low = str(measure_type).lower().strip()
                at_low = actual_type.lower()
                if not (at_low == mt_low
                        or mt_low in at_low
                        or at_low in mt_low):
                    return None, {
                        "error": (f"Слот {slot} имеет тип "
                                  f"'{actual_type}', а не "
                                  f"'{measure_type}'"),
                        "slot_actual_type": actual_type,
                        "hint": ("Укажите либо правильный slot_name, "
                                 "либо только measure_type "
                                 "(тогда слот подберётся "
                                 "автоматически)."),
                    }
        return slot, None

    def _get_int(args_dict, keys, default):
        for k in keys:
            if k in args_dict:
                try:
                    return int(args_dict[k])
                except (TypeError, ValueError):
                    pass
        return default

    def _get_bool(args_dict, keys, default=False):
        for k in keys:
            if k in args_dict:
                v = args_dict[k]
                if isinstance(v, bool):
                    return v
                if isinstance(v, str):
                    return v.strip().lower() in ('1', 'true', 'yes', 'y')
                return bool(v)
        return default

    def _extract_measure_type(args_dict):
        for k in ('measure_type', 'measurement_type',
                  'measure', 'type', 'замер', 'тип'):
            v = args_dict.get(k)
            if isinstance(v, (list, tuple)):
                for item in v:
                    if isinstance(item, str) and item.strip():
                        return item.strip()
            elif isinstance(v, str) and v.strip():
                return v.strip()
        return None

    def _scan_other_slots_for_field(f, exclude_slot):
        """Найти другие слоты, где параметр f реально заполнен."""
        result = []
        try:
            active = Statistik.Data.Data.get_active_data()
            mts = Statistik.Data.Data.get_measure_type_list()
        except Exception as e:
            _log(f'[get_stat] other_slots scan (active_data): {e}')
            return result

        for _, srow in active.iterrows():
            try:
                other_slot = int(srow['Name'])
            except (TypeError, ValueError):
                continue
            if other_slot == exclude_slot:
                continue
            other_df = Statistik.Data.Data.get_data(other_slot)
            if (other_df is None or other_df.empty
                    or f not in other_df.columns):
                continue
            nn = pd.to_numeric(other_df[f], errors='coerce').dropna()
            if len(nn) == 0:
                continue
            mt_id = int(srow['Value'])
            mt_row = mts[mts['ID'] == mt_id]
            mt_name = (mt_row['Name'].to_string(index=False)
                       if not mt_row.empty else f'тип {mt_id}')
            result.append({
                'slot': other_slot,
                'type': mt_name,
                'rows': int(len(nn)),
            })
        return result

    def _exec(name, args):
        try:
            # ---------- args ----------
            if isinstance(args, list):
                return {"error": "args должен быть JSON-объектом (dict), "
                                 "НЕ массивом",
                        "example": '{"field": "FL", '
                                   '"measure_type": "ПСИ", '
                                   '"msk": "РК569Б-10М"}',
                        "you_sent": args}
            if args is None:
                args = {}
            if not isinstance(args, dict):
                return {"error": f"args должен быть dict, "
                                 f"получено {type(args).__name__}"}

            # ---------- list_msks ----------
            if name == "list_msks":
                msks = list(Statistik.Data.Data.get_msk_list().keys())
                if not msks:
                    return {"msks": [],
                            "note": "Нет загруженных МСК. Используйте "
                                    "load_spec."}
                return msks

            # ---------- list_slots ----------
            if name == "list_slots":
                df = Statistik.Data.Data.get_active_data()
                mts = Statistik.Data.Data.get_measure_type_list()
                out = []
                for _, row in df.iterrows():
                    mt = mts[mts['ID'] == row['Value']]
                    mt_name = (mt['Name'].to_string(index=False)
                               if not mt.empty else '?')
                    out.append({'slot': int(row['Name']),
                                'type': mt_name,
                                'use': bool(row.get('Use', False)),
                                'count': int(row.get('Count', 0))})
                return out

            # ---------- list_specs ----------
            if name == "list_specs":
                search = (args.get('search')
                          or args.get('query')
                          or '').strip()
                if not search:
                    return {
                        "error": "search обязателен",
                        "hint": (
                            "Пустой search возвращает первые 20 "
                            "спецификаций по алфавиту — это бесполезно. "
                            "Передайте подстроку имени, например "
                            "{\"search\": \"569\"} или "
                            "{\"search\": \"РК569\"}."
                        ),
                    }
                specs = _find_specs(search, limit=20)
                if not specs:
                    return {"specs": [],
                            "note": f"Спецификации по запросу "
                                    f"{search!r} не найдены"}
                return specs

            # ---------- load_spec ----------
            if name == "load_spec":
                spec_name = (args.get('spec_name')
                             or args.get('name')
                             or args.get('spec'))
                if not spec_name:
                    return {
                        "error": "spec_name обязателен",
                        "hint": ('Например: '
                                 '{"spec_name": "РК507-98,415М-220", '
                                 '"period_days": 30}'),
                    }

                actual = _find_spec(str(spec_name))
                if not actual:
                    candidates = _find_specs(str(spec_name), limit=10)
                    return {"error": f"Спецификация {spec_name!r} "
                                     f"не найдена",
                            "candidates": candidates,
                            "hint": "Уточните имя через list_specs."}

                period_days = _get_int(args,
                                       ('period_days', 'period', 'days'),
                                       30)
                last_n = _get_int(args, ('last_n', 'count', 'limit'), 0)

                result = _auto_load_spec(actual,
                                         last_n=last_n,
                                         period_days=period_days)
                if result.get("error"):
                    return {"error": result["error"]}

                loaded = [x for x in result["loaded"]
                          if x["status"] in ("loaded", "already")]
                if not loaded:
                    return {"error": f"Не удалось загрузить ни одной "
                                     f"МСК для {actual!r}",
                            "details": result}

                msk_set.update(x["msk"] for x in loaded)

                if context is not None:
                    context.setdefault('loaded_specs', []).append({
                        'spec': actual,
                        'period_days': result.get('used_period_days'),
                        'last_n': result.get('used_last_n'),
                        'msk_dates': result.get('msk_dates', {}),
                    })

                return {
                    "spec": actual,
                    "loaded_count": len(loaded),
                    "loaded": loaded,
                    "period_days": period_days,
                    "last_n": last_n,
                    "note": (f"Загружено {len(loaded)} МСК "
                             f"(период: {period_days} дн., лимит: "
                             f"{last_n or 'без ограничения'}). "
                             f"get_stat без slot_name/measure_type "
                             f"даст агрегат по PSI-слоту."),
                }

            # ---------- get_stat ----------
            if name == "get_stat":
                raw_slot = args.get('slot_name', args.get('slot'))
                measure_type = _extract_measure_type(args)

                # Mistral иногда кладёт имя МСК в slot_name.
                # Если slot_name — нечисловая строка, а msk не задан —
                # интерпретируем её как имя МСК, слот выберем по
                # measure_type / PSI.
                if (isinstance(raw_slot, str)
                        and raw_slot.strip()
                        and not raw_slot.strip().lstrip('-').isdigit()
                        and not args.get('msk')):
                    _log(f"[get_stat] slot_name={raw_slot!r} — не "
                         f"число, интерпретируем как msk")
                    args = dict(args)
                    args['msk'] = raw_slot.strip()
                    args.pop('slot_name', None)
                    args.pop('slot', None)
                    raw_slot = None

                slot, err = _as_slot(raw_slot, measure_type)
                if err is not None:
                    return err

                f = _as_field(args.get('field'), field)

                msk_raw = args.get('msk')
                if isinstance(msk_raw, str):
                    msk_raw = msk_raw.strip() or None
                msk = msk_raw

                if msk and msk not in msk_set:
                    actual_spec = _find_spec(msk)
                    if actual_spec:
                        period_days = _get_int(
                            args, ('period_days', 'period', 'days'), 30)
                        last_n = _get_int(
                            args, ('last_n', 'count', 'limit'), 0)
                        load_res = _auto_load_spec(
                            actual_spec,
                            last_n=last_n,
                            period_days=period_days,
                        )
                        loaded = [x for x in load_res["loaded"]
                                  if x["status"] in ("loaded", "already")]
                        if loaded:
                            msk_set.update(x["msk"] for x in loaded)
                            if context is not None:
                                context.setdefault(
                                    'loaded_specs', []).append({
                                    'spec': actual_spec,
                                    'period_days':
                                        load_res.get('used_period_days'),
                                    'last_n': load_res.get('used_last_n'),
                                    'msk_dates':
                                        load_res.get('msk_dates', {}),
                                })
                            msk = None
                            _log(f"[LLM..] auto-loaded spec "
                                 f"{actual_spec!r}: {len(loaded)} MSK "
                                 f"(period={period_days}d)")
                        else:
                            return {
                                "error": f"Спецификация {actual_spec!r} "
                                         f"найдена, но МСК не загрузились",
                                "details": load_res,
                                "hint": "Проверьте наличие запущенных МСК.",
                            }
                    else:
                        msk_low = msk.lower()
                        matches = [m for m in msk_set
                                   if msk_low in m.lower()
                                   or m.lower() in msk_low]
                        if matches:
                            msk = matches[0]
                        else:
                            candidates = _find_specs(msk, limit=10)
                            return {
                                "error": f"МСК/спецификация {msk!r} "
                                         f"не найдена",
                                "candidates": candidates,
                                "available_msks": sorted(msk_set)[:15],
                                "hint": "list_msks или list_specs.",
                            }

                _, _, stat = get_pdf(slot, f, clear, msk)

                # ─── Count == 0: различаем «слот пуст», «поле пустое»,
                #     «комбинация msk+слот пуста» ───
                if int(stat.get('Count', 0) or 0) == 0:
                    df_slot = Statistik.Data.Data.get_data(slot)

                    if df_slot is not None and not df_slot.empty:
                        available = []
                        for col in ('Fr', 'Fs', 'FL', 'R',
                                    'C0', 'C1', 'L1', 'Q'):
                            if col in df_slot.columns:
                                nn = pd.to_numeric(
                                    df_slot[col], errors='coerce'
                                ).dropna()
                                if len(nn) > 0:
                                    available.append(col)

                        field_missing = (f in df_slot.columns
                                         and f not in available)
                        slot_type = _slot_actual_type_name(slot)

                        if field_missing:
                            other_slots = _scan_other_slots_for_field(
                                f, exclude_slot=slot
                            )
                            msg = (f"Параметр {f} в слоте {slot} "
                                   f"({slot_type or '?'}) пуст: "
                                   f"в этом слоте нет значений "
                                   f"(строк: {len(df_slot)}). "
                                   f"Заполнены: "
                                   f"{', '.join(available) or '—'}.")

                            hint_parts = [
                                f"Слот {slot} НЕ пустой — в нём "
                                f"{len(df_slot)} строк. Параметр {f} "
                                f"для этого слота не измерялся."
                            ]
                            if other_slots:
                                slots_str = ', '.join(
                                    f"слот {s['slot']} ({s['type']}, "
                                    f"{s['rows']} строк)"
                                    for s in other_slots
                                )
                                hint_parts.append(
                                    f"Параметр {f} ЗАПОЛНЕН в других "
                                    f"слотах: {slots_str}. Повтори "
                                    f"get_stat с measure_type или "
                                    f"slot_name из этого списка. "
                                    f"Если это PSI — там {f} считается "
                                    f"по колонке F из psidata."
                                )
                            else:
                                hint_parts.append(
                                    f"В других слотах параметр {f} "
                                    f"тоже пуст. Для FL можно включить "
                                    f"'Настройка без ёмкости (FL = Fr)' "
                                    f"в окне 'Действия'."
                                )

                            return {
                                "error": msg,
                                "count": 0,
                                "slot": slot,
                                "slot_type": slot_type,
                                "slot_has_data": True,
                                "field_missing": True,
                                "slot_rows": int(len(df_slot)),
                                "available_fields": available,
                                "other_slots_with_field": other_slots,
                                "hint": " ".join(hint_parts),
                            }

                        return {
                            "error": (f"Нет данных для slot={slot} "
                                      f"({slot_type or '?'}), "
                                      f"field={f}"
                                      + (f", msk={msk}" if msk else "")),
                            "count": 0,
                            "slot": slot,
                            "slot_type": slot_type,
                            "slot_has_data": True,
                            "slot_rows": int(len(df_slot)),
                            "available_fields": available,
                            "hint": ("Слот содержит данные, но для этой "
                                     "комбинации параметр/МСК пуст. "
                                     "Проверьте msk (list_msks) или "
                                     "field — available_fields "
                                     "покажет, что реально заполнено."),
                        }

                    return {
                        "error": f"Нет данных (slot={slot}, field={f})",
                        "count": 0,
                        "slot": slot,
                        "slot_has_data": False,
                        "hint": ("Слот пуст. Загрузите МСК (load_spec) "
                                 "или выберите другой слот (list_slots)."),
                    }

                # ---------- контекст для PDF ----------
                if context is not None:
                    slot_type = _slot_actual_type_name(slot) or '?'
                    title = f'Слот {slot} ({slot_type}), {f}'
                    if msk:
                        title += f', МСК {msk}'
                        context.setdefault('analyzed_msks',
                                           set()).add(msk)
                    else:
                        title += ' (все МСК)'
                        for m in msk_set:
                            context.setdefault('analyzed_msks',
                                               set()).add(m)

                    try:
                        fig = LLM._make_stat_plot(slot, f, clear, msk,
                                                  stat, title)
                        if fig is not None:
                            context['plots'].append(fig)
                    except Exception as e:
                        _log(f'[get_stat] plot: {e}')

                    context.setdefault('items', []).append({
                        'title': title,
                        'slot': slot,
                        'field': f,
                        'msk': msk,
                        'stat': dict(stat),
                    })

                return stat

            # ---------- get_norms ----------
            if name == "get_norms":
                result = {}
                for k, v in Statistik.Data.Data.spc_norm.items():
                    if k == 'Status' or not isinstance(v, dict):
                        continue
                    cleaned = {kk: vv for kk, vv in v.items()
                               if vv is not None}
                    if cleaned:
                        result[k] = cleaned
                if not result:
                    return {"error": "нормы не загружены",
                            "hint": "Загрузите спецификацию через "
                                    "load_spec."}
                return result

            # ---------- drop_anomalies ----------
            if name == "drop_anomalies":
                raw_slot = args.get('slot_name', args.get('slot'))
                measure_type = _extract_measure_type(args)

                if (isinstance(raw_slot, str)
                        and raw_slot.strip()
                        and not raw_slot.strip().lstrip('-').isdigit()
                        and not args.get('msk')):
                    _log(f"[drop_anomalies] slot_name={raw_slot!r} — "
                         f"не число, интерпретируем как msk")
                    args = dict(args)
                    args['msk'] = raw_slot.strip()
                    args.pop('slot_name', None)
                    args.pop('slot', None)
                    raw_slot = None

                slot, err = _as_slot(raw_slot, measure_type)
                if err is not None:
                    return err

                f = _as_field(args.get('field'), field)
                msk_raw = args.get('msk')
                if isinstance(msk_raw, str):
                    msk_raw = msk_raw.strip() or None
                msk = msk_raw
                confirm = _get_bool(args, ('confirm',), False)

                df = Statistik.Data.Data.get_data(slot)
                if df is None or df.empty or f not in df.columns:
                    return {"error": f"Нет данных (slot={slot}, field={f})",
                            "removed": 0, "count": 0}

                subset = df
                outside = None
                if msk:
                    msk_list = Statistik.Data.Data.get_msk_list()
                    if msk not in msk_list:
                        return {"error": f"МСК {msk!r} не загружена"}
                    msk_slot = msk_list[msk]
                    mrow = msk_slot[msk_slot['Name'] == slot]
                    if mrow.empty:
                        return {"error": f"МСК {msk!r} не содержит "
                                         f"слот {slot}"}
                    try:
                        mid = int(mrow['Mes_ID'].iloc[0])
                    except Exception:
                        mid = 0
                    if mid != 0 and 'Measure_ID' in df.columns:
                        mask = df['Measure_ID'] == mid
                    elif 'MSK' in df.columns:
                        # Подстрочный поиск — см. get_pdf в Operations.py
                        mask = df['MSK'].astype(str).str.contains(
                            str(msk), na=False, case=False,
                            regex=False)
                    else:
                        return {"error": "Не удалось отфильтровать по МСК"}
                    subset = df[mask]
                    outside = df[~mask]

                vals = pd.to_numeric(subset[f], errors='coerce')
                valid = vals.dropna()
                valid = valid[valid < 1e12]
                if len(valid) < 3:
                    return {"removed": 0,
                            "remaining": int(len(subset)),
                            "note": "мало данных для IQR (< 3)"}

                Q1 = float(valid.quantile(0.25))
                Q3 = float(valid.quantile(0.75))
                IQR = Q3 - Q1
                lo = Q1 - 1.5 * IQR
                hi = Q3 + 1.5 * IQR
                anom_mask = (vals < lo) | (vals > hi)
                anom_count = int(anom_mask.sum())

                if not confirm:
                    return {
                        "action": "dry_run",
                        "slot": slot,
                        "field": f,
                        "msk": msk,
                        "would_remove": anom_count,
                        "total": int(len(subset)),
                        "bounds": [lo, hi],
                        "note": "Это подсчёт. Для удаления повтори с "
                                "confirm=true. Удаление НЕОБРАТИМО.",
                    }

                keep_mask = ~anom_mask
                new_subset = subset[keep_mask]
                if outside is not None:
                    new_df = pd.concat([outside, new_subset])
                else:
                    new_df = new_subset
                Statistik.Data.Data.set_data(slot, new_df)

                return {
                    "action": "removed",
                    "slot": slot,
                    "field": f,
                    "msk": msk,
                    "removed": anom_count,
                    "remaining": int(len(new_subset)),
                    "note": "Аномалии удалены. Данные для этого "
                            "слота/МСК обновлены.",
                }

            return {"error": f"неизвестный инструмент: {name}"}

        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    return _exec
def _make_tool_executor_7(field, clear, msk_names=None, context=None):
    """Исполнитель инструментов: чтение, автозагрузка, drop_anomalies.

    В context (dict, если передан):
      - plots         list[Figure]     - графики для PDF
      - items         list[dict]       - сводки get_stat
      - analyzed_msks set[str]         - МСК, по которым был get_stat
      - loaded_specs  list[dict]       - {spec, period_days, msk_dates}

    Особенности get_stat при Count==0:
      * различает «слот пуст», «поле пустое в этом слоте»,
        «комбинация msk+слот пуста» — модель больше не может
        соврать «МСК не загружены»;
      * при field_missing сканирует остальные слоты и возвращает
        other_slots_with_field — подсказку, где этот же параметр
        реально заполнен (например, FL для PSI считается по F,
        даже если final_plating.FL пуст).
    """
    msk_set = set(str(m) for m in (msk_names or []))

    _FIELD_ALIASES = {
        'f': 'Fr', 'fr': 'Fr', 'fs': 'Fs', 'fl': 'FL', 'r': 'R',
        'c0': 'C0', 'c1': 'C1', 'cq': 'C1',
        'l': 'L1', 'l1': 'L1', 'q': 'Q',
    }

    def _as_field(v, default):
        # Mistral-7B иногда заворачивает скаляр в массив:
        # field: ["Fl"] или даже field: ["Fl", "R"].
        # Берём первый непустой string из массива — get_stat умеет
        # только одно поле за раз; для двух полей модель сделает
        # два вызова.
        if isinstance(v, (list, tuple)):
            picked = None
            for item in v:
                if isinstance(item, str) and item.strip():
                    picked = item
                    break
            if picked is None:
                return default
            v = picked

        if not isinstance(v, str):
            return default
        v = v.strip()
        if not v:
            return default
        low = v.lower()
        if low in _FIELD_ALIASES:
            return _FIELD_ALIASES[low]
        base = v.split()[0]
        return _FIELD_ALIASES.get(base.lower(), v)

    def _as_slot(v):
        if v is None:
            return 1, None
        if isinstance(v, bool):
            return None, {
                "error": "slot_name должен быть целым числом "
                         "(1, 2, 3, ...), а не boolean",
                "hint": 'Например: {"slot_name": 3, "field": "FL"}',
            }
        if isinstance(v, int):
            slot = v
        elif isinstance(v, float) and v.is_integer():
            slot = int(v)
        elif isinstance(v, str):
            try:
                slot = int(v.strip())
            except ValueError:
                return None, {
                    "error": f"slot_name должен быть ЦЕЛЫМ числом "
                             f"(1, 2, 3, ...). Получено: {v!r}.",
                    "hint": ("slot_name - номер канала (1, 2, 3, ...), "
                             "НЕ имя МСК/спецификации. Если не знаете "
                             "номер - вызовите list_slots."),
                }
        else:
            return None, {
                "error": f"slot_name: неподдерживаемый тип "
                         f"{type(v).__name__}",
                "hint": 'Передайте целое число: {"slot_name": 3}',
            }
        if slot == 0:
            return 1, None
        try:
            active = Statistik.Data.Data.get_active_data()
            valid = sorted(int(x) for x in active['Name'].tolist())
        except Exception:
            valid = [1, 2, 3]
        if slot not in valid:
            return None, {
                "error": f"Слот {slot} не существует",
                "available_slots": valid,
                "hint": (f"Доступные слоты: {valid}. По умолчанию 1, 2, 3. "
                         f"Новый создаётся кнопкой 'Добавить' в "
                         f"'Действия'."),
            }
        return slot, None

    def _get_int(args_dict, keys, default):
        for k in keys:
            if k in args_dict:
                try:
                    return int(args_dict[k])
                except (TypeError, ValueError):
                    pass
        return default

    def _get_bool(args_dict, keys, default=False):
        for k in keys:
            if k in args_dict:
                v = args_dict[k]
                if isinstance(v, bool):
                    return v
                if isinstance(v, str):
                    return v.strip().lower() in ('1', 'true', 'yes', 'y')
                return bool(v)
        return default

    def _scan_other_slots_for_field(f, exclude_slot):
        """Найти другие слоты, где параметр f реально заполнен.

        Используется при field_missing, чтобы подсказать модели,
        где этот же параметр доступен. Для PSI-слотов (Measure_Type=6)
        FL/Fs уже алиасированы на F в Data.append_data, так что
        проверка `f in df.columns and notna` работает корректно —
        если в PSI-слоте есть строки, то FL/Fs/Fr там заполнены.
        """
        result = []
        try:
            active = Statistik.Data.Data.get_active_data()
            mts = Statistik.Data.Data.get_measure_type_list()
        except Exception as e:
            _log(f'[get_stat] other_slots scan (active_data): {e}')
            return result

        for _, srow in active.iterrows():
            try:
                other_slot = int(srow['Name'])
            except (TypeError, ValueError):
                continue
            if other_slot == exclude_slot:
                continue

            other_df = Statistik.Data.Data.get_data(other_slot)
            if (other_df is None or other_df.empty
                    or f not in other_df.columns):
                continue

            nn = pd.to_numeric(other_df[f], errors='coerce').dropna()
            if len(nn) == 0:
                continue

            mt_id = int(srow['Value'])
            mt_row = mts[mts['ID'] == mt_id]
            mt_name = (mt_row['Name'].to_string(index=False)
                       if not mt_row.empty else f'тип {mt_id}')
            result.append({
                'slot': other_slot,
                'type': mt_name,
                'rows': int(len(nn)),
            })
        return result

    def _exec(name, args):
        try:
            # ---------- args ----------
            if isinstance(args, list):
                return {"error": "args должен быть JSON-объектом (dict), "
                                 "НЕ массивом",
                        "example": '{"slot_name": 3, "field": "FL"}',
                        "you_sent": args}
            if args is None:
                args = {}
            if not isinstance(args, dict):
                return {"error": f"args должен быть dict, "
                                 f"получено {type(args).__name__}"}

            # ---------- list_msks ----------
            if name == "list_msks":
                msks = list(Statistik.Data.Data.get_msk_list().keys())
                if not msks:
                    return {"msks": [],
                            "note": "Нет загруженных МСК. Используйте "
                                    "load_spec."}
                return msks

            # ---------- list_slots ----------
            if name == "list_slots":
                df = Statistik.Data.Data.get_active_data()
                mts = Statistik.Data.Data.get_measure_type_list()
                out = []
                for _, row in df.iterrows():
                    mt = mts[mts['ID'] == row['Value']]
                    mt_name = (mt['Name'].to_string(index=False)
                               if not mt.empty else '?')
                    out.append({'slot': int(row['Name']),
                                'type': mt_name,
                                'use': bool(row.get('Use', False)),
                                'count': int(row.get('Count', 0))})
                return out

            # ---------- list_specs ----------
            if name == "list_specs":
                search = (args.get('search')
                          or args.get('query')
                          or '').strip()
                if not search:
                    return {
                        "error": "search обязателен",
                        "hint": (
                            "Пустой search возвращает первые 20 "
                            "спецификаций по алфавиту — это бесполезно. "
                            "Передайте подстроку имени, например "
                            "{\"search\": \"569\"} или "
                            "{\"search\": \"РК569\"}."
                        ),
                    }
                specs = _find_specs(search, limit=20)
                if not specs:
                    return {"specs": [],
                            "note": f"Спецификации по запросу "
                                    f"{search!r} не найдены"}
                return specs

            # ---------- load_spec ----------
            if name == "load_spec":
                spec_name = (args.get('spec_name')
                             or args.get('name')
                             or args.get('spec'))
                if not spec_name:
                    return {
                        "error": "spec_name обязателен",
                        "hint": ('Например: '
                                 '{"spec_name": "РК507-98,415М-220", '
                                 '"period_days": 30}'),
                    }

                actual = _find_spec(str(spec_name))
                if not actual:
                    candidates = _find_specs(str(spec_name), limit=10)
                    return {"error": f"Спецификация {spec_name!r} "
                                     f"не найдена",
                            "candidates": candidates,
                            "hint": "Уточните имя через list_specs."}

                period_days = _get_int(args,
                                       ('period_days', 'period', 'days'),
                                       30)
                last_n = _get_int(args, ('last_n', 'count', 'limit'), 0)

                result = _auto_load_spec(actual,
                                         last_n=last_n,
                                         period_days=period_days)
                if result.get("error"):
                    return {"error": result["error"]}

                loaded = [x for x in result["loaded"]
                          if x["status"] in ("loaded", "already")]
                if not loaded:
                    return {"error": f"Не удалось загрузить ни одной "
                                     f"МСК для {actual!r}",
                            "details": result}

                msk_set.update(x["msk"] for x in loaded)

                if context is not None:
                    context.setdefault('loaded_specs', []).append({
                        'spec': actual,
                        'period_days': result.get('used_period_days'),
                        'last_n': result.get('used_last_n'),
                        'msk_dates': result.get('msk_dates', {}),
                    })

                return {
                    "spec": actual,
                    "loaded_count": len(loaded),
                    "loaded": loaded,
                    "period_days": period_days,
                    "last_n": last_n,
                    "note": (f"Загружено {len(loaded)} МСК "
                             f"(период: {period_days} дн., лимит: "
                             f"{last_n or 'без ограничения'}). "
                             f"get_stat без msk даст агрегат."),
                }

            # ---------- get_stat ----------
            if name == "get_stat":
                raw_slot = args.get('slot_name', args.get('slot'))
                slot, err = _as_slot(raw_slot)
                if err is not None:
                    return err

                f = _as_field(args.get('field'), field)

                msk_raw = args.get('msk')
                if isinstance(msk_raw, str):
                    msk_raw = msk_raw.strip() or None
                msk = msk_raw

                if msk and msk not in msk_set:
                    actual_spec = _find_spec(msk)
                    if actual_spec:
                        period_days = _get_int(
                            args, ('period_days', 'period', 'days'), 30)
                        last_n = _get_int(
                            args, ('last_n', 'count', 'limit'), 0)
                        load_res = _auto_load_spec(
                            actual_spec,
                            last_n=last_n,
                            period_days=period_days,
                        )
                        loaded = [x for x in load_res["loaded"]
                                  if x["status"] in ("loaded", "already")]
                        if loaded:
                            msk_set.update(x["msk"] for x in loaded)
                            if context is not None:
                                context.setdefault(
                                    'loaded_specs', []).append({
                                    'spec': actual_spec,
                                    'period_days':
                                        load_res.get('used_period_days'),
                                    'last_n': load_res.get('used_last_n'),
                                    'msk_dates':
                                        load_res.get('msk_dates', {}),
                                })
                            msk = None
                            _log(f"[LLM..] auto-loaded spec "
                                 f"{actual_spec!r}: {len(loaded)} MSK "
                                 f"(period={period_days}d)")
                        else:
                            return {
                                "error": f"Спецификация {actual_spec!r} "
                                         f"найдена, но МСК не загрузились",
                                "details": load_res,
                                "hint": "Проверьте наличие запущенных МСК.",
                            }
                    else:
                        msk_low = msk.lower()
                        matches = [m for m in msk_set
                                   if msk_low in m.lower()
                                   or m.lower() in msk_low]
                        if matches:
                            msk = matches[0]
                        else:
                            candidates = _find_specs(msk, limit=10)
                            return {
                                "error": f"МСК/спецификация {msk!r} "
                                         f"не найдена",
                                "candidates": candidates,
                                "available_msks": sorted(msk_set)[:15],
                                "hint": "list_msks или list_specs.",
                            }

                _, _, stat = get_pdf(slot, f, clear, msk)

                # ─── Count == 0: различаем «слот пуст», «поле пустое»,
                #     «комбинация msk+слот пуста» ───
                if int(stat.get('Count', 0) or 0) == 0:
                    df_slot = Statistik.Data.Data.get_data(slot)

                    # (1) Слот содержит данные → выясняем, что именно пусто
                    if df_slot is not None and not df_slot.empty:
                        available = []
                        for col in ('Fr', 'Fs', 'FL', 'R',
                                    'C0', 'C1', 'L1', 'Q'):
                            if col in df_slot.columns:
                                nn = pd.to_numeric(
                                    df_slot[col], errors='coerce'
                                ).dropna()
                                if len(nn) > 0:
                                    available.append(col)

                        field_missing = (f in df_slot.columns
                                         and f not in available)

                        if field_missing:
                            # ── ищем, где этот же параметр заполнен ──
                            other_slots = _scan_other_slots_for_field(
                                f, exclude_slot=slot
                            )

                            msg = (f"Параметр {f} в слоте {slot} "
                                   f"пуст: в этом слоте нет значений "
                                   f"(строк: {len(df_slot)}). "
                                   f"Заполнены: "
                                   f"{', '.join(available) or '—'}.")

                            hint_parts = [
                                f"Слот {slot} НЕ пустой — в нём "
                                f"{len(df_slot)} строк. Параметр {f} "
                                f"для этого слота не измерялся.",
                                "(1) запросите другой параметр из "
                                "available_fields",
                                "(2) для FL можно включить "
                                "'Настройка без ёмкости (FL = Fr)' "
                                "в окне 'Действия'",
                            ]
                            if other_slots:
                                slots_str = ', '.join(
                                    f"слот {s['slot']} ({s['type']}, "
                                    f"{s['rows']} строк)"
                                    for s in other_slots
                                )
                                hint_parts.append(
                                    f"(3) параметр {f} ЗАПОЛНЕН в "
                                    f"других слотах: {slots_str}. "
                                    f"Если пользователь имел в виду "
                                    f"PSI-статистику — повтори "
                                    f"get_stat с одним из этих слотов "
                                    f"(PSI хранит частоту в колонке F, "
                                    f"которая алиасируется в Fr/Fs/FL)."
                                )
                            else:
                                hint_parts.append(
                                    f"(3) в других слотах параметр {f} "
                                    f"тоже пуст — этот параметр нигде "
                                    f"не измерялся для текущего набора."
                                )

                            return {
                                "error": msg,
                                "count": 0,
                                "slot_has_data": True,
                                "field_missing": True,
                                "slot_rows": int(len(df_slot)),
                                "available_fields": available,
                                "other_slots_with_field": other_slots,
                                "hint": " ".join(hint_parts),
                            }

                        # (2) Поле есть, но для этой msk/слота пусто
                        return {
                            "error": (f"Нет данных для slot={slot}, "
                                      f"field={f}"
                                      + (f", msk={msk}" if msk else "")),
                            "count": 0,
                            "slot_has_data": True,
                            "slot_rows": int(len(df_slot)),
                            "available_fields": available,
                            "hint": ("Слот содержит данные, но для этой "
                                     "комбинации параметр/МСК пуст. "
                                     "Проверьте msk (list_msks) или "
                                     "field — available_fields "
                                     "покажет, что реально заполнено."),
                        }

                    # (3) Слот реально пуст — только тут load_spec уместен
                    return {
                        "error": f"Нет данных (slot={slot}, field={f})",
                        "count": 0,
                        "slot_has_data": False,
                        "hint": ("Слот пуст. Загрузите МСК (load_spec) "
                                 "или выберите другой слот (list_slots)."),
                    }

                # ---------- контекст для PDF ----------
                if context is not None:
                    title = f'Слот {slot}, {f}'
                    if msk:
                        title += f', МСК {msk}'
                        context.setdefault('analyzed_msks', set()).add(msk)
                    else:
                        title += ' (все МСК)'
                        for m in msk_set:
                            context.setdefault('analyzed_msks',
                                               set()).add(m)

                    try:
                        fig = LLM._make_stat_plot(slot, f, clear, msk,
                                                  stat, title)
                        if fig is not None:
                            context['plots'].append(fig)
                    except Exception as e:
                        _log(f'[get_stat] plot: {e}')

                    context.setdefault('items', []).append({
                        'title': title,
                        'slot': slot,
                        'field': f,
                        'msk': msk,
                        'stat': dict(stat),
                    })

                return stat

            # ---------- get_norms ----------
            if name == "get_norms":
                result = {}
                for k, v in Statistik.Data.Data.spc_norm.items():
                    if k == 'Status' or not isinstance(v, dict):
                        continue
                    cleaned = {kk: vv for kk, vv in v.items()
                               if vv is not None}
                    if cleaned:
                        result[k] = cleaned
                if not result:
                    return {"error": "нормы не загружены",
                            "hint": "Загрузите спецификацию через "
                                    "load_spec."}
                return result

            # ---------- drop_anomalies ----------
            if name == "drop_anomalies":
                raw_slot = args.get('slot_name', args.get('slot'))
                slot, err = _as_slot(raw_slot)
                if err is not None:
                    return err

                f = _as_field(args.get('field'), field)
                msk_raw = args.get('msk')
                if isinstance(msk_raw, str):
                    msk_raw = msk_raw.strip() or None
                msk = msk_raw
                confirm = _get_bool(args, ('confirm',), False)

                df = Statistik.Data.Data.get_data(slot)
                if df is None or df.empty or f not in df.columns:
                    return {"error": f"Нет данных (slot={slot}, field={f})",
                            "removed": 0, "count": 0}

                # отфильтровать по МСК
                subset = df
                outside = None
                if msk:
                    msk_list = Statistik.Data.Data.get_msk_list()
                    if msk not in msk_list:
                        return {"error": f"МСК {msk!r} не загружена"}
                    msk_slot = msk_list[msk]
                    mrow = msk_slot[msk_slot['Name'] == slot]
                    if mrow.empty:
                        return {"error": f"МСК {msk!r} не содержит "
                                         f"слот {slot}"}
                    try:
                        mid = int(mrow['Mes_ID'].iloc[0])
                    except Exception:
                        mid = 0
                    if mid != 0 and 'Measure_ID' in df.columns:
                        mask = df['Measure_ID'] == mid
                    elif 'MSK' in df.columns:
                        mask = df['MSK'] == str(msk)
                    else:
                        return {"error": "Не удалось отфильтровать по МСК"}
                    subset = df[mask]
                    outside = df[~mask]

                vals = pd.to_numeric(subset[f], errors='coerce')
                valid = vals.dropna()
                valid = valid[valid < 1e12]
                if len(valid) < 3:
                    return {"removed": 0,
                            "remaining": int(len(subset)),
                            "note": "мало данных для IQR (< 3)"}

                Q1 = float(valid.quantile(0.25))
                Q3 = float(valid.quantile(0.75))
                IQR = Q3 - Q1
                lo = Q1 - 1.5 * IQR
                hi = Q3 + 1.5 * IQR
                anom_mask = (vals < lo) | (vals > hi)
                anom_count = int(anom_mask.sum())

                if not confirm:
                    return {
                        "action": "dry_run",
                        "slot": slot,
                        "field": f,
                        "msk": msk,
                        "would_remove": anom_count,
                        "total": int(len(subset)),
                        "bounds": [lo, hi],
                        "note": "Это подсчёт. Для удаления повтори с "
                                "confirm=true. Удаление НЕОБРАТИМО.",
                    }

                # реальное удаление
                keep_mask = ~anom_mask
                new_subset = subset[keep_mask]
                if outside is not None:
                    new_df = pd.concat([outside, new_subset])
                else:
                    new_df = new_subset
                Statistik.Data.Data.set_data(slot, new_df)

                return {
                    "action": "removed",
                    "slot": slot,
                    "field": f,
                    "msk": msk,
                    "removed": anom_count,
                    "remaining": int(len(new_subset)),
                    "note": "Аномалии удалены. Данные для этого "
                            "слота/МСК обновлены.",
                }

            return {"error": f"неизвестный инструмент: {name}"}

        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    return _exec

def _make_tool_executor_4(field, clear, msk_names=None, context=None):
    """Исполнитель инструментов: чтение, автозагрузка, drop_anomalies.

    В context (dict, если передан):
      - plots         list[Figure]     - графики для PDF
      - items         list[dict]       - сводки get_stat
      - analyzed_msks set[str]         - МСК, по которым был get_stat
      - loaded_specs  list[dict]       - {spec, period_days, msk_dates}
    """
    msk_set = set(str(m) for m in (msk_names or []))

    _FIELD_ALIASES = {
        'f': 'Fr', 'fr': 'Fr', 'fs': 'Fs', 'fl': 'FL', 'r': 'R',
        'c0': 'C0', 'c1': 'C1', 'cq': 'C1',
        'l': 'L1', 'l1': 'L1', 'q': 'Q',
    }

    def _as_field(v, default):
        if not isinstance(v, str):
            return default
        v = v.strip()
        if not v:
            return default
        low = v.lower()
        if low in _FIELD_ALIASES:
            return _FIELD_ALIASES[low]
        base = v.split()[0]
        return _FIELD_ALIASES.get(base.lower(), v)

    def _as_slot(v):
        if v is None:
            return 1, None
        if isinstance(v, bool):
            return None, {
                "error": "slot_name должен быть целым числом "
                         "(1, 2, 3, ...), а не boolean",
                "hint": 'Например: {"slot_name": 3, "field": "FL"}',
            }
        if isinstance(v, int):
            slot = v
        elif isinstance(v, float) and v.is_integer():
            slot = int(v)
        elif isinstance(v, str):
            try:
                slot = int(v.strip())
            except ValueError:
                return None, {
                    "error": f"slot_name должен быть ЦЕЛЫМ числом "
                             f"(1, 2, 3, ...). Получено: {v!r}.",
                    "hint": ("slot_name - номер канала (1, 2, 3, ...), "
                             "НЕ имя МСК/спецификации. Если не знаете "
                             "номер - вызовите list_slots."),
                }
        else:
            return None, {
                "error": f"slot_name: неподдерживаемый тип "
                         f"{type(v).__name__}",
                "hint": 'Передайте целое число: {"slot_name": 3}',
            }
        if slot == 0:
            return 1, None
        try:
            active = Statistik.Data.Data.get_active_data()
            valid = sorted(int(x) for x in active['Name'].tolist())
        except Exception:
            valid = [1, 2, 3]
        if slot not in valid:
            return None, {
                "error": f"Слот {slot} не существует",
                "available_slots": valid,
                "hint": (f"Доступные слоты: {valid}. По умолчанию 1, 2, 3. "
                         f"Новый создаётся кнопкой 'Добавить' в "
                         f"'Действия'."),
            }
        return slot, None

    def _get_int(args_dict, keys, default):
        for k in keys:
            if k in args_dict:
                try:
                    return int(args_dict[k])
                except (TypeError, ValueError):
                    pass
        return default

    def _get_bool(args_dict, keys, default=False):
        for k in keys:
            if k in args_dict:
                v = args_dict[k]
                if isinstance(v, bool):
                    return v
                if isinstance(v, str):
                    return v.strip().lower() in ('1', 'true', 'yes', 'y')
                return bool(v)
        return default

    def _exec(name, args):
        try:
            # ---------- args ----------
            if isinstance(args, list):
                return {"error": "args должен быть JSON-объектом (dict), "
                                 "НЕ массивом",
                        "example": '{"slot_name": 3, "field": "FL"}',
                        "you_sent": args}
            if args is None:
                args = {}
            if not isinstance(args, dict):
                return {"error": f"args должен быть dict, "
                                 f"получено {type(args).__name__}"}

            # ---------- list_msks ----------
            if name == "list_msks":
                msks = list(Statistik.Data.Data.get_msk_list().keys())
                if not msks:
                    return {"msks": [],
                            "note": "Нет загруженных МСК. Используйте "
                                    "load_spec."}
                return msks

            # ---------- list_slots ----------
            if name == "list_slots":
                df = Statistik.Data.Data.get_active_data()
                mts = Statistik.Data.Data.get_measure_type_list()
                out = []
                for _, row in df.iterrows():
                    mt = mts[mts['ID'] == row['Value']]
                    mt_name = (mt['Name'].to_string(index=False)
                               if not mt.empty else '?')
                    out.append({'slot': int(row['Name']),
                                'type': mt_name,
                                'use': bool(row.get('Use', False)),
                                'count': int(row.get('Count', 0))})
                return out

            # ---------- list_specs ----------
            if name == "list_specs":
                search = (args.get('search')
                          or args.get('query')
                          or '').strip()
                if not search:
                    return {
                        "error": "search обязателен",
                        "hint": (
                            "Пустой search возвращает первые 20 "
                            "спецификаций по алфавиту — это бесполезно. "
                            "Передайте подстроку имени, например "
                            "{\"search\": \"569\"} или "
                            "{\"search\": \"РК569\"}."
                        ),
                    }
                specs = _find_specs(search, limit=20)
                if not specs:
                    return {"specs": [],
                            "note": f"Спецификации по запросу "
                                    f"{search!r} не найдены"}
                return specs

            # ---------- load_spec ----------
            if name == "load_spec":
                spec_name = (args.get('spec_name')
                             or args.get('name')
                             or args.get('spec'))
                if not spec_name:
                    return {
                        "error": "spec_name обязателен",
                        "hint": ('Например: '
                                 '{"spec_name": "РК507-98,415М-220", '
                                 '"period_days": 30}'),
                    }

                actual = _find_spec(str(spec_name))
                if not actual:
                    candidates = _find_specs(str(spec_name), limit=10)
                    return {"error": f"Спецификация {spec_name!r} "
                                     f"не найдена",
                            "candidates": candidates,
                            "hint": "Уточните имя через list_specs."}

                period_days = _get_int(args,
                                       ('period_days', 'period', 'days'),
                                       30)
                last_n = _get_int(args, ('last_n', 'count', 'limit'), 0)

                result = _auto_load_spec(actual,
                                         last_n=last_n,
                                         period_days=period_days)
                if result.get("error"):
                    return {"error": result["error"]}

                loaded = [x for x in result["loaded"]
                          if x["status"] in ("loaded", "already")]
                if not loaded:
                    return {"error": f"Не удалось загрузить ни одной "
                                     f"МСК для {actual!r}",
                            "details": result}

                msk_set.update(x["msk"] for x in loaded)

                if context is not None:
                    context.setdefault('loaded_specs', []).append({
                        'spec': actual,
                        'period_days': result.get('used_period_days'),
                        'last_n': result.get('used_last_n'),
                        'msk_dates': result.get('msk_dates', {}),
                    })

                return {
                    "spec": actual,
                    "loaded_count": len(loaded),
                    "loaded": loaded,
                    "period_days": period_days,
                    "last_n": last_n,
                    "note": (f"Загружено {len(loaded)} МСК "
                             f"(период: {period_days} дн., лимит: "
                             f"{last_n or 'без ограничения'}). "
                             f"get_stat без msk даст агрегат."),
                }

            # ---------- get_stat ----------
            if name == "get_stat":
                raw_slot = args.get('slot_name', args.get('slot'))
                slot, err = _as_slot(raw_slot)
                if err is not None:
                    return err

                f = _as_field(args.get('field'), field)

                msk_raw = args.get('msk')
                if isinstance(msk_raw, str):
                    msk_raw = msk_raw.strip() or None
                msk = msk_raw

                if msk and msk not in msk_set:
                    actual_spec = _find_spec(msk)
                    if actual_spec:
                        period_days = _get_int(
                            args, ('period_days', 'period', 'days'), 30)
                        last_n = _get_int(
                            args, ('last_n', 'count', 'limit'), 0)
                        load_res = _auto_load_spec(
                            actual_spec,
                            last_n=last_n,
                            period_days=period_days,
                        )
                        loaded = [x for x in load_res["loaded"]
                                  if x["status"] in ("loaded", "already")]
                        if loaded:
                            msk_set.update(x["msk"] for x in loaded)
                            if context is not None:
                                context.setdefault(
                                    'loaded_specs', []).append({
                                    'spec': actual_spec,
                                    'period_days':
                                        load_res.get('used_period_days'),
                                    'last_n': load_res.get('used_last_n'),
                                    'msk_dates':
                                        load_res.get('msk_dates', {}),
                                })
                            msk = None
                            _log(f"[LLM..] auto-loaded spec "
                                 f"{actual_spec!r}: {len(loaded)} MSK "
                                 f"(period={period_days}d)")
                        else:
                            return {
                                "error": f"Спецификация {actual_spec!r} "
                                         f"найдена, но МСК не загрузились",
                                "details": load_res,
                                "hint": "Проверьте наличие запущенных МСК.",
                            }
                    else:
                        msk_low = msk.lower()
                        matches = [m for m in msk_set
                                   if msk_low in m.lower()
                                   or m.lower() in msk_low]
                        if matches:
                            msk = matches[0]
                        else:
                            candidates = _find_specs(msk, limit=10)
                            return {
                                "error": f"МСК/спецификация {msk!r} "
                                         f"не найдена",
                                "candidates": candidates,
                                "available_msks": sorted(msk_set)[:15],
                                "hint": "list_msks или list_specs.",
                            }

                _, _, stat = get_pdf(slot, f, clear, msk)

                # ─── Count == 0: различаем «слот пуст», «поле пустое»,
                #     «комбинация msk+слот пуста» ───
                if int(stat.get('Count', 0) or 0) == 0:
                    df_slot = Statistik.Data.Data.get_data(slot)

                    # (1) Слот содержит данные → выясняем, что именно пусто
                    if df_slot is not None and not df_slot.empty:
                        available = []
                        for col in ('Fr', 'Fs', 'FL', 'R',
                                    'C0', 'C1', 'L1', 'Q'):
                            if col in df_slot.columns:
                                nn = pd.to_numeric(
                                    df_slot[col], errors='coerce'
                                ).dropna()
                                if len(nn) > 0:
                                    available.append(col)

                        field_missing = (f in df_slot.columns
                                         and f not in available)

                        if field_missing:
                            msg = (f"Параметр {f} в слоте {slot} "
                                   f"пуст: в БД нет значений "
                                   f"(строк в слоте: {len(df_slot)}). "
                                   f"Заполнены: "
                                   f"{', '.join(available) or '—'}.")
                            hint = (
                                f"Слот НЕ пустой — в нём {len(df_slot)} "
                                f"строк. Просто параметр {f} для этого "
                                f"слота/МСК не измерялся. Варианты: "
                                f"(1) запросите другой параметр из "
                                f"available_fields; (2) для FL включите "
                                f"'Настройка без ёмкости (FL = Fr)' в "
                                f"окне 'Действия' — FL будет считаться "
                                f"по Fr; (3) другой слот (list_slots). "
                                f"НЕ предлагайте пользователю "
                                f"load_spec — данные уже загружены."
                            )
                            return {
                                "error": msg,
                                "count": 0,
                                "slot_has_data": True,
                                "field_missing": True,
                                "slot_rows": int(len(df_slot)),
                                "available_fields": available,
                                "hint": hint,
                            }

                        # (2) Поле есть, но для этой msk/слота пусто
                        return {
                            "error": (f"Нет данных для slot={slot}, "
                                      f"field={f}"
                                      + (f", msk={msk}" if msk else "")),
                            "count": 0,
                            "slot_has_data": True,
                            "slot_rows": int(len(df_slot)),
                            "available_fields": available,
                            "hint": ("Слот содержит данные, но для этой "
                                     "комбинации параметр/МСК пуст. "
                                     "Проверьте msk (list_msks) или "
                                     "field — available_fields "
                                     "покажет, что реально заполнено."),
                        }

                    # (3) Слот реально пуст — только тут load_spec уместен
                    return {
                        "error": f"Нет данных (slot={slot}, field={f})",
                        "count": 0,
                        "slot_has_data": False,
                        "hint": ("Слот пуст. Загрузите МСК (load_spec) "
                                 "или выберите другой слот (list_slots)."),
                    }

                # ---------- контекст для PDF ----------
                if context is not None:
                    title = f'Слот {slot}, {f}'
                    if msk:
                        title += f', МСК {msk}'
                        context.setdefault('analyzed_msks', set()).add(msk)
                    else:
                        title += ' (все МСК)'
                        for m in msk_set:
                            context.setdefault('analyzed_msks',
                                               set()).add(m)

                    try:
                        fig = LLM._make_stat_plot(slot, f, clear, msk,
                                                  stat, title)
                        if fig is not None:
                            context['plots'].append(fig)
                    except Exception as e:
                        _log(f'[get_stat] plot: {e}')

                    context.setdefault('items', []).append({
                        'title': title,
                        'slot': slot,
                        'field': f,
                        'msk': msk,
                        'stat': dict(stat),
                    })

                return stat

            # ---------- get_norms ----------
            if name == "get_norms":
                result = {}
                for k, v in Statistik.Data.Data.spc_norm.items():
                    if k == 'Status' or not isinstance(v, dict):
                        continue
                    cleaned = {kk: vv for kk, vv in v.items()
                               if vv is not None}
                    if cleaned:
                        result[k] = cleaned
                if not result:
                    return {"error": "нормы не загружены",
                            "hint": "Загрузите спецификацию через "
                                    "load_spec."}
                return result

            # ---------- drop_anomalies ----------
            if name == "drop_anomalies":
                raw_slot = args.get('slot_name', args.get('slot'))
                slot, err = _as_slot(raw_slot)
                if err is not None:
                    return err

                f = _as_field(args.get('field'), field)
                msk_raw = args.get('msk')
                if isinstance(msk_raw, str):
                    msk_raw = msk_raw.strip() or None
                msk = msk_raw
                confirm = _get_bool(args, ('confirm',), False)

                df = Statistik.Data.Data.get_data(slot)
                if df is None or df.empty or f not in df.columns:
                    return {"error": f"Нет данных (slot={slot}, field={f})",
                            "removed": 0, "count": 0}

                # отфильтровать по МСК
                subset = df
                outside = None
                if msk:
                    msk_list = Statistik.Data.Data.get_msk_list()
                    if msk not in msk_list:
                        return {"error": f"МСК {msk!r} не загружена"}
                    msk_slot = msk_list[msk]
                    mrow = msk_slot[msk_slot['Name'] == slot]
                    if mrow.empty:
                        return {"error": f"МСК {msk!r} не содержит "
                                         f"слот {slot}"}
                    try:
                        mid = int(mrow['Mes_ID'].iloc[0])
                    except Exception:
                        mid = 0
                    if mid != 0 and 'Measure_ID' in df.columns:
                        mask = df['Measure_ID'] == mid
                    elif 'MSK' in df.columns:
                        mask = df['MSK'] == str(msk)
                    else:
                        return {"error": "Не удалось отфильтровать по МСК"}
                    subset = df[mask]
                    outside = df[~mask]

                vals = pd.to_numeric(subset[f], errors='coerce')
                valid = vals.dropna()
                valid = valid[valid < 1e12]
                if len(valid) < 3:
                    return {"removed": 0,
                            "remaining": int(len(subset)),
                            "note": "мало данных для IQR (< 3)"}

                Q1 = float(valid.quantile(0.25))
                Q3 = float(valid.quantile(0.75))
                IQR = Q3 - Q1
                lo = Q1 - 1.5 * IQR
                hi = Q3 + 1.5 * IQR
                anom_mask = (vals < lo) | (vals > hi)
                anom_count = int(anom_mask.sum())

                if not confirm:
                    return {
                        "action": "dry_run",
                        "slot": slot,
                        "field": f,
                        "msk": msk,
                        "would_remove": anom_count,
                        "total": int(len(subset)),
                        "bounds": [lo, hi],
                        "note": "Это подсчёт. Для удаления повтори с "
                                "confirm=true. Удаление НЕОБРАТИМО.",
                    }

                # реальное удаление
                keep_mask = ~anom_mask
                new_subset = subset[keep_mask]
                if outside is not None:
                    new_df = pd.concat([outside, new_subset])
                else:
                    new_df = new_subset
                Statistik.Data.Data.set_data(slot, new_df)

                return {
                    "action": "removed",
                    "slot": slot,
                    "field": f,
                    "msk": msk,
                    "removed": anom_count,
                    "remaining": int(len(new_subset)),
                    "note": "Аномалии удалены. Данные для этого "
                            "слота/МСК обновлены.",
                }

            return {"error": f"неизвестный инструмент: {name}"}

        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    return _exec

def _make_tool_executor_1(field, clear, msk_names=None, context=None):
    """Исполнитель инструментов: чтение, автозагрузка, drop_anomalies.

    В context (dict, если передан):
      - plots         list[Figure]     - графики для PDF
      - items         list[dict]       - сводки get_stat
      - analyzed_msks set[str]         - МСК, по которым был get_stat
      - loaded_specs  list[dict]       - {spec, period_days, msk_dates}
    """
    msk_set = set(str(m) for m in (msk_names or []))

    _FIELD_ALIASES = {
        'f': 'Fr', 'fr': 'Fr', 'fs': 'Fs', 'fl': 'FL', 'r': 'R',
        'c0': 'C0', 'c1': 'C1', 'cq': 'C1',
        'l': 'L1', 'l1': 'L1', 'q': 'Q',
    }

    def _as_field(v, default):
        if not isinstance(v, str):
            return default
        v = v.strip()
        if not v:
            return default
        low = v.lower()
        if low in _FIELD_ALIASES:
            return _FIELD_ALIASES[low]
        base = v.split()[0]
        return _FIELD_ALIASES.get(base.lower(), v)

    def _as_slot(v):
        if v is None:
            return 1, None
        if isinstance(v, bool):
            return None, {
                "error": "slot_name должен быть целым числом "
                         "(1, 2, 3, ...), а не boolean",
                "hint": 'Например: {"slot_name": 3, "field": "FL"}',
            }
        if isinstance(v, int):
            slot = v
        elif isinstance(v, float) and v.is_integer():
            slot = int(v)
        elif isinstance(v, str):
            try:
                slot = int(v.strip())
            except ValueError:
                return None, {
                    "error": f"slot_name должен быть ЦЕЛЫМ числом "
                             f"(1, 2, 3, ...). Получено: {v!r}.",
                    "hint": ("slot_name - номер канала (1, 2, 3, ...), "
                             "НЕ имя МСК/спецификации. Если не знаете "
                             "номер - вызовите list_slots."),
                }
        else:
            return None, {
                "error": f"slot_name: неподдерживаемый тип "
                         f"{type(v).__name__}",
                "hint": 'Передайте целое число: {"slot_name": 3}',
            }
        if slot == 0:
            return 1, None
        try:
            active = Statistik.Data.Data.get_active_data()
            valid = sorted(int(x) for x in active['Name'].tolist())
        except Exception:
            valid = [1, 2, 3]
        if slot not in valid:
            return None, {
                "error": f"Слот {slot} не существует",
                "available_slots": valid,
                "hint": (f"Доступные слоты: {valid}. По умолчанию 1, 2, 3. "
                         f"Новый создаётся кнопкой 'Добавить' в "
                         f"'Действия'."),
            }
        return slot, None

    def _get_int(args_dict, keys, default):
        for k in keys:
            if k in args_dict:
                try:
                    return int(args_dict[k])
                except (TypeError, ValueError):
                    pass
        return default

    def _get_bool(args_dict, keys, default=False):
        for k in keys:
            if k in args_dict:
                v = args_dict[k]
                if isinstance(v, bool):
                    return v
                if isinstance(v, str):
                    return v.strip().lower() in ('1', 'true', 'yes', 'y')
                return bool(v)
        return default

    def _exec(name, args):
        try:
            # ---------- args ----------
            if isinstance(args, list):
                return {"error": "args должен быть JSON-объектом (dict), "
                                 "НЕ массивом",
                        "example": '{"slot_name": 3, "field": "FL"}',
                        "you_sent": args}
            if args is None:
                args = {}
            if not isinstance(args, dict):
                return {"error": f"args должен быть dict, "
                                 f"получено {type(args).__name__}"}

            # ---------- list_msks ----------
            if name == "list_msks":
                msks = list(Statistik.Data.Data.get_msk_list().keys())
                if not msks:
                    return {"msks": [],
                            "note": "Нет загруженных МСК. Используйте "
                                    "load_spec."}
                return msks

            # ---------- list_slots ----------
            if name == "list_slots":
                df = Statistik.Data.Data.get_active_data()
                mts = Statistik.Data.Data.get_measure_type_list()
                out = []
                for _, row in df.iterrows():
                    mt = mts[mts['ID'] == row['Value']]
                    mt_name = (mt['Name'].to_string(index=False)
                               if not mt.empty else '?')
                    out.append({'slot': int(row['Name']),
                                'type': mt_name,
                                'use': bool(row.get('Use', False)),
                                'count': int(row.get('Count', 0))})
                return out

            # ---------- list_specs ----------
            if name == "list_specs":
                search = args.get('search') or args.get('query') or ''
                specs = _find_specs(search, limit=20)
                if not specs:
                    return {"specs": [],
                            "note": f"Спецификации по запросу "
                                    f"{search!r} не найдены"}
                return specs

            # ---------- load_spec ----------
            if name == "load_spec":
                spec_name = (args.get('spec_name')
                             or args.get('name')
                             or args.get('spec'))
                if not spec_name:
                    return {
                        "error": "spec_name обязателен",
                        "hint": ('Например: '
                                 '{"spec_name": "РК507-98,415М-220", '
                                 '"period_days": 30}'),
                    }

                actual = _find_spec(str(spec_name))
                if not actual:
                    candidates = _find_specs(str(spec_name), limit=10)
                    return {"error": f"Спецификация {spec_name!r} "
                                     f"не найдена",
                            "candidates": candidates,
                            "hint": "Уточните имя через list_specs."}

                period_days = _get_int(args,
                                       ('period_days', 'period', 'days'),
                                       30)
                last_n = _get_int(args, ('last_n', 'count', 'limit'), 0)

                result = _auto_load_spec(actual,
                                         last_n=last_n,
                                         period_days=period_days)
                if result.get("error"):
                    return {"error": result["error"]}

                loaded = [x for x in result["loaded"]
                          if x["status"] in ("loaded", "already")]
                if not loaded:
                    return {"error": f"Не удалось загрузить ни одной "
                                     f"МСК для {actual!r}",
                            "details": result}

                msk_set.update(x["msk"] for x in loaded)

                if context is not None:
                    context.setdefault('loaded_specs', []).append({
                        'spec': actual,
                        'period_days': result.get('used_period_days'),
                        'last_n': result.get('used_last_n'),
                        'msk_dates': result.get('msk_dates', {}),
                    })

                return {
                    "spec": actual,
                    "loaded_count": len(loaded),
                    "loaded": loaded,
                    "period_days": period_days,
                    "last_n": last_n,
                    "note": (f"Загружено {len(loaded)} МСК "
                             f"(период: {period_days} дн., лимит: "
                             f"{last_n or 'без ограничения'}). "
                             f"get_stat без msk даст агрегат."),
                }

            # ---------- get_stat ----------
            if name == "get_stat":
                raw_slot = args.get('slot_name', args.get('slot'))
                slot, err = _as_slot(raw_slot)
                if err is not None:
                    return err

                f = _as_field(args.get('field'), field)

                msk_raw = args.get('msk')
                if isinstance(msk_raw, str):
                    msk_raw = msk_raw.strip() or None
                msk = msk_raw

                if msk and msk not in msk_set:
                    actual_spec = _find_spec(msk)
                    if actual_spec:
                        period_days = _get_int(
                            args, ('period_days', 'period', 'days'), 30)
                        last_n = _get_int(
                            args, ('last_n', 'count', 'limit'), 0)
                        load_res = _auto_load_spec(
                            actual_spec,
                            last_n=last_n,
                            period_days=period_days,
                        )
                        loaded = [x for x in load_res["loaded"]
                                  if x["status"] in ("loaded", "already")]
                        if loaded:
                            msk_set.update(x["msk"] for x in loaded)
                            if context is not None:
                                context.setdefault(
                                    'loaded_specs', []).append({
                                    'spec': actual_spec,
                                    'period_days':
                                        load_res.get('used_period_days'),
                                    'last_n': load_res.get('used_last_n'),
                                    'msk_dates':
                                        load_res.get('msk_dates', {}),
                                })
                            msk = None
                            _log(f"[LLM..] auto-loaded spec "
                                 f"{actual_spec!r}: {len(loaded)} MSK "
                                 f"(period={period_days}d)")
                        else:
                            return {
                                "error": f"Спецификация {actual_spec!r} "
                                         f"найдена, но МСК не загрузились",
                                "details": load_res,
                                "hint": "Проверьте наличие запущенных МСК.",
                            }
                    else:
                        msk_low = msk.lower()
                        matches = [m for m in msk_set
                                   if msk_low in m.lower()
                                   or m.lower() in msk_low]
                        if matches:
                            msk = matches[0]
                        else:
                            candidates = _find_specs(msk, limit=10)
                            return {
                                "error": f"МСК/спецификация {msk!r} "
                                         f"не найдена",
                                "candidates": candidates,
                                "available_msks": sorted(msk_set)[:15],
                                "hint": "list_msks или list_specs.",
                            }

                _, _, stat = get_pdf(slot, f, clear, msk)

                if int(stat.get('Count', 0) or 0) == 0:
                    what = f"slot={slot}, field={f}"
                    if msk:
                        what += f", msk={msk}"
                    return {
                        "error": f"Нет данных ({what})",
                        "count": 0,
                        "hint": "Данных нет. Загрузите МСК (load_spec) "
                                "или выберите другой слот/параметр.",
                    }

                # ---------- контекст для PDF ----------
                if context is not None:
                    title = f'Слот {slot}, {f}'
                    if msk:
                        title += f', МСК {msk}'
                        context.setdefault('analyzed_msks', set()).add(msk)
                    else:
                        title += ' (все МСК)'
                        for m in msk_set:
                            context.setdefault('analyzed_msks',
                                               set()).add(m)

                    try:
                        fig = LLM._make_stat_plot(slot, f, clear, msk,
                                                  stat, title)
                        if fig is not None:
                            context['plots'].append(fig)
                    except Exception as e:
                        _log(f'[get_stat] plot: {e}')

                    context.setdefault('items', []).append({
                        'title': title,
                        'slot': slot,
                        'field': f,
                        'msk': msk,
                        'stat': dict(stat),
                    })

                return stat

            # ---------- get_norms ----------
            if name == "get_norms":
                result = {}
                for k, v in Statistik.Data.Data.spc_norm.items():
                    if k == 'Status' or not isinstance(v, dict):
                        continue
                    cleaned = {kk: vv for kk, vv in v.items()
                               if vv is not None}
                    if cleaned:
                        result[k] = cleaned
                if not result:
                    return {"error": "нормы не загружены",
                            "hint": "Загрузите спецификацию через "
                                    "load_spec."}
                return result

            # ---------- drop_anomalies ----------
            if name == "drop_anomalies":
                raw_slot = args.get('slot_name', args.get('slot'))
                slot, err = _as_slot(raw_slot)
                if err is not None:
                    return err

                f = _as_field(args.get('field'), field)
                msk_raw = args.get('msk')
                if isinstance(msk_raw, str):
                    msk_raw = msk_raw.strip() or None
                msk = msk_raw
                confirm = _get_bool(args, ('confirm',), False)

                df = Statistik.Data.Data.get_data(slot)
                if df is None or df.empty or f not in df.columns:
                    return {"error": f"Нет данных (slot={slot}, field={f})",
                            "removed": 0, "count": 0}

                # отфильтровать по МСК
                subset = df
                outside = None
                if msk:
                    msk_list = Statistik.Data.Data.get_msk_list()
                    if msk not in msk_list:
                        return {"error": f"МСК {msk!r} не загружена"}
                    msk_slot = msk_list[msk]
                    mrow = msk_slot[msk_slot['Name'] == slot]
                    if mrow.empty:
                        return {"error": f"МСК {msk!r} не содержит "
                                         f"слот {slot}"}
                    try:
                        mid = int(mrow['Mes_ID'].iloc[0])
                    except Exception:
                        mid = 0
                    if mid != 0 and 'Measure_ID' in df.columns:
                        mask = df['Measure_ID'] == mid
                    elif 'MSK' in df.columns:
                        mask = df['MSK'] == str(msk)
                    else:
                        return {"error": "Не удалось отфильтровать по МСК"}
                    subset = df[mask]
                    outside = df[~mask]

                vals = pd.to_numeric(subset[f], errors='coerce')
                valid = vals.dropna()
                valid = valid[valid < 1e12]
                if len(valid) < 3:
                    return {"removed": 0,
                            "remaining": int(len(subset)),
                            "note": "мало данных для IQR (< 3)"}

                Q1 = float(valid.quantile(0.25))
                Q3 = float(valid.quantile(0.75))
                IQR = Q3 - Q1
                lo = Q1 - 1.5 * IQR
                hi = Q3 + 1.5 * IQR
                anom_mask = (vals < lo) | (vals > hi)
                anom_count = int(anom_mask.sum())

                if not confirm:
                    return {
                        "action": "dry_run",
                        "slot": slot,
                        "field": f,
                        "msk": msk,
                        "would_remove": anom_count,
                        "total": int(len(subset)),
                        "bounds": [lo, hi],
                        "note": "Это подсчёт. Для удаления повтори с "
                                "confirm=true. Удаление НЕОБРАТИМО.",
                    }

                # реальное удаление
                keep_mask = ~anom_mask
                new_subset = subset[keep_mask]
                if outside is not None:
                    new_df = pd.concat([outside, new_subset])
                else:
                    new_df = new_subset
                Statistik.Data.Data.set_data(slot, new_df)

                return {
                    "action": "removed",
                    "slot": slot,
                    "field": f,
                    "msk": msk,
                    "removed": anom_count,
                    "remaining": int(len(new_subset)),
                    "note": "Аномалии удалены. Данные для этого "
                            "слота/МСК обновлены.",
                }

            return {"error": f"неизвестный инструмент: {name}"}

        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    return _exec



# ===========================================================================
# NL-запрос (вариант B)
# ===========================================================================
def run_nl_query(sender, data, dpg_):
    """Точка входа. Логика — в _run_nl_query_impl.
    После отправки (успех/ошибка/ранний return) поле очищается."""
    try:
        return _run_nl_query_impl(sender, data, dpg_)
    finally:
        _clear_assistant_input(dpg_)
def _run_nl_query_impl(sender, data, dpg_):
    """Запуск NL-запроса (вариант B) в фоновом потоке.

    Порядок:
      1. Проверка занятости / ввода.
      2. _reload_current_msks() — ТОЛЬКО если
         Statistik.Data.Data.dirty == True (набор МСК или
         конфигурация слотов менялись с прошлого запроса).
         Это устраняет 10–30-секундную блокировку UI на
         каждом вопросе, когда набор данных не менялся.
      3. Снятие контекста UI в главном потоке: параметр,
         флаг clear, имена МСК.
      4. Свежий _LAST_REPORT_CONTEXT.
      5. Исполнитель инструментов.
      6. Запуск LLM.nl_query в AsyncTask + poll-цикл.
    """
    global _ASSISTANT_BUSY, _LAST_REPORT_CONTEXT

    # ---- 1. проверки ввода ----
    if _ASSISTANT_BUSY:
        if dpg_.does_item_exist('assistant_status'):
            dpg_.set_value('assistant_status',
                           'Дождитесь предыдущего ответа...')
        return
    if not dpg_.does_item_exist('assistant_input'):
        return
    text = (dpg_.get_value('assistant_input') or '').strip()
    if not text:
        return

    # ---- 2. reload ТОЛЬКО если данные помечены как устаревшие ----
    # dirty=True ставится в load_msk_dat / del_msk_from_list /
    # clear_all_data. Обычный вопрос без изменения набора МСК
    # больше не блокирует UI на десятки секунд.
    if getattr(Statistik.Data.Data, 'dirty', True):
        try:
            _reload_current_msks()
            Statistik.Data.Data.dirty = False
        except Exception as e:
            _log(f'[run_nl_query] _reload_current_msks: {e}')

    # ---- 3. контекст UI (главный поток) ----
    field = (dpg_.get_value('measure_select')
             if dpg_.does_item_exist('measure_select') else 'Fr')
    clear = (bool(dpg_.get_value('clear_check'))
             if dpg_.does_item_exist('clear_check') else False)
    msk_names = list(Statistik.Data.Data.get_msk_list().keys())

    # ---- 4. свежий контекст для PDF этого запроса ----
    _LAST_REPORT_CONTEXT = {
        'plots': [],
        'items': [],
        'field': field,
        'clear': clear,
        'analyzed_msks': set(),
        'loaded_specs': [],
    }

    # ---- 5. исполнитель инструментов ----
    executor = _make_tool_executor(field, clear, msk_names,
                                   context=_LAST_REPORT_CONTEXT)

    # ---- 6. блокируем кнопку, запускаем worker ----
    _ASSISTANT_BUSY = True
    if dpg_.does_item_exist('assistant_ask_btn'):
        dpg_.configure_item('assistant_ask_btn', enabled=False)
    if dpg_.does_item_exist('assistant_status'):
        dpg_.set_value('assistant_status', 'Думаю...')
    dpg_.set_value('assistant_input', '')

    _append_assistant_log(dpg_, f"Вы: {text}", color=(180, 220, 255))

    _ASSISTANT_TASK.submit(LLM.nl_query, text, executor,
                           msk_names=msk_names, field=field)

    dpg_.set_frame_callback(dpg_.get_frame_count() + 1,
                            lambda: _poll_assistant(dpg_))
def run_nl_query_3(sender, data, dpg_):
    """Запуск NL-запроса (вариант B) в фоновом потоке.

    Порядок действий:
      1. Проверка занятости / ввода.
      2. _reload_current_msks() — очистка данных и перезагрузка всех
         текущих МСК (сохраняя per-MSK конфиг слотов: какие слоты,
         какой Mes_ID). Если МСК не загружено — пропуск.
      3. Снятие контекста UI в ГЛАВНОМ потоке (worker только читает):
         текущий параметр (field), флаг clear, список имён МСК.
      4. Создание свежего _LAST_REPORT_CONTEXT (включая 'clear' —
         нужен _finalize_nl_report для per-MSK графиков).
      5. Создание исполнителя инструментов с этим контекстом.
      6. Запуск LLM.nl_query в AsyncTask + подписка на poll-цикл
         через set_frame_callback.
    """
    global _ASSISTANT_BUSY, _LAST_REPORT_CONTEXT

    # ---- 1. проверки ввода ----
    if _ASSISTANT_BUSY:
        if dpg_.does_item_exist('assistant_status'):
            dpg_.set_value('assistant_status',
                           'Дождитесь предыдущего ответа...')
        return
    if not dpg_.does_item_exist('assistant_input'):
        return
    text = (dpg_.get_value('assistant_input') or '').strip()
    if not text:
        return

    # ---- 2. clear + reload текущих МСК ----
    try:
        _reload_current_msks()
    except Exception as e:
        _log(f'[run_nl_query] _reload_current_msks: {e}')

    # ---- 3. контекст UI (главный поток) ----
    field = (dpg_.get_value('measure_select')
             if dpg_.does_item_exist('measure_select') else 'Fr')
    clear = (bool(dpg_.get_value('clear_check'))
             if dpg_.does_item_exist('clear_check') else False)
    msk_names = list(Statistik.Data.Data.get_msk_list().keys())

    # ---- 4. свежий контекст для PDF этого запроса ----
    _LAST_REPORT_CONTEXT = {
        'plots': [],
        'items': [],
        'field': field,
        'clear': clear,          # нужно _finalize_nl_report для per-MSK
        'analyzed_msks': set(),
        'loaded_specs': [],
    }

    # ---- 5. исполнитель инструментов ----
    executor = _make_tool_executor(field, clear, msk_names,
                                   context=_LAST_REPORT_CONTEXT)

    # ---- 6. блокируем кнопку, запускаем worker ----
    _ASSISTANT_BUSY = True
    if dpg_.does_item_exist('assistant_ask_btn'):
        dpg_.configure_item('assistant_ask_btn', enabled=False)
    if dpg_.does_item_exist('assistant_status'):
        dpg_.set_value('assistant_status', 'Думаю...')
    dpg_.set_value('assistant_input', '')

    _append_assistant_log(dpg_, f"Вы: {text}", color=(180, 220, 255))

    _ASSISTANT_TASK.submit(LLM.nl_query, text, executor,
                           msk_names=msk_names, field=field)

    dpg_.set_frame_callback(dpg_.get_frame_count() + 1,
                            lambda: _poll_assistant(dpg_))




def _reload_current_msks():
    """Очистить данные и заново загрузить текущие МСК.

    Вызывается в начале каждого NL-запроса ассистента. Сохраняет
    per-MSK конфигурацию слотов (какие слоты, какой Mes_ID) на момент
    вызова, чтобы после reload ассистент работал с тем же набором.
    """
    msk_list_orig = dict(Statistik.Data.Data.get_msk_list())
    if not msk_list_orig:
        _log('[_reload_current_msks] нет загруженных МСК — пропуск')
        return

    _log(f'[_reload_current_msks] reload {len(msk_list_orig)} MSK')

    # сохраняем конфиг слотов для каждой МСК до очистки
    slot_cfgs = {
        msk: cfg.copy() for msk, cfg in msk_list_orig.items()
    }

    # очищаем всё (msk_list, data_full, Use/Count)
    Statistik.Data.Data.clear_all_data()

    # загружаем заново
    for msk, slot_cfg in slot_cfgs.items():
        try:
            load_data(msk, slot_cfg)
        except Exception as e:
            _log(f'[_reload_current_msks] {msk}: {e}')

    _log(f'[_reload_current_msks] done. '
         f'data_full keys: {list(Statistik.Data.Data.data_full.keys())}')

def _poll_assistant(dpg_):
    global _ASSISTANT_BUSY
    if not _ASSISTANT_BUSY:
        return
    try:
        res = _ASSISTANT_TASK.poll()
    except Exception as e:
        _log(f'[_poll_assistant] poll error: {e}')
        _ASSISTANT_BUSY = False
        return

    if res is None:
        # перепланируем ТОЛЬКО если задача всё ещё активна
        if _ASSISTANT_BUSY:
            dpg_.set_frame_callback(
                dpg_.get_frame_count() + 1,
                lambda: _poll_assistant(dpg_))
        return

    _ASSISTANT_BUSY = False
    _log(f'[_poll_assistant] result: status={res[0]}')

    if dpg_.does_item_exist('assistant_ask_btn'):
        dpg_.configure_item('assistant_ask_btn', enabled=True)
    if dpg_.does_item_exist('assistant_status'):
        dpg_.set_value('assistant_status', '')

    status, val = res
    try:
        if status == "ok":
            _append_assistant_log(
                dpg_, f"Ассистент: {val}", color=(200, 255, 200))
            _refresh_ui_after_llm(dpg_)
            if _LAST_REPORT_CONTEXT.get('plots'):
                _finalize_nl_report(dpg_)
        else:
            _append_assistant_log(
                dpg_, f"Ошибка LLM: {val}", color=(255, 150, 150))
            LLM.close_figures(_LAST_REPORT_CONTEXT.get('plots'))
            _LAST_REPORT_CONTEXT['plots'] = []
    except Exception as e:
        _log(f'[_poll_assistant] post-processing error: {e}')

def _poll_assistant_4(dpg_):
    global _ASSISTANT_BUSY
    if not _ASSISTANT_BUSY:
        return
    res = _ASSISTANT_TASK.poll()
    if res is None:
        dpg_.set_frame_callback(dpg_.get_frame_count() + 1,
                                lambda: _poll_assistant(dpg_))
        return

    _ASSISTANT_BUSY = False
    if dpg_.does_item_exist('assistant_ask_btn'):
        dpg_.configure_item('assistant_ask_btn', enabled=True)
    if dpg_.does_item_exist('assistant_status'):
        dpg_.set_value('assistant_status', '')

    status, val = res
    if status == "ok":
        _append_assistant_log(dpg_, f"Ассистент: {val}",
                              color=(200, 255, 200))
        _refresh_ui_after_llm(dpg_)
        # NEW: если во время запроса собирались графики - сохраняем PDF
        if _LAST_REPORT_CONTEXT.get('plots'):
            _finalize_nl_report(dpg_)
    else:
        _append_assistant_log(dpg_, f"Ошибка LLM: {val}",
                              color=(255, 150, 150))
        # даже при ошибке закрываем фигуры, если они накопились
        LLM.close_figures(_LAST_REPORT_CONTEXT.get('plots'))
        _LAST_REPORT_CONTEXT['plots'] = []
def _finalize_nl_report(dpg_):
    """Собрать PDF по результатам NL-запроса.

    Структура отчёта:
      1. Шапка (параметр, период, список МСК, число резонаторов).
      2. Таблица 1 — сводная статистика по slot/field (агрегат).
      3. Анализ выбросов (IQR 1.5x).
      4. Детальный текстовый анализ по каждой МСК.
      5. Таблица 2 — статистика по каждой МСК (slot × field × msk).
      6. Графики: сначала агрегатные (ctx['plots']), затем per-MSK.

    Источник данных — модульный _LAST_REPORT_CONTEXT:
      'plots'        — list[Figure]  — агрегатные графики
      'items'        — list[dict]    — сводки get_stat
      'field'        — str           — текущий параметр
      'clear'        — bool          — флаг "удалить аномальные"
      'analyzed_msks'— set[str]      — МСК, по которым считали
      'loaded_specs' — list[dict]    — {spec, period_days, msk_dates, ...}

    get_pdf для per-MSK графика/строки вызывается ОДИН раз: тот же
    stat_msk идёт и в текст, и в таблицу 2, и в график.
    """
    ctx = _LAST_REPORT_CONTEXT
    plots = list(ctx.get('plots') or [])
    items = ctx.get('items') or []
    if not plots and not items:
        return

    field = ctx.get('field') or '—'
    clear = bool(ctx.get('clear', False))
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = _report_path(f"llm_stats_{ts}.pdf")

    # ---- список МСК в анализе ----
    analyzed_msks = sorted(ctx.get('analyzed_msks') or set())
    if not analyzed_msks:
        try:
            analyzed_msks = sorted(
                Statistik.Data.Data.get_msk_list().keys())
        except Exception:
            pass

    # ---- период (по датам загруженных спецификаций) ----
    all_dates = []
    for spec in (ctx.get('loaded_specs') or []):
        for d in (spec.get('msk_dates') or {}).values():
            if d:
                all_dates.append(d)
    try:
        dt_objs = [pd.to_datetime(d, errors='coerce')
                   for d in all_dates]
        dt_objs = [d for d in dt_objs if pd.notna(d)]
        if dt_objs:
            date_from = min(dt_objs).strftime("%Y-%m-%d")
            date_to = max(dt_objs).strftime("%Y-%m-%d")
        else:
            date_from = date_to = '—'
    except Exception:
        date_from = date_to = '—'

    # ---- суммарное число резонаторов ----
    total_res = 0
    for it in items:
        st = it.get('stat') or {}
        total_res += int(st.get('Count', 0) or 0)

    # ---- шапка ----
    header_lines = [
        "=" * 60,
        "LLM-отчёт по статистике",
        "=" * 60,
        f"Параметр: {field}",
        f"Дата отчёта: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Период данных: {date_from} - {date_to}",
        f"МСК в анализе ({len(analyzed_msks)}):",
    ]
    if analyzed_msks:
        chunk = []
        for m in analyzed_msks:
            chunk.append(m)
            if len(chunk) == 4:
                header_lines.append("  " + ", ".join(chunk))
                chunk = []
        if chunk:
            header_lines.append("  " + ", ".join(chunk))
    else:
        header_lines.append("  —")
    header_lines.append(f"Резонаторов в анализе: {total_res}")
    header_lines.append("")

    # ---- утилита форматирования чисел ----
    def _f(v):
        try:
            return f"{float(v):.4g}"
        except (TypeError, ValueError):
            return str(v)

    # ---- таблица 1: сводная по slot/field ----
    table_headers = ['Слот', 'Поле', 'МСК',
                     'N', 'Mean', 'Median', 'StDev',
                     'Min', 'Max', 'Аномалий', 'Выход, %']
    table_rows = []
    for it in items:
        st = it.get('stat') or {}
        msk = it.get('msk') or '(все)'
        table_rows.append([
            str(it.get('slot', '')),
            str(it.get('field', '')),
            str(msk),
            str(int(st.get('Count', 0) or 0)),
            _f(st.get('Mean')),
            _f(st.get('Median')),
            _f(st.get('StDev')),
            _f(st.get('Min')),
            _f(st.get('Max')),
            str(int(st.get('Anomal_count', 0) or 0)),
            _f(st.get('Out')),
        ])

    table_summary = None
    if table_rows:
        table_summary = {
            'title': 'Таблица 1. Сводная статистика',
            'headers': table_headers,
            'rows': table_rows,
        }

    # ---- анализ выбросов ----
    anomaly_lines = ["", "## Анализ аномальных значений", ""]
    total_anomalies = 0
    rows_with_anom = []
    for it in items:
        st = it.get('stat') or {}
        cnt = int(st.get('Anomal_count', 0) or 0)
        total_anomalies += cnt
        if cnt > 0:
            lb = st.get('Lower_bound', 0)
            ub = st.get('Upper_bound', 0)
            try:
                lb_s = f"{float(lb):.4g}"
                ub_s = f"{float(ub):.4g}"
            except (TypeError, ValueError):
                lb_s, ub_s = str(lb), str(ub)
            rows_with_anom.append(
                f"  - {it.get('title', '?')}: {cnt} аномалий "
                f"(вне [{lb_s}, {ub_s}])"
            )
    anomaly_lines.append(
        f"Всего аномальных значений (IQR 1.5x): {total_anomalies}"
    )
    if rows_with_anom:
        anomaly_lines.extend(rows_with_anom)
        anomaly_lines.append("")
        anomaly_lines.append(
            "Для удаления аномалий по конкретному слоту/МСК скажите: "
            "«удали аномалии в слоте N по параметру X»."
        )
    else:
        anomaly_lines.append("Аномальных значений не обнаружено.")

    # ---- детальный анализ по каждой МСК + per-MSK графики + таблица 2 ----
    per_msk_lines = []
    per_msk_plots = []
    per_msk_rows = []

    if analyzed_msks and items:
        per_msk_lines.append("")
        per_msk_lines.append("=" * 60)
        per_msk_lines.append(
            f"Детальный анализ по каждой МСК ({len(analyzed_msks)})"
        )
        per_msk_lines.append("=" * 60)
        per_msk_lines.append("")

        for it in items:
            slot = it.get('slot')
            f = it.get('field')
            if slot is None or f is None:
                continue
            per_msk_lines.append(f"## Слот {slot}, поле {f}")
            per_msk_lines.append("")

            for msk in analyzed_msks:
                try:
                    _, _, stat_msk = get_pdf(slot, f, clear, msk)
                    cnt = int(stat_msk.get('Count', 0) or 0)

                    if cnt == 0:
                        per_msk_lines.append(f"  - {msk}: данных нет")
                        continue

                    per_msk_lines.append(
                        f"  - {msk}: "
                        f"N={cnt}, "
                        f"Mean={stat_msk.get('Mean', 0):.4g}, "
                        f"Median={stat_msk.get('Median', 0):.4g}, "
                        f"StDev={stat_msk.get('StDev', 0):.4g}, "
                        f"Min={stat_msk.get('Min', 0):.4g}, "
                        f"Max={stat_msk.get('Max', 0):.4g}, "
                        f"Выход={stat_msk.get('Out', 0):.2f}%, "
                        f"Аномалий="
                        f"{int(stat_msk.get('Anomal_count', 0) or 0)}"
                    )

                    per_msk_rows.append([
                        str(msk),
                        str(slot),
                        str(f),
                        str(cnt),
                        _f(stat_msk.get('Mean')),
                        _f(stat_msk.get('Median')),
                        _f(stat_msk.get('StDev')),
                        _f(stat_msk.get('Min')),
                        _f(stat_msk.get('Max')),
                        str(int(stat_msk.get('Anomal_count', 0) or 0)),
                        _f(stat_msk.get('Out')),
                    ])

                    try:
                        fig = LLM._make_stat_plot(
                            slot, f, clear, msk, stat_msk,
                            f'Слот {slot}, {f}, МСК {msk}'
                        )
                        if fig is not None:
                            per_msk_plots.append(fig)
                    except Exception as e:
                        _log(f'[_finalize_nl_report] plot {msk}: {e}')
                except Exception as e:
                    per_msk_lines.append(f"  - {msk}: ошибка ({e})")
            per_msk_lines.append("")

    # ---- таблица 2: статистика по каждой МСК ----
    table_per_msk = None
    if per_msk_rows:
        table_per_msk = {
            'title': (f'Таблица 2. Статистика по каждой МСК '
                      f'(параметр {field})'),
            'headers': ['МСК', 'Слот', 'Поле', 'N',
                        'Mean', 'Median', 'StDev',
                        'Min', 'Max', 'Аномалий', 'Выход, %'],
            'rows': per_msk_rows,
        }

    # ---- итоговый текст ----
    text = "\n".join(header_lines + anomaly_lines + per_msk_lines)

    # ---- сохраняем: обе таблицы + все графики ----
    tables_to_save = []
    if table_summary:
        tables_to_save.append(table_summary)
    if table_per_msk:
        tables_to_save.append(table_per_msk)

    all_plots = plots + per_msk_plots

    try:
        ok, msg = LLM.save_report_pdf(
            text, path,
            plots=all_plots,
            table=tables_to_save or None,
        )
    except Exception as e:
        _log(f'[_finalize_nl_report] save_report_pdf: {e}')
        ok, msg = False, str(e)

    # освобождаем matplotlib-фигуры в любом случае
    try:
        LLM.close_figures(all_plots)
    except Exception:
        pass
    ctx['plots'] = []

    if ok:
        _append_assistant_log(
            dpg_,
            (f"PDF: {path}  "
             f"(графиков: {len(all_plots)}, "
             f"таблиц: {len(tables_to_save)})"),
            color=(180, 220, 180),
        )
        try:
            LLM.open_file(path)
        except Exception as e:
            _log(f'[_finalize_nl_report] open_file: {e}')
    else:
        _append_assistant_log(dpg_, f"PDF не создан: {msg}",
                              color=(255, 150, 150))




# ===========================================================================
# Генератор отчёта (вариант A) -> PDF
# ===========================================================================
def run_llm_report(sender, data, dpg_):
    global _REPORT_BUSY, _REPORT_CANCEL
    if _REPORT_BUSY:
        show_message('Отчёт уже генерируется', dpg_)
        return

    msk_list = list(Statistik.Data.Data.get_msk_list().keys())
    if not msk_list:
        show_message('Нет добавленных МСК', dpg_)
        return

    field = (dpg_.get_value('measure_select')
             if dpg_.does_item_exist('measure_select') else 'Fr')
    clear = (bool(dpg_.get_value('clear_check'))
             if dpg_.does_item_exist('clear_check') else False)

    _REPORT_BUSY = True
    _REPORT_CANCEL = False
    if dpg_.does_item_exist('llm_report_btn'):
        dpg_.configure_item('llm_report_btn', enabled=False)
    if dpg_.does_item_exist('llm_report_stop_btn'):
        dpg_.configure_item('llm_report_stop_btn', enabled=True)
    if dpg_.does_item_exist('msk_text_label'):
        dpg_.set_value('msk_text_label', 'LLM: генерация отчёта...')

    while not _REPORT_PROGRESS.empty():
        _REPORT_PROGRESS.get_nowait()

    _REPORT_TASK.submit(_build_report_worker, field, clear, msk_list,
                        _REPORT_PROGRESS)
    dpg_.set_frame_callback(dpg_.get_frame_count() + 1,
                            lambda: _poll_report(dpg_))


def stop_llm_report(sender, data, dpg_):
    global _REPORT_CANCEL
    _REPORT_CANCEL = True
    if dpg_.does_item_exist('msk_text_label'):
        dpg_.set_value('msk_text_label', 'LLM: остановка...')

def _build_report_worker(field, clear, msk_list, progress_q):
    active = Statistik.Data.Data.get_active_data()
    slots = active[active['Use'] == True]
    mts = Statistik.Data.Data.get_measure_type_list()

    total = len(slots) * (1 + len(msk_list))
    done = 0
    figures = []
    lines = [
        "=" * 60,
        f"LLM-анализ: {len(slots)} слотов x {len(msk_list)} МСК",
        f"Параметр: {field}",
        f"Модель:   {LLM.MODEL_NAME}",
        "=" * 60,
    ]

    for _, srow in slots.iterrows():
        if _REPORT_CANCEL:
            lines.append("\n[ОСТАНОВЛЕНО ПОЛЬЗОВАТЕЛЕМ]")
            break
        slot = int(srow['Name'])
        mt = mts[mts['ID'] == srow['Value']]
        slot_label = (mt['Name'].to_string(index=False)
                      if not mt.empty else str(slot))

        try:
            _, _, stat_all = get_pdf(slot, field, clear)
            norms = Statistik.Data.Data.get_spc_norm(field)
            summary = LLM.summarize_msk("(все МСК)", slot_label,
                                        field, stat_all, norms)
            if int(stat_all.get('Count', 0) or 0) > 0:
                fig = LLM._make_stat_plot(
                    slot, field, clear, None, stat_all,
                    f'Слот {slot} - {slot_label}, все МСК')
                if fig is not None:
                    figures.append(fig)
        except Exception as e:
            stat_all, summary = {}, f"[ошибка: {e}]"

        done += 1
        progress_q.put(f"слот {slot}: общая ({done}/{total})")

        lines.append("")
        lines.append(f"### Слот {slot} - {slot_label} (все МСК)")
        lines.append(f"Статистика: {_fmt_stat(stat_all)}")
        lines.append(f"Анализ: {summary}")

        for msk in msk_list:
            if _REPORT_CANCEL:
                lines.append("  [остановлено]")
                return {"text": "\n".join(lines), "plots": figures}
            try:
                _, _, stat = get_pdf(slot, field, clear, msk)
                if int(stat.get('Count', 0) or 0) == 0:
                    continue
                s = LLM.summarize_msk(msk, slot_label, field, stat, norms)
                lines.append("")
                lines.append(f"  --- {msk} ---")
                lines.append(f"  Статистика: {_fmt_stat(stat)}")
                lines.append(f"  Анализ: {s}")
                fig = LLM._make_stat_plot(
                    slot, field, clear, msk, stat,
                    f'Слот {slot} - {slot_label}, МСК {msk}')
                if fig is not None:
                    figures.append(fig)
            except Exception as e:
                lines.append(f"  --- {msk} --- ошибка: {e}")
            done += 1
            progress_q.put(f"слот {slot} / {msk} ({done}/{total})")

    return {"text": "\n".join(lines), "plots": figures}


def _poll_report(dpg_):
    global _REPORT_BUSY
    last = None
    try:
        while True:
            last = _REPORT_PROGRESS.get_nowait()
    except queue.Empty:
        pass
    if last and dpg_.does_item_exist('msk_text_label'):
        dpg_.set_value('msk_text_label', f'LLM: {last}')

    if not _REPORT_BUSY:
        return
    res = _REPORT_TASK.poll()
    if res is None:
        dpg_.set_frame_callback(dpg_.get_frame_count() + 1,
                                lambda: _poll_report(dpg_))
        return

    _REPORT_BUSY = False
    if dpg_.does_item_exist('llm_report_btn'):
        dpg_.configure_item('llm_report_btn', enabled=True)
    if dpg_.does_item_exist('llm_report_stop_btn'):
        dpg_.configure_item('llm_report_stop_btn', enabled=False)
    if dpg_.does_item_exist('msk_text_label'):
        dpg_.set_value('msk_text_label', 'МСК')

    status, val = res
    if status != "ok":
        show_message(f'Ошибка отчёта: {val}', dpg_)
        return

    if isinstance(val, dict):
        text = val.get('text', '')
        plots = val.get('plots', [])
    else:
        text = val
        plots = []

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    pdf_name = _report_path(f"llm_report_{ts}.pdf")  # было: f"llm_report_{ts}.pdf"

    ok, msg = LLM.save_report_pdf(text, pdf_name, plots=plots)
    LLM.close_figures(plots)

    if ok:
        show_message(f'PDF-отчёт сохранён: {pdf_name}', dpg_)
        print(f"[LLM] PDF сохранён: {pdf_name}")
        LLM.open_file(pdf_name)
        return

    txt_name = _report_path(f"llm_report_{ts}.txt")  # было: f"llm_report_{ts}.txt"
    try:
        with open(txt_name, 'w', encoding='utf-8') as f:
            f.write(text)
        show_message(f'PDF не удалось ({msg}). TXT: {txt_name}', dpg_)
    except Exception as e:
        show_message(f'Ошибка записи: {e}', dpg_)

def _build_report_worker_1(field, clear, msk_list, progress_q):
    active = Statistik.Data.Data.get_active_data()
    slots = active[active['Use'] == True]
    mts = Statistik.Data.Data.get_measure_type_list()

    total = len(slots) * (1 + len(msk_list))
    done = 0
    lines = [
        "=" * 60,
        f"LLM-анализ: {len(slots)} слотов x {len(msk_list)} МСК",
        f"Параметр: {field}",
        f"Модель:   {LLM.MODEL_NAME}",
        "=" * 60,
    ]

    for _, srow in slots.iterrows():
        if _REPORT_CANCEL:
            lines.append("\n[ОСТАНОВЛЕНО ПОЛЬЗОВАТЕЛЕМ]")
            break
        slot = int(srow['Name'])
        mt = mts[mts['ID'] == srow['Value']]
        slot_label = (mt['Name'].to_string(index=False)
                      if not mt.empty else str(slot))

        try:
            _, _, stat_all = get_pdf(slot, field, clear)
            norms = Statistik.Data.Data.get_spc_norm(field)
            summary = LLM.summarize_msk("(все МСК)", slot_label,
                                        field, stat_all, norms)
        except Exception as e:
            stat_all, summary = {}, f"[ошибка: {e}]"
        done += 1
        progress_q.put(f"слот {slot}: общая ({done}/{total})")

        lines.append("")
        lines.append(f"### Слот {slot} - {slot_label} (все МСК)")
        lines.append(f"Статистика: {_fmt_stat(stat_all)}")
        lines.append(f"Анализ: {summary}")

        for msk in msk_list:
            if _REPORT_CANCEL:
                lines.append("  [остановлено]")
                return "\n".join(lines)
            try:
                _, _, stat = get_pdf(slot, field, clear, msk)
                if int(stat.get('Count', 0) or 0) == 0:
                    continue
                s = LLM.summarize_msk(msk, slot_label, field, stat, norms)
                lines.append("")
                lines.append(f"  --- {msk} ---")
                lines.append(f"  Статистика: {_fmt_stat(stat)}")
                lines.append(f"  Анализ: {s}")
            except Exception as e:
                lines.append(f"  --- {msk} --- ошибка: {e}")
            done += 1
            progress_q.put(f"слот {slot} / {msk} ({done}/{total})")

    return "\n".join(lines)


def _fmt_stat(stat):
    if not stat:
        return "нет данных"
    keys = ['Count', 'Out', 'Bad_Count', 'Anomal_count',
            'Max', 'Min', 'Mean', 'Median', 'StDev']
    parts = []
    for k in keys:
        v = stat.get(k)
        if isinstance(v, (int, float)):
            parts.append(f"{k}={v:.4g}")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts)


def _poll_report_1(dpg_):
    global _REPORT_BUSY
    last = None
    try:
        while True:
            last = _REPORT_PROGRESS.get_nowait()
    except queue.Empty:
        pass
    if last and dpg_.does_item_exist('msk_text_label'):
        dpg_.set_value('msk_text_label', f'LLM: {last}')

    if not _REPORT_BUSY:
        return
    res = _REPORT_TASK.poll()
    if res is None:
        dpg_.set_frame_callback(dpg_.get_frame_count() + 1,
                                lambda: _poll_report(dpg_))
        return

    _REPORT_BUSY = False
    if dpg_.does_item_exist('llm_report_btn'):
        dpg_.configure_item('llm_report_btn', enabled=True)
    if dpg_.does_item_exist('llm_report_stop_btn'):
        dpg_.configure_item('llm_report_stop_btn', enabled=False)
    if dpg_.does_item_exist('msk_text_label'):
        dpg_.set_value('msk_text_label', 'МСК')

    status, val = res
    if status != "ok":
        show_message(f'Ошибка отчёта: {val}', dpg_)
        return

    # --- PDF с fallback на TXT ---
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    pdf_name = f"llm_report_{ts}.pdf"
    ok, msg = LLM.save_report_pdf(val, pdf_name)
    if ok:
        show_message(f'PDF-отчёт сохранён: {pdf_name}', dpg_)
        print(f"[LLM] PDF сохранён: {pdf_name}")
        return

    txt_name = f"llm_report_{ts}.txt"
    try:
        with open(txt_name, 'w', encoding='utf-8') as f:
            f.write(val)
        show_message(f'PDF не удалось ({msg}). TXT: {txt_name}', dpg_)
        print(f"[LLM] PDF не удалось ({msg}), сохранён TXT: {txt_name}")
    except Exception as e:
        show_message(f'Ошибка записи: {e}', dpg_)