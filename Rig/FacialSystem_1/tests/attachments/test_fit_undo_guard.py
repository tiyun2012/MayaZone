"""Test the Maya transaction wrapper without executing Maya commands."""
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class UndoGuardTests(unittest.TestCase):
    def setUp(self):
        self.enabled = True
        self.top = 'PreviousArtistAction'
        self.undo_count = 0
        self.closed_count = 0
        cmds = types.ModuleType('maya.cmds')
        def undo_info(**kwargs):
            if kwargs.get('query') and kwargs.get('state'): return self.enabled
            if kwargs.get('query') and kwargs.get('undoName'): return self.top
            if kwargs.get('closeChunk'): self.closed_count += 1
        def undo(): self.undo_count += 1
        cmds.undoInfo = undo_info
        cmds.undo = undo
        om = types.ModuleType('maya.api.OpenMaya')
        om.MSpace = types.SimpleNamespace(kWorld=0, kObject=1)
        self.patch = mock.patch.dict(sys.modules, {'maya': types.ModuleType('maya'), 'maya.cmds': cmds,
                                                   'maya.api': types.ModuleType('maya.api'), 'maya.api.OpenMaya': om,
                                                   'maya.api.OpenMayaAnim': types.ModuleType('maya.api.OpenMayaAnim')})
        self.patch.start()
        sys.modules.pop('facial_system.scene_adapter', None)
        sys.modules.pop('facial_system.fit', None)
        self.fit = importlib.import_module('facial_system.fit')

    def tearDown(self):
        sys.modules.pop('facial_system.fit', None)
        sys.modules.pop('facial_system.scene_adapter', None)
        self.patch.stop()

    def test_fitting_chunk_is_undone_once(self):
        scene = self.fit.MayaFitScene()
        scene.begin()
        scene.changed = True
        self.top = self.fit.UNDO_CHUNK
        scene.rollback()
        self.assertEqual(self.undo_count, 1)
        self.assertEqual(self.closed_count, 1)

    def test_failed_operation_without_writes_does_not_undo_previous_action(self):
        scene = self.fit.MayaFitScene()
        scene.begin()
        scene.rollback()
        self.assertEqual(self.undo_count, 0)

    def test_changed_undo_queue_is_not_blindly_undone(self):
        scene = self.fit.MayaFitScene()
        scene.begin()
        scene.changed = True
        with self.assertRaises(RuntimeError): scene.rollback()
        self.assertEqual(self.undo_count, 0)

    def test_disabled_undo_rejects_apply_before_writes(self):
        scene = self.fit.MayaFitScene()
        self.enabled = False
        with self.assertRaises(ValueError): scene.begin()
        self.assertFalse(scene.open)


if __name__ == '__main__': unittest.main()
