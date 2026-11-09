import copy
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_cage_core import cage_fixture, IDENTITY
import facial_system


class CageNativeCallTests(unittest.TestCase):
    def setUp(self):
        self.data = cage_fixture()
        self.data['source_snapshot'] = {'default_positions_cm': [[0., 0., 0.], [1., 1., 1.]], 'vertex_count': 2}
        self.top = 'PreviousArtistAction'
        self.current_chunk = None
        self.enabled = True
        self.undo_count = 0
        self.writes = []
        self.enum_queries = []
        self.saved = []
        self.rest_shift = False
        cmds = types.ModuleType('maya.cmds')
        def undo_info(**kwargs):
            if kwargs.get('query') and kwargs.get('state'): return self.enabled
            if kwargs.get('query') and kwargs.get('undoName'): return self.top
            if kwargs.get('openChunk'): self.current_chunk = kwargs['chunkName']
        def undo(): self.undo_count += 1
        def set_attr(*args, **kwargs):
            self.writes.append(args)
            self.top = self.current_chunk
        def query(attribute, **kwargs):
            self.enum_queries.append(attribute)
            return ['Global:Offset:Surface'] if attribute == 'driverWrapMode' else ['Offset:Surface:Snap']
        cmds.undoInfo, cmds.undo = undo_info, undo
        cmds.setAttr, cmds.attributeQuery = set_attr, query
        cmds.deformer = lambda *args, **kwargs: ['wrapNode']
        self.driver_calls = []
        def proximity(*args, **kwargs):
            self.driver_calls.append((args, kwargs))
            return [0] if kwargs.get('query') else None
        cmds.proximityWrap = proximity
        om = types.ModuleType('maya.api.OpenMaya')
        om.MSpace = types.SimpleNamespace(kWorld=0, kObject=1)
        om.MPoint = lambda *args: types.SimpleNamespace(x=args[0], y=args[1], z=args[2])
        om.MFnMesh = lambda path: types.SimpleNamespace(getClosestPoint=lambda p, space: (p, 0))
        modules = {'maya': types.ModuleType('maya'), 'maya.cmds': cmds,
                   'maya.api': types.ModuleType('maya.api'), 'maya.api.OpenMaya': om,
                   'maya.api.OpenMayaAnim': types.ModuleType('maya.api.OpenMayaAnim')}
        self.modules = mock.patch.dict(sys.modules, modules)
        self.modules.start()
        sys.modules.pop('facial_system.cage', None)
        if hasattr(facial_system, 'cage'):
            del facial_system.cage
        self.backend = importlib.import_module('facial_system.cage')
        PathObject = lambda name: types.SimpleNamespace(fullPathName=lambda: name)
        cage_path, preview_path = PathObject('cage'), PathObject('preview')
        def points(path, space=None):
            if path.fullPathName() == 'cage': return copy.deepcopy(self.data['rest_cage_points_cm'])
            result = copy.deepcopy(self.data['source_snapshot']['default_positions_cm'])
            if self.rest_shift and sum(bool(call[1].get('query')) for call in self.driver_calls):
                result[0][0] += .1
            return result
        self.patches = [
            mock.patch.object(self.backend, '_check', return_value=(cage_path, preview_path)),
            mock.patch.object(self.backend, '_matrix', return_value=list(IDENTITY)),
            mock.patch.object(self.backend, 'resolve', side_effect=lambda info: info['path']),
            mock.patch.object(self.backend, 'node_info', side_effect=lambda name: {'uuid': name, 'path': name}),
            mock.patch.object(self.backend, '_save', side_effect=lambda data: self.saved.append(copy.deepcopy(data))),
            mock.patch.object(self.backend.adapter, 'mesh_path', side_effect=PathObject),
            mock.patch.object(self.backend.fit, 'points', side_effect=points)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        sys.modules.pop('facial_system.cage', None)
        if hasattr(facial_system, 'cage'):
            del facial_system.cage
        self.modules.stop()

    def test_bind_uses_one_native_driver_offset_mode_and_finite_coverage(self):
        result = self.backend.bind(self.data)
        self.assertEqual(result['deformer']['path'], 'wrapNode')
        self.assertIn(('wrapNode.wrapMode', 0), self.writes)
        self.assertEqual(len([call for call in self.driver_calls if call[1].get('edit')]), 1)
        self.assertGreater(result['falloff_end_cm'], 0.)
        self.assertEqual(result['bind_rest_error_cm'], 0.)
        self.assertEqual(self.undo_count, 0)
        self.assertNotIn('deformer', {key for key, value in self.data.items() if value})

    def test_copy_uses_fresh_transform_without_unlocking_the_source(self):
        paths = {
            'lockedHead': '|head_grp|lockedHead|headShape',
            'FS_CopyTmp': '|head_grp|FS_CopyTmp|copiedShape',
            'FS_CagePreview': '|FS_CageWork|FS_CagePreview|copiedShape',
            '|FS_CageWork|FS_CagePreview': '|FS_CageWork|FS_CagePreview|copiedShape'}
        mesh_path = lambda name: types.SimpleNamespace(fullPathName=lambda: paths[name])
        cmds = self.backend.cmds
        cmds.listRelatives = mock.Mock(side_effect=lambda node, **kwargs:
            ['|head_grp|FS_CopyTmp|copiedShape'] if kwargs.get('shapes') else ['headShape'])
        cmds.nodeType = mock.Mock(return_value='mesh')
        cmds.duplicate = mock.Mock(return_value=['FS_CopyTmp'])
        cmds.delete = mock.Mock()
        cmds.getAttr = mock.Mock(return_value=False)
        cmds.createNode = mock.Mock(return_value='FS_CagePreview')
        cmds.parent = mock.Mock()
        snapshot = self.data['source_snapshot']
        with mock.patch.object(self.backend.adapter, 'mesh_path', side_effect=mesh_path), \
             mock.patch.object(self.backend.adapter, 'mesh_snapshot', return_value=(snapshot, None)), \
             mock.patch.object(self.backend.adapter, 'assert_topology'), \
             mock.patch.object(self.backend.adapter, 'skin_history', return_value=[]), \
             mock.patch.object(self.backend.fit, 'points', return_value=copy.deepcopy(snapshot['default_positions_cm'])), \
             mock.patch.object(self.backend, '_set_matrix') as set_matrix:
            result = self.backend._copy_mesh('lockedHead', 'FS_CagePreview', 'FS_CageWork')
        self.assertEqual(result, '|FS_CageWork|FS_CagePreview')
        cmds.createNode.assert_called_once_with('transform', name='FS_CagePreview', parent='FS_CageWork')
        cmds.parent.assert_called_once_with('|head_grp|FS_CopyTmp|copiedShape', 'FS_CagePreview', shape=True, relative=True)
        set_matrix.assert_called_once_with('FS_CagePreview', list(IDENTITY))
        self.assertEqual(cmds.delete.call_args_list, [mock.call('FS_CopyTmp', constructionHistory=True), mock.call('FS_CopyTmp')])
        self.assertEqual(self.writes, [])

    def test_compound_enum_queries_use_the_attribute_name_without_array_index(self):
        self.backend.bind(self.data)
        self.assertIn('driverWrapMode', self.enum_queries)
        self.assertFalse(any('[' in attribute for attribute in self.enum_queries))

    def test_layer_weight_is_honored_when_binding(self):
        self.data['weight'] = .4
        self.backend.bind(self.data)
        self.assertIn(('wrapNode.envelope', .4), self.writes)

    def test_rest_movement_failure_rolls_back_the_created_graph(self):
        self.rest_shift = True
        with self.assertRaisesRegex(ValueError, 'changed the rest mesh'):
            self.backend.bind(self.data)
        self.assertEqual(self.undo_count, 1)
        self.assertEqual(self.saved, [])

    def test_cancelled_bind_rolls_back_and_keeps_original_capture(self):
        original = copy.deepcopy(self.data)
        with self.assertRaises(Exception):
            self.backend.bind(self.data, progress=lambda *args: False)
        self.assertEqual(self.undo_count, 1)
        self.assertEqual(self.data, original)

    def test_disabled_undo_rejects_edit_before_any_native_write(self):
        self.enabled = False
        with self.assertRaises(ValueError):
            self.backend.bind(self.data)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.undo_count, 0)

    def test_settings_failure_before_a_write_does_not_undo_artist_action(self):
        with self.assertRaises(RuntimeError):
            with self.backend.transaction('new_action'):
                raise RuntimeError('failed before editing')
        self.assertEqual(self.undo_count, 0)

    def _response_simulation(self, fail=False):
        controls = copy.deepcopy(self.data['rest_cage_points_cm'])
        original = copy.deepcopy(controls)
        self.data['deformer'] = {'uuid': 'wrapNode', 'path': 'wrapNode'}
        def xform(component, **kwargs):
            index = int(component.rsplit('[', 1)[1][:-1])
            controls[index] = list(kwargs['translation'])
            self.top = self.current_chunk
        self.backend.cmds.xform = xform
        def points(path, space=None):
            if path.fullPathName() == 'cage':
                return copy.deepcopy(controls)
            delta = sum(a[1] - b[1] for a, b in zip(controls, original))
            if fail and abs(delta) > 1e-9:
                raise RuntimeError('simulated native evaluation failure')
            return [[0., .5 * delta, 0.], [1., 1., 1.]]
        return controls, original, points

    def test_response_probe_restores_control_and_identifies_actual_output_movement(self):
        controls, original, points = self._response_simulation()
        with mock.patch.object(self.backend.fit, 'points', side_effect=points), \
             mock.patch.object(self.backend.fit, 'ui_distance', side_effect=lambda x: x):
            report = self.backend.test_response(self.data)
        self.assertTrue(report['passed'])
        self.assertAlmostEqual(report['maximum_output_move_cm'], .1)
        self.assertEqual(report['maximum_restore_error_cm'], 0.)
        self.assertEqual(controls, original)
        self.assertEqual(self.undo_count, 1)

    def test_failed_probe_restores_artist_cage_edit_state(self):
        controls, original, points = self._response_simulation(fail=True)
        with mock.patch.object(self.backend.fit, 'points', side_effect=points), \
             mock.patch.object(self.backend.fit, 'ui_distance', side_effect=lambda x: x):
            with self.assertRaisesRegex(RuntimeError, 'simulated native evaluation failure'):
                self.backend.test_response(self.data)
        self.assertEqual(controls, original)
        self.assertEqual(self.undo_count, 1)

    def _reduction_simulation(self, retained):
        from test_cage_landmarks import landmark_fixture
        from facial_system import cage_landmarks
        marks = cage_landmarks.assign(landmark_fixture(), 'nose_tip', 0)
        source = marks['source_snapshot']['default_positions_cm']
        fn = types.SimpleNamespace(getVertices=lambda: ([3, 3], [0, 1, 2, 3, 4, 5]),
            getVertexColors=lambda name: [types.SimpleNamespace(r=0., g=float(i), b=0.) for i in retained])
        self.backend.cmds.polyColorSet = mock.Mock(return_value=[])
        self.backend.cmds.polyReduce = mock.Mock()
        return marks, source, fn

    def test_reduction_targets_only_unprotected_faces_and_keeps_native_source_ids(self):
        marks, source, fn = self._reduction_simulation([0, 1, 2, 3, 4])
        with mock.patch.object(self.backend, '_copy_mesh', return_value='cage'), \
             mock.patch.object(self.backend.om, 'MFnMesh', return_value=fn), \
             mock.patch.object(self.backend.fit, 'points', return_value=source[:5]), \
             mock.patch.object(self.backend.fit, 'ui_distance', side_effect=lambda value: value):
            result = self.backend._reduced_copy('source', 'root', source, [.5, .5, .5], marks, 4, 0, None)
        args, kwargs = self.backend.cmds.polyReduce.call_args
        self.assertEqual(args, (['cage.f[1]'],))
        self.assertEqual(kwargs['version'], 1)
        self.assertEqual(kwargs['keepBorderWeight'], 1.)
        self.assertEqual(kwargs['useVirtualSymmetry'], 2)
        self.assertLess(kwargs['keepQuadsWeight'], 1.)
        self.assertEqual(result[1], [0, 1, 2, 3, 4])
        self.assertEqual(result[2]['items'][0]['cage_vertex'], 0)
        self.assertEqual(result[4]['protected_vertices'], 2)
        self.assertFalse(self.backend.cmds.polyReduce.call_args.kwargs['constructionHistory'])

    def test_reduction_rejects_loss_of_a_protected_vertex(self):
        marks, source, fn = self._reduction_simulation([1, 2, 3, 4, 5])
        with mock.patch.object(self.backend, '_copy_mesh', return_value='cage'), \
             mock.patch.object(self.backend.om, 'MFnMesh', return_value=fn), \
             mock.patch.object(self.backend.fit, 'points', return_value=source[1:]), \
             mock.patch.object(self.backend.fit, 'ui_distance', side_effect=lambda value: value):
            with self.assertRaisesRegex(ValueError, 'removed protected vertices'):
                self.backend._reduced_copy('source', 'root', source, [.5, .5, .5], marks, 4, 0, None)

    def test_reduction_cancel_after_native_edit_rolls_back_its_own_chunk(self):
        marks, source, fn = self._reduction_simulation([0, 1, 2, 3, 4])
        def reduce(*args, **kwargs):
            self.top = self.current_chunk
        self.backend.cmds.polyReduce.side_effect = reduce
        with mock.patch.object(self.backend, '_copy_mesh', return_value='cage'), \
             mock.patch.object(self.backend.om, 'MFnMesh', return_value=fn), \
             mock.patch.object(self.backend.fit, 'points', return_value=source[:5]), \
             mock.patch.object(self.backend.fit, 'ui_distance', side_effect=lambda value: value):
            with self.assertRaises(self.backend.adapter.Cancelled):
                with self.backend.transaction('CreateReducedCage'):
                    self.backend._reduced_copy('source', 'root', source, [.5, .5, .5], marks, 4, 0,
                                              lambda value, *args: value == 0)
        self.assertEqual(self.undo_count, 1)

    def test_rig_suggestions_never_replace_manual_landmarks(self):
        from test_cage_landmarks import landmark_fixture
        from facial_system import cage_landmarks
        marks = cage_landmarks.assign(landmark_fixture(), 'upper_lip', 2)
        with mock.patch.object(self.backend, 'landmark_draft', return_value=marks), \
             mock.patch.object(self.backend.adapter, 'discover_joints', return_value=(['FACIAL_C_LipUpper', 'FACIAL_C_NoseTip'], 'test')):
            result = self.backend.suggest_landmarks('source', marks)
        assigned = {item['key']: item for item in result['items']}
        self.assertEqual(assigned['upper_lip']['source_vertex'], 2)
        self.assertEqual(assigned['upper_lip']['method'], 'manual')
        self.assertEqual(assigned['nose_tip']['method'], 'rig_suggestion_review')
        self.assertEqual(len(marks['items']), 1)

    def test_landmark_capture_rejects_a_replaced_or_edited_source_before_writes(self):
        from test_cage_landmarks import landmark_fixture
        marks = landmark_fixture()
        with mock.patch.object(self.backend.adapter, 'identity', return_value={'uuid': 'replacement'}):
            with self.assertRaisesRegex(ValueError, 'another source mesh'):
                self.backend.landmark_draft('source', marks)
        actual = copy.deepcopy(marks['source_snapshot']['default_positions_cm'])
        actual[0][0] += .1
        with mock.patch.object(self.backend.adapter, 'identity', return_value={'uuid': 'mesh'}), \
             mock.patch.object(self.backend.adapter, 'assert_topology'), \
             mock.patch.object(self.backend.fit, 'points', return_value=actual):
            with self.assertRaisesRegex(ValueError, 'positions changed'):
                self.backend.landmark_draft('source', marks)
        self.assertEqual(self.writes, [])

    def test_full_protection_reports_actual_count_without_reducing_any_source_faces(self):
        from facial_system import cage_landmarks
        marks, source, fn = self._reduction_simulation(list(range(6)))
        marks = cage_landmarks.assign(marks, 'chin', 3)
        with mock.patch.object(self.backend, '_copy_mesh', return_value='cage'), \
             mock.patch.object(self.backend.om, 'MFnMesh', return_value=fn):
            result = self.backend._reduced_copy('source', 'root', source, [.5, .5, .5], marks, 4, 0, None)
        self.backend.cmds.polyReduce.assert_not_called()
        self.assertFalse(result[4]['reduction_ran'])
        self.assertEqual(result[4]['actual_vertices'], 6)

    def test_landmark_match_updates_its_saved_partner_in_one_native_transaction(self):
        self.data['deformer'] = {'uuid': 'wrap', 'path': 'wrap'}
        self.data['landmarks'] = {'items': [{'key': 'mouth_corner_L', 'label': 'Mouth corner L', 'cage_vertex': 0}]}
        class Point:
            def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z
            def __mul__(self, matrix): return self
        class Matrix:
            def __init__(self, values): pass
            def inverse(self): return self
        updates = {}
        def xform(name, **kwargs):
            updates[name] = kwargs['translation']
            self.top = self.current_chunk
        self.backend.cmds.xform = xform
        with mock.patch.object(self.backend.om, 'MPoint', Point), \
             mock.patch.object(self.backend.om, 'MMatrix', Matrix, create=True), \
             mock.patch.object(self.backend.fit, 'ui_distance', side_effect=lambda x: x):
            result = self.backend.move_landmark(self.data, 'mouth_corner_L', [3., 4., 5.])
            self.data['symmetry']['unpaired'] = [0]
            with self.assertRaisesRegex(ValueError, 'no captured mirror partner'):
                self.backend.move_landmark(self.data, 'mouth_corner_L', [3., 4., 5.])
        self.assertEqual(updates, {'cage.vtx[0]': [3., 4., 5.], 'cage.vtx[1]': [-3., 4., 5.]})
        self.assertEqual(result['updated_cage_vertices'], [0, 1])
        self.assertEqual(self.undo_count, 0)
        self.assertEqual(self.current_chunk, 'FacialSystem_MoveCageLandmark')


if __name__ == '__main__':
    unittest.main()
