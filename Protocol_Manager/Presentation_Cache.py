"""Кэш параметров представления протокола.

`build_presentation_params(spc, tu_data)` зависит только от Spc (её ТУ),
но не от конкретного резонатора. Для N резонаторов функция вызывается
N раз — кэш сводит это к одному вычислению.

Печать в лог:
  - "cache miss" — при первом вычислении Spc (полный блок от impl),
  - "cache hit"  — только при ПЕРВОМ попадании на данный Spc,
    дальше тишина (иначе лог забьётся 15 одинаковыми строками).
"""
import threading

_lock = threading.RLock()
_cache: dict = {}
_hit_printed: set = set()


def get_or_build(spc, builder):
    """Вернуть значение для `spc` из кэша или построить через `builder()`."""
    key = str(spc) if spc is not None else ""
    with _lock:
        if key in _cache:
            if key not in _hit_printed:
                _hit_printed.add(key)
                print(f"[Presentation] build_presentation_params: cache hit "
                      f"для Spc: '{spc}' (дальнейшие попадания не логируются)")
            return _cache[key]

    result = builder()
    with _lock:
        _cache[key] = result
    return result


def get_or_build_presentation_params(spc_val, tu_data):
    """Кэшированный `build_presentation_params(spc_val, tu_data)`."""
    if not spc_val:
        from Archive_View.Archive_Data import build_presentation_params
        return build_presentation_params(spc_val, tu_data)

    def _build():
        from Archive_View.Archive_Data import build_presentation_params
        print(f"[Presentation] build_presentation_params (cache miss) "
              f"для Spc: '{spc_val}'")
        return build_presentation_params(spc_val, tu_data)

    return get_or_build(spc_val, _build)


def clear():
    """Сбросить кэш (после правок норм/спецификаций)."""
    with _lock:
        _cache.clear()
        _hit_printed.clear()