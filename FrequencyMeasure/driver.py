import time
import re
import pyvisa
from pyvisa.errors import VisaIOError


class CH3_85_6:
    FUNC_CMDS = {
        'FREQ':  ':SENS:FUNC "FREQ"',
        'PER':   ':SENS:FUNC "PER"',
        'RATIO': ':SENS:FUNC "RATIO"',
        'DUTY':  ':SENS:FUNC "DUTY"',
        'PHASE': ':SENS:FUNC "PHASE"',
        'PWID':  ':SENS:FUNC "PWID"',
        'NWID':  ':SENS:FUNC "NWID"',
        'TI':    ':SENS:FUNC "TI"',
        'TOT':   ':SENS:FUNC "TOT"',
    }
    IDN_PATTERNS = ('43-85', 'ч3-85', 'ch3-85', 'suin')

    def __init__(self, resource=None, backend='@py', baudrate=9600,
                 timeout=5000, verbose=False, **kwargs):
        self.rm = (pyvisa.ResourceManager(backend) if backend
                   else pyvisa.ResourceManager())
        self.timeout = timeout
        self.verbose = verbose
        if resource in (None, 'auto'):
            resource = self.find_device(baudrate=baudrate, verbose=verbose)
            if resource is None:
                self.rm.close()
                raise RuntimeError("Ч3-85/6 не найден")
        open_kwargs = {'timeout': timeout}
        if resource.startswith('ASRL'):
            open_kwargs.update({
                'baud_rate': baudrate, 'data_bits': 8,
                'parity': pyvisa.constants.Parity.none,
                'stop_bits': pyvisa.constants.StopBits.one,
                'flow_control': pyvisa.constants.ControlFlow.none,
            })
        open_kwargs.update(kwargs)
        self.inst = self.rm.open_resource(resource, **open_kwargs)
        self.inst.read_termination = '\n'
        self.inst.write_termination = '\n'
        self.resource = resource
        try:
            self.set_function('FREQ')
        except Exception:
            pass

    @classmethod
    def find_device(cls, baudrate=9600, probe_timeout=800, verbose=False,
                    idn_patterns=None):
        patterns = tuple(p.lower() for p in (idn_patterns or cls.IDN_PATTERNS))
        try:
            rm = pyvisa.ResourceManager('@py')
        except Exception:
            rm = pyvisa.ResourceManager()
        resources = sorted(rm.list_resources(),
                           key=lambda r: (0 if r.startswith('USB')
                                          else 1 if r.startswith('ASRL')
                                          else 2))
        for res in resources:
            try:
                kw = {'timeout': probe_timeout}
                if res.startswith('ASRL'):
                    kw.update({
                        'baud_rate': baudrate, 'data_bits': 8,
                        'parity': pyvisa.constants.Parity.none,
                        'stop_bits': pyvisa.constants.StopBits.one,
                        'flow_control': pyvisa.constants.ControlFlow.none,
                    })
                inst = rm.open_resource(res, **kw)
                inst.read_termination = '\n'
                inst.write_termination = '\n'
                try:
                    idn = inst.query('*IDN?').strip().lower()
                except VisaIOError:
                    idn = ''
                inst.close()
                if idn and any(p in idn for p in patterns):
                    if verbose:
                        print(f"[CH3] Найден: {res} -> {idn!r}")
                    return res
                if verbose:
                    print(f"[CH3] {res} -> {idn!r} (не подходит)")
            except Exception as e:
                if verbose:
                    print(f"[CH3] {res} -> {e}")
        return None

    def _write(self, cmd):
        self.inst.write(cmd)

    def _query(self, cmd, timeout=None):
        """query с временным переопределением таймаута."""
        old = self.inst.timeout
        if timeout is not None:
            self.inst.timeout = timeout
        try:
            return self.inst.query(cmd).strip()
        finally:
            self.inst.timeout = old

    def _recover_after_timeout(self):
        """Восстановление после таймаута чтения:
          - сбросить буферы VISA (чтобы не осталось хвоста);
          - очистить статус прибора командой *CLS.
        """
        for op in (pyvisa.constants.BufferOperation.discard_read_buffer_no_io,
                   pyvisa.constants.BufferOperation.discard_write_buffer):
            try:
                self.inst.flush(op)
            except Exception:
                pass
        try:
            self.inst.write('*CLS')
            time.sleep(0.05)
        except Exception:
            pass

    def _parse_float(self, resp):
        if not resp:
            return None
        try:
            return float(resp)
        except ValueError:
            m = re.search(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', resp)
            return float(m.group()) if m else None

    def identify(self):
        return self._query('*IDN?')

    def set_function(self, func):
        self._write(self.FUNC_CMDS[func.upper()])
        time.sleep(0.15)

    def set_gate_time(self, seconds):
        self._write(f':SENS:FREQ:GATE {seconds}')
        time.sleep(0.05)

    def measure_frequency(self, gate_time=0.1, read_timeout=None):
        """Однократное измерение частоты.
        read_timeout - если None, используется self.timeout (из config).
        """
        if read_timeout is None:
            read_timeout = self.timeout
        try:
            self._write(':INIT')
            time.sleep(gate_time + 0.05)
            resp = self._query(':FETCH?', timeout=read_timeout)
            return self._parse_float(resp)
        except VisaIOError:
            self._recover_after_timeout()
            return None

    def close(self):
        try:
            self.inst.close()
        except Exception:
            pass
        try:
            self.rm.close()
        except Exception:
            pass