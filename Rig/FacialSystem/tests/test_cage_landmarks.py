import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facial_system import cage_landmarks as marks, cage_core
from test_cage_core import cage_fixture


def landmark_fixture():
    return marks.empty({'identity': {'uuid': 'mesh', 'path': '|head|headShape'},
        'vertex_count': 6, 'topology_sha256': 'fixture-topology',
        'default_positions_cm': [[0., 0., 0.], [1., 0., 0.], [0., 1., 0.],
                                 [0., 0., 1.], [1., 0., 1.], [0., 1., 1.]]})


class CageLandmarkTests(unittest.TestCase):
    def test_named_points_cover_both_sides_and_separate_upper_lower_lips(self):
        points = marks.presets()
        self.assertEqual(len(points), 32)
        self.assertEqual(len({p['key'] for p in points}), 32)
        keys = {p['key'] for p in points}
        self.assertTrue({'upper_lip', 'lower_lip', 'eye_inner_L', 'eye_inner_R', 'mouth_corner_L', 'mouth_corner_R'} <= keys)

    def test_manual_assignment_retains_ids_and_keeps_original_capture(self):
        data = landmark_fixture()
        before = copy.deepcopy(data)
        result = marks.assign(data, 'upper_lip', 0)
        result = marks.assign(result, 'lower_lip', 1)
        self.assertEqual(data, before)
        self.assertEqual([p['source_vertex'] for p in result['items']], [0, 1])
        for invalid in (-1, 6, True):
            with self.assertRaises(ValueError):
                marks.assign(data, 'chin', invalid)

    def test_protection_excludes_incident_faces_and_the_opposite_side(self):
        plan = marks.reduction_faces(9, [3] * 4,
            [0, 2, 4, 1, 3, 5, 4, 6, 7, 5, 7, 8], [0], {'pairs': [[0, 1], [2, 3], [4, 5]]})
        self.assertEqual(plan['protected_vertices'], [0, 1])
        self.assertEqual(plan['excluded_faces'], [0, 1])
        self.assertEqual(plan['reduce_faces'], [2, 3])

    def test_padding_uses_topology_and_can_protect_all_faces(self):
        plan = marks.reduction_faces(9, [3] * 4,
            [0, 2, 4, 1, 3, 5, 4, 6, 7, 5, 7, 8], [0], {'pairs': [[0, 1], [2, 3], [4, 5]]}, rings=1)
        self.assertEqual(plan['protected_vertices'], [0, 1, 2, 3, 4, 5])
        self.assertEqual(plan['reduce_faces'], [])

    def test_face_masks_reject_out_of_range_source_ids(self):
        with self.assertRaises(ValueError):
            marks.reduction_faces(3, [3], [0, 1, 4])
        with self.assertRaises(ValueError):
            marks.reduction_faces(3, [3], [0, 1, 2], [3])

    def test_component_ranges_never_include_protected_gaps(self):
        self.assertEqual(marks.component_ranges('headShape', 'f', [0, 1, 4, 6, 7, 8]),
                         ['headShape.f[0:1]', 'headShape.f[4]', 'headShape.f[6:8]'])
        self.assertEqual(marks.component_ranges('headShape', 'f', []), [])

    def test_native_vertex_map_disambiguates_coincident_lip_points(self):
        source = [[0., 0., 0.], [0., 0., 0.], [1., 1., 1.]]
        ids = marks.decode_source_map([[0., 1., 0.], [0., 0., 0.]], source, [source[1], source[0]])
        self.assertEqual(ids, [1, 0])
        data = marks.assign(marks.assign(landmark_fixture(), 'upper_lip', 0), 'lower_lip', 1)
        mapped = marks.map_items(data, ids)
        self.assertEqual([p['cage_vertex'] for p in mapped['items']], [1, 0])

    def test_mapping_fails_if_a_protected_landmark_is_missing(self):
        data = marks.assign(landmark_fixture(), 'chin', 5)
        with self.assertRaisesRegex(ValueError, 'removed protected landmark'):
            marks.map_items(data, [0, 1, 2])

    def test_vertex_map_rejects_incomplete_unset_repeated_or_moved_points(self):
        source = [[0., 0., 0.], [1., 0., 0.]]
        for colors, actual in (([], source), ([[-1., -1.]], [source[0]]),
                               ([[0., 0.], [0., 0.]], [source[0], source[0]]),
                               ([[0., 1.]], [source[0]])):
            with self.assertRaises(ValueError):
                marks.decode_source_map(colors, source, actual)

    def test_reduced_symmetry_uses_source_ids_and_reports_missing_partners(self):
        pairing = {'pairs': [[0, 1], [2, 3]], 'seam': [4], 'tolerance_cm': .001}
        result = marks.remap_symmetry(pairing, [1, 4, 0, 2])
        self.assertEqual(result['pairs'], [[2, 0]])
        self.assertEqual(result['seam'], [1])
        self.assertEqual(result['unpaired'], [3])

    def test_saved_cage_rejects_a_landmark_pointing_to_the_wrong_vertex(self):
        data = cage_fixture()
        landmark_data = marks.assign(landmark_fixture(), 'chin', 0)
        data['source_snapshot'] = copy.deepcopy(landmark_data['source_snapshot'])
        data['cage_source_vertex_ids'] = [0, 1, 2, 3, 4]
        data['landmarks'] = marks.map_items(landmark_data, data['cage_source_vertex_ids'])
        cage_core.validate(data)
        data['landmarks']['items'][0]['cage_vertex'] = 1
        with self.assertRaises(ValueError):
            cage_core.validate(data)


if __name__ == '__main__':
    unittest.main()
