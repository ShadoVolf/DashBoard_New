import importlib
import os
import sys
import tempfile

import dearpygui.dearpygui as dpg
from screeninfo import get_monitors

from Console import ConsoleManager
from Pictures.Theme_View.Load_Themes import load_themes
from Update import check_for_updates, download_update, verify_update, start_updater, get_current_version
from fonts.Font import setup_fonts
from Authorization.Login import fill_list
from Authorization.Login import is_login_user
from Authorization.Login import is_barCode_exist
from Authorization.Login import add_login_window
from Main_Menu import create_main_menu

dpg.create_context()



def open_main_window(sender, data):
    global test_login
    temp_login = dpg.get_value('cmb_login')
    temp_password = dpg.get_value('password')
    print(data)
    if sender == 'password':
        test_login = is_login_user(temp_login, temp_password)
        print('Enter password ' + data)
    if sender == 'bar_code':
        print('Enter barcode ' + data)
        test_login = is_barCode_exist(data)
    if test_login:
        create_main_menu(dpg)
        dpg.delete_item('login')
        add_login_window(dpg)

        # === Ассистент: авто-показ после логина ===
        try:
            from Assistant import create_assistant_window
            create_assistant_window(dpg)
        except Exception as e:
            print(f'[Assistant] auto-launch error: {e}')

def open_main_window_1(sender, data):
    global test_login
    temp_login = dpg.get_value('cmb_login')
    temp_password = dpg.get_value('password')
    print(data)
    # если введен пароль
    if sender == 'password':
        test_login = is_login_user(temp_login, temp_password)
        print('Enter password ' + data)
    # если введен идентификатор
    if sender == 'bar_code':
        print('Enter barcode ' + data)
        test_login = is_barCode_exist(data)
    if test_login:
        create_main_menu(dpg)
        dpg.delete_item('login')
        add_login_window(dpg)
        # show_stat_dashboard(None, None, dpg)
# Глобальные переменные


monitors = get_monitors()
# Вывод размеров каждого монитора
setup_fonts(dpg, 'MonoCondensed')
# Устанавливаем размеры окна
window_width = 400
window_height = 150
'''
if "NUITKA_ONEFILE_PARENT" in os.environ:
   splash_filename = os.path.join(
      tempfile.gettempdir(),
      "onefile_%d_splash_feedback.tmp" % int(os.environ["NUITKA_ONEFILE_PARENT"]),
   )

   if os.path.exists(splash_filename):
      os.unlink(splash_filename)
'''

try:
    import pyi_splash
    pyi_splash.update_text('Загрузка ...')
    pyi_splash.close()

except:
    pass


# Обновление программы
'''****************************************************************************************************************'''

print("Version", get_current_version())
update_info = check_for_updates()
print(update_info)
if update_info:
    url, expected_md5 = update_info
    start_updater(url, expected_md5)

'''******************************************************************************************************************'''

dpg.create_viewport(title='MORION RESONATORS', width=monitors[0].width, height=monitors[0].height, x_pos=0, y_pos=0)
# Получение размеров экрана
screen_width = dpg.get_viewport_width()
screen_height = dpg.get_viewport_height()

# Вычисление позиций для центрирования окна
pos_x = (screen_width - window_width) // 2
pos_y = (screen_height - window_height) // 2
with dpg.window(label="Авторизация", width=window_width, height=window_height, pos=(pos_x, pos_y), tag='login'):
    cmb_Login = dpg.add_combo(label='Пользователь', tag='cmb_login')
    edt_pass = dpg.add_input_text(label='Пароль', password=True, on_enter=True, callback=open_main_window,
                                  tag='password')
    edt_id = dpg.add_input_text(label='Идентификатор', decimal=True, on_enter=True, callback=open_main_window,
                                tag='bar_code')
fill_list(dpg, 'cmb_login')

load_themes(dpg)

dpg.setup_dearpygui()
dpg.show_viewport()
def _on_viewport_resize(sender=None, app_data=None):
    # Импорт внутри функции — модуль опционален
    try:
        from ResonatorGraph.ui import _apply_layout
        _apply_layout()
    except Exception:
        pass


dpg.set_viewport_resize_callback(_on_viewport_resize)

# ============================================================
# Реестр контроллеров активных модулей.
# Любой модуль (FrequencyMeasure, будущие) при создании окна
# вызывает register_controller(my_controller) — и его очередь
# опрашивается в главном цикле комплекса ниже.
# ============================================================
_active_controllers = []

def register_controller(controller):
    if controller is not None and controller not in _active_controllers:
        _active_controllers.append(controller)
        print(f"[main] controller registered: {type(controller).__name__}")

def unregister_controller(controller):
    try:
        _active_controllers.remove(controller)
    except ValueError:
        pass

# Публикуем функции через builtins — модули не зависят от того,
# под каким именем (__main__ / main) загружен этот файл.
import builtins
builtins.register_controller = register_controller
builtins.unregister_controller = unregister_controller

# ============================================================
# Главный цикл (замена dpg.start_dearpygui()).
# Сначала дренируем очереди всех контроллеров,
# затем рендерим кадр.
# ============================================================
while dpg.is_dearpygui_running():
    for c in list(_active_controllers):
        try:
            c.process_queue()
        except Exception:
            import traceback
            traceback.print_exc()
    dpg.render_dearpygui_frame()

dpg.destroy_context()
#dpg.start_dearpygui()
#dpg.destroy_context()
