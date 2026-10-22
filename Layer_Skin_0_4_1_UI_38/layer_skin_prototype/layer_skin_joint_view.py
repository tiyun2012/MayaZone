"""Scene-backed Qt joint hierarchy. No scene edits or Maya calls while painting rows."""
import fnmatch
import re
try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets


class JointStatus:
    def __init__(self):
        self.paths = {}; self.by_name = {}; self.weighted = set(); self.members = set()

    def update(self, paths, weighted, members):
        self.paths = dict(paths); self.weighted = set(weighted); self.members = set(members)
        self.by_name = {}
        for path in self.paths:
            self.by_name.setdefault(path.rsplit('|', 1)[-1], []).append(path)

    def resolve(self, index):
        """Resolve duplicate names through displayed ancestors, using cached DAG paths."""
        if not index.isValid():return None
        index = index.sibling(index.row(), 0)
        tooltip = index.data(QtCore.Qt.ToolTipRole)
        if isinstance(tooltip, str) and tooltip in self.paths:return tooltip
        name = index.data(QtCore.Qt.DisplayRole)
        if not isinstance(name, str):return None
        if name in self.paths:return name
        candidates = self.by_name.get(name, [])
        if len(candidates) == 1:return candidates[0]
        ancestors = []; parent = index.parent()
        while parent.isValid():
            ancestors.append(str(parent.data(QtCore.Qt.DisplayRole))); parent = parent.parent()
        def matches(path):
            parts = path.split('|')[:-1]
            for ancestor in ancestors:
                while parts and parts[-1] != ancestor:parts.pop()
                if not parts:return False
                parts.pop()
            return True
        matching = [path for path in candidates if matches(path)]
        return matching[0] if len(matching) == 1 else None


class JointDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, view, status):
        super(JointDelegate, self).__init__(view)
        self.original = view.itemDelegate(); self.status = status

    def is_empty(self, index):
        path = self.status.resolve(index)
        return path is not None and self.status.paths[path] not in self.status.weighted

    def empty_option(self, option, index):
        result = QtWidgets.QStyleOptionViewItem(option); self.initStyleOption(result, index)
        text = result.palette.color(QtGui.QPalette.Active, QtGui.QPalette.Text)
        base = result.palette.color(QtGui.QPalette.Active, QtGui.QPalette.Base)
        gray = round(.4 * text.lightness() + .6 * base.lightness())
        color = QtGui.QColor(gray, gray, gray)
        for group in (QtGui.QPalette.Active, QtGui.QPalette.Inactive, QtGui.QPalette.Disabled):
            result.palette.setColor(group, QtGui.QPalette.Text, color)
            result.palette.setColor(group, QtGui.QPalette.HighlightedText, QtGui.QColor(max(gray, 165), max(gray, 165), max(gray, 165)))
        return result

    def paint(self, painter, option, index):
        if not self.is_empty(index):
            self.original.paint(painter, option, index); return
        # Keep model icons and selection while using this view's gray palette.
        styled = self.empty_option(option, index)
        style = styled.widget.style() if styled.widget else QtWidgets.QApplication.style()
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, styled, painter, styled.widget)

    def sizeHint(self, option, index):return self.original.sizeHint(option, index)

    def helpEvent(self, event, view, option, index):
        path = self.status.resolve(index)
        if path is None:return self.original.helpEvent(event, view, option, index)
        identity = self.status.paths[path]
        note = 'Has weights in this layer.' if identity in self.status.weighted else 'No weights in this layer. This joint is still selectable.'
        if getattr(self.status,'editable',False):
            note+='\n'+('Locked' if identity in getattr(self.status,'locked',set()) else 'Unlocked')+' for this layer. Click the padlock to toggle.'
            note+='\nLocks protect this layer contribution; lower layers, coverage, masks and alpha still affect final skin weights.'
        if identity not in self.status.members:note += '\nPaint directly; the first stroke adds this joint automatically.'
        note+='\nShift-click the row or arrow to expand this entire branch.'
        QtWidgets.QToolTip.showText(event.globalPos(), path + '\n' + note, view)
        return True


class JointStyling:
    def __init__(self, widget):
        self.status = JointStatus(); self.views = widget.findChildren(QtWidgets.QTreeView)
        if isinstance(widget, QtWidgets.QTreeView):self.views.append(widget)
        if not self.views:raise RuntimeError('The joint view has no Qt tree to style.')
        self.delegates = []
        for view in self.views:
            delegate = JointDelegate(view, self.status); view.setItemDelegate(delegate); self.delegates.append(delegate)

    def update(self, paths, weighted, members):
        self.status.update(paths, weighted, members)
        for view in self.views:view.viewport().update()


def skin_roots(api,ctx):
    """All influence branches, including joint ancestors above transform buffers.

    Skin membership, not selection or layer weights, seeds the forest. Read
    full DAG prefixes once per distinct ancestor; no scene edits are performed.
    """
    roots=set();types={}
    for influence in ctx['influences']:
        path=influence.fullPathName();root=None
        while path:
            if path not in types:types[path]=api.cmds.nodeType(path)
            if types[path]=='joint':root=path
            path=path.rsplit('|',1)[0]
        if root:roots.add(root)
    result=[]
    for root in sorted(roots,key=lambda path:(path.count('|'),path)):
        if not any(root.startswith(parent+'|') for parent in result):result.append(root)
    return tuple(result)


def joint_icon():
    for resource in (':/out_joint.png', ':/kinJoint.png'):
        icon=QtGui.QIcon(resource)
        if not icon.isNull():return icon
    pixmap=QtGui.QPixmap(16,16);pixmap.fill(QtCore.Qt.transparent)
    painter=QtGui.QPainter(pixmap);painter.setRenderHint(QtGui.QPainter.Antialiasing)
    color=QtGui.QColor(172,151,210);painter.setPen(QtGui.QPen(color,1.4))
    painter.drawLine(QtCore.QPointF(4,12),QtCore.QPointF(12,4));painter.setBrush(color)
    painter.drawEllipse(QtCore.QPointF(4,12),2.4,2.4);painter.drawEllipse(QtCore.QPointF(12,4),1.8,1.8)
    painter.end();return QtGui.QIcon(pixmap)


def lock_icon(locked):
    """Prefer Maya's own padlocks; keep an off-host/missing-resource fallback.

    Loaded only when the browser builds its two cached row icons. Validate a
    rendered pixmap: a missing SVG can still produce a non-null QIcon in Qt.
    """
    names=('Lock_ON.png','lockGeneric.png') if locked else ('Lock_OFF.png','unlockGeneric.png')
    for name in names:
        icon=QtGui.QIcon(':/'+name)
        if not icon.pixmap(16,16).isNull():return icon
    pixmap=QtGui.QPixmap(16,16);pixmap.fill(QtCore.Qt.transparent)
    p=QtGui.QPainter(pixmap);p.setRenderHint(QtGui.QPainter.Antialiasing)
    color=QtGui.QColor('#e2b74b' if locked else '#969b9f')
    p.setPen(QtGui.QPen(color,1.4));p.setBrush(QtCore.Qt.NoBrush)
    p.drawArc(QtCore.QRectF(4 if locked else 6,1,7,9),0,180*16)
    if locked:
        p.drawLine(QtCore.QPointF(4,5.5),QtCore.QPointF(4,8));p.drawLine(QtCore.QPointF(11,5.5),QtCore.QPointF(11,8))
    else:p.drawLine(QtCore.QPointF(13,5.5),QtCore.QPointF(13,8))
    p.setBrush(color.darker(145));p.drawRoundedRect(QtCore.QRectF(2,7,12,8),1.5,1.5)
    p.setPen(color.lighter(155));p.drawLine(8,10,8,12)
    p.end();return QtGui.QIcon(pixmap)


def influence_icon(joint,locked):
    pixmap=QtGui.QPixmap(36,16);pixmap.fill(QtCore.Qt.transparent)
    p=QtGui.QPainter(pixmap)
    lock_icon(locked).paint(p,QtCore.QRect(0,0,16,16))
    joint.paint(p,QtCore.QRect(20,0,16,16));p.end();return QtGui.QIcon(pixmap)


class LockClicks(QtCore.QObject):
    """Keep padlock clicks separate from Shift-click branch expansion."""
    def __init__(self,browser):
        super(LockClicks,self).__init__(browser.widget);self.browser=browser;self.pressed=None;self.branch_pressed=False
    def eventFilter(self,watched,event):
        b=self.browser
        if b.closed:return False
        kind=event.type()
        if kind not in (QtCore.QEvent.MouseButtonPress,QtCore.QEvent.MouseButtonRelease,QtCore.QEvent.MouseButtonDblClick):return False
        if event.button()!=QtCore.Qt.LeftButton:return False
        point=event.position().toPoint() if hasattr(event,'position') else event.pos()
        item=b.widget.itemAt(point);inside=item is not None and b.lock_rect(item).contains(point)
        if kind==QtCore.QEvent.MouseButtonPress:
            self.branch_pressed=False
            self.pressed=item.data(0,QtCore.Qt.UserRole) if inside else None
            if inside:return True
            if item is not None and event.modifiers() & QtCore.Qt.ShiftModifier:
                self.branch_pressed=True
                b.expand_branch(item)
                b.shift_select(item,bool(event.modifiers() & QtCore.Qt.ControlModifier))
                return True
            return False
        if kind==QtCore.QEvent.MouseButtonDblClick:
            if inside:self.pressed=None
            elif item is not None and event.modifiers() & QtCore.Qt.ShiftModifier:
                self.branch_pressed=True;b.expand_branch(item);return True
            return inside
        if self.branch_pressed:
            self.branch_pressed=False;return True
        pressed=self.pressed;self.pressed=None
        if pressed is not None:
            if inside and item.data(0,QtCore.Qt.UserRole)==pressed and b.editable and b.lock_changed:
                b.lock_changed(pressed,b.records[pressed] not in b.locked)
            return True
        return inside


class JointTree:
    """Own the real tree widget directly, instead of reparenting a Maya editor."""
    def __init__(self,api,parent,selected,guard=None):
        self.api=api;self.selected=selected;self.closed=False;self.roots=();self._updating=False
        self.items={};self.records={};self.known={};self.weighted=set();self.members=set()
        self.locked=set();self.editable=False;self.lock_changed=None
        self.search=None;self.search_status=None;self._search_expanded=None
        self.select_branch=None
        self.widget=None;self.empty=None;self.styling=None;self.guard=None
        try:self.create_widgets(parent,guard)
        except Exception:
            self.close();raise

    def create_widgets(self,parent,guard):
        search_row=QtWidgets.QWidget(parent);row=QtWidgets.QHBoxLayout(search_row);row.setContentsMargins(0,0,0,0)
        row.addWidget(QtWidgets.QLabel('Search',search_row))
        self.search=QtWidgets.QLineEdit(search_row);self.search.setObjectName('LayerSkinJointSearch')
        self.search.setPlaceholderText('Name or pattern: left*Shoulder*')
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip('Case-insensitive joint names. Plain text finds any part of a name. * matches any text; ? matches one character. Examples: Shoulder, left**Shoulder**. Namespaces are ignored unless included in the search. Parents stay visible; search does not change the paint joint.')
        row.addWidget(self.search,1);parent.layout().addWidget(search_row)
        self.search_status=QtWidgets.QLabel(parent);self.search_status.setObjectName('LayerSkinJointSearchStatus')
        self.search_status.setWordWrap(True);self.search_status.hide();parent.layout().addWidget(self.search_status)
        self.search.textChanged.connect(self.filter_joints)
        self.empty=QtWidgets.QLabel('Select a skinned mesh to show its joint hierarchy.',parent)
        self.empty.setWordWrap(True);parent.layout().addWidget(self.empty)
        self.widget=QtWidgets.QTreeWidget(parent);self.widget.setObjectName('LayerSkinJointTree')
        self.widget.setHeaderHidden(True);self.widget.setRootIsDecorated(True);self.widget.setIndentation(18)
        self.widget.setUniformRowHeights(True);self.widget.setExpandsOnDoubleClick(True)
        self.widget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.widget.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.widget.setDragEnabled(False);self.widget.setAcceptDrops(False)
        self.widget.setContextMenuPolicy(QtCore.Qt.PreventContextMenu)
        self.widget.setToolTip('Shift-click a joint row or its arrow to expand every level below it. Use Select joint + descendants to select the whole branch. Ctrl-click keeps normal multi-selection.')
        parent.layout().addWidget(self.widget,1);self.widget.show()
        self.select_branch=QtWidgets.QPushButton('Select joint + descendants',parent)
        self.select_branch.setObjectName('LayerSkinSelectJointBranch')
        self.select_branch.setToolTip('Select each selected joint and all its joint descendants, including collapsed or search-hidden rows. Keeps the current paint joint and does not change Maya scene selection.')
        self.select_branch.setEnabled(False);self.select_branch.clicked.connect(self.select_descendants)
        parent.layout().addWidget(self.select_branch)
        self.guard=guard(self.widget) if guard else None
        self.styling=JointStyling(self.widget);self.icon=joint_icon()
        self.icons={locked:influence_icon(self.icon,locked) for locked in (False,True)}
        self.widget.setIconSize(QtCore.QSize(36,16));self.lock_clicks=LockClicks(self)
        self.widget.viewport().installEventFilter(self.lock_clicks)
        self.widget.itemSelectionChanged.connect(self.selection_changed)

    def selection_changed(self):
        if not self.closed:
            self.update_branch_action()
            if not self._updating:self.selected()

    def update_branch_action(self):
        if self.select_branch is not None:self.select_branch.setEnabled(bool(self.joints()))

    def branch_items(self,roots):
        """Iterate cached rows, including hidden children and skipped DAG buffers."""
        stack=list(roots);seen=set()
        while stack:
            item=stack.pop();path=item.data(0,QtCore.Qt.UserRole)
            if path in seen:continue
            seen.add(path);yield item
            stack.extend(item.child(i) for i in range(item.childCount()-1,-1,-1))

    def expand_branch(self,item):
        if self.closed:return
        updates=self.widget.updatesEnabled();self.widget.setUpdatesEnabled(False)
        try:
            for row in self.branch_items([item]):
                if row.childCount():
                    row.setExpanded(True)
                    if self._search_expanded is not None:
                        self._search_expanded[self.records[row.data(0,QtCore.Qt.UserRole)]]=True
        finally:self.widget.setUpdatesEnabled(updates)

    def shift_select(self,item,additive=False):
        """Expand gestures keep an already selected row's multi-selection intact."""
        tree=self.widget;before=self.joints();current=tree.currentItem()
        tree.setFocus(QtCore.Qt.MouseFocusReason)
        blocker=QtCore.QSignalBlocker(tree)
        try:
            flags=(QtCore.QItemSelectionModel.NoUpdate if item.isSelected() else
                   (QtCore.QItemSelectionModel.Select if additive else QtCore.QItemSelectionModel.ClearAndSelect)
                   | QtCore.QItemSelectionModel.Rows)
            tree.setCurrentItem(item,0,flags)
        finally:del blocker
        if self.joints()!=before or current is not tree.currentItem():self.selection_changed()

    def select_descendants(self,*_):
        """Select complete branches once, retaining the active joint as current."""
        if self.closed:return
        before=self.joints()
        if not before:return
        tree=self.widget;roots=[self.items[path] for path in before]
        current=tree.currentItem();anchor=current if current in roots else roots[-1]
        selection=QtCore.QItemSelection()
        for item in roots:
            index=tree.indexFromItem(item);selection.select(index,index)
        for item in self.branch_items(roots):
            if item.childCount():
                selection.select(tree.indexFromItem(item.child(0)),tree.indexFromItem(item.child(item.childCount()-1)))
        updates=tree.updatesEnabled();tree.setUpdatesEnabled(False);blocker=QtCore.QSignalBlocker(tree)
        try:
            tree.selectionModel().select(selection,QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
            tree.setCurrentItem(anchor,0,QtCore.QItemSelectionModel.NoUpdate)
        finally:
            del blocker;tree.setUpdatesEnabled(updates)
        if set(self.joints())!=set(before) or current is not tree.currentItem():self.selection_changed()

    def filter_joints(self,*_):
        """Filter existing Qt rows only; no scene queries or paint callbacks."""
        if self.closed or self.widget is None:return
        pattern=self.search.text().strip().casefold()
        active=bool(pattern)
        if active and self._search_expanded is None:self._search_expanded={}
        if active:
            for path,item in self.items.items():
                self._search_expanded.setdefault(self.records[path],item.isExpanded())
            if not any(char in pattern for char in '*?['):pattern='*'+pattern+'*'
            matcher=re.compile(fnmatch.translate(pattern))
            matches=set()
            for path in self.items:
                name=path.rsplit('|',1)[-1]
                if ':' not in pattern:name=name.rsplit(':',1)[-1]
                if matcher.fullmatch(name.casefold()):matches.add(path)
            visible=set(matches)
            # scope inserts parents before children. One reversed pass retains
            # ancestors in linear time even for deep chains.
            parents=set()
            for path in reversed(self.items):
                if path in visible:
                    parent=self.items[path].parent()
                    if parent is not None:
                        ancestor=parent.data(0,QtCore.Qt.UserRole)
                        visible.add(ancestor);parents.add(ancestor)
        else:visible=set(self.items);parents=set();matches=visible
        updates=self.widget.updatesEnabled();blocker=QtCore.QSignalBlocker(self.widget)
        self.widget.setUpdatesEnabled(False)
        try:
            for path,item in self.items.items():
                item.setHidden(path not in visible)
                if active and path in parents:item.setExpanded(True)
                elif not active and self._search_expanded is not None:
                    item.setExpanded(self._search_expanded.get(self.records[path],item.isExpanded()))
            if not active:self._search_expanded=None
            self.search_status.setText('{} of {} joints match{}'.format(len(matches),len(self.items),
                ' · parents shown for context' if parents else '') if matches else 'No matching joints.')
            self.search_status.setVisible(active and bool(self.items))
        finally:
            del blocker;self.widget.setUpdatesEnabled(updates)

    def scope(self,roots):
        if self.closed:return
        if isinstance(roots,str):roots=(roots,)
        roots=tuple(dict.fromkeys(roots or ()))
        selected={self.records.get(path) for path in self.joints()}
        expanded=({identity for identity,value in self._search_expanded.items() if value}
                  if self._search_expanded is not None else
                  {self.records[path] for path,item in self.items.items() if item.isExpanded()})
        previous=set(self.records.values());current=self.widget.currentItem()
        current_id=self.records.get(current.data(0,QtCore.Qt.UserRole)) if current is not None else None
        self.roots=roots;cmds=self.api.cmds;paths=set();errors=[]
        for root in roots:
            try:
                if not cmds.objExists(root):continue
                names=cmds.ls(root,long=True) or [];root=names[0] if len(names)==1 else root
                if cmds.nodeType(root)=='joint':paths.add(root)
                paths.update(cmds.listRelatives(root,allDescendents=True,type='joint',fullPath=True) or [])
            except Exception as exc:errors.append('Could not read '+root+': '+str(exc))
        paths=sorted(paths,key=lambda path:(path.count('|'),path))
        self._updating=True;blocker=QtCore.QSignalBlocker(self.widget)
        try:
            self.widget.clear();self.items={};self.records={}
            for path in paths:
                try:identity=self.api.joint_id(path)
                except RuntimeError:continue  # A joint may have been deleted since the read.
                parent_path=path.rsplit('|',1)[0]
                while parent_path and parent_path not in self.items:parent_path=parent_path.rsplit('|',1)[0]
                item=QtWidgets.QTreeWidgetItem(self.items.get(parent_path,self.widget),[path.rsplit('|',1)[-1]])
                item.setData(0,QtCore.Qt.UserRole,path);item.setToolTip(0,path);item.setIcon(0,self.icons[identity in self.locked])
                # Preserve a joint's existing Outliner text color for weighted rows.
                try:
                    if cmds.getAttr(path+'.useOutlinerColor'):
                        rgb=cmds.getAttr(path+'.outlinerColor')[0];item.setForeground(0,QtGui.QColor.fromRgbF(*rgb))
                except (AttributeError,RuntimeError,TypeError):pass
                self.items[path]=item;self.records[path]=identity
                if identity in previous:item.setExpanded(identity in expanded)
                else:
                    depth=0;ancestor=item.parent()
                    while ancestor is not None:depth+=1;ancestor=ancestor.parent()
                    item.setExpanded(depth<=2)
                if identity in selected:item.setSelected(True)
                if identity==current_id:self.widget.setCurrentItem(item,0,QtCore.QItemSelectionModel.NoUpdate)
            # Setting the current item may auto-expand its parents in Qt.
            # Restore existing branches after current/selection restoration.
            for path,item in self.items.items():
                if self.records[path] in previous:item.setExpanded(self.records[path] in expanded)
            self.empty.setText('\n'.join(errors) or ('No joints found in the skinCluster hierarchy.' if roots else 'Select a skinned mesh to show its joint hierarchy.'))
            self.empty.setVisible(not self.items);self.update_style()
            if self._search_expanded is not None:
                live=set(self.records.values());self._search_expanded={key:value for key,value in self._search_expanded.items() if key in live}
            self.filter_joints()
        finally:
            del blocker;self._updating=False;self.update_branch_action()

    def joints(self):
        if self.closed or self.widget is None:return []
        # QTreeWidget.selectedItems excludes hidden rows. Keep the paint target
        # and explicit multi-selection stable while a search hides those rows.
        items=[self.widget.itemFromIndex(index) for index in self.widget.selectionModel().selectedRows(0)]
        current=self.widget.currentItem()
        if current in items:items=[item for item in items if item is not current]+[current]
        return [item.data(0,QtCore.Qt.UserRole) for item in items]

    def select_joint(self,path):
        if self.closed:return
        if path not in self.items and self.roots:self.scope(self.roots)
        item=self.items.get(path)
        if item is None or self.joints()==[path]:return
        blocker=QtCore.QSignalBlocker(self.widget)
        self.widget.clearSelection();self.widget.setCurrentItem(item);item.setSelected(True)
        ancestor=item.parent()
        while ancestor is not None:ancestor.setExpanded(True);ancestor=ancestor.parent()
        self.widget.scrollToItem(item);del blocker
        self.update_branch_action()

    def set_layer_status(self,weighted,members,paths):
        self.weighted=set(weighted);self.members=set(members);self.known=dict(paths);self.update_style()

    def lock_rect(self,item):
        option=QtWidgets.QStyleOptionViewItem();option.initFrom(self.widget)
        option.rect=self.widget.visualItemRect(item);self.widget.itemDelegate().initStyleOption(option,self.widget.indexFromItem(item))
        option.decorationSize=self.widget.iconSize()
        rect=self.widget.style().subElementRect(QtWidgets.QStyle.SE_ItemViewItemDecoration,option,self.widget)
        return QtCore.QRect(rect.x(),rect.y(),16,rect.height())

    def set_influence_locks(self,locked,editable,callback):
        locks=set(locked);changed=locks!=self.locked or editable!=self.editable
        self.locked=locks;self.editable=editable;self.lock_changed=callback
        self.styling.status.locked=locks;self.styling.status.editable=editable
        if changed:
            for path,item in self.items.items():item.setIcon(0,self.icons[self.records[path] in locks])

    def update_style(self):
        if self.styling:
            paths=dict(self.known);paths.update(self.records)
            self.styling.update(paths,self.weighted,self.members)

    def close(self):
        if self.closed:return
        self.closed=True
        if self.widget is not None:self.widget.blockSignals(True);self.widget.hide();self.widget.deleteLater()
        if self.empty is not None:self.empty.hide();self.empty.deleteLater()
        if self.search is not None:self.search.parentWidget().hide();self.search.parentWidget().deleteLater()
        if self.search_status is not None:self.search_status.hide();self.search_status.deleteLater()
        if self.select_branch is not None:self.select_branch.hide();self.select_branch.deleteLater()
        self.search=None;self.search_status=None;self._search_expanded=None
        self.select_branch=None
        self.widget=None;self.empty=None;self.styling=None;self.guard=None
        self.items={};self.records={};self.known={};self.weighted=set();self.members=set();self.selected=None
        self.locked=set();self.lock_changed=None
