"""Создание/показ окна ассистента в левой части экрана."""
import dearpygui.dearpygui as dpg
from .constants import (
    USER_WINDOW_H, MARGIN, WIDTH_FRAC, HEIGHT_FRAC, MIN_WIDTH,
)

_REGISTERED = False


def _compute_rect(dpg_):
    """((x, y), (w, h)) — слева, под user-окном, 26 %×80 % экрана."""
    sw = dpg_.get_viewport_client_width() or 1920
    sh = dpg_.get_viewport_client_height() or 1080
    w = max(MIN_WIDTH, int(sw * WIDTH_FRAC))
    x = MARGIN
    y = USER_WINDOW_H + 2 * MARGIN
    h = int(sh * HEIGHT_FRAC)
    if y + h > sh - MARGIN:
        h = sh - y - MARGIN
    return (x, y), (w, h)


def _factory():
    create_assistant_window()


def _ensure_registered():
    global _REGISTERED
    if _REGISTERED:
        return
    try:
        import window_manager
        window_manager.register('assistant', 'Ассистент (LLM)', _factory)
        _REGISTERED = True
    except Exception as e:
        print(f'[Assistant.window] register: {e}')


def _rebuild_menu_safe():
    try:
        import window_manager
        window_manager.rebuild_menu()
    except Exception:
        pass


def _rebind_ask_callback(dpg_):
    """Перевесить «Спросить» и Enter на controller-обёртку."""
    if not dpg_.does_item_exist('assistant_ask_btn'):
        return
    from .controller import run_nl_query
    try:
        dpg_.configure_item(
            'assistant_ask_btn',
            callback=run_nl_query, user_data=dpg_,
        )
    except Exception as e:
        print(f'[Assistant.window] rebind ask: {e}')

    # NEW: тот же callback — на Enter в поле ввода
    if dpg_.does_item_exist('assistant_input'):
        try:
            dpg_.configure_item(
                'assistant_input',
                on_enter=True,
                callback=run_nl_query, user_data=dpg_,
            )
        except Exception as e:
            print(f'[Assistant.window] rebind input: {e}')


def create_assistant_window(dpg_=None):
    """Создать / показать ассистента слева (26 %×80 %, под user-окном)."""
    if dpg_ is None:
        dpg_ = dpg
    _ensure_registered()

    if dpg_.does_item_exist('assistant'):
        # Показать в его текущей позиции (в статистике — справа от
        # результатов, на старте — слева, см. п.3).
        dpg_.configure_item('assistant', show=True)
        try:
            dpg_.focus_item('assistant')
        except Exception:
            pass
        _rebind_ask_callback(dpg_)   # на случай создания «в обход» Assistant
        _rebuild_menu_safe()
        return

    # Первое создание — на левой стороне, широкое.
    from Statistik.dashboard_llm import (
        create_assistant_window as _llm_create,
    )
    pos, size = _compute_rect(dpg_)
    _llm_create(dpg_, pos=pos, size=size)
    _rebind_ask_callback(dpg_)
    _rebuild_menu_safe()


def show_assistant_window(sender, data, dpg_):
    create_assistant_window(dpg_)