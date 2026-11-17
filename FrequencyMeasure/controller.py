import os
import time
import queue
import threading
import datetime

import numpy as np

from .driver import CH3_85_6
from .models import (get_engine, init_db,
                     Measurement, MeasurementPoint, Summary)
from .pdf_report import export_summary_pdf, export_graphs_pdf
from .config import _resolve_path
from .calculations import to_ppm, calc_monotonicity_ppm, calc_outliers


class MeasurementController:
    """Бизнес-логика без зависимостей от GUI.

    Взаимодействие с представлением - через:
      * hooks     (self.on_*)       - уведомления "сделай в UI то-то";
      * providers (self.*_provider) - запросы "дай мне текущее значение поля UI".
    """

    ST_ASK_MCU = 'ASK_MCU'
    ST_WAIT_SIGNAL_LOSS = 'WAIT_SIGNAL_LOSS'
    ST_WAIT_SIGNAL = 'WAIT_SIGNAL'
    ST_MEASURING = 'MEASURING'
    ST_DONE = 'DONE'

    def __init__(self, cfg):
        self.cfg = cfg
        self.meas_cfg = cfg['measurement']
        self.dev_cfg = cfg['device']
        self.accept_cfg = cfg['acceptance']

        self.state = self.ST_ASK_MCU
        self.current_mcu = None
        self.current_mcu_nominal_khz = None
        self.current_resonator = None
        self.current_cycle = None
        self.selected_resonator = None

        self.cur_t = []
        self.cur_f = []
        self.cur_start = None
        self.signal_stable_since = None

        self.measurements = []

        self.device = None
        self.device_lock = threading.Lock()
        self.data_queue = queue.Queue()
        self.worker_stop = threading.Event()
        self.worker_thread = None

        self.engine = None
        self.Session = None

        self.on_log = lambda msg: None
        self.on_state_changed = lambda st: None
        self.on_device_status = lambda text: None
        self.on_mcu_labels = lambda mcu, nominal_khz: None
        self.on_ask_mcu_dialog = lambda: None
        self.on_ask_resonator_dialog = lambda: None
        self.on_measurement_finished = lambda m: None
        self.on_summary_updated = lambda: None
        self.on_plot_refresh = lambda: None
        self.on_plot_live = lambda: None
        self.on_pdf_created = lambda path: None

        self.epsilon_provider = lambda: self.meas_cfg.get('epsilon', 2.0)

    # ----------------------------------------------------------- log
    def log(self, msg):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        line = f'[{ts}] {msg}'
        print(line, flush=True)
        self.on_log(line)

    # =========================================================== device
    def start_device(self):
        try:
            self.device = CH3_85_6(
                resource=self.dev_cfg.get('resource', 'auto'),
                baudrate=self.dev_cfg.get('baudrate', 9600),
                timeout=self.dev_cfg.get('timeout_ms', 5000),
                verbose=True,
            )
            try:
                idn = self.device.identify()
            except Exception:
                idn = ''
            self.on_device_status(f"OK: {idn}" if idn else "OK")
        except Exception as e:
            self.on_device_status(f"Ошибка: {e}")
            self.device = None

    def start_worker(self):
        self.worker_stop.clear()
        self.worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def _worker_loop(self):
        gate = self.dev_cfg.get('gate_time', 0.1)
        poll = self.dev_cfg.get('poll_interval', 0.05)
        while not self.worker_stop.is_set():
            if self.device is None:
                time.sleep(0.5)
                continue
            try:
                with self.device_lock:
                    freq = self.device.measure_frequency(gate_time=gate)
                if freq is not None:
                    self.data_queue.put(('freq', time.time(), freq))
                else:
                    self.data_queue.put(('none', time.time(), None))
            except Exception as e:
                self.data_queue.put(('error', time.time(), str(e)))
                time.sleep(0.5)
            time.sleep(poll)

    # =========================================================== state
    def set_state(self, st):
        self.state = st
        self.on_state_changed(st)

    # =========================================================== MCU
    def ask_mcu(self):
        self.on_ask_mcu_dialog()

    def set_mcu(self, mcu, nominal_khz):
        self.current_mcu = mcu
        self.current_mcu_nominal_khz = nominal_khz
        self.on_mcu_labels(mcu, nominal_khz)

        self.measurements.clear()
        self.selected_resonator = None
        self.on_summary_updated()
        self.on_plot_refresh()

        self.load_measurements_for_mcu(mcu)

        self.set_state(self.ST_WAIT_SIGNAL)
        self.log(f'МСК: {mcu}, номинал {nominal_khz:.6f} кГц '
                 f'({nominal_khz*1e3:.3f} Гц)')

    # =========================================================== resonator
    def request_resonator(self):
        self.on_ask_resonator_dialog()

    def begin_measurement(self, resonator, cycle):
        self.current_resonator = resonator
        self.current_cycle = cycle
        self.cur_t = []
        self.cur_f = []
        self.cur_start = time.time()
        self.set_state(self.ST_MEASURING)
        self.on_plot_refresh()
        self.log(f'Старт: МСК={self.current_mcu}, '
                 f'рез={resonator}, цикл={cycle}')

    def finish_measurement(self, reason='epsilon'):
        if not self.cur_f:
            self.set_state(self.ST_WAIT_SIGNAL)
            return

        freqs = np.array(self.cur_f)
        times = np.array(self.cur_t)
        nominal_hz = self.current_mcu_nominal_khz * 1e3

        # Опорная частота - последняя точка измерения.
        ref_hz = float(freqs[-1])
        if ref_hz <= 0:
            ref_hz = nominal_hz

        max_f = float(np.max(freqs))
        min_f = float(np.min(freqs))
        max_ppm = to_ppm(max_f, ref_hz)
        min_ppm = to_ppm(min_f, ref_hz)

        mono_ppm = calc_monotonicity_ppm(freqs, ref_hz)
        max_outlier_ppm = calc_outliers(
            freqs, ref_hz,
            threshold_ppm=self.accept_cfg.get('outlier_threshold_ppm', 20.0))

        m = {
            'mcu': self.current_mcu,
            'resonator': self.current_resonator,
            'cycle': self.current_cycle,
            'nominal_khz': self.current_mcu_nominal_khz,
            'ref_hz': ref_hz,
            't': times.tolist(),
            'f': freqs.tolist(),
            'f_ppm': [to_ppm(v, ref_hz) for v in freqs],
            'max': max_f, 'min': min_f,
            'max_ppm': max_ppm, 'min_ppm': min_ppm,
            'mono_ppm': mono_ppm,
            'max_outlier_ppm': max_outlier_ppm,
            'start': datetime.datetime.fromtimestamp(self.cur_start),
            'end': datetime.datetime.now(),
            'reason': reason,
        }
        self.measurements.append(m)
        self.on_summary_updated()

        self.selected_resonator = m['resonator']
        self.signal_stable_since = None
        self.set_state(self.ST_WAIT_SIGNAL_LOSS)
        self.on_plot_refresh()
        self.log(f'Измерение завершено ({reason}), опора: '
                 f'{ref_hz:.3f} Гц ({ref_hz / 1e3:.6f} кГц)')
        self.on_measurement_finished(m)

    # =========================================================== queue
    def process_queue(self):
        try:
            while True:
                kind, ts, val = self.data_queue.get_nowait()
                if kind in ('freq', 'none'):
                    self.handle_freq(ts, val)
                elif kind == 'error':
                    self.log(f'Ошибка драйвера: {val}')
        except queue.Empty:
            pass

    def handle_freq(self, ts, freq):
        min_f = self.meas_cfg['min_frequency']
        signal_present = freq is not None and freq >= min_f

        if self.state == self.ST_WAIT_SIGNAL_LOSS:
            if not signal_present:
                self.signal_stable_since = None
                self.set_state(self.ST_WAIT_SIGNAL)

        if self.state == self.ST_WAIT_SIGNAL:
            if signal_present:
                if self.signal_stable_since is None:
                    self.signal_stable_since = ts
                elif (ts - self.signal_stable_since) >= \
                        self.meas_cfg['signal_stable_time']:
                    self.signal_stable_since = None
                    self.request_resonator()
            else:
                self.signal_stable_since = None

        if self.state == self.ST_MEASURING:
            if not signal_present:
                self.finish_measurement('signal_lost')
                return
            if self.cur_start is None:
                self.cur_start = ts
            t = ts - self.cur_start
            self.cur_t.append(t)
            self.cur_f.append(freq)

            nominal_hz = self.current_mcu_nominal_khz * 1e3
            eps_ppm = self.epsilon_provider()
            eps_hz = abs(eps_ppm) * nominal_hz / 1e6

            w = self.meas_cfg['epsilon_window']
            min_dur = self.meas_cfg['min_duration']
            max_dur = self.meas_cfg['max_duration']
            if t >= max_dur:
                self.finish_measurement('max_duration')
                return
            if t >= min_dur and len(self.cur_f) >= w:
                recent = self.cur_f[-w:]
                if (max(recent) - min(recent)) < eps_hz:
                    self.finish_measurement('epsilon')
                    return

            self.on_plot_live()

    # =========================================================== summary
    def calc_status(self, row):
        ac = self.accept_cfg
        if row['max_ppm'] is None or row['min_ppm'] is None:
            return '-'
        ok = (row['max_ppm'] < ac.get('max_ppm', 1e9) and
              row['min_ppm'] > ac.get('min_ppm', -1e9) and
              row['monotonicity_ppm'] < ac.get('max_monotonicity_ppm', 1e9) and
              row.get('max_outlier_ppm', 0.0) == 0.0)
        return 'Годен' if ok else 'Брак'

    def build_summary_rows(self):
        groups = {}
        for m in self.measurements:
            key = (m['mcu'], m['resonator'])
            g = groups.setdefault(key, {
                'mcu': m['mcu'],
                'resonator': m['resonator'],
                'nominal_khz': m['nominal_khz'],
                'max_ppm': None,
                'min_ppm': None,
                'mono_ppm': [],
                'max_outlier_ppm': 0.0,
                'cycles_count': 0,
            })
            if g['max_ppm'] is None or (m['max_ppm'] or 0) > g['max_ppm']:
                g['max_ppm'] = m['max_ppm'] or 0.0
            if g['min_ppm'] is None or (m['min_ppm'] or 0) < g['min_ppm']:
                g['min_ppm'] = m['min_ppm'] or 0.0
            g['mono_ppm'].append(m['mono_ppm'] or 0.0)
            g['max_outlier_ppm'] = max(g['max_outlier_ppm'],
                                       m.get('max_outlier_ppm', 0.0) or 0.0)
            g['cycles_count'] += 1

        rows = []
        for g in groups.values():
            row = {
                'mcu': g['mcu'],
                'resonator': g['resonator'],
                'nominal_khz': g['nominal_khz'],
                'max_ppm': g['max_ppm'],
                'min_ppm': g['min_ppm'],
                'monotonicity_ppm': (float(np.mean(g['mono_ppm']))
                                     if g['mono_ppm'] else 0.0),
                'max_outlier_ppm': g['max_outlier_ppm'],
                'cycles_count': g['cycles_count'],
            }
            row['status'] = self.calc_status(row)
            rows.append(row)
        rows.sort(key=lambda r: r['resonator'])
        return rows

    def rename_resonator(self, old, new):
        if not new or new == old:
            return False
        for m in self.measurements:
            if m['mcu'] == self.current_mcu and m['resonator'] == old:
                m['resonator'] = new
        if self.selected_resonator == old:
            self.selected_resonator = new
        self.on_summary_updated()
        self.on_plot_refresh()
        return True

    # =========================================================== DB
    def ensure_db(self):
        if self.engine is None:
            self.engine = get_engine(self.cfg['database'])
            self.Session = init_db(self.engine)
        return self.Session()

    def load_measurements_for_mcu(self, mcu):
        self.log(f'Загрузка из БД: МСК="{mcu}"')
        try:
            session = self.ensure_db()
        except Exception as e:
            self.log(f'БД недоступна: {e}')
            return
        try:
            try:
                recs = (session.query(Measurement)
                        .filter_by(mcu_number=mcu).all())
            except Exception as e:
                self.log(f'ОШИБКА query(Measurement): {e}')
                return

            self.log(f'Найдено записей Measurement: {len(recs)}')

            loaded = []
            for rec in recs:
                try:
                    pts = (session.query(MeasurementPoint)
                           .filter_by(measurement_id=rec.id)
                           .order_by(MeasurementPoint.t).all())
                except Exception as e:
                    self.log(f'ОШИБКА query(MeasurementPoint) '
                             f'для id={rec.id}: {e}')
                    continue

                nominal_khz = rec.nominal_khz
                if nominal_khz is None or nominal_khz <= 0:
                    nominal_khz = self.current_mcu_nominal_khz or 0
                nominal_hz = nominal_khz * 1e3

                t_list, f_list = [], []
                for p in pts:
                    if p.t is None:
                        continue
                    if p.ppm is not None and nominal_hz > 0:
                        f_hz = nominal_hz * (1.0 + float(p.ppm) / 1e6)
                    elif p.frequency is not None:
                        f_hz = float(p.frequency)
                    else:
                        continue
                    t_list.append(float(p.t))
                    f_list.append(f_hz)

                if f_list:
                    ref_hz = float(f_list[-1])
                else:
                    ref_hz = nominal_hz

                if f_list and ref_hz > 0:
                    freqs_np = np.array(f_list, dtype=float)
                    ppm_list = [to_ppm(v, ref_hz) for v in freqs_np]
                    max_ppm = to_ppm(float(np.max(freqs_np)), ref_hz)
                    min_ppm = to_ppm(float(np.min(freqs_np)), ref_hz)
                    mono_ppm = calc_monotonicity_ppm(freqs_np, ref_hz)
                    max_outlier_ppm = calc_outliers(
                        freqs_np, ref_hz,
                        threshold_ppm=self.accept_cfg.get(
                            'outlier_threshold_ppm', 20.0))
                    max_f = float(np.max(freqs_np))
                    min_f = float(np.min(freqs_np))
                else:
                    ppm_list = []
                    max_ppm = rec.max_ppm
                    min_ppm = rec.min_ppm
                    mono_ppm = rec.monotonicity_ppm or 0.0
                    max_outlier_ppm = (getattr(rec, 'max_outlier_ppm', 0.0)
                                       or 0.0)
                    max_f = rec.max_freq
                    min_f = rec.min_freq

                loaded.append({
                    'mcu': rec.mcu_number,
                    'resonator': rec.resonator_number,
                    'cycle': rec.cycle_type,
                    'nominal_khz': nominal_khz,
                    'ref_hz': ref_hz,
                    't': t_list,
                    'f': f_list,
                    'f_ppm': ppm_list,
                    'max': max_f,
                    'min': min_f,
                    'max_ppm': max_ppm,
                    'min_ppm': min_ppm,
                    'mono_ppm': mono_ppm,
                    'max_outlier_ppm': max_outlier_ppm,
                    'start': rec.start_time,
                    'end': rec.end_time,
                    'reason': 'loaded_from_db',
                })

            self.measurements = loaded
            self.on_summary_updated()
            self.on_plot_refresh()
            self.log(f'Итого загружено: {len(loaded)} измерений для МСК {mcu} '
                     f'(Гц восстановлены из ppm, метрики - от последней точки)')
        except Exception as e:
            import traceback
            self.log(f'Ошибка загрузки из БД: {e}')
            traceback.print_exc()
        finally:
            session.close()

    def save_to_db(self, epsilon_value):
        if not self.measurements:
            self.log('Нет данных для сохранения')
            return
        if self.current_mcu is None:
            self.log('МСК не задан')
            return
        try:
            session = self.ensure_db()
            saved = 0
            updated = 0

            for m in self.measurements:
                ref_hz = m.get('ref_hz')
                if not ref_hz or ref_hz <= 0:
                    if m.get('f'):
                        ref_hz = float(m['f'][-1])
                    else:
                        ref_hz = (m.get('nominal_khz') or 0) * 1e3

                existing = (session.query(Measurement)
                            .filter_by(mcu_number=m['mcu'],
                                       resonator_number=m['resonator'],
                                       cycle_type=m['cycle']).first())

                if existing is None:
                    rec = Measurement(
                        mcu_number=m['mcu'],
                        resonator_number=m['resonator'],
                        cycle_type=m['cycle'],
                        nominal_khz=m['nominal_khz'],
                        start_time=m['start'],
                        end_time=m['end'],
                        max_freq=m['max'],
                        min_freq=m['min'],
                        max_ppm=m['max_ppm'],
                        min_ppm=m['min_ppm'],
                        monotonicity_ppm=m['mono_ppm'],
                        max_outlier_ppm=m.get('max_outlier_ppm', 0.0),
                        epsilon=epsilon_value,
                        points_count=len(m['t']),
                    )
                    session.add(rec)
                    session.flush()

                    pts = [MeasurementPoint(
                        measurement_id=rec.id,
                        t=t, frequency=f,
                        ppm=(to_ppm(f, ref_hz) if ref_hz > 0 else 0.0))
                        for t, f in zip(m['t'], m['f'])]
                    session.add_all(pts)
                    saved += 1
                else:
                    existing.nominal_khz = m['nominal_khz']
                    existing.max_freq = m['max']
                    existing.min_freq = m['min']
                    existing.max_ppm = m['max_ppm']
                    existing.min_ppm = m['min_ppm']
                    existing.monotonicity_ppm = m['mono_ppm']
                    existing.max_outlier_ppm = m.get('max_outlier_ppm', 0.0)
                    existing.points_count = len(m['t'])

                    (session.query(MeasurementPoint)
                     .filter_by(measurement_id=existing.id)
                     .delete(synchronize_session=False))
                    pts = [MeasurementPoint(
                        measurement_id=existing.id,
                        t=t, frequency=f,
                        ppm=(to_ppm(f, ref_hz) if ref_hz > 0 else 0.0))
                        for t, f in zip(m['t'], m['f'])]
                    session.add_all(pts)
                    updated += 1

            rows = self.build_summary_rows()
            for r in rows:
                s_rec = (session.query(Summary)
                         .filter_by(mcu_number=r['mcu'],
                                    resonator_number=r['resonator']).first())
                if s_rec is None:
                    s_rec = Summary(mcu_number=r['mcu'],
                                    resonator_number=r['resonator'])
                    session.add(s_rec)
                s_rec.nominal_khz = r['nominal_khz']
                s_rec.max_ppm = r['max_ppm']
                s_rec.min_ppm = r['min_ppm']
                s_rec.monotonicity_ppm = r['monotonicity_ppm']
                s_rec.cycles_count = r['cycles_count']
                s_rec.updated_at = datetime.datetime.utcnow()
                s_rec.max_outlier_ppm = r.get('max_outlier_ppm', 0.0)

            session.commit()
            session.close()
            self.log(f'Сохранено в БД: {saved} новых, {updated} обновлено, '
                     f'сводных записей: {len(rows)} '
                     f'(ppm относительно последней точки)')
        except Exception as e:
            import traceback
            self.log(f'Ошибка БД: {e}')
            traceback.print_exc()

    # =========================================================== PDF
    def export_summary(self):
        out_dir = _resolve_path(self.cfg['pdf']['output_dir'])
        os.makedirs(out_dir, exist_ok=True)
        fname = (f"summary_{self.current_mcu or 'MCU'}_"
                 f"{datetime.datetime.now():%Y%m%d_%H%M%S}.pdf")
        path = os.path.join(out_dir, fname)
        rows = self.build_summary_rows()
        export_summary_pdf(path,
                           self.current_mcu or '-',
                           self.current_mcu_nominal_khz or 0.0,
                           rows,
                           self.cfg['pdf'].get('font_path', ''))
        self.log(f'PDF сохранён: {path}')
        self.on_pdf_created(path)

    def export_graphs(self, data):
        out_dir = _resolve_path(self.cfg['pdf']['output_dir'])
        os.makedirs(out_dir, exist_ok=True)
        fname = (f"graphs_{self.current_mcu or 'MCU'}_"
                 f"{datetime.datetime.now():%Y%m%d_%H%M%S}.pdf")
        path = os.path.join(out_dir, fname)
        export_graphs_pdf(path, data,
                          self.cfg['pdf'].get('font_path', ''))
        self.log(f'PDF сохранён: {path} ({len(data)} графиков)')
        self.on_pdf_created(path)

    # =========================================================== shutdown
    def shutdown(self):
        self.worker_stop.set()
        if self.device:
            try:
                with self.device_lock:
                    self.device.close()
            except Exception:
                pass