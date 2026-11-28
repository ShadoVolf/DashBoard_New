"""
Тесты автоподбора спецификаций (варианты 1 и 2):
  - гибкий порог ppm (все кандидаты ≤ threshold, не только min);
  - score-ранжирование;
  - capacity-фильтр PHYSICAL;
  - classify_temp_match;
  - порядок итогового списка.

Чистая логика без БД — импорт функций из Analyze_Data.
"""
import os
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

# Корень патча: artifacts/ рядом с Temperature_Measure-совместимой структурой
ROOT = Path(__file__).resolve().parents[1]
# Позволяем импортировать Analyze_Data как модуль: sys.path → artifacts
sys.path.insert(0, str(ROOT))

# Analyze_Data тянет Options / MEASURE_DATA — подменяем лёгкими stubs до импорта
import types

if 'Options' not in sys.modules:
    opt = types.ModuleType('Options')
    opt.get_connection_string = lambda: 'sqlite:///:memory:'
    opt._fast = True
    opt.is_fast_spec_search_enabled = lambda: bool(getattr(opt, '_fast', True))
    opt.set_fast_spec_search = lambda v: setattr(opt, '_fast', bool(v)) or True
    opt.load_app_settings = lambda force=False: {'fast_spec_search': opt._fast}
    opt.get_app_directory = lambda: str(ROOT)
    opt.get_app_settings_path = lambda: str(ROOT / 'app_settings.json')
    sys.modules['Options'] = opt

# Лёгкие stubs внешних зависимостей Analyze_Data
if 'sqlalchemy' not in sys.modules:
    sa = types.ModuleType('sqlalchemy')
    sa.create_engine = lambda *a, **k: None
    sys.modules['sqlalchemy'] = sa

if 'tabulate' not in sys.modules:
    tab = types.ModuleType('tabulate')
    tab.tabulate = lambda *a, **k: ''
    sys.modules['tabulate'] = tab

if 'Temperature_Measure' not in sys.modules:
    pkg = types.ModuleType('Temperature_Measure')
    pkg.__path__ = []
    sys.modules['Temperature_Measure'] = pkg

if 'Temperature_Measure.measure_data_class' not in sys.modules:
    mdc = types.ModuleType('Temperature_Measure.measure_data_class')

    class MEASURE_DATA:
        measure_file = {}

    mdc.MEASURE_DATA = MEASURE_DATA
    sys.modules['Temperature_Measure.measure_data_class'] = mdc

# Имя файла Analyze_Data.py лежит в ROOT (артефакты патча)
import importlib.util

spec = importlib.util.spec_from_file_location(
    'Analyze_Data', ROOT / 'Analyze_Data.py'
)
Analyze_Data = importlib.util.module_from_spec(spec)
sys.modules['Analyze_Data'] = Analyze_Data
spec.loader.exec_module(Analyze_Data)

compute_freq_diff_ppm = Analyze_Data.compute_freq_diff_ppm
capacity_matches = Analyze_Data.capacity_matches
score_nomenclature_candidate = Analyze_Data.score_nomenclature_candidate
score_with_temp_match = Analyze_Data.score_with_temp_match
classify_temp_match = Analyze_Data.classify_temp_match
filter_and_rank_nomenclature = Analyze_Data.filter_and_rank_nomenclature
get_ppm_threshold = Analyze_Data.get_ppm_threshold
set_ppm_threshold = Analyze_Data.set_ppm_threshold
PPM_THRESHOLD_DEFAULT = Analyze_Data.PPM_THRESHOLD_DEFAULT
SCORE_BASE = Analyze_Data.SCORE_BASE
SCORE_CAPACITY_MATCH = Analyze_Data.SCORE_CAPACITY_MATCH
SCORE_TEMP_EXACT = Analyze_Data.SCORE_TEMP_EXACT
SCORE_TEMP_SUBSET = Analyze_Data.SCORE_TEMP_SUBSET
SpecRefCache = Analyze_Data.SpecRefCache
get_spec_cache = Analyze_Data.get_spec_cache
clear_spec_cache = Analyze_Data.clear_spec_cache
get_psi_specification = Analyze_Data.get_psi_specification


def _nom_df(rows):
    """rows: list of (name, nom_id, freq_hz, cn)"""
    return pd.DataFrame([
        {'наименование': n, 'номенклатура': i, 'частота': f, 'Cn(pF)': c}
        for n, i, f, c in rows
    ])


class TestPpmHelpers(unittest.TestCase):
    def test_zero_target(self):
        self.assertEqual(compute_freq_diff_ppm(10e6, 0), float('inf'))

    def test_exact_match(self):
        self.assertAlmostEqual(compute_freq_diff_ppm(10_000_000, 10_000_000), 0.0)

    def test_100_ppm(self):
        # 10 MHz + 1 kHz = 100 ppm
        self.assertAlmostEqual(
            compute_freq_diff_ppm(10_001_000, 10_000_000), 100.0, places=6
        )


class TestCapacity(unittest.TestCase):
    def test_non_physical_always_ok(self):
        ok, reason = capacity_matches('SERIES', 0, 0)
        self.assertTrue(ok)
        self.assertIsNone(reason)
        ok, reason = capacity_matches('EQREACT', 12, 0)
        self.assertTrue(ok)

    def test_physical_fl_needs_cn(self):
        ok, reason = capacity_matches('PHYSICAL', 12.0, 0)
        self.assertFalse(ok)
        self.assertIn('Cn', reason)

        ok, reason = capacity_matches('PHYSICAL', 12.0, 8.0)
        self.assertTrue(ok)

    def test_physical_series_needs_zero_cn(self):
        ok, reason = capacity_matches('PHYSICAL', 0, 5.0)
        self.assertFalse(ok)
        ok, reason = capacity_matches('PHYSICAL', 0, 0)
        self.assertTrue(ok)


class TestScore(unittest.TestCase):
    def test_lower_ppm_higher_score(self):
        s1 = score_nomenclature_candidate(10, True)
        s2 = score_nomenclature_candidate(50, True)
        self.assertGreater(s1, s2)

    def test_capacity_bonus(self):
        with_c = score_nomenclature_candidate(10, True)
        without = score_nomenclature_candidate(10, False)
        self.assertAlmostEqual(with_c - without, SCORE_CAPACITY_MATCH)

    def test_temp_bonus(self):
        base = 900.0
        self.assertAlmostEqual(
            score_with_temp_match(base, 'exact') - base, SCORE_TEMP_EXACT
        )
        self.assertAlmostEqual(
            score_with_temp_match(base, 'subset') - base, SCORE_TEMP_SUBSET
        )
        self.assertEqual(score_with_temp_match(base, 'none'), base)


class TestTempClassify(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(
            classify_temp_match([-40, 25, 85], [-40, 25, 85]), 'exact'
        )

    def test_subset(self):
        self.assertEqual(
            classify_temp_match([-40, 0, 25, 85], [-40, 25, 85]), 'subset'
        )

    def test_none(self):
        self.assertEqual(
            classify_temp_match([-40, 25], [0, 50, 100]), 'none'
        )


class TestFilterAndRank(unittest.TestCase):
    def setUp(self):
        set_ppm_threshold(PPM_THRESHOLD_DEFAULT)

    def tearDown(self):
        set_ppm_threshold(PPM_THRESHOLD_DEFAULT)
        if 'SPEC_PPM_THRESHOLD' in os.environ:
            del os.environ['SPEC_PPM_THRESHOLD']

    def test_all_within_threshold_not_only_min(self):
        """Вариант 2: берутся ВСЕ ≤ threshold, не только с min ppm."""
        target = 10_000_000
        df = _nom_df([
            ('A-close', 'idA', 10_000_100, 0),   # 10 ppm
            ('B-mid', 'idB', 10_000_500, 0),     # 50 ppm
            ('C-far', 'idC', 10_002_000, 0),     # 200 ppm — отсев
        ])
        accepted, rejected = filter_and_rank_nomenclature(
            df, target, 'SERIES', 0, ppm_threshold=100
        )
        names = [a['наименование'] for a in accepted]
        self.assertEqual(names, ['A-close', 'B-mid'])  # score: A > B
        self.assertEqual(len(rejected), 1)
        self.assertIn('порог', rejected[0]['reason'])
        self.assertEqual(rejected[0]['наименование'], 'C-far')

    def test_ranking_order_by_score(self):
        target = 10_000_000
        df = _nom_df([
            ('worse', 'w', 10_000_800, 0),   # 80 ppm
            ('best', 'b', 10_000_050, 0),    # 5 ppm
            ('mid', 'm', 10_000_300, 0),     # 30 ppm
        ])
        accepted, _ = filter_and_rank_nomenclature(
            df, target, 'SERIES', 0, ppm_threshold=100
        )
        self.assertEqual(
            [a['наименование'] for a in accepted],
            ['best', 'mid', 'worse']
        )
        self.assertGreater(accepted[0]['score'], accepted[1]['score'])

    def test_physical_capacity_reject(self):
        target = 10_000_000
        df = _nom_df([
            ('with-cn', 'c1', 10_000_100, 8.0),   # ok for FL>0
            ('no-cn', 'c0', 10_000_050, 0.0),     # reject: FL>0 needs Cn>0
        ])
        accepted, rejected = filter_and_rank_nomenclature(
            df, target, 'PHYSICAL', fl_value=12.0, ppm_threshold=100
        )
        self.assertEqual([a['наименование'] for a in accepted], ['with-cn'])
        self.assertEqual(len(rejected), 1)
        self.assertIn('Cn', rejected[0]['reason'])
        # no-cn имел меньший ppm, но отсеян по ёмкости
        self.assertEqual(rejected[0]['наименование'], 'no-cn')

    def test_threshold_override_session(self):
        set_ppm_threshold(30)
        target = 10_000_000
        df = _nom_df([
            ('ok', 'a', 10_000_200, 0),    # 20 ppm
            ('out', 'b', 10_000_500, 0),   # 50 ppm
        ])
        accepted, rejected = filter_and_rank_nomenclature(
            df, target, 'SERIES', 0
        )
        self.assertEqual([a['наименование'] for a in accepted], ['ok'])
        self.assertEqual(rejected[0]['наименование'], 'out')

    def test_threshold_from_env(self):
        os.environ['SPEC_PPM_THRESHOLD'] = '50'
        self.assertEqual(get_ppm_threshold(), 50.0)
        target = 10_000_000
        df = _nom_df([
            ('in', 'a', 10_000_400, 0),   # 40 ppm
            ('out', 'b', 10_000_800, 0),  # 80 ppm
        ])
        accepted, rejected = filter_and_rank_nomenclature(
            df, target, 'SERIES', 0
        )
        self.assertEqual([a['наименование'] for a in accepted], ['in'])
        self.assertEqual(len(rejected), 1)

    def test_empty_when_all_rejected(self):
        target = 10_000_000
        df = _nom_df([
            ('far', 'f', 10_010_000, 0),  # 1000 ppm
        ])
        accepted, rejected = filter_and_rank_nomenclature(
            df, target, 'SERIES', 0, ppm_threshold=100
        )
        self.assertEqual(accepted, [])
        self.assertEqual(len(rejected), 1)

    def test_score_formula(self):
        ppm = 25.0
        expected = SCORE_BASE - ppm + SCORE_CAPACITY_MATCH
        self.assertAlmostEqual(
            score_nomenclature_candidate(ppm, True), expected
        )


class TestOldBehaviourRegression(unittest.TestCase):
    """Старое поведение брало только min ppm — убеждаемся, что новое шире."""

    def test_second_best_within_threshold_kept(self):
        target = 16_000_000
        df = _nom_df([
            ('N1', '1', 16_000_160, 0),  # 10 ppm
            ('N2', '2', 16_000_800, 0),  # 50 ppm — раньше отбрасывался
        ])
        accepted, _ = filter_and_rank_nomenclature(
            df, target, 'SERIES', 0, ppm_threshold=100
        )
        self.assertEqual(len(accepted), 2)



class TestSpecRefCache(unittest.TestCase):
    def setUp(self):
        clear_spec_cache()

    def tearDown(self):
        clear_spec_cache()

    def test_clear_resets(self):
        cache = get_spec_cache()
        cache.nomeklatura_rk = pd.DataFrame({'частота': [1.0]})
        cache._loaded.add('nomeklatura_rk')
        clear_spec_cache()
        self.assertIsNone(get_spec_cache().nomeklatura_rk)
        self.assertEqual(get_spec_cache()._loaded, set())

    def test_psi_filter_from_cache_no_sql(self):
        """get_psi_specification фильтрует кэш без обращения к БД."""
        cache = get_spec_cache()
        cache.nomeklatura_rk_psi = pd.DataFrame({
            'NomenklaturaID': ['A', 'A', 'B', 'C'],
            'SpcID': [1, 2, 3, 4],
            'SpcName': ['SpcA1', 'SpcA2', 'SpcB', 'SpcC'],
        })
        cache._loaded.add('nomeklatura_rk_psi')
        result = get_psi_specification(['A', 'C'])
        names = result['SpcName'].tolist()
        self.assertEqual(names, ['SpcA1', 'SpcA2', 'SpcC'])
        self.assertEqual(len(get_psi_specification([])), 0)

    def test_ensure_spec_profiles_uses_memory(self):
        cache = get_spec_cache()
        cache.spec_profiles['S1'] = ('P1', [-40.0, 25.0], '-40 25')
        # already present — ensure should not need SQL
        out = cache.ensure_spec_profiles(['S1'])
        self.assertEqual(out['S1'][1], [-40.0, 25.0])

    def test_multi_temps_key_match(self):
        """Логика ключа multi-spec: sorted string temps."""
        cache = get_spec_cache()
        cache.spc_special = pd.DataFrame({
            'Temps': ['-40 25 85', '0 50'],
            'Multy_Spc_Name': ['MULTI-A', 'MULTI-B'],
        })
        cache._loaded.add('spc_special')
        # emulate get_multy_spec key
        temp_list = [85.0, -40.0, 25.0]
        key = tuple(sorted(str(int(float(x))) for x in temp_list))
        found = []
        for _, row in cache.spc_special.iterrows():
            if tuple(sorted(str(row['Temps']).split())) == key:
                found.append(row['Multy_Spc_Name'])
        self.assertEqual(found, ['MULTI-A'])





class TestModeSwitch(unittest.TestCase):
    def setUp(self):
        self.opt = sys.modules['Options']
        self.opt._fast = True
        clear_spec_cache()

    def tearDown(self):
        self.opt._fast = True
        clear_spec_cache()

    def test_router_find_closest_dispatches(self):
        import Analyze_Data as ad
        target = 10_000_000
        df = _nom_df([
            ('A', 'a', 10_000_100, 0),  # 10 ppm
            ('B', 'b', 10_000_500, 0),  # 50 ppm — only in fast mode
        ])
        row = pd.Series({
            'Target_Hz': target,
            'CL_Metod': 'SERIES',
            'FL': 0,
        })
        cache = get_spec_cache()
        cache.nomeklatura_rk_psi = pd.DataFrame({
            'NomenklaturaID': ['a', 'b'],
            'SpcID': [1, 2],
            'SpcName': ['SpA', 'SpB'],
        })
        cache._loaded.add('nomeklatura_rk_psi')

        self.opt._fast = True
        res_fast = ad.find_closest_specs_fast(row, df)
        self.assertEqual(len(res_fast[1]), 2)  # A and B

        # legacy: only min ppm → только A; psi заглушаем
        def _psi_stub(ids):
            return pd.DataFrame({
                'NomenklaturaID': list(ids),
                'SpcID': list(range(len(ids))),
                'SpcName': [f'Sp{x}' for x in ids],
            })
        ad.get_psi_specification_legacy = _psi_stub
        res_leg = ad.find_closest_specs_legacy(row, df)
        self.assertEqual(res_leg[1], ['A'])

    def test_build_spc_combo_list_routes(self):
        import Analyze_Data as ad
        row = pd.Series({
            'SpcName': ['Z-spec', 'A-spec'],
            'Temp_List': [25.0],
        })
        # fast path with empty profiles in cache → all dropped → «Нет»
        self.opt._fast = True
        cache = get_spec_cache()
        cache.spec_profiles['Z-spec'] = ('P', [25.0], '25')
        cache.spec_profiles['A-spec'] = ('P', [25.0], '25')
        cache.spc_special = pd.DataFrame({'Temps': [], 'Multy_Spc_Name': []})
        cache._loaded.add('spc_special')
        out_fast = ad.build_spc_combo_list(row)
        self.assertIn(out_fast[0], ('A-spec', 'Z-spec'))  # ranking order preserved from SpcName

        self.opt._fast = False
        ad.test_temp_interval_points_legacy = lambda data, lst: list(lst)
        ad.get_multy_spec_legacy = lambda r: []
        out_leg = ad.build_spc_combo_list(row)
        self.assertEqual(out_leg, ['A-spec', 'Z-spec'])  # sorted by name


if __name__ == '__main__':
    unittest.main(verbosity=2)
