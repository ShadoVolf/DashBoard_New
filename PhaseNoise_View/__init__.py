"""Модуль фазовых шумов. Настраивает логгер пакета."""
import logging
import sys

_log = logging.getLogger("PhaseNoise")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter(
        "[%(asctime)s][%(name)s][%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"))
    _log.addHandler(_h)
    _log.setLevel(logging.DEBUG)
    _log.propagate = False

from .PhaseNoise_Window import create_phase_noise_window  # noqa: E402

__all__ = ["create_phase_noise_window"]