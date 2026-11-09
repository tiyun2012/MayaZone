import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_core import fixture
import drive_neutral_core as core


class MemoryScene:
    """Independent test scene: parent rotated 90 degrees about Z, no Maya."""
    def __init__(self, fail=None):
        self.data = {'parent_world': [0., 0., 0.], 'child_local': [2., 0., 0.],
                     'mesh': [[0., 0., 0.]], 'bind_updated': False, 'pose_updated': False}
        self.fail = fail
        self.log = []
        self.saved = None
        self.rolled_back = False

    def begin(self):
        self.saved = copy.deepcopy(self.data)

    def place_joint(self, row, report):
        self.log.append(row['name'])
        if row['name'] == 'parent':
            self.data['parent_world'] = list(row['position_cm'])
        else:
            dx, dy, dz = [a - b for a, b in zip(row['position_cm'], self.data['parent_world'])]
            self.data['child_local'] = [dy, -dx, dz]

    def write_mesh(self, row, report):
        self.data['mesh'] = copy.deepcopy(row['points'])
        report('Mesh partially written')

    def update_skin(self, row, report):
        if self.fail == 'skin': raise RuntimeError('simulated bind failure')
        self.data['bind_updated'] = True

    def update_pose(self, row, report): self.data['pose_updated'] = True

    def verify(self, plan):
        p = self.data['parent_world']
        x, y, z = self.data['child_local']
        child = [p[0] - y, p[1] + x, p[2] + z]
        return {'passed': self.fail != 'verify' and child == [5., 3., 0.],
                'child_world': child}

    def commit(self): self.log.append('commit')

    def rollback(self):
        self.data = self.saved
        self.rolled_back = True


def plan():
    return {'joints': [{'name': 'parent', 'position_cm': [1., 1., 0.]},
                       {'name': 'child', 'position_cm': [5., 3., 0.]}],
            'mesh_edits': [{'name': 'head', 'points': [[2., 3., 4.]]}],
            'skins': [{'name': 'skin'}], 'poses': [{'name': 'bindPose'}]}


class FitTests(unittest.TestCase):
    def test_edited_target_produces_absolute_translation_from_saved_default(self):
        document, _ = fixture()
        target = [[x + 3, y + 4, z] for x, y, z in document['meshes']['mesh']['default_positions_cm']]
        before = copy.deepcopy(document)
        for _ in range(20):
            fitted = core.fit_positions(document, {'mesh': target})
            self.assertEqual(fitted[0]['position_cm'], [3.5, 4.5, -2.])
        self.assertEqual(document, before)

    def test_unmapped_mesh_and_unassigned_joint_keep_saved_defaults(self):
        document, _ = fixture()
        self.assertEqual(core.fit_positions(document, {})[0]['delta_cm'], [0, 0, 0])
        core.set_group(document, document['joints'][0], {}, 'unassigned')
        target = [[x + 5, y, z] for x, y, z in document['meshes']['mesh']['default_positions_cm']]
        self.assertEqual(core.fit_positions(document, {'mesh': target})[0]['delta_cm'], [0, 0, 0])

    def test_target_count_mismatch_is_rejected(self):
        document, _ = fixture()
        with self.assertRaises(ValueError): core.fit_positions(document, {'mesh': [[0, 0, 0]]})

    def test_native_matrix_cells_keep_row_vector_order(self):
        self.assertEqual([core.matrix_cell_from_extractor([0, 1, 0], col) for col in range(3)], [4, 5, 6])
        with self.assertRaises(ValueError): core.matrix_cell_from_extractor([.5, .5, 0], 1)

    def test_parent_then_child_produces_correct_local_translation_in_rotated_parent(self):
        scene = MemoryScene()
        result = core.execute_fit(plan(), scene)
        self.assertTrue(result['passed'])
        self.assertEqual(scene.data['child_local'], [2., -4., 0.])
        self.assertEqual(scene.log[:2], ['parent', 'child'])
        self.assertTrue(scene.data['bind_updated'] and scene.data['pose_updated'])

    def test_bind_failure_restores_joints_mesh_and_bind_state(self):
        scene = MemoryScene(fail='skin')
        before = copy.deepcopy(scene.data)
        with self.assertRaises(RuntimeError): core.execute_fit(plan(), scene)
        self.assertTrue(scene.rolled_back)
        self.assertEqual(scene.data, before)

    def test_failed_postcondition_restores_entire_scene(self):
        scene = MemoryScene(fail='verify')
        before = copy.deepcopy(scene.data)
        with self.assertRaises(ValueError): core.execute_fit(plan(), scene)
        self.assertEqual(scene.data, before)

    def test_cancel_during_mesh_write_restores_prior_state(self):
        scene = MemoryScene()
        before = copy.deepcopy(scene.data)
        with self.assertRaises(RuntimeError):
            core.execute_fit(plan(), scene, lambda step, total, text: text != 'Mesh partially written')
        self.assertEqual(scene.data, before)


if __name__ == '__main__': unittest.main()
