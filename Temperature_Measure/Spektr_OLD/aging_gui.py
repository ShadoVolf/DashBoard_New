"""GUI модуля «Спектр. Старение резонаторов»."""
import threading
import traceback

import pandas as pd
import dearpygui.dearpygui as dpg

from Temperature_Measure import _layout
from Temperature_Measure.Spektr_OLD.aging_logic import (
    compute_aging, load_old_by_id, load_old_id_meta,
    search_measure_ids_by_number_partial,
)
from Temperature_Measure.Spektr_OLD.aging_report import (
    create_aging_report, open_pdf,
)
from Temperature_Measure.unite_protokol.db import execute_query

try:
    from Temperature_Measure.Archive.Archive_Data import search_archive_msk
except ImportError:
    try:
        from Archive_View.Archive_Data import search_archive_msk
    except ImportError:
        search_archive_msk = None

try:
    from Authorization.Login import LoginUser
except ImportError:
    LoginUser = None


BOTTOM_H = 120
FORM_H = 400


class AgingWindow:

    def __init__(self, dpg_context):
        self.dpg = dpg_context
        self.window_tag = 'aging_window'
        self._result = None
        # --- состояние индикатора поиска ---
        self._searching = False
        self._search_anim_phase = 0.0
        self._init_ui()

    # ------------------------------------------------------------------ UI
    def _init_ui(self):
        pos, size = _layout.dialog_rect(
            fraction_w=0.58, fraction_h=0.86,
            min_w=820, min_h=650, max_w=1200, max_h=1100,
        )
        with dpg.window(label='Спектр. Старение резонаторов',
                        tag=self.window_tag,
                        width=size[0], height=size[1],
                        pos=pos, no_collapse=True):

            with dpg.child_window(height=FORM_H, border=False,
                                   tag='aging_form_child'):
                self._build_form()

            dpg.add_separator()

            with dpg.child_window(height=-BOTTOM_H, border=True,
                                   tag='aging_result_child'):
                self._build_result_table()

            dpg.add_separator()
            with dpg.group(horizontal=True):
                dpg.add_button(label='Расчёт', tag='aging_btn_calc',
                               callback=self.on_calc, width=140, height=30)
                dpg.add_button(label='Печать', tag='aging_btn_print',
                               callback=self.on_print, width=140, height=30,
                               enabled=False)
                dpg.add_button(label='Закрыть', tag='aging_btn_close',
                               callback=self.on_close, width=100, height=30)
            dpg.add_progress_bar(tag='aging_progress',
                                 default_value=0.0, width=-1, height=8)

    def _build_form(self):
        dpg.add_text('Расчёт старения резонаторов',
                     color=(200, 220, 255))
        dpg.add_separator()

        dpg.add_checkbox(
            label='Автопоиск второго замера '
                  '(для каждого N ищется замер без темп. параметров)',
            tag='aging_auto_search', default_value=True,
            callback=self._on_auto_search_toggle,
        )
        dpg.add_separator()

        with dpg.collapsing_header(
                label='Поиск «Код замера 1» (по МСК или номеру)',
                tag='aging_search_header', default_open=True):
            self._build_search_panel()
            dpg.add_separator()

        with dpg.group(horizontal=True):
            with dpg.group():
                dpg.add_text('Код замера 1:', color=(180, 200, 230))
                dpg.add_input_text(tag='aging_m_id_1',
                                   width=200, decimal=True,
                                   hint='например: 230630')
            with dpg.group():
                dpg.add_text('Код замера 2:',
                             color=(180, 200, 230),
                             tag='aging_m_id_2_label')
                dpg.add_input_text(tag='aging_m_id_2',
                                   width=200, decimal=True,
                                   hint='автопоиск',
                                   enabled=False)
            with dpg.group():
                dpg.add_text('ID старения:', color=(180, 200, 230))
                dpg.add_input_text(tag='aging_old_id',
                                   width=140, readonly=True, hint='-')

        dpg.add_separator()
        dpg.add_text('Нормы', color=(200, 220, 255))
        with dpg.group(horizontal=True):
            dpg.add_input_text(label='F max', tag='aging_f_max',
                               width=140, readonly=True)
            dpg.add_input_text(label='F min', tag='aging_f_min',
                               width=140, readonly=True)
            dpg.add_input_text(label='R max', tag='aging_r_max',
                               width=140, readonly=True)
            dpg.add_input_text(label='R min', tag='aging_r_min',
                               width=140, readonly=True)

        dpg.add_separator()
        dpg.add_text('Результат:', color=(200, 220, 255))
        dpg.add_text('-', tag='aging_result_text',
                     color=(140, 200, 140))

    def _build_search_panel(self):
        # ---- Общий индикатор поиска ----
        with dpg.group(horizontal=True, show=False,
                       tag='aging_search_status_group'):
            dpg.add_text('Поиск...', tag='aging_search_status',
                         color=(220, 220, 100))
        dpg.add_progress_bar(tag='aging_search_progress',
                             default_value=0.0, width=-1, height=6,
                             show=False)
        dpg.add_separator()

        # ---- Поиск по МСК ----
        dpg.add_text('Поиск по МСК:', color=(200, 220, 255))
        with dpg.group(horizontal=True):
            dpg.add_input_text(
                tag='aging_msk_search_input', width=240,
                hint='456  |  25-2456', on_enter=True,
                callback=self._on_msk_search,
            )
            dpg.add_button(label='Найти МСК', width=110,
                           callback=self._on_msk_search)
        with dpg.group(horizontal=True):
            dpg.add_text('МСК:', color=(180, 200, 230))
            dpg.add_combo([], tag='aging_msk_combo', width=280,
                          callback=self._on_msk_selected)
            dpg.add_text('ID:', color=(180, 200, 230))
            dpg.add_combo([], tag='aging_m_id_by_msk_combo', width=200,
                          callback=self._on_mid_by_msk_selected)

        dpg.add_spacer(height=8)

        # ---- Поиск по номеру резонатора ----
        dpg.add_text('Поиск по номеру резонатора:',
                     color=(200, 220, 255))
        with dpg.group(horizontal=True):
            dpg.add_input_text(
                tag='aging_number_search_input', width=240,
                hint='SU8525  |  8525  |  SU85',
                on_enter=True,
                callback=self._on_number_search,
            )
            dpg.add_button(label='Найти', width=110,
                           callback=self._on_number_search)
        with dpg.group(horizontal=True):
            dpg.add_text('Найденные замеры:',
                         color=(180, 200, 230))
            dpg.add_combo([], tag='aging_m_id_by_number_combo',
                          width=520,
                          callback=self._on_mid_by_number_selected)
        dpg.add_text(
            'Выберите запись — ID подставится в «Код замера 1»',
            color=(140, 140, 140),
        )

    # ---------------------------------- хелперы индикатора поиска
    def _begin_search(self, message: str) -> bool:
        """Показать индикатор. False — если поиск уже идёт."""
        if self._searching:
            if dpg.does_item_exist('aging_search_status'):
                dpg.set_value('aging_search_status',
                              'Поиск уже выполняется...')
                dpg.configure_item('aging_search_status_group', show=True)
            return False
        self._searching = True
        self._search_anim_phase = 0.0
        if dpg.does_item_exist('aging_search_status_group'):
            dpg.configure_item('aging_search_status_group', show=True)
        if dpg.does_item_exist('aging_search_status'):
            dpg.set_value('aging_search_status', message)
        if dpg.does_item_exist('aging_search_progress'):
            dpg.configure_item('aging_search_progress', show=True)
            dpg.set_value('aging_search_progress', 0.0)
        self._animate_search()
        return True

    def _animate_search(self):
        """Периодически двигает прогресс-бар — indeterminate."""
        if not self._searching:
            return
        self._search_anim_phase = (self._search_anim_phase + 0.03) % 1.0
        if dpg.does_item_exist('aging_search_progress'):
            dpg.set_value('aging_search_progress', self._search_anim_phase)
        dpg.set_frame_callback(dpg.get_frame_count() + 3,
                               self._animate_search)

    def _finish_search(self):
        """Скрыть индикатор."""
        self._searching = False
        if dpg.does_item_exist('aging_search_status_group'):
            dpg.configure_item('aging_search_status_group', show=False)
        if dpg.does_item_exist('aging_search_progress'):
            dpg.configure_item('aging_search_progress', show=False)
            dpg.set_value('aging_search_progress', 0.0)

    # ------------------------------------ поиск по МСК (в фоне)
    def _on_msk_search(self, sender=None, app_data=None):
        if search_archive_msk is None:
            self._show_error('Функция search_archive_msk недоступна')
            return
        partial = (dpg.get_value('aging_msk_search_input') or '').strip()
        if not partial:
            return
        if not self._begin_search(f'Поиск МСК "{partial}"...'):
            return

        def worker():
            try:
                matches = search_archive_msk(partial)
                dpg.set_frame_callback(
                    dpg.get_frame_count() + 1,
                    lambda: self._finish_msk_search(partial, matches, None))
            except Exception as e:
                print(f'[aging] MSK search error: {e}')
                traceback.print_exc()
                dpg.set_frame_callback(
                    dpg.get_frame_count() + 1,
                    lambda: self._finish_msk_search(partial, None, e))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_msk_search(self, partial, matches, error):
        self._finish_search()
        if error is not None:
            if dpg.does_item_exist('aging_search_status'):
                dpg.set_value('aging_search_status', f'Ошибка: {error}')
                dpg.configure_item('aging_search_status_group', show=True)
            return
        print(f'[aging] MSK "{partial}" -> {len(matches)} matches')
        dpg.configure_item('aging_msk_combo', items=matches)
        if matches:
            dpg.set_value('aging_msk_combo', matches[0])
            self._on_msk_selected()
        else:
            dpg.configure_item('aging_m_id_by_msk_combo', items=[])
            dpg.set_value('aging_m_id_by_msk_combo', '')

    def _on_msk_selected(self, sender=None, app_data=None):
        msk = dpg.get_value('aging_msk_combo')
        if not msk:
            return
        if not self._begin_search(f'Загрузка ID для МСК "{msk}"...'):
            return

        def worker():
            try:
                safe_msk = str(msk).replace("'", "''")
                sql = (
                    "SELECT Measure_ID, MIN(Date) AS Date, "
                    "COUNT(*) AS Cnt "
                    "FROM psidata "
                    f"WHERE MSK = '{safe_msk}' "
                    "  AND Measure_ID IS NOT NULL "
                    "GROUP BY Measure_ID "
                    "ORDER BY Measure_ID DESC"
                )
                print(f'[aging] MSK measure ids SQL: {sql}')
                df = execute_query(sql)
                dpg.set_frame_callback(
                    dpg.get_frame_count() + 1,
                    lambda: self._finish_msk_selected(msk, df, None))
            except Exception as e:
                print(f'[aging] MSK measure_ids error: {e}')
                traceback.print_exc()
                dpg.set_frame_callback(
                    dpg.get_frame_count() + 1,
                    lambda: self._finish_msk_selected(msk, None, e))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_msk_selected(self, msk, df, error):
        self._finish_search()
        if error is not None:
            return
        items = []
        for _, r in df.iterrows():
            try:
                mid = int(r['Measure_ID'])
            except (TypeError, ValueError):
                continue
            items.append(f"{mid} | {_fmt_str(r.get('Date'))} | "
                         f"{int(r.get('Cnt', 0) or 0)}")
        print(f'[aging] MSK "{msk}" -> {len(items)} Measure_IDs')
        dpg.configure_item('aging_m_id_by_msk_combo', items=items)
        if items:
            dpg.set_value('aging_m_id_by_msk_combo', items[0])
            self._on_mid_by_msk_selected()

    def _on_mid_by_msk_selected(self, sender=None, app_data=None):
        val = dpg.get_value('aging_m_id_by_msk_combo')
        if not val:
            return
        mid_str = str(val).split('|')[0].strip()
        if mid_str.isdigit():
            dpg.set_value('aging_m_id_1', mid_str)
            print(f'[aging] set aging_m_id_1 = {mid_str} (by MSK)')

    # ---------------------------------- поиск по номеру (в фоне)
    def _on_number_search(self, sender=None, app_data=None):
        partial = (dpg.get_value(
            'aging_number_search_input') or '').strip()
        if not partial:
            return
        if not self._begin_search(f'Поиск по номеру "{partial}"...'):
            return

        def worker():
            try:
                df = search_measure_ids_by_number_partial(partial)
                dpg.set_frame_callback(
                    dpg.get_frame_count() + 1,
                    lambda: self._finish_number_search(
                        partial, df, None))
            except Exception as e:
                print(f'[aging] number search error: {e}')
                traceback.print_exc()
                dpg.set_frame_callback(
                    dpg.get_frame_count() + 1,
                    lambda: self._finish_number_search(
                        partial, None, e))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_number_search(self, partial, df, error):
        self._finish_search()
        if error is not None:
            return
        print(f'[aging] number "{partial}" -> {len(df)} rows')

        items = []
        for _, r in df.iterrows():
            try:
                mid = int(r['Measure_ID'])
            except (TypeError, ValueError):
                continue
            items.append(
                f"{mid} | N={_fmt_str(r.get('Sample_N'))} | "
                f"{_fmt_str(r.get('MSK'))} | "
                f"{_fmt_str(r.get('Date'))} | "
                f"{int(r.get('Numbers_Count', 0) or 0)}")

        dpg.configure_item('aging_m_id_by_number_combo', items=items)
        if items:
            dpg.set_value('aging_m_id_by_number_combo', items[0])
            self._on_mid_by_number_selected()
        else:
            dpg.set_value('aging_m_id_by_number_combo', '')
            print(f'[aging] number "{partial}": не найдено')

    def _on_mid_by_number_selected(self, sender=None, app_data=None):
        val = dpg.get_value('aging_m_id_by_number_combo')
        if not val:
            return
        mid_str = str(val).split('|')[0].strip()
        if mid_str.isdigit():
            dpg.set_value('aging_m_id_1', mid_str)
            print(f'[aging] set aging_m_id_1 = {mid_str} (by number)')

    # ------------------------------------------------------------ таблица
    def _build_result_table(self):
        with dpg.table(tag='aging_result_table', header_row=True,
                       borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True,
                       scrollY=True, height=-1,
                       policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column(label='N')
            dpg.add_table_column(label='ID второго')
            dpg.add_table_column(label='F2-F1, ppm')
            dpg.add_table_column(label='R2-R1, Ohm')
            dpg.add_table_column(label='Статус')

    def _fill_result_table(self, data_df):
        if dpg.does_item_exist('aging_result_table'):
            children = dpg.get_item_children('aging_result_table', 1) or []
            for row in children:
                dpg.delete_item(row)
        for _, r in data_df.iterrows():
            with dpg.table_row(parent='aging_result_table'):
                dpg.add_text(_fmt_str(r.get('N')))
                dpg.add_text(_fmt_int(r.get('Measure_ID_2')))
                dpg.add_text(_fmt(r.get('diffF')))
                dpg.add_text(_fmt(r.get('diffR')))
                status = r.get('Status', '') or '-'
                color = (255, 100, 100) if status == 'Брак' \
                        else (140, 220, 140)
                dpg.add_text(status, color=color)

    # ------------------------------------------------------------ actions
    def _on_auto_search_toggle(self, sender, app_data):
        dpg.configure_item('aging_m_id_2', enabled=not app_data)
        dpg.configure_item(
            'aging_m_id_2_label',
            color=(180, 200, 230) if not app_data else (120, 120, 120),
        )

    def on_calc(self):
        mid_1 = (dpg.get_value('aging_m_id_1') or '').strip()
        auto = dpg.get_value('aging_auto_search')
        mid_2 = None if auto else \
            (dpg.get_value('aging_m_id_2') or '').strip()

        if not mid_1:
            self._show_error('Введите «Код замера 1»')
            return
        if not auto and not mid_2:
            self._show_error(
                'Введите «Код замера 2» или включите автопоиск')
            return

        print(f'[aging_gui] start: mid_1={mid_1!r}, '
              f'mid_2={mid_2!r}, auto={auto}')

        dpg.configure_item('aging_btn_print', enabled=False)
        dpg.set_value('aging_progress', 0.05)
        dpg.set_value('aging_result_text', 'Расчёт...')

        result_box = {}

        def worker():
            try:
                result_box['ok'] = compute_aging(
                    measure_id_1=mid_1,
                    measure_id_2=mid_2,
                    operator=self._operator(),
                    auto_search=auto,
                )
            except Exception as e:
                result_box['err'] = e
                traceback.print_exc()

        def wait():
            th = threading.Thread(target=worker, daemon=True)
            th.start()
            # Расчёт старения — секунды, не минуты; блокируем UI
            # ненадолго, зато безопасно для DearPyGui.
            th.join(timeout=180)
            if 'err' in result_box:
                dpg.set_value('aging_progress', 0.0)
                dpg.set_value('aging_result_text',
                              f'Ошибка: {result_box["err"]}')
                self._show_error(str(result_box['err']))
                return
            if 'ok' not in result_box:
                dpg.set_value('aging_progress', 0.0)
                dpg.set_value('aging_result_text',
                              'Ошибка: таймаут расчёта')
                return

            result = result_box['ok']
            self._result = result
            dpg.set_value('aging_old_id', str(result['old_id']))
            norms = result['norms']
            dpg.set_value('aging_f_max', _fmt(norms.get('old1max')))
            dpg.set_value('aging_f_min', _fmt(norms.get('old1min')))
            dpg.set_value('aging_r_max', _fmt(norms.get('Old2Max')))
            dpg.set_value('aging_r_min', _fmt(norms.get('old2min')))

            st = result['stats']
            sigma = result['dyn_norm']['sigma']
            dpg.set_value(
                'aging_result_text',
                f"Всего: {st['total']}, годных: {st['good']}, "
                f"брак: {st['bad']}, dyn sigma = {sigma:.4g}",
            )
            self._fill_result_table(result['data'])
            dpg.configure_item('aging_btn_print', enabled=True)
            dpg.set_value('aging_progress', 1.0)
            print(f'[aging_gui] done: old_id={result["old_id"]}')

        wait()

    def on_print(self):
        if not self._result:
            self._show_error('Сначала выполните расчёт')
            return
        try:
            res = self._result
            meta = load_old_id_meta(res['old_id'])
            data_df = load_old_by_id(res['old_id'])
            if data_df.empty:
                data_df = res['data']
            path = create_aging_report(
                old_id=res['old_id'],
                data_df=data_df,
                meta=meta,
                norms=res['norms'],
                stats=res['stats'],
            )
            dpg.set_value('aging_result_text', f'PDF: {path}')
            open_pdf(path)
            print(f'[aging_gui] PDF: {path}')
        except Exception as e:
            print(f'[aging_gui] print ERROR: {e}')
            traceback.print_exc()
            self._show_error(f'Ошибка печати: {e}')

    # -------------------------------------------------------------- utils
    @staticmethod
    def _operator() -> str:
        if LoginUser is None:
            return ''
        try:
            parts = [LoginUser.login[3], LoginUser.login[5]]
            return ' '.join(str(p) for p in parts if p)
        except (IndexError, AttributeError):
            return ''

    def _show_error(self, message):
        tag = 'aging_error_modal'
        if self.dpg.does_item_exist(tag):
            self.dpg.delete_item(tag)
        with dpg.window(label='Ошибка', modal=True,
                        width=580, height=260, tag=tag, no_resize=True):
            dpg.add_text(message, wrap=560, color=(220, 80, 80))
            dpg.add_separator()
            dpg.add_button(label='OK',
                           callback=lambda: dpg.delete_item(tag),
                           width=100)

    def on_close(self):
        dpg.delete_item(self.window_tag)

    def show(self):
        dpg.show_item(self.window_tag)

    def hide(self):
        dpg.hide_item(self.window_tag)


# ------------------------------------------------- форматирование
def _fmt(v, empty='-'):
    if v is None:
        return empty
    try:
        f = float(v)
    except (TypeError, ValueError):
        s = str(v).strip()
        return s if s else empty
    if f != f or f in (float('inf'), float('-inf')):
        return empty
    return f'{f:.4g}'


def _fmt_str(v):
    if v is None:
        return '-'
    try:
        if pd.isna(v):
            return '-'
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return s if s else '-'


def _fmt_int(v):
    if v is None:
        return '-'
    try:
        f = float(v)
    except (TypeError, ValueError):
        return _fmt_str(v)
    if f != f or f in (float('inf'), float('-inf')):
        return '-'
    try:
        return str(int(f))
    except (ValueError, OverflowError):
        return str(v)