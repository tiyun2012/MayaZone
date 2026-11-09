"""Mocked Maya orchestration checks; these do not claim Maya API validation."""
import copy
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_core import fixture
import drive_neutral_core as core


class FakePath:
    def __init__(self, name): self.name = name
    def fullPathName(self): return '|head|headShape' if self.name == 'mesh' else '|rig|' + self.name
    def partialPathName(self): return self.name


class FakeSelection:
    def add(self, name): self.name = name
    def getDependNode(self, index): return self.name


class FakeAffected:
    def __init__(self, ids): self.ids = ids
    def length(self): return int(bool(self.ids))
    def getComponent(self, index):
        return FakePath('mesh'), types.SimpleNamespace(apiType=lambda: 1, ids=self.ids)


class FakeSkin:
    def __init__(self, node): pass
    def influenceObjects(self): return [FakePath(name) for name in ('weighted', 'manual', 'empty')]
    def getPointsAffectedByInfluence(self, influence):
        if influence.name == 'weighted': return FakeAffected([0, 1, 2, 3]), [1., .8, .7, .1]
        if influence.name == 'manual': return FakeAffected([4, 5, 6, 7]), [1., .9, .8, .7]
        return FakeAffected([]), []


class AdapterOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.base, self.graph = fixture()
        self.snapshot = copy.deepcopy(self.base['meshes']['mesh'])
        cmds = types.ModuleType('maya.cmds')
        cmds.file = lambda **kw: 'test.ma'
        cmds.currentUnit = lambda **kw: 'cm'
        cmds.listHistory = lambda *a, **kw: ['skin']
        cmds.ls = lambda names=None, **kw: ['skin'] if kw.get('type') == 'skinCluster' else []
        om = types.ModuleType('maya.api.OpenMaya')
        om.MSelectionList = FakeSelection
        om.MFn = types.SimpleNamespace(kMeshVertComponent=1)
        om.MFnSingleIndexedComponent = lambda comp: types.SimpleNamespace(isComplete=False, getElements=lambda: comp.ids)
        oma = types.ModuleType('maya.api.OpenMayaAnim')
        oma.MFnSkinCluster = FakeSkin
        modules = {'maya': types.ModuleType('maya'), 'maya.cmds': cmds,
                   'maya.api': types.ModuleType('maya.api'), 'maya.api.OpenMaya': om,
                   'maya.api.OpenMayaAnim': oma}
        self.module_patch = mock.patch.dict(sys.modules, modules)
        self.module_patch.start()
        sys.modules.pop('drive_neutral_maya', None)
        self.adapter = importlib.import_module('drive_neutral_maya')
        def identity(obj):
            name = obj.name if isinstance(obj, FakePath) else obj
            return {'uuid': name, 'path': '|rig|' + name, 'name': name}
        def joint_record(name):
            row = copy.deepcopy(self.base['joints'][0])
            row['joint'] = identity(name)
            core.set_group(self.base, row, {}, 'unassigned')
            return row
        self.patches = [mock.patch.object(self.adapter, 'identity', identity),
                        mock.patch.object(self.adapter, 'mesh_path', lambda name: FakePath('mesh')),
                        mock.patch.object(self.adapter, 'mesh_snapshot', lambda name: (copy.deepcopy(self.snapshot), self.graph)),
                        mock.patch.object(self.adapter, 'joint_record', joint_record),
                        mock.patch.object(self.adapter, 'discover_joints', lambda *a: (['weighted', 'manual', 'empty'], 'test'))]
        for patch in self.patches: patch.start()

    def tearDown(self):
        for patch in reversed(self.patches): patch.stop()
        self.module_patch.stop()
        sys.modules.pop('drive_neutral_maya', None)

    def test_detect_builds_skin_and_reviewable_fallback_groups(self):
        data = self.adapter.detect(['mesh'], max_vertices=3)
        rows = {row['joint']['name']: row for row in data['joints']}
        self.assertEqual(rows['weighted']['method'], 'skin_weights')
        self.assertEqual(rows['weighted']['vertex_count'], 3)
        self.assertEqual(rows['empty']['method'], 'nearest_fallback')
        self.assertTrue(rows['empty']['review_required'])

    def test_redetect_retains_manual_groups_and_original_mesh_defaults(self):
        data = self.adapter.detect(['mesh'], max_vertices=3)
        manual = next(row for row in data['joints'] if row['joint']['name'] == 'manual')
        core.set_group(data, manual, {'mesh': [0, 3]}, 'manual')
        saved_manual = copy.deepcopy(manual)
        saved_points = copy.deepcopy(data['meshes']['mesh']['default_positions_cm'])
        self.snapshot['default_positions_cm'] = [[x + 100, y, z] for x, y, z in saved_points]
        result = self.adapter.detect(['mesh'], max_vertices=1, existing=data)
        self.assertEqual(result['meshes']['mesh']['default_positions_cm'], saved_points)
        self.assertEqual(next(row for row in result['joints'] if row['joint']['name'] == 'manual'), saved_manual)

    def test_cancel_keeps_existing_document(self):
        data = self.adapter.detect(['mesh'], max_vertices=3)
        before = copy.deepcopy(data)
        with self.assertRaises(self.adapter.Cancelled):
            self.adapter.detect(['mesh'], existing=data, progress=lambda *a: False)
        self.assertEqual(data, before)

    def test_changed_connectivity_is_rejected_without_replacing_defaults(self):
        data = self.adapter.detect(['mesh'], max_vertices=3)
        self.snapshot['topology_sha256'] = 'a' * 64
        with self.assertRaises(ValueError): self.adapter.detect(['mesh'], existing=data)

    def test_empty_history_does_not_query_all_scene_skin_clusters(self):
        with mock.patch.object(self.adapter.cmds, 'listHistory', return_value=None), \
             mock.patch.object(self.adapter.cmds, 'ls', return_value=['unrelated_skin']) as ls:
            self.assertEqual(self.adapter.skin_history('clean_fit_target'), [])
            ls.assert_not_called()


if __name__ == '__main__': unittest.main()
