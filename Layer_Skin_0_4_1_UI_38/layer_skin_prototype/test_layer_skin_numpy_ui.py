"""Real Qt installer controls driven by recorded child-process results; no network."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock
import layer_skin_dependencies as deps

try:
    from layer_skin_numpy_ui import PerformancePanel,QtCore,QtWidgets
except ImportError:
    PerformancePanel=None


if PerformancePanel is not None:
    class Process(QtCore.QObject):
        readyReadStandardOutput=QtCore.Signal()
        finished=QtCore.Signal(int,object)
        errorOccurred=QtCore.Signal(object)
        def __init__(self,parent):
            super(Process,self).__init__(parent);self.starts=[];self.program=None;self.args=[]
            self.running=False;self.data=b'';self.killed=0
        def setProcessChannelMode(self,value):pass
        def setProgram(self,value):self.program=value
        def setArguments(self,value):self.args=list(value)
        def start(self):self.running=True;self.starts.append((self.program,self.args[:]))
        def state(self):return QtCore.QProcess.Running if self.running else QtCore.QProcess.NotRunning
        def readAllStandardOutput(self):data=self.data;self.data=b'';return data
        def errorString(self):return 'Cannot launch executable'
        def complete(self,output='',code=0):
            self.data=output.encode();self.readyReadStandardOutput.emit();self.running=False
            self.finished.emit(code,QtCore.QProcess.NormalExit)
        def kill(self):
            self.killed+=1;self.running=False;self.finished.emit(1,QtCore.QProcess.CrashExit)
        def waitForFinished(self,timeout):return not self.running

    class Backend:
        def __init__(self):self.available=None;self.checks=[];self._NUMPY_ERROR=''
        def dependency_helpers(self):return deps
        def configure_numpy_root(self,root):self.root=root
        def numpy_backend(self,refresh=False):self.checks.append(refresh);return self.available


@unittest.skipIf(PerformancePanel is None,'PySide required')
class InstallerUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.backend=Backend();self.window=QtWidgets.QWidget()
        self.window.api=types.SimpleNamespace(cmds=types.SimpleNamespace(internalVar=lambda **kw:self.temp.name))
        self.panel=PerformancePanel(self.window,backend=self.backend,process_factory=Process)
        layout=QtWidgets.QVBoxLayout(self.window);layout.addWidget(self.panel);self.window.show();self.app.processEvents()
        self.path=mock.patch.object(deps,'mayapy_path',return_value='/Maya install/bin/mayapy');self.path.start()
    def tearDown(self):
        self.panel.shutdown();self.window.close();self.window.deleteLater()
        self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete);self.path.stop();self.temp.cleanup()
    def start(self):
        self.panel.install_button.click();self.assertTrue(self.panel._busy)
        self.assertEqual(self.panel.phase,'environment');return self.panel.process
    def environment(self,process,**changes):
        data=dict(deps.runtime_info(),pip=True);data.update(changes)
        process.complete(deps.ENV_MARKER+json.dumps(data))
    def installed(self,process,ready=True):
        self.environment(process);self.assertEqual(self.panel.phase,'install')
        stage=Path(self.panel.stage);(stage/'numpy').mkdir();(stage/'numpy/__init__.py').write_text('')
        process.complete();self.assertEqual(self.panel.phase,'verify')
        if ready:self.backend.available=types.SimpleNamespace(__version__='1.26.4')
        process.complete(deps.NUMPY_MARKER+json.dumps(dict(version='1.26.4',file=str(stage/'numpy/__init__.py'))))
    def test_missing_backend_is_reported_without_starting_install_or_creating_files(self):
        self.assertIn('unavailable',self.panel.status.text());self.assertTrue(self.panel.install_button.isEnabled())
        self.assertEqual(self.panel.process.starts,[]);self.assertFalse(Path(self.panel.root).exists())
    def test_already_available_backend_never_installs_or_replaces_it(self):
        self.backend.available=types.SimpleNamespace(__version__='existing')
        self.panel.recheck();self.assertIn('existing ready',self.panel.status.text())
        self.panel.install();self.assertEqual(self.panel.process.starts,[]);self.assertTrue(self.panel.install_button.isHidden())
    def test_success_uses_maya_python_verifies_before_activation_and_rechecks_backend(self):
        process=self.start();self.assertFalse(self.panel.check_button.isEnabled())
        self.panel.install();self.assertEqual(len(process.starts),1)
        self.installed(process)
        self.assertEqual(len(process.starts),3)
        self.assertEqual(process.starts[1][0],'/Maya install/bin/mayapy')
        args=process.starts[1][1];self.assertIn('--only-binary=:all:',args);self.assertEqual(args[-1],'numpy==1.26.4')
        self.assertTrue(deps.active_path(self.panel.root));self.assertIsNone(self.panel.stage)
        self.assertFalse(self.panel._busy);self.assertIn('1.26.4 ready',self.panel.status.text())
        self.assertTrue(all(self.backend.checks));self.assertTrue(self.panel.install_button.isHidden())
    def test_pip_failure_never_publishes_partial_install(self):
        process=self.start();stage=Path(self.panel.stage);self.environment(process)
        process.complete('Network or wheel error',code=1)
        self.assertFalse(self.panel._busy);self.assertFalse(stage.exists());self.assertIsNone(deps.active_path(self.panel.root))
        self.assertIn('failed',self.panel.status.text());self.assertIn('Network or wheel error',self.panel.log.toPlainText())
    def test_wrong_python_and_missing_pip_never_start_install(self):
        for changes in [dict(python=[3,99]),dict(pip=False)]:
            process=self.start();before=len(process.starts);self.environment(process,**changes)
            self.assertFalse(self.panel._busy);self.assertEqual(len(process.starts),before)
            self.assertIsNone(deps.active_path(self.panel.root));self.assertIsNone(self.panel.stage)
    def test_cancel_kills_only_child_process_and_keeps_backend_fallback(self):
        process=self.start();stage=Path(self.panel.stage)
        self.panel.cancel_button.click()
        self.assertEqual(process.killed,1);self.assertFalse(self.panel._busy);self.assertFalse(stage.exists())
        self.assertIn('canceled',self.panel.status.text());self.assertIsNone(self.backend.available)
    def test_timeout_cancels_without_activating_any_package(self):
        process=self.start();self.panel.timeout.timeout.emit()
        self.assertEqual(process.killed,1);self.assertIn('timed out',self.panel.status.text())
        self.assertIsNone(deps.active_path(self.panel.root))
    def test_shutdown_during_download_cancels_and_removes_inactive_stage(self):
        process=self.start();self.environment(process);stage=Path(self.panel.stage)
        self.panel.shutdown();self.assertEqual(process.killed,1);self.assertFalse(stage.exists())
        self.assertIsNone(deps.active_path(self.panel.root));self.assertFalse(self.panel._busy)
    def test_failed_current_session_import_explains_restart_and_does_not_reinstall(self):
        process=self.start();self.backend._NUMPY_ERROR='DLL import failed';self.installed(process,ready=False)
        self.assertTrue(deps.active_path(self.panel.root));self.assertIn('restart Maya',self.panel.status.text())
        self.assertIn('DLL import failed',self.panel.log.toPlainText());self.assertFalse(self.panel.install_button.isEnabled())
        before=len(process.starts);self.panel.install();self.assertEqual(len(process.starts),before)
    def test_verification_cannot_activate_another_numpy_version(self):
        process=self.start();self.environment(process);process.complete()
        process.complete(deps.NUMPY_MARKER+json.dumps(dict(version='2.0.0',file='/elsewhere/numpy/__init__.py')))
        self.assertFalse(self.panel._busy);self.assertIsNone(deps.active_path(self.panel.root))
        self.assertIn('requested NumPy version',self.panel.status.text())
    def test_failed_to_start_cleans_attempt_and_retains_usable_controls(self):
        process=self.start();process.running=False;process.errorOccurred.emit(QtCore.QProcess.FailedToStart)
        self.assertFalse(self.panel._busy);self.assertIsNone(self.panel.stage)
        self.assertTrue(self.panel.check_button.isEnabled());self.assertIn('Could not start',self.panel.status.text())
    def test_recheck_enables_backend_after_external_install_without_starting_a_process(self):
        self.backend.available=types.SimpleNamespace(__version__='manual')
        self.panel.check_button.click()
        self.assertIn('manual ready',self.panel.status.text());self.assertEqual(self.panel.process.starts,[])
    def test_unsupported_python_keeps_standard_comparison_without_creating_install(self):
        with mock.patch.object(deps,'supported',return_value=False):
            self.panel.recheck();self.assertFalse(self.panel.install_button.isEnabled());self.panel.install()
        self.assertEqual(self.panel.process.starts,[]);self.assertFalse(Path(self.panel.root).exists())
    def test_real_layer_window_uses_active_command_backend_in_utilities_panel(self):
        import layer_skin_ui as ui
        from test_layer_skin_ui import Adapter
        api=Adapter();api.cmds.internalVar=lambda **kw:self.temp.name
        api._layer_skin_command_owner={'_modules':{'layer_skin_performance':self.backend}}
        window=ui.LayerUI(api)
        try:
            window.show();window.tabs.setCurrentIndex(1);self.app.processEvents()
            self.assertIs(window.numpy_panel.backend,self.backend)
            self.assertIn('unavailable',window.numpy_panel.status.text())
            self.assertTrue(window.numpy_panel.install_button.isVisible())
            self.assertEqual(window.numpy_panel.process.state(),QtCore.QProcess.NotRunning)
            self.assertEqual(api.calls,[])
        finally:window.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)


if __name__=='__main__':unittest.main()
