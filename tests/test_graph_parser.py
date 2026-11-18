"""Unit-тесты graph_parser (без UI / БД)."""
from __future__ import annotations

import os
import sys
import types
import unittest


def _install_stubs():
    if 'Archive_View' not in sys.modules:
        arch = types.ModuleType('Archive_View')
        arch_data = types.ModuleType('Archive_View.Archive_Data')

        def parse_numbers_input(s):
            s = (s or '').strip()
            if not s:
                return []
            if '-' in s:
                import re
                a, b = s.split('-', 1)
                ma, mb = re.search(r'(\d+)', a), re.search(r'(\d+)', b)
                if ma and mb:
                    na, nb = int(ma.group(1)), int(mb.group(1))
                    prefix = re.match(r'([A-Za-z]*)', a).group(1)
                    return [f'{prefix}{i}' for i in range(na, nb + 1)]
            return [s]

        arch_data.parse_numbers_input = parse_numbers_input
        sys.modules['Archive_View'] = arch
        sys.modules['Archive_View.Archive_Data'] = arch_data


_install_stubs()
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from Assistant import graph_parser as gp  # noqa: E402


class TestGraphParser(unittest.TestCase):

    def test_open_msk(self):
        r = gp.parse('открой графики МСК 456')
        self.assertEqual(r['intent'], 'open_graphs_msk')
        self.assertEqual(r['params']['msk'], '456')

    def test_param_implicit(self):
        r = gp.parse('графики МСК 456 без нагрузки')
        self.assertEqual(r['intent'], 'open_graphs_msk')
        self.assertIn('без нагруз', (r['params'].get('param') or '').lower())

    def test_density(self):
        r = gp.parse('плотность распределения МСК 456')
        self.assertEqual(r['intent'], 'density')

    def test_all_on_one(self):
        r = gp.parse('все графики МСК 456 на одном поле')
        self.assertEqual(r['intent'], 'all_on_one')

    def test_compare(self):
        r = gp.parse('сравни МСК 456 и 457 по F')
        self.assertEqual(r['intent'], 'compare_msk')
        self.assertEqual(r['params']['msk_a'], '456')
        self.assertEqual(r['params']['msk_b'], '457')

    def test_auto_report(self):
        r = gp.parse('отчёт по МСК 456')
        self.assertEqual(r['intent'], 'auto_report')

    def test_quality_filter(self):
        r = gp.parse('графики МСК 456 только годные')
        self.assertEqual(r['params'].get('quality'), 'only_good')

    def test_last_n(self):
        r = gp.parse('последние 20 номеров МСК 456 графики')
        self.assertEqual(r['params'].get('last_n'), 20)

    def test_measure_id(self):
        r = gp.parse('открой графики id замера 12345')
        self.assertEqual(r['intent'], 'open_by_measure_id')
        self.assertEqual(r['params']['measure_id'], '12345')

    def test_skips_protocol(self):
        self.assertIsNone(gp.parse('напечатай протокол 1'))


if __name__ == '__main__':
    unittest.main()
