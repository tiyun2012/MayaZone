"""Opt-in NumPy installer; child mayapy processes keep Maya's UI responsive."""
import os
import weakref
try:
    from PySide6 import QtCore,QtWidgets
except ImportError:
    from PySide2 import QtCore,QtWidgets


class PerformancePanel(QtWidgets.QGroupBox):
    def __init__(self,window,backend=None,process_factory=None):
        super(PerformancePanel,self).__init__('Performance',window)
        self.owner=weakref.ref(window);self._backend=backend
        self._checked=False;self._busy=False;self._closed=False;self._ready=False;self._restart_required=False
        self.root=None;self.stage=None;self.executable=None;self.phase=None;self.output='';self.failure=''
        layout=QtWidgets.QVBoxLayout(self)
        self.status=QtWidgets.QLabel('Check NumPy for optional high-resolution acceleration.');self.status.setWordWrap(True);layout.addWidget(self.status)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.install_button=QtWidgets.QPushButton('Install NumPy');self.check_button=QtWidgets.QPushButton('Recheck NumPy')
        self.cancel_button=QtWidgets.QPushButton('Cancel installation');self.cancel_button.hide()
        for button in (self.install_button,self.check_button,self.cancel_button):
            button.setAutoDefault(False);button.setDefault(False);row.addWidget(button)
        row.addStretch(1)
        note=QtWidgets.QLabel('Optional acceleration for large weight comparisons. Installation needs internet access and runs in the background.');note.setWordWrap(True);layout.addWidget(note)
        self.progress=QtWidgets.QProgressBar();self.progress.setRange(0,0);self.progress.hide();layout.addWidget(self.progress)
        self.log=QtWidgets.QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(200)
        self.log.setMaximumHeight(140);self.log.setPlaceholderText('Install details');self.log.hide();layout.addWidget(self.log)
        self.process=(process_factory or QtCore.QProcess)(self)
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.process_finished);self.process.errorOccurred.connect(self.process_error)
        self.timeout=QtCore.QTimer(self);self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda:self.abort('NumPy installation timed out. See install details.'))
        self.install_button.clicked.connect(self.install);self.check_button.clicked.connect(self.recheck)
        self.cancel_button.clicked.connect(lambda:self.abort('NumPy installation canceled.'))
        window.destroyed.connect(self.shutdown)

    @property
    def backend(self):
        if self._backend is None:
            window=self.owner()
            owner=getattr(window.api,'_layer_skin_command_owner',{})
            self._backend=owner.get('_modules',{}).get('layer_skin_performance')
            if self._backend is None:self._backend=window.session.helper('layer_skin_performance')
        return self._backend

    @property
    def deps(self):return self.backend.dependency_helpers()

    def showEvent(self,event):
        super(PerformancePanel,self).showEvent(event)
        if not self._checked:self.recheck()

    def set_busy(self,value):
        self._busy=value
        if self._closed:return
        self.progress.setVisible(value);self.cancel_button.setVisible(value)
        self.check_button.setEnabled(not value)
        self.install_button.setVisible(not self._ready)
        self.install_button.setEnabled(not value and not self._ready and not self._restart_required and self.deps.supported())

    def configure(self):
        window=self.owner();internal=getattr(window.api.cmds,'internalVar',None)
        if callable(internal):
            self.root=self.deps.dependency_root(internal(userAppDir=True))
            self.backend.configure_numpy_root(self.root)

    def recheck(self,*_):
        if self._busy or self._closed:return
        self._checked=True
        try:
            self.configure();np=self.backend.numpy_backend(refresh=True)
            self._ready=np is not None
            if self._ready:
                self._restart_required=False
                self.status.setText('NumPy {} ready · accelerated large comparisons.'.format(np.__version__))
            elif not self.deps.supported():
                self.status.setText('NumPy unavailable · standard comparison active. Automatic install supports Python 3.9–3.12.')
            else:self.status.setText('NumPy unavailable · standard comparison active. Install NumPy to enable acceleration.')
        except Exception as exc:
            self._ready=False;self.status.setText('NumPy check failed: '+str(exc))
        self.set_busy(False)

    def install(self,*_):
        if self._busy or self._closed:return
        self.recheck()
        if self._ready or self._restart_required:return
        try:
            if not self.deps.supported():raise ValueError('Automatic install supports Python 3.9–3.12.')
            if not self.root:raise ValueError('Maya user folder is unavailable. Run this installer inside Maya.')
            self.executable=self.deps.mayapy_path()
            if not self.executable:raise ValueError('Could not locate mayapy beside Maya or under MAYA_LOCATION.')
            self.stage=self.deps.make_stage(self.root);self.failure='';self.log.clear();self.log.show()
            self.set_busy(True)
            self.start_step('environment',['-c',self.deps.ENV_PROBE],'Checking Maya Python…',30000)
        except Exception as exc:self.finish('NumPy installation could not start: '+str(exc))

    def start_step(self,phase,arguments,text,timeout):
        self.phase=phase;self.output='';self.status.setText(text)
        self.process.setProgram(self.executable);self.process.setArguments(arguments)
        self.timeout.start(timeout);self.process.start()

    def read_output(self):
        text=bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace')
        self.output=(self.output+text)[-65536:]
        if text and not self._closed:self.log.appendPlainText(text[-16384:].rstrip())

    def process_finished(self,code,status):
        if not self._busy:return
        self.timeout.stop();self.read_output()
        if self._closed or self.failure:
            self.finish(self.failure or 'NumPy installation canceled.');return
        if code or status!=QtCore.QProcess.NormalExit:
            self.finish('NumPy installation failed. See install details; standard comparison remains available.');return
        try:
            if self.phase=='environment':
                self.deps.validate_runtime(self.deps.parse_result(self.output,self.deps.ENV_MARKER))
                self.start_step('install',self.deps.pip_arguments(self.stage),'Downloading and installing NumPy…',600000)
            elif self.phase=='install':
                self.start_step('verify',['-c',self.deps.NUMPY_PROBE,self.stage],'Verifying NumPy in Maya Python…',60000)
            elif self.phase=='verify':
                self.deps.verify_numpy(self.deps.parse_result(self.output,self.deps.NUMPY_MARKER),self.stage)
                self.deps.activate(self.root,self.stage);self.stage=None
                np=self.backend.numpy_backend(refresh=True);self._ready=np is not None
                self._restart_required=not self._ready
                if self._ready:self.finish('NumPy {} ready · accelerated large comparisons.'.format(np.__version__))
                else:
                    error=getattr(self.backend,'_NUMPY_ERROR','')
                    if error:self.log.appendPlainText(error)
                    self.finish('NumPy installed, but Maya could not load it yet. See details and restart Maya; standard comparison remains active.')
        except Exception as exc:self.finish('NumPy installation failed: '+str(exc))

    def process_error(self,error):
        if self._busy and error==QtCore.QProcess.FailedToStart:
            self.finish('Could not start Maya Python: '+self.process.errorString())

    def abort(self,message):
        if not self._busy:return
        self.failure=message
        if self.process.state()!=QtCore.QProcess.NotRunning:self.process.kill()
        else:self.finish(message)

    def finish(self,message):
        self.timeout.stop()
        if self.stage:
            try:self.deps.remove_stage(self.root,self.stage);self.stage=None
            except (OSError,ValueError) as exc:
                if not self._closed:self.log.appendPlainText('Inactive temporary files could not be removed: '+str(exc))
        self.set_busy(False)
        if not self._closed:self.status.setText(message)

    def shutdown(self,*_):
        if self._closed:return
        self._closed=True;self.timeout.stop();self.failure='NumPy installation canceled.'
        if self.process.state()!=QtCore.QProcess.NotRunning:
            self.process.kill();self.process.waitForFinished(1000)
        if self.process.state()==QtCore.QProcess.NotRunning:self.finish(self.failure)
