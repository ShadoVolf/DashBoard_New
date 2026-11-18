"""Unit-тесты protocol_parser.

    python -m pytest tests/test_protocol_parser.py -q
    python tests/test_protocol_parser.py
"""
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
            if '-' in s or '\u2013' in s or '\u2014' in s:
                import re
                parts = re.split(r'[-\u2013\u2014]', s)
                if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                    a, b = parts[0].strip(), parts[1].strip()
                    def _num(x):
                        m = re.search(r'(\d+)', x)
                        return int(m.group(1)) if m else None
                    na, nb = _num(a), _num(b)
                    if na is not None and nb is not None and na <= nb and nb - na < 500:
                        prefix = re.match(r'([A-Za-z]*)', a).group(1)
                        return [f'{prefix}{i}' for i in range(na, nb + 1)]
            return [x.strip() for x in s.replace(';', ',').split(',') if x.strip()]

        arch_data.parse_numbers_input = parse_numbers_input
        sys.modules['Archive_View'] = arch
        sys.modules['Archive_View.Archive_Data'] = arch_data


_install_stubs()
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from Assistant import protocol_parser as pp  # noqa: E402


class TestProtocolParser(unittest.TestCase):

    def test_open_protocols(self):
        r = pp.parse('открой протоколы')
        self.assertEqual(r['intent'], 'open_protocols')

    def test_open_protocols_msk(self):
        r = pp.parse('открой модуль протоколов МСК 456')
        self.assertEqual(r['intent'], 'open_protocols')
        self.assertEqual(r['params'].get('msk'), '456')

    def test_create_with_numbers_and_msk(self):
        r = pp.parse('создай протокол МСК 456 номера JN4450-JN4452')
        self.assertEqual(r['intent'], 'create_protocols')
        self.assertEqual(r['params']['msk_or_spec'], '456')
        self.assertTrue(r['params']['numbers'])
        self.assertEqual(r['params']['psi_type'], 'ОТК')
        self.assertFalse(r['params']['psi_type_explicit'])

    def test_create_psi_explicit(self):
        r = pp.parse('создай протокол ПСИ МСК 826-130')
        self.assertEqual(r['intent'], 'create_protocols')
        self.assertEqual(r['params']['psi_type'], 'ПСИ')
        self.assertTrue(r['params']['psi_type_explicit'])

    def test_create_loose_numbers(self):
        r = pp.parse('создай протокол МСК 456 JN4450-JN4451')
        self.assertEqual(r['intent'], 'create_protocols')
        self.assertTrue(r['params'].get('numbers'))

    def test_search_msk(self):
        r = pp.parse('найди протоколы МСК 456')
        self.assertEqual(r['intent'], 'search_protocols')
        self.assertEqual(r['params']['msk'], '456')

    def test_search_with_date(self):
        r = pp.parse('покажи протоколы МСК 456 за 2026-03-15')
        self.assertEqual(r['intent'], 'search_protocols')
        self.assertEqual(r['params'].get('date'), '2026-03-15')

    def test_latest_protocol(self):
        r = pp.parse('последний протокол МСК 456')
        self.assertEqual(r['intent'], 'latest_protocol')
        self.assertTrue(r['params'].get('latest'))

    def test_get_info_by_id(self):
        r = pp.parse('протокол ID 312494')
        self.assertEqual(r['intent'], 'get_protocol_info')
        self.assertEqual(r['params']['protokol_id'], 312494)

    def test_print_protocol(self):
        r = pp.parse('напечатай протокол 312494')
        self.assertEqual(r['intent'], 'print_protocol')
        self.assertEqual(r['params']['protokol_id'], 312494)

    def test_print_does_not_catch_graphs(self):
        r = pp.parse('pdf графики МСК 456')
        self.assertIsNone(r)

    def test_print_bare_id(self):
        r = pp.parse('напечатай 312494')
        self.assertEqual(r['intent'], 'print_protocol')
        self.assertEqual(r['params']['protokol_id'], 312494)

    def test_send_to_otk(self):
        r = pp.parse('отправь в ОТК протокол 312494')
        self.assertEqual(r['intent'], 'send_to_otk')
        self.assertEqual(r['params']['protokol_id'], 312494)

    def test_delete_numbers(self):
        r = pp.parse('удали номера JN4450 из протокола 312494')
        self.assertEqual(r['intent'], 'delete_numbers')
        self.assertEqual(r['params']['protokol_id'], 312494)
        self.assertTrue(r['params']['numbers'])

    def test_add_numbers(self):
        r = pp.parse('добавь номера JN4500 в протокол 312494')
        self.assertEqual(r['intent'], 'add_numbers')
        self.assertEqual(r['params']['protokol_id'], 312494)

    def test_add_order(self):
        r = pp.parse('добавь заказ 12345 от 15.03.2026 в протокол 312494')
        self.assertEqual(r['intent'], 'add_order')
        self.assertEqual(r['params']['protokol_id'], 312494)
        order = r['params'].get('order') or {}
        self.assertEqual(order.get('lot'), '12345')
        self.assertEqual(order.get('date'), '2026-03-15')

    def test_bare_id(self):
        r = pp.parse('312494')
        self.assertEqual(r['intent'], 'get_protocol_info')
        self.assertEqual(r['params']['protokol_id'], 312494)

    def test_empty(self):
        self.assertIsNone(pp.parse(''))
        self.assertIsNone(pp.parse('   '))

    def test_unrelated(self):
        self.assertIsNone(pp.parse('какая погода завтра'))

    def test_generic_protocols_opens(self):
        r = pp.parse('протоколы')
        self.assertEqual(r['intent'], 'open_protocols')

    def test_search_psi_filter(self):
        r = pp.parse('список протоколов ПСИ МСК 456')
        self.assertIn(r['intent'], ('search_protocols', 'latest_protocol'))
        self.assertEqual(r['params'].get('psi_type'), 'ПСИ')


class TestGraphProtocolRouting(unittest.TestCase):

    def test_graph_parser_ignores_protocol(self):
        from Assistant import graph_parser as gp
        self.assertIsNone(gp.parse('напечатай протокол 312494'))
        self.assertIsNone(gp.parse('pdf протокол МСК 456'))

    def test_graph_parser_still_handles_graphs(self):
        from Assistant import graph_parser as gp
        r = gp.parse('открой графики МСК 456')
        self.assertIsNotNone(r)
        self.assertEqual(r['intent'], 'open_graphs_msk')

    def test_graph_pdf_numbers(self):
        from Assistant import graph_parser as gp
        r = gp.parse('pdf графики номеров JN4450-JN4460')
        self.assertIsNotNone(r)
        self.assertEqual(r['intent'], 'pdf_numbers')


if __name__ == '__main__':
    unittest.main()
