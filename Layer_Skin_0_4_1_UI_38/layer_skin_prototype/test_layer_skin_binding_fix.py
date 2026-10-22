"""Live repair checks with a real Qt window and recording scene APIs."""
import json
import sys
import types
import unittest
from unittest import mock

import layer_skin_binding_fix as fix
import layer_skin_session as sessions
from test_layer_skin_session import FakeAPI, FakePaintBuffer


class RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6 import QtWidgets
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        from layer_skin_ui import LayerUI
        self.api=FakeAPI();self.window=LayerUI(self.api)
        self.window.target.setText('mesh');self.window.show();self.app.processEvents()
        self.window.choose_joint('|b');self.window.paint()
        self.session=self.window.session
    def tearDown(self):
        self.window.close()
        sys.modules.pop('_rtk_layer_skin_paint_040',None)
        sys.modules.pop('_rtk_layer_skin_artisan_040',None)
        sys.modules.pop(sessions.BRIDGE,None)
    def old_installation(self):
        self.api.VERSION='0.4.0'
        helper=types.ModuleType('_rtk_layer_skin_artisan_040')
        helper.get_buffer=lambda api:self.api.paint_buffer
        self.api.make_paint_buffer=lambda *args:helper.get_buffer(self.api)
        sys.modules[helper.__name__]=helper
        sys.modules['_rtk_layer_skin_paint_040']=sys.modules[sessions.BRIDGE]
        return helper
    def test_current_version_refreshes_binding_without_authoring_edits(self):
        before=json.dumps(self.api.state,sort_keys=True)
        result=fix.apply(self.window)
        self.assertTrue(result['active']);self.assertEqual(result['geometry_sources'],['meshShape.outMesh'])
        self.assertEqual(json.dumps(self.api.state,sort_keys=True),before);self.assertEqual(self.api.calls,[])
        self.assertEqual(self.api._chunk_depth,0)
    def test_old_backend_uses_new_mesh_factory_without_reloading_command(self):
        helper=self.old_installation();buffer=FakePaintBuffer()
        runtime=types.SimpleNamespace(BINDING_REVISION='mesh_geometry_1',get_buffer=mock.Mock(return_value=buffer))
        before=self.api.snapshot()
        with mock.patch.object(fix,'_runtime',return_value=runtime):result=fix.apply(self.window)
        self.assertIs(self.session.buffer,buffer)
        runtime.get_buffer.assert_called_once_with(self.api,'meshShape')
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(result['registered_backend'],'0.4.0')
        self.assertEqual(helper._geometry_binding_patch.revision,'mesh_geometry_1')
        self.session.start('mesh',self.api.layer,joint='a',mode='weights')
        self.assertEqual(runtime.get_buffer.call_count,2)
    def test_repeated_repair_reuses_runtime_buffer(self):
        self.old_installation();buffer=FakePaintBuffer()
        runtime=types.SimpleNamespace(BINDING_REVISION='mesh_geometry_1',get_buffer=lambda api,mesh:buffer)
        with mock.patch.object(fix,'_runtime',return_value=runtime):
            fix.apply(self.window);fix.apply(self.window)
        self.assertIs(self.session.buffer,buffer);self.assertEqual(self.api.calls,[])
    def test_failed_activation_restores_old_factory(self):
        helper=self.old_installation();original=helper.get_buffer
        runtime=types.SimpleNamespace(BINDING_REVISION='mesh_geometry_1',get_buffer=lambda api,mesh:FakePaintBuffer())
        with mock.patch.object(fix,'_runtime',return_value=runtime),mock.patch.object(self.session,'start',side_effect=RuntimeError('activation failed')):
            with self.assertRaisesRegex(RuntimeError,'activation failed'):fix.apply(self.window)
        self.assertIs(helper.get_buffer,original);self.assertFalse(hasattr(helper,'_geometry_binding_patch'))
        self.assertEqual(self.api.calls,[]);self.assertEqual(self.api._chunk_depth,0)
    def test_valid_pending_stroke_saved_before_repair(self):
        self.session.before_stroke();self.api.paint_buffer.write([.7,0.,0.])
        fix.apply(self.window)
        self.assertEqual(self.session.values,[.7,0.,0.]);self.assertEqual(len(self.api.calls),1)
        self.assertEqual(self.api._chunk_depth,0)
    def test_unrelated_version_is_rejected_before_any_scene_action(self):
        self.api.VERSION='0.3.9';before=self.api.snapshot()
        with self.assertRaisesRegex(RuntimeError,'supports'):fix.apply(self.window)
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[])


if __name__=='__main__':unittest.main()
