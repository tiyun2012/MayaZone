import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facial_system import cage_core

IDENTITY = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]


def cage_fixture():
    points = [[1., 0., 0.], [-1., 0., 0.], [0., 1., 0.],
              [2., 2., 0.], [-2., 2., 0.]]
    data = {'schema': cage_core.SCHEMA, 'version': 1, 'weight': 1., 'enabled': True,
            'mode': 'Offset', 'rest_cage_points_cm': points,
            'rest_cage_world_matrix_cm': list(IDENTITY),
            'symmetry': cage_core.symmetry_map(points),
            'cage_snapshot': {'vertex_count': len(points)}}
    for key in ('source', 'root', 'cage', 'preview', 'session'):
        data[key] = {'uuid': key, 'path': key, 'name': key}
    return data


class CageCoreTests(unittest.TestCase):
    def test_pairing_is_unique_and_identifies_the_center_seam(self):
        data = cage_fixture()
        self.assertEqual(data['symmetry']['pairs'], [[0, 1], [3, 4]])
        self.assertEqual(data['symmetry']['seam'], [2])
        self.assertEqual(data['symmetry']['unpaired'], [])
        cage_core.validate(data)

    def test_mirror_uses_saved_ids_after_large_asymmetric_edits(self):
        data = cage_fixture()
        current = copy.deepcopy(data['rest_cage_points_cm'])
        current[0] = [5., 9., -3.]
        current[1] = [-10., 2., 20.]
        target = cage_core.mirrored_positions(current, data['symmetry'], 'positive')
        self.assertEqual(target[1], [-5., 9., -3.])
        self.assertEqual(current[1], [-10., 2., 20.])

    def test_reverse_mirroring_and_seam_projection(self):
        data = cage_fixture()
        points = copy.deepcopy(data['rest_cage_points_cm'])
        points[1], points[2] = [-4., 3., 2.], [.8, 7., 2.]
        target = cage_core.mirrored_positions(points, data['symmetry'], 'negative')
        self.assertEqual(target[0], [4., 3., 2.])
        self.assertEqual(target[2], [0., 7., 2.])

    def test_average_keeps_both_sides_information(self):
        data = cage_fixture()
        points = copy.deepcopy(data['rest_cage_points_cm'])
        points[0], points[1] = [3., 4., 2.], [-1., 2., 4.]
        result = cage_core.mirrored_positions(points, data['symmetry'], 'average')
        self.assertEqual(result[0], [2., 3., 3.])
        self.assertEqual(result[1], [-2., 3., 3.])

    def test_partial_custom_cage_reports_unmatched_vertices(self):
        pairing = cage_core.symmetry_map([[1., 0., 0.], [-1., 0., 0.], [3., 9., 1.]])
        self.assertEqual(pairing['unpaired'], [2])

    def test_native_enum_values_are_resolved_by_label(self):
        self.assertEqual(cage_core.enum_index('Offset:Surface:Snap', 'Offset'), 0)
        self.assertEqual(cage_core.enum_index('Global:Offset:Surface', 'Offset'), 1)
        self.assertEqual(cage_core.enum_index('Global=3:Offset=7:Surface', 'Surface'), 8)
        with self.assertRaises(ValueError):
            cage_core.enum_index('Surface', 'Offset')

    def test_export_keeps_rest_capture_independent_of_current_edits(self):
        data = cage_fixture()
        original = copy.deepcopy(data)
        current = [[x + .3, y, z] for x, y, z in data['rest_cage_points_cm']]
        result = cage_core.export_data(data, current, IDENTITY)
        self.assertEqual(data, original)
        self.assertEqual(result['rest_cage_points_cm'], original['rest_cage_points_cm'])
        self.assertNotEqual(result['current_cage_points_cm'], result['rest_cage_points_cm'])

    def test_changed_vertex_count_and_nonfinite_rest_are_rejected(self):
        data = cage_fixture()
        with self.assertRaises(ValueError):
            cage_core.mirrored_positions(data['rest_cage_points_cm'][:-1], data['symmetry'])
        for value in (float('nan'), float('inf')):
            broken = copy.deepcopy(data)
            broken['rest_cage_world_matrix_cm'][12] = value
            with self.assertRaises(ValueError):
                cage_core.validate(broken)


if __name__ == '__main__':
    unittest.main()
