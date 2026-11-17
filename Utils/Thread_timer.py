import time
import threading
from typing import Callable, Union

from Pribory.Network_Analyzer import VNA_Data
from Pribory.Network_Analyzer.VNA_Data import VNA_DATA
from RT.RT_TECH_Parameters.RT_Data import RT_DATA


class Timer_D:

    def __init__(self, dpg, value_func: Callable[[], Union[float, str]] = None,
                 display='voltage_val', data='V', sleep_time=0.5):
        self.start_time = None
        self.elapsed_time = 0
        self.running = False
        self.stopped = True
        self.thread = None
        self.dpg = dpg
        self.func = value_func
        self.display = display
        self.data = data
        self.sleep_time = sleep_time

    def start(self):
        if not self.running:
            if self.stopped:
                self.start_time = time.time()
                self.stopped = False
            self.running = True
            self.thread = threading.Thread(target=self.update_timer)
            self.thread.start()

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join()
        self.stopped = True

    def reset(self):
        self.stop()
        self.elapsed_time = 0
        self.start_time = None

    def safe_float(self, s):
        s = str(s).strip()
        if s.replace('.', '', 1).replace('-', '', 1).isdigit():
            return float(s)
        return 0.0

    def update_timer(self):
        while self.running:
            current_time = time.time()
            elapsed = current_time - self.start_time + self.elapsed_time
            mins, secs = divmod(elapsed, 60)
            hours, mins = divmod(mins, 60)
            timer_str = f"{int(mins):02d}:{int(secs):02d}"
            result_str = self.func()
            self.dpg.set_value(self.display, result_str)
            if self.data == 'V':
                RT_DATA.Current_V = result_str
                RT_DATA.Current_V_Status = True
            elif self.data == 'A':
                pre_a = self.safe_float(RT_DATA.Current_A)
                cur_a = self.safe_float(result_str)
                RT_DATA.Current_A = result_str
                RT_DATA.Current_dA = str(abs(cur_a-pre_a))
                RT_DATA.Current_A_Status = True
            elif self.data == 'F':
                VNA_Data.VNA_DATA.current_F = result_str
                VNA_DATA.current_F_status = True
            elif self.data == 'P':
                RT_DATA.Current_P = result_str
            elif self.data == 'F_ppm':
                pre_f = self.safe_float(VNA_DATA.current_F_ppm)
                cur_f = self.safe_float(result_str)
                VNA_DATA.current_dF_ppm = str(abs(cur_f-pre_f))
                VNA_Data.VNA_DATA.current_F_ppm = result_str
            elif self.data == 'R':
                VNA_Data.VNA_DATA.current_R = result_str
            time.sleep(self.sleep_time)

        # Сохраняем прошедшее время при остановке
        if self.start_time is not None:
            self.elapsed_time += time.time() - self.start_time
