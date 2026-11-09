import gzip
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from facial_system import validation

spec = importlib.util.spec_from_file_location('native_reference_model', ROOT / 'developer/native_rebuild/model.py')
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


class ReferenceDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = json.loads((ROOT / 'facial_system/data/behavior.json').read_text())
        with gzip.open(ROOT / 'facial_system/data/validation_cases.json.gz', 'rt') as handle:
            cls.cases = json.load(handle)['cases']

    def test_all_bundled_poses_with_fitted_translation_offsets(self):
        self.assertEqual(len(self.cases), 107)
        self.assertEqual(len(self.model['outputs']), 1962)
        offsets = {row['destination']: math.sin(index * .51) * .5
                   for index, row in enumerate(self.model['outputs']) if row['dof'] < 3}
        maxima = [0., 0., 0.]
        for case in self.cases:
            actual, _, _ = reference.evaluate(self.model, case['raw'])
            correct = validation.adjusted_reference(self.model['outputs'], case['expected'], offsets)
            for row, value, expected in zip(self.model['outputs'], actual, correct):
                group = row['dof'] // 3
                if group == 0:
                    value += offsets[row['destination']]
                maxima[group] = max(maxima[group], abs(value - expected))
        self.assertLessEqual(maxima[0], .006)
        self.assertLessEqual(maxima[1], .025)
        self.assertLessEqual(maxima[2], 1e-5)

    def test_saved_upper_nose_modifiers_are_joint_and_map_neutral(self):
        raw = [0.] * self.model['raw_count']
        for index in (254, 258, 262):
            raw[index] = 1.
        neutral, neutral_maps, _ = reference.evaluate(self.model, raw)
        raw[53] = raw[54] = 1.
        current, maps, _ = reference.evaluate(self.model, raw)
        self.assertEqual(current, neutral)
        self.assertEqual(maps, neutral_maps)


if __name__ == '__main__':
    unittest.main()
