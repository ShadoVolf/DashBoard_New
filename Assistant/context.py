"""Разделяемое состояние ассистента — не UI, не статистика.

Pending-состояние — одна активная многошаговая операция.
При новом запросе (кроме 'да'/'нет'/числа) pending сбрасывается.
"""
import time

_ctx = {
    'last_search_df': None,        # DataFrame из search_protocols
    'last_protokol_id': None,      # int | None
    'last_msk': None,              # str | None
    'pending': None,               # {'kind':..., 'payload':..., 'expires':...}
}

_CONFIRM_YES = frozenset(('да', 'yes', 'подтверждаю', 'применить',
                          'ok', 'выполняй', 'создавай', 'отправляй'))
_CONFIRM_NO  = frozenset(('нет', 'no', 'отмена', 'cancel', 'стоп', 'не надо'))


def get_ctx() -> dict:
    return _ctx


def set_pending(kind: str, payload: dict, ttl: int = 180) -> None:
    _ctx['pending'] = {
        'kind': kind,
        'payload': payload,
        'expires': time.time() + ttl,
    }


def peek_pending():
    p = _ctx.get('pending')
    if not p:
        return None
    if time.time() > p['expires']:
        _ctx['pending'] = None
        return None
    return p


def pop_pending():
    p = peek_pending()
    _ctx['pending'] = None
    return p


def clear_pending() -> None:
    _ctx['pending'] = None


def is_yes(q: str) -> bool:
    return (q or '').strip().lower() in _CONFIRM_YES


def is_no(q: str) -> bool:
    return (q or '').strip().lower() in _CONFIRM_NO