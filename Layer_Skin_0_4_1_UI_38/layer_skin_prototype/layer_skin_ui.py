"""Layer Skin Qt panel. Maya scene edits go through the undoable command only."""
import json

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    import shiboken6 as shiboken
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    import shiboken2 as shiboken

_dialog = None
BASE = '__base__'


class LayerDelegate(QtWidgets.QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        if index.column() == 3:
            editor = QtWidgets.QDoubleSpinBox(parent)
            editor.setRange(0., 1.); editor.setDecimals(6); editor.setSingleStep(.01)
            editor.setKeyboardTracking(False)
            editor.setToolTip('Layer alpha (opacity). Enter or leave the field to apply.')
            if index.sibling(index.row(),0).data(QtCore.Qt.UserRole)==BASE:editor.setEnabled(False)
            editor.editingFinished.connect(lambda: self.commitData.emit(editor))
            return editor
        if index.column() == 1:
            return super(LayerDelegate, self).createEditor(parent, option, index)
        return None

    def setEditorData(self, editor, index):
        if index.column() == 3:
            blocker = QtCore.QSignalBlocker(editor)
            editor.setValue(float(index.data(QtCore.Qt.EditRole) or 0.))
            editor._rtk_displayed_value = editor.value()
            del blocker
        else:
            super(LayerDelegate, self).setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if index.column() == 3:
            editor.interpretText()
            if editor.value() != editor._rtk_displayed_value:
                model.setData(index, editor.value(), QtCore.Qt.EditRole)
        else:
            super(LayerDelegate, self).setModelData(editor, model, index)


class LayerTable(QtWidgets.QTreeWidget):
    MIME = 'application/x-rtk-layer-id'
    orderRequested = QtCore.Signal(list)
    propertyRequested = QtCore.Signal(str, dict)
    actionRequested = QtCore.Signal(str, str)

    def __init__(self, parent=None):
        super(LayerTable, self).__init__(parent)
        self.setColumnCount(4); self.setHeaderLabels(['↕', 'Layer name', 'Enabled', 'Alpha'])
        self.setRootIsDecorated(False); self.setItemsExpandable(False)
        self.setAlternatingRowColors(True); self.setUniformRowHeights(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.EditKeyPressed)
        self.setDragEnabled(True); self.setAcceptDrops(True); self.setDropIndicatorShown(False)
        self._drop_slot = None
        pixmap = QtGui.QPixmap(14, 14); pixmap.fill(QtGui.QColor(230, 230, 230))
        painter = QtGui.QPainter(pixmap); painter.fillRect(0, 0, 7, 14, QtGui.QColor(90, 90, 90)); painter.end()
        self._mask_icon = QtGui.QIcon(pixmap)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.MoveAction); self.setSortingEnabled(False)
        self.setMinimumHeight(190)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed); self.setColumnWidth(0, 30)
        self.header().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.header().setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed); self.setColumnWidth(2, 76)
        self.header().setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed); self.setColumnWidth(3, 96)
        self.setItemDelegate(LayerDelegate(self))
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_menu)
        self.itemChanged.connect(self.changed)

    def identity(self, item):
        return item.data(0, QtCore.Qt.UserRole) if item else None

    def order(self):
        return [self.identity(self.topLevelItem(i)) for i in range(self.topLevelItemCount())]

    def set_layers(self, rows, keep=None):
        blocker = QtCore.QSignalBlocker(self)
        # Preserve active editors for name/checkbox/alpha changes. A reorder
        # rebuilds rows from the authoritative scene, never from their labels.
        rebuild = self.order() != [row['id'] for row in rows]
        if rebuild:
            self.clear()
        selected = None
        for i, row in enumerate(rows):
            item = QtWidgets.QTreeWidgetItem(self) if rebuild else self.topLevelItem(i)
            item.setFlags((item.flags() | QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsUserCheckable |
                           QtCore.Qt.ItemIsDragEnabled) & ~QtCore.Qt.ItemIsDropEnabled)
            if row['id']==BASE:
                item.setFlags(item.flags() & ~(QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsDragEnabled))
            item.setData(0, QtCore.Qt.UserRole, row['id']); item.setText(0, '' if row['id']==BASE else '⋮⋮')
            item.setToolTip(0, 'Drag this row above or below another layer.')
            item.setText(1, row['name'])
            item.setIcon(1, self._mask_icon)
            item.setToolTip(1, '{} edited vertices · {} mask overrides\nDouble-click or right-click to rename.'.format(
                len(row['samples']), len(row['mask'])))
            item.setCheckState(2, QtCore.Qt.Checked if row['enabled'] else QtCore.Qt.Unchecked)
            item.setData(3, QtCore.Qt.EditRole, float(row['opacity']))
            item.setSizeHint(0, QtCore.QSize(30, 30))
            if row['id'] == keep:
                selected = item
        if rows:
            self.setCurrentItem(selected or self.topLevelItem(0), 1)
        for i in range(self.topLevelItemCount()):
            self.openPersistentEditor(self.topLevelItem(i), 3)
        del blocker

    def changed(self, item, column):
        identity = self.identity(item)
        if identity==BASE:return
        if column == 1:
            self.propertyRequested.emit(identity, {'name': item.text(1)})
        elif column == 2:
            self.propertyRequested.emit(identity, {'enabled': item.checkState(2) == QtCore.Qt.Checked})
        elif column == 3:
            self.propertyRequested.emit(identity, {'opacity': float(item.data(3, QtCore.Qt.EditRole))})

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if not item or self.identity(item)==BASE:
            return
        drag = QtGui.QDrag(self); mime = QtCore.QMimeData()
        mime.setData(self.MIME, self.identity(item).encode('utf-8')); drag.setMimeData(mime)
        execute = getattr(drag, 'exec', None) or drag.exec_
        execute(QtCore.Qt.MoveAction)

    def valid_drag(self, event):
        return event.source() is self and event.mimeData().hasFormat(self.MIME)

    def position(self, event):
        return event.position().toPoint() if hasattr(event, 'position') else event.pos()

    def target_slot(self, position):
        item = self.itemAt(position)
        if item is None:
            return self.topLevelItemCount()
        return self.indexOfTopLevelItem(item) + int(position.y() > self.visualItemRect(item).center().y())

    def dragEnterEvent(self, event):
        event.acceptProposedAction() if self.valid_drag(event) else event.ignore()

    def dragMoveEvent(self, event):
        if not self.valid_drag(event):
            event.ignore(); return
        self._drop_slot = self.target_slot(self.position(event)); self.viewport().update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._drop_slot = None; self.viewport().update(); event.accept()

    def paintEvent(self, event):
        super(LayerTable, self).paintEvent(event)
        if self._drop_slot is not None:
            count = self.topLevelItemCount()
            if self._drop_slot < count:
                y = self.visualItemRect(self.topLevelItem(self._drop_slot)).top()
            else:
                y = self.visualItemRect(self.topLevelItem(count-1)).bottom() if count else 1
            painter = QtGui.QPainter(self.viewport()); painter.setPen(QtGui.QPen(self.palette().highlight().color(), 2))
            painter.drawLine(0, y, self.viewport().width(), y); painter.end()

    def dropEvent(self, event):
        self._drop_slot = None; self.viewport().update()
        if not self.valid_drag(event):
            event.ignore(); return
        identity = bytes(event.mimeData().data(self.MIME)).decode('utf-8')
        before = self.order()
        if identity not in before:
            event.ignore(); return
        source = before.index(identity); slot = self.target_slot(self.position(event))
        if identity==BASE:event.ignore();return
        if BASE in before:slot=min(slot,before.index(BASE))
        after = list(before); after.pop(source); after.insert(slot-int(source < slot), identity)
        event.acceptProposedAction()
        # Never move rows independently of the scene. Failed commands leave the
        # authoritative order intact, and one accepted drop creates one Undo.
        if after != before:
            self.orderRequested.emit([identity for identity in after if identity!=BASE])

    def mouseDoubleClickEvent(self,event):
        point=event.position().toPoint() if hasattr(event,'position') else event.pos()
        item=self.itemAt(point)
        if item and self.columnAt(point.x())==1 and point.x()-self.columnViewportPosition(1)<22:
            identity=self.identity(item)
            self.actionRequested.emit('view_mask' if identity==BASE else 'paint_mask',identity);event.accept();return
        super(LayerTable,self).mouseDoubleClickEvent(event)

    def menu_for(self, item):
        menu = QtWidgets.QMenu(self)
        identity=self.identity(item)
        if identity==BASE:
            view=menu.addAction('View mask');view.triggered.connect(lambda *_:self.actionRequested.emit('view_mask',identity))
            return menu
        paint=menu.addAction('Paint mask');paint.triggered.connect(lambda *_:self.actionRequested.emit('paint_mask',identity))
        menu.addSeparator()
        rename = menu.addAction('Rename'); rename.triggered.connect(lambda *_: self.editItem(item, 1))
        toggle = menu.addAction('Disable' if item.checkState(2) == QtCore.Qt.Checked else 'Enable')
        identity = self.identity(item)
        toggle.triggered.connect(lambda *_: self.propertyRequested.emit(identity, {'enabled': item.checkState(2) != QtCore.Qt.Checked}))
        menu.addSeparator()
        delete = menu.addAction('Delete layer'); delete.triggered.connect(lambda *_: self.actionRequested.emit('delete', identity))
        return menu

    def context_menu(self, position):
        item = self.itemAt(position)
        if not item:
            return
        self.setCurrentItem(item, 1)
        menu = self.menu_for(item)
        execute = getattr(menu, 'exec', None) or menu.exec_
        execute(self.viewport().mapToGlobal(position))
        menu.deleteLater()


_workflow_module = None


def LayerUI(api, parent=None):
    global _workflow_module
    if _workflow_module is None:
        import importlib.util
        import os
        filename=os.path.join(os.path.dirname(__file__),'layer_skin_workflow_ui.py')
        spec=importlib.util.spec_from_file_location('_rtk_layer_skin_workflow_ui_041',filename)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);_workflow_module=module
    return _workflow_module.LayerUI(api,LayerTable,parent)


def show(api):
    global _dialog
    if _dialog is not None and shiboken.isValid(_dialog) and not getattr(_dialog,'_closed',False):
        _dialog.show(); _dialog.raise_(); _dialog.activateWindow(); return _dialog
    import maya.OpenMayaUI as omui
    pointer = omui.MQtUtil.mainWindow()
    parent = shiboken.wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else None
    _dialog = LayerUI(api, parent); _dialog.show(); return _dialog


def close_dialog():
    global _dialog
    if _dialog is not None and shiboken.isValid(_dialog):
        _dialog.close()
    _dialog = None
