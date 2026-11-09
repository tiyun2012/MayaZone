import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from facial_system import core


def fixture():
    points = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
              [0, 0, .001], [1, 0, .001], [1, 1, .001], [0, 1, .001]]
    counts, ids = [4, 4], list(range(8))
    mesh = {'id': 'mesh', 'identity': {'uuid': 'mesh', 'path': '|head|headShape', 'name': 'headShape'},
            'vertex_count': 8, 'polygon_count': 2,
            'topology_sha256': core.topology_hash(8, counts, ids),
            'default_positions_cm': points}
    document = core.new_document()
    document['meshes']['mesh'] = mesh
    row = {'joint': {'uuid': 'joint', 'path': '|rig|joint', 'name': 'joint'}, 'parent': None,
           'group_name': 'joint_neutralVerts', 'default_world_position_cm': [.5, .5, -2],
           'default_local_translation_cm': [.5, .5, -2]}
    core.set_group(document, row, {'mesh': [0, 1, 2, 3]}, 'manual')
    document['joints'].append(row)
    return document, core.adjacency(8, counts, ids)


class NeutralDataTests(unittest.TestCase):
    def test_translation_preserves_interior_offset_without_accumulation(self):
        document, _ = fixture()
        row = document['joints'][0]
        current = {'mesh': [[p[0] + 3, p[1] - 5, p[2] + 7]
                            for p in document['meshes']['mesh']['default_positions_cm']]}
        expected = [3.5, -4.5, 5]
        for _ in range(100):
            self.assertEqual(core.predicted_position(row, current), expected)
        self.assertEqual(row['default_world_position_cm'], [.5, .5, -2])

    def test_manual_replacement_uses_captured_default_positions(self):
        document, _ = fixture()
        row = document['joints'][0]
        core.set_group(document, row, {'mesh': [1, 1, 2]}, 'manual')
        self.assertEqual(row['vertex_count'], 2)
        self.assertEqual(row['default_group_center_cm'], [1, .5, 0])
        self.assertEqual(row['offset_from_group_cm'], [-.5, 0, -2])
        core.validate(document)

    def test_skin_patch_does_not_join_nearby_disconnected_lip_surfaces(self):
        document, neighbors = fixture()
        points = document['meshes']['mesh']['default_positions_cm']
        ids, _ = core.skin_patch(points, [0, 0, -1], list(range(8)), [1, .9, .8, .7, .99, .98, .97, .96],
                                  max_vertices=8, neighbors=neighbors)
        self.assertEqual(ids, [0, 1, 2, 3])

    def test_nearest_fallback_stays_on_one_connected_surface(self):
        document, neighbors = fixture()
        ids, _ = core.nearest_patch(document['meshes']['mesh']['default_positions_cm'],
                                     [0, 0, -.001], 6, neighbors)
        self.assertEqual(ids, [0, 1, 2, 3])

    def test_relative_weight_cutoff_keeps_weak_but_relevant_influence(self):
        points = [[i, 0, 0] for i in range(5)]
        ids, _ = core.skin_patch(points, [0, 0, 0], list(range(5)), [.0001, .00008, .00005, .00001, 0],
                                  relative_threshold=.5)
        self.assertEqual(ids, [0, 1, 2])

    def test_save_load_preserves_all_default_data_and_vertex_ids(self):
        document, _ = fixture()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'driveNeutralData.json'
            core.save(document, path)
            loaded = core.load(path)
        self.assertEqual(document, loaded)

    def test_failed_atomic_write_keeps_previous_file(self):
        document, _ = fixture()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'driveNeutralData.json'
            core.save(document, path)
            before = path.read_bytes()
            document['joints'][0]['group_name'] = 'changed'
            with mock.patch('facial_system.core.os.replace', side_effect=OSError('test failure')):
                with self.assertRaises(OSError): core.save(document, path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_corrupted_ids_centers_and_duplicate_joints_are_rejected(self):
        original, _ = fixture()
        for corrupt in ('id', 'center', 'duplicate'):
            document = copy.deepcopy(original)
            if corrupt == 'id': document['joints'][0]['vertex_groups'][0]['vertex_ids'] = [999]
            elif corrupt == 'center': document['joints'][0]['default_group_center_cm'][0] += 1
            else: document['joints'].append(copy.deepcopy(document['joints'][0]))
            with self.assertRaises(ValueError): core.validate(document)

    def test_topology_fingerprint_detects_reordered_vertices_and_connectivity(self):
        a = core.topology_hash(4, [4], [0, 1, 2, 3])
        self.assertNotEqual(a, core.topology_hash(4, [4], [0, 2, 1, 3]))
        self.assertNotEqual(a, core.topology_hash(4, [3, 3], [0, 1, 2, 0, 2, 3]))

    def test_unassigned_rows_can_be_saved_as_work_in_progress(self):
        document, _ = fixture()
        core.set_group(document, document['joints'][0], {}, 'unassigned')
        core.validate(document)
        self.assertIsNone(document['joints'][0]['default_group_center_cm'])
        self.assertTrue(document['joints'][0]['review_required'])


if __name__ == '__main__': unittest.main()
