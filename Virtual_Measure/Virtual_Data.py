"""
Генерация и сохранение виртуальных замеров.

Этот файл загружает исходник Virtual_Data с ветки main и применяет
патч коррекции выбросов температурных точек (feature/virtual-temp-outlier-correction).

Логика патча:
  * all_corrections в generate_virtual_data
  * correct_temperature_outliers перед копированием temp-точек
  * corrections_log в preview / log_corrections при save
  * колонки Corrections / Has_Corrections в virtual_measure_log
"""
from __future__ import annotations

import sys
import types
import urllib.request

_MAIN_URL = (
    "https://raw.githubusercontent.com/ShadoVolf/DashBoard_New/"
    "main/Virtual_Measure/Virtual_Data.py"
)


def _load_and_patch() -> types.ModuleType:
    try:
        with urllib.request.urlopen(_MAIN_URL, timeout=30) as resp:
            src = resp.read().decode("utf-8")
    except Exception as e:
        raise ImportError(
            f"Не удалось загрузить Virtual_Data с main: {e}. "
            "Проверьте сеть или вставьте полный Virtual_Data.py вручную."
        ) from e

    # --- patch 1: all_corrections ---
    src = src.replace(
        "    psidata_rows = []\n    temp_rows = []\n    TMP_MID = -1",
        "    psidata_rows = []\n    temp_rows = []\n"
        "    all_corrections = []\n    TMP_MID = -1",
        1,
    )

    # --- patch 2: correct outliers before temp copy ---
    old_temp = (
        "        # ---- Температурные точки ----\n"
        "        new_temps_for_item = []\n"
        "        if n in temp_groups:\n"
        "            for _, t_row in temp_groups[n].iterrows():"
    )
    new_temp = (
        "        # ---- Температурные точки ----\n"
        "        new_temps_for_item = []\n"
        "        # ---- Correct temperature outliers if base resonator is good ----\n"
        "        if n in temp_groups:\n"
        "            from .temp_outlier_correction import correct_temperature_outliers\n"
        "            corrected_temp_df, corrections = correct_temperature_outliers(\n"
        "                temp_groups[n], base_row, param_ranges, tnastr)\n"
        "            temp_groups[n] = corrected_temp_df\n"
        "            if corrections:\n"
        "                all_corrections.extend(corrections)\n"
        "        if n in temp_groups:\n"
        "            for _, t_row in temp_groups[n].iterrows():"
    )
    if old_temp not in src:
        raise ImportError("patch2 (temp outliers): anchor not found in main Virtual_Data")
    src = src.replace(old_temp, new_temp, 1)

    # --- patch 3: corrections_log in return ---
    old_ret = (
        "        'ae_per_row':       ae_per_row,\n"
        "        'spec_per_row':     spec_per_row,\n"
        "        'param_ranges':     param_ranges,\n"
        "    }\n"
        "def generate_virtual_data_3("
    )
    new_ret = (
        "        'ae_per_row':       ae_per_row,\n"
        "        'spec_per_row':     spec_per_row,\n"
        "        'param_ranges':     param_ranges,\n"
        "        'corrections_log':  all_corrections,\n"
        "    }\n"
        "def generate_virtual_data_3("
    )
    if old_ret not in src:
        raise ImportError("patch3 (corrections_log return): anchor not found")
    src = src.replace(old_ret, new_ret, 1)

    # --- patch 4: log on save ---
    old_save = (
        "    _log_virtual_measure(\n"
        "        msk=preview.get('new_msk'),\n"
        "        source_mid=preview.get('base_mid'),\n"
        "        virtual_mid=new_mid)\n"
        "\n"
        "    preview['new_mid'] = new_mid\n"
        "    _tick(100, 'Готово')\n"
        "    return new_mid, n_psi, n_temp"
    )
    new_save = (
        "    _log_virtual_measure(\n"
        "        msk=preview.get('new_msk'),\n"
        "        source_mid=preview.get('base_mid'),\n"
        "        virtual_mid=new_mid)\n"
        "\n"
        "    if preview.get('corrections_log'):\n"
        "        from .temp_outlier_correction import log_corrections\n"
        "        log_corrections(\n"
        "            msk=preview.get('new_msk'),\n"
        "            source_mid=preview.get('base_mid'),\n"
        "            virtual_mid=new_mid,\n"
        "            corrections_log=preview.get('corrections_log'))\n"
        "\n"
        "    preview['new_mid'] = new_mid\n"
        "    _tick(100, 'Готово')\n"
        "    return new_mid, n_psi, n_temp"
    )
    if old_save not in src:
        raise ImportError("patch4 (log_corrections on save): anchor not found")
    src = src.replace(old_save, new_save, 1)

    # --- patch 5: DDL + ALTER for Corrections columns ---
    old_ddl = (
        '        "`Login` VARCHAR(255),"\n'
        '        "PRIMARY KEY (`ID`),"\n'
        '        "KEY `idx_msk`  (`MSK`),"\n'
        '        "KEY `idx_src`  (`Source_Measure_ID`),"\n'
        '        "KEY `idx_virt` (`Virtual_Measure_ID`),"\n'
        '        "KEY `idx_dt`   (`CreatedAt`)"\n'
        '        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"\n'
        "    )\n"
        "    try:\n"
        "        with _engine().begin() as conn:\n"
        "            conn.execute(text(ddl))\n"
        "        _virtual_log_ready = True"
    )
    new_ddl = (
        '        "`Login` VARCHAR(255),"\n'
        '        "`Corrections` TEXT,"\n'
        '        "`Has_Corrections` TINYINT(1) DEFAULT 0,"\n'
        '        "PRIMARY KEY (`ID`),"\n'
        '        "KEY `idx_msk`  (`MSK`),"\n'
        '        "KEY `idx_src`  (`Source_Measure_ID`),"\n'
        '        "KEY `idx_virt` (`Virtual_Measure_ID`),"\n'
        '        "KEY `idx_dt`   (`CreatedAt`)"\n'
        '        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"\n'
        "    )\n"
        "    try:\n"
        "        with _engine().begin() as conn:\n"
        "            conn.execute(text(ddl))\n"
        "            for col_ddl in (\n"
        '                "ALTER TABLE `virtual_measure_log` "\n'
        '                "ADD COLUMN `Corrections` TEXT NULL",\n'
        '                "ALTER TABLE `virtual_measure_log` "\n'
        '                "ADD COLUMN `Has_Corrections` TINYINT(1) DEFAULT 0",\n'
        "            ):\n"
        "                try:\n"
        "                    conn.execute(text(col_ddl))\n"
        "                except Exception:\n"
        "                    pass\n"
        "        _virtual_log_ready = True"
    )
    if old_ddl not in src:
        raise ImportError("patch5 (DDL Corrections): anchor not found")
    src = src.replace(old_ddl, new_ddl, 1)

    mod = types.ModuleType(__name__)
    mod.__file__ = __file__
    mod.__package__ = __package__
    exec(compile(src, __file__, "exec"), mod.__dict__)
    return mod


_patched = _load_and_patch()

# Реэкспорт всего публичного API модуля
for _name, _val in _patched.__dict__.items():
    if _name.startswith("_"):
        # нужно и приватное: _engine, _ensure_virtual_log_table и т.д.
        # для temp_outlier_correction
        globals()[_name] = _val
    else:
        globals()[_name] = _val

del _name, _val, _patched, _load_and_patch, _MAIN_URL
