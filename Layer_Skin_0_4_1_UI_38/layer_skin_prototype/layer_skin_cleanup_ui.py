"""Reviewable cleanup for the current mesh; no scene-wide delete operation."""
import weakref
try:
    from PySide6 import QtCore,QtWidgets
except ImportError:
    from PySide2 import QtCore,QtWidgets


class CleanupDialog(QtWidgets.QDialog):
    def __init__(self,window):
        super(CleanupDialog,self).__init__(window)
        self.owner=weakref.ref(window);self.plan=None
        self.setObjectName('rtkLayerSkinCleanupWindow');self.setWindowTitle('Layer Skin · Cleanup')
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose);self.resize(650,420)
        layout=QtWidgets.QVBoxLayout(self)
        note=QtWidgets.QLabel('Saved layers stay in the Maya scene and reload when you reopen the tool. Choose a cleanup action below.');note.setWordWrap(True);layout.addWidget(note)
        self.target=QtWidgets.QLineEdit();self.target.setReadOnly(True);layout.addWidget(self.target)
        self.details=QtWidgets.QPlainTextEdit();self.details.setReadOnly(True);layout.addWidget(self.details,1)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        self.refresh_button=self.button(row,'Inspect current mesh',self.refresh_plan)
        self.cache_button=self.button(row,'Clear memory caches',self.clear_caches)
        self.remove_button=self.button(layout,'Remove saved layers · keep current skin',self.remove_layers)
        self.remove_button.setToolTip('Remove this mesh\'s Base snapshot, layers, masks and assignment reference. Current skinCluster weights and joints remain. One Maya Undo restores the saved data.')
        self.status=QtWidgets.QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        note=QtWidgets.QLabel('Temporary paint arrays may stay in memory for Maya Undo and are not saved to the scene. Cleanup never clears Undo. Save the scene after removing saved layers to keep that change.');note.setWordWrap(True);layout.addWidget(note)
        self.button(layout,'Close',self.close);self.refresh_plan()
    def button(self,layout,text,callback):
        button=QtWidgets.QPushButton(text);button.setAutoDefault(False);button.setDefault(False)
        button.clicked.connect(callback);layout.addWidget(button);return button
    def helper(self):return self.owner().session.helper('layer_skin_cleanup')
    def show_plan(self,plan):
        self.plan=plan;self.target.setText(plan['mesh'])
        lines=['Scope: this mesh only. Current skin weights are kept.','']
        for row in plan['nodes']:
            lines.append(row['node']+' — '+('BLOCKED: '+' '.join(row['blocked']) if row['blocked'] else 'Saved layer data'))
        for row in plan['skipped']:lines.append(row['node']+' — SKIPPED: '+row['reason'])
        if not plan['nodes']:lines.append('No removable saved layer data is linked to this mesh.')
        lines += ['', 'Removal discards the saved Base snapshot, all layers, masks, generated/painted samples and assignment reference for the listed data nodes.',
                  'It does not delete the mesh, skinCluster, joints, materials or unrelated network nodes.']
        self.details.setPlainText('\n'.join(lines))
        self.remove_button.setEnabled(bool(plan['nodes']) and not any(row['blocked'] for row in plan['nodes']))
    def refresh_plan(self,*_):
        self.plan=None;self.remove_button.setEnabled(False);window=self.owner()
        try:
            self.show_plan(self.helper().inspect(window.api,window.target.text()));self.status.setText('Inspection reads ownership links; skin weights and layer payloads are not decoded.')
        except Exception as exc:self.details.setPlainText(str(exc));self.status.setText('Load the intended mesh and inspect again. Memory-cache cleanup is still available.')
    def clear_caches(self,*_):
        window=self.owner()
        if window and window.clear_cache():self.status.setText('Memory caches cleared. Saved layers and current skin weights are kept.')
    def remove_layers(self,*_):
        window=self.owner()
        if self.plan is None:return
        try:
            result=window.remove_saved_layers(self.plan)
            if result is None:return
            count=len(result['removed']);self.refresh_plan()
            self.status.setText('Removed {} saved data node(s). Current skin is unchanged. Maya Undo restores the layers; + starts a fresh stack from current skin.'.format(count))
            if result.get('cache_warning'):self.status.setText(self.status.text()+' '+result['cache_warning'])
        except Exception as exc:self.status.setText(str(exc))
