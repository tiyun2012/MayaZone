"""Optional dependency plans, activation, and retry behavior; no downloads."""
import builtins
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock
import layer_skin_dependencies as deps
import layer_skin_performance as perf


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.root=deps.dependency_root(str(self.base/'Maya user folder'))
    def tearDown(self):self.temp.cleanup()
    def staged(self):
        stage=deps.make_stage(self.root);package=Path(stage)/'numpy';package.mkdir()
        (package/'__init__.py').write_text('__version__="1.26.4"\n')
        return stage
    def test_supported_python_range_and_pinned_binary_only_arguments(self):
        for version,expected in [([3,8],False),([3,9],True),([3,12],True),([3,13],False)]:
            self.assertEqual(deps.supported(dict(python=version)),expected)
        stage=str(self.base/'folder with spaces');args=deps.pip_arguments(stage)
        self.assertEqual(args[:3],['-m','pip','install']);self.assertEqual(args[-1],'numpy==1.26.4')
        self.assertEqual(args[args.index('--target')+1],stage)
        self.assertIn('--only-binary=:all:',args);self.assertIn('--no-deps',args)
        self.assertNotIn('--upgrade',args);self.assertNotIn('--user',args)
    def test_mayapy_is_located_beside_maya_in_a_path_with_spaces(self):
        folder=self.base/'Maya install'/'bin';folder.mkdir(parents=True)
        maya=folder/'maya.exe';maya.touch();mayapy=folder/'mayapy.exe';mayapy.touch()
        self.assertEqual(deps.mayapy_path({},str(maya)),str(mayapy))
        self.assertEqual(deps.mayapy_path({'MAYA_LOCATION':str(folder.parent)},'/unknown/python'),str(mayapy))
    def test_maya_application_is_never_used_as_python(self):
        maya=self.base/'maya.exe';maya.touch()
        self.assertIsNone(deps.mayapy_path({},str(maya)))
    def test_wrong_interpreter_and_missing_pip_reject_before_install(self):
        valid=dict(deps.runtime_info(),pip=True);deps.validate_runtime(valid)
        for key,value in [('python',[3,99]),('platform','wrong-platform'),('bits',16)]:
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'does not match'):
                deps.validate_runtime(dict(valid,**{key:value}))
        with self.assertRaisesRegex(ValueError,'pip is unavailable'):deps.validate_runtime(dict(valid,pip=False))
    def test_probe_parser_ignores_other_process_output(self):
        result=dict(deps.runtime_info(),pip=True)
        self.assertEqual(deps.parse_result('startup\n'+deps.ENV_MARKER+json.dumps(result)+'\n',deps.ENV_MARKER),result)
        with self.assertRaises(ValueError):deps.parse_result('No result',deps.ENV_MARKER)
    def test_activation_keeps_old_install_until_new_publication(self):
        first=deps.activate(self.root,self.staged());second_stage=self.staged()
        self.assertEqual(deps.active_path(self.root),first)
        second=deps.activate(self.root,second_stage)
        self.assertEqual(deps.active_path(self.root),second);self.assertTrue(Path(first).is_dir())
        self.assertFalse(Path(second_stage).exists())
    def test_failed_manifest_write_retains_prior_activation_and_removes_new_folder(self):
        first=deps.activate(self.root,self.staged());stage=self.staged();replace=os.replace
        def fail(source,target):
            if str(target).endswith('active.json'):raise OSError('Cannot publish')
            return replace(source,target)
        with mock.patch.object(deps.os,'replace',side_effect=fail),self.assertRaisesRegex(OSError,'Cannot publish'):
            deps.activate(self.root,stage)
        self.assertEqual(deps.active_path(self.root),first)
        self.assertEqual(sorted(p.name for p in Path(self.root).iterdir()),sorted(['active.json',Path(first).name]))
    def test_invalid_or_incomplete_manifest_cannot_add_arbitrary_search_paths(self):
        Path(self.root).mkdir(parents=True)
        for data in [dict(version='1.26.4',directory='../outside'),dict(version='2.0.0',directory='numpy-1.26.4-'+'a'*32),
                     dict(version='1.26.4',directory='numpy-1.26.4-'+'a'*32),[],{'directory':None}]:
            (Path(self.root)/'active.json').write_text(json.dumps(data))
            self.assertIsNone(deps.active_path(self.root))
    def test_cancellation_removes_only_owned_staging_directory(self):
        stage=self.staged();outside=self.base/'.numpy-install-outside';outside.mkdir()
        with self.assertRaises(ValueError):deps.remove_stage(self.root,str(outside))
        self.assertTrue(outside.is_dir());deps.remove_stage(self.root,stage)
        self.assertFalse(Path(stage).exists());self.assertIsNone(deps.active_path(self.root))
    def test_verification_requires_exact_version_and_new_package_path(self):
        stage=self.staged();result=dict(version='1.26.4',file=str(Path(stage)/'numpy/__init__.py'))
        deps.verify_numpy(result,stage)
        for bad in [dict(result,version='2.3.5'),dict(result,file='/elsewhere/numpy/__init__.py')]:
            with self.assertRaises(ValueError):deps.verify_numpy(bad,stage)


class BackendRetryTests(unittest.TestCase):
    def setUp(self):
        self.patch=mock.patch.multiple(perf,_NUMPY=None,_NUMPY_TRIED=False,_NUMPY_ERROR='',_NUMPY_ROOT=None)
        self.patch.start();self.addCleanup(self.patch.stop)
    def imports(self,handler):
        original=builtins.__import__
        def load(name,*args,**kwargs):
            return handler() if name=='numpy' else original(name,*args,**kwargs)
        return mock.patch.object(builtins,'__import__',side_effect=load)
    def test_failed_import_is_cached_until_explicit_recheck_then_retried(self):
        result=types.SimpleNamespace(__version__='1.26.4');attempts=[]
        def load():
            attempts.append(1)
            if len(attempts)==1:raise ImportError('Not installed')
            return result
        with self.imports(load):
            self.assertIsNone(perf.numpy_backend());self.assertIsNone(perf.numpy_backend())
            self.assertEqual(len(attempts),1);self.assertIs(perf.numpy_backend(refresh=True),result)
            self.assertIs(perf.numpy_backend(refresh=True),result);self.assertEqual(len(attempts),2)
        self.assertEqual(perf._NUMPY_ERROR,'')
    def test_binary_import_error_preserves_python_comparison(self):
        def load():raise OSError('NumPy DLL unavailable')
        with self.imports(load):
            self.assertIsNone(perf.numpy_backend());self.assertIn('DLL',perf._NUMPY_ERROR)
            a=[.5]*20000;b=a[:];b[-1]+=.000001
            self.assertTrue(perf.same(a,b,2e-6));self.assertFalse(perf.same(a,b,1e-7))
    def test_managed_package_path_is_appended_without_reordering_existing_paths(self):
        before=list(sys.path);helpers=types.SimpleNamespace(active_path=lambda root:'/managed/numpy')
        perf.configure_numpy_root('/managed');result=types.SimpleNamespace(__version__='1.26.4')
        with mock.patch.object(sys,'path',before[:]),mock.patch.object(perf,'dependency_helpers',return_value=helpers),self.imports(lambda:result):
            self.assertIs(perf.numpy_backend(),result);self.assertEqual(sys.path,before+['/managed/numpy'])
            perf.numpy_backend(refresh=True);self.assertEqual(sys.path,before+['/managed/numpy'])
    def test_configuration_invalidates_only_a_failed_backend_attempt(self):
        perf._NUMPY_TRIED=True;perf.configure_numpy_root('/new/root')
        self.assertFalse(perf._NUMPY_TRIED)
        result=types.SimpleNamespace(__version__='existing');perf._NUMPY=result;perf._NUMPY_TRIED=True
        perf.configure_numpy_root('/another/root')
        self.assertIs(perf.numpy_backend(refresh=True),result)
    def test_native_helper_install_configures_persistent_maya_user_package_root(self):
        import test_layer_skin_command as commands
        case=commands.CommandTests();case.setUp();owner=case.ns
        with tempfile.TemporaryDirectory() as user:
            owner['cmds'].internalVar=mock.Mock(return_value=user)
            self.assertTrue(perf.install(owner))
            self.assertEqual(perf._NUMPY_ROOT,perf.dependency_helpers().dependency_root(user))
            owner['cmds'].internalVar.assert_called_once_with(userAppDir=True)


if __name__=='__main__':unittest.main()
