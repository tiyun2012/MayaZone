"""Launcher tests with registered command/path/version results, without Maya."""
from pathlib import Path
import tempfile
import unittest
import layer_skin_launch as launch


class MayaCommands:
    def __init__(self):
        self.plugins={'unrelated':dict(command=['otherCommand'],path='/other/plugin.py',version='1.0')}
        self.loads=[];self.ui_calls=[];self.register=True
    def pluginInfo(self,name=None,**kw):
        if kw.get('listPlugins'):return list(self.plugins)
        return self.plugins[name][next(key for key in kw if key!='query')]
    def loadPlugin(self,path,**kw):
        self.loads.append(path)
        if self.register:self.plugins['layer_skin_test.py']=dict(command=['rtkLayerSkin'],path=path,version=launch.disk_version(path))
        return ['layer_skin_test.py']
    def rtkLayerSkin(self,**kw):self.ui_calls.append(kw);return 'window'


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.path=self.folder/'layer_skin_test.py';self.path.write_text('VERSION = "9.10.0"\n')
        for name in ('layer_skin_core','layer_skin_assignment','layer_skin_session','layer_skin_joint_view','layer_skin_workflow_ui','layer_skin_ui','layer_skin_artisan'):
            (self.folder/(name+'.py')).write_text('')
        self.cmds=MayaCommands()
    def tearDown(self):self.temp.cleanup()
    def registered(self,version='9.10.0',path=None,name='layer_skin_test.py'):
        self.cmds.plugins[name]=dict(command=['rtkLayerSkin'],version=version,path=str(path or self.path))
    def test_fresh_load_uses_exact_path_and_version_from_source_without_a_fixed_release_check(self):
        self.assertEqual(launch.open_ui(str(self.folder),self.cmds),'window')
        self.assertEqual(self.cmds.loads,[str(self.path)]);self.assertEqual(self.cmds.ui_calls,[dict(action='ui')])
    def test_matching_registered_command_reopens_without_a_load_or_unload(self):
        self.registered(name='customRegisteredName')
        launch.open_ui(str(self.folder),self.cmds)
        self.assertEqual(self.cmds.loads,[]);self.assertEqual(len(self.cmds.ui_calls),1)
    def test_mismatch_reports_both_versions_instead_of_calling_every_mismatch_older(self):
        for version in ('0.3.2','9.11.0'):
            with self.subTest(version=version):
                self.registered(version)
                with self.assertRaises(RuntimeError) as caught:launch.open_ui(str(self.folder),self.cmds)
                message=str(caught.exception)
                self.assertIn('registered version '+version,message);self.assertIn('requested version 9.10.0',message)
                self.assertIn(str(self.path),message);self.assertNotIn('older plug-in',message.lower())
        self.assertEqual(self.cmds.loads,[]);self.assertEqual(self.cmds.ui_calls,[])
    def test_same_version_at_another_path_does_not_open_the_wrong_command(self):
        other=self.folder/'duplicate'/'layer_skin_test.py';self.registered(path=other)
        with self.assertRaises(RuntimeError) as caught:launch.open_ui(str(self.folder),self.cmds)
        self.assertIn(str(other),str(caught.exception));self.assertIn(str(self.path),str(caught.exception))
        self.assertEqual(self.cmds.ui_calls,[])
    def test_path_normalization_accepts_the_same_file(self):
        self.registered(path=self.folder/'unused'/'..'/'layer_skin_test.py')
        launch.open_ui(str(self.folder),self.cmds);self.assertEqual(len(self.cmds.ui_calls),1)
    def test_incomplete_package_is_rejected_before_loading(self):
        (self.folder/'layer_skin_session.py').unlink()
        with self.assertRaisesRegex(RuntimeError,'layer_skin_session.py'):launch.open_ui(str(self.folder),self.cmds)
        self.assertEqual(self.cmds.loads,[])
    def test_failed_registration_never_attempts_to_call_the_ui(self):
        self.cmds.register=False
        with self.assertRaisesRegex(RuntimeError,'did not register'):launch.open_ui(str(self.folder),self.cmds)
        self.assertEqual(self.cmds.ui_calls,[])


if __name__=='__main__':unittest.main(verbosity=2)
