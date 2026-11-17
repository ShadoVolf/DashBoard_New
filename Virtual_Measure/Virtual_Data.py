"""
Генерация и сохранение виртуальных замеров.

Алгоритм:
    * берётся базовый Measure_ID;
    * для каждого изделия загружаются значения psidata и psidatatemp;
    * определяется спецификация и диапазоны [Min, Max] активных
      параметров (spc_map_table + specification);
    * для каждого параметра генерируется новое значение с малым
      отклонением. Если preserve_status=True, новое значение
      подбирается так, чтобы попадание в [Min, Max] совпало с
      базовым;
    * температурные точки пересчитываются с тем же относительным
      коэффициентом по частоте и сопротивлению — производные
      характеристики (Fmax, Fmin, Fptp, Fmaxm, Mono, Slope, Rmax,
      Rmin, RcRb) вычисляются из новых температурных точек;
    * создаётся новая запись в psi_measure_id;
    * все psidata-строки помечаются Virtual_Data = 1;
    * psidatatemp сохраняется без этого флага;
    * пишется запись в журнал virtual_measure_log.
"""
import random
import re
from typing import Optional
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from Archive_View.Archive_Data import load_spc_map_for_archive, load_specification
from Options import get_connection_string

import pandas as pd
from sqlalchemy import create_engine, text
import traceback          # ← добавить

try:
    from Authorization.Login import LoginUser
except Exception:
    LoginUser = None


# ============================================================================
# Кэш соединения и справочников
# ============================================================================
_ENGINE = None
_PARAM_TABLE = None
_FIELD_MAP = None


def _ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(str(get_connection_string()))
    return _ENGINE


def _param_table():
    global _PARAM_TABLE
    if _PARAM_TABLE is not None:
        return _PARAM_TABLE
    try:
        _PARAM_TABLE = pd.read_sql(
            "SELECT * FROM spc_map_table ORDER BY ID", _engine())
    except Exception as e:
        print(f"[Virtual] spc_map_table error: {e}")
        _PARAM_TABLE = pd.DataFrame()
    return _PARAM_TABLE


def _field_map():
    global _FIELD_MAP
    if _FIELD_MAP is not None:
        return _FIELD_MAP
    try:
        df = pd.read_sql(
            "SELECT Parameter, Field FROM psidata_map_table", _engine())
        _FIELD_MAP = {
            str(p): str(f) for p, f in zip(df['Parameter'], df['Field'])
            if pd.notna(p) and pd.notna(f)
        }
    except Exception as e:
        print(f"[Virtual] psidata_map_table error: {e}")
        _FIELD_MAP = {}
    return _FIELD_MAP


# ============================================================================
# Мелкие утилиты
# ============================================================================
def _safe_float(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() in ('no', 'nan', 'false', ''):
            return None
        try:
            return float(s.replace(',', '.'))
        except (ValueError, TypeError):
            return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_str(v):
    if v is None:
        return ''
    try:
        if pd.isna(v):
            return ''
    except (TypeError, ValueError):
        pass
    return str(v)


def get_operator() -> str:
    try:
        if LoginUser and getattr(LoginUser, 'login', None):
            v = str(LoginUser.login[3]).strip()
            if v:
                return v
    except Exception:
        pass
    return 'system'


def get_login_user_for_log() -> str:
    """
    Логин пользователя для журнала — как в редакторе спецификаций
    (LoginUser.login[0] = ФИО).
    """
    try:
        if LoginUser and getattr(LoginUser, 'login', None):
            val = str(LoginUser.login[0]).strip()
            if val:
                return val
    except Exception:
        pass
    return "unknown"


# ============================================================================
# Справочники для каскада
# ============================================================================
def get_rtypes() -> list:
    try:
        print(f"[Virtual {_ts()}] get_rtypes: start", flush=True)
        df = pd.read_sql(
            "SELECT `Type` FROM resonatortype ORDER BY `Type`",
            _engine())
        result = df['Type'].dropna().tolist()
        print(f"[Virtual {_ts()}] get_rtypes: {len(result)} типов",
              flush=True)
        return result
    except Exception as e:
        import traceback
        print(f"[Virtual {_ts()}] ERROR get_rtypes: {e}", flush=True)
        traceback.print_exc()
        return []


def get_spcs(rtype: str) -> list:
    if not rtype:
        print(f"[Virtual {_ts()}] get_spcs: пустой rtype", flush=True)
        return []
    try:
        print(f"[Virtual {_ts()}] get_spcs: start rtype='{rtype}'",
              flush=True)
        df = pd.read_sql(
            text("SELECT `Name` FROM specification WHERE NameR = :t "
                 "ORDER BY `Name`"),
            _engine(), params={'t': rtype})
        result = df['Name'].dropna().tolist()
        print(f"[Virtual {_ts()}] get_spcs: "
              f"rtype='{rtype}' -> {len(result)} спц", flush=True)
        return result
    except Exception as e:
        import traceback
        print(f"[Virtual {_ts()}] ERROR get_spcs(rtype='{rtype}'): {e}",
              flush=True)
        traceback.print_exc()
        return []


def get_msks(spc: str) -> list:
    if not spc:
        print(f"[Virtual {_ts()}] get_msks: пустой spc", flush=True)
        return []
    try:
        t0 = datetime.now()
        print(f"[Virtual {_ts()}] get_msks: start spc='{spc}'",
              flush=True)
        df = pd.read_sql(
            text("SELECT DISTINCT MSK FROM psidata "
                 "WHERE Spc = :s AND MSK IS NOT NULL ORDER BY MSK"),
            _engine(), params={'s': spc})
        result = df['MSK'].dropna().tolist()
        dt = (datetime.now() - t0).total_seconds()
        print(f"[Virtual {_ts()}] get_msks: "
              f"spc='{spc}' -> {len(result)} МСК за {dt:.2f}s",
              flush=True)
        return result
    except Exception as e:
        import traceback
        print(f"[Virtual {_ts()}] ERROR get_msks(spc='{spc}'): {e}",
              flush=True)
        traceback.print_exc()
        return []


def get_measure_ids(msk: str) -> list:
    if not msk:
        print(f"[Virtual {_ts()}] get_measure_ids: пустой msk",
              flush=True)
        return []
    try:
        t0 = datetime.now()
        print(f"[Virtual {_ts()}] get_measure_ids: start msk='{msk}'",
              flush=True)
        df = pd.read_sql(
            text("SELECT DISTINCT Measure_ID FROM psidata "
                 "WHERE MSK = :m AND Measure_ID IS NOT NULL "
                 "ORDER BY Measure_ID"),
            _engine(), params={'m': msk})
        result = [int(x) for x in df['Measure_ID'].dropna().tolist()]
        dt = (datetime.now() - t0).total_seconds()
        print(f"[Virtual {_ts()}] get_measure_ids: "
              f"msk='{msk}' -> {len(result)} замеров за {dt:.2f}s",
              flush=True)
        return result
    except Exception as e:
        import traceback
        print(f"[Virtual {_ts()}] ERROR get_measure_ids(msk='{msk}'): "
              f"{e}", flush=True)
        traceback.print_exc()
        return []


# ============================================================================
# Справочник установок измерения
# ============================================================================
def get_machine_types() -> list:
    try:
        df = pd.read_sql(
            "SELECT DISTINCT `Type` FROM machines "
            "WHERE `Function`='Measure' AND `Type` IS NOT NULL "
            "ORDER BY `Type`", _engine())
        return df['Type'].dropna().astype(str).tolist()
    except Exception as e:
        print(f"[Virtual] machine types error: {e}")
        return []


_PSIDATA_TO_MACHINES = {
    'W2200':   'Saunders',
    'CNA-300': 'Transat',
}


def get_machines_for_type(type_name: str) -> pd.DataFrame:
    if not type_name:
        return pd.DataFrame()
    type_name = _PSIDATA_TO_MACHINES.get(type_name, type_name)
    try:
        return pd.read_sql(
            text("SELECT `ID`, `IP`, `Name`, `Type`, `Serial_N`, "
                 "`Call_Date`, `M_Type`, `PoverKa` "
                 "FROM machines "
                 "WHERE `Function`='Measure' AND `Type`=:t "
                 "ORDER BY `Serial_N`"),
            _engine(), params={'t': type_name})
    except Exception as e:
        print(f"[Virtual] machines_for_type error: {e}")
        return pd.DataFrame()


def build_machine_info(row) -> dict:
    return {
        'MachineType':       _safe_str(row.get('Type')),
        'Machine_Serial':    _safe_str(row.get('Serial_N')),
        'Machine_Call_Date': _safe_str(row.get('Call_Date')),
        'Machine_ID':        _safe_str(row.get('ID')),
        'M_Type':            int(_safe_float(row.get('M_Type')) or 0),
        'PoverKa':           1 if _safe_float(row.get('PoverKa')) else 0,
    }


# ============================================================================
# Загрузка базовых данных
# ============================================================================
def load_base_psidata(measure_id: int) -> pd.DataFrame:
    try:
        return pd.read_sql(
            text("SELECT * FROM psidata WHERE Measure_ID = :m "
                 "ORDER BY N"),
            _engine(), params={'m': measure_id})
    except Exception as e:
        print(f"[Virtual] load_base_psidata error: {e}")
        return pd.DataFrame()


def load_base_temp(measure_id: int) -> pd.DataFrame:
    try:
        return pd.read_sql(
            text("SELECT * FROM psidatatemp WHERE Measure_ID = :m "
                 "ORDER BY N, Temp"),
            _engine(), params={'m': measure_id})
    except Exception as e:
        print(f"[Virtual] load_base_temp error: {e}")
        return pd.DataFrame()


def load_spec(spc_name: str) -> Optional[pd.Series]:
    if not spc_name:
        return None
    try:
        df = pd.read_sql(
            text("SELECT * FROM specification WHERE Name = :n"),
            _engine(), params={'n': spc_name})
        return df.iloc[0] if not df.empty else None
    except Exception as e:
        print(f"[Virtual] load_spec error: {e}")
        return None


# ============================================================================
# Параметры спецификации
# ============================================================================
def build_param_ranges(spec_row) -> list:
    if spec_row is None:
        return []
    spc_map = _param_table()
    fmap = _field_map()
    result = []
    for _, row in spc_map.iterrows():
        use_field = _safe_str(row.get('Use'))
        if not use_field:
            continue
        use_val = _safe_str(spec_row.get(use_field)).lower()
        if use_val not in ('true', '1', 'yes'):
            continue
        param_name = _safe_str(row.get('Parameter_Name'))
        if not param_name:
            continue
        min_field = _safe_str(row.get('Min'))
        max_field = _safe_str(row.get('Max'))
        min_v = _safe_float(spec_row.get(min_field)) if min_field else None
        max_v = _safe_float(spec_row.get(max_field)) if max_field else None
        result.append({
            'param':   param_name,
            'field':   fmap.get(param_name, param_name),
            'min':     min_v,
            'max':     max_v,
            'has_min': min_v is not None,
            'has_max': max_v is not None,
        })
    return result


# ============================================================================
# Проверка и генерация
# ============================================================================
def _in_spec(val, mn, mx):
    if val is None:
        return None
    if mn is not None and val < mn:
        return False
    if mx is not None and val > mx:
        return False
    return True


def _delta_max(base_val, settings):
    v = settings.get('variance', {})
    use_abs = bool(v.get('use_absolute', False))
    pct = abs(float(v.get('max_delta_percent', 0.5)))
    abs_val = abs(float(v.get('max_delta_absolute', 0.05)))
    if use_abs:
        return abs_val
    if base_val is None:
        return 0.0
    d = abs(float(base_val)) * pct / 100.0
    if d < 1e-12:
        d = abs_val
    return d


def generate_value(base_val, min_v, max_v, settings,
                   attempts: int = None,
                   param_name: str = None,
                   rtype: str = None) -> Optional[float]:
    """
    Сгенерировать значение с отклонением ±delta_max.

    Порядок:
      1. Отсечка 0-маркера (0 вне [min,max] → NaN).
      2. preserve_status=False → uniform-отклонение.
      3. preserve_status=True + MLP включён → MLP-предсказание.
      4. Иначе — brute-force перебор.
    """
    if base_val is None:
        return base_val
    try:
        if isinstance(base_val, float) and np.isnan(base_val):
            return base_val
    except (TypeError, ValueError):
        pass

    # ---- Отсечка 0-маркера ----
    try:
        fv_base = float(base_val)
        if fv_base == 0.0:
            eps = 1e-12
            zero_out_of_spec = (
                    (min_v is not None and min_v > eps)
                    or (max_v is not None and max_v < -eps)
            )
            if zero_out_of_spec:
                return float('nan')
    except (TypeError, ValueError):
        pass

    v = settings.get('variance', {})
    nn = settings.get('nn', {})
    preserve = bool(v.get('preserve_status', True))

    delta_max = _delta_max(base_val, settings)
    if delta_max <= 0 and not preserve:
        return base_val

    base_in = _in_spec(base_val, min_v, max_v)

    # ---- Без сохранения статуса ----
    if not preserve:
        if delta_max <= 0:
            return base_val
        return base_val + random.uniform(-delta_max, delta_max)

    # ---- Stage 1: MLP ----
    if nn.get('mlp_enabled', False):
        try:
            from . import Virtual_NN
            pred = Virtual_NN.predict_new_value(
                base_val, min_v, max_v,
                min_v is not None, max_v is not None,
                base_in,
                param_name=param_name,
                rtype=rtype)
            if pred is not None and delta_max > 0:
                pred = max(base_val - delta_max,
                           min(base_val + delta_max, pred))
                if _in_spec(pred, min_v, max_v) == base_in:
                    return pred
        except Exception as e:
            print(f"[Virtual] MLP fallback: {e}", flush=True)

    # ---- Fallback: brute-force ----
    if attempts is None:
        attempts = int(v.get('max_attempts', 64))
    if delta_max <= 0:
        return base_val

    for _ in range(attempts):
        d = random.uniform(-delta_max, delta_max)
        cand = base_val + d
        if _in_spec(cand, min_v, max_v) == base_in:
            return cand

    eps = abs(delta_max) * 1e-3 + 1e-12
    if base_in:
        lo = base_val - delta_max
        hi = base_val + delta_max
        if min_v is not None:
            lo = max(lo, min_v + eps)
        if max_v is not None:
            hi = min(hi, max_v - eps)
        if lo > hi:
            return base_val
        return random.uniform(lo, hi)
    else:
        if min_v is not None and base_val < min_v:
            hi = min_v - eps
            lo = min(base_val - delta_max, hi - delta_max)
            return random.uniform(lo, hi)
        if max_v is not None and base_val > max_v:
            lo = max_v + eps
            hi = max(base_val + delta_max, lo + delta_max)
            return random.uniform(lo, hi)
    return base_val


# ============================================================================
# Парсинг номеров
# ============================================================================
_NUM_SPLIT = re.compile(r'[,;\s]+')
_NUM_RANGE = re.compile(r'^([A-Za-z]*)(\d+)\s*-\s*([A-Za-z]*)(\d+)$')


def parse_numbers_input(text) -> list | None:
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None

    result = set()
    for part in _NUM_SPLIT.split(text):
        part = part.strip()
        if not part:
            continue

        m = _NUM_RANGE.match(part)
        if m:
            pre1, n1, pre2, n2 = m.groups()
            prefix = (pre1 or pre2 or '').upper()
            try:
                a, b = int(n1), int(n2)
            except ValueError:
                result.add(part.upper())
                continue
            if a > b:
                a, b = b, a
            width = max(len(n1), len(n2))
            if b - a > 10000:
                b = a + 10000
            for i in range(a, b + 1):
                result.add(f"{prefix}{i:0{width}d}")
        else:
            result.add(part.upper())

    return sorted(result) if result else None


def get_all_numbers(measure_id) -> list:
    if not measure_id:
        return []
    try:
        df = pd.read_sql(
            text("SELECT DISTINCT N FROM psidata WHERE Measure_ID = :m "
                 "AND N IS NOT NULL ORDER BY N"),
            _engine(), params={'m': measure_id})
        return df['N'].dropna().astype(str).tolist()
    except Exception as e:
        print(f"[Virtual] get_all_numbers error: {e}")
        return []


def peek_next_measure_id() -> int:
    try:
        df = pd.read_sql(
            "SELECT COALESCE(MAX(MeasureID), 0) + 1 AS next_id "
            "FROM psi_measure_id", _engine())
        return int(df['next_id'].iloc[0]) if not df.empty else 1
    except Exception as e:
        print(f"[Virtual] peek_next_measure_id error: {e}")
        return 1


# ============================================================================
# Создание Measure_ID (5 fallback-вариантов)
# ============================================================================
def create_measure_id(new_msk: str, file_name: str,
                      operator: str, file_id: str = '') -> Optional[int]:
    eng = _engine()

    variants = [
        ("""
            INSERT INTO psi_measure_id
                (MSK, File, Operator, Program_Type, File_ID, ProtokolN)
            VALUES (:msk, :file, :op, 'VirtualMeasure', :fid, :ptype)
        """, {
            'msk': new_msk, 'file': file_name, 'op': operator,
            'fid': file_id or '', 'ptype': 'Виртуальный',
        }),
        ("""
            INSERT INTO psi_measure_id
                (MSK, File, Operator, Program_Type)
            VALUES (:msk, :file, :op, 'VirtualMeasure')
        """, {
            'msk': new_msk, 'file': file_name, 'op': operator,
        }),
        ("""
            INSERT INTO psi_measure_id (MSK, File)
            VALUES (:msk, :file)
        """, {
            'msk': new_msk, 'file': file_name,
        }),
        ("""
            INSERT INTO psi_measure_id (MSK, File, File_ID)
            VALUES (:msk, :file, :fid)
        """, {
            'msk': new_msk, 'file': file_name, 'fid': file_id or '',
        }),
        ("""
            INSERT INTO psi_measure_id (MSK) VALUES (:msk)
        """, {
            'msk': new_msk,
        }),
    ]

    for idx, (sql_str, params) in enumerate(variants):
        try:
            with eng.begin() as conn:
                r = conn.execute(text(sql_str), params)
                new_id = int(r.lastrowid)
                print(f"[Virtual] create_measure_id: ok, variant={idx}, "
                      f"id={new_id}")
                return new_id
        except Exception as e:
            print(f"[Virtual] create_measure_id: variant={idx} failed: "
                  f"{e}")
            continue

    print("[Virtual] create_measure_id: все варианты провалились")
    return None


# ============================================================================
# Проверка производных коэффициентов
# ============================================================================
def _check_F_derivatives(base_row, range_by_param, ratio, settings):
    if not settings.get('variance', {}).get('preserve_status', True):
        return ratio
    F_DERIVED = ('Fmax', 'Fmin', 'Fptp', 'Fptp_2', 'Fmaxm',
                 'Mono', 'Slope', 'MonoT', 'FT', 'Ft1', 'Ft2',
                 'Ft3', 'Ft4')
    for _ in range(16):
        ok = True
        for p in F_DERIVED:
            pr = range_by_param.get(p)
            if pr is None:
                continue
            base_v = _safe_float(base_row.get(p))
            if base_v is None:
                continue
            new_v = base_v * ratio
            base_in = _in_spec(base_v, pr['min'], pr['max'])
            new_in = _in_spec(new_v, pr['min'], pr['max'])
            if base_in != new_in:
                ok = False
                break
        if ok:
            return ratio
        ratio = 1.0 + (ratio - 1.0) * 0.5
    return 1.0


def _check_R_derivatives(base_row, range_by_param, ratio, settings):
    if not settings.get('variance', {}).get('preserve_status', True):
        return ratio
    for _ in range(16):
        ok = True
        for p in ('Rmax', 'Rmin', 'Rmax-Rmin', 'RcRb'):
            pr = range_by_param.get(p)
            if pr is None:
                continue
            base_v = _safe_float(base_row.get(p))
            if base_v is None:
                continue
            new_v = base_v * ratio
            base_in = _in_spec(base_v, pr['min'], pr['max'])
            new_in = _in_spec(new_v, pr['min'], pr['max'])
            if base_in != new_in:
                ok = False
                break
        if ok:
            return ratio
        ratio = 1.0 + (ratio - 1.0) * 0.5
    return 1.0


# ============================================================================
# Пересчёт производных из температурных точек
# ============================================================================
def _recompute_derived_from_temps(new_psidata, new_temps, base_row,
                                   range_by_param, new_F, tnastr):
    if not new_temps:
        return

    fs = [t['F'] for t in new_temps
          if t.get('F') is not None]
    if fs:
        Fmax = max(fs)
        Fmin = min(fs)
        Fptp = Fmax - Fmin
        new_psidata['Fmax']   = Fmax
        new_psidata['Fmin']   = Fmin
        new_psidata['Fptp']   = Fptp
        new_psidata['Fptp_2'] = Fptp / 2.0

        ref_F = new_F
        if ref_F is None:
            ref_F = _safe_float(base_row.get('Fn'))
        if ref_F is None:
            ref_F = _safe_float(base_row.get('F'))
        if ref_F is None:
            for t in new_temps:
                if (t.get('Temp') is not None
                        and abs(t['Temp'] - tnastr) < 0.1
                        and t.get('F') is not None):
                    ref_F = t['F']
                    break
        if ref_F is None:
            ref_F = Fmin

        dmax = Fmax - ref_F
        dmin = Fmin - ref_F
        new_psidata['Fmaxm'] = dmax if abs(dmax) >= abs(dmin) else dmin

    rs = [t['R'] for t in new_temps
          if t.get('R') is not None]
    if rs:
        Rmax = max(rs)
        Rmin = min(rs)
        new_psidata['Rmax']      = Rmax
        new_psidata['Rmin']      = Rmin
        new_psidata['Rmax-Rmin'] = Rmax - Rmin

    rc_rb_max = None
    for t in new_temps:
        R_t = t.get('R')
        Rb_t = t.get('Rb')
        if R_t and Rb_t and Rb_t > 0:
            v = R_t / Rb_t
            if rc_rb_max is None or v > rc_rb_max:
                rc_rb_max = v
    if rc_rb_max is not None:
        new_psidata['RcRb'] = rc_rb_max

    # ------------------------------------------------------------------
    # C0_C1 / C1_2C0 — из psidata C0 и C1 (то, что реально видит
    # пользователь в таблице). Раньше считалось из температурных
    # C0/Cq — и не совпадало с psidata.C0 / psidata.Cq, из-за чего
    # C0_C1 в предпросмотре не бился с C0 и C1 (и строка ложно
    # браковалась по C0_C1).
    #
    # Формула та же, что в C++: C0_C1 = C0 / (C1 * 1e-3),
    # C1_2C0 = (C1 * 1e-3) / (2 * C0) * 1e6.
    # ------------------------------------------------------------------
    c0_field = None
    c1_field = None
    for _pr in range_by_param.values():
        if _pr['param'] == 'C0':
            c0_field = _pr['field']
        elif _pr['param'] == 'C1':
            c1_field = _pr['field']
    if not c0_field:
        c0_field = 'C0'
    if not c1_field:
        c1_field = _field_map().get('C1', 'C1')

    c0_p = _safe_float(new_psidata.get(c0_field))
    cq_p = _safe_float(new_psidata.get(c1_field))
    if (c0_p is not None and c0_p != 0
            and cq_p is not None and cq_p != 0):
        new_psidata['C0_C1'] = c0_p / (cq_p * 1e-3)
        new_psidata['C1_2C0'] = (
            (cq_p * 1e-3) / (2 * c0_p) * 1e6)

    base_F_val = _safe_float(base_row.get('F'))
    if (base_F_val is not None
            and abs(base_F_val) > 1e-12
            and new_F is not None):
        f_ratio = new_F / base_F_val
        for p in ('Mono', 'Slope', 'MonoT', 'FT',
                  'Ft1', 'Ft2', 'Ft3', 'Ft4'):
            base_v = _safe_float(base_row.get(p))
            if base_v is not None:
                new_psidata[p] = base_v * f_ratio

def _recompute_derived_from_temps_1(new_psidata, new_temps, base_row,
                                   range_by_param, new_F, tnastr):
    if not new_temps:
        return

    fs = [t['F'] for t in new_temps
          if t.get('F') is not None]
    if fs:
        Fmax = max(fs)
        Fmin = min(fs)
        Fptp = Fmax - Fmin
        new_psidata['Fmax']   = Fmax
        new_psidata['Fmin']   = Fmin
        new_psidata['Fptp']   = Fptp
        new_psidata['Fptp_2'] = Fptp / 2.0

        ref_F = new_F
        if ref_F is None:
            ref_F = _safe_float(base_row.get('Fn'))
        if ref_F is None:
            ref_F = _safe_float(base_row.get('F'))
        if ref_F is None:
            for t in new_temps:
                if (t.get('Temp') is not None
                        and abs(t['Temp'] - tnastr) < 0.1
                        and t.get('F') is not None):
                    ref_F = t['F']
                    break
        if ref_F is None:
            ref_F = Fmin

        dmax = Fmax - ref_F
        dmin = Fmin - ref_F
        new_psidata['Fmaxm'] = dmax if abs(dmax) >= abs(dmin) else dmin

    rs = [t['R'] for t in new_temps
          if t.get('R') is not None]
    if rs:
        Rmax = max(rs)
        Rmin = min(rs)
        new_psidata['Rmax']      = Rmax
        new_psidata['Rmin']      = Rmin
        new_psidata['Rmax-Rmin'] = Rmax - Rmin

    rc_rb_max = None
    for t in new_temps:
        R_t = t.get('R')
        Rb_t = t.get('Rb')
        if R_t and Rb_t and Rb_t > 0:
            v = R_t / Rb_t
            if rc_rb_max is None or v > rc_rb_max:
                rc_rb_max = v
    if rc_rb_max is not None:
        new_psidata['RcRb'] = rc_rb_max

    for t in new_temps:
        T = t.get('Temp')
        if T is not None and abs(T - tnastr) < 0.1:
            c0 = t.get('C0')
            cq = t.get('Cq')
            if c0 is not None and cq and cq != 0:
                new_psidata['C0_C1'] = c0 / (cq * 1e-3)
                if c0 != 0:
                    new_psidata['C1_2C0'] = (
                        (cq * 1e-3) / (2 * c0) * 1e6)
            break

    base_F_val = _safe_float(base_row.get('F'))
    if (base_F_val is not None
            and abs(base_F_val) > 1e-12
            and new_F is not None):
        f_ratio = new_F / base_F_val
        for p in ('Mono', 'Slope', 'MonoT', 'FT',
                  'Ft1', 'Ft2', 'Ft3', 'Ft4'):
            base_v = _safe_float(base_row.get(p))
            if base_v is not None:
                new_psidata[p] = base_v * f_ratio


# ============================================================================
# Генерация виртуального замера БЕЗ сохранения
# ============================================================================
def generate_virtual_data(
        base_measure_id: int,
        new_msk: str,
        file_name: str = None,
        operator: str = None,
        settings: dict = None,
        only_good: bool = False,
        selected_numbers: list = None,
        machine_info: dict = None,
        progress_cb=None) -> dict | None:

    def _tick(percent, message):
        if progress_cb:
            try:
                progress_cb(percent, message)
            except Exception:
                pass

    if settings is None:
        from .Virtual_Settings import load_settings
        settings = load_settings()
    if operator is None:
        operator = get_operator()

    nn_cfg = settings.get('nn', {}) or {}

    # ---- 1. Базовый замер ----
    _tick(2, 'Загрузка базового замера...')
    base_df = load_base_psidata(base_measure_id)
    if base_df.empty:
        print(f"[Virtual] base {base_measure_id} empty")
        return None

    base_file_id = _safe_str(base_df.iloc[0].get('File_ID'))
    temp_df = load_base_temp(base_measure_id)

    # ---- 2. Спецификация (ДО фильтров — для разбраковки) ----
    _tick(8, 'Загрузка спецификации...')
    spc_name = _safe_str(base_df.iloc[0].get('Spc'))
    spec_row = load_spec(spc_name)
    if spec_row is None:
        print(f"[Virtual] specification '{spc_name}' not found")
        return None

    rtype = _safe_str(spec_row.get('NameR'))
    param_ranges = build_param_ranges(spec_row)
    if not param_ranges:
        print(f"[Virtual] no active parameters in spec '{spc_name}'")
        return None

    tnastr = _safe_float(spec_row.get('Tnastr'))
    if tnastr is None:
        tnastr = 25.0

    range_by_param = {r['param']: r for r in param_ranges}

    # ---- 3. selected_numbers ----
    if selected_numbers:
        sel_set = {str(n).strip().upper() for n in selected_numbers}
        base_df = base_df[
            base_df['N'].astype(str).str.strip().str.upper()
            .isin(sel_set)
        ].reset_index(drop=True)
        if base_df.empty:
            print("[Virtual] no base rows match selected numbers")
            return None

    # ---- 4. only_good: разбраковка по спецификации ----
    if only_good:
        spec_ok_mask = _compute_spec_status_df(base_df, param_ranges)
        base_df = base_df[spec_ok_mask].reset_index(drop=True)
        if base_df.empty:
            print("[Virtual] no Good items in base (по спецификации)")
            return None

    F_DERIVED = {
        'Fmax', 'Fmin', 'Fptp', 'Fptp_2', 'Fmaxm',
        'Mono', 'Slope', 'MonoT',
        'FT', 'Ft1', 'Ft2', 'Ft3', 'Ft4',
        'F_max_int', 'F_min_int',
        'F0-Fl', 'Ftgk',
        'Fs_ppm', 'Fl_ppm', 'FL_Num',
    }
    R_DERIVED = {'Rmax', 'Rmin', 'Rmax-Rmin', 'RcRb'}

    if not file_name:
        file_name = f"VIRT_{new_msk}_{base_measure_id}"

    temp_groups = {}
    if not temp_df.empty:
        for n_val, g in temp_df.groupby('N', sort=False):
            temp_groups[n_val] = g.reset_index(drop=True)

    total = len(base_df)
    psidata_rows = []
    temp_rows = []
    TMP_MID = -1

    _tick(10, f'Генерация значений (изделий: {total})...')

    # ---- 5. Итерация по изделиям ----
    for idx, (_, base_row) in enumerate(base_df.iterrows()):
        if progress_cb and (idx % 10 == 0 or idx == total - 1):
            _tick(
                10 + int(idx / max(total, 1) * 80),
                f'Обработка изделия {idx + 1}/{total}')

        n = _safe_str(base_row.get('N'))

        # ---- F ----
        base_F = _safe_float(base_row.get('F'))
        pr_F = range_by_param.get('F')
        new_F = generate_value(
            base_F,
            pr_F['min'] if pr_F else None,
            pr_F['max'] if pr_F else None,
            settings, param_name='F', rtype=rtype)
        if new_F is None:
            new_F = base_F
        if base_F is not None and abs(base_F) > 1e-12:
            F_ratio = new_F / base_F
        else:
            F_ratio = 1.0
        F_ratio = _check_F_derivatives(
            base_row, range_by_param, F_ratio, settings)
        if base_F is not None:
            new_F = base_F * F_ratio

        # ---- R ----
        base_R = _safe_float(base_row.get('R'))
        pr_R = range_by_param.get('R')
        new_R = generate_value(
            base_R,
            pr_R['min'] if pr_R else None,
            pr_R['max'] if pr_R else None,
            settings, param_name='R', rtype=rtype)
        if new_R is None:
            new_R = base_R
        if base_R is not None and abs(base_R) > 1e-12:
            R_ratio = new_R / base_R
        else:
            R_ratio = 1.0
        R_ratio = _check_R_derivatives(
            base_row, range_by_param, R_ratio, settings)
        if base_R is not None:
            new_R = base_R * R_ratio

        # ---- Прямые параметры ----
        other_values = {}
        for pr in param_ranges:
            p = pr['param']
            if p in ('F', 'R', 'Fn'):
                continue
            if p in F_DERIVED or p in R_DERIVED:
                continue
            base_v = _safe_float(base_row.get(pr['field']))
            if base_v is None:
                base_v = _safe_float(base_row.get(p))
            other_values[p] = generate_value(
                base_v, pr['min'], pr['max'], settings,
                param_name=p, rtype=rtype)

        # ---- psidata row ----
        new_psidata = base_row.to_dict()
        new_psidata['Measure_ID']   = TMP_MID
        new_psidata['MSK']          = new_msk
        new_psidata['File']         = file_name
        new_psidata['Operator']     = operator
        new_psidata['Virtual_Data'] = 1

        if machine_info:
            for key in ('MachineType', 'Machine_Serial',
                        'Machine_Call_Date', 'Machine_ID',
                        'M_Type', 'PoverKa'):
                if key in new_psidata:
                    new_psidata[key] = machine_info.get(key)

        if new_F is not None:
            if 'F' in new_psidata:
                new_psidata['F'] = new_F
            if 'Fn' in new_psidata:
                new_psidata['Fn'] = new_F

        if new_R is not None and 'R' in new_psidata:
            new_psidata['R'] = new_R

        for p, v in other_values.items():
            pr = range_by_param.get(p)
            field = pr['field'] if pr else p
            if field in new_psidata:
                new_psidata[field] = v
            if p in new_psidata:
                new_psidata[p] = v

        # ---- ▼ Карта новых значений по psidata-полю ----
        # Нужна для когерентной генерации температурных C0/Cq/Q/L:
        # значение на tnastr должно совпадать с psidata, а на
        # других температурах — пропорционально новому psidata.
        new_by_field = {}
        for _p, _v in other_values.items():
            _pr = range_by_param.get(_p)
            _field = _pr['field'] if _pr else _p
            new_by_field[_field] = _v
        if new_F is not None:
            new_by_field['F'] = new_F
            new_by_field['Fn'] = new_F
        if new_R is not None:
            new_by_field['R'] = new_R

        # ---- Температурные точки ----
        new_temps_for_item = []
        if n in temp_groups:
            for _, t_row in temp_groups[n].iterrows():
                new_t = t_row.to_dict()
                new_t['Measure_ID'] = TMP_MID
                new_t['MSK']        = new_msk
                new_t['File']       = file_name

                T        = _safe_float(t_row.get('Temp'))
                base_F_t = _safe_float(t_row.get('F'))
                base_R_t = _safe_float(t_row.get('R'))

                if base_F_t is not None:
                    if T is not None and abs(T - tnastr) < 0.1:
                        new_t['F'] = (new_F if new_F is not None
                                      else base_F_t)
                    else:
                        new_t['F'] = base_F_t * F_ratio

                if base_R_t is not None:
                    new_t['R'] = base_R_t * R_ratio

                base_FL = _safe_float(t_row.get('FL'))
                if base_FL is not None:
                    new_t['FL'] = base_FL * F_ratio

                base_Rb = _safe_float(t_row.get('Rb'))
                if base_Rb is not None:
                    new_t['Rb'] = base_Rb * R_ratio

                # ---- C0/Cq/Q/L — когерентно с psidata ----
                #   * на tnastr      → new_psidata-значение;
                #   * на других T   → base_temp * (new_psidata / base_psidata);
                #   * поля нет в спеке → fallback на прежнюю генерацию
                #     (с правильным param_name, найденным по field).
                for field in ('C0', 'Cq', 'Q', 'L'):
                    base_v = _safe_float(t_row.get(field))
                    if base_v is None:
                        continue

                    new_psidata_v = new_by_field.get(field)
                    if new_psidata_v is None:
                        pr = next(
                            (x for x in param_ranges
                             if x['field'] == field), None)
                        new_psidata_v = generate_value(
                            base_v,
                            pr['min'] if pr else None,
                            pr['max'] if pr else None,
                            settings,
                            param_name=pr['param'] if pr else field,
                            rtype=rtype)

                    if new_psidata_v is None:
                        continue

                    base_psidata_v = _safe_float(
                        base_row.get(field))
                    T_t = _safe_float(t_row.get('Temp'))

                    if (T_t is not None
                            and abs(T_t - tnastr) < 0.1):
                        new_t[field] = new_psidata_v
                    elif (base_psidata_v is not None
                          and abs(base_psidata_v) > 1e-12):
                        ratio = new_psidata_v / base_psidata_v
                        new_t[field] = base_v * ratio
                    else:
                        new_t[field] = new_psidata_v

                new_temps_for_item.append(new_t)

        # ---- Fallback F/Fn ----
        if new_F is None:
            for t in new_temps_for_item:
                if (t.get('Temp') is not None
                        and abs(t['Temp'] - tnastr) < 0.1
                        and t.get('F') is not None):
                    if 'F' in new_psidata:
                        new_psidata['F'] = t['F']
                    if 'Fn' in new_psidata:
                        new_psidata['Fn'] = t['F']
                    break

        # ---- Производные ----
        _recompute_derived_from_temps(
            new_psidata, new_temps_for_item, base_row,
            range_by_param, new_F, tnastr)

        psidata_rows.append(new_psidata)
        temp_rows.extend(new_temps_for_item)

    # ============================================================
    # 5a. ПЕРЕСЧЁТ Status / Status2 / spec_per_row
    # ============================================================
    spec_per_row = []
    if psidata_rows:
        _tick(90, 'Разбраковка по спецификации...')
        df_check = pd.DataFrame(psidata_rows)

        ok_series   = _compute_spec_status_df(df_check, param_ranges)
        per_field   = _compute_per_field_status_df(df_check, param_ranges)

        for i, ok in enumerate(ok_series.tolist()):
            psidata_rows[i]['Status']  = 1 if ok else 0
            psidata_rows[i]['Status2'] = 'Good' if ok else 'Bad'

        for i in range(len(psidata_rows)):
            row_status = {}
            for field, ser in per_field.items():
                row_status[field] = bool(ser.iloc[i])
            spec_per_row.append(row_status)

    # ---- 6. AE-валидация ----
    ae_summary = {}
    ae_per_row = {}

    if nn_cfg.get('autoenc_enabled', False) and psidata_rows:
        _tick(93, 'Проверка реалистичности (Autoencoder)...')
        try:
            from . import Virtual_NN

            thr_override = nn_cfg.get('autoenc_threshold')
            if thr_override is not None:
                try:
                    thr_override = float(thr_override)
                    if thr_override <= 0:
                        thr_override = None
                except (TypeError, ValueError):
                    thr_override = None

            if Virtual_NN.is_autoenc_available(rtype, spc=spc_name):
                scores = []
                anomalies = 0
                threshold = None
                skipped = 0
                diag_budget = 3

                for row_idx, r in enumerate(psidata_rows):
                    try:
                        score, is_anom, thr, per_f = \
                            Virtual_NN.autoenc_score(
                                r, rtype=rtype, spc=spc_name,
                                diagnostic=(diag_budget > 0),
                                threshold_override=thr_override)
                    except Exception:
                        score, is_anom, thr, per_f = \
                            None, False, None, {}

                    if score is None:
                        skipped += 1
                        continue

                    scores.append(score)
                    if is_anom:
                        anomalies += 1
                        if diag_budget > 0:
                            diag_budget -= 1
                    if threshold is None:
                        threshold = thr

                    ae_per_row[row_idx] = {
                        'score':       score,
                        'is_anom':     is_anom,
                        'threshold':   thr,
                        'per_feature': per_f,
                    }

                if scores:
                    thr_str = (f"{threshold:.3f}"
                               if threshold is not None else "n/a")
                    ovr_str = ("из настроек"
                               if thr_override is not None
                               else "из модели")
                    ae_summary = {
                        'mean_score':    sum(scores) / len(scores),
                        'max_score':     max(scores),
                        'anomaly_count': anomalies,
                        'total':         len(scores),
                        'skipped':       skipped,
                        'threshold':     threshold,
                        'threshold_src': ovr_str,
                    }
                    print(
                        f"[Virtual {_ts()}] AE (rtype='{rtype}', "
                        f"spc='{spc_name}'): "
                        f"mean={ae_summary['mean_score']:.3f}, "
                        f"max={ae_summary['max_score']:.3f}, "
                        f"anomalies={anomalies}/{len(scores)}, "
                        f"skipped={skipped}, "
                        f"threshold={thr_str} ({ovr_str})",
                        flush=True)
            else:
                print(f"[Virtual {_ts()}] AE: модель не найдена для "
                      f"spc='{spc_name}', rtype='{rtype}'", flush=True)
        except Exception as e:
            print(f"[Virtual {_ts()}] AE validation error: {e}",
                  flush=True)
            import traceback
            traceback.print_exc()

    _tick(95, 'Подготовка предпросмотра...')

    return {
        'psidata_rows':     psidata_rows,
        'temp_rows':        temp_rows,
        'base_mid':         base_measure_id,
        'new_msk':          new_msk,
        'file_name':        file_name,
        'operator':         operator,
        'spc_name':         spc_name,
        'spec_row':         spec_row,
        'base_file_id':     base_file_id,
        'rtype':            rtype,
        'selected_numbers': selected_numbers,
        'n_psidata':        len(psidata_rows),
        'n_psidatatemp':    len(temp_rows),
        'only_good':        only_good,
        'settings':         settings,
        'machine_info':     machine_info or {},
        'ae_validation':    ae_summary,
        'ae_per_row':       ae_per_row,
        'spec_per_row':     spec_per_row,
        'param_ranges':     param_ranges,
    }
def generate_virtual_data_3(
        base_measure_id: int,
        new_msk: str,
        file_name: str = None,
        operator: str = None,
        settings: dict = None,
        only_good: bool = False,
        selected_numbers: list = None,
        machine_info: dict = None,
        progress_cb=None) -> dict | None:

    def _tick(percent, message):
        if progress_cb:
            try:
                progress_cb(percent, message)
            except Exception:
                pass

    if settings is None:
        from .Virtual_Settings import load_settings
        settings = load_settings()
    if operator is None:
        operator = get_operator()

    nn_cfg = settings.get('nn', {}) or {}

    # ---- 1. Базовый замер ----
    _tick(2, 'Загрузка базового замера...')
    base_df = load_base_psidata(base_measure_id)
    if base_df.empty:
        print(f"[Virtual] base {base_measure_id} empty")
        return None

    base_file_id = _safe_str(base_df.iloc[0].get('File_ID'))
    temp_df = load_base_temp(base_measure_id)

    # ---- 2. Спецификация (ДО фильтров — для разбраковки) ----
    _tick(8, 'Загрузка спецификации...')
    spc_name = _safe_str(base_df.iloc[0].get('Spc'))
    spec_row = load_spec(spc_name)
    if spec_row is None:
        print(f"[Virtual] specification '{spc_name}' not found")
        return None

    rtype = _safe_str(spec_row.get('NameR'))
    param_ranges = build_param_ranges(spec_row)
    if not param_ranges:
        print(f"[Virtual] no active parameters in spec '{spc_name}'")
        return None

    tnastr = _safe_float(spec_row.get('Tnastr'))
    if tnastr is None:
        tnastr = 25.0

    range_by_param = {r['param']: r for r in param_ranges}

    # ---- 3. selected_numbers ----
    if selected_numbers:
        sel_set = {str(n).strip().upper() for n in selected_numbers}
        base_df = base_df[
            base_df['N'].astype(str).str.strip().str.upper()
            .isin(sel_set)
        ].reset_index(drop=True)
        if base_df.empty:
            print("[Virtual] no base rows match selected numbers")
            return None

    # ---- 4. only_good: разбраковка по спецификации (НЕ по Status2 psidata) ----
    if only_good:
        spec_ok_mask = _compute_spec_status_df(base_df, param_ranges)
        base_df = base_df[spec_ok_mask].reset_index(drop=True)
        if base_df.empty:
            print("[Virtual] no Good items in base (по спецификации)")
            return None

    F_DERIVED = {
        'Fmax', 'Fmin', 'Fptp', 'Fptp_2', 'Fmaxm',
        'Mono', 'Slope', 'MonoT',
        'FT', 'Ft1', 'Ft2', 'Ft3', 'Ft4',
        'F_max_int', 'F_min_int',
        'F0-Fl', 'Ftgk',
        'Fs_ppm', 'Fl_ppm', 'FL_Num',
    }
    R_DERIVED = {'Rmax', 'Rmin', 'Rmax-Rmin', 'RcRb'}

    if not file_name:
        file_name = f"VIRT_{new_msk}_{base_measure_id}"

    temp_groups = {}
    if not temp_df.empty:
        for n_val, g in temp_df.groupby('N', sort=False):
            temp_groups[n_val] = g.reset_index(drop=True)

    total = len(base_df)
    psidata_rows = []
    temp_rows = []
    TMP_MID = -1

    _tick(10, f'Генерация значений (изделий: {total})...')

    # ---- 5. Итерация по изделиям (без изменения логики) ----
    for idx, (_, base_row) in enumerate(base_df.iterrows()):
        if progress_cb and (idx % 10 == 0 or idx == total - 1):
            _tick(
                10 + int(idx / max(total, 1) * 80),
                f'Обработка изделия {idx + 1}/{total}')

        n = _safe_str(base_row.get('N'))

        # ---- F ----
        base_F = _safe_float(base_row.get('F'))
        pr_F = range_by_param.get('F')
        new_F = generate_value(
            base_F,
            pr_F['min'] if pr_F else None,
            pr_F['max'] if pr_F else None,
            settings, param_name='F', rtype=rtype)
        if new_F is None:
            new_F = base_F
        if base_F is not None and abs(base_F) > 1e-12:
            F_ratio = new_F / base_F
        else:
            F_ratio = 1.0
        F_ratio = _check_F_derivatives(
            base_row, range_by_param, F_ratio, settings)
        if base_F is not None:
            new_F = base_F * F_ratio

        # ---- R ----
        base_R = _safe_float(base_row.get('R'))
        pr_R = range_by_param.get('R')
        new_R = generate_value(
            base_R,
            pr_R['min'] if pr_R else None,
            pr_R['max'] if pr_R else None,
            settings, param_name='R', rtype=rtype)
        if new_R is None:
            new_R = base_R
        if base_R is not None and abs(base_R) > 1e-12:
            R_ratio = new_R / base_R
        else:
            R_ratio = 1.0
        R_ratio = _check_R_derivatives(
            base_row, range_by_param, R_ratio, settings)
        if base_R is not None:
            new_R = base_R * R_ratio

        # ---- Прямые параметры ----
        other_values = {}
        for pr in param_ranges:
            p = pr['param']
            if p in ('F', 'R', 'Fn'):
                continue
            if p in F_DERIVED or p in R_DERIVED:
                continue
            base_v = _safe_float(base_row.get(pr['field']))
            if base_v is None:
                base_v = _safe_float(base_row.get(p))
            other_values[p] = generate_value(
                base_v, pr['min'], pr['max'], settings,
                param_name=p, rtype=rtype)

        # ---- psidata row ----
        new_psidata = base_row.to_dict()
        new_psidata['Measure_ID']   = TMP_MID
        new_psidata['MSK']          = new_msk
        new_psidata['File']         = file_name
        new_psidata['Operator']     = operator
        new_psidata['Virtual_Data'] = 1

        if machine_info:
            for key in ('MachineType', 'Machine_Serial',
                        'Machine_Call_Date', 'Machine_ID',
                        'M_Type', 'PoverKa'):
                if key in new_psidata:
                    new_psidata[key] = machine_info.get(key)

        if new_F is not None:
            if 'F' in new_psidata:
                new_psidata['F'] = new_F
            if 'Fn' in new_psidata:
                new_psidata['Fn'] = new_F

        if new_R is not None and 'R' in new_psidata:
            new_psidata['R'] = new_R

        for p, v in other_values.items():
            pr = range_by_param.get(p)
            field = pr['field'] if pr else p
            if field in new_psidata:
                new_psidata[field] = v
            if p in new_psidata:
                new_psidata[p] = v

        # ---- Температурные точки ----
        new_temps_for_item = []
        if n in temp_groups:
            for _, t_row in temp_groups[n].iterrows():
                new_t = t_row.to_dict()
                new_t['Measure_ID'] = TMP_MID
                new_t['MSK']        = new_msk
                new_t['File']       = file_name

                T        = _safe_float(t_row.get('Temp'))
                base_F_t = _safe_float(t_row.get('F'))
                base_R_t = _safe_float(t_row.get('R'))

                if base_F_t is not None:
                    if T is not None and abs(T - tnastr) < 0.1:
                        new_t['F'] = (new_F if new_F is not None
                                      else base_F_t)
                    else:
                        new_t['F'] = base_F_t * F_ratio

                if base_R_t is not None:
                    new_t['R'] = base_R_t * R_ratio

                base_FL = _safe_float(t_row.get('FL'))
                if base_FL is not None:
                    new_t['FL'] = base_FL * F_ratio

                base_Rb = _safe_float(t_row.get('Rb'))
                if base_Rb is not None:
                    new_t['Rb'] = base_Rb * R_ratio

                for field in ('C0', 'Cq', 'Q', 'L'):
                    base_v = _safe_float(t_row.get(field))
                    if base_v is None:
                        continue
                    pr = range_by_param.get(field)
                    new_t[field] = generate_value(
                        base_v,
                        pr['min'] if pr else None,
                        pr['max'] if pr else None,
                        settings, param_name=field, rtype=rtype)

                new_temps_for_item.append(new_t)

        # ---- Fallback F/Fn ----
        if new_F is None:
            for t in new_temps_for_item:
                if (t.get('Temp') is not None
                        and abs(t['Temp'] - tnastr) < 0.1
                        and t.get('F') is not None):
                    if 'F' in new_psidata:
                        new_psidata['F'] = t['F']
                    if 'Fn' in new_psidata:
                        new_psidata['Fn'] = t['F']
                    break

        # ---- Производные ----
        _recompute_derived_from_temps(
            new_psidata, new_temps_for_item, base_row,
            range_by_param, new_F, tnastr)

        # ▼ Статусы больше НЕ копируются из base_row — пересчёт ниже

        psidata_rows.append(new_psidata)
        temp_rows.extend(new_temps_for_item)

    # ============================================================
    # 5a. ПЕРЕСЧЁТ Status / Status2 / spec_per_row
    # ============================================================
    spec_per_row = []
    if psidata_rows:
        _tick(90, 'Разбраковка по спецификации...')
        df_check = pd.DataFrame(psidata_rows)

        ok_series   = _compute_spec_status_df(df_check, param_ranges)
        per_field   = _compute_per_field_status_df(df_check, param_ranges)

        for i, ok in enumerate(ok_series.tolist()):
            psidata_rows[i]['Status']  = 1 if ok else 0
            psidata_rows[i]['Status2'] = 'Good' if ok else 'Bad'

        # per-row статусы по каждому параметру — для подсветки
        for i in range(len(psidata_rows)):
            row_status = {}
            for field, ser in per_field.items():
                row_status[field] = bool(ser.iloc[i])
            spec_per_row.append(row_status)

    # ---- 6. AE-валидация ----
    ae_summary = {}
    ae_per_row = {}

    if nn_cfg.get('autoenc_enabled', False) and psidata_rows:
        _tick(93, 'Проверка реалистичности (Autoencoder)...')
        try:
            from . import Virtual_NN

            thr_override = nn_cfg.get('autoenc_threshold')
            if thr_override is not None:
                try:
                    thr_override = float(thr_override)
                    if thr_override <= 0:
                        thr_override = None
                except (TypeError, ValueError):
                    thr_override = None

            if Virtual_NN.is_autoenc_available(rtype, spc=spc_name):
                scores = []
                anomalies = 0
                threshold = None
                skipped = 0
                diag_budget = 3

                for row_idx, r in enumerate(psidata_rows):
                    try:
                        score, is_anom, thr, per_f = \
                            Virtual_NN.autoenc_score(
                                r, rtype=rtype, spc=spc_name,
                                diagnostic=(diag_budget > 0),
                                threshold_override=thr_override)
                    except Exception:
                        score, is_anom, thr, per_f = \
                            None, False, None, {}

                    if score is None:
                        skipped += 1
                        continue

                    scores.append(score)
                    if is_anom:
                        anomalies += 1
                        if diag_budget > 0:
                            diag_budget -= 1
                    if threshold is None:
                        threshold = thr

                    ae_per_row[row_idx] = {
                        'score':       score,
                        'is_anom':     is_anom,
                        'threshold':   thr,
                        'per_feature': per_f,
                    }

                if scores:
                    thr_str = (f"{threshold:.3f}"
                               if threshold is not None else "n/a")
                    ovr_str = ("из настроек"
                               if thr_override is not None
                               else "из модели")
                    ae_summary = {
                        'mean_score':    sum(scores) / len(scores),
                        'max_score':     max(scores),
                        'anomaly_count': anomalies,
                        'total':         len(scores),
                        'skipped':       skipped,
                        'threshold':     threshold,
                        'threshold_src': ovr_str,
                    }
                    print(
                        f"[Virtual {_ts()}] AE (rtype='{rtype}', "
                        f"spc='{spc_name}'): "
                        f"mean={ae_summary['mean_score']:.3f}, "
                        f"max={ae_summary['max_score']:.3f}, "
                        f"anomalies={anomalies}/{len(scores)}, "
                        f"skipped={skipped}, "
                        f"threshold={thr_str} ({ovr_str})",
                        flush=True)
            else:
                print(f"[Virtual {_ts()}] AE: модель не найдена для "
                      f"spc='{spc_name}', rtype='{rtype}'", flush=True)
        except Exception as e:
            print(f"[Virtual {_ts()}] AE validation error: {e}",
                  flush=True)
            import traceback
            traceback.print_exc()

    _tick(95, 'Подготовка предпросмотра...')

    return {
        'psidata_rows':     psidata_rows,
        'temp_rows':        temp_rows,
        'base_mid':         base_measure_id,
        'new_msk':          new_msk,
        'file_name':        file_name,
        'operator':         operator,
        'spc_name':         spc_name,
        'spec_row':         spec_row,
        'base_file_id':     base_file_id,
        'rtype':            rtype,
        'selected_numbers': selected_numbers,
        'n_psidata':        len(psidata_rows),
        'n_psidatatemp':    len(temp_rows),
        'only_good':        only_good,
        'settings':         settings,
        'machine_info':     machine_info or {},
        'ae_validation':    ae_summary,
        'ae_per_row':       ae_per_row,
        'spec_per_row':     spec_per_row,   # ← НОВОЕ
        'param_ranges':     param_ranges,   # ← на всякий случай
    }

def generate_virtual_data_1(
        base_measure_id: int,
        new_msk: str,
        file_name: str = None,
        operator: str = None,
        settings: dict = None,
        only_good: bool = False,
        selected_numbers: list = None,
        machine_info: dict = None,
        progress_cb=None) -> dict | None:
    """
    Сгенерировать данные виртуального замера без записи в БД.

    Порядок поиска AE-модели: spec → rtype → global.
    Порог AE берётся из settings['nn']['autoenc_threshold'].
    Возвращает ae_validation и ae_per_row (для цветовой разметки).
    """
    def _tick(percent, message):
        if progress_cb:
            try:
                progress_cb(percent, message)
            except Exception:
                pass

    if settings is None:
        from .Virtual_Settings import load_settings
        settings = load_settings()
    if operator is None:
        operator = get_operator()

    nn_cfg = settings.get('nn', {}) or {}

    # ---- 1. Базовый замер ----
    _tick(2, 'Загрузка базового замера...')
    base_df = load_base_psidata(base_measure_id)
    if base_df.empty:
        print(f"[Virtual] base {base_measure_id} empty")
        return None

    base_file_id = _safe_str(base_df.iloc[0].get('File_ID'))
    temp_df = load_base_temp(base_measure_id)

    if selected_numbers:
        sel_set = {str(n).strip().upper() for n in selected_numbers}
        base_df = base_df[
            base_df['N'].astype(str).str.strip().str.upper()
            .isin(sel_set)
        ].reset_index(drop=True)
        if base_df.empty:
            print("[Virtual] no base rows match selected numbers")
            return None

    if only_good and 'Status2' in base_df.columns:
        base_df = base_df[
            base_df['Status2'] == 'Good'
        ].reset_index(drop=True)
        if base_df.empty:
            print("[Virtual] no Good items in base")
            return None

    # ---- 2. Спецификация ----
    _tick(8, 'Загрузка спецификации...')
    spc_name = _safe_str(base_df.iloc[0].get('Spc'))
    spec_row = load_spec(spc_name)
    if spec_row is None:
        print(f"[Virtual] specification '{spc_name}' not found")
        return None

    rtype = _safe_str(spec_row.get('NameR'))

    param_ranges = build_param_ranges(spec_row)
    if not param_ranges:
        print(f"[Virtual] no active parameters in spec '{spc_name}'")
        return None

    tnastr = _safe_float(spec_row.get('Tnastr'))
    if tnastr is None:
        tnastr = 25.0

    range_by_param = {r['param']: r for r in param_ranges}

    F_DERIVED = {
        'Fmax', 'Fmin', 'Fptp', 'Fptp_2', 'Fmaxm',
        'Mono', 'Slope', 'MonoT',
        'FT', 'Ft1', 'Ft2', 'Ft3', 'Ft4',
        'F_max_int', 'F_min_int',
        'F0-Fl', 'Ftgk',
        'Fs_ppm', 'Fl_ppm', 'FL_Num',
    }
    R_DERIVED = {'Rmax', 'Rmin', 'Rmax-Rmin', 'RcRb'}

    if not file_name:
        file_name = f"VIRT_{new_msk}_{base_measure_id}"

    temp_groups = {}
    if not temp_df.empty:
        for n_val, g in temp_df.groupby('N', sort=False):
            temp_groups[n_val] = g.reset_index(drop=True)

    total = len(base_df)
    psidata_rows = []
    temp_rows = []
    TMP_MID = -1

    _tick(10, f'Генерация значений (изделий: {total})...')

    # ---- 3. Итерация по изделиям ----
    for idx, (_, base_row) in enumerate(base_df.iterrows()):
        if progress_cb and (idx % 10 == 0 or idx == total - 1):
            _tick(
                10 + int(idx / max(total, 1) * 80),
                f'Обработка изделия {idx + 1}/{total}')

        n = _safe_str(base_row.get('N'))

        # ---- F ----
        base_F = _safe_float(base_row.get('F'))
        pr_F = range_by_param.get('F')
        new_F = generate_value(
            base_F,
            pr_F['min'] if pr_F else None,
            pr_F['max'] if pr_F else None,
            settings, param_name='F', rtype=rtype)
        if new_F is None:
            new_F = base_F

        if base_F is not None and abs(base_F) > 1e-12:
            F_ratio = new_F / base_F
        else:
            F_ratio = 1.0

        F_ratio = _check_F_derivatives(
            base_row, range_by_param, F_ratio, settings)
        if base_F is not None:
            new_F = base_F * F_ratio

        # ---- R ----
        base_R = _safe_float(base_row.get('R'))
        pr_R = range_by_param.get('R')
        new_R = generate_value(
            base_R,
            pr_R['min'] if pr_R else None,
            pr_R['max'] if pr_R else None,
            settings, param_name='R', rtype=rtype)
        if new_R is None:
            new_R = base_R

        if base_R is not None and abs(base_R) > 1e-12:
            R_ratio = new_R / base_R
        else:
            R_ratio = 1.0

        R_ratio = _check_R_derivatives(
            base_row, range_by_param, R_ratio, settings)
        if base_R is not None:
            new_R = base_R * R_ratio

        # ---- Прямые параметры ----
        other_values = {}
        for pr in param_ranges:
            p = pr['param']
            if p in ('F', 'R', 'Fn'):
                continue
            if p in F_DERIVED or p in R_DERIVED:
                continue
            base_v = _safe_float(base_row.get(pr['field']))
            if base_v is None:
                base_v = _safe_float(base_row.get(p))
            other_values[p] = generate_value(
                base_v, pr['min'], pr['max'], settings,
                param_name=p, rtype=rtype)

        # ---- psidata row ----
        new_psidata = base_row.to_dict()
        new_psidata['Measure_ID']   = TMP_MID
        new_psidata['MSK']          = new_msk
        new_psidata['File']         = file_name
        new_psidata['Operator']     = operator
        new_psidata['Virtual_Data'] = 1

        if machine_info:
            for key in ('MachineType', 'Machine_Serial',
                        'Machine_Call_Date', 'Machine_ID',
                        'M_Type', 'PoverKa'):
                if key in new_psidata:
                    new_psidata[key] = machine_info.get(key)

        if new_F is not None:
            if 'F' in new_psidata:
                new_psidata['F'] = new_F
            if 'Fn' in new_psidata:
                new_psidata['Fn'] = new_F

        if new_R is not None and 'R' in new_psidata:
            new_psidata['R'] = new_R

        for p, v in other_values.items():
            pr = range_by_param.get(p)
            field = pr['field'] if pr else p
            if field in new_psidata:
                new_psidata[field] = v
            if p in new_psidata:
                new_psidata[p] = v

        # ---- Температурные точки ----
        new_temps_for_item = []
        if n in temp_groups:
            for _, t_row in temp_groups[n].iterrows():
                new_t = t_row.to_dict()
                new_t['Measure_ID'] = TMP_MID
                new_t['MSK']        = new_msk
                new_t['File']       = file_name

                T        = _safe_float(t_row.get('Temp'))
                base_F_t = _safe_float(t_row.get('F'))
                base_R_t = _safe_float(t_row.get('R'))

                if base_F_t is not None:
                    if T is not None and abs(T - tnastr) < 0.1:
                        new_t['F'] = (new_F if new_F is not None
                                      else base_F_t)
                    else:
                        new_t['F'] = base_F_t * F_ratio

                if base_R_t is not None:
                    new_t['R'] = base_R_t * R_ratio

                base_FL = _safe_float(t_row.get('FL'))
                if base_FL is not None:
                    new_t['FL'] = base_FL * F_ratio

                base_Rb = _safe_float(t_row.get('Rb'))
                if base_Rb is not None:
                    new_t['Rb'] = base_Rb * R_ratio

                for field in ('C0', 'Cq', 'Q', 'L'):
                    base_v = _safe_float(t_row.get(field))
                    if base_v is None:
                        continue
                    pr = range_by_param.get(field)
                    new_t[field] = generate_value(
                        base_v,
                        pr['min'] if pr else None,
                        pr['max'] if pr else None,
                        settings, param_name=field, rtype=rtype)

                new_temps_for_item.append(new_t)

        # ---- Fallback F/Fn ----
        if new_F is None:
            for t in new_temps_for_item:
                if (t.get('Temp') is not None
                        and abs(t['Temp'] - tnastr) < 0.1
                        and t.get('F') is not None):
                    if 'F' in new_psidata:
                        new_psidata['F'] = t['F']
                    if 'Fn' in new_psidata:
                        new_psidata['Fn'] = t['F']
                    break

        # ---- Производные ----
        _recompute_derived_from_temps(
            new_psidata, new_temps_for_item, base_row,
            range_by_param, new_F, tnastr)

        # ---- Статусы ----
        if 'Status' in base_row.index:
            new_psidata['Status'] = base_row.get('Status')
        if 'Status2' in base_row.index:
            new_psidata['Status2'] = base_row.get('Status2')

        psidata_rows.append(new_psidata)
        temp_rows.extend(new_temps_for_item)

    # ---- 4. AE-валидация ----
    ae_summary = {}
    ae_per_row = {}

    if nn_cfg.get('autoenc_enabled', False) and psidata_rows:
        _tick(93, 'Проверка реалистичности (Autoencoder)...')
        try:
            from . import Virtual_NN

            thr_override = nn_cfg.get('autoenc_threshold')
            if thr_override is not None:
                try:
                    thr_override = float(thr_override)
                    if thr_override <= 0:
                        thr_override = None
                except (TypeError, ValueError):
                    thr_override = None

            if Virtual_NN.is_autoenc_available(rtype, spc=spc_name):
                scores = []
                anomalies = 0
                threshold = None
                skipped = 0
                diag_budget = 3

                for row_idx, r in enumerate(psidata_rows):
                    try:
                        score, is_anom, thr, per_f = \
                            Virtual_NN.autoenc_score(
                                r, rtype=rtype, spc=spc_name,
                                diagnostic=(diag_budget > 0),
                                threshold_override=thr_override)
                    except Exception:
                        score, is_anom, thr, per_f = \
                            None, False, None, {}

                    if score is None:
                        skipped += 1
                        continue

                    scores.append(score)
                    if is_anom:
                        anomalies += 1
                        if diag_budget > 0:
                            diag_budget -= 1
                    if threshold is None:
                        threshold = thr

                    ae_per_row[row_idx] = {
                        'score':       score,
                        'is_anom':     is_anom,
                        'threshold':   thr,
                        'per_feature': per_f,
                    }

                if scores:
                    thr_str = (f"{threshold:.3f}"
                               if threshold is not None else "n/a")
                    ovr_str = ("из настроек"
                               if thr_override is not None
                               else "из модели")
                    ae_summary = {
                        'mean_score':    sum(scores) / len(scores),
                        'max_score':     max(scores),
                        'anomaly_count': anomalies,
                        'total':         len(scores),
                        'skipped':       skipped,
                        'threshold':     threshold,
                        'threshold_src': ovr_str,
                    }
                    print(
                        f"[Virtual {_ts()}] AE (rtype='{rtype}', "
                        f"spc='{spc_name}'): "
                        f"mean={ae_summary['mean_score']:.3f}, "
                        f"max={ae_summary['max_score']:.3f}, "
                        f"anomalies={anomalies}/{len(scores)}, "
                        f"skipped={skipped}, "
                        f"threshold={thr_str} ({ovr_str})",
                        flush=True)
            else:
                print(f"[Virtual {_ts()}] AE: модель не найдена для "
                      f"spc='{spc_name}', rtype='{rtype}'", flush=True)
        except Exception as e:
            print(f"[Virtual {_ts()}] AE validation error: {e}",
                  flush=True)
            import traceback
            traceback.print_exc()

    _tick(95, 'Подготовка предпросмотра...')

    return {
        'psidata_rows':     psidata_rows,
        'temp_rows':        temp_rows,
        'base_mid':         base_measure_id,
        'new_msk':          new_msk,
        'file_name':        file_name,
        'operator':         operator,
        'spc_name':         spc_name,
        'spec_row':         spec_row,
        'base_file_id':     base_file_id,
        'rtype':            rtype,
        'selected_numbers': selected_numbers,
        'n_psidata':        len(psidata_rows),
        'n_psidatatemp':    len(temp_rows),
        'only_good':        only_good,
        'settings':         settings,
        'machine_info':     machine_info or {},
        'ae_validation':    ae_summary,
        'ae_per_row':       ae_per_row,
    }


# ============================================================================
# Сохранение в БД
# ============================================================================
def save_virtual_measure(measure_id, psidata_rows, temp_rows,
                         progress_cb=None):
    def _tick(percent, message):
        if progress_cb:
            try:
                progress_cb(percent, message)
            except Exception:
                pass

    eng = _engine()
    n_psi, n_temp = 0, 0

    _tick(10, 'Подготовка структуры psidata...')
    try:
        cols_df = pd.read_sql(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = 'psidata' AND TABLE_SCHEMA = DATABASE() "
            "ORDER BY ORDINAL_POSITION", eng)
        psi_cols = [c for c in cols_df['COLUMN_NAME'].tolist()
                    if c != 'ID']
    except Exception as e:
        print(f"[Virtual] psidata columns error: {e}")
        raise

    _tick(20, 'Подготовка структуры psidatatemp...')
    try:
        cols_df2 = pd.read_sql(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = 'psidatatemp' "
            "AND TABLE_SCHEMA = DATABASE() "
            "ORDER BY ORDINAL_POSITION", eng)
        temp_cols = [c for c in cols_df2['COLUMN_NAME'].tolist()
                     if c not in ('RecordId', 'ID')]
    except Exception as e:
        print(f"[Virtual] psidatatemp columns error: {e}")
        raise

    if psidata_rows:
        df = pd.DataFrame(psidata_rows)
        for c in psi_cols:
            if c not in df.columns:
                df[c] = None
        df = df[psi_cols]

        _tick(35, f'Запись psidata: {len(df)} строк...')
        try:
            df.to_sql('psidata', eng, if_exists='append',
                      index=False, method='multi')
            n_psi = len(df)
        except Exception as e:
            print(f"[Virtual] psidata save error: {e}")
            raise

    if temp_rows:
        _tick(65, 'Подготовка psidatatemp...')
        df = pd.DataFrame(temp_rows)
        for c in temp_cols:
            if c not in df.columns:
                df[c] = None
        df = df[temp_cols]

        _tick(75, f'Запись psidatatemp: {len(df)} строк...')
        try:
            df.to_sql('psidatatemp', eng, if_exists='append',
                      index=False, method='multi')
            n_temp = len(df)
        except Exception as e:
            print(f"[Virtual] psidatatemp save error: {e}")
            raise

    _tick(100, 'Готово')
    return n_psi, n_temp


def save_generated_data(preview: dict, progress_cb=None) -> tuple:
    """
    Сохранить предпросмотр в БД. Назначает реальный Measure_ID.
    Пишет в virtual_measure_log. Блокирует при autoenc_block=True
    и наличии аномалий.
    """
    def _tick(percent, message):
        if progress_cb:
            try:
                progress_cb(percent, message)
            except Exception:
                pass

    if not preview:
        return None, 0, 0

    nn_cfg = preview.get('settings', {}).get('nn', {})
    if nn_cfg.get('autoenc_enabled') and nn_cfg.get('autoenc_block'):
        ae = preview.get('ae_validation') or {}
        if ae.get('anomaly_count', 0) > 0:
            raise RuntimeError(
                f"Autoencoder: {ae['anomaly_count']} из "
                f"{ae['total']} записей ниже порога "
                f"реалистичности. Сохранение заблокировано.")

    _tick(5, 'Создание Measure_ID...')
    new_mid = create_measure_id(
        preview['new_msk'], preview['file_name'],
        preview['operator'], file_id=preview['base_file_id'])
    if not new_mid:
        raise RuntimeError('create_measure_id вернул None')

    for row in preview['psidata_rows']:
        row['Measure_ID'] = new_mid
    for row in preview['temp_rows']:
        row['Measure_ID'] = new_mid

    n_psi, n_temp = save_virtual_measure(
        new_mid, preview['psidata_rows'], preview['temp_rows'],
        progress_cb=progress_cb)

    _tick(95, 'Запись в журнал...')
    _log_virtual_measure(
        msk=preview.get('new_msk'),
        source_mid=preview.get('base_mid'),
        virtual_mid=new_mid)

    preview['new_mid'] = new_mid
    _tick(100, 'Готово')
    return new_mid, n_psi, n_temp


# ============================================================================
# Журнал
# ============================================================================
_virtual_log_ready = False


def _ensure_virtual_log_table() -> bool:
    global _virtual_log_ready
    if _virtual_log_ready:
        return True

    ddl = (
        "CREATE TABLE IF NOT EXISTS `virtual_measure_log` ("
        "`ID` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,"
        "`CreatedAt` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "`MSK` VARCHAR(64),"
        "`Source_Measure_ID` INT,"
        "`Virtual_Measure_ID` INT,"
        "`Login` VARCHAR(255),"
        "PRIMARY KEY (`ID`),"
        "KEY `idx_msk`  (`MSK`),"
        "KEY `idx_src`  (`Source_Measure_ID`),"
        "KEY `idx_virt` (`Virtual_Measure_ID`),"
        "KEY `idx_dt`   (`CreatedAt`)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    try:
        with _engine().begin() as conn:
            conn.execute(text(ddl))
        _virtual_log_ready = True
        print(f"[Virtual {_ts()}] virtual_measure_log: таблица готова",
              flush=True)
        return True
    except Exception as e:
        print(f"[Virtual {_ts()}] ensure_virtual_log_table error: {e}",
              flush=True)
        return False


def _log_virtual_measure(msk: str, source_mid: int, virtual_mid: int):
    if source_mid is None or virtual_mid is None:
        print(f"[Virtual {_ts()}] log: пропуск (source/virtual = None)",
              flush=True)
        return

    try:
        if not _ensure_virtual_log_table():
            return

        login = get_login_user_for_log()
        sql = text(
            "INSERT INTO `virtual_measure_log` "
            "(`MSK`, `Source_Measure_ID`, `Virtual_Measure_ID`, `Login`) "
            "VALUES (:msk, :src, :virt, :login)"
        )
        with _engine().begin() as conn:
            conn.execute(sql, {
                'msk':   str(msk or ''),
                'src':   int(source_mid),
                'virt':  int(virtual_mid),
                'login': login,
            })
        print(f"[Virtual {_ts()}] log: MSK='{msk}', "
              f"source={source_mid}, virtual={virtual_mid}, "
              f"login='{login}'", flush=True)
    except Exception as e:
        print(f"[Virtual {_ts()}] log_virtual_measure error: {e}",
              flush=True)


# ============================================================================
# Прямой ввод МСК
# ============================================================================
def load_by_msk(msk: str) -> dict | None:
    if not msk:
        return None
    msk = str(msk).strip()
    if not msk:
        return None

    try:
        t0 = datetime.now()
        print(f"[Virtual {_ts()}] load_by_msk: start msk='{msk}'",
              flush=True)

        row = pd.read_sql(
            text("SELECT DISTINCT `Spc` FROM psidata "
                 "WHERE Msk = :m LIMIT 1"),
            _engine(), params={'m': msk})
        if row.empty or not row['Spc'].iloc[0]:
            print(f"[Virtual {_ts()}] load_by_msk: МСК '{msk}' "
                  f"не найдена", flush=True)
            return None
        spc = str(row['Spc'].iloc[0])

        rtype = ''
        try:
            sr = pd.read_sql(
                text("SELECT `NameR` FROM specification "
                     "WHERE `Name` = :s"),
                _engine(), params={'s': spc})
            if not sr.empty:
                rtype = _safe_str(sr['NameR'].iloc[0])
        except Exception as e:
            print(f"[Virtual {_ts()}] load_by_msk: NameR error: {e}",
                  flush=True)

        try:
            nr = pd.read_sql(
                text("SELECT DISTINCT `N` FROM psidata "
                     "WHERE Msk = :m AND `N` IS NOT NULL ORDER BY `N`"),
                _engine(), params={'m': msk})
            numbers = [str(x) for x in nr['N'].tolist()]
        except Exception as e:
            print(f"[Virtual {_ts()}] load_by_msk: numbers error: {e}",
                  flush=True)
            numbers = []

        dt = (datetime.now() - t0).total_seconds()
        print(f"[Virtual {_ts()}] load_by_msk: msk='{msk}' -> "
              f"spc='{spc}', rtype='{rtype}', numbers={len(numbers)} "
              f"({dt:.2f}s)", flush=True)
        return {
            'msk':     msk,
            'spc':     spc,
            'rtype':   rtype,
            'numbers': numbers,
        }
    except Exception as e:
        import traceback
        print(f"[Virtual {_ts()}] ERROR load_by_msk(msk='{msk}'): {e}",
              flush=True)
        traceback.print_exc()
        return None


# ============================================================================
# Обёртка (обратная совместимость)
# ============================================================================
def generate_virtual_measure(base_measure_id, new_msk, file_name=None,
                              operator=None, settings=None,
                              only_good=False,
                              selected_numbers=None,
                              machine_info=None,
                              progress_cb=None) -> tuple:
    preview = generate_virtual_data(
        base_measure_id, new_msk, file_name, operator,
        settings, only_good, selected_numbers, machine_info,
        progress_cb=progress_cb)
    if not preview:
        return None, 0, 0
    return save_generated_data(preview)

# ============================================================================
# Разбраковка по спецификации (аналог Archive_View)
# ============================================================================
def _row_spec_status(row_dict: dict, param_ranges: list) -> tuple:
    """
    Проверка ОДНОЙ записи по всем параметрам спецификации.
    NaN и отсутствующее значение = брак.

    Возвращает (overall_ok, per_field_status):
        overall_ok        — True если все параметры в норме;
        per_field_status  — {col: True/False}, ключ = field psidata.
    """
    per_field = {}
    overall = True
    for pr in param_ranges:
        param = pr['param']
        field = pr['field']

        val = row_dict.get(field)
        if val is None:
            val = row_dict.get(param)

        try:
            fv = float(val) if val is not None else None
        except (TypeError, ValueError):
            fv = None

        is_bad = fv is None or (isinstance(fv, float) and np.isnan(fv))
        if not is_bad:
            if pr['min'] is not None and fv < pr['min']:
                is_bad = True
            if pr['max'] is not None and fv > pr['max']:
                is_bad = True

        per_field[field] = not is_bad
        if is_bad:
            overall = False

    return overall, per_field


def _compute_spec_status_df_1(df: pd.DataFrame,
                            param_ranges: list) -> pd.Series:
    """
    Векторный расчёт ОБЩЕГО статуса по всем параметрам спецификации.
    NaN = брак. При пустом param_ranges — все True.

    Возвращает pd.Series[bool] с тем же индексом, что df.
    """
    if not param_ranges:
        return pd.Series(True, index=df.index)

    overall = pd.Series(True, index=df.index)
    for pr in param_ranges:
        col = None
        for c in (pr['field'], pr['param']):
            if c in df.columns:
                col = c
                break
        if col is None:
            continue

        values = pd.to_numeric(df[col], errors='coerce')
        mask = values.notna()
        if pr['min'] is not None:
            mask &= values >= pr['min']
        if pr['max'] is not None:
            mask &= values <= pr['max']

        overall &= mask

    return overall


def _compute_per_field_status_df_1(df: pd.DataFrame,
                                 param_ranges: list) -> dict:
    """
    Векторный расчёт статусов по каждому параметру спецификации.
    Ключ = field psidata (совпадает с именем колонки для подсветки).
    Возвращает {field: pd.Series[bool]}.
    """
    result = {}
    if not param_ranges:
        return result

    for pr in param_ranges:
        col = None
        for c in (pr['field'], pr['param']):
            if c in df.columns:
                col = c
                break
        if col is None:
            continue

        values = pd.to_numeric(df[col], errors='coerce')
        mask = values.notna()
        if pr['min'] is not None:
            mask &= values >= pr['min']
        if pr['max'] is not None:
            mask &= values <= pr['max']
        result[col] = mask

    return result


def load_spc_map_otk_for_archive(spc_name: str) -> pd.DataFrame:
    """
    Возвращает карту норм с учётом технологического запаса (ОТК).
    Добавляет колонки Max_otk и Min_otk.
    """
    spc_map = load_spc_map_for_archive(spc_name)
    if spc_map.empty:
        return spc_map

    engine = create_engine(str(get_connection_string()))
    try:
        dopusk_map = pd.read_sql(
            "SELECT * FROM spc_dopusk_map_table ORDER BY ID", engine)
    except Exception as e:
        print(f"[Archive] Ошибка загрузки spc_dopusk_map_table: {e}")
        # Если таблицы нет, возвращаем базовые нормы
        spc_map['Max_otk'] = spc_map['Max']
        spc_map['Min_otk'] = spc_map['Min']
        return spc_map

    spc_df = load_specification(spc_name)
    row = spc_df.iloc[0]

    result = []
    for _, r in spc_map.iterrows():
        param = r['Parameter']
        mx = r['Max']
        mn = r['Min']

        dm = dopusk_map[dopusk_map['Parameter'] == param]
        if not dm.empty:
            units_col = dm.iloc[0].get('Dopusk_units')
            pct_col = dm.iloc[0].get('Dopusk_%')

            units = _safe_float(row.get(units_col)) if units_col else None
            pct = _safe_float(row.get(pct_col)) if pct_col else None

            if units is not None and units > 0:
                if mx is not None: mx -= units
                if mn is not None: mn += units
            elif pct is not None and pct > 0:
                if mx is not None: mx *= (1 - pct / 100)
                if mn is not None: mn *= (1 + pct / 100)

        r['Max_otk'] = mx
        r['Min_otk'] = mn
        result.append(r)

    return pd.DataFrame(result)


# ============================================================================
# Поиск базового замера: по частичному МСК и по номерам резонаторов
# ============================================================================
def search_msks_partial(partial: str) -> pd.DataFrame:
    """
    Поиск МСК по подстроке номера (LIKE '%partial%').

    Возвращает DataFrame:
        MSK           — полный номер МСК
        Spc           — спецификация
        Rtype         — тип резонатора
        Measure_Count — количество замеров с этим МСК
        Record_Count  — общее количество записей
    """
    if not partial or not str(partial).strip():
        return pd.DataFrame()
    partial = str(partial).strip()

    sql = """
        SELECT p.MSK                  AS MSK,
               MAX(p.Spc)             AS Spc,
               MAX(s.NameR)           AS Rtype,
               COUNT(DISTINCT p.Measure_ID) AS Measure_Count,
               COUNT(*)               AS Record_Count
        FROM psidata p
        LEFT JOIN specification s ON s.Name = p.Spc
        WHERE p.MSK IS NOT NULL AND p.MSK LIKE :pat
        GROUP BY p.MSK
        ORDER BY p.MSK
    """
    try:
        return pd.read_sql(
            text(sql), _engine(), params={'pat': f'%{partial}%'})
    except Exception as e:
        print(f"[Virtual] search_msks_partial error: {e}")
        return pd.DataFrame()


def search_measure_ids_by_numbers(numbers: list[str],
                                  only_good: bool = False) -> list[int]:
    """
    Поиск Measure_ID по номерам резонаторов через справочник
    psidata_resonator_lookup + fallback по psidata.N.

    Переиспользует логику Archive_View.Archive_Data — так же, как
    модуль Архив. only_good фильтрует замеры, где был хотя бы один
    Status2='Good' (грубая проверка, чтобы не показывать заведомо
    бракованные базовые замеры).
    """
    if not numbers:
        return []
    try:
        from Archive_View.Archive_Data import find_measure_ids_by_numbers
        return find_measure_ids_by_numbers(numbers, only_good=only_good)
    except Exception as e:
        print(f"[Virtual] search_measure_ids_by_numbers error: {e}")
        return []


def load_measure_ids_info(mids: list[int]) -> pd.DataFrame:
    """
    Загрузить краткую информацию по списку Measure_ID:
        Measure_ID, MSK, Spc, Rtype, Record_Count,
        Numbers (первые 10 уникальных), Number_Count
    """
    if not mids:
        return pd.DataFrame()
    from sqlalchemy import bindparam

    sql = text("""
        SELECT p.Measure_ID                         AS Measure_ID,
               MAX(p.MSK)                           AS MSK,
               MAX(p.Spc)                           AS Spc,
               MAX(s.NameR)                         AS Rtype,
               COUNT(*)                             AS Record_Count,
               SUBSTRING_INDEX(
                   GROUP_CONCAT(p.N ORDER BY p.N SEPARATOR ','),
                   ',', 10
               )                                    AS Numbers,
               COUNT(DISTINCT p.N)                  AS Number_Count
        FROM psidata p
        LEFT JOIN specification s ON s.Name = p.Spc
        WHERE p.Measure_ID IN :mids
        GROUP BY p.Measure_ID
        ORDER BY p.Measure_ID DESC
    """).bindparams(bindparam("mids", expanding=True))

    try:
        return pd.read_sql(sql, _engine(), params={'mids': list(mids)})
    except Exception as e:
        print(f"[Virtual] load_measure_ids_info error: {e}")
        return pd.DataFrame()

# ============================================================================
# Разбраковка по спецификации (аналог Archive_View)
# ============================================================================
def _compute_param_masks(df: pd.DataFrame,
                         param_ranges: list) -> dict:
    """
    Возвращает {param_name: pd.Series[bool]} с учётом логики
    нежелательных резонансов — точный порт
    Archive_Data._compute_param_masks:

        1) базовые маски по Min/Max;
        2) Rsp* бракует только если SPFR_* в норме:
              mask[RspN] = (~mask[SPFR_N]) | mask[RspN];
        3) SPFR_* исключены из отбраковки: mask = True.

    Ключи dict — Parameter_Name (как в spc_map), чтобы
    одинаково работали startswith('Rsp')/('SPFR_') для
    'Rsp1' и 'SPFR_1'. Сопоставление с колонкой psidata
    идёт через pr['field'] с fallback на pr['param'].
    """
    if not param_ranges:
        return {}

    # --- карта: param_name -> (col_in_df, pr) ------------------------------
    param_to_col = {}
    for pr in param_ranges:
        param = pr['param']
        col = None
        for c in (pr['field'], pr['param']):
            if c in df.columns:
                col = c
                break
        if col is None:
            continue
        param_to_col[param] = (col, pr)

    # --- 1) базовые маски по Min/Max --------------------------------------
    param_masks = {}
    for param, (col, pr) in param_to_col.items():
        values = pd.to_numeric(df[col], errors='coerce')
        mask = values.notna()
        if pr['min'] is not None:
            mask &= values >= pr['min']
        if pr['max'] is not None:
            mask &= values <= pr['max']
        param_masks[param] = mask

    # --- 2) Rsp* — бракует только когда SPFR_* в норме --------------------
    # (SPFR ещё не переопределён как True — используем наивную маску,
    #  порядок важен: как в Archive)
    for param in list(param_masks.keys()):
        if param.startswith('Rsp'):
            rsp_index = param[3:]                 # 'Rsp1' -> '1'
            spfr_param = f"SPFR_{rsp_index}"
            if spfr_param in param_masks:
                spfr_in_spec = param_masks[spfr_param]
                param_masks[param] = ((~spfr_in_spec)
                                      | param_masks[param])

    # --- 3) SPFR_* — не бракует изделие самостоятельно --------------------
    for param in list(param_masks.keys()):
        if param.startswith('SPFR_'):
            param_masks[param] = pd.Series(
                True, index=df.index, dtype=bool)

    return param_masks


def _compute_spec_status_df(df: pd.DataFrame,
                            param_ranges: list) -> pd.Series:
    """Общий статус изделия с учётом Rsp/SPFR (аналог Archive)."""
    param_masks = _compute_param_masks(df, param_ranges)
    if not param_masks:
        return pd.Series(True, index=df.index)
    overall = pd.Series(True, index=df.index)
    for mask in param_masks.values():
        overall &= mask
    return overall


def _compute_per_field_status_df(df: pd.DataFrame,
                                 param_ranges: list) -> dict:
    """
    Per-field статусы с учётом Rsp/SPFR.
    Ключ = имя колонки df (field, если оно есть; иначе param),
    чтобы совпадало с отображаемыми колонками в превью.
    """
    param_masks = _compute_param_masks(df, param_ranges)

    # param_name -> col_in_df (для перевода ключей в field)
    field_by_param = {}
    for pr in param_ranges:
        col = None
        for c in (pr['field'], pr['param']):
            if c in df.columns:
                col = c
                break
        if col is not None:
            field_by_param[pr['param']] = col

    result = {}
    for param, mask in param_masks.items():
        field = field_by_param.get(param, param)
        result[field] = mask
    return result