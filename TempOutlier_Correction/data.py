"""Zagruzka i sohranenie dannyh psidata / psidatatemp."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
from sqlalchemy import create_engine, text, bindparam

from Options import get_connection_string

from .constants import SOURCES

_engine = None
_source = {
    "main_table": "psidata",
    "temps_table": "psidatatemp",
    "label": "Osnovnaya",
}


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            str(get_connection_string()),
            pool_pre_ping=True,
            future=True,
        )
    return _engine
