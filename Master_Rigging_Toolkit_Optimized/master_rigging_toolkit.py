# -*- coding: utf-8 -*-
"""
Optimized Maya Rigging Toolkit v2.41

Combines:
  1) Master Rigging Toolkit (Group SDK / Vertex Constraints / MiniRig Guides)
  2) Unified Rigging & Skinning Toolkit, including FK/Aim and AimAndReduce By Distance

The Unified toolkit is embedded as a tab in the PySide master window.
"""

import json
import math
import traceback
import uuid
from functools import wraps
from contextlib import contextmanager

import maya.cmds as cmds
import maya.OpenMayaUI as omui
import maya.api.OpenMaya as om

try:
    from PySide6 import QtWidgets, QtCore, QtGui
    import shiboken6 as shiboken
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui
    import shiboken2 as shiboken

# ==============================================================================
# CENTRALIZED ACTION-BASED UNDO
# ==============================================================================
# Maya tools often call many cmds.* operations for one button press.  These
# helpers make the OUTERMOST user action one undo step.  If a helper function
# starts another undo block while an action is already running, it simply joins
# the existing block instead of creating a competing nested chunk.
_TOOL_UNDO_DEPTH = 0

def _begin_tool_undo(action_name="MasterRiggingAction"):
    global _TOOL_UNDO_DEPTH
    if _TOOL_UNDO_DEPTH == 0:
        cmds.undoInfo(openChunk=True, chunkName=action_name)
    _TOOL_UNDO_DEPTH += 1

def _end_tool_undo():
    global _TOOL_UNDO_DEPTH
    if _TOOL_UNDO_DEPTH <= 0:
        _TOOL_UNDO_DEPTH = 0
        return
    _TOOL_UNDO_DEPTH -= 1
    if _TOOL_UNDO_DEPTH == 0:
        cmds.undoInfo(closeChunk=True)

def _non_undoable_cache_write(func):
    """Keep passive UI/cache bookkeeping out of Maya's scene undo history.

    If called during a real tool action, the cache update joins that action.
    Otherwise undo recording is temporarily disabled without flushing history.
    """
    @wraps(func)
    def _wrapped(*args, **kwargs):
        if _TOOL_UNDO_DEPTH > 0:
            return func(*args, **kwargs)

        undo_was_enabled = cmds.undoInfo(query=True, state=True)
        try:
            if undo_was_enabled:
                cmds.undoInfo(stateWithoutFlush=False)
            return func(*args, **kwargs)
        finally:
            if undo_was_enabled:
                cmds.undoInfo(stateWithoutFlush=True)
    return _wrapped

# ==============================================================================
# 1. SKIN WEIGHT TRANSFER LOGIC (UNDOABLE BULK MAYA COMMANDS)
# ==============================================================================
@contextmanager
def _tool_action(name):
    """One command-level undo chunk, including nested helper calls."""
    _begin_tool_undo(name)
    try:
        yield
    finally:
        _end_tool_undo()

# Constraint nodes are DAG transforms used as solvers. Their parent is organizational;
# keep their driven inputs intact and reparent relatively, never bake their outputs.
def _constraint_node(value):
    nodes=cmds.ls(value,long=True) or []
    return nodes[0] if len(nodes)==1 else None


def _constraint_uuid(node):
    values=cmds.ls(node,uuid=True) or []
    if len(values)!=1:raise ValueError('Choose one unambiguous constraint node: '+str(node))
    return values[0]


def _constraint_root(create=False):
    nodes=cmds.ls('|constraintNode',long=True) or cmds.ls('constraintNode',long=True) or []
    if len(nodes)>1:raise ValueError('Several constraintNode groups exist. Keep one unambiguous shared container, preferably |constraintNode.')
    if nodes:
        node=nodes[0]
        if cmds.nodeType(node)!='transform':raise ValueError('constraintNode must be a transform group: '+node)
        if cmds.referenceQuery(node,isNodeReferenced=True) or (cmds.lockNode(node,query=True,lock=True) or [False])[0]:
            raise ValueError('constraintNode is locked or referenced. Use an editable group.')
        return node
    if not create:return None
    node=cmds.group(empty=True,name=':constraintNode')
    cmds.addAttr(node,longName='rtkConstraintContainer',dataType='string')
    cmds.setAttr(node+'.rtkConstraintContainer','1',type='string')
    cmds.setAttr(node+'.inheritsTransform',False)
    return _constraint_node(node)


def _constraint_context(name,remember=None):
    return {'name':str(name),'node':None,'remember':remember}


def _constraint_prune():
    try:root=_constraint_root(False)
    except ValueError:return
    if not root:return
    # An existing user container is never deleted, even when empty.
    for node in cmds.listRelatives(root,children=True,fullPath=True) or []:
        if (cmds.nodeType(node)=='transform' and cmds.attributeQuery('rtkConstraintSubgroup',node=node,exists=True)
                and cmds.getAttr(node+'.rtkConstraintSubgroup')=='1'
                and not (cmds.listRelatives(node,children=True,fullPath=True) or [])
                and not (cmds.listConnections(node,source=False,destination=True,plugs=True) or [])):
            cmds.delete(node)
    if (cmds.attributeQuery('rtkConstraintContainer',node=root,exists=True)
            and cmds.getAttr(root+'.rtkConstraintContainer')=='1'
            and not (cmds.listRelatives(root,children=True,fullPath=True) or [])
            and not (cmds.listConnections(root,source=False,destination=True,plugs=True) or [])):
        cmds.delete(root)


def _constraint_delete_owned(identities):
    ranked=[]
    for identity in set(identities):
        node=_constraint_node(identity)
        if node:
            kind=cmds.nodeType(node)
            rank=0 if kind.endswith('Constraint') else 1 if kind=='ikHandle' else 2 if kind=='ikEffector' else 3
            ranked.append((rank,-node.count('|'),identity))
    for _,__,identity in sorted(ranked):
        node=_constraint_node(identity)
        if node:cmds.delete(node)
    _constraint_prune()


def _constraint_scope_group(scope):
    root=_constraint_root(True)
    if scope is None:return root
    parent=_constraint_node(scope['node']) if scope.get('node') else None
    if not parent:
        label=''.join(c if c.isascii() and (c.isalnum() or c=='_') else '_' for c in scope['name']).strip('_') or 'Rig'
        if label[0].isdigit():label='Rig_'+label
        parent=cmds.group(empty=True,name=':'+label+'_constraintNode#')
        identity=_constraint_uuid(parent);scope['node']=identity
        if scope.get('remember'):scope['remember'](parent)
        cmds.addAttr(parent,longName='rtkConstraintSubgroup',dataType='string')
        cmds.setAttr(parent+'.rtkConstraintSubgroup','1',type='string')
        cmds.setAttr(parent+'.inheritsTransform',False)
        cmds.parent(parent,root,relative=True)
        parent=_constraint_node(identity)
    return parent


def _constraint_organize(nodes,scope=None):
    identities=[_constraint_uuid(node) for node in nodes]
    if not identities:return []
    parent=_constraint_scope_group(scope);result=[]
    for identity in identities:
        node=_constraint_node(identity)
        if scope is not None and scope.get('remember'):scope['remember'](node)
        parents=cmds.listRelatives(node,parent=True,fullPath=True) or []
        if not parents or _constraint_uuid(parents[0])!=_constraint_uuid(parent):
            cmds.parent(node,parent,relative=True)
        result.append(_constraint_node(identity))
    return result


def _constraint_command(command,*args,**kwargs):
    """Create and group a solver; query/edit calls retain Maya's native behavior."""
    scope=kwargs.pop('_scope',None)
    native=getattr(cmds,command)
    if any(kwargs.get(flag) for flag in ('query','q','edit','e')):
        return native(*args,**kwargs)
    _constraint_root(False)
    nodes=native(*args,**kwargs) or []
    identities=[_constraint_uuid(node) for node in nodes]
    previous=scope.get('node') if scope is not None else None
    try:return _constraint_organize(nodes,scope)
    except Exception:
        fresh=[scope['node']] if scope is not None and scope.get('node') and scope['node']!=previous else []
        _constraint_delete_owned(identities+fresh)
        if fresh:scope['node']=previous
        raise


def _read_scene_cache(node, attribute):
    if not cmds.objExists(node) or not cmds.attributeQuery(attribute, node=node, exists=True):
        return []
    raw = cmds.getAttr("{}.{}".format(node, attribute))
    rows = json.loads(raw or "[]")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Expected a JSON list of setup objects.")
    return rows

@_non_undoable_cache_write
def _write_scene_cache(node, attribute, rows):
    """Keep existing cache node types; new caches need no DAG transform."""
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    exists = cmds.objExists(node)
    has_attr = exists and cmds.attributeQuery(attribute, node=node, exists=True)
    if has_attr and cmds.getAttr("{}.{}".format(node, attribute)) == payload:
        return False
    if not exists:
        cmds.createNode("network", name=node, skipSelect=True)
    if not has_attr:
        cmds.addAttr(node, longName=attribute, dataType="string")
    cmds.setAttr("{}.{}".format(node, attribute), payload, type="string")
    return True

def _set_button_role(button, role):
    button.setProperty("role", role)
    button.style().unpolish(button)
    button.style().polish(button)

def _polish_native_panel(panel):
    """Style PySide controls once per page; keep Maya custom controls intact."""
    panel.setProperty("qtPanel", True)
    destructive = ("remove", "delete", "wipe", "clean all")
    primary = ("execute", "generate", "apply", "snap")
    for button in panel.findChildren(QtWidgets.QPushButton):
        button.setAutoDefault(False)
        button.setDefault(False)
        text = button.text().lower().strip()
        if text.startswith(destructive):
            _set_button_role(button, "danger")
        elif text.startswith(primary):
            _set_button_role(button, "primary")
        if "load" in text or text == "<<":
            button.setToolTip("Fill this field from the current Maya selection.")
            if text == "<<":
                button.setText("Sel")
                button.setMinimumWidth(38)
                button.setMaximumWidth(48)
    for spin in panel.findChildren(QtWidgets.QAbstractSpinBox):
        spin.setKeyboardTracking(False)
    for form in panel.findChildren(QtWidgets.QFormLayout):
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

TOOLKIT_STYLE = """
QDialog#MasterRiggingToolkit { background: #202329; color: #e4e8ee; }
QDialog#MasterRiggingToolkit QWidget { color: #e4e8ee; font-size: 12px; }
QDialog#MasterRiggingToolkit QLabel[role="muted"] { color: #949dab; }
QDialog#MasterRiggingToolkit QLabel#ToolkitTitle { font-size: 19px; font-weight: 600; }
QDialog#MasterRiggingToolkit QLabel#PageTitle { font-size: 16px; font-weight: 600; }
QDialog#MasterRiggingToolkit QFrame#Sidebar { background: #191c21; border-radius: 8px; }
QDialog#MasterRiggingToolkit QListWidget#Navigation { background: transparent; border: none; outline: none; }
QDialog#MasterRiggingToolkit QListWidget#Navigation::item { padding: 10px 9px; border-radius: 5px; margin: 2px 4px; }
QDialog#MasterRiggingToolkit QListWidget#Navigation::item:selected { background: #29483e; color: #b4efd4; }
QDialog#MasterRiggingToolkit QListWidget#Navigation::item:hover { background: #30363f; }
QDialog#MasterRiggingToolkit QFrame#SDKCard,
QDialog#MasterRiggingToolkit QFrame#VertexCard { background: #282d34; border: 1px solid #3b424c; border-radius: 7px; }
QDialog#MasterRiggingToolkit QGroupBox { border: 1px solid #3b424c; border-radius: 7px; margin-top: 15px; padding: 16px 10px 10px; font-weight: 600; }
QDialog#MasterRiggingToolkit QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QDialog#MasterRiggingToolkit QWidget#ModularRigPage { background: #202329; }
QDialog#MasterRiggingToolkit QWidget#RigConnectionsPage { background: #202329; }
QDialog#MasterRiggingToolkit QTabWidget#RigModuleTabs::pane { background: #202329; border: 1px solid #3b424c; }
QDialog#MasterRiggingToolkit QTabWidget#RigModuleTabs QTabBar::tab { background: #282d34; padding: 8px 18px; border: 1px solid #3b424c; }
QDialog#MasterRiggingToolkit QTabWidget#RigModuleTabs QTabBar::tab:selected { background: #365949; color: #d7f5e7; }
QDialog#MasterRiggingToolkit QPlainTextEdit#RigConnectionIssues { background: #23282f; border: 1px solid #414a57; }
QDialog#MasterRiggingToolkit QWidget#WaveJointsPage { background: #202329; }
QDialog#MasterRiggingToolkit QListWidget#WaveJointList { background: #1c2026; border: 1px solid #414a57; border-radius: 4px; selection-background-color: #365949; }
QDialog#MasterRiggingToolkit QListWidget#WaveJointList::item { padding: 3px 5px; }
QDialog#MasterRiggingToolkit QWidget#WaveJointsPage QAbstractSpinBox:disabled { color: #7a818c; background: #292e35; border-color: #343b44; }
QDialog#MasterRiggingToolkit QWidget#JointCleanupPage { background: #202329; }
QDialog#MasterRiggingToolkit QGroupBox#JointCleanupInputs { background: #282d34; }
QDialog#MasterRiggingToolkit QListWidget#JointCleanupMeshes { background: #1c2026; border: 1px solid #414a57; border-radius: 4px; selection-background-color: #365949; }
QDialog#MasterRiggingToolkit QFrame#RigModuleGroup { background: #282d34; border: 1px solid #3b424c; border-radius: 6px; }
QDialog#MasterRiggingToolkit QWidget#RigModuleBody { background: #282d34; }
QDialog#MasterRiggingToolkit QToolButton#RigModuleHeader { background: #282d34; border: none; border-radius: 5px; padding: 6px 10px; min-height: 18px; font-weight: 600; }
QDialog#MasterRiggingToolkit QToolButton#RigModuleHeader:hover { background: #343c46; }
QDialog#MasterRiggingToolkit QToolButton#RigModuleHeader:checked { color: #b4efd4; }
QDialog#MasterRiggingToolkit QPushButton { background: #353c46; border: 1px solid #48515e; border-radius: 5px; }
QDialog#MasterRiggingToolkit QWidget[qtPanel="true"] QPushButton { padding: 5px 10px; min-height: 22px; }
QDialog#MasterRiggingToolkit QPushButton:hover { background: #424c59; border-color: #7b899b; }
QDialog#MasterRiggingToolkit QPushButton:pressed { background: #262d36; }
QDialog#MasterRiggingToolkit QPushButton[role="primary"] { background: #285344; border-color: #40745f; color: #d7f5e7; font-weight: 600; }
QDialog#MasterRiggingToolkit QPushButton[role="danger"] { background: #4d3035; border-color: #795059; color: #ffcdd3; }
QDialog#MasterRiggingToolkit QPushButton:disabled { color: #7a818c; background: #292e35; border-color: #343b44; }
QDialog#MasterRiggingToolkit QLineEdit,
QDialog#MasterRiggingToolkit QComboBox,
QDialog#MasterRiggingToolkit QAbstractSpinBox { background: #1c2026; border: 1px solid #414a57; border-radius: 4px; selection-background-color: #3c715e; }
QDialog#MasterRiggingToolkit QWidget[qtPanel="true"] QLineEdit,
QDialog#MasterRiggingToolkit QWidget[qtPanel="true"] QComboBox,
QDialog#MasterRiggingToolkit QWidget[qtPanel="true"] QAbstractSpinBox,
QDialog#MasterRiggingToolkit QLineEdit#ToolSearch { min-height: 25px; padding: 2px 6px; }
QDialog#MasterRiggingToolkit QLineEdit:focus,
QDialog#MasterRiggingToolkit QComboBox:focus,
QDialog#MasterRiggingToolkit QAbstractSpinBox:focus { border-color: #72ad97; }
QDialog#MasterRiggingToolkit QLineEdit:disabled { color: #7a818c; background: #292e35; }
QDialog#MasterRiggingToolkit QComboBox QAbstractItemView { background: #282d34; selection-background-color: #365949; }
QDialog#MasterRiggingToolkit QScrollArea { background: transparent; border: none; }
QDialog#MasterRiggingToolkit QScrollBar:vertical { background: #202329; width: 10px; margin: 0; }
QDialog#MasterRiggingToolkit QScrollBar::handle:vertical { background: #505a68; border-radius: 4px; min-height: 24px; }
QDialog#MasterRiggingToolkit QScrollBar::add-line:vertical,
QDialog#MasterRiggingToolkit QScrollBar::sub-line:vertical { height: 0; }
QDialog#MasterRiggingToolkit QCheckBox { spacing: 7px; }
QDialog#MasterRiggingToolkit QTreeWidget { background: #23282f; alternate-background-color: #292f37; border: 1px solid #414a57; border-radius: 5px; selection-background-color: #365949; }
QDialog#MasterRiggingToolkit QTableWidget#RigModuleRows,
QDialog#MasterRiggingToolkit QTableWidget#RigModuleOutputs { background: #23282f; alternate-background-color: #292f37; gridline-color: #414a57; border: 1px solid #414a57; selection-background-color: #365949; }
QDialog#MasterRiggingToolkit QHeaderView::section { background: #353c46; padding: 6px; border: none; border-right: 1px solid #48515e; }
"""

def transfer_namespace_weights(mesh, src_ns="B", tgt_ns="A", remove_src=True):
    """Move complete influence columns with Maya's undoable bulk command.

    The original version indexed dense weights with sparse logical indices and
    wrote through MFnSkinCluster, which does not create command-level undo.
    Native skinPercent avoids both errors and the Python vertex/influence loop.
    """
    src_ns = (src_ns or "").strip().strip(":")
    tgt_ns = (tgt_ns or "").strip().strip(":")
    if not src_ns or not tgt_ns or src_ns == tgt_ns:
        cmds.warning("Enter two different, non-empty namespaces.")
        return
    matches = cmds.ls(mesh, long=True) or []
    if len(matches) != 1 or "." in mesh:
        cmds.warning("Choose one unambiguous polygon mesh, not components.")
        return
    mesh = matches[0]
    if cmds.nodeType(mesh) == "transform":
        shapes = cmds.listRelatives(mesh, shapes=True, noIntermediate=True, type="mesh", fullPath=True) or []
    elif cmds.nodeType(mesh) == "mesh":
        shapes = [mesh]
    else:
        shapes = []
    if len(shapes) != 1:
        cmds.warning("The target must contain exactly one non-intermediate polygon mesh.")
        return
    shape = shapes[0]
    skins = list(dict.fromkeys(cmds.ls(cmds.listHistory(shape, pdo=True) or [], type="skinCluster") or []))
    if len(skins) != 1:
        cmds.warning("Expected one skinCluster on '{}'; found {}.".format(mesh, len(skins)))
        return
    skin = skins[0]
    all_infs = cmds.skinCluster(skin, query=True, influence=True) or []
    current = set()
    for inf in all_infs:
        current.update(cmds.ls(inf, long=True) or [])
    pairs = []
    for inf in all_infs:
        source_matches = cmds.ls(inf, long=True) or []
        if len(source_matches) != 1:
            cmds.warning("Ambiguous source influence '{}'. Transfer cancelled.".format(inf))
            return
        source = source_matches[0]
        leaf = source.rsplit("|", 1)[-1]
        prefix = src_ns + ":"
        if not leaf.startswith(prefix):
            continue
        target_name = tgt_ns + ":" + leaf[len(prefix):]
        targets = cmds.ls(target_name, long=True) or []
        targets = [node for node in targets if cmds.objectType(node, isAType="transform")]
        if len(targets) != 1:
            cmds.warning("Target '{}' is missing or ambiguous; skipping '{}'.".format(target_name, source))
            continue
        target = targets[0]
        for influence in (source, target):
            if (cmds.attributeQuery("liw", node=influence, exists=True)
                    and cmds.getAttr(influence + ".liw")):
                cmds.warning("Unlock skin weights on '{}' before transferring. No changes made.".format(influence))
                return
        pairs.append((source, target))
    if not pairs:
        cmds.warning("No influence pairs found for '{}:' → '{}:'.".format(src_ns, tgt_ns))
        return

    with _tool_action("TransferSkinWeights"):
        for _source, target in pairs:
            if target not in current:
                cmds.skinCluster(skin, edit=True, addInfluence=target, weight=0.0, lockWeights=False)
                current.add(target)
        components = shape + ".vtx[*]"
        for source, target in pairs:
            cmds.skinPercent(skin, components, transformMoveWeights=[source, target], normalize=False)
        if remove_src:
            for source, _target in pairs:
                cmds.skinCluster(skin, edit=True, removeInfluence=source)
    print("Transferred {} influence pair(s) from '{}' to '{}' on '{}'.".format(len(pairs), src_ns, tgt_ns, mesh))
    return {"skin_cluster": skin, "pairs": pairs, "removed_source": bool(remove_src)}

# ==============================================================================
# 2. CONTROLLER MIRROR LOGIC
# ==============================================================================
def copy_color_override(src_ctrl, tgt_ctrl):
    src_shapes = cmds.listRelatives(src_ctrl, shapes=True, type='nurbsCurve', noIntermediate=True) or []
    tgt_shapes = cmds.listRelatives(tgt_ctrl, shapes=True, type='nurbsCurve', noIntermediate=True) or []

    if not src_shapes or not tgt_shapes:
        return

    first_src = src_shapes[0]
    enabled = cmds.getAttr(f"{first_src}.overrideEnabled")

    for t_shape in tgt_shapes:
        if not enabled:
            cmds.setAttr(f"{t_shape}.overrideEnabled", 0)
            continue

        cmds.setAttr(f"{t_shape}.overrideEnabled", 1)
        is_rgb = cmds.getAttr(f"{first_src}.overrideRGBColors")
        cmds.setAttr(f"{t_shape}.overrideRGBColors", is_rgb)

        if is_rgb:
            rgb_val = cmds.getAttr(f"{first_src}.overrideColorRGB")[0]
            cmds.setAttr(f"{t_shape}.overrideColorRGB", rgb_val[0], rgb_val[1], rgb_val[2])
        else:
            idx_val = cmds.getAttr(f"{first_src}.overrideColor")
            cmds.setAttr(f"{t_shape}.overrideColor", idx_val)

def mirror_ctrl_shape(src_ctrl, tgt_ctrl, force_recreate=False, match_color=False):
    if not cmds.objExists(src_ctrl) or not cmds.objExists(tgt_ctrl):
        return False

    src_shapes = cmds.listRelatives(src_ctrl, shapes=True, type='nurbsCurve', noIntermediate=True) or []
    tgt_shapes = cmds.listRelatives(tgt_ctrl, shapes=True, type='nurbsCurve', noIntermediate=True) or []

    if not src_shapes:
        cmds.warning(f"No NURBS curve shapes found on source '{src_ctrl}'.")
        return False

    topology_matches = (len(src_shapes) == len(tgt_shapes)) and not force_recreate
    if topology_matches:
        for s_shape, t_shape in zip(src_shapes, tgt_shapes):
            s_cvs = cmds.ls(f"{s_shape}.cv[*]", flatten=True) or []
            t_cvs = cmds.ls(f"{t_shape}.cv[*]", flatten=True) or []
            if len(s_cvs) != len(t_cvs):
                topology_matches = False
                break

    if topology_matches:
        for s_shape, t_shape in zip(src_shapes, tgt_shapes):
            s_cvs = cmds.ls(f"{s_shape}.cv[*]", flatten=True) or []
            t_cvs = cmds.ls(f"{t_shape}.cv[*]", flatten=True) or []
            for s_cv, t_cv in zip(s_cvs, t_cvs):
                pos = cmds.xform(s_cv, query=True, worldSpace=True, translation=True)
                mirrored_pos = [-pos[0], pos[1], pos[2]]
                cmds.xform(t_cv, worldSpace=True, translation=mirrored_pos)

        if match_color:
            copy_color_override(src_ctrl, tgt_ctrl)

        return True
    else:
        return _recreate_and_mirror_shapes(src_ctrl, tgt_ctrl, match_color)

def _recreate_and_mirror_shapes(src_ctrl, tgt_ctrl, match_color=False):
    tgt_shapes = cmds.listRelatives(tgt_ctrl, shapes=True, type='nurbsCurve', noIntermediate=True) or []
    color_override = None
    if not match_color and tgt_shapes and cmds.getAttr(f"{tgt_shapes[0]}.overrideEnabled"):
        color_override = cmds.getAttr(f"{tgt_shapes[0]}.overrideColor")

    temp_dup = cmds.duplicate(src_ctrl, rc=True)[0]
    children = cmds.listRelatives(temp_dup, children=True, fullPath=True) or []
    for child in children:
        if cmds.nodeType(child) != 'nurbsCurve':
            cmds.delete(child)

    temp_grp = cmds.group(temp_dup, name="temp_mirror_grp#")
    cmds.xform(temp_grp, worldSpace=True, pvt=[0, 0, 0])
    cmds.setAttr(f"{temp_grp}.scaleX", -1)
    cmds.makeIdentity(temp_dup, apply=True, t=True, r=True, s=True, normal=False)

    cmds.parent(temp_dup, tgt_ctrl)
    cmds.makeIdentity(temp_dup, apply=True, t=True, r=True, s=True, normal=False)

    if tgt_shapes:
        cmds.delete(tgt_shapes)

    new_shapes = cmds.listRelatives(temp_dup, shapes=True, fullPath=True) or []
    for shape in new_shapes:
        cmds.parent(shape, tgt_ctrl, shape=True, relative=True)

    cmds.delete(temp_dup)
    if cmds.objExists(temp_grp):
        cmds.delete(temp_grp)

    if match_color:
        copy_color_override(src_ctrl, tgt_ctrl)
    elif color_override is not None:
        updated_shapes = cmds.listRelatives(tgt_ctrl, shapes=True, type='nurbsCurve') or []
        for s in updated_shapes:
            cmds.setAttr(f"{s}.overrideEnabled", 1)
            cmds.setAttr(f"{s}.overrideColor", color_override)

    return True

# ==============================================================================
# 3. UTILITIES LOGIC
# ==============================================================================
def swap_and_suffix_old(hide_shape=False):
    selection = cmds.ls(sl=True)
    if len(selection) != 2:
        cmds.warning("Please select exactly 2 objects in order: [1st] Old Object, [2nd] Replacement Object.")
        return

    src_obj, tgt_obj = selection[0], selection[1]

    orig_src_name = src_obj.split('|')[-1]
    new_src_name = f"{orig_src_name}_old"

    _begin_tool_undo("SwapNameAndSuffixOld")
    try:
        renamed_src = cmds.rename(src_obj, new_src_name)
        renamed_tgt = cmds.rename(tgt_obj, orig_src_name)

        if hide_shape:
            shapes = cmds.listRelatives(renamed_src, shapes=True, fullPath=True) or []
            for s in shapes:
                cmds.setAttr(f"{s}.visibility", 0)

        cmds.select([renamed_src, renamed_tgt])
        print(f"Successfully renamed:\n  • '{src_obj}' -> '{renamed_src}'\n  • '{tgt_obj}' -> '{renamed_tgt}'")

    finally:
        _end_tool_undo()

def rename_remove_suffix_from_selection(suffix):
    selection = cmds.ls(sl=True, long=True) or []

    if not selection:
        cmds.warning("Please select at least one object.")
        return []

    suffix = (suffix or "").strip()

    if not suffix:
        cmds.warning("Please enter a suffix to remove.")
        return []

    selection.sort(key=lambda x: x.count("|"), reverse=True)

    renamed = []
    skipped = []

    _begin_tool_undo("RemoveSuffix")
    try:
        for node in selection:
            if not cmds.objExists(node):
                skipped.append(f"{node} (no longer exists at original path)")
                continue

            short_name = node.split("|")[-1]

            if not short_name.endswith(suffix):
                skipped.append(f"{short_name} (suffix not found)")
                continue

            new_name = short_name[:-len(suffix)]

            if not new_name:
                skipped.append(f"{short_name} (empty result)")
                continue

            try:
                renamed_node = cmds.rename(node, new_name)
                renamed.append((short_name, renamed_node))
            except Exception as e:
                skipped.append(f"{short_name} ({e})")

        if renamed:
            valid_nodes = [
                new_name
                for _, new_name in renamed
                if cmds.objExists(new_name)
            ]
            if valid_nodes:
                cmds.select(valid_nodes, replace=True)

        print("=" * 60)
        print(
            f"REMOVE SUFFIX: '{suffix}' | "
            f"Selected: {len(selection)} | "
            f"Renamed: {len(renamed)} | "
            f"Skipped: {len(skipped)}"
        )

        return renamed

    finally:
        _end_tool_undo()

def collect_constraints_under_hierarchy(root_node=None, target_grp="constraintNode"):
    if not root_node:
        sel = cmds.ls(sl=True, long=True)
        if not sel:
            cmds.warning("Please select a root hierarchy node or specify one.")
            return []
        root_node = sel[0]

    if not cmds.objExists(root_node):
        cmds.warning(f"Root object '{root_node}' does not exist.")
        return []

    constraint_types = [
        'parentConstraint', 'pointConstraint', 'orientConstraint',
        'scaleConstraint', 'aimConstraint', 'poleVectorConstraint',
        'geometryConstraint', 'normalConstraint', 'tangentConstraint'
    ]

    all_children = cmds.listRelatives(root_node, allDescendents=True, fullPath=True) or []
    all_nodes = all_children + cmds.ls(root_node, long=True)

    found_constraints = [
        node for node in all_nodes
        if cmds.nodeType(node) in constraint_types or 'Constraint' in cmds.nodeType(node)
    ]

    if not found_constraints:
        cmds.warning(f"No constraint nodes found under hierarchy '{root_node}'.")
        return []

    moved_constraints = []
    _begin_tool_undo("CollectConstraints")
    try:
        # Group creation belongs to the same user action as the reparenting.
        if not cmds.objExists(target_grp):
            target_grp = cmds.group(empty=True, name=target_grp)

        for const in found_constraints:
            parents = cmds.listRelatives(const, parent=True, fullPath=True)
            if parents:
                parent_short = parents[0].split('|')[-1]
                target_short = target_grp.split('|')[-1]
                if parent_short == target_short:
                    continue

            try:
                reparented = cmds.parent(const, target_grp, relative=True)
                moved_constraints.append(reparented[0])
            except Exception as e:
                print(f"Could not parent constraint '{const}': {e}")

        print(f"Moved {len(moved_constraints)} constraint node(s) under '{target_grp}'.")
        return moved_constraints

    finally:
        _end_tool_undo()

# ==============================================================================
# 4. UNIFIED TOOLKIT UI CLASS
# ==============================================================================
class UnifiedRiggingToolkitUI(object):
    WINDOW_NAME = "UnifiedRiggingToolkitWin"

    def __init__(self):
        self.fk_chains_data = []
        self.aim_setups_data = []
        self.aim_distance_setups_data = []
        self.create_ui()

    def create_ui(self):
        if cmds.window(self.WINDOW_NAME, exists=True):
            cmds.deleteUI(self.WINDOW_NAME)

        self.win = cmds.window(
            self.WINDOW_NAME,
            title="Maya Rigging & Skinning Toolkit",
            widthHeight=(410, 720),
            sizeable=True
        )

        main_layout = cmds.columnLayout(adjustableColumn=True)
        self.tabs = cmds.tabLayout(innerMarginWidth=5, innerMarginHeight=5)

        # TAB 1: Auto Controller
        tab1 = cmds.columnLayout(adjustableColumn=True, rowSpacing=10, columnOffset=["both", 10])
        self.build_controller_tab(tab1)
        cmds.setParent('..')

        # TAB 2: Mirror Shapes
        tab2 = cmds.columnLayout(adjustableColumn=True, rowSpacing=10, columnOffset=["both", 10])
        self.build_mirror_tab(tab2)
        cmds.setParent('..')

        # TAB 3: Weight Transfer
        tab3 = cmds.columnLayout(adjustableColumn=True, rowSpacing=10, columnOffset=["both", 10])
        self.build_weight_tab(tab3)
        cmds.setParent('..')

        # TAB 4: Naming & Utils
        tab4 = cmds.columnLayout(adjustableColumn=True, rowSpacing=10, columnOffset=["both", 10])
        self.build_utils_tab(tab4)
        cmds.setParent('..')

        # TAB 5: FK & Aim Utils
        tab5 = cmds.columnLayout(adjustableColumn=True, rowSpacing=10, columnOffset=["both", 10])
        self.build_fk_aim_tab(tab5)
        cmds.setParent('..')

        cmds.tabLayout(
            self.tabs,
            edit=True,
            tabLabel=[
                (tab1, 'Auto Controller'),
                (tab2, 'Mirror Shapes'),
                (tab3, 'Weight Transfer'),
                (tab4, 'Naming Utils'),
                (tab5, 'FK & Aim Utils')
            ]
        )

        cmds.showWindow(self.win)

    # --------------------------------------------------------------------------
    # TAB 1: Auto Controller Builder
    # --------------------------------------------------------------------------
    def build_controller_tab(self, parent):
        cmds.separator(height=6, style='none')
        cmds.text(label="Auto Controller Generator", font="boldLabelFont", align="center")
        cmds.separator(height=6, style='single')

        cmds.frameLayout(label=" Control Settings ", marginWidth=8, marginHeight=8)

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[120, 200], adjustableColumn=2)
        cmds.text(label="Control Shape:")
        self.shape_menu = cmds.optionMenu()
        cmds.menuItem(label="Circle (X-Axis)")
        cmds.menuItem(label="Circle (Y-Axis)")
        cmds.menuItem(label="Circle (Z-Axis)")
        cmds.menuItem(label="Cube")
        cmds.menuItem(label="Sphere")
        cmds.menuItem(label="Square")
        cmds.setParent('..')

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[120, 200], adjustableColumn=2)
        cmds.text(label="Control Size:")
        self.size_field = cmds.floatField(value=3.0, minValue=0.001, precision=3)
        cmds.setParent('..')

        # Circle-only settings. Hidden automatically for non-circle shapes.
        self.circle_options_row = cmds.rowLayout(
            numberOfColumns=4,
            columnWidth4=[120, 65, 70, 105],
            adjustableColumn=4
        )
        cmds.text(label="Circle Sections:")
        self.circle_sections_field = cmds.intField(
            value=8,
            minValue=3,
            maxValue=128
        )
        cmds.text(label="Degree:")
        self.circle_degree_menu = cmds.optionMenu()
        cmds.menuItem(label="Cubic")
        cmds.menuItem(label="Linear")
        cmds.setParent('..')

        # RGB color control + explicit Maya color editor button.
        self.color_slider = cmds.colorSliderGrp(
            label="Control Color:",
            rgb=(1.0, 1.0, 0.0),
            columnWidth3=[120, 65, 135],
            adjustableColumn=3
        )

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[120, 200], adjustableColumn=2)
        cmds.text(label="")
        self.color_wheel_btn = cmds.button(
            label="Open Color Wheel...",
            command=self.open_ctrl_color_picker
        )
        cmds.setParent('..')

        # Shape changes control whether Circle-specific options are shown.
        cmds.optionMenu(
            self.shape_menu,
            edit=True,
            changeCommand=self.update_circle_shape_options
        )
        self.update_circle_shape_options()

        cmds.setParent('..')

        cmds.frameLayout(label=" Hierarchy Attachments (Optional) ", marginWidth=8, marginHeight=8)

        cmds.rowLayout(numberOfColumns=3, columnWidth3=[80, 170, 70], adjustableColumn=2)
        cmds.text(label="Parent:")
        self.parent_obj_field = cmds.textField(placeholderText="Attach root control under...")
        cmds.button(label="Get Sel", command=self.populate_parent_obj)
        cmds.setParent('..')

        cmds.rowLayout(numberOfColumns=3, columnWidth3=[80, 170, 70], adjustableColumn=2)
        cmds.text(label="Child:")
        self.child_obj_field = cmds.textField(placeholderText="Attach object under ctrl...")
        cmds.button(label="Get Sel", command=self.populate_child_obj)
        cmds.setParent('..')
        cmds.setParent('..')

        cmds.frameLayout(label=" Constraint & Hierarchy Options ", marginWidth=8, marginHeight=8)
        self.constraint_cb = cmds.checkBox(label="Create Parent Constraint (Ctrl -> Joint)", value=True)
        self.scale_cb = cmds.checkBox(label="Add Scale Constraint", value=False)
        self.hierarchy_cb = cmds.checkBox(label="Maintain Controller Hierarchy", value=True)
        cmds.setParent('..')

        cmds.frameLayout(label=" Constraint Organization ", marginWidth=8, marginHeight=8)
        self.use_grp_cb = cmds.checkBox(label="Use custom constraint subgroup", value=True)
        cmds.rowLayout(numberOfColumns=3, columnWidth3=[80, 170, 70], adjustableColumn=2)
        cmds.text(label="Group Name:")
        self.grp_name_field = cmds.textField(text="Controllers")
        cmds.button(label="Get Sel", command=self.populate_grp_from_sel)
        cmds.setParent('..')
        cmds.setParent('..')

        cmds.button(
            label="Generate Controllers for Selected",
            height=36,
            backgroundColor=[0.2, 0.5, 0.4],
            command=self.run_generator
        )

        # --------------------------------------------------------------
        # Add Controller To Layer
        # --------------------------------------------------------------
        cmds.separator(height=8, style='none')
        cmds.frameLayout(
            label=" Add Controller To Layer ",
            marginWidth=8,
            marginHeight=8
        )

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[120, 220], adjustableColumn=2)
        cmds.text(label="Controller Set:")
        cmds.text(label="ControlSet", align="left")
        cmds.setParent('..')

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[120, 220], adjustableColumn=2)
        cmds.text(label="Display Layer:")
        cmds.text(label="AllControllers", align="left")
        cmds.setParent('..')

        cmds.text(
            label=(
                "Any transform in ControlSet that owns a non-intermediate shape "
                "is treated as a controller."
            ),
            align="left",
            wordWrap=True
        )

        cmds.button(
            label="Add ControlSet Controllers To AllControllers",
            height=32,
            backgroundColor=[0.25, 0.45, 0.55],
            command=self.add_controllers_to_layer
        )
        cmds.setParent('..')

    def populate_parent_obj(self, *args):
        sel = cmds.ls(sl=True, type='transform')
        if sel:
            cmds.textField(self.parent_obj_field, edit=True, text=sel[0])

    def populate_child_obj(self, *args):
        sel = cmds.ls(sl=True, type='transform')
        if sel:
            cmds.textField(self.child_obj_field, edit=True, text=sel[0])

    def populate_grp_from_sel(self, *args):
        sel = cmds.ls(sl=True, type='transform')
        if sel:
            cmds.textField(self.grp_name_field, edit=True, text=sel[0])

    def update_circle_shape_options(self, *args):
        """Show Circle-specific settings only when a Circle shape is selected."""
        shape_type = cmds.optionMenu(self.shape_menu, query=True, value=True)
        is_circle = shape_type.startswith("Circle (")
        if hasattr(self, 'circle_options_row') and cmds.layout(self.circle_options_row, exists=True):
            cmds.rowLayout(
                self.circle_options_row,
                edit=True,
                visible=is_circle,
                manage=is_circle
            )

    def open_ctrl_color_picker(self, *args):
        """Open Maya's color editor and push the chosen RGB back into the UI."""
        current_rgb = cmds.colorSliderGrp(
            self.color_slider,
            query=True,
            rgb=True
        )
        cmds.colorEditor(rgbValue=current_rgb)
        if cmds.colorEditor(query=True, result=True):
            rgb = cmds.colorEditor(query=True, rgb=True)
            cmds.colorSliderGrp(
                self.color_slider,
                edit=True,
                rgb=rgb
            )

    def create_ctrl_shape(self, shape_type, size, name, circle_sections=8, circle_degree=3):
        if shape_type == "Circle (X-Axis)":
            return cmds.circle(
                normal=(1, 0, 0), radius=size,
                degree=circle_degree, sections=circle_sections,
                name=name, constructionHistory=False
            )[0]
        elif shape_type == "Circle (Y-Axis)":
            return cmds.circle(
                normal=(0, 1, 0), radius=size,
                degree=circle_degree, sections=circle_sections,
                name=name, constructionHistory=False
            )[0]
        elif shape_type == "Circle (Z-Axis)":
            return cmds.circle(
                normal=(0, 0, 1), radius=size,
                degree=circle_degree, sections=circle_sections,
                name=name, constructionHistory=False
            )[0]
        elif shape_type == "Square":
            return cmds.circle(normal=(0, 1, 0), radius=size, degree=1, sections=4, name=name, constructionHistory=False)[0]
        elif shape_type == "Cube":
            s = size / 2.0
            points = [
                (-s, s, s), (s, s, s), (s, -s, s), (-s, -s, s), (-s, s, s),
                (-s, s, -s), (s, s, -s), (s, -s, -s), (-s, -s, -s), (-s, s, -s),
                (-s, -s, -s), (-s, -s, s), (s, -s, s), (s, -s, -s), (s, s, -s), (s, s, s)
            ]
            return cmds.curve(degree=1, point=points, name=name)
        elif shape_type == "Sphere":
            c1 = cmds.circle(normal=(1, 0, 0), radius=size, constructionHistory=False)[0]
            c2 = cmds.circle(normal=(0, 1, 0), radius=size, constructionHistory=False)[0]
            c3 = cmds.circle(normal=(0, 0, 1), radius=size, constructionHistory=False)[0]
            shapes = cmds.listRelatives(c2, shapes=True) + cmds.listRelatives(c3, shapes=True)
            cmds.parent(shapes, c1, relative=True, shape=True)
            cmds.delete(c2, c3)
            return cmds.rename(c1, name)

    def set_ctrl_color(self, obj, color_rgb):
        """Apply the selected RGB override color to all controller curve shapes."""
        shapes = cmds.listRelatives(obj, shapes=True, fullPath=True) or []
        r, g, b = color_rgb
        for shape in shapes:
            cmds.setAttr(f"{shape}.overrideEnabled", 1)
            cmds.setAttr(f"{shape}.overrideRGBColors", 1)
            cmds.setAttr(f"{shape}.overrideColorRGB", r, g, b)

    def _collect_set_members_recursive(self, set_name, visited=None):
        """Return members of an objectSet, expanding nested sets safely."""
        if visited is None:
            visited = set()

        if set_name in visited:
            return []
        visited.add(set_name)

        members = cmds.sets(set_name, query=True) or []
        result = []

        for member in members:
            # Nested objectSet: recurse instead of treating the set node as a controller.
            try:
                if cmds.objExists(member) and cmds.nodeType(member) == "objectSet":
                    result.extend(self._collect_set_members_recursive(member, visited))
                    continue
            except Exception:
                pass

            result.append(member)

        return result

    def _as_controller_transform(self, member):
        """Return a transform only when it directly owns a real shape."""
        if not member or "." in member:
            # Components are not controller transforms.
            return None

        if not cmds.objExists(member):
            return None

        try:
            node_type = cmds.nodeType(member)
        except Exception:
            return None

        transform = None

        if node_type == "transform":
            transform = member
        elif cmds.objectType(member, isAType="shape"):
            parents = cmds.listRelatives(member, parent=True, fullPath=True) or []
            if parents:
                transform = parents[0]

        if not transform or not cmds.objExists(transform):
            return None

        shapes = cmds.listRelatives(
            transform,
            shapes=True,
            noIntermediate=True,
            fullPath=True
        ) or []

        return transform if shapes else None

    def add_controllers_to_layer(self, *args):
        """Add controller transforms from ControlSet to the AllControllers display layer."""
        source_set = "ControlSet"
        layer_name = "AllControllers"

        if not cmds.objExists(source_set) or cmds.nodeType(source_set) != "objectSet":
            cmds.warning(
                "Controller set '{}' does not exist or is not an objectSet.".format(source_set)
            )
            return

        members = self._collect_set_members_recursive(source_set)

        controllers = []
        seen = set()
        for member in members:
            ctrl = self._as_controller_transform(member)
            if not ctrl:
                continue

            long_names = cmds.ls(ctrl, long=True) or [ctrl]
            ctrl = long_names[0]
            if ctrl not in seen:
                seen.add(ctrl)
                controllers.append(ctrl)

        if not controllers:
            cmds.warning(
                "No controller transforms with their own shapes were found in '{}'.".format(
                    source_set
                )
            )
            return

        _begin_tool_undo("AddControllersToLayer")
        try:
            if cmds.objExists(layer_name):
                if cmds.nodeType(layer_name) != "displayLayer":
                    cmds.warning(
                        "A node named '{}' already exists, but it is not a display layer.".format(
                            layer_name
                        )
                    )
                    return
            else:
                cmds.createDisplayLayer(
                    name=layer_name,
                    empty=True
                )

            cmds.editDisplayLayerMembers(
                layer_name,
                controllers,
                noRecurse=True
            )

            print(
                "Added {} controller(s) from '{}' to display layer '{}'.".format(
                    len(controllers), source_set, layer_name
                )
            )
        finally:
            _end_tool_undo()

    def clean_joint_name(self, jnt_name):
        short_name = jnt_name.split('|')[-1]
        for sfx in ["_jnt", "_JNT", "_joint", "_JOINT"]:
            if short_name.endswith(sfx):
                return short_name[:-len(sfx)]
        return short_name

    def run_generator(self, *args):
        selection = cmds.ls(sl=True, type='joint', long=True)
        if not selection:
            cmds.warning("Please select at least one joint.")
            return

        shape_type = cmds.optionMenu(self.shape_menu, query=True, value=True)
        size = cmds.floatField(self.size_field, query=True, value=True)
        circle_sections = cmds.intField(self.circle_sections_field, query=True, value=True)
        degree_label = cmds.optionMenu(self.circle_degree_menu, query=True, value=True)
        circle_degree = 3 if degree_label == "Cubic" else 1
        color_rgb = cmds.colorSliderGrp(self.color_slider, query=True, rgb=True)

        parent_obj = cmds.textField(self.parent_obj_field, query=True, text=True).strip()
        child_obj = cmds.textField(self.child_obj_field, query=True, text=True).strip()

        add_parent_const = cmds.checkBox(self.constraint_cb, query=True, value=True)
        add_scale_const = cmds.checkBox(self.scale_cb, query=True, value=True)
        maintain_hierarchy = cmds.checkBox(self.hierarchy_cb, query=True, value=True)

        use_const_grp = cmds.checkBox(self.use_grp_cb, query=True, value=True)
        const_grp_name = cmds.textField(self.grp_name_field, query=True, text=True).strip()

        if parent_obj and not cmds.objExists(parent_obj):
            cmds.warning(f"Parent object '{parent_obj}' does not exist in scene.")
            parent_obj = None

        if child_obj and not cmds.objExists(child_obj):
            cmds.warning(f"Child object '{child_obj}' does not exist in scene.")
            child_obj = None

        _begin_tool_undo("GenerateControllers")
        try:
            constraint_scope=_constraint_context(const_grp_name if use_const_grp and const_grp_name else
                self.clean_joint_name(selection[0])+'_Controllers')

            joint_to_ctrl_map = {}
            for jnt in selection:
                base_name = self.clean_joint_name(jnt)
                ctrl_name = f"{base_name}_ctrl"
                offset_name = f"{base_name}_offset_grp"
                parent_grp_name = f"{base_name}_parent_grp"

                ctrl = self.create_ctrl_shape(
                    shape_type,
                    size,
                    ctrl_name,
                    circle_sections=circle_sections,
                    circle_degree=circle_degree
                )
                self.set_ctrl_color(ctrl, color_rgb)

                offset_grp = cmds.group(empty=True, name=offset_name)
                parent_grp = cmds.group(empty=True, name=parent_grp_name)

                cmds.parent(ctrl, offset_grp)
                cmds.parent(offset_grp, parent_grp)

                cmds.matchTransform(parent_grp, jnt, position=True, rotation=True)

                if add_parent_const:
                    p_constraint = _constraint_command('parentConstraint',ctrl, jnt, maintainOffset=True,_scope=constraint_scope)[0]

                    if add_scale_const:
                        s_constraint = _constraint_command('scaleConstraint',ctrl, jnt, maintainOffset=True,_scope=constraint_scope)[0]

                joint_to_ctrl_map[jnt] = (parent_grp, ctrl)

            if maintain_hierarchy:
                for jnt, (parent_grp, ctrl) in joint_to_ctrl_map.items():
                    parent_jnt = cmds.listRelatives(jnt, parent=True, type='joint', fullPath=True)
                    if parent_jnt and parent_jnt[0] in joint_to_ctrl_map:
                        _, parent_ctrl = joint_to_ctrl_map[parent_jnt[0]]
                        cmds.parent(parent_grp, parent_ctrl)

            if parent_obj:
                for jnt, (parent_grp, ctrl) in joint_to_ctrl_map.items():
                    parent_jnt = cmds.listRelatives(jnt, parent=True, type='joint', fullPath=True)
                    is_root = True
                    if maintain_hierarchy and parent_jnt and parent_jnt[0] in joint_to_ctrl_map:
                        is_root = False
                    if is_root:
                        cmds.parent(parent_grp, parent_obj)

            if child_obj:
                leaf_ctrl = None
                if maintain_hierarchy:
                    for jnt, (parent_grp, ctrl) in joint_to_ctrl_map.items():
                        child_jnts = cmds.listRelatives(jnt, children=True, type='joint', fullPath=True) or []
                        has_child_in_sel = any(cj in joint_to_ctrl_map for cj in child_jnts)
                        if not has_child_in_sel:
                            leaf_ctrl = ctrl
                            break

                if not leaf_ctrl:
                    leaf_ctrl = list(joint_to_ctrl_map.values())[-1][1]

                if leaf_ctrl:
                    cmds.parent(child_obj, leaf_ctrl)

            cmds.select([data[1] for data in joint_to_ctrl_map.values()])
            print(f"Successfully generated controllers for {len(selection)} joints.")
        finally:
            _end_tool_undo()

    # --------------------------------------------------------------------------
    # TAB 2: Shape Mirroring Builder
    # --------------------------------------------------------------------------
    def build_mirror_tab(self, parent):
        cmds.separator(height=6, style='none')
        cmds.text(label="Mirror Control Shapes across YZ Plane", font="boldLabelFont", align="center")
        cmds.separator(height=6, style='single')

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[165, 165], adjustableColumn=2)
        cmds.columnLayout(adjustableColumn=True)
        cmds.text(label="Search (Source):", align="left")
        self.search_field = cmds.textField(text="L_")
        cmds.setParent('..')

        cmds.columnLayout(adjustableColumn=True)
        cmds.text(label="Replace (Target):", align="left")
        self.replace_field = cmds.textField(text="R_")
        cmds.setParent('..')
        cmds.setParent('..')

        self.force_recreate_cb = cmds.checkBox(label="Force Recreate Shapes (if CV counts differ)", value=False)
        self.match_color_cb = cmds.checkBox(label="Match Source Color (Copy display color)", value=False)

        cmds.separator(height=6, style='single')

        cmds.button(label="Mirror Selected Controls", height=36, backgroundColor=[0.25, 0.45, 0.55], command=self.run_mirror)
        cmds.button(label="Swap Search & Replace (R_ -> L_)", height=24, command=self.swap_fields)

    def swap_fields(self, *args):
        s_val = cmds.textField(self.search_field, query=True, text=True)
        r_val = cmds.textField(self.replace_field, query=True, text=True)
        cmds.textField(self.search_field, edit=True, text=r_val)
        cmds.textField(self.replace_field, edit=True, text=s_val)

    def run_mirror(self, *args):
        selection = cmds.ls(sl=True, type='transform')
        search_str = cmds.textField(self.search_field, query=True, text=True).strip()
        replace_str = cmds.textField(self.replace_field, query=True, text=True).strip()
        force_recreate = cmds.checkBox(self.force_recreate_cb, query=True, value=True)
        match_color = cmds.checkBox(self.match_color_cb, query=True, value=True)

        if not selection:
            cmds.warning("Please select at least one control or a pair of controls.")
            return

        _begin_tool_undo("MirrorControls")
        count = 0
        try:
            if len(selection) == 2 and (search_str not in selection[0]):
                if mirror_ctrl_shape(selection[0], selection[1], force_recreate, match_color):
                    count += 1
            else:
                for src in selection:
                    if search_str in src:
                        tgt = src.replace(search_str, replace_str)
                        if cmds.objExists(tgt):
                            if mirror_ctrl_shape(src, tgt, force_recreate, match_color):
                                count += 1
                        else:
                            cmds.warning(f"Target object '{tgt}' not found for '{src}'.")
                    else:
                        cmds.warning(f"Search prefix/suffix '{search_str}' not found in '{src}'.")

            print(f"Successfully mirrored {count} controller shape(s) across YZ plane.")
        finally:
            _end_tool_undo()

    # --------------------------------------------------------------------------
    # TAB 3: Skin Weight Transfer Builder
    # --------------------------------------------------------------------------
    def build_weight_tab(self, parent):
        cmds.separator(height=6, style='none')
        cmds.text(label="Namespace Weight Transfer", font="boldLabelFont", align="center")
        cmds.separator(height=6, style='single')

        cmds.rowLayout(numberOfColumns=3, columnWidth3=[90, 170, 70], adjustableColumn=2)
        cmds.text(label="Target Mesh:")
        self.mesh_field = cmds.textField(placeholderText="Select mesh...")
        cmds.button(label="Get Sel", command=self.populate_mesh)
        cmds.setParent('..')

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[165, 165], adjustableColumn=2)
        cmds.columnLayout(adjustableColumn=True)
        cmds.text(label="Source Namespace:", align='left')
        self.src_field = cmds.textField(text="B")
        cmds.setParent('..')

        cmds.columnLayout(adjustableColumn=True)
        cmds.text(label="Target Namespace:", align='left')
        self.tgt_field = cmds.textField(text="A")
        cmds.setParent('..')
        cmds.setParent('..')

        self.remove_cb = cmds.checkBox(label="Remove source influences after transfer", value=True)

        cmds.separator(height=6, style='single')

        cmds.button(label="Transfer Weights", height=36, backgroundColor=[0.25, 0.45, 0.35], command=self.run_transfer)
        self.populate_mesh()

    def populate_mesh(self, *args):
        sel = cmds.ls(sl=True, type='transform')
        if sel:
            cmds.textField(self.mesh_field, edit=True, text=sel[0])

    def run_transfer(self, *args):
        mesh = cmds.textField(self.mesh_field, query=True, text=True).strip()
        src_ns = cmds.textField(self.src_field, query=True, text=True).strip()
        tgt_ns = cmds.textField(self.tgt_field, query=True, text=True).strip()
        remove_src = cmds.checkBox(self.remove_cb, query=True, value=True)

        if not mesh or not src_ns or not tgt_ns:
            cmds.warning("Please populate Mesh and both Source/Target namespaces.")
            return

        transfer_namespace_weights(mesh, src_ns, tgt_ns, remove_src)

    # --------------------------------------------------------------------------
    # TAB 4: Naming & Utilities Builder
    # --------------------------------------------------------------------------
    def build_utils_tab(self, parent):
        cmds.separator(height=6, style='none')
        cmds.text(label="Naming & Hierarchy Utilities", font="boldLabelFont", align="center")
        cmds.separator(height=6, style='single')

        # Feature 1: Name Swap
        cmds.frameLayout(label=" Replace Name & Suffix Old ", marginWidth=8, marginHeight=8)
        cmds.text(
            label="1. Select Old Object\n2. Shift-Select Replacement Object\n3. Click button below:",
            align="left"
        )
        cmds.separator(height=6, style='none')

        self.hide_old_shape_cb = cmds.checkBox(
            label="Hide Shape Node(s) of Old Object",
            value=True
        )

        cmds.separator(height=6, style='none')

        cmds.button(
            label="Swap Name & Add '_old' to 1st",
            height=34,
            backgroundColor=[0.55, 0.35, 0.25],
            command=self.run_swap_old
        )
        cmds.setParent('..')

        # Feature 2: Rename by Removing Suffix
        cmds.frameLayout(
            label=" Rename Selected Objects - Remove Suffix ",
            marginWidth=8,
            marginHeight=8
        )

        cmds.text(
            label="Rename ALL selected objects by removing this suffix from the END of each name:",
            align="left",
            wordWrap=True
        )

        cmds.rowLayout(
            numberOfColumns=2,
            columnWidth2=[110, 210],
            adjustableColumn=2
        )
        cmds.text(label="Suffix to Remove:")
        self.remove_suffix_field = cmds.textField(text="_ctrl")
        cmds.setParent('..')

        cmds.separator(height=6, style='none')

        cmds.button(
            label="Rename ALL Selected - Remove Suffix",
            height=34,
            backgroundColor=[0.45, 0.35, 0.25],
            command=self.run_remove_suffix
        )
        cmds.setParent('..')

        # Feature 3: Constraint Collector
        cmds.frameLayout(label=" Hierarchy Constraint Collector ", marginWidth=8, marginHeight=8)

        cmds.rowLayout(numberOfColumns=3, columnWidth3=[90, 160, 70], adjustableColumn=2)
        cmds.text(label="Root Node:")
        self.root_node_field = cmds.textField(placeholderText="Leave empty to use selection...")
        cmds.button(label="Get Sel", command=self.populate_root_node)
        cmds.setParent('..')

        cmds.rowLayout(numberOfColumns=3, columnWidth3=[90, 160, 70], adjustableColumn=2)
        cmds.text(label="Target Group:")
        self.collect_grp_field = cmds.textField(text="constraintNode")
        cmds.button(label="Get Sel", command=self.populate_collect_grp)
        cmds.setParent('..')

        cmds.separator(height=6, style='none')

        cmds.button(
            label="Collect Hierarchy Constraints to Group",
            height=34,
            backgroundColor=[0.25, 0.45, 0.55],
            command=self.run_collect_constraints
        )
        cmds.setParent('..')

    def populate_root_node(self, *args):
        sel = cmds.ls(sl=True)
        if sel:
            cmds.textField(self.root_node_field, edit=True, text=sel[0])

    def populate_collect_grp(self, *args):
        sel = cmds.ls(sl=True)
        if sel:
            cmds.textField(self.collect_grp_field, edit=True, text=sel[0])

    def run_swap_old(self, *args):
        hide_shape = cmds.checkBox(self.hide_old_shape_cb, query=True, value=True)
        swap_and_suffix_old(hide_shape=hide_shape)

    def run_remove_suffix(self, *args):
        suffix = cmds.textField(self.remove_suffix_field, query=True, text=True).strip()
        rename_remove_suffix_from_selection(suffix)

    def run_collect_constraints(self, *args):
        root_node = cmds.textField(self.root_node_field, query=True, text=True).strip()
        target_grp = cmds.textField(self.collect_grp_field, query=True, text=True).strip() or "constraintNode"
        collect_constraints_under_hierarchy(root_node=root_node, target_grp=target_grp)

    # --------------------------------------------------------------------------
    # TAB 5: FK & Aim Utilities
    # --------------------------------------------------------------------------
    def build_fk_aim_tab(self, parent):
        self.fk_aim_scroll = cmds.scrollLayout(childResizable=True)
        self.fk_aim_container = cmds.columnLayout(adjustableColumn=True, rowSpacing=10)

        # ======================================================================
        # SECTION 1: FK DriveChain
        # ======================================================================
        cmds.frameLayout(label="1. FK DriveChain System", collapsable=True, collapse=False, marginWidth=8, marginHeight=8, bgc=[0.18, 0.18, 0.18])

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[185, 185], adjustableColumn=2)
        cmds.button(label="Load All Cached Chains", command=self.load_all_fk_caches, bgc=[0.3, 0.45, 0.55])
        cmds.button(label="+ Add New Chain Setup", command=lambda x: self.add_fk_chain_ui(), bgc=[0.4, 0.4, 0.4])
        cmds.setParent('..')

        cmds.separator(height=10, style='single')
        self.fk_chains_container = cmds.columnLayout(adjustableColumn=True, rowSpacing=10)
        cmds.setParent('..') # exit fk_chains_container
        cmds.setParent('..') # exit frameLayout 1

        # ======================================================================
        # SECTION 2: AimCurve Constraint System
        # ======================================================================
        cmds.frameLayout(label="2. AimCurve Constraint System", collapsable=True, collapse=False, marginWidth=8, marginHeight=8, bgc=[0.18, 0.22, 0.2])

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[185, 185], adjustableColumn=2)
        cmds.button(label="Load All Aim Caches", command=self.load_all_aim_caches, bgc=[0.3, 0.45, 0.55])
        cmds.button(label="+ Add New Aim Setup", command=lambda x: self.add_aim_setup_ui(), bgc=[0.4, 0.4, 0.4])
        cmds.setParent('..')

        cmds.separator(height=10, style='single')
        self.aim_setups_container = cmds.columnLayout(adjustableColumn=True, rowSpacing=10)
        cmds.setParent('..') # exit aim_setups_container
        cmds.setParent('..') # exit frameLayout 2

        # ======================================================================
        # SECTION 3: AimAndReduce By Distance
        # ======================================================================
        cmds.frameLayout(
            label="3. AimAndReduce By Distance",
            collapsable=True,
            collapse=False,
            marginWidth=8,
            marginHeight=8,
            bgc=[0.22, 0.20, 0.18]
        )

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[185, 185], adjustableColumn=2)
        cmds.button(
            label="Load All Distance Aim Caches",
            command=self.load_all_aim_distance_caches,
            bgc=[0.3, 0.45, 0.55]
        )
        cmds.button(
            label="+ Add Distance Aim Setup",
            command=lambda x: self.add_aim_distance_setup_ui(),
            bgc=[0.4, 0.4, 0.4]
        )
        cmds.setParent('..')

        cmds.separator(height=10, style='single')
        self.aim_distance_setups_container = cmds.columnLayout(
            adjustableColumn=True,
            rowSpacing=10
        )
        cmds.setParent('..') # exit aim_distance_setups_container
        cmds.setParent('..') # exit frameLayout 3

        cmds.setParent('..') # exit fk_aim_container
        cmds.setParent('..') # exit scroll

    # --- AimCurve Caching & UI Methods ---
    def add_aim_setup_ui(self, setup_name="SpineAim", root_grp="AtRoot", aim_axis="X", up_axis="Y", use_parent=True, pairs=None):
        if pairs is None:
            pairs = []

        cmds.setParent(self.aim_setups_container)

        frame = cmds.frameLayout(
            label=f"Aim Setup: {setup_name}",
            collapsable=True,
            collapse=False,
            marginWidth=5,
            marginHeight=5,
            bgc=[0.2, 0.24, 0.22]
        )

        aim_data = {
            'frame': frame,
            'pairs_data': []
        }

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[90, 260], adjustableColumn=2)
        cmds.text(label="Setup Name:")
        aim_data['name_field'] = cmds.textField(text=setup_name)
        cmds.textField(
            aim_data['name_field'],
            edit=True,
            changeCommand=lambda val, f=frame: cmds.frameLayout(f, edit=True, label=f"Aim Setup: {val}")
        )
        cmds.setParent('..')

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[90, 240], adjustableColumn=2)
        cmds.text(label="AtRoot Group:")
        aim_data['root_field'] = cmds.textField(text=root_grp, placeholderText="Parent group for everything...")
        cmds.setParent('..')

        cmds.separator(height=6, style='single')

        cmds.rowLayout(numberOfColumns=4, columnWidth4=[60, 80, 60, 80])
        cmds.text(label="Aim Axis:")
        aim_data['aim_axis_menu'] = cmds.optionMenu()
        for axis in ["X", "Y", "Z", "-X", "-Y", "-Z"]: cmds.menuItem(label=axis)
        cmds.optionMenu(aim_data['aim_axis_menu'], edit=True, value=aim_axis)

        cmds.text(label="Up Axis:")
        aim_data['up_axis_menu'] = cmds.optionMenu()
        for axis in ["X", "Y", "Z", "-X", "-Y", "-Z"]: cmds.menuItem(label=axis)
        cmds.optionMenu(aim_data['up_axis_menu'], edit=True, value=up_axis)
        cmds.setParent('..')

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[260, 100], adjustableColumn=1)
        aim_data['use_parent_cb'] = cmds.checkBox(label="Use Controller Parent Rotation for Up Vector", value=use_parent)
        cmds.button(label="Delete Aim UI", bgc=[0.6, 0.2, 0.2], command=lambda x, a=aim_data: self.remove_aim_ui(a))
        cmds.setParent('..')

        cmds.separator(height=6, style='single')

        cmds.text(label="Aim Targets (Curve → Controllers):", font="obliqueLabelFont", align="left")
        aim_data['pairs_layout'] = cmds.columnLayout(adjustableColumn=True, rowSpacing=6)
        cmds.setParent('..')

        cmds.button(
            label="+ Add Aim Target (1st Sel = Curve, Rest = Ctrls)",
            height=26,
            command=lambda x, a=aim_data: self.add_aim_pair_from_sel(a)
        )

        cmds.separator(height=10, style='none')
        cmds.button(label="Generate Aim Constraints for Setup", height=34, bgc=[0.55, 0.45, 0.25], command=lambda x, a=aim_data: self.run_aim_curve(a))

        cmds.setParent('..') # exit frame
        self.aim_setups_data.append(aim_data)

        for p in pairs:
            self.add_aim_pair_from_sel(aim_data, crv_str=p.get('crv', ''), ctrls_str=p.get('ctrls', ''))

        return aim_data

    def remove_aim_ui(self, aim_data):
        if cmds.layout(aim_data['frame'], exists=True):
            cmds.deleteUI(aim_data['frame'])
        if aim_data in self.aim_setups_data:
            self.aim_setups_data.remove(aim_data)

    def add_aim_pair_from_sel(self, aim_data, crv_str="", ctrls_str=""):
        if not crv_str and not ctrls_str:
            sel = cmds.ls(sl=True)
            if sel:
                crv_str = sel[0]
                ctrls_str = ",".join(sel[1:])

        cmds.setParent(aim_data['pairs_layout'])

        pair_col = cmds.columnLayout(adjustableColumn=True)

        pair_dict = {'layout': pair_col}

        # Curve Row
        cmds.rowLayout(numberOfColumns=3, columnWidth3=[40, 200, 50], adjustableColumn=2)
        cmds.text(label="Crv:")
        pair_dict['crv_tf'] = cmds.textField(text=crv_str)
        cmds.button(label="Get Sel", command=lambda x, tf=pair_dict['crv_tf']: self._populate_field(tf))
        cmds.setParent('..')

        # Ctrls Row
        cmds.rowLayout(numberOfColumns=4, columnWidth4=[40, 160, 50, 40], adjustableColumn=2)
        cmds.text(label="Ctrls:")
        pair_dict['ctrls_tf'] = cmds.textField(text=ctrls_str)

        def _get_rest_sel(tf):
            s = cmds.ls(sl=True)
            if s: cmds.textField(tf, edit=True, text=",".join(s))

        cmds.button(label="Get Sel", command=lambda x, tf=pair_dict['ctrls_tf']: _get_rest_sel(tf))

        def _del_pair(p_dict):
            cmds.deleteUI(p_dict['layout'])
            if p_dict in aim_data['pairs_data']:
                aim_data['pairs_data'].remove(p_dict)

        cmds.button(label="Del", bgc=[0.5, 0.2, 0.2], command=lambda x, pd=pair_dict: _del_pair(pd))
        cmds.setParent('..')

        cmds.separator(style='singleDash')
        cmds.setParent('..') # exit pair_col

        aim_data['pairs_data'].append(pair_dict)

    def load_all_aim_caches(self, *args):
        available_caches = cmds.ls("*AimCached") or []
        if not available_caches:
            cmds.warning("No cache nodes with suffix 'AimCached' found in the scene.")
            return

        for a_data in list(self.aim_setups_data):
            self.remove_aim_ui(a_data)

        for cache_node in available_caches:
            try:
                setup_name = cache_node.replace("AimCached", "")
                root_grp = cmds.getAttr(f"{cache_node}.rootGrp") or "AtRoot"
                aim_axis = cmds.getAttr(f"{cache_node}.aimAxis") or "X"
                up_axis = cmds.getAttr(f"{cache_node}.upAxis") or "Y"

                use_parent = True
                if cmds.attributeQuery("useParent", node=cache_node, exists=True):
                    use_parent = cmds.getAttr(f"{cache_node}.useParent")

                pair_count = 0
                if cmds.attributeQuery("pairCount", node=cache_node, exists=True):
                    pair_count = cmds.getAttr(f"{cache_node}.pairCount")

                loaded_pairs = []
                for i in range(pair_count):
                    c_crv = ""
                    c_ctrls = ""
                    if cmds.attributeQuery(f"crv_{i}", node=cache_node, exists=True):
                        c_crv = cmds.getAttr(f"{cache_node}.crv_{i}") or ""
                    if cmds.attributeQuery(f"ctrls_{i}", node=cache_node, exists=True):
                        c_ctrls = cmds.getAttr(f"{cache_node}.ctrls_{i}") or ""

                    loaded_pairs.append({'crv': c_crv, 'ctrls': c_ctrls})

                self.add_aim_setup_ui(setup_name, root_grp, aim_axis, up_axis, use_parent, pairs=loaded_pairs)
            except Exception as e:
                cmds.warning(f"Error loading cache node '{cache_node}': {e}")

        print(f"Loaded {len(available_caches)} Cached Aim Setup(s).")

    # --- AimCurve Execution Logic ---
    def run_aim_curve(self, aim_data):
        setup_name = cmds.textField(aim_data['name_field'], query=True, text=True).strip()
        if not setup_name:
            cmds.warning("Please provide a Setup Name.")
            return

        root_grp = cmds.textField(aim_data['root_field'], query=True, text=True).strip()
        use_parent = cmds.checkBox(aim_data['use_parent_cb'], query=True, value=True)

        aim_axis_str = cmds.optionMenu(aim_data['aim_axis_menu'], query=True, value=True)
        up_axis_str = cmds.optionMenu(aim_data['up_axis_menu'], query=True, value=True)

        axis_map = {"X": (1,0,0), "Y": (0,1,0), "Z": (0,0,1), "-X": (-1,0,0), "-Y": (0,-1,0), "-Z": (0,0,-1)}
        aim_vec = axis_map.get(aim_axis_str, (1,0,0))
        up_vec = axis_map.get(up_axis_str, (0,1,0))

        valid_pairs = []
        for p in aim_data['pairs_data']:
            if cmds.layout(p['layout'], exists=True):
                crv = cmds.textField(p['crv_tf'], query=True, text=True).strip()
                ctrls = cmds.textField(p['ctrls_tf'], query=True, text=True).strip()
                if crv and ctrls:
                    valid_pairs.append({'crv': crv, 'ctrls': ctrls})

        if not valid_pairs:
            cmds.warning(f"No valid targets provided for setup '{setup_name}'.")
            return

        _begin_tool_undo("GenerateAimCurve")
        try:
            # 1. Update/Create Cache Node
            cache_node = f"{setup_name}AimCached"
            if not cmds.objExists(cache_node):
                cache_node = cmds.group(empty=True, name=cache_node)
                cmds.setAttr(f"{cache_node}.visibility", 0)

            attrs = {
                "rootGrp": "string",
                "aimAxis": "string",
                "upAxis": "string",
                "useParent": "bool",
                "pairCount": "long"
            }

            for attr, atype in attrs.items():
                if not cmds.attributeQuery(attr, node=cache_node, exists=True):
                    if atype == "string":
                        cmds.addAttr(cache_node, ln=attr, dt="string")
                    elif atype == "bool":
                        cmds.addAttr(cache_node, ln=attr, at="bool")
                    elif atype == "long":
                        cmds.addAttr(cache_node, ln=attr, at="long")

            cmds.setAttr(f"{cache_node}.rootGrp", root_grp, type="string")
            cmds.setAttr(f"{cache_node}.aimAxis", aim_axis_str, type="string")
            cmds.setAttr(f"{cache_node}.upAxis", up_axis_str, type="string")
            cmds.setAttr(f"{cache_node}.useParent", use_parent)
            cmds.setAttr(f"{cache_node}.pairCount", len(valid_pairs))

            for i, p in enumerate(valid_pairs):
                if not cmds.attributeQuery(f"crv_{i}", node=cache_node, exists=True):
                    cmds.addAttr(cache_node, ln=f"crv_{i}", dt="string")
                if not cmds.attributeQuery(f"ctrls_{i}", node=cache_node, exists=True):
                    cmds.addAttr(cache_node, ln=f"ctrls_{i}", dt="string")

                cmds.setAttr(f"{cache_node}.crv_{i}", p['crv'], type="string")
                cmds.setAttr(f"{cache_node}.ctrls_{i}", p['ctrls'], type="string")

            # 2. Build Constraint Logic
            if not root_grp:
                root_grp = "AtRoot"
            if not cmds.objExists(root_grp):
                root_grp = cmds.group(empty=True, name=root_grp)

            total_ctrls_processed = 0

            for p in valid_pairs:
                crv = p['crv']
                ctrls_str = p['ctrls']

                if not cmds.objExists(crv):
                    cmds.warning(f"DriverCurve '{crv}' does not exist. Skipping pair.")
                    continue

                shapes = cmds.listRelatives(crv, shapes=True, fullPath=True) or []
                if cmds.nodeType(crv) == "nurbsCurve":
                    shapes = [crv]

                if not shapes or cmds.nodeType(shapes[0]) != "nurbsCurve":
                    cmds.warning(f"Object '{crv}' is not a valid Nurbs Curve node. Skipping.")
                    continue

                crv_shape = shapes[0]

                sel_list = om.MSelectionList()
                sel_list.add(crv_shape)
                crv_dag = sel_list.getDagPath(0)
                curve_fn = om.MFnNurbsCurve(crv_dag)

                ctrls = [x.strip() for x in ctrls_str.split(',') if cmds.objExists(x.strip())]

                for ctrl in ctrls:
                    short_name = ctrl.split('|')[-1]

                    # Create Aim Connection Group
                    aim_grp_name = f"{short_name}_Aim"
                    if cmds.objExists(aim_grp_name):
                        cmds.warning(f"Aim group '{aim_grp_name}' already exists. Skipping recreation for '{ctrl}'.")
                        continue

                    aim_grp = cmds.group(empty=True, name=aim_grp_name)
                    cmds.matchTransform(aim_grp, ctrl, position=True, rotation=True)

                    ctrl_parent = cmds.listRelatives(ctrl, parent=True, fullPath=True)
                    if ctrl_parent:
                        cmds.parent(aim_grp, ctrl_parent[0])

                    cmds.parent(ctrl, aim_grp)

                    # Build tracking hierarchy mapped to curve
                    offset = cmds.group(empty=True, name=f"Offset_{short_name}_AtRoot")
                    at_root = cmds.group(empty=True, name=f"{short_name}_AtRoot")

                    cmds.matchTransform(offset, aim_grp, position=True, rotation=True)
                    cmds.matchTransform(at_root, aim_grp, position=True, rotation=True)

                    cmds.parent(at_root, offset)
                    cmds.parent(offset, root_grp)

                    ctrl_pos = cmds.xform(aim_grp, query=True, worldSpace=True, rotatePivot=True)
                    mpt = om.MPoint(ctrl_pos[0], ctrl_pos[1], ctrl_pos[2])

                    closest_pt, u_param = curve_fn.closestPoint(mpt, space=om.MSpace.kWorld)

                    loc = cmds.spaceLocator(name=f"{short_name}_target")[0]
                    cmds.parent(loc, root_grp)

                    poci = cmds.createNode('pointOnCurveInfo', name=f"{short_name}_poci")
                    cmds.connectAttr(f"{crv_shape}.worldSpace[0]", f"{poci}.inputCurve", force=True)
                    cmds.setAttr(f"{poci}.parameter", u_param)
                    cmds.connectAttr(f"{poci}.position", f"{loc}.translate", force=True)

                    # Use the ACTUAL parent of the driven Aim group as the
                    # object-rotation up object. Query it after hierarchy setup so
                    # we do not rely on a stale parent path captured earlier.
                    driven_parent = cmds.listRelatives(
                        aim_grp,
                        parent=True,
                        fullPath=True
                    ) or []

                    if use_parent and driven_parent:
                        _constraint_command('aimConstraint',
                            loc,
                            at_root,
                            aimVector=aim_vec,
                            upVector=up_vec,
                            worldUpType="objectrotation",
                            worldUpObject=driven_parent[0],
                            maintainOffset=True
                        )
                    else:
                        _constraint_command('aimConstraint',
                            loc,
                            at_root,
                            aimVector=aim_vec,
                            upVector=up_vec,
                            worldUpType="vector",
                            worldUpVector=up_vec,
                            maintainOffset=True
                        )

                    # Connect AtRoot to the new Aim group
                    try:
                        cmds.connectAttr(f"{at_root}.rotate", f"{aim_grp}.rotate", force=True)
                        total_ctrls_processed += 1
                    except Exception as e:
                        cmds.warning(f"Could not connect {at_root}.rotate to {aim_grp}.rotate: {e}")

            if total_ctrls_processed > 0:
                print(f"Successfully Aimed {total_ctrls_processed} controllers mapped to cache '{cache_node}'.")

        finally:
            _end_tool_undo()

    # --------------------------------------------------------------------------
    # SECTION 3: AimAndReduce By Distance
    # --------------------------------------------------------------------------
    def add_aim_distance_setup_ui(
        self,
        setup_name="SpineAimReduce",
        root_grp="AtRoot",
        slider_obj="",
        falloff_distance=10.0,
        aim_axis="X",
        up_axis="Y",
        use_parent=True,
        pairs=None
    ):
        """Create one AimAndReduce By Distance setup UI."""
        if pairs is None:
            pairs = []

        cmds.setParent(self.aim_distance_setups_container)

        frame = cmds.frameLayout(
            label=f"Distance Aim Setup: {setup_name}",
            collapsable=True,
            collapse=False,
            marginWidth=5,
            marginHeight=5,
            bgc=[0.24, 0.22, 0.20]
        )

        aim_data = {
            'frame': frame,
            'pairs_data': []
        }

        # Setup Name
        cmds.rowLayout(numberOfColumns=2, columnWidth2=[90, 260], adjustableColumn=2)
        cmds.text(label="Setup Name:")
        aim_data['name_field'] = cmds.textField(text=setup_name)
        cmds.textField(
            aim_data['name_field'],
            edit=True,
            changeCommand=lambda val, f=frame: cmds.frameLayout(
                f, edit=True, label=f"Distance Aim Setup: {val}"
            )
        )
        cmds.setParent('..')

        # AtRoot Group
        cmds.rowLayout(numberOfColumns=2, columnWidth2=[90, 240], adjustableColumn=2)
        cmds.text(label="AtRoot Group:")
        aim_data['root_field'] = cmds.textField(
            text=root_grp,
            placeholderText="Parent group for everything..."
        )
        cmds.setParent('..')

        # Slider Object
        cmds.rowLayout(numberOfColumns=3, columnWidth3=[90, 180, 60], adjustableColumn=2)
        cmds.text(label="Slider:")
        aim_data['slider_field'] = cmds.textField(
            text=slider_obj,
            placeholderText="Distance driver object..."
        )
        cmds.button(
            label="Get Sel",
            command=lambda x, f=aim_data['slider_field']: self._populate_transform_field(f)
        )
        cmds.setParent('..')

        # Initial DistanceMax value.  On Generate this becomes a keyable
        # attribute on the Slider transform.  Existing slider values are preserved.
        cmds.rowLayout(numberOfColumns=2, columnWidth2=[90, 240], adjustableColumn=2)
        cmds.text(label="Distance Max:")
        aim_data['falloff_field'] = cmds.floatField(
            value=falloff_distance,
            minValue=0.001,
            precision=3
        )
        cmds.setParent('..')

        cmds.text(
            label="Slider attrs: DistanceMax = falloff radius | Power = aim strength",
            align="left"
        )
        cmds.separator(height=6, style='single')

        # Aim / Up Axis
        cmds.rowLayout(numberOfColumns=4, columnWidth4=[60, 80, 60, 80])
        cmds.text(label="Aim Axis:")
        aim_data['aim_axis_menu'] = cmds.optionMenu()
        for axis in ["X", "Y", "Z", "-X", "-Y", "-Z"]:
            cmds.menuItem(label=axis)
        cmds.optionMenu(aim_data['aim_axis_menu'], edit=True, value=aim_axis)

        cmds.text(label="Up Axis:")
        aim_data['up_axis_menu'] = cmds.optionMenu()
        for axis in ["X", "Y", "Z", "-X", "-Y", "-Z"]:
            cmds.menuItem(label=axis)
        cmds.optionMenu(aim_data['up_axis_menu'], edit=True, value=up_axis)
        cmds.setParent('..')

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[260, 100], adjustableColumn=1)
        aim_data['use_parent_cb'] = cmds.checkBox(
            label="Use Controller Parent Rotation for Up Vector",
            value=use_parent
        )
        cmds.button(
            label="Delete Aim UI",
            bgc=[0.6, 0.2, 0.2],
            command=lambda x, a=aim_data: self.remove_aim_distance_ui(a)
        )
        cmds.setParent('..')

        cmds.separator(height=6, style='single')

        cmds.text(
            label="Aim Targets (Curve → Controllers):",
            font="obliqueLabelFont",
            align="left"
        )
        aim_data['pairs_layout'] = cmds.columnLayout(adjustableColumn=True, rowSpacing=6)
        cmds.setParent('..')

        # Reuse Section 2's curve/controller pair widget.
        cmds.button(
            label="+ Add Aim Target (Curve + Ctrls; Slider ignored)",
            height=26,
            command=lambda x, a=aim_data: self.add_aim_distance_pair_from_sel(a)
        )

        cmds.separator(height=10, style='none')
        cmds.button(
            label="Generate All Pending Distance Aim Tasks",
            height=34,
            bgc=[0.55, 0.40, 0.22],
            command=lambda x, a=aim_data: self.run_aim_distance(a)
        )

        cmds.setParent('..') # exit frame
        self.aim_distance_setups_data.append(aim_data)

        # Cached tasks must use the Section 3 task UI too, otherwise they would
        # lose the per-task Generate button when loaded from cache.
        for p in pairs:
            self.add_aim_distance_pair_ui(
                aim_data,
                crv_str=p.get('crv', ''),
                ctrls_str=p.get('ctrls', '')
            )

        return aim_data

    def remove_aim_distance_ui(self, aim_data):
        if cmds.layout(aim_data['frame'], exists=True):
            cmds.deleteUI(aim_data['frame'])
        if aim_data in self.aim_distance_setups_data:
            self.aim_distance_setups_data.remove(aim_data)

    def _populate_transform_field(self, field_widget):
        """Populate a textField with the first selected transform node."""
        sel = cmds.ls(sl=True, type="transform") or []
        if not sel:
            cmds.warning("Please select a transform object for Slider.")
            return
        cmds.textField(field_widget, edit=True, text=sel[0])

    def _populate_aim_distance_curve_field(self, field_widget, aim_data):
        """Populate Section 3 Curve field only with a valid NURBS curve."""
        sel = cmds.ls(sl=True) or []
        if not sel:
            cmds.warning("Please select a NURBS curve for Crv.")
            return

        slider_obj = cmds.textField(
            aim_data['slider_field'], query=True, text=True
        ).strip()

        for node in sel:
            if node == slider_obj:
                continue

            if not cmds.objExists(node):
                continue

            if cmds.nodeType(node) == "nurbsCurve":
                parents = cmds.listRelatives(node, parent=True, fullPath=False) or []
                cmds.textField(
                    field_widget, edit=True, text=parents[0] if parents else node
                )
                return

            if cmds.nodeType(node) == "transform":
                shapes = cmds.listRelatives(
                    node, shapes=True, noIntermediate=True, type="nurbsCurve"
                ) or []
                if shapes:
                    cmds.textField(field_widget, edit=True, text=node)
                    return

        cmds.warning("Select a NURBS curve transform for Crv; Slider is a separate transform field.")

    def add_aim_distance_pair_ui(self, aim_data, crv_str="", ctrls_str=""):
        """
        Add one independently runnable Distance Aim task.

        Each task owns its own Generate button, so adding a new task does not
        require rebuilding/walking tasks that were already completed.
        """
        cmds.setParent(aim_data['pairs_layout'])

        task_frame = cmds.frameLayout(
            label="Distance Aim Task",
            collapsable=True,
            collapse=False,
            marginWidth=5,
            marginHeight=5,
            bgc=[0.20, 0.20, 0.20]
        )

        pair_dict = {
            'layout': task_frame
        }

        # Curve row
        cmds.rowLayout(
            numberOfColumns=3,
            columnWidth3=[40, 200, 50],
            adjustableColumn=2
        )
        cmds.text(label="Crv:")
        pair_dict['crv_tf'] = cmds.textField(text=crv_str)
        cmds.button(
            label="Get Sel",
            command=lambda x, tf=pair_dict['crv_tf'], a=aim_data: self._populate_aim_distance_curve_field(tf, a)
        )
        cmds.setParent('..')

        # Controllers row
        cmds.rowLayout(
            numberOfColumns=4,
            columnWidth4=[40, 160, 50, 40],
            adjustableColumn=2
        )
        cmds.text(label="Ctrls:")
        pair_dict['ctrls_tf'] = cmds.textField(text=ctrls_str)

        def _get_ctrl_selection(tf):
            selected = cmds.ls(sl=True) or []
            slider = cmds.textField(
                aim_data['slider_field'], query=True, text=True
            ).strip()
            # Slider is a separate transform input, never a controller entry.
            selected = [node for node in selected if node != slider]
            if selected:
                cmds.textField(tf, edit=True, text=",".join(selected))

        cmds.button(
            label="Get Sel",
            command=lambda x, tf=pair_dict['ctrls_tf']: _get_ctrl_selection(tf)
        )

        def _delete_task(task):
            if cmds.layout(task['layout'], exists=True):
                cmds.deleteUI(task['layout'])
            if task in aim_data['pairs_data']:
                aim_data['pairs_data'].remove(task)

        cmds.button(
            label="Del",
            bgc=[0.5, 0.2, 0.2],
            command=lambda x, task=pair_dict: _delete_task(task)
        )
        cmds.setParent('..')

        cmds.separator(height=5, style='none')

        # This is the important change: run only this task.
        pair_dict['generate_btn'] = cmds.button(
            label="Generate AIM + Distance for This Task",
            height=28,
            bgc=[0.45, 0.38, 0.20],
            command=lambda x, a=aim_data, task=pair_dict: self.run_aim_distance(
                a, only_pair=task
            )
        )

        cmds.setParent('..') # exit task frame
        aim_data['pairs_data'].append(pair_dict)
        return pair_dict

    def add_aim_distance_pair_from_sel(self, aim_data):
        """Add a Section 3 task from selection, excluding the Slider transform."""
        sel = cmds.ls(sl=True) or []
        slider_obj = cmds.textField(
            aim_data['slider_field'], query=True, text=True
        ).strip()

        # Slider is a separate transform input and must never become the curve.
        filtered = [node for node in sel if node != slider_obj]

        if not filtered:
            return self.add_aim_distance_pair_ui(
                aim_data, crv_str="", ctrls_str=""
            )

        crv_str = filtered[0]
        ctrls_str = ",".join(filtered[1:])
        return self.add_aim_distance_pair_ui(
            aim_data,
            crv_str=crv_str,
            ctrls_str=ctrls_str
        )

    def load_all_aim_distance_caches(self, *args):
        available_caches = cmds.ls("*AimDistanceCached", type="transform") or []
        if not available_caches:
            cmds.warning("No cache nodes with suffix 'AimDistanceCached' found in the scene.")
            return

        for data in list(self.aim_distance_setups_data):
            self.remove_aim_distance_ui(data)

        for cache_node in available_caches:
            try:
                setup_name = cache_node.replace("AimDistanceCached", "")
                root_grp = "AtRoot"
                slider_obj = ""
                falloff_distance = 10.0
                aim_axis = "X"
                up_axis = "Y"
                use_parent = True
                pair_count = 0

                if cmds.attributeQuery("rootGrp", node=cache_node, exists=True):
                    root_grp = cmds.getAttr(f"{cache_node}.rootGrp") or "AtRoot"
                if cmds.attributeQuery("sliderObj", node=cache_node, exists=True):
                    slider_obj = cmds.getAttr(f"{cache_node}.sliderObj") or ""
                if cmds.attributeQuery("falloffDistance", node=cache_node, exists=True):
                    falloff_distance = cmds.getAttr(f"{cache_node}.falloffDistance")
                if cmds.attributeQuery("aimAxis", node=cache_node, exists=True):
                    aim_axis = cmds.getAttr(f"{cache_node}.aimAxis") or "X"
                if cmds.attributeQuery("upAxis", node=cache_node, exists=True):
                    up_axis = cmds.getAttr(f"{cache_node}.upAxis") or "Y"
                if cmds.attributeQuery("useParent", node=cache_node, exists=True):
                    use_parent = cmds.getAttr(f"{cache_node}.useParent")
                if cmds.attributeQuery("pairCount", node=cache_node, exists=True):
                    pair_count = cmds.getAttr(f"{cache_node}.pairCount")

                loaded_pairs = []
                for i in range(pair_count):
                    crv = ""
                    ctrls = ""
                    if cmds.attributeQuery(f"crv_{i}", node=cache_node, exists=True):
                        crv = cmds.getAttr(f"{cache_node}.crv_{i}") or ""
                    if cmds.attributeQuery(f"ctrls_{i}", node=cache_node, exists=True):
                        ctrls = cmds.getAttr(f"{cache_node}.ctrls_{i}") or ""
                    loaded_pairs.append({'crv': crv, 'ctrls': ctrls})

                self.add_aim_distance_setup_ui(
                    setup_name=setup_name,
                    root_grp=root_grp,
                    slider_obj=slider_obj,
                    falloff_distance=falloff_distance,
                    aim_axis=aim_axis,
                    up_axis=up_axis,
                    use_parent=use_parent,
                    pairs=loaded_pairs
                )

            except Exception as e:
                cmds.warning(f"Error loading Distance Aim cache '{cache_node}': {e}")

        print(f"Loaded {len(available_caches)} Distance Aim Setup(s).")

    def _ensure_aim_distance_slider_attrs(self, slider_obj, distance_default=10.0):
        """
        Add animator-facing attributes to the Section 3 Slider transform.

        DistanceMax:
            World-space falloff radius.  Distance >= DistanceMax gives zero weight.

        Power:
            Final aim strength multiplier.  0 = off, 1 = normal, 2 = double.

        Existing attributes/animation are preserved.
        """
        if not cmds.objExists(slider_obj) or cmds.nodeType(slider_obj) != "transform":
            raise RuntimeError(
                "Aim distance slider '{}' must be a transform.".format(slider_obj)
            )

        distance_attr = f"{slider_obj}.DistanceMax"
        power_attr = f"{slider_obj}.Power"

        if not cmds.attributeQuery("DistanceMax", node=slider_obj, exists=True):
            cmds.addAttr(
                slider_obj,
                longName="DistanceMax",
                niceName="Distance Max",
                attributeType="double",
                minValue=0.001,
                defaultValue=max(float(distance_default), 0.001),
                keyable=True
            )

        if not cmds.attributeQuery("Power", node=slider_obj, exists=True):
            cmds.addAttr(
                slider_obj,
                longName="Power",
                niceName="Power",
                attributeType="double",
                minValue=0.0,
                defaultValue=1.0,
                keyable=True
            )

        # Be defensive if a slider already had attributes with these names.
        numeric_types = {
            "double", "float", "doubleLinear", "doubleAngle",
            "long", "short", "byte"
        }
        for plug in (distance_attr, power_attr):
            attr_type = cmds.getAttr(plug, type=True)
            if attr_type not in numeric_types:
                raise RuntimeError(
                    "Slider attribute '{}' already exists but is type '{}'. "
                    "Please rename/remove that attribute before generating.".format(
                        plug, attr_type
                    )
                )

        return distance_attr, power_attr

    def run_aim_distance(self, aim_data, only_pair=None):
        """
        Build the same AimCurve system as Section 2, but drive each Aim group with:

        If only_pair is supplied, only that Distance Aim task is processed.
        This lets each task have its own Generate button without revisiting earlier tasks.

            AtRoot.rotate * distanceWeight

        distanceWeight is calculated from the Slider object to the controller's
        corresponding AtRoot transform.  This keeps the distance reference out of
        the animated controller hierarchy:

            distance = 0                   -> base weight = 1
            distance >= Slider.DistanceMax -> base weight = 0

        Final weight = base weight * Slider.Power
        """
        setup_name = cmds.textField(
            aim_data['name_field'], query=True, text=True
        ).strip()
        if not setup_name:
            cmds.warning("Please provide a Setup Name.")
            return

        root_grp = cmds.textField(
            aim_data['root_field'], query=True, text=True
        ).strip()
        slider_obj = cmds.textField(
            aim_data['slider_field'], query=True, text=True
        ).strip()

        if not slider_obj or not cmds.objExists(slider_obj):
            cmds.warning("Please provide a valid Slider transform object.")
            return

        if cmds.nodeType(slider_obj) != "transform":
            cmds.warning(
                "Slider '{}' must be a transform node, not '{}'.".format(
                    slider_obj, cmds.nodeType(slider_obj)
                )
            )
            return

        falloff_distance = cmds.floatField(
            aim_data['falloff_field'], query=True, value=True
        )
        if falloff_distance <= 0:
            cmds.warning("Distance Max must be greater than 0.")
            return

        use_parent = cmds.checkBox(
            aim_data['use_parent_cb'], query=True, value=True
        )
        aim_axis_str = cmds.optionMenu(
            aim_data['aim_axis_menu'], query=True, value=True
        )
        up_axis_str = cmds.optionMenu(
            aim_data['up_axis_menu'], query=True, value=True
        )

        axis_map = {
            "X": (1, 0, 0),
            "Y": (0, 1, 0),
            "Z": (0, 0, 1),
            "-X": (-1, 0, 0),
            "-Y": (0, -1, 0),
            "-Z": (0, 0, -1)
        }
        aim_vec = axis_map.get(aim_axis_str, (1, 0, 0))
        up_vec = axis_map.get(up_axis_str, (0, 1, 0))

        # Collect every valid task for cache persistence, but optionally execute
        # only the task whose local Generate button was pressed.
        valid_pairs = []
        pair_lookup = {}

        for p in aim_data['pairs_data']:
            if not cmds.layout(p['layout'], exists=True):
                continue

            crv = cmds.textField(
                p['crv_tf'], query=True, text=True
            ).strip()
            ctrls = cmds.textField(
                p['ctrls_tf'], query=True, text=True
            ).strip()

            if crv and ctrls:
                pair_values = {
                    'crv': crv,
                    'ctrls': ctrls,
                    '_ui_pair': p
                }
                valid_pairs.append(pair_values)
                pair_lookup[id(p)] = pair_values

        if not valid_pairs:
            cmds.warning(f"No valid targets provided for setup '{setup_name}'.")
            return

        if only_pair is not None:
            selected_pair = pair_lookup.get(id(only_pair))
            if not selected_pair:
                cmds.warning("This Distance Aim task needs both a Curve and Controllers.")
                return
            process_pairs = [selected_pair]
        else:
            process_pairs = valid_pairs

        # One click = one Maya Undo.
        _begin_tool_undo("AimAndReduceByDistance")
        try:
            # Create/reuse animator-facing attributes directly on the Slider.
            # Keeping this inside the chunk means the whole setup is one Undo.
            try:
                slider_distance_attr, slider_power_attr = (
                    self._ensure_aim_distance_slider_attrs(
                        slider_obj, distance_default=falloff_distance
                    )
                )
            except RuntimeError as exc:
                cmds.warning(str(exc))
                return

            # --------------------------------------------------------------
            # Cache
            # --------------------------------------------------------------
            cache_node = f"{setup_name}AimDistanceCached"
            if not cmds.objExists(cache_node):
                cache_node = cmds.group(empty=True, name=cache_node)
                cmds.setAttr(f"{cache_node}.visibility", 0)

            attrs = {
                "rootGrp": "string",
                "sliderObj": "string",
                "falloffDistance": "double",
                "aimAxis": "string",
                "upAxis": "string",
                "useParent": "bool",
                "pairCount": "long"
            }

            for attr, atype in attrs.items():
                if cmds.attributeQuery(attr, node=cache_node, exists=True):
                    continue
                if atype == "string":
                    cmds.addAttr(cache_node, ln=attr, dt="string")
                elif atype == "double":
                    cmds.addAttr(cache_node, ln=attr, at="double")
                elif atype == "bool":
                    cmds.addAttr(cache_node, ln=attr, at="bool")
                elif atype == "long":
                    cmds.addAttr(cache_node, ln=attr, at="long")

            cmds.setAttr(f"{cache_node}.rootGrp", root_grp, type="string")
            cmds.setAttr(f"{cache_node}.sliderObj", slider_obj, type="string")
            # Keep legacy cache compatibility, but store the slider's current
            # DistanceMax rather than a baked network value.
            cmds.setAttr(
                f"{cache_node}.falloffDistance",
                cmds.getAttr(slider_distance_attr)
            )
            cmds.setAttr(f"{cache_node}.aimAxis", aim_axis_str, type="string")
            cmds.setAttr(f"{cache_node}.upAxis", up_axis_str, type="string")
            cmds.setAttr(f"{cache_node}.useParent", use_parent)
            cmds.setAttr(f"{cache_node}.pairCount", len(valid_pairs))

            for i, pair in enumerate(valid_pairs):
                crv_attr = f"crv_{i}"
                ctrls_attr = f"ctrls_{i}"

                if not cmds.attributeQuery(crv_attr, node=cache_node, exists=True):
                    cmds.addAttr(cache_node, ln=crv_attr, dt="string")
                if not cmds.attributeQuery(ctrls_attr, node=cache_node, exists=True):
                    cmds.addAttr(cache_node, ln=ctrls_attr, dt="string")

                cmds.setAttr(f"{cache_node}.{crv_attr}", pair['crv'], type="string")
                cmds.setAttr(f"{cache_node}.{ctrls_attr}", pair['ctrls'], type="string")

            # --------------------------------------------------------------
            # Root
            # --------------------------------------------------------------
            if not root_grp:
                root_grp = "AtRoot"
            if not cmds.objExists(root_grp):
                root_grp = cmds.group(empty=True, name=root_grp)

            total_ctrls_processed = 0
            total_ctrls_already_done = 0

            for pair in process_pairs:
                crv = pair['crv']
                ctrls_str = pair['ctrls']

                if not cmds.objExists(crv):
                    cmds.warning(f"DriverCurve '{crv}' does not exist. Skipping pair.")
                    continue

                shapes = cmds.listRelatives(
                    crv, shapes=True, fullPath=True
                ) or []
                if cmds.nodeType(crv) == "nurbsCurve":
                    shapes = [crv]

                if not shapes or cmds.nodeType(shapes[0]) != "nurbsCurve":
                    if crv == slider_obj:
                        cmds.warning(
                            "Slider '{}' is a transform and cannot be used as the Curve. "
                            "Set Slider in the Slider field and a NURBS curve in Crv.".format(crv)
                        )
                    else:
                        cmds.warning(
                            "Object '{}' is not a valid Nurbs Curve node. Skipping.".format(crv)
                        )
                    continue

                crv_shape = shapes[0]

                sel_list = om.MSelectionList()
                sel_list.add(crv_shape)
                crv_dag = sel_list.getDagPath(0)
                curve_fn = om.MFnNurbsCurve(crv_dag)

                ctrls = [
                    x.strip()
                    for x in ctrls_str.split(',')
                    if cmds.objExists(x.strip())
                ]

                for ctrl in ctrls:
                    short_name = ctrl.split('|')[-1]

                    # Capture the original controller parent for hierarchy insertion
                    # and (optionally) the aimConstraint up-vector source.  It is NOT
                    # used for distance, because it may move during animation.
                    ctrl_parent_list = cmds.listRelatives(
                        ctrl, parent=True, fullPath=True
                    ) or []
                    ctrl_parent = ctrl_parent_list[0] if ctrl_parent_list else None

                    # ------------------------------------------------------
                    # Driven group
                    # ------------------------------------------------------
                    aim_grp_name = f"{short_name}_AimDistance"
                    if cmds.objExists(aim_grp_name):
                        # Already generated. This is expected when using
                        # "Generate All Pending" after some tasks were built
                        # individually, so skip quietly and do not rebuild it.
                        total_ctrls_already_done += 1
                        continue

                    aim_grp = cmds.group(empty=True, name=aim_grp_name)
                    cmds.matchTransform(aim_grp, ctrl, position=True, rotation=True)

                    if ctrl_parent:
                        # Preserve world transform while placing the new group next
                        # to the controller under its original parent.
                        cmds.parent(aim_grp, ctrl_parent, absolute=True)

                    # Preserve controller world transform when inserting group.
                    cmds.parent(ctrl, aim_grp, absolute=True)

                    # ------------------------------------------------------
                    # Tracking hierarchy mapped to curve
                    # ------------------------------------------------------
                    offset = cmds.group(
                        empty=True,
                        name=f"Offset_{short_name}_AimDistance_AtRoot"
                    )
                    at_root = cmds.group(
                        empty=True,
                        name=f"{short_name}_AimDistance_AtRoot"
                    )

                    cmds.matchTransform(offset, aim_grp, position=True, rotation=True)
                    cmds.matchTransform(at_root, aim_grp, position=True, rotation=True)
                    cmds.parent(at_root, offset)
                    cmds.parent(offset, root_grp)

                    ctrl_pos = cmds.xform(
                        aim_grp,
                        query=True,
                        worldSpace=True,
                        rotatePivot=True
                    )
                    mpt = om.MPoint(ctrl_pos[0], ctrl_pos[1], ctrl_pos[2])
                    _, u_param = curve_fn.closestPoint(mpt, space=om.MSpace.kWorld)

                    # ------------------------------------------------------
                    # Point on curve locator
                    # ------------------------------------------------------
                    loc = cmds.spaceLocator(
                        name=f"{short_name}_AimDistance_target"
                    )[0]
                    cmds.parent(loc, root_grp)

                    poci = cmds.createNode(
                        'pointOnCurveInfo',
                        name=f"{short_name}_AimDistance_poci"
                    )
                    cmds.connectAttr(
                        f"{crv_shape}.worldSpace[0]",
                        f"{poci}.inputCurve",
                        force=True
                    )
                    cmds.setAttr(f"{poci}.parameter", u_param)
                    cmds.connectAttr(
                        f"{poci}.position",
                        f"{loc}.translate",
                        force=True
                    )

                    # ------------------------------------------------------
                    # Aim calculation
                    # ------------------------------------------------------
                    # The object-rotation up object must be the ACTUAL parent of
                    # the driven AimDistance group. Query it after parenting so
                    # animation/hierarchy changes do not leave us using the wrong
                    # transform or an old DAG path.
                    driven_parent = cmds.listRelatives(
                        aim_grp,
                        parent=True,
                        fullPath=True
                    ) or []

                    if use_parent and driven_parent:
                        _constraint_command('aimConstraint',
                            loc,
                            at_root,
                            aimVector=aim_vec,
                            upVector=up_vec,
                            worldUpType="objectrotation",
                            worldUpObject=driven_parent[0],
                            maintainOffset=True
                        )
                    else:
                        _constraint_command('aimConstraint',
                            loc,
                            at_root,
                            aimVector=aim_vec,
                            upVector=up_vec,
                            worldUpType="vector",
                            worldUpVector=up_vec,
                            maintainOffset=True
                        )

                    # ------------------------------------------------------
                    # Distance: Slider <-> corresponding AtRoot transform
                    #
                    # Do NOT use ctrl_parent / aim_grp here.  Those live in the
                    # animated controller hierarchy, so their positions may change
                    # during animation and unintentionally change the falloff.
                    #
                    # The AtRoot transform is the stable reference created for this
                    # controller in the AtRoot tracking hierarchy.
                    # ------------------------------------------------------
                    distance_node = cmds.createNode(
                        "distanceBetween",
                        name=f"{short_name}_AimDistance_DST"
                    )
                    cmds.connectAttr(
                        f"{slider_obj}.worldMatrix[0]",
                        f"{distance_node}.inMatrix1",
                        force=True
                    )
                    cmds.connectAttr(
                        f"{at_root}.worldMatrix[0]",
                        f"{distance_node}.inMatrix2",
                        force=True
                    )

                    # ------------------------------------------------------
                    # Distance -> 0..1 weight
                    # 0 distance       = 1.0
                    # falloff distance = 0.0
                    # farther          = clamped to 0.0
                    # ------------------------------------------------------
                    remap = cmds.createNode(
                        "remapValue",
                        name=f"{short_name}_AimDistance_Remap"
                    )
                    cmds.connectAttr(
                        f"{distance_node}.distance",
                        f"{remap}.inputValue",
                        force=True
                    )
                    cmds.setAttr(f"{remap}.inputMin", 0.0)
                    # Live animation control from the Slider transform.
                    cmds.connectAttr(
                        slider_distance_attr,
                        f"{remap}.inputMax",
                        force=True
                    )
                    cmds.setAttr(f"{remap}.outputMin", 1.0)
                    cmds.setAttr(f"{remap}.outputMax", 0.0)

                    # Linear distance falloff:
                    # near = 1, DistanceMax = 0.
                    cmds.setAttr(f"{remap}.value[0].value_Position", 0.0)
                    cmds.setAttr(f"{remap}.value[0].value_FloatValue", 0.0)
                    cmds.setAttr(f"{remap}.value[0].value_Interp", 1)
                    cmds.setAttr(f"{remap}.value[1].value_Position", 1.0)
                    cmds.setAttr(f"{remap}.value[1].value_FloatValue", 1.0)
                    cmds.setAttr(f"{remap}.value[1].value_Interp", 1)

                    # ------------------------------------------------------
                    # Final weight = distance falloff * Slider.Power
                    # ------------------------------------------------------
                    power_mdl = cmds.createNode(
                        "multDoubleLinear",
                        name=f"{short_name}_AimDistance_Power_MDL"
                    )
                    cmds.connectAttr(
                        f"{remap}.outValue",
                        f"{power_mdl}.input1",
                        force=True
                    )
                    cmds.connectAttr(
                        slider_power_attr,
                        f"{power_mdl}.input2",
                        force=True
                    )

                    # ------------------------------------------------------
                    # AtRoot.rotate * finalWeight -> driven group.rotate
                    # ------------------------------------------------------
                    rotate_md = cmds.createNode(
                        "multiplyDivide",
                        name=f"{short_name}_AimDistance_MD_R"
                    )
                    cmds.connectAttr(
                        f"{at_root}.rotate",
                        f"{rotate_md}.input1",
                        force=True
                    )
                    cmds.connectAttr(
                        f"{power_mdl}.output",
                        f"{rotate_md}.input2X",
                        force=True
                    )
                    cmds.connectAttr(
                        f"{power_mdl}.output",
                        f"{rotate_md}.input2Y",
                        force=True
                    )
                    cmds.connectAttr(
                        f"{power_mdl}.output",
                        f"{rotate_md}.input2Z",
                        force=True
                    )
                    cmds.connectAttr(
                        f"{rotate_md}.output",
                        f"{aim_grp}.rotate",
                        force=True
                    )

                    total_ctrls_processed += 1

            if only_pair is not None:
                # Keep the button runnable so the artist can add more controllers
                # to the same task later. Existing controllers are skipped.
                if cmds.control(only_pair.get('generate_btn', ''), exists=True):
                    if total_ctrls_processed > 0:
                        cmds.button(
                            only_pair['generate_btn'],
                            edit=True,
                            label="Generate Missing AIM + Distance (Task Built)"
                        )
                    elif total_ctrls_already_done > 0:
                        cmds.button(
                            only_pair['generate_btn'],
                            edit=True,
                            label="Generate Missing AIM + Distance (Already Built)"
                        )

            if total_ctrls_processed > 0:
                print(
                    f"Successfully created AimAndReduce By Distance for "
                    f"{total_ctrls_processed} controller(s), mapped to "
                    f"cache '{cache_node}'."
                )
            elif total_ctrls_already_done > 0:
                print(
                    f"Distance Aim task already built for "
                    f"{total_ctrls_already_done} controller(s); nothing repeated."
                )

        finally:
            _end_tool_undo()

    # --- FK DriveChain Methods ---
    def add_fk_chain_ui(self, parent_node="", chain_name="Arm", is_fk=True, groups=None, vis_on_shape=True):
        if groups is None:
            groups = []

        cmds.setParent(self.fk_chains_container)

        frame = cmds.frameLayout(
            label=f"Chain Setup: {chain_name}",
            collapsable=True,
            collapse=False,
            marginWidth=5,
            marginHeight=5,
            bgc=[0.22, 0.22, 0.22]
        )

        chain_data = {
            'frame': frame,
            'group_fields': []
        }

        cmds.rowLayout(numberOfColumns=3, columnWidth3=[70, 180, 60], adjustableColumn=2)
        cmds.text(label="Parent:")
        chain_data['parent_field'] = cmds.textField(text=parent_node, placeholderText="Attach root control under...")
        cmds.button(label="Get Sel", command=lambda x, f=chain_data['parent_field']: self._populate_field(f))
        cmds.setParent('..')

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[70, 240], adjustableColumn=2)
        cmds.text(label="Name:")
        chain_data['name_field'] = cmds.textField(text=chain_name)
        cmds.textField(
            chain_data['name_field'],
            edit=True,
            changeCommand=lambda val, f=frame: cmds.frameLayout(f, edit=True, label=f"Chain Setup: {val}")
        )
        cmds.setParent('..')

        cmds.rowLayout(numberOfColumns=2, columnWidth2=[200, 100], adjustableColumn=1)
        chain_data['fk_cb'] = cmds.checkBox(label="FK Sequence (Parent consecutive)", value=is_fk)
        cmds.button(label="Delete Chain UI", bgc=[0.6, 0.2, 0.2], command=lambda x, c=chain_data: self.remove_chain_ui(c))
        cmds.setParent('..')

        cmds.rowLayout(numberOfColumns=1)
        chain_data['vis_shape_cb'] = cmds.checkBox(label="Apply Visibility to Shapes (instead of Transform)", value=vis_on_shape)
        cmds.setParent('..')

        cmds.separator(height=6, style='single')

        cmds.text(label="Driven Item Groups:", font="obliqueLabelFont", align="left")
        chain_data['groups_layout'] = cmds.columnLayout(adjustableColumn=True, rowSpacing=4)
        cmds.setParent('..')

        cmds.button(
            label="+ Add Driven Group (from Ordered Selection)",
            height=26,
            command=lambda x, c=chain_data: self.add_fk_group_from_sel(c)
        )

        cmds.separator(height=8, style='none')

        cmds.button(
            label="Generate Controllers for this Chain",
            height=34,
            backgroundColor=[0.25, 0.5, 0.45],
            command=lambda x, c=chain_data: self.run_generate_fk_system(c)
        )

        cmds.setParent('..')
        self.fk_chains_data.append(chain_data)

        for grp_str in groups:
            self.add_fk_group_from_sel(chain_data, items_str=grp_str)

        return chain_data

    def remove_chain_ui(self, chain_data):
        if cmds.layout(chain_data['frame'], exists=True):
            cmds.deleteUI(chain_data['frame'])
        if chain_data in self.fk_chains_data:
            self.fk_chains_data.remove(chain_data)

    def _populate_field(self, field_widget):
        sel = cmds.ls(sl=True)
        if sel:
            cmds.textField(field_widget, edit=True, text=sel[0])

    def _populate_field_multiple(self, field_widget):
        sel = cmds.ls(sl=True)
        if sel:
            cmds.textField(field_widget, edit=True, text=",".join(sel))

    def add_fk_group_from_sel(self, chain_data, items_str=None):
        if items_str is None:
            sel = cmds.ls(sl=True)
            items_str = ",".join(sel) if sel else ""

        cmds.setParent(chain_data['groups_layout'])
        row = cmds.rowLayout(numberOfColumns=3, columnWidth3=[210, 48, 38], adjustableColumn=1)
        tf = cmds.textField(text=items_str, placeholderText="e.g. pSphere1, pSphere2")

        def reload_row(tf_widget):
            sel = cmds.ls(sl=True)
            if sel:
                cmds.textField(tf_widget, edit=True, text=",".join(sel))

        def remove_row(r_widget, tf_widget):
            cmds.deleteUI(r_widget)
            if tf_widget in chain_data['group_fields']:
                chain_data['group_fields'].remove(tf_widget)

        cmds.button(label="Reload", command=lambda x, t=tf: reload_row(t))
        cmds.button(label="Del", command=lambda x, r=row, t=tf: remove_row(r, t))
        chain_data['group_fields'].append(tf)

    def load_all_fk_caches(self, *args):
        available_caches = cmds.ls("*ChainCached") or []
        if not available_caches:
            cmds.warning("No cache nodes with suffix 'ChainCached' found in the scene.")
            return

        for c_data in list(self.fk_chains_data):
            self.remove_chain_ui(c_data)

        for cache_node in available_caches:
            try:
                detected_chain_name = cache_node.replace("ChainCached", "")
                parent_node = cmds.getAttr(f"{cache_node}.parentNode") or ""
                is_fk = cmds.getAttr(f"{cache_node}.isFk")
                group_count = cmds.getAttr(f"{cache_node}.groupCount")

                vis_on_shape = True
                if cmds.attributeQuery("visOnShape", node=cache_node, exists=True):
                    vis_on_shape = cmds.getAttr(f"{cache_node}.visOnShape")

                loaded_groups = []
                for i in range(group_count):
                    attr_name = f"group_{i}"
                    if cmds.attributeQuery(attr_name, node=cache_node, exists=True):
                        grp_str = cmds.getAttr(f"{cache_node}.{attr_name}") or ""
                        loaded_groups.append(grp_str)

                self.add_fk_chain_ui(
                    parent_node=parent_node,
                    chain_name=detected_chain_name,
                    is_fk=is_fk,
                    groups=loaded_groups,
                    vis_on_shape=vis_on_shape
                )
            except Exception as e:
                cmds.warning(f"Error loading cache node '{cache_node}': {e}")

        print(f"Loaded {len(available_caches)} Cached Chain(s).")

    def run_generate_fk_system(self, chain_data):
        chain_name = cmds.textField(chain_data['name_field'], query=True, text=True).strip()
        if not chain_name:
            cmds.warning("Please provide a Chain Name.")
            return

        parent_node = cmds.textField(chain_data['parent_field'], query=True, text=True).strip()
        is_fk = cmds.checkBox(chain_data['fk_cb'], query=True, value=True)
        vis_on_shape = cmds.checkBox(chain_data['vis_shape_cb'], query=True, value=True)

        valid_groups = []
        for tf in chain_data['group_fields']:
            if cmds.control(tf, exists=True):
                val = cmds.textField(tf, query=True, text=True).strip()
                if val:
                    valid_groups.append(val)

        if not valid_groups:
            cmds.warning(f"No valid item groups provided for chain '{chain_name}'.")
            return

        _begin_tool_undo("GenerateFKSystem")
        try:
            cache_node = f"{chain_name}ChainCached"
            if not cmds.objExists(cache_node):
                cache_node = cmds.group(empty=True, name=cache_node)
                cmds.setAttr(f"{cache_node}.visibility", 0)

            for attr in ["parentNode", "isFk", "groupCount", "visOnShape"]:
                if not cmds.attributeQuery(attr, node=cache_node, exists=True):
                    if attr == "groupCount":
                        cmds.addAttr(cache_node, ln=attr, at="long")
                    elif attr in ["isFk", "visOnShape"]:
                        cmds.addAttr(cache_node, ln=attr, at="bool")
                    else:
                        cmds.addAttr(cache_node, ln=attr, dt="string")

            cmds.setAttr(f"{cache_node}.parentNode", parent_node, type="string")
            cmds.setAttr(f"{cache_node}.isFk", is_fk)
            cmds.setAttr(f"{cache_node}.visOnShape", vis_on_shape)
            cmds.setAttr(f"{cache_node}.groupCount", len(valid_groups))

            for i, grp_val in enumerate(valid_groups):
                attr_name = f"group_{i}"
                if not cmds.attributeQuery(attr_name, node=cache_node, exists=True):
                    cmds.addAttr(cache_node, ln=attr_name, dt="string")
                cmds.setAttr(f"{cache_node}.{attr_name}", grp_val, type="string")

            prev_last_item = None
            prev_ctrl = None
            generated_ctrls = []

            for i, grp_val in enumerate(valid_groups):
                items = [x.strip() for x in grp_val.split(',') if cmds.objExists(x.strip())]
                if not items:
                    continue

                first_item = items[0]
                last_item = items[-1]
                ctrl_name = f"{chain_name}_{i+1:02d}_ctrl"
                offset_name = f"{chain_name}_{i+1:02d}_offset"

                ctrl = cmds.circle(normal=(1,0,0), radius=2.5, name=ctrl_name, ch=False)[0]
                offset = cmds.group(empty=True, name=offset_name)

                cmds.parent(ctrl, offset)
                cmds.matchTransform(offset, first_item, position=True, rotation=True)

                if i == 0:
                    if parent_node and cmds.objExists(parent_node):
                        cmds.parent(offset, parent_node)
                else:
                    if is_fk and prev_last_item and cmds.objExists(prev_last_item) and prev_ctrl and cmds.objExists(prev_ctrl):
                        cmds.parent(offset, prev_ctrl)
                        _constraint_command('parentConstraint',prev_last_item, offset, maintainOffset=True)
                    elif parent_node and cmds.objExists(parent_node):
                        cmds.parent(offset, parent_node)

                cmds.addAttr(ctrl, ln="PercentTranslationFollow", at="double", dv=1, keyable=True)
                cmds.addAttr(ctrl, ln="PercentRotateFollow", at="double", dv=1, keyable=True)
                cmds.addAttr(ctrl, ln="VisSubController", at="bool", dv=1, keyable=True)

                for item in items:
                    short_name = item.split('|')[-1]
                    follow_name = f"{short_name}FollowDriver"

                    if cmds.objExists(follow_name):
                        cmds.warning(f"Group '{follow_name}' already exists. Skipping recreation for '{item}'.")
                        continue

                    old_parent = cmds.listRelatives(item, parent=True, fullPath=True)

                    follow_grp = cmds.group(empty=True, name=follow_name)
                    cmds.matchTransform(follow_grp, item, position=True, rotation=True)

                    if old_parent:
                        cmds.parent(follow_grp, old_parent[0])

                    cmds.parent(item, follow_grp)

                    curr_t = cmds.getAttr(f"{follow_grp}.translate")[0]
                    curr_r = cmds.getAttr(f"{follow_grp}.rotate")[0]

                    # Translate Setup
                    md_t = cmds.createNode("multiplyDivide", name=f"{short_name}_MD_T")
                    cmds.connectAttr(f"{ctrl}.translate", f"{md_t}.input1")
                    cmds.connectAttr(f"{ctrl}.PercentTranslationFollow", f"{md_t}.input2X")
                    cmds.connectAttr(f"{ctrl}.PercentTranslationFollow", f"{md_t}.input2Y")
                    cmds.connectAttr(f"{ctrl}.PercentTranslationFollow", f"{md_t}.input2Z")

                    pma_t = cmds.createNode("plusMinusAverage", name=f"{short_name}_PMA_T")
                    cmds.setAttr(f"{pma_t}.input3D[0].input3Dx", curr_t[0])
                    cmds.setAttr(f"{pma_t}.input3D[0].input3Dy", curr_t[1])
                    cmds.setAttr(f"{pma_t}.input3D[0].input3Dz", curr_t[2])

                    cmds.connectAttr(f"{md_t}.output", f"{pma_t}.input3D[1]")
                    cmds.connectAttr(f"{pma_t}.output3D", f"{follow_grp}.translate")

                    # Rotate Setup
                    md_r = cmds.createNode("multiplyDivide", name=f"{short_name}_MD_R")
                    cmds.connectAttr(f"{ctrl}.rotate", f"{md_r}.input1")
                    cmds.connectAttr(f"{ctrl}.PercentRotateFollow", f"{md_r}.input2X")
                    cmds.connectAttr(f"{ctrl}.PercentRotateFollow", f"{md_r}.input2Y")
                    cmds.connectAttr(f"{ctrl}.PercentRotateFollow", f"{md_r}.input2Z")

                    pma_r = cmds.createNode("plusMinusAverage", name=f"{short_name}_PMA_R")
                    cmds.setAttr(f"{pma_r}.input3D[0].input3Dx", curr_r[0])
                    cmds.setAttr(f"{pma_r}.input3D[0].input3Dy", curr_r[1])
                    cmds.setAttr(f"{pma_r}.input3D[0].input3Dz", curr_r[2])

                    cmds.connectAttr(f"{md_r}.output", f"{pma_r}.input3D[1]")
                    cmds.connectAttr(f"{pma_r}.output3D", f"{follow_grp}.rotate")

                    # Visibility Setup based on Checkbox
                    if vis_on_shape:
                        item_shapes = cmds.listRelatives(item, shapes=True, fullPath=True)
                        vis_targets = item_shapes if item_shapes else [item]
                    else:
                        vis_targets = [item]

                    for v_tgt in vis_targets:
                        if cmds.getAttr(f"{v_tgt}.visibility", lock=True):
                            cmds.setAttr(f"{v_tgt}.visibility", lock=False)

                        cmds.connectAttr(f"{ctrl}.VisSubController", f"{v_tgt}.visibility", force=True)
                        cmds.setAttr(f"{v_tgt}.visibility", keyable=False, channelBox=False, lock=True)

                prev_last_item = last_item
                prev_ctrl = ctrl
                generated_ctrls.append(ctrl)

            if generated_ctrls:
                cmds.select(generated_ctrls)
                print(f"Generated FK System '{chain_name}' mapped to cache '{cache_node}'.")

        finally:
            _end_tool_undo()

# ==============================================================================
# EMBED THE LEGACY MAYA-CMDS TOOLKIT INSIDE THE PYSIDE MASTER WINDOW
# ==============================================================================
def _qt_object_valid(obj):
    if obj is None:
        return False
    try:
        return shiboken.isValid(obj)
    except (RuntimeError, TypeError):
        return False


def _install_maya_shutdown_guard():
    """One lightweight process guard, retained on QApplication across reloads."""
    app = QtWidgets.QApplication.instance()
    if app is None:
        raise RuntimeError("The Rigging Toolkit requires interactive Maya.")
    state = getattr(app, "_rtk_shutdown_state", None)
    if state is None:
        state = {"exiting": False}
        app._rtk_shutdown_state = state

        def mark_exiting(*_args):
            # Do not call Maya commands from this shutdown guard.
            state["exiting"] = True

        state["mark_exiting"] = mark_exiting
        state["callback"] = om.MSceneMessage.addCallback(om.MSceneMessage.kMayaExiting, mark_exiting)
        app.aboutToQuit.connect(mark_exiting)
    return state


def _maya_is_exiting():
    app = QtWidgets.QApplication.instance()
    if app is None:
        return True
    return bool(getattr(app, "_rtk_shutdown_state", {}).get("exiting", False))


def _defer_maya_host_deletion(hosts, keep_alive=()):
    """Native Maya windows are deleted at Maya idle, after Qt reparenting finishes."""
    hosts = tuple(hosts)
    if not hosts or _maya_is_exiting():
        return

    def delete_hosts():
        # Retain wrappers until this idle operation; their C++ parent is native Maya.
        _retained = keep_alive
        if _maya_is_exiting():
            return  # Let Maya itself destroy its UI during application shutdown.
        for win in hosts:
            try:
                if cmds.window(win, exists=True):
                    cmds.deleteUI(win, window=True)
            except RuntimeError as exc:
                if not _maya_is_exiting():
                    cmds.warning("Could not release Rigging Toolkit host '{}': {}".format(win, exc))

    cmds.evalDeferred(delete_hosts, lowestPriority=True)


class EmbeddedUnifiedRiggingToolkit(UnifiedRiggingToolkitUI):
    """Lazy Maya-owned pages, exposed individually to the Qt navigation shell."""

    WINDOW_NAME = "UnifiedRiggingToolkitEmbeddedHost"
    BUILDERS = {
        "controllers": "build_controller_tab", "mirror": "build_mirror_tab",
        "weights": "build_weight_tab", "naming": "build_utils_tab",
        "fk_aim": "build_fk_aim_tab",
    }

    def create_ui(self):
        self.pages = {}
        self.hosts = {}
        self.original_parents = {}
        self._disposed = False
        self._instance_token = uuid.uuid4().hex[:8]

    def get_page(self, key):
        if self._disposed or _maya_is_exiting():
            raise RuntimeError("Cannot build native pages while the toolkit is closing.")
        if key in self.pages:
            return self.pages[key]
        if key not in self.BUILDERS:
            raise KeyError(key)
        previous_parent = cmds.setParent(query=True)
        name = "{}_{}_{}".format(self.WINDOW_NAME, self._instance_token, key)
        try:
            win = cmds.window(name, title="Rigging Toolkit Host", widthHeight=(520, 720), visible=False)
            self.hosts[key] = win
            if key == "fk_aim":
                parent = cmds.columnLayout(adjustableColumn=True)
                self.build_fk_aim_tab(parent)
                layout_name = self.fk_aim_scroll
            else:
                layout_name = cmds.scrollLayout(childResizable=True)
                parent = cmds.columnLayout(adjustableColumn=True, rowSpacing=8, columnOffset=["both", 12])
                getattr(self, self.BUILDERS[key])(parent)
            ptr = omui.MQtUtil.findLayout(layout_name) or omui.MQtUtil.findControl(layout_name)
            if not ptr:
                raise RuntimeError("Cannot resolve Maya page '{}' to a Qt widget.".format(key))
            widget = shiboken.wrapInstance(int(ptr), QtWidgets.QWidget)
            original_parent = widget.parentWidget()
            if not _qt_object_valid(original_parent):
                raise RuntimeError("Native Maya page has no valid owning parent.")
            self.original_parents[key] = original_parent
            self.pages[key] = widget
            return widget
        except Exception:
            if key in self.hosts:
                _defer_maya_host_deletion([self.hosts[key]])
            self.hosts.pop(key, None)
            self.pages.pop(key, None)
            self.original_parents.pop(key, None)
            raise
        finally:
            try:
                cmds.setParent(previous_parent or "..")
            except RuntimeError:
                pass

    def get_qt_widget(self):
        """Compatibility with scripts which previously embedded the entire toolkit."""
        if not hasattr(self, "qt_widget"):
            self.qt_widget = QtWidgets.QTabWidget()
            for key, title in (("controllers", "Controllers"), ("mirror", "Mirror"),
                               ("weights", "Skin"), ("naming", "Naming"), ("fk_aim", "FK & Aim")):
                self.qt_widget.addTab(self.get_page(key), title)
        return self.qt_widget

    def dispose(self, shutdown=False):
        """Return controls to their exact native parent; never delete from a close event."""
        if self._disposed:
            return True
        # Set the guard before parent/layout changes can emit any Qt signals.
        self._disposed = True
        records = [(key, self.pages.get(key), self.original_parents.get(key))
                   for key in list(self.pages)]
        restored = True
        retained = []
        for key, widget, original_parent in records:
            if not _qt_object_valid(widget):
                continue
            if not _qt_object_valid(original_parent):
                # A missing native owner is not a reason to hand Maya controls to
                # an unrelated window or to delete them through Qt.
                restored = False
                continue
            widget.blockSignals(True)
            for child in widget.findChildren(QtWidgets.QWidget):
                if _qt_object_valid(child):
                    child.blockSignals(True)
            tabs = getattr(self, "qt_widget", None)
            if _qt_object_valid(tabs):
                index = tabs.indexOf(widget)
                if index >= 0:
                    tabs.removeTab(index)
            current_parent = widget.parentWidget()
            if _qt_object_valid(current_parent):
                layout = current_parent.layout()
                if layout is not None:
                    layout.removeWidget(widget)
            widget.hide()
            widget.setParent(original_parent)
            retained.extend((widget, original_parent))
        if not restored:
            self._disposed = False
            if not shutdown and not _maya_is_exiting():
                cmds.warning("A Rigging Toolkit native UI owner is no longer valid. The hidden dialog is retained; restart Maya before reopening the toolkit.")
            return False
        hosts = tuple(self.hosts.values())
        self.pages.clear()
        self.original_parents.clear()
        self.hosts.clear()
        if not shutdown:
            _defer_maya_host_deletion(hosts, keep_alive=tuple(retained))
        return True

# =====================================================================

# GLOBAL CONSTANTS

# =====================================================================

SDK_CACHE_NODE = "toolSettingsGroup_SDK"

VTX_CACHE_NODE = "vertexConstraint_CacheNode"

VTX_CACHE_ATTR = "vertex_json_data"

VTX_BUFFER_GROUP = "vertexConstraint_BufferGroup"

def get_maya_main_window():

    ptr = omui.MQtUtil.mainWindow()

    if ptr is not None:

        return shiboken.wrapInstance(int(ptr), QtWidgets.QMainWindow)

    return None

# =====================================================================

# WIDGET 1: SDK TASK WIDGET (For Tab 1)

# =====================================================================

class SDKTaskWidget(QtWidgets.QFrame):

    def __init__(self, task_id, parent_ui):
        super(SDKTaskWidget, self).__init__(parent_ui)
        self.setObjectName("SDKCard")
        self.parent_ui = parent_ui
        self.task_id = task_id
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Raised)
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # Header
        header_layout = QtWidgets.QHBoxLayout()
        self.btn_toggle = QtWidgets.QPushButton("▼ Group Task {}".format(self.task_id))
        self.btn_delete = QtWidgets.QPushButton("Remove")
        self.btn_delete.setMinimumWidth(70)
        header_layout.addWidget(self.btn_toggle)
        header_layout.addWidget(self.btn_delete)
        main_layout.addLayout(header_layout)

        # Content
        self.content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(self.content_widget)
        self.le_target = QtWidgets.QLineEdit()
        self.le_target.setPlaceholderText("Target Objects (Comma-separated)...")
        self.btn_get_target = QtWidgets.QPushButton("<<")
        self.btn_get_target.setFixedWidth(30)
        target_layout = QtWidgets.QHBoxLayout()
        target_layout.addWidget(QtWidgets.QLabel("Targets:"))
        target_layout.addWidget(self.le_target)
        target_layout.addWidget(self.btn_get_target)
        content_layout.addLayout(target_layout)
        opt_layout = QtWidgets.QFormLayout()
        self.cb_hierarchy = QtWidgets.QComboBox()
        self.cb_hierarchy.addItems(["as Child", "asParent", "World"])
        self.cb_hierarchy.setCurrentIndex(1)
        self.cb_match = QtWidgets.QComboBox()
        self.cb_match.addItems(["match position Only", "match rotation Only", "match Transform", "world"])
        self.cb_match.setCurrentIndex(2)
        self.le_prefix = QtWidgets.QLineEdit()
        self.le_suffix = QtWidgets.QLineEdit()
        self.le_search = QtWidgets.QLineEdit()
        self.le_replace = QtWidgets.QLineEdit()
        opt_layout.addRow("Hierarchy Mode:", self.cb_hierarchy)
        opt_layout.addRow("Match Mode:", self.cb_match)
        opt_layout.addRow("Prefix:", self.le_prefix)
        opt_layout.addRow("Suffix:", self.le_suffix)
        opt_layout.addRow("Search For:", self.le_search)
        opt_layout.addRow("Replace With:", self.le_replace)
        content_layout.addLayout(opt_layout)
        self.btn_transform = QtWidgets.QPushButton("Execute Transform")
        self.btn_transform.setMinimumHeight(35)
        content_layout.addWidget(self.btn_transform)
        main_layout.addWidget(self.content_widget)

        # Connections
        self.btn_toggle.clicked.connect(self.toggle_collapse)
        self.btn_delete.clicked.connect(lambda: self.parent_ui.remove_task(self))
        self.btn_get_target.clicked.connect(self.get_selection)
        self.btn_transform.clicked.connect(self.execute_task)

    def toggle_collapse(self):
        collapsed = not self.content_widget.isHidden()
        self.content_widget.setVisible(not collapsed)
        self.btn_toggle.setText(("▶" if collapsed else "▼") + " Group Task {}".format(self.task_id))

    def get_selection(self):
        sel = cmds.ls(selection=True)
        if sel:
            self.le_target.setText(", ".join(sel))

    def get_data(self):
        return {
            "targets": self.le_target.text(), "hierarchy": self.cb_hierarchy.currentIndex(),
            "match": self.cb_match.currentIndex(), "prefix": self.le_prefix.text(),
            "suffix": self.le_suffix.text(), "search": self.le_search.text(), "replace": self.le_replace.text()
        }

    def set_data(self, data):
        self.le_target.setText(data.get("targets", ""))
        self.cb_hierarchy.setCurrentIndex(data.get("hierarchy", 1))
        self.cb_match.setCurrentIndex(data.get("match", 2))
        self.le_prefix.setText(data.get("prefix", ""))
        self.le_suffix.setText(data.get("suffix", ""))
        self.le_search.setText(data.get("search", ""))
        self.le_replace.setText(data.get("replace", ""))

    def execute_task(self):
        targets = [t.strip() for t in self.le_target.text().split(",") if t.strip()]
        if not targets:
            return cmds.warning("No targets specified!")
        _begin_tool_undo("SDK_Task{}".format(self.task_id))
        try:

            # Save this task's settings as part of the same action.
            self.parent_ui.save_cache()
            for obj in targets:
                if not cmds.objExists(obj): continue
                short_name = obj.split("|")[-1]
                s, r = self.le_search.text(), self.le_replace.text()
                new_base = short_name.replace(s, r) if s else short_name
                new_name = "{}{}{}".format(self.le_prefix.text(), new_base, self.le_suffix.text())
                sdk_node = cmds.group(empty=True, name=new_name)
                match_mode = self.cb_match.currentText()
                if match_mode == "match position Only": cmds.matchTransform(sdk_node, obj, pos=True, rot=False, scl=False)
                elif match_mode == "match rotation Only": cmds.matchTransform(sdk_node, obj, pos=False, rot=True, scl=False)
                elif match_mode == "match Transform": cmds.matchTransform(sdk_node, obj, pos=True, rot=True, scl=False)
                h_mode = self.cb_hierarchy.currentText()
                if h_mode == "asParent":
                    parent = cmds.listRelatives(obj, parent=True, fullPath=True)
                    if parent: cmds.parent(sdk_node, parent[0])
                    cmds.parent(obj, sdk_node)
                elif h_mode == "as Child": cmds.parent(sdk_node, obj)
            print("SDK Task {} Complete.".format(self.task_id))
        finally:
            _end_tool_undo()

# =====================================================================

# WIDGET 2: VERTEX CONSTRAINT GROUP WIDGET (For Tab 2)

# =====================================================================

class VertexGroupWidget(QtWidgets.QFrame):

    def __init__(self, group_id, parent_ui):
        super(VertexGroupWidget, self).__init__(parent_ui)
        self.setObjectName("VertexCard")
        self.parent_ui = parent_ui
        self.group_id = group_id
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Raised)
        main_layout = QtWidgets.QVBoxLayout(self)
        header_layout = QtWidgets.QHBoxLayout()
        self.lbl_title = QtWidgets.QLabel("Vertex Constraint {}".format(self.group_id))
        self.btn_delete = QtWidgets.QPushButton("Delete")
        self.btn_delete.clicked.connect(lambda: self.parent_ui.remove_group(self))
        header_layout.addWidget(self.lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_delete)
        main_layout.addLayout(header_layout)
        settings_layout = QtWidgets.QFormLayout()
        vtx_layout, driven_layout = QtWidgets.QHBoxLayout(), QtWidgets.QHBoxLayout()
        self.le_vertex, self.le_driven = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        self.btn_vtx, self.btn_driven = QtWidgets.QPushButton("<<"), QtWidgets.QPushButton("<<")
        self.btn_vtx.setFixedWidth(30); self.btn_driven.setFixedWidth(30)
        self.btn_vtx.clicked.connect(self.get_vtx); self.btn_driven.clicked.connect(self.get_driven)
        vtx_layout.addWidget(self.le_vertex); vtx_layout.addWidget(self.btn_vtx)
        driven_layout.addWidget(self.le_driven); driven_layout.addWidget(self.btn_driven)
        self.spn_threshold = QtWidgets.QDoubleSpinBox()
        self.spn_threshold.setRange(0.0, 1.0); self.spn_threshold.setDecimals(4); self.spn_threshold.setValue(0.001)
        self.cb_type = QtWidgets.QComboBox()
        self.cb_type.addItems(["parentConstraint", "PointConstraint", "OrientConstraint"])
        self.chk_mo = QtWidgets.QCheckBox(); self.chk_mo.setChecked(True)
        settings_layout.addRow("Vertex:", vtx_layout)
        settings_layout.addRow("Driven:", driven_layout)
        settings_layout.addRow("Threshold:", self.spn_threshold)
        settings_layout.addRow("Type:", self.cb_type)
        settings_layout.addRow("Maintain Offset:", self.chk_mo)
        main_layout.addLayout(settings_layout)
        self.btn_execute = QtWidgets.QPushButton("Execute Vertex Constraint")
        self.btn_execute.clicked.connect(self.execute_logic)
        main_layout.addWidget(self.btn_execute)

    def get_vtx(self):
        sel = cmds.ls(selection=True, flatten=True)
        if sel and ".vtx[" in sel[0]: self.le_vertex.setText(sel[0])

    def get_driven(self):
        sel = cmds.ls(selection=True)
        if sel: self.le_driven.setText(sel[0])

    def get_data(self):
        return {
            "vertex": self.le_vertex.text(), "driven": self.le_driven.text(),
            "threshold": self.spn_threshold.value(), "type": self.cb_type.currentIndex(),
            "maintain_offset": self.chk_mo.isChecked()
        }

    def set_data(self, data):
        self.le_vertex.setText(data.get("vertex", "")); self.le_driven.setText(data.get("driven", ""))
        self.spn_threshold.setValue(data.get("threshold", 0.001))
        self.cb_type.setCurrentIndex(data.get("type", 0))
        self.chk_mo.setChecked(data.get("maintain_offset", True))

    def execute_logic(self):
        vertex, driven, thresh, c_type, mo = self.le_vertex.text(), self.le_driven.text(), self.spn_threshold.value(), self.cb_type.currentText(), self.chk_mo.isChecked()
        if not cmds.objExists(vertex) or not cmds.objExists(driven): return cmds.warning("Invalid Vertex or Driven Object!")
        skin = cmds.ls(cmds.listHistory(vertex), type="skinCluster")
        if not skin: return cmds.warning("No SkinCluster found.")
        infs = cmds.skinCluster(skin[0], q=True, inf=True)
        wgts = cmds.skinPercent(skin[0], vertex, q=True, v=True)
        valid_drvs, valid_wgts = [], []
        for i, w in zip(infs, wgts):
            if w >= thresh: valid_drvs.append(i); valid_wgts.append(w)
        if not valid_drvs: return cmds.warning("No weights found above threshold.")
        _begin_tool_undo("VtxConstraint")
        try:
            if not cmds.objExists(VTX_BUFFER_GROUP): cmds.group(empty=True, name=VTX_BUFFER_GROUP)
            driven_short = driven.split("|")[-1].replace(":", "_")
            old = cmds.ls("bufferLoc_*_to_{}".format(driven_short), type="transform")
            if old: cmds.delete(old)
            wm = cmds.xform(driven, q=True, m=True, ws=True)
            buffers = []
            for drv in valid_drvs:
                loc = cmds.spaceLocator(name="bufferLoc_{}_to_{}".format(drv.split("|")[-1].replace(":", "_"), driven_short))[0]
                cmds.parent(loc, VTX_BUFFER_GROUP)
                cmds.matchTransform(loc, driven, pos=True, rot=True, scl=False)
                _constraint_command('parentConstraint',drv, loc, mo=True)
                buffers.append(loc)
            old_const = cmds.listRelatives(driven, type="constraint")
            if old_const: cmds.delete(old_const)
            cmds.xform(driven, m=wm, ws=True)
            c_node, aliases = None, []
            if c_type == "parentConstraint":
                c_node = _constraint_command('parentConstraint',buffers, driven, mo=mo)[0]
                aliases = _constraint_command('parentConstraint',c_node, q=True, wal=True)
            elif c_type == "PointConstraint":
                c_node = _constraint_command('pointConstraint',buffers, driven, mo=mo)[0]
                aliases = _constraint_command('pointConstraint',c_node, q=True, wal=True)
            elif c_type == "OrientConstraint":
                c_node = _constraint_command('orientConstraint',buffers, driven, mo=mo)[0]
                aliases = _constraint_command('orientConstraint',c_node, q=True, wal=True)
            if c_node and aliases:
                for a, w in zip(aliases, valid_wgts): cmds.setAttr("{}.{}".format(c_node, a), w)
            self.parent_ui.save_cache()
        finally:
            _end_tool_undo()

# =====================================================================

# TABS

# =====================================================================

class _CachedSetupPanel(QtWidgets.QWidget):
    """Shared collection/cache lifecycle for SDK and vertex setup cards."""

    CACHE_NODE = ""
    CACHE_ATTR = ""
    ADD_LABEL = ""
    DESCRIPTION = ""
    ROW_CLASS = None
    ID_ATTR = ""

    def __init__(self, parent=None):
        super(_CachedSetupPanel, self).__init__(parent)
        self.setProperty("qtPanel", True)
        self.rows = []
        self._next_id = 1
        self._loading = True
        self._cache_error = False
        self._cache_timer = QtCore.QTimer(self)
        self._cache_timer.setSingleShot(True)
        self._cache_timer.setInterval(350)
        self._cache_timer.timeout.connect(self._save_pending_cache)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QtWidgets.QHBoxLayout()
        hint = QtWidgets.QLabel(self.DESCRIPTION)
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        top.addWidget(hint, 1)
        add = QtWidgets.QPushButton(self.ADD_LABEL)
        add.clicked.connect(lambda _checked=False: self._add_row())
        top.addWidget(add)
        layout.addLayout(top)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(0, 8, 0, 0)
        self.scroll_layout.setSpacing(10)
        self.scroll_layout.addStretch()
        self.scroll.setWidget(self.scroll_widget)
        layout.addWidget(self.scroll)
        self.load_cache()
        self._loading = False

    def _add_row(self, data=None):
        row = self.ROW_CLASS(self._next_id, self)
        self._next_id += 1
        if data is not None:
            row.set_data(data)
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, row)
        self.rows.append(row)
        _polish_native_panel(row)
        for widget in row.findChildren(QtWidgets.QLineEdit):
            widget.textChanged.connect(self.schedule_cache)
        for widget in row.findChildren(QtWidgets.QComboBox):
            widget.currentIndexChanged.connect(self.schedule_cache)
        for widget in row.findChildren(QtWidgets.QAbstractSpinBox):
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self.schedule_cache)
        for widget in row.findChildren(QtWidgets.QCheckBox):
            widget.toggled.connect(self.schedule_cache)
        self.schedule_cache()
        return row

    def _remove_row(self, row):
        if row not in self.rows:
            return
        self.scroll_layout.removeWidget(row)
        self.rows.remove(row)
        row.hide()
        row.deleteLater()
        self.save_cache()

    def schedule_cache(self, *_args):
        if not self._loading and not self._cache_error:
            self._cache_timer.start()

    def _save_pending_cache(self):
        try:
            self.save_cache()
        except (RuntimeError, ValueError) as exc:
            self._cache_error = True
            cmds.warning("Could not save setup settings: {}".format(exc))

    def save_cache(self):
        self._cache_timer.stop()
        if self._cache_error:
            cmds.warning("Cache could not be loaded/saved. Existing scene settings are preserved; reopen after fixing the cache.")
            return
        _write_scene_cache(self.CACHE_NODE, self.CACHE_ATTR, [row.get_data() for row in self.rows])

    def flush_cache(self):
        if self._cache_timer.isActive():
            self._save_pending_cache()

    def load_cache(self):
        self._cache_timer.stop()
        previous_loading = self._loading
        self._loading = True
        try:
            data = _read_scene_cache(self.CACHE_NODE, self.CACHE_ATTR)
            for row in list(self.rows):
                self.scroll_layout.removeWidget(row)
                row.deleteLater()
            self.rows[:] = []
            self._next_id = 1
            for item in data:
                self._add_row(item)
            # An explicitly saved empty list stays empty on reopen.
            has_cache = (cmds.objExists(self.CACHE_NODE)
                         and cmds.attributeQuery(self.CACHE_ATTR, node=self.CACHE_NODE, exists=True))
            if not data and not has_cache:
                self._add_row()
        except (ValueError, TypeError, RuntimeError) as exc:
            self._cache_error = True
            cmds.warning("Cannot read '{}.{}': {}".format(self.CACHE_NODE, self.CACHE_ATTR, exc))
            if not self.rows:
                self._add_row()
        finally:
            self._loading = previous_loading

class TabGroupUtils(_CachedSetupPanel):
    CACHE_NODE = SDK_CACHE_NODE
    CACHE_ATTR = "sdk_json_data"
    ADD_LABEL = "+ Group task"
    DESCRIPTION = "Wrap selected objects with matched transform groups."
    ROW_CLASS = SDKTaskWidget

    @property
    def tasks(self):
        return self.rows

    def add_task(self, data=None):
        return self._add_row(data)

    def remove_task(self, task):
        self._remove_row(task)

class TabVertexConstraint(_CachedSetupPanel):
    CACHE_NODE = VTX_CACHE_NODE
    CACHE_ATTR = VTX_CACHE_ATTR
    ADD_LABEL = "+ Vertex setup"
    DESCRIPTION = "Drive a transform using a skinned vertex's influence weights."
    ROW_CLASS = VertexGroupWidget

    @property
    def groups(self):
        return self.rows

    def add_group(self, data=None):
        return self._add_row(data)

    def remove_group(self, group):
        self._remove_row(group)

_LOCATOR_VIEW_TAG = "rtkLocatorViewVersion"
_LOCATOR_VIEW_ROOT = "rtkLocatorViewRoot"
_LOCATOR_VIEW_MEMBERS = "rtkLocatorViewMembers"
_LOCATOR_VIEW_VERSION = "1"


def _resolve_locator_view_joint(joint):
    joint = _resolve_hierarchy_root(joint)
    if cmds.nodeType(joint) != "joint":
        raise ValueError("Choose a joint for Locator View.")
    return joint


def _is_locator_view_group(group):
    return (cmds.objExists(group) and cmds.nodeType(group) == "transform"
            and cmds.attributeQuery(_LOCATOR_VIEW_TAG, node=group, exists=True)
            and cmds.getAttr(group + "." + _LOCATOR_VIEW_TAG) == _LOCATOR_VIEW_VERSION)


def find_locator_view_groups(joint):
    """Find only tool-tagged groups linked to this joint; survives joint renames."""
    joint = _resolve_locator_view_joint(joint)
    groups = []
    outputs = cmds.listConnections(joint + ".message", source=False, destination=True, plugs=True) or []
    for plug in outputs:
        node, attribute = plug.rsplit(".", 1)
        if attribute != _LOCATOR_VIEW_ROOT:
            continue
        for group in cmds.ls(node, long=True) or []:
            if _is_locator_view_group(group) and group not in groups:
                groups.append(group)
    return groups


def _check_locator_view_members(group):
    """Do not delete an unrelated object which a user parented into this group."""
    if not _is_locator_view_group(group):
        raise ValueError("'{}' is not a Locator View group.".format(group))
    if (cmds.lockNode(group, query=True, lock=True) or [False])[0]:
        raise ValueError("Locator View group '{}' is locked. Unlock the node before deleting or regenerating.".format(group))
    if not cmds.attributeQuery(_LOCATOR_VIEW_MEMBERS, node=group, exists=True):
        raise ValueError("Locator View membership is missing on '{}'.".format(group))
    try:
        members = json.loads(cmds.getAttr(group + "." + _LOCATOR_VIEW_MEMBERS) or "[]")
        if not isinstance(members, list) or any(not isinstance(item, str) for item in members):
            raise ValueError("Invalid membership data")
    except (ValueError, TypeError) as exc:
        raise ValueError("Cannot validate Locator View group '{}': {}".format(group, exc))
    owned = set(members)
    paths=cmds.listRelatives(group,allDescendents=True,fullPath=True) or []
    for identity in owned:
        member=_constraint_node(identity)
        if member:
            paths.append(member)
            paths.extend(cmds.listRelatives(member,allDescendents=True,fullPath=True) or [])
    for node in set(paths):
        if _constraint_uuid(node) not in owned:
            raise ValueError("'{}' contains an unrelated object '{}'. Move it out before deleting or regenerating the view.".format(group,node))
        if (cmds.lockNode(node,query=True,lock=True) or [False])[0]:
            raise ValueError("Locator View member '{}' is locked. Unlock the node before deleting or regenerating.".format(node))



@_non_undoable_cache_write
def _restore_locator_view_selection(selection):
    existing = [item for item in selection if cmds.objExists(item)]
    if existing:
        cmds.select(existing, replace=True)
    else:
        cmds.select(clear=True)


def generate_locator_view(joint, size=1.0, include_children=False, match_mode="constraints"):
    """Create a flat, grouped joint view. Constraints follow; matrix mode snapshots."""
    joint = _resolve_locator_view_joint(joint)
    try:
        size = float(size)
    except (TypeError, ValueError):
        raise ValueError("Locator size must be a positive number.")
    if not math.isfinite(size) or size <= 0:
        raise ValueError("Locator size must be a finite, positive number.")
    if match_mode not in ("constraints", "world_matrix"):
        raise ValueError("Match mode must be 'constraints' or 'world_matrix'.")
    joints = [joint]
    if include_children:
        descendants = cmds.listRelatives(joint, allDescendents=True, type="joint", fullPath=True) or []
        joints.extend(sorted(descendants, key=lambda node: (node.count("|"), node)))
    identities = [(cmds.ls(node, uuid=True) or [node])[0] for node in joints]
    if len(set(identities)) != len(identities):
        raise ValueError("Instanced joints are not supported by Locator View.")
    for node in joints:
        if len(cmds.listRelatives(node, allParents=True, fullPath=True) or []) > 1:
            raise ValueError("Instanced joint '{}' is not supported.".format(node))
    previous_groups = find_locator_view_groups(joint)
    for group in previous_groups:
        _check_locator_view_members(group)
    # Read all matrices before changing the scene.
    matrices = {node: cmds.xform(node, query=True, worldSpace=True, matrix=True) for node in joints}
    selection = cmds.ls(selection=True, long=True) or []
    group, locators, constraints, created_locator_ids = None, [], [], []
    constraint_scope=_constraint_context(joint.rsplit('|',1)[-1]+'_LocatorView',
        lambda node:created_locator_ids.extend(cmds.ls(node,uuid=True) or []))
    try:
        with _tool_action("GenerateLocatorView"):
            try:
                label = joint.rsplit("|", 1)[-1].replace(":", "_")
                group = cmds.group(empty=True, name=":" + label + "_locatorView_grp#")
                group = (cmds.ls(group, long=True) or [group])[0]
                cmds.addAttr(group, longName=_LOCATOR_VIEW_TAG, dataType="string", hidden=True)
                cmds.setAttr(group + "." + _LOCATOR_VIEW_TAG, _LOCATOR_VIEW_VERSION, type="string")
                cmds.setAttr(group + "." + _LOCATOR_VIEW_TAG, lock=True)
                cmds.addAttr(group, longName=_LOCATOR_VIEW_ROOT, attributeType="message", hidden=True)
                cmds.connectAttr(joint + ".message", group + "." + _LOCATOR_VIEW_ROOT)
                for source in joints:
                    name = source.rsplit("|", 1)[-1].replace(":", "_")
                    locator = cmds.spaceLocator(name=":" + name + "_locatorView#")[0]
                    created_locator_ids.extend(cmds.ls(locator, uuid=True) or [])
                    # Record ownership under the group before any matching can fail.
                    locator = cmds.parent(locator, group)[0]
                    locator = (cmds.ls(locator, long=True) or [locator])[0]
                    cmds.xform(locator, worldSpace=True, matrix=matrices[source])
                    shapes = cmds.listRelatives(locator, shapes=True, type="locator", fullPath=True) or []
                    for shape in shapes:
                        for axis in "XYZ":
                            cmds.setAttr(shape + ".localScale" + axis, size)
                    if match_mode == "constraints":
                        for command, suffix in (("parentConstraint", "parentConstraint#"),
                                                ("scaleConstraint", "scaleConstraint#")):
                            for node in _constraint_command(command,source, locator, maintainOffset=False,
                                                name="locatorView_" + suffix, _scope=constraint_scope) or []:
                                owned_path = locator + "|" + node.rsplit("|", 1)[-1]
                                constraints.append(owned_path if cmds.objExists(owned_path) else node)
                    locators.append(locator)
                members = cmds.listRelatives(group, allDescendents=True, fullPath=True) or []
                member_ids = list(dict.fromkeys([(cmds.ls(node, uuid=True) or [node])[0] for node in members]+created_locator_ids))
                cmds.addAttr(group, longName=_LOCATOR_VIEW_MEMBERS, dataType="string", hidden=True)
                cmds.setAttr(group + "." + _LOCATOR_VIEW_MEMBERS, json.dumps(member_ids), type="string")
                cmds.setAttr(group + "." + _LOCATOR_VIEW_MEMBERS, lock=True)
            except Exception:
                if group and cmds.objExists(group):
                    _constraint_delete_owned(created_locator_ids+[_constraint_uuid(group)])
                # A failed parent command can leave a locator outside the new group.
                for identity in created_locator_ids:
                    remaining = cmds.ls(identity, long=True) or []
                    if remaining:
                        cmds.delete(remaining)
                raise
            # Keep the previous view until the replacement has completed successfully.
            if previous_groups:
                try:
                    for old_group in previous_groups:
                        _constraint_delete_owned(json.loads(cmds.getAttr(old_group+"."+_LOCATOR_VIEW_MEMBERS))+[_constraint_uuid(old_group)])
                except Exception:
                    if cmds.objExists(group):
                        _constraint_delete_owned(created_locator_ids+[_constraint_uuid(group)])
                    raise
    finally:
        _restore_locator_view_selection(selection)
    return {"joint": joint, "group": group, "locators": locators, "constraints": constraints,
            "size": size, "include_children": bool(include_children), "match_mode": match_mode}


def delete_locator_view(joint):
    """Delete only this joint's tagged Locator View groups, not legacy guide locators."""
    groups = find_locator_view_groups(joint)
    for group in groups:
        _check_locator_view_members(group)
    if not groups:
        return []
    selection = cmds.ls(selection=True, long=True) or []
    try:
        with _tool_action("DeleteLocatorView"):
            for group in groups:
                _constraint_delete_owned(json.loads(cmds.getAttr(group+"."+_LOCATOR_VIEW_MEMBERS))+[_constraint_uuid(group)])
    finally:
        _restore_locator_view_selection(selection)
    return groups


_IK_GUIDE_TAG = "rtkGuideIKVersion"
_IK_GUIDE_STATE = "rtkGuideIKState"
_IK_GUIDE_ROOT = "rtkGuideIKFirstJoint"


def calculate_guide_ik_pole(first, second, third, distance_scale=1.0):
    """Project B onto line AC, then extend from B along projection-to-B."""
    points = [tuple(float(v) for v in point) for point in (first, second, third)]
    if any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in points):
        raise ValueError("Joint positions must contain three finite coordinates.")
    distance_scale = float(distance_scale)
    if not math.isfinite(distance_scale) or distance_scale <= 0:
        raise ValueError("Pole distance must be a finite, positive multiplier.")
    a, b, c = points
    ac = tuple(c[i] - a[i] for i in range(3))
    ab = tuple(b[i] - a[i] for i in range(3))
    bc = tuple(c[i] - b[i] for i in range(3))
    length_ab = math.sqrt(sum(v*v for v in ab))
    length_bc = math.sqrt(sum(v*v for v in bc))
    span_sq = sum(v*v for v in ac)
    chain_length = length_ab + length_bc
    tolerance = max(chain_length * 1e-6, 1e-8)
    if min(length_ab, length_bc, math.sqrt(span_sq)) <= tolerance:
        raise ValueError("The joints overlap or the first-to-third span is too short.")
    t = sum(ab[i]*ac[i] for i in range(3)) / span_sq
    projection = tuple(a[i] + t*ac[i] for i in range(3))
    outward = tuple(b[i] - projection[i] for i in range(3))
    bend = math.sqrt(sum(v*v for v in outward))
    if bend <= tolerance:
        raise ValueError("The joint chain is straight. Give the second joint a slight bend before building IK.")
    pole = tuple(b[i] + outward[i]/bend * chain_length * distance_scale for i in range(3))
    return {"projection": projection, "position": pole, "chain_length": chain_length}


def _guide_ik_uuid(node):
    identities = cmds.ls(node, uuid=True) or []
    if len(identities) != 1:
        raise ValueError("IK node is missing or ambiguous: {}".format(node))
    return identities[0]


def _guide_ik_resolve_uuid(identity):
    matches = cmds.ls(identity, long=True) or []
    if len(matches) > 1:
        raise ValueError("Instanced IK members are not supported: {}".format(identity))
    return matches[0] if matches else None


def _guide_ik_joint(joint):
    node = _resolve_hierarchy_root(joint)
    if cmds.nodeType(node) != "joint":
        raise ValueError("Choose a joint for each IK field.")
    if len(cmds.ls(node, long=True, allPaths=True) or []) != 1:
        raise ValueError("Instanced joints are not supported: {}".format(node))
    return node


def find_guide_ik_systems(first_joint):
    """Return only tagged systems linked to the chosen first joint."""
    first = _guide_ik_joint(first_joint)
    groups = []
    for plug in cmds.listConnections(first + ".message", source=False, destination=True, plugs=True) or []:
        node, attribute = plug.rsplit(".", 1)
        if attribute != _IK_GUIDE_ROOT:
            continue
        for group in cmds.ls(node, long=True) or []:
            if (cmds.nodeType(group) == "transform"
                    and cmds.attributeQuery(_IK_GUIDE_TAG, node=group, exists=True)
                    and cmds.getAttr(group + "." + _IK_GUIDE_TAG) == "1"
                    and group not in groups):
                groups.append(group)
    return groups


def _guide_ik_snapshot(joints):
    records = []
    for joint in joints:
        records.append({"uuid": _guide_ik_uuid(joint),
                        "rotate": list(cmds.getAttr(joint + ".rotate")[0]),
                        "ikBlend": cmds.getAttr(joint + ".ikBlend")
                            if cmds.attributeQuery("ikBlend", node=joint, exists=True) else None})
    return records


def _guide_ik_restore_pose(records):
    for record in records:
        joint = _guide_ik_resolve_uuid(record["uuid"])
        if not joint:
            continue
        cmds.setAttr(joint + ".rotate", *record["rotate"], type="double3")
        if record["ikBlend"] is not None and cmds.attributeQuery("ikBlend", node=joint, exists=True):
            cmds.setAttr(joint + ".ikBlend", record["ikBlend"])


def plan_guide_ik(first_joint, second_joint, third_joint, control_size=1.0, pole_distance=1.0):
    joints = [_guide_ik_joint(j) for j in (first_joint, second_joint, third_joint)]
    if len(set(_guide_ik_uuid(j) for j in joints)) != 3:
        raise ValueError("Choose three different joints.")
    for parent, child in zip(joints, joints[1:]):
        if (cmds.listRelatives(child, parent=True, fullPath=True) or []) != [parent]:
            raise ValueError("Use a consecutive chain: first joint → second joint → third joint.")
    control_size = float(control_size)
    if not math.isfinite(control_size) or control_size <= 0:
        raise ValueError("Control size must be a finite, positive number.")
    if find_guide_ik_systems(joints[0]):
        raise ValueError("An IK system already exists for this first joint. Remove it before building again.")
    ids = set(_guide_ik_uuid(j) for j in joints)
    for handle in cmds.ls(type="ikHandle", long=True) or []:
        affected = cmds.ikHandle(handle, query=True, jointList=True) or []
        effector = cmds.ikHandle(handle, query=True, endEffector=True)
        if effector:
            affected.extend(cmds.listRelatives(effector, parent=True, fullPath=True) or [])
            affected.extend(cmds.listConnections(effector + ".translate", source=True, destination=False, type="joint") or [])
        if any(_guide_ik_uuid(j) in ids for j in affected):
            raise ValueError("The chain overlaps an existing IK handle: {}".format(handle))
    for joint in joints:
        if (cmds.lockNode(joint, query=True, lock=True) or [False])[0]:
            raise ValueError("Joint is locked: {}".format(joint))
        if cmds.referenceQuery(joint, isNodeReferenced=True):
            raise ValueError("Build IK on editable, local joints: {}".format(joint))
        for attr in ("rotate", "rotateX", "rotateY", "rotateZ", "ikBlend"):
            if not cmds.attributeQuery(attr, node=joint, exists=True):
                continue
            plug = joint + "." + attr
            if cmds.getAttr(plug, lock=True) or cmds.listConnections(plug, source=True, destination=False):
                raise ValueError("Joint attribute is locked or already driven: {}".format(plug))
    positions = [cmds.xform(j, query=True, worldSpace=True, translation=True) for j in joints]
    pole = calculate_guide_ik_pole(*positions, distance_scale=pole_distance)
    return {"joints": joints, "control_size": control_size, "pole": pole,
            "pose": _guide_ik_snapshot(joints)}


def _check_guide_ik_removal(group):
    """Validate every owned descendant, including the effector outside the group."""
    try:
        state = json.loads(cmds.getAttr(group + "." + _IK_GUIDE_STATE))
        if (not isinstance(state, dict) or not isinstance(state["members"], list)
                or not state["members"] or not all(isinstance(i, str) for i in state["members"])
                or not isinstance(state["joints"], list) or len(state["joints"]) != 3):
            raise ValueError("Invalid IK state")
        for record in state["joints"]:
            if (not isinstance(record["uuid"], str) or len(record["rotate"]) != 3
                    or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in record["rotate"])
                    or (record["ikBlend"] is not None and (not isinstance(record["ikBlend"], (int, float)) or not math.isfinite(record["ikBlend"])))):
                raise ValueError("Invalid joint pose data")
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("Cannot validate IK system '{}': {}".format(group, exc))
    identities = set(state["members"])
    joint_ids = {record["uuid"] for record in state["joints"]}
    if len(joint_ids) != 3 or joint_ids & identities:
        raise ValueError("IK state contains invalid joint/member ownership.")
    roots = cmds.listConnections(group + "." + _IK_GUIDE_ROOT, source=True, destination=False) or []
    if len(roots) != 1 or _guide_ik_uuid(roots[0]) != state["joints"][0]["uuid"]:
        raise ValueError("IK first-joint link does not match its saved pose.")
    if _guide_ik_uuid(group) not in identities:
        raise ValueError("IK group ownership data is missing.")
    members = [node for identity in state["members"]
               for node in [_guide_ik_resolve_uuid(identity)] if node]
    for node in members:
        if cmds.referenceQuery(node, isNodeReferenced=True) or (cmds.lockNode(node, query=True, lock=True) or [False])[0]:
            raise ValueError("IK member is locked or referenced: {}".format(node))
        for child in cmds.listRelatives(node, allDescendents=True, fullPath=True) or []:
            if _guide_ik_uuid(child) not in identities:
                raise ValueError("Move unrelated object '{}' out of the IK system before removing it.".format(child))
    for record in state["joints"]:
        joint = _guide_ik_resolve_uuid(record["uuid"])
        if not joint:
            continue
        if cmds.referenceQuery(joint, isNodeReferenced=True) or (cmds.lockNode(joint, query=True, lock=True) or [False])[0]:
            raise ValueError("Cannot keep the pose of a locked or referenced joint: {}".format(joint))
        for attr in ("rotate", "rotateX", "rotateY", "rotateZ", "ikBlend"):
            if not cmds.attributeQuery(attr, node=joint, exists=True):
                continue
            plug = joint + "." + attr
            if cmds.getAttr(plug, lock=True):
                raise ValueError("Unlock '{}' before removing IK.".format(plug))
            for driver in cmds.listConnections(plug, source=True, destination=False) or []:
                if _guide_ik_uuid(driver) not in identities:
                    raise ValueError("Joint has a new external driver: {}. Remove it before removing IK.".format(plug))
    return state, members


def _guide_ik_delete_owned(identities):
    _constraint_delete_owned(identities)


def build_guide_ik(first_joint, second_joint, third_joint, control_size=1.0, pole_distance=1.0):
    """Create an RP handle, end controller and calculated pole controller."""
    plan = plan_guide_ik(first_joint, second_joint, third_joint, control_size, pole_distance)
    first, second, third = plan["joints"]
    label = first.rsplit("|", 1)[-1].replace(":", "_")
    prefix = ":" + label + "_guideIK_" + uuid.uuid4().hex[:8] + "_"
    selection = cmds.ls(selection=True, long=True) or []
    created = []

    def remember(node):
        identity = _guide_ik_uuid(node)
        if identity not in created:
            created.append(identity)
        return node

    constraint_scope=_constraint_context(label+'_GuideIK',remember)
    try:
        with _tool_action("BuildGuideIK"):
            try:
                group = remember(cmds.group(empty=True, name=prefix + "grp#"))
                group = cmds.ls(group, long=True)[0]
                end_offset = remember(cmds.group(empty=True, name=prefix + "end_offset#", parent=group))
                cmds.matchTransform(end_offset, third, position=True, rotation=True)
                end = remember(cmds.circle(name=prefix + "end_ctrl#", normal=(0, 1, 0),
                    radius=plan["control_size"], constructionHistory=False)[0])
                end = cmds.parent(end, end_offset, relative=True)[0]
                end = cmds.ls(end, long=True)[0]
                pole_offset = remember(cmds.group(empty=True, name=prefix + "pole_offset#", parent=group))
                cmds.xform(pole_offset, worldSpace=True, translation=plan["pole"]["position"])
                s = plan["control_size"] * .6
                pole = remember(cmds.curve(name=prefix + "pole_ctrl#", degree=1,
                    point=[(0,s,0), (s,0,0), (0,-s,0), (-s,0,0), (0,s,0),
                           (0,0,s), (0,-s,0), (0,0,-s), (0,s,0)]))
                pole = cmds.parent(pole, pole_offset, relative=True)[0]
                pole = cmds.ls(pole, long=True)[0]
                for control, color in ((end, 17), (pole, 13)):
                    for shape in cmds.listRelatives(control, shapes=True, fullPath=True) or []:
                        remember(shape)
                        cmds.setAttr(shape + ".overrideEnabled", True)
                        cmds.setAttr(shape + ".overrideColor", color)
                    for axis in "XYZ":
                        cmds.setAttr(control + ".scale" + axis, lock=True, keyable=False)
                        if control == pole:
                            cmds.setAttr(control + ".rotate" + axis, lock=True, keyable=False)
                    cmds.setAttr(control + ".visibility", keyable=False)
                handle, effector = cmds.ikHandle(name=prefix + "handle#", startJoint=first,
                    endEffector=third, solver="ikRPsolver")
                remember(handle)
                remember(effector)  # Maya places this beneath the original joint chain.
                handle = cmds.parent(handle, end, absolute=True)[0]
                handle = cmds.ls(handle, long=True)[0]
                cmds.setAttr(handle + ".visibility", False)
                constraints = _constraint_command('poleVectorConstraint',pole, handle, name=prefix + "poleConstraint#", _scope=constraint_scope)
                for node in constraints:
                    remember(node)
                for node in _constraint_command('orientConstraint',end, third, maintainOffset=True, name=prefix + "endOrient#", _scope=constraint_scope):
                    remember(node)
                # Constraints can be DAG children outside our group; record them too.
                for node in cmds.listRelatives(group, allDescendents=True, fullPath=True) or []:
                    remember(node)
                cmds.addAttr(group, longName=_IK_GUIDE_TAG, dataType="string", hidden=True)
                cmds.setAttr(group + "." + _IK_GUIDE_TAG, "1", type="string", lock=True)
                cmds.addAttr(group, longName=_IK_GUIDE_ROOT, attributeType="message", hidden=True)
                cmds.connectAttr(first + ".message", group + "." + _IK_GUIDE_ROOT)
                state = {"members": created[:], "joints": plan["pose"]}
                cmds.addAttr(group, longName=_IK_GUIDE_STATE, dataType="string", hidden=True)
                cmds.setAttr(group + "." + _IK_GUIDE_STATE, json.dumps(state), type="string", lock=True)
            except Exception:
                # Delete only UUIDs captured during this build, including loose nodes.
                _guide_ik_delete_owned(created)
                _guide_ik_restore_pose(plan["pose"])
                raise
    finally:
        _restore_locator_view_selection(selection)
    return {"group": group, "joints": plan["joints"], "end_controller": end,
            "pole_controller": pole, "handle": handle, "pole_position": plan["pole"]["position"]}


def _guide_ik_current_world_pose(checked):
    """Sample the evaluated pose while all handles and constraints still exist."""
    poses = {}
    for state, _members in checked:
        for record in state["joints"]:
            joint = _guide_ik_resolve_uuid(record["uuid"])
            if not joint or record["uuid"] in poses:
                continue
            if len(cmds.ls(joint, long=True, allPaths=True) or []) != 1:
                raise ValueError("Instanced joints cannot retain an unambiguous IK pose: {}".format(joint))
            matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
            rotation = cmds.xform(joint, query=True, worldSpace=True, rotation=True)
            if (len(matrix) != 16 or len(rotation) != 3
                    or not all(math.isfinite(v) for v in matrix + rotation)):
                raise ValueError("Joint has an invalid evaluated transform: {}".format(joint))
            poses[record["uuid"]] = {"uuid": record["uuid"], "matrix": matrix,
                "rotation": rotation, "depth": joint.count("|"),
                "joint_orient": list(cmds.getAttr(joint + ".jointOrient")[0]),
                "rotate_axis": list(cmds.getAttr(joint + ".rotateAxis")[0])}
    return sorted(poses.values(), key=lambda pose: pose["depth"])


def _guide_ik_keep_world_pose(poses):
    # Solve the preserved world orientation through Maya's constraint math,
    # which accounts for jointOrient, rotate order and parent inverse/scale.
    # Only the resulting local rotate values are retained. T/S remain untouched.
    for pose in poses:
        joint = _guide_ik_resolve_uuid(pose["uuid"])
        if not joint:
            raise RuntimeError("A driven joint disappeared during IK removal.")
        proxy, constraints = None, []
        try:
            proxy = cmds.createNode("transform", name=":rtkKeepIKPose_" + uuid.uuid4().hex, skipSelect=True)
            cmds.xform(proxy, worldSpace=True, matrix=pose["matrix"])
            constraints = _constraint_command('orientConstraint',proxy, joint, maintainOffset=False,
                name=":rtkKeepIKPoseConstraint_" + uuid.uuid4().hex) or []
            local_rotation = cmds.getAttr(joint + ".rotate")[0]
            if len(local_rotation) != 3 or not all(math.isfinite(v) for v in local_rotation):
                raise RuntimeError("Could not evaluate the preserved orientation of '{}'.".format(joint))
            cmds.delete(constraints)
            constraints = []
            cmds.setAttr(joint + ".rotate", *local_rotation, type="double3")
        finally:
            remaining = [node for node in constraints if cmds.objExists(node)]
            if remaining:
                cmds.delete(remaining)
            if proxy and cmds.objExists(proxy):
                cmds.delete(proxy)
    # Validate the evaluated world pose, not Euler values which can wrap.
    for pose in poses:
        joint = _guide_ik_resolve_uuid(pose["uuid"])
        actual = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
        if (len(actual) != 16 or any(not math.isfinite(a) or abs(a-b) > 1e-5*max(1.0, abs(a), abs(b))
               for a,b in zip(actual, pose["matrix"]))):
            raise RuntimeError("Could not keep the current world position/orientation of '{}'.".format(joint))
        for attr, key in (("jointOrient", "joint_orient"), ("rotateAxis", "rotate_axis")):
            values = cmds.getAttr(joint + "." + attr)[0]
            if any(abs(a-b) > 1e-8 for a,b in zip(values, pose[key])):
                raise RuntimeError("Joint orientation definition changed while removing IK: {}.{}".format(joint, attr))


def remove_guide_ik(first_joint):
    """Delete generated IK nodes and retain the currently evaluated joint pose."""
    groups = find_guide_ik_systems(first_joint)
    checked = [_check_guide_ik_removal(group) for group in groups]
    if not checked:
        return []
    # Capture ALL affected chains before deleting even one driver.
    poses = _guide_ik_current_world_pose(checked)
    selection = cmds.ls(selection=True, long=True) or []
    can_rollback = _TOOL_UNDO_DEPTH == 0 and cmds.undoInfo(query=True, state=True)
    undo_name = "RemoveGuideIK_" + uuid.uuid4().hex
    changed = False
    try:
        try:
            with _tool_action(undo_name):
                for state, _members in checked:
                    changed = True
                    _guide_ik_delete_owned(state["members"])
                _guide_ik_keep_world_pose(poses)
                _constraint_prune()
        except Exception as exc:
            # Undo only this tool's completed top-level chunk, never prior work
            # or a caller's still-open chunk. A unique name prevents confusing
            # this action with an earlier removal. Deleted drivers are restored.
            if changed and can_rollback and cmds.undoInfo(query=True, undoName=True) == undo_name:
                cmds.undo()
                raise RuntimeError("IK removal was rolled back to keep the joints and IK system intact: {}".format(exc)) from exc
            raise
    finally:
        _restore_locator_view_selection(selection)
    return groups


def _guide_match_set_channels(source, target, prefixes, position, rotation, scale):
    """Solve on an unconnected copy, then author the actual channels with setAttr."""
    helpers = []
    try:
        helpers = cmds.duplicate(target, parentOnly=True, returnRootsOnly=True,
            inputConnections=False, upstreamNodes=False, name=":rtkSetMatch_" + uuid.uuid4().hex)
        if len(helpers) != 1:
            raise RuntimeError("Could not create one temporary transform for matching.")
        helper = cmds.ls(helpers[0], long=True)[0]
        definitions = {attribute:cmds.getAttr(helper+"."+attribute) for attribute in ("jointOrient","rotateAxis")
                       if cmds.nodeType(helper)=="joint"}
        cmds.matchTransform(helper, source, position=bool(position), rotation=bool(rotation), scale=bool(scale))
        if any(cmds.getAttr(helper+"."+attribute) != value for attribute,value in definitions.items()):
            raise RuntimeError("The match solver changed the joint orientation definition.")
        values = [(prefix+axis, float(cmds.getAttr(helper+"."+prefix+axis)))
                  for prefix in prefixes for axis in "XYZ"]
        if not all(math.isfinite(value) for attribute,value in values):
            raise ValueError("The matched transform contains non-finite channel values.")
    finally:
        for helper in helpers:
            if cmds.objExists(helper):
                cmds.delete(helper)
    # Solve and clean up before touching Target; only requested TRS channels change.
    for attribute,value in values:
        cmds.setAttr(target+"."+attribute, value)
    for attribute,value in values:
        actual = float(cmds.getAttr(target+"."+attribute))
        if not math.isfinite(actual) or abs(actual-value) > 1e-5*max(1.,abs(value)):
            raise RuntimeError("Maya did not retain the set value on '{}.{}'; its driver may be recomputing the channel.".format(target,attribute))


def match_two_transforms(source, target, position=True, rotation=True, scale=False, method="set"):
    """Match once using direct channel setting (SDK authoring) or strict native matching."""
    if method not in ("set", "native"):
        raise ValueError("Choose Set channel values or Native match.")
    source,target = _resolve_hierarchy_root(source),_resolve_hierarchy_root(target)
    if not any((position,rotation,scale)):
        raise ValueError("Enable Position, Rotation or Scale.")
    if _guide_ik_uuid(source) == _guide_ik_uuid(target):
        raise ValueError("Source and Target must be different objects.")
    if source.startswith(target+"|"):
        raise ValueError("Source is below Target. Choose a reference that will not move with Target.")
    for node in (source,target):
        if len(cmds.ls(node,long=True,allPaths=True) or []) != 1:
            raise ValueError("Choose non-instanced Source and Target objects.")
    if (cmds.lockNode(target,query=True,lock=True) or [False])[0]:
        raise ValueError("Target node is locked.")
    prefixes = [name for enabled,name in ((position,"translate"),(rotation,"rotate"),(scale,"scale")) if enabled]
    inputs = {}
    for prefix in prefixes:
        for attribute in (prefix,) + tuple(prefix+axis for axis in "XYZ"):
            plug = target+"."+attribute
            if cmds.getAttr(plug,lock=True):
                raise ValueError("Target channel is locked: {}".format(plug))
            inputs[plug] = sorted(cmds.listConnections(plug,source=True,destination=False,plugs=True) or [])
            if method == "native" and inputs[plug]:
                raise ValueError("Target channel has animation or an incoming connection: {}".format(plug))
            if method == "native" and not cmds.getAttr(plug,settable=True):
                raise ValueError("Target channel is not writable: {}".format(plug))
    if _TOOL_UNDO_DEPTH or not cmds.undoInfo(query=True,state=True):
        raise ValueError("Enable Maya Undo and match outside another tool action so a failed match can be rolled back.")
    selection = cmds.ls(selection=True,long=True) or []
    undo_name = "MatchTwoTransforms_"+uuid.uuid4().hex
    definitions = {attribute:cmds.getAttr(target+"."+attribute) for attribute in ("jointOrient","rotateAxis")
                   if cmds.nodeType(target)=="joint"}
    changed = False
    try:
        try:
            with _tool_action(undo_name):
                changed = True
                if method == "set":
                    _guide_match_set_channels(source,target,prefixes,position,rotation,scale)
                else:
                    cmds.matchTransform(target,source,position=bool(position),rotation=bool(rotation),scale=bool(scale))
                for plug,previous in inputs.items():
                    if sorted(cmds.listConnections(plug,source=True,destination=False,plugs=True) or []) != previous:
                        raise RuntimeError("Match changed an incoming connection: {}".format(plug))
                for attribute,value in definitions.items():
                    if cmds.getAttr(target+"."+attribute) != value:
                        raise RuntimeError("Match changed the joint orientation definition: {}".format(attribute))
        except Exception as exc:
            if changed and cmds.undoInfo(query=True,undoName=True)==undo_name:
                cmds.undo()
                raise RuntimeError("Match was rolled back; Target and its inputs were kept: {}".format(exc)) from exc
            raise
    finally:
        _restore_locator_view_selection(selection)
    return {"source":source,"target":target,"position":bool(position),"rotation":bool(rotation),"scale":bool(scale),"method":method}


class MatchTransformsPanel(QtWidgets.QGroupBox):
    def __init__(self,parent=None):
        super(MatchTransformsPanel,self).__init__("Match 2 transforms · Target → Source",parent)
        form = QtWidgets.QFormLayout(self)
        self.source,self.target = QtWidgets.QLineEdit(),QtWidgets.QLineEdit()
        for field,label in ((self.source,"Source (reference):"),(self.target,"Target (move):")):
            field.setPlaceholderText("Transform, joint or controller")
            row = QtWidgets.QHBoxLayout()
            row.addWidget(field,1)
            get = QtWidgets.QPushButton("Get selected")
            get.clicked.connect(lambda _checked=False,field=field:self._get(field))
            row.addWidget(get)
            form.addRow(label,row)
        row = QtWidgets.QHBoxLayout()
        both = QtWidgets.QPushButton("Get both from selection")
        both.setToolTip("Select Source first, then Shift-select Target.")
        both.clicked.connect(self._get_both)
        swap = QtWidgets.QPushButton("Swap")
        swap.clicked.connect(self._swap)
        row.addWidget(both)
        row.addWidget(swap)
        form.addRow(row)
        row = QtWidgets.QHBoxLayout()
        self.position,self.rotation,self.scale = QtWidgets.QCheckBox("Position"),QtWidgets.QCheckBox("Rotation"),QtWidgets.QCheckBox("Scale")
        self.position.setChecked(True)
        self.rotation.setChecked(True)
        for check in (self.position,self.rotation,self.scale): row.addWidget(check)
        form.addRow("Match:",row)
        self.method = QtWidgets.QComboBox()
        self.method.addItem("Set channel values · SDK authoring", "set")
        self.method.addItem("Native match · unconnected channels", "native")
        self.method.setToolTip("Set channel values attempts setAttr while preserving SDK inputs. Drivers can recompute the pose later. Native match keeps the previous strict connection checks.")
        form.addRow("Method:",self.method)
        apply = QtWidgets.QPushButton("Match Target to Source")
        apply.setProperty("role","primary")
        apply.clicked.connect(self._apply)
        form.addRow(apply)
        self.status = QtWidgets.QLabel("Set channel values supports SDK pose authoring without disconnecting inputs. Position/Rotation on; Scale optional. Undo restores Target.")
        self.status.setWordWrap(True)
        self.status.setProperty("role","muted")
        form.addRow(self.status)

    def _get(self,field):
        try:
            selection = cmds.ls(selection=True,long=True) or []
            if len(selection)!=1: raise ValueError("Select one transform or joint.")
            field.setText(_resolve_hierarchy_root(selection[0]))
        except (ValueError,RuntimeError) as exc:
            self.status.setText(str(exc))

    def _get_both(self,*_args):
        try:
            selection = cmds.ls(selection=True,long=True) or []
            if len(selection)!=2: raise ValueError("Select Source first, then Shift-select Target.")
            source,target = [_resolve_hierarchy_root(node) for node in selection]
            self.source.setText(source)
            self.target.setText(target)
        except (ValueError,RuntimeError) as exc:
            self.status.setText(str(exc))

    def _swap(self,*_args):
        source,target = self.source.text(),self.target.text()
        self.source.setText(target)
        self.target.setText(source)

    def _apply(self,*_args):
        try:
            result = match_two_transforms(self.source.text(),self.target.text(),self.position.isChecked(),self.rotation.isChecked(),self.scale.isChecked(),method=self.method.currentData())
            self.status.setText("Matched {} to {}. Undo restores the previous transform.{}".format(result["target"],result["source"],
                " SDK inputs stay connected; changing their drivers can recompute this pose." if result["method"] == "set" else ""))
        except (ValueError,RuntimeError) as exc:
            self.status.setText(str(exc))
            cmds.warning(str(exc))


class TabMiniRig(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super(TabMiniRig, self).__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)

        # Snap Center
        grp1 = QtWidgets.QGroupBox("1. Match Transform to Vertex Center")
        lyt1 = QtWidgets.QVBoxLayout(grp1)
        row1 = QtWidgets.QHBoxLayout()
        self.le_match = QtWidgets.QLineEdit(); self.le_match.setPlaceholderText("Target transform (optional)")
        btn_match = QtWidgets.QPushButton("<< Load"); btn_match.clicked.connect(lambda: self.le_match.setText(cmds.ls(sl=True)[0] if cmds.ls(sl=True) else ""))
        row1.addWidget(self.le_match); row1.addWidget(btn_match)
        btn_snap = QtWidgets.QPushButton("Snap / Create to Center")
        btn_snap.clicked.connect(self.snap_center)
        lyt1.addLayout(row1); lyt1.addWidget(btn_snap)

        # Locators
        grp2 = QtWidgets.QGroupBox("2. Generate Guide Locators")
        lyt2 = QtWidgets.QFormLayout(grp2)
        r_row = QtWidgets.QHBoxLayout(); self.le_root = QtWidgets.QLineEdit(); btn_r = QtWidgets.QPushButton("<<"); btn_r.clicked.connect(lambda: self.le_root.setText(cmds.ls(sl=True)[0] if cmds.ls(sl=True) else ""))
        r_row.addWidget(self.le_root); r_row.addWidget(btn_r)
        s_row = QtWidgets.QHBoxLayout(); self.le_sel = QtWidgets.QLineEdit(); btn_s = QtWidgets.QPushButton("<<"); btn_s.clicked.connect(lambda: self.le_sel.setText(",".join(cmds.ls(sl=True))))
        s_row.addWidget(self.le_sel); s_row.addWidget(btn_s)
        self.chk_sel = QtWidgets.QCheckBox("Selection Only"); self.spn_rad = QtWidgets.QDoubleSpinBox(); self.spn_rad.setValue(1.0)
        self.spn_rad.setRange(0.001, 10000.0)
        self.spn_rad.setDecimals(3)
        self._radius_timer = QtCore.QTimer(self)
        self._radius_timer.setSingleShot(True)
        self._radius_timer.setInterval(200)
        self._radius_timer.timeout.connect(self._apply_pending_radius)
        self.spn_rad.valueChanged.connect(lambda _value: self._radius_timer.start())
        self.spn_rad.editingFinished.connect(self._apply_pending_radius)
        lyt2.addRow("Root:", r_row); lyt2.addRow("List:", s_row)
        lyt2.addRow("", self.chk_sel); lyt2.addRow("Radius:", self.spn_rad)
        b_row = QtWidgets.QHBoxLayout()
        bg = QtWidgets.QPushButton("Generate"); bg.clicked.connect(self.gen_locs)
        bc = QtWidgets.QPushButton("Clean All"); bc.clicked.connect(self.clean_all_guides)
        b_row.addWidget(bg); b_row.addWidget(bc)
        lyt2.addRow(b_row)

        # Orient Joint
        grp3 = QtWidgets.QGroupBox("3. Orient Joint")
        lyt3 = QtWidgets.QFormLayout(grp3)
        self.cb_orient_aim_axis = QtWidgets.QComboBox()
        self.cb_orient_aim_axis.addItems(["X", "Y", "Z", "-X", "-Y", "-Z"])
        self.cb_orient_aim_axis.setCurrentText("X")
        self.cb_orient_up_axis = QtWidgets.QComboBox()
        self.cb_orient_up_axis.addItems(["X", "Y", "Z", "-X", "-Y", "-Z"])
        self.cb_orient_up_axis.setCurrentText("Y")
        self.cb_orient_up_mode = QtWidgets.QComboBox()
        self.cb_orient_up_mode.addItems(["Scene Up", "Object Rotation Up", "Object Up"])
        self.cb_orient_up_mode.setCurrentText("Scene Up")
        up_ref_row = QtWidgets.QHBoxLayout()
        self.le_orient_up_object = QtWidgets.QLineEdit()
        self.le_orient_up_object.setPlaceholderText("Used by Object Up modes; blank = joint parent")
        self.btn_orient_up_object = QtWidgets.QPushButton("<<")
        self.btn_orient_up_object.setFixedWidth(30)
        self.btn_orient_up_object.clicked.connect(self.load_orient_up_object)
        up_ref_row.addWidget(self.le_orient_up_object)
        up_ref_row.addWidget(self.btn_orient_up_object)

        # Scene Up does not use an Up Object. Disable these controls so the
        # UI makes that behavior explicit, and re-enable them for object modes.
        self.cb_orient_up_mode.currentTextChanged.connect(self.update_orient_up_object_state)
        self.update_orient_up_object_state(self.cb_orient_up_mode.currentText())
        self.chk_orient_children = QtWidgets.QCheckBox("Apply Children")
        self.chk_orient_children.setChecked(False)
        btn_orient = QtWidgets.QPushButton("Apply Orient Joint")
        btn_orient.clicked.connect(self.orient_joints)
        lyt3.addRow("Aim Axis:", self.cb_orient_aim_axis)
        lyt3.addRow("Up Axis:", self.cb_orient_up_axis)
        lyt3.addRow("Up Mode:", self.cb_orient_up_mode)
        lyt3.addRow("Up Object:", up_ref_row)
        lyt3.addRow("", self.chk_orient_children)
        lyt3.addRow(btn_orient)

        # --------------------------------------------------------------
        # Object-axis orientation offset
        # --------------------------------------------------------------
        orient_divider = QtWidgets.QFrame()
        orient_divider.setFrameShape(QtWidgets.QFrame.HLine)
        orient_divider.setFrameShadow(QtWidgets.QFrame.Sunken)
        lyt3.addRow(orient_divider)
        object_axis_label = QtWidgets.QLabel("Rotate Joint Orient Around Object Axis")
        lyt3.addRow(object_axis_label)
        self.spn_orient_rot_x = QtWidgets.QDoubleSpinBox()
        self.spn_orient_rot_y = QtWidgets.QDoubleSpinBox()
        self.spn_orient_rot_z = QtWidgets.QDoubleSpinBox()
        for spin in (self.spn_orient_rot_x, self.spn_orient_rot_y, self.spn_orient_rot_z):
            spin.setRange(-3600.0, 3600.0)
            spin.setDecimals(3)
            spin.setSingleStep(1.0)
            spin.setValue(0.0)
            spin.setSuffix(" deg")
        self.chk_object_rotate_children = QtWidgets.QCheckBox("Apply Children")
        self.chk_object_rotate_children.setChecked(False)
        btn_object_rotate = QtWidgets.QPushButton("Apply Object Axis Rotation")
        btn_object_rotate.clicked.connect(self.rotate_joint_object_axis)
        lyt3.addRow("Rot Axis X:", self.spn_orient_rot_x)
        lyt3.addRow("Rot Axis Y:", self.spn_orient_rot_y)
        lyt3.addRow("Rot Axis Z:", self.spn_orient_rot_z)
        lyt3.addRow("", self.chk_object_rotate_children)
        lyt3.addRow(btn_object_rotate)

        # Cleanup Keys
        grp4 = QtWidgets.QGroupBox("4. Safe Delete Timeline Keyframes")
        lyt4 = QtWidgets.QVBoxLayout(grp4)
        self.rad_sel = QtWidgets.QRadioButton("Selected & Hierarchy Below"); self.rad_all = QtWidgets.QRadioButton("All Objects in Scene")
        self.rad_sel.setChecked(True)
        btn_del = QtWidgets.QPushButton("Wipe Keys")
        btn_del.clicked.connect(self.del_keys)
        lyt4.addWidget(self.rad_sel); lyt4.addWidget(self.rad_all); lyt4.addWidget(btn_del)
        layout.addWidget(MatchTransformsPanel(self))
        layout.addWidget(grp1); layout.addWidget(grp2)
        layout.addWidget(self._build_locator_view_section())
        layout.addWidget(self._build_guide_ik_section())
        layout.addWidget(grp3); layout.addWidget(grp4); layout.addStretch()

    def _build_guide_ik_section(self):
        section = QtWidgets.QGroupBox("Three-Joint IK")
        form = QtWidgets.QFormLayout(section)
        self.le_guide_ik_joints = []
        for index, label in enumerate(("First joint:", "Second joint:", "Third joint:")):
            row = QtWidgets.QHBoxLayout()
            field = QtWidgets.QLineEdit()
            field.setPlaceholderText("Select the joint, then Get selected")
            self.le_guide_ik_joints.append(field)
            row.addWidget(field, 1)
            button = QtWidgets.QPushButton("Get selected")
            button.clicked.connect(lambda _checked=False, i=index: self._load_guide_ik_joint(i))
            row.addWidget(button)
            form.addRow(label, row)
        self.spn_guide_ik_size = QtWidgets.QDoubleSpinBox()
        self.spn_guide_ik_size.setRange(0.001, 10000.0)
        self.spn_guide_ik_size.setDecimals(3)
        self.spn_guide_ik_size.setValue(1.0)
        form.addRow("Control size:", self.spn_guide_ik_size)
        self.spn_guide_ik_distance = QtWidgets.QDoubleSpinBox()
        self.spn_guide_ik_distance.setRange(0.01, 100.0)
        self.spn_guide_ik_distance.setDecimals(2)
        self.spn_guide_ik_distance.setSingleStep(0.1)
        self.spn_guide_ik_distance.setValue(1.0)
        self.spn_guide_ik_distance.setSuffix(" × chain length")
        self.spn_guide_ik_distance.setToolTip("Distance outward from the second joint along the calculated pole direction.")
        form.addRow("Pole distance:", self.spn_guide_ik_distance)
        row = QtWidgets.QHBoxLayout()
        self.btn_guide_ik_build = QtWidgets.QPushButton("Build IK")
        self.btn_guide_ik_build.setProperty("role", "primary")
        self.btn_guide_ik_build.clicked.connect(self._build_guide_ik)
        self.btn_guide_ik_remove = QtWidgets.QPushButton("Remove IK")
        self.btn_guide_ik_remove.clicked.connect(self._remove_guide_ik)
        self.btn_guide_ik_remove.setToolTip("Uses First joint to find the system. Deletes generated IK nodes and keeps the joints in their current world pose.")
        row.addWidget(self.btn_guide_ik_build)
        row.addWidget(self.btn_guide_ik_remove)
        form.addRow(row)
        self.lbl_guide_ik_status = QtWidgets.QLabel("Choose a bent, consecutive three-joint chain. Build adds an end control and a pole control. Remove keeps the current joint pose.")
        self.lbl_guide_ik_status.setProperty("role", "muted")
        self.lbl_guide_ik_status.setWordWrap(True)
        form.addRow(self.lbl_guide_ik_status)
        return section

    def _load_guide_ik_joint(self, index):
        try:
            selected = cmds.ls(selection=True, long=True) or []
            if len(selected) != 1:
                raise ValueError("Select exactly one joint, then click Get selected.")
            self.le_guide_ik_joints[index].setText(_guide_ik_joint(selected[0]))
            self.lbl_guide_ik_status.setText("Joint loaded. Fill all three fields, then Build IK.")
        except (ValueError, RuntimeError) as exc:
            self.lbl_guide_ik_status.setText(str(exc))

    def _build_guide_ik(self, *_args):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            result = build_guide_ik(*(field.text() for field in self.le_guide_ik_joints),
                control_size=self.spn_guide_ik_size.value(), pole_distance=self.spn_guide_ik_distance.value())
            for field, joint in zip(self.le_guide_ik_joints, result["joints"]):
                field.setText(joint)
            self.lbl_guide_ik_status.setText("Built {}. Move the end control to pose the chain; move the pole control to set its bend. Remove keeps the current joint pose.".format(result["group"].rsplit("|", 1)[-1]))
        except (ValueError, RuntimeError) as exc:
            self.lbl_guide_ik_status.setText(str(exc))
            cmds.warning(str(exc))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _remove_guide_ik(self, *_args):
        try:
            groups = remove_guide_ik(self.le_guide_ik_joints[0].text())
            self.lbl_guide_ik_status.setText("Removed IK and kept the current joint position/orientation." if groups else "No generated IK system found for the first joint.")
        except (ValueError, RuntimeError) as exc:
            self.lbl_guide_ik_status.setText(str(exc))
            cmds.warning(str(exc))

    def _build_locator_view_section(self):
        section = QtWidgets.QGroupBox("Locator View")
        form = QtWidgets.QFormLayout(section)
        self.le_locator_view_joint = QtWidgets.QLineEdit()
        self.le_locator_view_joint.setPlaceholderText("Select a joint, then Load selected…")
        joint_row = QtWidgets.QHBoxLayout()
        joint_row.addWidget(self.le_locator_view_joint, 1)
        load = QtWidgets.QPushButton("Load selected")
        load.clicked.connect(self._load_locator_view_joint)
        joint_row.addWidget(load)
        form.addRow("Joint:", joint_row)
        self.spn_locator_view_size = QtWidgets.QDoubleSpinBox()
        self.spn_locator_view_size.setRange(0.001, 10000.0)
        self.spn_locator_view_size.setDecimals(3)
        self.spn_locator_view_size.setSingleStep(0.1)
        self.spn_locator_view_size.setValue(1.0)
        self.spn_locator_view_size.setToolTip("Locator shape size on X/Y/Z. Joint world scale also affects its displayed size.")
        form.addRow("Size:", self.spn_locator_view_size)
        self.chk_locator_view_children = QtWidgets.QCheckBox("Include child joints")
        self.chk_locator_view_children.setChecked(False)
        form.addRow("", self.chk_locator_view_children)
        self.cb_locator_view_match = QtWidgets.QComboBox()
        self.cb_locator_view_match.addItem("Constraints · follow joints", "constraints")
        self.cb_locator_view_match.addItem("World matrix · snapshot", "world_matrix")
        form.addRow("Match:", self.cb_locator_view_match)
        buttons = QtWidgets.QHBoxLayout()
        self.btn_locator_view_generate = QtWidgets.QPushButton("Generate")
        self.btn_locator_view_generate.clicked.connect(self._generate_locator_view)
        self.btn_locator_view_delete = QtWidgets.QPushButton("Delete View")
        self.btn_locator_view_delete.clicked.connect(self._delete_locator_view)
        self.btn_locator_view_delete.setToolTip("Delete only the Locator View groups for the joint in this field.")
        buttons.addWidget(self.btn_locator_view_generate)
        buttons.addWidget(self.btn_locator_view_delete)
        form.addRow(buttons)
        self.lbl_locator_view_status = QtWidgets.QLabel("Locators are grouped separately from the joint hierarchy. Generate replaces this joint's previous view.")
        self.lbl_locator_view_status.setProperty("role", "muted")
        self.lbl_locator_view_status.setWordWrap(True)
        form.addRow(self.lbl_locator_view_status)
        return section

    def _load_locator_view_joint(self, *_args):
        selection = cmds.ls(selection=True, long=True) or []
        try:
            if len(selection) != 1:
                raise ValueError("Select exactly one joint, then click Load selected.")
            self.le_locator_view_joint.setText(_resolve_locator_view_joint(selection[0]))
            self.lbl_locator_view_status.setText("Ready. Choose size, child scope, and matching mode, then Generate.")
        except (ValueError, RuntimeError) as exc:
            self.lbl_locator_view_status.setText(str(exc))

    def _generate_locator_view(self, *_args):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            result = generate_locator_view(self.le_locator_view_joint.text(),
                size=self.spn_locator_view_size.value(),
                include_children=self.chk_locator_view_children.isChecked(),
                match_mode=self.cb_locator_view_match.currentData())
            self.le_locator_view_joint.setText(result["joint"])
            self.lbl_locator_view_status.setText("Created {} locator(s) in {}. {}".format(
                len(result["locators"]), result["group"].rsplit("|", 1)[-1],
                "Following joints with constraints." if result["match_mode"] == "constraints" else "World-space snapshot; does not follow later joint edits."))
        except (ValueError, RuntimeError) as exc:
            self.lbl_locator_view_status.setText(str(exc))
            cmds.warning(str(exc))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _delete_locator_view(self, *_args):
        try:
            groups = delete_locator_view(self.le_locator_view_joint.text())
            self.lbl_locator_view_status.setText("Deleted {} Locator View group(s).".format(len(groups))
                if groups else "No Locator View exists for this joint.")
        except (ValueError, RuntimeError) as exc:
            self.lbl_locator_view_status.setText(str(exc))
            cmds.warning(str(exc))


    def snap_center(self):
        vtx = cmds.filterExpand(ex=True, sm=31)
        if not vtx:
            return cmds.warning("Select vertices first!")
        _begin_tool_undo("MiniRig_SnapCenter")
        try:
            bb = cmds.exactWorldBoundingBox(vtx)
            cx, cy, cz = (bb[0]+bb[3])/2, (bb[1]+bb[4])/2, (bb[2]+bb[5])/2
            tgt = self.le_match.text()
            if not tgt or not cmds.objExists(tgt):
                tgt = cmds.spaceLocator(n="vtx_center_loc")[0]
                self.le_match.setText(tgt)
            cmds.xform(tgt, ws=True, t=[cx, cy, cz])
        finally:
            _end_tool_undo()

    def gen_locs(self):
        tgts = [t.strip() for t in self.le_sel.text().split(",") if cmds.objExists(t.strip())] if self.chk_sel.isChecked() else ([self.le_root.text()] + (cmds.listRelatives(self.le_root.text(), ad=True, typ="transform", f=True) or [])) if cmds.objExists(self.le_root.text()) else []
        if not tgts:
            return cmds.warning("No valid guide targets found.")
        _begin_tool_undo("MiniRig_GenerateGuides")
        try:
            for t in tgts:
                if cmds.objExists(t.split("|")[-1]+"_GuideLoc"):
                    continue
                loc = cmds.spaceLocator(n=t.split("|")[-1]+"_GuideLoc")[0]
                cmds.matchTransform(loc, t)
                cmds.parent(loc, t)

            # Nested call joins this same Generate action.
            self._radius_timer.stop()
            self.update_live(self.spn_rad.value())
        finally:
            _end_tool_undo()

    def _apply_pending_radius(self):
        if self._radius_timer.isActive():
            self._radius_timer.stop()
        self.update_live(self.spn_rad.value())

    def update_live(self, val):
        shapes = []
        for loc in cmds.ls("*_GuideLoc", type="transform", long=True) or []:
            shapes.extend(cmds.listRelatives(loc, shapes=True, type="locator", fullPath=True) or [])
        changes = []
        for shape in shapes:
            for axis in "XYZ":
                plug = shape + ".localScale" + axis
                if cmds.getAttr(plug, settable=True) and abs(cmds.getAttr(plug) - val) > 1e-8:
                    changes.append(plug)
        if changes:
            with _tool_action("MiniRig_UpdateGuideRadius"):
                for plug in changes:
                    cmds.setAttr(plug, val)

    def clean_all_guides(self):
        guides = cmds.ls("*_GuideLoc", type="transform") or []
        if not guides:
            return
        _begin_tool_undo("MiniRig_CleanGuides")
        try:
            cmds.delete(guides)
        finally:
            _end_tool_undo()

    def update_orient_up_object_state(self, mode=None):
        mode = mode or self.cb_orient_up_mode.currentText()
        use_object = mode != "Scene Up"
        self.le_orient_up_object.setEnabled(use_object)
        self.btn_orient_up_object.setEnabled(use_object)

    def load_orient_up_object(self):

        # Scene Up intentionally ignores Up Object.
        if self.cb_orient_up_mode.currentText() == "Scene Up":
            return
        sel = cmds.ls(sl=True, long=True) or []
        if sel:
            self.le_orient_up_object.setText(sel[0])

    @staticmethod
    def _orient_axis_vector(axis_name):
        axis_map = {
            "X": (1, 0, 0),
            "Y": (0, 1, 0),
            "Z": (0, 0, 1),
            "-X": (-1, 0, 0),
            "-Y": (0, -1, 0),
            "-Z": (0, 0, -1),
        }
        return axis_map.get(axis_name, (1, 0, 0))

    @staticmethod
    def _orient_axis_family(axis_name):
        return axis_name.replace("-", "")

    def _collect_joints_for_orient(self, roots, apply_children):
        joints = []
        seen = set()
        for root in roots:
            root_long = (cmds.ls(root, long=True) or [root])[0]
            candidates = [root_long]
            if apply_children:
                candidates.extend(
                    cmds.listRelatives(
                        root_long,
                        allDescendents=True,
                        type="joint",
                        fullPath=True
                    ) or []
                )
            for jnt in candidates:
                long_name = (cmds.ls(jnt, long=True) or [jnt])[0]
                if long_name not in seen:
                    seen.add(long_name)
                    joints.append(long_name)

        # Parent first.  This is important when Apply Children is enabled:
        # every parent is oriented before its child is processed.
        joints.sort(key=lambda node: node.count("|"))
        return joints

    @staticmethod
    def _save_descendant_world_transforms(joint):
        """Snapshot descendant DAG transforms in world space.

        Reorienting a parent joint changes the evaluated world transform of its
        children.  Saving only translation is not enough: child world rotation
        (and potentially scale) can still change.  Store the complete world
        matrix so an orientation edit can leave the rest of the hierarchy
        visually and spatially untouched.
        """
        descendants = cmds.listRelatives(
            joint,
            allDescendents=True,
            fullPath=True
        ) or []
        result = []
        for child in descendants:
            if not cmds.objExists(child):
                continue

            # Shapes do not have an independently editable transform matrix.
            # Preserve joints and ordinary transform nodes only.
            node_type = cmds.nodeType(child)
            if node_type not in ("joint", "transform"):
                continue
            try:
                world_matrix = cmds.xform(
                    child,
                    query=True,
                    worldSpace=True,
                    matrix=True
                )
                result.append((child, world_matrix))
            except Exception as exc:
                cmds.warning(
                    "Could not snapshot child world transform '{}': {}".format(
                        child, exc
                    )
                )

        # Restore parent descendants first, then deeper nodes.  A deeper node's
        # final matrix is therefore applied after all of its ancestors have been
        # restored.
        result.sort(key=lambda item: item[0].count("|"))
        return result

    @staticmethod
    def _restore_descendant_world_transforms(saved_transforms):
        for child, world_matrix in saved_transforms:
            if cmds.objExists(child):
                try:
                    cmds.xform(
                        child,
                        worldSpace=True,
                        matrix=world_matrix
                    )
                except Exception as exc:
                    cmds.warning(
                        "Could not restore child world transform '{}': {}".format(
                            child, exc
                        )
                    )

    def orient_joints(self):

        # Preserve the user's exact selection state. Temporary constraints/buffers
        # created during the orient solve can otherwise change Maya's selection.
        original_selection = cmds.ls(sl=True, long=True) or []
        selected = cmds.ls(sl=True, type="joint", long=True) or []
        if not selected:
            return cmds.warning("Select at least one joint to orient.")
        aim_axis_name = self.cb_orient_aim_axis.currentText()
        up_axis_name = self.cb_orient_up_axis.currentText()
        if self._orient_axis_family(aim_axis_name) == self._orient_axis_family(up_axis_name):
            return cmds.warning("Aim Axis and Up Axis cannot use the same axis.")
        aim_vec = self._orient_axis_vector(aim_axis_name)
        up_vec = self._orient_axis_vector(up_axis_name)
        up_mode_label = self.cb_orient_up_mode.currentText()
        apply_children = self.chk_orient_children.isChecked()

        # Scene Up never reads or validates the Up Object field. A stale or
        # missing object in that field must not block Scene Up orientation.
        explicit_up_object = ""
        if up_mode_label != "Scene Up":
            explicit_up_object = self.le_orient_up_object.text().strip()
            if explicit_up_object and not cmds.objExists(explicit_up_object):
                return cmds.warning("Up Object '{}' does not exist.".format(explicit_up_object))
        joints = self._collect_joints_for_orient(selected, apply_children)
        if not joints:
            return cmds.warning("No valid joints found to orient.")

        def _make_world_buffer(source, suffix):
            """Create an unparented transform that snapshots source's world matrix.

            The helper has no DAG dependency on the joint being oriented, so using it
            as an aim/up reference cannot create the child->parent evaluation cycle
            that occurs when the live child joint is used directly.
            """
            if not source or not cmds.objExists(source):
                return None
            short_name = source.split("|")[-1].replace(":", "_")
            buffer_node = cmds.createNode(
                "transform",
                name="{}_{}#".format(short_name, suffix)
            )
            world_matrix = cmds.xform(
                source,
                query=True,
                worldSpace=True,
                matrix=True
            )
            cmds.xform(
                buffer_node,
                worldSpace=True,
                matrix=world_matrix
            )
            return buffer_node
        _begin_tool_undo("MiniRig_OrientJoint")
        oriented_count = 0
        skipped_count = 0
        try:
            for joint in joints:
                if not cmds.objExists(joint):
                    skipped_count += 1
                    continue
                child_joints = cmds.listRelatives(
                    joint,
                    children=True,
                    type="joint",
                    fullPath=True
                ) or []
                if not child_joints:
                    # A leaf joint has no direction to aim toward.
                    skipped_count += 1
                    continue

                # If a joint branches, use the first child as the orientation
                # direction.  IMPORTANT: do not aim at this live child directly,
                # because child.worldMatrix depends on the parent joint and would
                # create an aimConstraint evaluation cycle.
                aim_target = child_joints[0]
                saved_transforms = self._save_descendant_world_transforms(joint)

                # Up object: explicit UI object wins. Otherwise use the joint's
                # current parent as a convenient reference for object-based modes.
                up_object = explicit_up_object
                if not up_object:
                    parent = cmds.listRelatives(joint, parent=True, fullPath=True) or []
                    if parent:
                        up_object = parent[0]
                constraint = None
                aim_buffer = None
                up_buffer = None
                try:
                    # Snapshot the child before changing the parent joint.  This is
                    # the key cycle-safe target used by the temporary aimConstraint.
                    aim_buffer = _make_world_buffer(
                        aim_target,
                        "OrientAimBuffer"
                    )
                    if not aim_buffer:
                        raise RuntimeError(
                            "Could not create aim buffer for '{}'".format(aim_target)
                        )
                    if up_mode_label == "Scene Up":
                        constraint = _constraint_command('aimConstraint',
                            aim_buffer,
                            joint,
                            aimVector=aim_vec,
                            upVector=up_vec,
                            worldUpType="scene",
                            maintainOffset=False
                        )[0]
                    elif up_object and cmds.objExists(up_object):
                        # Buffer the up reference as well. This is especially
                        # important when the explicit Up Object lives somewhere
                        # under the joint hierarchy being reoriented.
                        up_buffer = _make_world_buffer(
                            up_object,
                            "OrientUpBuffer"
                        )
                        if not up_buffer:
                            raise RuntimeError(
                                "Could not create up buffer for '{}'".format(up_object)
                            )
                        world_up_type = (
                            "objectrotation"
                            if up_mode_label == "Object Rotation Up"
                            else "object"
                        )
                        constraint = _constraint_command('aimConstraint',
                            aim_buffer,
                            joint,
                            aimVector=aim_vec,
                            upVector=up_vec,
                            worldUpType=world_up_type,
                            worldUpObject=up_buffer,
                            worldUpVector=up_vec,
                            maintainOffset=False
                        )[0]
                    else:
                        # Object-based modes need an up reference. If none exists,
                        # use the default Scene Up behavior rather than failing.
                        cmds.warning(
                            "Joint '{}' has no Up Object; using Scene Up.".format(joint)
                        )
                        constraint = _constraint_command('aimConstraint',
                            aim_buffer,
                            joint,
                            aimVector=aim_vec,
                            upVector=up_vec,
                            worldUpType="scene",
                            maintainOffset=False
                        )[0]

                    # Bake the solved rotation: remove the temporary solver first,
                    # then push the current joint rotate into jointOrient.
                    if constraint and cmds.objExists(constraint):
                        cmds.delete(constraint)
                        constraint = None
                    cmds.makeIdentity(
                        joint,
                        apply=True,
                        translate=False,
                        rotate=True,
                        scale=False,
                        normal=False
                    )
                    oriented_count += 1
                except Exception as exc:
                    cmds.warning("Could not orient '{}': {}".format(joint, exc))
                    skipped_count += 1
                finally:
                    if constraint and cmds.objExists(constraint):
                        cmds.delete(constraint)

                    # Delete world-space helper transforms after the solve. They are
                    # temporary only and do not remain in the user's rig.
                    temp_nodes = [
                        node for node in (aim_buffer, up_buffer)
                        if node and cmds.objExists(node)
                    ]
                    if temp_nodes:
                        cmds.delete(temp_nodes)

                    # Preserve the hierarchy exactly: descendants return to the full
                    # world transforms they had before this joint was reoriented.
                    self._restore_descendant_world_transforms(saved_transforms)
            print(
                "Orient Joint complete. Oriented: {} | Skipped/leaf: {}".format(
                    oriented_count, skipped_count
                )
            )
        finally:
            _end_tool_undo()

            # Selection restoration is UI state, not part of the rig edit. Keep it
            # out of Maya's undo queue so Apply Orient Joint remains one undo step.
            undo_was_enabled = cmds.undoInfo(query=True, state=True)
            try:
                if undo_was_enabled:
                    cmds.undoInfo(stateWithoutFlush=False)
                valid_selection = [
                    item for item in original_selection
                    if cmds.objExists(item)
                ]
                if valid_selection:
                    cmds.select(valid_selection, replace=True)
                else:
                    cmds.select(clear=True)
            finally:
                if undo_was_enabled:
                    cmds.undoInfo(stateWithoutFlush=True)

    def rotate_joint_object_axis(self):

        # Preserve the exact user selection.  Object-axis orientation is a rig
        # edit and should not leave helper/descendant joints selected afterward.
        original_selection = cmds.ls(sl=True, long=True) or []
        selected = cmds.ls(sl=True, type="joint", long=True) or []
        if not selected:
            return cmds.warning("Select at least one joint to rotate around its object axis.")
        rot_x = self.spn_orient_rot_x.value()
        rot_y = self.spn_orient_rot_y.value()
        rot_z = self.spn_orient_rot_z.value()
        if abs(rot_x) < 1e-10 and abs(rot_y) < 1e-10 and abs(rot_z) < 1e-10:
            return cmds.warning("Rot Axis X/Y/Z are all 0. Nothing to apply.")
        apply_children = self.chk_object_rotate_children.isChecked()
        joints = self._collect_joints_for_orient(selected, apply_children)
        if not joints:
            return cmds.warning("No valid joints found for Object Axis Rotation.")
        _begin_tool_undo("MiniRig_ObjectAxisJointOrient")
        rotated_count = 0
        skipped_count = 0
        try:
            for joint in joints:
                if not cmds.objExists(joint):
                    skipped_count += 1
                    continue

                # Rotating a parent normally moves its descendants.  Snapshot their full
                # world transforms first so this operation changes only this joint's
                # orientation, not child position/rotation/scale in world space.
                saved_transforms = self._save_descendant_world_transforms(joint)
                try:
                    # relative + objectSpace means X/Y/Z are interpreted around the
                    # joint's CURRENT local/object axes, not world axes.
                    cmds.rotate(
                        rot_x,
                        rot_y,
                        rot_z,
                        joint,
                        relative=True,
                        objectSpace=True
                    )

                    # This is an orient-edit tool, not an animation rotate tool.
                    # Bake the local rotation into jointOrient so rotate channels
                    # return to zero while the new object-axis orientation remains.
                    cmds.makeIdentity(
                        joint,
                        apply=True,
                        translate=False,
                        rotate=True,
                        scale=False,
                        normal=False
                    )
                    rotated_count += 1
                except Exception as exc:
                    skipped_count += 1
                    cmds.warning(
                        "Could not apply Object Axis Rotation to '{}': {}".format(
                            joint, exc
                        )
                    )
                finally:
                    self._restore_descendant_world_transforms(saved_transforms)
            print(
                "Object Axis Joint Orient complete. Rotated: {} | Skipped: {} | "
                "Offset: ({:.3f}, {:.3f}, {:.3f})".format(
                    rotated_count, skipped_count, rot_x, rot_y, rot_z
                )
            )
        finally:
            _end_tool_undo()

            # Selection is UI state. Restore it without adding another item to the
            # Maya undo queue, preserving the one-button = one-undo behavior.
            undo_was_enabled = cmds.undoInfo(query=True, state=True)
            try:
                if undo_was_enabled:
                    cmds.undoInfo(stateWithoutFlush=False)
                valid_selection = [
                    item for item in original_selection
                    if cmds.objExists(item)
                ]
                if valid_selection:
                    cmds.select(valid_selection, replace=True)
                else:
                    cmds.select(clear=True)
            finally:
                if undo_was_enabled:
                    cmds.undoInfo(stateWithoutFlush=True)

    def del_keys(self):
        _begin_tool_undo("MiniRig_SafeDeleteKeys")
        try:
            if self.rad_sel.isChecked():
                sel = cmds.ls(sl=True)
                if not sel: return cmds.warning("Nothing selected!")
                cnt = cmds.cutKey(sel, hierarchy="below", clear=True)
                print("Deleted {} keys from hierarchy.".format(cnt))
            else:
                curves = [c for c in cmds.ls(type=['animCurveTA', 'animCurveTL', 'animCurveTT', 'animCurveTU']) if not cmds.lockNode(c, q=True)[0] and not cmds.referenceQuery(c, inr=True)]
                if curves: cmds.delete(curves); print("Wiped {} animation curves.".format(len(curves)))
        finally:
            _end_tool_undo()

# =====================================================================

# MASTER WINDOW

# =====================================================================

def _resolve_hierarchy_root(root):
    root = (root or "").strip()
    matches = (cmds.ls(root, long=True) or []) if root else []
    if len(matches) != 1 or "." in root:
        raise ValueError("Choose one unambiguous transform or joint root: '{}'".format(root))
    root = matches[0]
    if cmds.nodeType(root) not in ("transform", "joint"):
        raise ValueError("'{}' is not a transform or joint.".format(root))
    return root


def _hierarchy_snapshot(root, match_mode, ignore_namespaces, search="", replace="", source=False):
    """Iterative top-down traversal. Shapes and constraint nodes are excluded."""
    stack = [(root, ())]
    records = {}
    order = []
    identities = set()
    while stack:
        node, key = stack.pop()
        identity = (cmds.ls(node, uuid=True) or [node])[0]
        if identity in identities:
            raise ValueError("Instanced transforms are not supported: '{}'".format(node))
        identities.add(identity)
        if key in records:
            raise ValueError("Duplicate relative path after name normalization: {}".format("/".join(map(str, key))))
        records[key] = {"node": node, "type": cmds.nodeType(node), "uuid": identity}
        order.append(key)
        children = [child for child in (cmds.listRelatives(node, children=True, fullPath=True) or [])
                    if cmds.nodeType(child) in ("transform", "joint")]
        pending = []
        for index, child in enumerate(children):
            if match_mode == "structure":
                part = index
            else:
                part = child.rsplit("|", 1)[-1]
                if ignore_namespaces:
                    part = part.rsplit(":", 1)[-1]
                if source and search:
                    part = part.replace(search, replace)
            pending.append((child, key + (part,)))
        stack.extend(reversed(pending))
    return records, order, identities


def _hierarchy_target_blockers(target, parent_constraint, scale_constraint):
    if (cmds.lockNode(target, query=True, lock=True) or [False])[0]:
        return ["Node is locked"]
    attributes = []
    if parent_constraint:
        attributes.extend(prefix + axis for prefix in ("translate", "rotate") for axis in "XYZ")
    if scale_constraint:
        attributes.extend("scale" + axis for axis in "XYZ")
    blocked = []
    for attribute in attributes:
        plug = target + "." + attribute
        if cmds.getAttr(plug, lock=True):
            blocked.append(attribute + " is locked")
        elif cmds.listConnections(plug, source=True, destination=False, plugs=True):
            # getAttr(settable=True) can still be True for animated attributes.
            # Check incoming plugs explicitly to avoid inserting pairBlend nodes.
            blocked.append(attribute + " has an incoming connection")
        elif not cmds.getAttr(plug, settable=True):
            blocked.append(attribute + " is not writable")
    return blocked


def plan_matching_hierarchies(old_root, new_root, match_mode="names", ignore_namespaces=True,
                             search="", replace="", include_root=True,
                             parent_constraint=True, scale_constraint=True):
    """Read-only matching/preflight. Never pairs two allDescendents lists by zip."""
    if match_mode not in ("names", "structure"):
        raise ValueError("Match mode must be 'names' or 'structure'.")
    if not parent_constraint and not scale_constraint:
        raise ValueError("Enable parent and/or scale constraints.")
    old_root = _resolve_hierarchy_root(old_root)
    new_root = _resolve_hierarchy_root(new_root)
    if (old_root == new_root or old_root.startswith(new_root + "|")
            or new_root.startswith(old_root + "|")):
        raise ValueError("The two roots must be separate, non-overlapping hierarchies.")
    old, order, old_ids = _hierarchy_snapshot(old_root, match_mode, ignore_namespaces,
                                              search, replace, source=True)
    new, _new_order, new_ids = _hierarchy_snapshot(new_root, match_mode, ignore_namespaces)
    if old_ids & new_ids:
        raise ValueError("The hierarchies share instanced transforms; choose separate objects.")
    if set(old) != set(new):
        missing = [key for key in order if key not in new]
        extra = [key for key in new if key not in old]
        def display(keys):
            return ", ".join("/".join(map(str, key)) or "<root>" for key in keys[:4]) or "none"
        raise ValueError("Hierarchy mismatch. Missing in new: {}. Extra in new: {}.".format(display(missing), display(extra)))
    rows = []
    for key in order:
        if old[key]["type"] != new[key]["type"]:
            raise ValueError("Node type mismatch: '{}' ({}) → '{}' ({}).".format(
                old[key]["node"], old[key]["type"], new[key]["node"], new[key]["type"]))
        if not key and not include_root:
            continue
        source, target = old[key]["node"], new[key]["node"]
        blockers = _hierarchy_target_blockers(target, parent_constraint, scale_constraint)
        rows.append({"old": source, "new": target, "path": key,
                     "status": "Blocked" if blockers else "Ready", "reason": "; ".join(blockers)})
    if not rows:
        raise ValueError("No transform/joint pairs to constrain. Include the roots or choose hierarchies with descendants.")
    return {"old_root": old_root, "new_root": new_root, "rows": rows,
            "old_count": len(old), "new_count": len(new), "match_mode": match_mode}


def constrain_matching_hierarchies(old_root, new_root, maintain_offset=True,
                                  parent_constraint=True, scale_constraint=True,
                                  include_root=True, match_mode="names", ignore_namespaces=True,
                                  search="", replace="", skip_blocked=True):
    """Create old(driver) → new(driven) constraints in one undo chunk.

    Names match by relative path below the roots; namespaces can be ignored and
    source name tokens replaced. Structure mode explicitly pairs by child order
    and checks the full branching shape and node types, rather than node count.
    Existing driven connections are not overwritten. Any newly created constraint
    in a failed pair is removed, while previous successful pairs remain undoable.
    """
    plan = plan_matching_hierarchies(old_root, new_root, match_mode=match_mode,
        ignore_namespaces=ignore_namespaces, search=search, replace=replace,
        include_root=include_root, parent_constraint=parent_constraint, scale_constraint=scale_constraint)
    blocked = [row for row in plan["rows"] if row["status"] == "Blocked"]
    if blocked and not skip_blocked:
        raise ValueError("{} pair(s) have locked or connected target channels. No changes made. {}".format(
            len(blocked), blocked[0]["reason"]))
    ready = [row for row in plan["rows"] if row["status"] == "Ready"]
    result = {"plan": plan, "constraints": [], "created_pairs": [],
              "skipped": blocked, "failed": [], "not_run": []}
    if not ready:
        return result
    with _tool_action("ConstrainMatchingHierarchies"):
        for index, row in enumerate(ready):
            created = []
            try:
                # Recheck: an earlier rig edit may change the next target's inputs.
                blockers = _hierarchy_target_blockers(row["new"], parent_constraint, scale_constraint)
                if blockers:
                    raise RuntimeError("; ".join(blockers))
                if parent_constraint:
                    nodes = _constraint_command('parentConstraint',row["old"], row["new"],
                        maintainOffset=maintain_offset, name="hierarchyMatch_parentConstraint#") or []
                    for node in nodes:
                        owned_path = row["new"] + "|" + node.rsplit("|", 1)[-1]
                        created.append(owned_path if cmds.objExists(owned_path) else node)
                if scale_constraint:
                    nodes = _constraint_command('scaleConstraint',row["old"], row["new"],
                        maintainOffset=maintain_offset, name="hierarchyMatch_scaleConstraint#") or []
                    for node in nodes:
                        owned_path = row["new"] + "|" + node.rsplit("|", 1)[-1]
                        created.append(owned_path if cmds.objExists(owned_path) else node)
                row["status"] = "Created"
                row["reason"] = ", ".join(created)
                result["created_pairs"].append((row["old"], row["new"], created[:]))
                result["constraints"].extend(created)
            except RuntimeError as exc:
                remaining = [node for node in created if cmds.objExists(node)]
                if remaining:
                    cmds.delete(remaining)
                row["status"] = "Failed"
                row["reason"] = str(exc)
                result["failed"].append(row)
                cmds.warning("Could not constrain '{}' → '{}': {}".format(row["old"], row["new"], exc))
                if not skip_blocked:
                    for pending in ready[index + 1:]:
                        pending["status"] = "Not run"
                        pending["reason"] = "Stopped after the preceding failure"
                        result["not_run"].append(pending)
                    break
    print("Hierarchy constraints: {} pairs created, {} skipped, {} failed, {} not run.".format(
        len(result["created_pairs"]), len(result["skipped"]), len(result["failed"]), len(result["not_run"])))
    return result


_PAIR_CONSTRAINT_TYPES = {
    "parent": ("parentConstraint",), "point": ("pointConstraint",),
    "orient": ("orientConstraint",), "scale": ("scaleConstraint",),
    "aim": ("aimConstraint",), "parent_scale": ("parentConstraint", "scaleConstraint")}


def plan_pair_constraint(driver, driven, constraint_type="parent"):
    """Validate one Driver -> Driven constraint without traversing children."""
    driver, driven = _resolve_hierarchy_root(driver), _resolve_hierarchy_root(driven)
    if constraint_type not in _PAIR_CONSTRAINT_TYPES:
        raise ValueError("Choose Parent, Point, Orient, Scale, Aim or Parent + Scale.")
    if _guide_ik_uuid(driver) == _guide_ik_uuid(driven):
        raise ValueError("Driver and Driven must be different objects.")
    if driver.startswith(driven + "|"):
        raise ValueError("Driver is a child of Driven; this constraint would create a hierarchy feedback loop.")
    for node in (driver,driven):
        if len(cmds.ls(node,long=True,allPaths=True) or []) != 1:
            raise ValueError("Choose non-instanced Driver and Driven objects.")
    if (cmds.lockNode(driven,query=True,lock=True) or [False])[0]:
        raise ValueError("The Driven node is locked.")
    prefixes = {"parent":("translate","rotate"), "parent_scale":("translate","rotate","scale"),
                "point":("translate",), "orient":("rotate",), "scale":("scale",), "aim":("rotate",)}[constraint_type]
    for prefix in prefixes:
        for attribute in (prefix,) + tuple(prefix+axis for axis in "XYZ"):
            plug = driven + "." + attribute
            if cmds.getAttr(plug,lock=True):
                raise ValueError("Driven channel is locked: {}".format(plug))
            if cmds.listConnections(plug,source=True,destination=False,plugs=True):
                raise ValueError("Driven channel already has animation or an incoming connection: {}".format(plug))
            if not cmds.getAttr(plug,settable=True):
                raise ValueError("Driven channel is not writable: {}".format(plug))
    if constraint_type == "aim":
        a = cmds.xform(driver,query=True,worldSpace=True,translation=True)
        b = cmds.xform(driven,query=True,worldSpace=True,translation=True)
        if not all(math.isfinite(v) for v in list(a)+list(b)) or sum((x-y)**2 for x,y in zip(a,b)) <= 1e-16:
            raise ValueError("Aim requires Driver and Driven at different world positions.")
    return {"driver":driver,"driven":driven,"type":constraint_type,
            "commands":_PAIR_CONSTRAINT_TYPES[constraint_type]}


def create_pair_constraint(driver, driven, constraint_type="parent", maintain_offset=True):
    """Apply a typed constraint in one undo step, retaining inputs on failure."""
    plan = plan_pair_constraint(driver,driven,constraint_type)
    if _TOOL_UNDO_DEPTH or not cmds.undoInfo(query=True,state=True):
        raise ValueError("Enable Maya Undo and apply outside another tool action so a failed constraint can be rolled back.")
    selection = cmds.ls(selection=True,long=True) or []
    undo_name = "CreatePairConstraint_" + uuid.uuid4().hex
    created, changed = [], False
    try:
        try:
            with _tool_action(undo_name):
                for command in plan["commands"]:
                    changed = True
                    options = {"maintainOffset":bool(maintain_offset),
                               "name":":rtkPair_" + command + "_" + uuid.uuid4().hex[:8]}
                    if command == "aimConstraint":
                        options.update(aimVector=(1,0,0),upVector=(0,1,0),worldUpVector=(0,1,0),worldUpType="vector")
                    created.extend(_constraint_command(command,plan["driver"],plan["driven"],**options) or [])
        except Exception as exc:
            if changed and cmds.undoInfo(query=True,undoName=True) == undo_name:
                cmds.undo()
                raise RuntimeError("Constraint creation was rolled back; Driven and its inputs were kept: {}".format(exc)) from exc
            raise
    finally:
        _restore_locator_view_selection(selection)
    plan["constraints"] = created
    plan["maintain_offset"] = bool(maintain_offset)
    return plan


class PairConstraintPanel(QtWidgets.QGroupBox):
    """Quick constraint inputs alongside the hierarchy matching tool."""
    def __init__(self,parent=None):
        super(PairConstraintPanel,self).__init__("Quick constraint · Driver → Driven",parent)
        form = QtWidgets.QFormLayout(self)
        self.driver, self.driven = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        for field,label in ((self.driver,"Driver:"),(self.driven,"Driven:")):
            field.setPlaceholderText("Transform, joint or controller")
            row = QtWidgets.QHBoxLayout()
            row.addWidget(field,1)
            get = QtWidgets.QPushButton("Get selected")
            get.clicked.connect(lambda _checked=False,field=field:self._get(field))
            row.addWidget(get)
            form.addRow(label,row)
        row = QtWidgets.QHBoxLayout()
        both = QtWidgets.QPushButton("Get both from selection")
        both.setToolTip("Select Driver first, then Shift-select Driven.")
        both.clicked.connect(self._get_both)
        swap = QtWidgets.QPushButton("Swap Driver / Driven")
        swap.clicked.connect(self._swap)
        row.addWidget(both)
        row.addWidget(swap)
        form.addRow(row)
        self.kind = QtWidgets.QComboBox()
        for label,key in (("Parent","parent"),("Point","point"),("Orient","orient"),("Scale","scale"),("Aim","aim"),("Parent + Scale","parent_scale")):
            self.kind.addItem(label,key)
        self.kind.setToolTip("Parent: position/rotation; Point: position; Orient: rotation; Scale: scale. Aim uses +X aim, +Y up, world +Y up.")
        form.addRow("Constraint type:",self.kind)
        self.offset = QtWidgets.QCheckBox("Maintain Offset")
        self.offset.setChecked(True)
        self.offset.setToolTip("On: keep Driven's initial offset. Off: align constrained channels to Driver.")
        form.addRow(self.offset)
        apply = QtWidgets.QPushButton("Apply constraint")
        apply.setProperty("role","primary")
        apply.clicked.connect(self._apply)
        form.addRow(apply)
        self.status = QtWidgets.QLabel("Pick Driver and Driven, choose the type, then Apply. This affects only the Driven object.")
        self.status.setWordWrap(True)
        self.status.setProperty("role","muted")
        form.addRow(self.status)

    def _get(self,field):
        try:
            selected = cmds.ls(selection=True,long=True) or []
            if len(selected) != 1:
                raise ValueError("Select one object, then Get selected.")
            field.setText(_resolve_hierarchy_root(selected[0]))
        except (ValueError,RuntimeError) as exc:
            self.status.setText(str(exc))

    def _get_both(self,*_args):
        try:
            selected = cmds.ls(selection=True,long=True) or []
            if len(selected) != 2:
                raise ValueError("Select Driver first, then Shift-select Driven.")
            driver,driven = [_resolve_hierarchy_root(node) for node in selected]
            self.driver.setText(driver)
            self.driven.setText(driven)
        except (ValueError,RuntimeError) as exc:
            self.status.setText(str(exc))

    def _swap(self,*_args):
        driver,driven = self.driver.text(),self.driven.text()
        self.driver.setText(driven)
        self.driven.setText(driver)

    def _apply(self,*_args):
        try:
            result = create_pair_constraint(self.driver.text(),self.driven.text(),self.kind.currentData(),self.offset.isChecked())
            self.status.setText("Created {}: {} drives {}. Undo removes this action.".format(", ".join(result["constraints"]),result["driver"],result["driven"]))
        except (ValueError,RuntimeError) as exc:
            self.status.setText(str(exc))
            cmds.warning(str(exc))


class TabHierarchyConstraints(QtWidgets.QWidget):
    """Root pickers, mapping preview, and constraint options for two hierarchies."""

    def __init__(self, parent=None):
        super(TabHierarchyConstraints, self).__init__(parent)
        self.setProperty("qtPanel", True)
        self._preview_valid = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(PairConstraintPanel(self))

        roots = QtWidgets.QGroupBox("Objects · Old drives New")
        roots_layout = QtWidgets.QFormLayout(roots)
        self.old_root_field = QtWidgets.QLineEdit()
        self.new_root_field = QtWidgets.QLineEdit()
        for field, label, placeholder in (
                (self.old_root_field, "Old / driver root:", "Select the existing rig root…"),
                (self.new_root_field, "New / driven root:", "Select the replacement rig root…")):
            field.setPlaceholderText(placeholder)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(field, 1)
            button = QtWidgets.QPushButton("Load selected")
            button.clicked.connect(lambda _checked=False, target=field: self._load_root(target))
            row.addWidget(button)
            roots_layout.addRow(label, row)
        root_actions = QtWidgets.QHBoxLayout()
        load_both = QtWidgets.QPushButton("Load both from selection")
        load_both.setToolTip("Select the old root first, then Shift-select the new root.")
        load_both.clicked.connect(self._load_both)
        swap = QtWidgets.QPushButton("Swap roots")
        swap.clicked.connect(self._swap_roots)
        root_actions.addWidget(load_both)
        root_actions.addWidget(swap)
        roots_layout.addRow(root_actions)
        layout.addWidget(roots)

        options = QtWidgets.QGroupBox("Matching & constraints")
        form = QtWidgets.QFormLayout(options)
        self.match_mode = QtWidgets.QComboBox()
        self.match_mode.addItem("Relative names", "names")
        self.match_mode.addItem("Structure / child order", "structure")
        self.ignore_namespaces = QtWidgets.QCheckBox("Ignore namespaces when matching names")
        self.ignore_namespaces.setChecked(True)
        self.search_field = QtWidgets.QLineEdit()
        self.search_field.setPlaceholderText("Optional source token, e.g. old_")
        self.replace_field = QtWidgets.QLineEdit()
        self.replace_field.setPlaceholderText("Replacement, e.g. new_")
        name_row = QtWidgets.QHBoxLayout()
        name_row.addWidget(self.search_field)
        name_row.addWidget(QtWidgets.QLabel("→"))
        name_row.addWidget(self.replace_field)
        self.parent_cb = QtWidgets.QCheckBox("Parent (position + rotation)")
        self.parent_cb.setChecked(True)
        self.scale_cb = QtWidgets.QCheckBox("Scale")
        self.scale_cb.setChecked(True)
        types = QtWidgets.QHBoxLayout()
        types.addWidget(self.parent_cb)
        types.addWidget(self.scale_cb)
        self.offset_cb = QtWidgets.QCheckBox("Maintain offset")
        self.offset_cb.setChecked(True)
        self.include_root_cb = QtWidgets.QCheckBox("Include root objects")
        self.include_root_cb.setChecked(True)
        scope = QtWidgets.QHBoxLayout()
        scope.addWidget(self.offset_cb)
        scope.addWidget(self.include_root_cb)
        self.skip_cb = QtWidgets.QCheckBox("Skip blocked pairs; continue after individual failures")
        self.skip_cb.setChecked(True)
        self.mode_hint = QtWidgets.QLabel()
        self.mode_hint.setProperty("role", "muted")
        self.mode_hint.setWordWrap(True)
        form.addRow("Match by:", self.match_mode)
        form.addRow("", self.ignore_namespaces)
        form.addRow("Source names:", name_row)
        form.addRow("Create:", types)
        form.addRow("", scope)
        form.addRow("", self.skip_cb)
        form.addRow(self.mode_hint)
        layout.addWidget(options)

        actions = QtWidgets.QHBoxLayout()
        self.preview_button = QtWidgets.QPushButton("Preview matches")
        self.preview_button.clicked.connect(self._preview)
        self.create_button = QtWidgets.QPushButton("Create hierarchy constraints")
        self.create_button.setEnabled(False)
        self.create_button.clicked.connect(self._create)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.create_button, 1)
        layout.addLayout(actions)
        self.summary = QtWidgets.QLabel("Load the old and new roots, then preview the pairs.")
        self.summary.setWordWrap(True)
        self.summary.setProperty("role", "muted")
        layout.addWidget(self.summary)
        self.table = QtWidgets.QTreeWidget()
        self.table.setColumnCount(3)
        self.table.setHeaderLabels(["Old / driver", "New / driven", "Status"])
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setUniformRowHeights(True)
        self.table.setMinimumHeight(160)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setToolTip("Hover for full DAG paths and detailed status. Double-click an object to select it in Maya.")
        header = self.table.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.itemDoubleClicked.connect(self._select_pair_object)
        layout.addWidget(self.table, 1)

        for field in (self.old_root_field, self.new_root_field, self.search_field, self.replace_field):
            field.textChanged.connect(self._invalidate)
        for checkbox in (self.ignore_namespaces, self.parent_cb, self.scale_cb,
                         self.offset_cb, self.include_root_cb, self.skip_cb):
            checkbox.toggled.connect(self._invalidate)
        self.match_mode.currentIndexChanged.connect(self._matching_changed)
        self._matching_changed()
        _polish_native_panel(self)
        _set_button_role(self.create_button, "primary")

    def _load_root(self, field):
        selection = cmds.ls(selection=True, long=True) or []
        if len(selection) != 1:
            self.summary.setText("Select exactly one transform or joint root, then click Load selected.")
            return
        try:
            field.setText(_resolve_hierarchy_root(selection[0]))
        except ValueError as exc:
            self.summary.setText(str(exc))

    def _load_both(self, *_args):
        selection = cmds.ls(selection=True, long=True) or []
        if len(selection) != 2:
            self.summary.setText("Select two roots: old first, then Shift-select new.")
            return
        try:
            old, new = [_resolve_hierarchy_root(node) for node in selection]
            self.old_root_field.setText(old)
            self.new_root_field.setText(new)
        except ValueError as exc:
            self.summary.setText(str(exc))

    def _swap_roots(self, *_args):
        old, new = self.old_root_field.text(), self.new_root_field.text()
        self.old_root_field.setText(new)
        self.new_root_field.setText(old)

    def _matching_changed(self, *_args):
        by_names = self.match_mode.currentData() == "names"
        for widget in (self.ignore_namespaces, self.search_field, self.replace_field):
            widget.setEnabled(by_names)
        self.mode_hint.setText(
            "Root names may differ. Descendants match by their relative paths; optional token replacement applies to old names."
            if by_names else
            "Pairs use Maya child order. Both trees must have the same branching and node types; verify the preview, especially for reordered siblings.")
        self._invalidate()

    def _invalidate(self, *_args):
        self._preview_valid = False
        self.create_button.setEnabled(False)
        self.table.clear()
        self.summary.setText("Preview required: roots or options changed.")

    def _parameters(self):
        by_names = self.match_mode.currentData() == "names"
        return {"old_root": self.old_root_field.text(), "new_root": self.new_root_field.text(),
                "match_mode": self.match_mode.currentData(),
                "ignore_namespaces": self.ignore_namespaces.isChecked(),
                "search": self.search_field.text() if by_names else "",
                "replace": self.replace_field.text() if by_names else "",
                "include_root": self.include_root_cb.isChecked(),
                "parent_constraint": self.parent_cb.isChecked(), "scale_constraint": self.scale_cb.isChecked()}

    def _show_rows(self, rows):
        self.table.clear()
        self.table.setUpdatesEnabled(False)
        try:
            for row in rows:
                old = row["old"].rsplit("|", 1)[-1]
                new = row["new"].rsplit("|", 1)[-1]
                item = QtWidgets.QTreeWidgetItem([old, new, row["status"]])
                item.setData(0, QtCore.Qt.UserRole, row["old"])
                item.setData(1, QtCore.Qt.UserRole, row["new"])
                item.setToolTip(0, row["old"])
                item.setToolTip(1, row["new"])
                item.setToolTip(2, row["reason"] or "Channels are available for the requested constraints.")
                if row["status"] in ("Blocked", "Failed", "Not run"):
                    item.setForeground(2, QtGui.QBrush(QtGui.QColor("#e7b57f")))
                self.table.addTopLevelItem(item)
        finally:
            self.table.setUpdatesEnabled(True)

    def _preview(self, *_args):
        self.create_button.setEnabled(False)
        self._preview_valid = False
        try:
            plan = plan_matching_hierarchies(**self._parameters())
            self.old_root_field.setText(plan["old_root"])
            self.new_root_field.setText(plan["new_root"])
            self._show_rows(plan["rows"])
            ready = sum(row["status"] == "Ready" for row in plan["rows"])
            blocked = len(plan["rows"]) - ready
            allowed = bool(ready) and (self.skip_cb.isChecked() or not blocked)
            self._preview_valid = allowed
            self.create_button.setEnabled(allowed)
            self.summary.setText("{} pairs · {} ready · {} blocked.{}".format(
                len(plan["rows"]), ready, blocked,
                " Enable Skip blocked or free the target channels." if blocked and not self.skip_cb.isChecked() else ""))
        except (ValueError, RuntimeError) as exc:
            self.table.clear()
            self.summary.setText(str(exc))

    def _create(self, *_args):
        if not self._preview_valid:
            return
        self.create_button.setEnabled(False)
        self._preview_valid = False
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            # Recompute from the current scene instead of applying a stale table.
            result = constrain_matching_hierarchies(maintain_offset=self.offset_cb.isChecked(),
                skip_blocked=self.skip_cb.isChecked(), **self._parameters())
            self._show_rows(result["plan"]["rows"])
            self.summary.setText("Created {} constraints on {} pairs · {} skipped · {} failed · {} not run.{}".format(
                len(result["constraints"]), len(result["created_pairs"]), len(result["skipped"]),
                len(result["failed"]), len(result["not_run"]),
                " Undo once to undo this action." if result["created_pairs"] else " No constraints were created."))
        except (ValueError, RuntimeError) as exc:
            self.summary.setText(str(exc))
            cmds.warning(str(exc))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    @_non_undoable_cache_write
    def _select_pair_object(self, item, column):
        if column not in (0, 1):
            return
        node = item.data(column, QtCore.Qt.UserRole)
        if node and cmds.objExists(node):
            cmds.select(node, replace=True)


_CUSTOM_SCALARS = {"bool", "byte", "char", "short", "long", "float", "double", "doubleAngle", "doubleLinear", "time", "enum"}
_CUSTOM_VECTORS = {"short2", "short3", "long2", "long3", "float2", "float3", "double2", "double3"}


def _custom_attr_schema(node, attribute):
    plug = node + "." + attribute
    kind = cmds.getAttr(plug, type=True)
    definition_type = cmds.attributeQuery(attribute, node=node, attributeType=True)
    if cmds.attributeQuery(attribute, node=node, multi=True):
        raise ValueError("Multi/array attributes are not supported by this tool.")
    if kind not in _CUSTOM_SCALARS | _CUSTOM_VECTORS | {"string", "matrix"}:
        raise ValueError("Unsupported attribute type: {}".format(kind))
    children = cmds.attributeQuery(attribute, node=node, listChildren=True) or []
    schema = {"name": attribute, "type": kind, "definition_type": definition_type,
              "short_name": cmds.attributeQuery(attribute, node=node, shortName=True),
              "nice_name": cmds.attributeQuery(attribute, node=node, niceName=True),
              "keyable": bool(cmds.getAttr(plug, keyable=True)),
              "channel_box": bool(cmds.getAttr(plug, channelBox=True)),
              "locked": bool(cmds.getAttr(plug, lock=True)), "children": [], "limits": {}}
    for flag in ("hidden", "readable", "writable", "storable", "connectable", "usedAsColor"):
        schema[flag] = bool(cmds.attributeQuery(attribute, node=node, **{flag: True}))
    if not schema["readable"] or not schema["writable"] or not schema["connectable"]:
        raise ValueError("The attribute must be readable, writable, and connectable.")
    if kind == "enum":
        schema["enum"] = (cmds.attributeQuery(attribute, node=node, listEnum=True) or [""])[0]
    if kind == "string":
        schema["usedAsFilename"] = bool(cmds.attributeQuery(attribute, node=node, usedAsFilename=True))
    if kind in _CUSTOM_SCALARS:
        default = cmds.attributeQuery(attribute, node=node, listDefault=True) or []
        if default:
            schema["default"] = default[0]
        for exists, query, creation in (("minExists", "minimum", "minValue"),
                                        ("maxExists", "maximum", "maxValue"),
                                        ("softMinExists", "softMin", "softMinValue"),
                                        ("softMaxExists", "softMax", "softMaxValue")):
            if cmds.attributeQuery(attribute, node=node, **{exists: True}):
                schema["limits"][creation] = cmds.attributeQuery(attribute, node=node, **{query: True})[0]
    schema["children"] = [_custom_attr_schema(node, child) for child in children]
    return schema


def _custom_attr_parts(schema):
    return [schema] + [part for child in schema["children"] for part in _custom_attr_parts(child)]


def _custom_attr_leaves(schema):
    if not schema["children"]:
        return [schema]
    return [leaf for child in schema["children"] for leaf in _custom_attr_leaves(child)]


def _custom_attr_signature(schema):
    return (schema["name"], schema["type"], schema["definition_type"], schema.get("enum"),
            schema["limits"], tuple(_custom_attr_signature(child) for child in schema["children"]))


def plan_custom_attribute_transfer(source_controller, target_controller, attributes=None,
                                   replace_source_inputs=False, unlock_source=False):
    """Read-only discovery of dynamic attributes; never includes built-in plugs."""
    source = _resolve_hierarchy_root(source_controller)
    target = _resolve_hierarchy_root(target_controller)
    if source == target or (cmds.ls(source, uuid=True) or [source]) == (cmds.ls(target, uuid=True) or [target]):
        raise ValueError("Choose two different controllers.")
    source_custom = cmds.listAttr(source, userDefined=True) or []
    target_custom = set(cmds.listAttr(target, userDefined=True) or [])
    top_level = [attr for attr in source_custom if not cmds.attributeQuery(attr, node=source, listParent=True)]
    if attributes is not None:
        selected = set(attributes)
        unknown = selected - set(top_level)
        if unknown:
            raise ValueError("Only top-level custom attributes may be selected: {}".format(
                ", ".join(sorted(unknown))))
        top_level = [attr for attr in top_level if attr in selected]
    source_node_locked = (cmds.lockNode(source, query=True, lock=True) or [False])[0]
    target_node_locked = (cmds.lockNode(target, query=True, lock=True) or [False])[0]
    rows = []
    for attribute in top_level:
        row = {"attribute": attribute, "type": "", "status": "Ready", "reason": "",
               "exists": cmds.attributeQuery(attribute, node=target, exists=True), "schema": None}
        rows.append(row)
        try:
            schema = _custom_attr_schema(source, attribute)
            row["schema"], row["type"] = schema, schema["type"]
            parts, leaves = _custom_attr_parts(schema), _custom_attr_leaves(schema)
            if source_node_locked or target_node_locked:
                raise RuntimeError("A controller node is locked.")
            if row["exists"]:
                if attribute not in target_custom:
                    raise RuntimeError("The target name belongs to a built-in attribute; it will not be changed.")
                if _custom_attr_signature(_custom_attr_schema(target, attribute)) != _custom_attr_signature(schema):
                    raise RuntimeError("Existing target type, enum, limits, or child layout differs.")
                row["reason"] = "Reuse existing target attribute and retain its current value."
            else:
                for part in parts:
                    for name in {part["name"], part["short_name"]}:
                        if cmds.attributeQuery(name, node=target, exists=True):
                            raise RuntimeError("Target attribute name/alias collision: {}".format(name))
                row["reason"] = "Create the same custom attribute on the target."
            connections = [(target + "." + leaf["name"], source + "." + leaf["name"]) for leaf in leaves]
            if row["exists"] and all(cmds.isConnected(driver, driven) for driver, driven in connections):
                row["status"], row["reason"] = "Connected", "Target already drives source; no changes needed."
                continue
            if schema["children"] and cmds.connectionInfo(source + "." + attribute, isExactDestination=True):
                raise RuntimeError("Disconnect the compound-parent input first; this tool connects individual children.")
            for driver, driven in connections:
                if row["exists"] and cmds.isConnected(driven, driver):
                    raise RuntimeError("Source already drives target. Disconnect that reverse connection first.")
                incoming = cmds.listConnections(driven, source=True, destination=False, plugs=True) or []
                if incoming and not (row["exists"] and cmds.isConnected(driver, driven)) and not replace_source_inputs:
                    raise RuntimeError("{} already has an incoming connection.".format(driven))
            if any(part["locked"] for part in parts) and not unlock_source:
                row["status"] = "Blocked" if row["exists"] else "Copy only"
                row["reason"] = "Source is locked. New attributes can be copied without connecting; enable Unlock source to connect."
        except ValueError as exc:
            row["status"], row["reason"] = "Unsupported", str(exc)
        except RuntimeError as exc:
            row["status"], row["reason"] = "Blocked", str(exc)
    return {"source": source, "target": target, "rows": rows}


def _create_custom_attr_definition(target, schema, parent=None):
    options = {"longName": schema["name"], "shortName": schema["short_name"],
               "niceName": schema["nice_name"], "keyable": schema["keyable"],
               "hidden": schema["hidden"], "readable": schema["readable"],
               "writable": schema["writable"], "storable": schema["storable"]}
    if parent:
        options["parent"] = parent
    if schema["definition_type"] == "typed" or schema["type"] in ("string", "matrix"):
        options["dataType"] = schema["type"]
    else:
        options["attributeType"] = schema["definition_type"]
    if "enum" in schema:
        options["enumName"] = schema["enum"]
    if "default" in schema:
        options["defaultValue"] = schema["default"]
    options.update(schema["limits"])
    if schema["usedAsColor"]:
        options["usedAsColor"] = True
    if schema.get("usedAsFilename"):
        options["usedAsFilename"] = True
    cmds.addAttr(target, **options)
    for child in schema["children"]:
        _create_custom_attr_definition(target, child, parent=schema["name"])


def _set_custom_attr_value(plug, value, kind):
    if kind == "string":
        cmds.setAttr(plug, value or "", type="string")
    elif kind == "matrix" or kind in _CUSTOM_VECTORS:
        if value is None:
            return
        if len(value) == 1 and isinstance(value[0], (list, tuple)):
            value = value[0]
        cmds.setAttr(plug, *value, type=kind)
    else:
        cmds.setAttr(plug, value)


def _copy_custom_attr_value(source, target, schema):
    for leaf in _custom_attr_leaves(schema):
        _set_custom_attr_value(target + "." + leaf["name"],
                              cmds.getAttr(source + "." + leaf["name"]), leaf["type"])


def copy_custom_attributes_and_connect(source_controller, target_controller, attributes=None,
                                      copy_values=True, replace_source_inputs=False, unlock_source=False):
    """Copy dynamic definitions to target, then connect target.attr → source.attr."""
    plan = plan_custom_attribute_transfer(source_controller, target_controller, attributes,
        replace_source_inputs=replace_source_inputs, unlock_source=unlock_source)
    source, target = plan["source"], plan["target"]
    result = {"plan": plan, "created": [], "connected": [], "copied_only": [], "failed": [], "changed": False}
    ready = [row for row in plan["rows"] if row["status"] in ("Ready", "Copy only")]
    if not ready:
        return result
    with _tool_action("CopyCustomAttributesTargetDrivesSource"):
        for row in ready:
            attribute, schema = row["attribute"], row["schema"]
            new_attribute = not row["exists"]
            connected, previous_inputs, previous_values, unlocked = [], {}, {}, []
            try:
                if new_attribute:
                    _create_custom_attr_definition(target, schema)
                    if copy_values:
                        _copy_custom_attr_value(source, target, schema)
                    for part in _custom_attr_parts(schema):
                        cmds.setAttr(target + "." + part["name"], keyable=part["keyable"], channelBox=part["channel_box"])
                if row["status"] != "Copy only":
                    if unlock_source:
                        for part in _custom_attr_parts(schema):
                            if part["locked"]:
                                plug = source + "." + part["name"]
                                cmds.setAttr(plug, lock=False)
                                unlocked.append(plug)
                    for leaf in _custom_attr_leaves(schema):
                        driver, driven = target + "." + leaf["name"], source + "." + leaf["name"]
                        if cmds.isConnected(driver, driven):
                            continue
                        previous_inputs[driven] = cmds.listConnections(driven, source=True, destination=False, plugs=True) or []
                        previous_values[driven] = (cmds.getAttr(driven), leaf["type"])
                        cmds.connectAttr(driver, driven, force=replace_source_inputs)
                        connected.append((driver, driven))
                    row["status"], row["reason"] = "Connected", "Target → Source"
                else:
                    row["status"], row["reason"] = "Copied only", "Source remains locked; no connection was made."
                if new_attribute:
                    for part in reversed(_custom_attr_parts(schema)):
                        if part["locked"] and not unlock_source:
                            cmds.setAttr(target + "." + part["name"], lock=True)
                    result["created"].append(attribute)
                if connected:
                    result["connected"].extend(connected)
                if row["status"] == "Copied only":
                    result["copied_only"].append(attribute)
                result["changed"] = result["changed"] or bool(new_attribute or connected or unlocked)
            except (RuntimeError, ValueError, TypeError) as exc:
                # Restore only inputs/locks touched in this attribute's attempt.
                for driver, driven in reversed(connected):
                    if cmds.isConnected(driver, driven):
                        cmds.disconnectAttr(driver, driven)
                for driven, inputs in previous_inputs.items():
                    for previous in inputs:
                        if not cmds.isConnected(previous, driven):
                            cmds.connectAttr(previous, driven, force=True)
                    if not inputs and driven in previous_values:
                        value, kind = previous_values[driven]
                        _set_custom_attr_value(driven, value, kind)
                for plug in reversed(unlocked):
                    cmds.setAttr(plug, lock=True)
                if new_attribute and cmds.attributeQuery(attribute, node=target, exists=True):
                    for part in _custom_attr_parts(schema):
                        plug = target + "." + part["name"]
                        if cmds.objExists(plug):
                            cmds.setAttr(plug, lock=False)
                    cmds.deleteAttr(target + "." + attribute)
                row["status"], row["reason"] = "Failed", str(exc)
                result["failed"].append(attribute)
                cmds.warning("Custom attribute '{}': {}".format(attribute, exc))
    return result


class TabCustomAttributes(QtWidgets.QWidget):
    """Small controller picker and selectable custom-attribute preview."""

    def __init__(self, parent=None):
        super(TabCustomAttributes, self).__init__(parent)
        self.setProperty("qtPanel", True)
        self._plan = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        objects = QtWidgets.QGroupBox("Source definitions · Target drives Source")
        form = QtWidgets.QFormLayout(objects)
        self.source_field, self.target_field = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        for field, label in ((self.source_field, "Source controller:"), (self.target_field, "Target controller:")):
            field.setPlaceholderText("Select a controller, then Load selected…")
            row = QtWidgets.QHBoxLayout()
            row.addWidget(field, 1)
            button = QtWidgets.QPushButton("Load selected")
            button.clicked.connect(lambda _checked=False, target=field: self._load_controller(target))
            row.addWidget(button)
            form.addRow(label, row)
        both = QtWidgets.QPushButton("Load both from selection (source first)")
        both.clicked.connect(self._load_both)
        form.addRow(both)
        layout.addWidget(objects)
        self.copy_values_cb = QtWidgets.QCheckBox("Copy current source values to newly created target attributes")
        self.copy_values_cb.setChecked(True)
        self.replace_inputs_cb = QtWidgets.QCheckBox("Replace existing incoming connections on source attributes")
        self.unlock_source_cb = QtWidgets.QCheckBox("Unlock selected source attributes so target can drive them")
        for checkbox in (self.copy_values_cb, self.replace_inputs_cb, self.unlock_source_cb):
            layout.addWidget(checkbox)
            checkbox.toggled.connect(self._invalidate)
        actions = QtWidgets.QHBoxLayout()
        scan = QtWidgets.QPushButton("Scan custom attributes")
        scan.clicked.connect(self._scan)
        self.apply_button = QtWidgets.QPushButton("Copy & connect · Target → Source")
        self.apply_button.clicked.connect(self._apply)
        self.apply_button.setEnabled(False)
        actions.addWidget(scan)
        actions.addWidget(self.apply_button, 1)
        layout.addLayout(actions)
        self.summary = QtWidgets.QLabel("Only custom attributes are listed. Translate, Rotate, Scale, and other built-ins are excluded.")
        self.summary.setWordWrap(True)
        self.summary.setProperty("role", "muted")
        layout.addWidget(self.summary)
        self.table = QtWidgets.QTreeWidget()
        self.table.setColumnCount(4)
        self.table.setHeaderLabels(["Attribute", "Type", "Target", "Status"])
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setUniformRowHeights(True)
        self.table.setMinimumHeight(200)
        self.table.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for column in (1, 2, 3):
            self.table.header().setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._update_apply_state)
        layout.addWidget(self.table, 1)
        self.source_field.textChanged.connect(self._invalidate)
        self.target_field.textChanged.connect(self._invalidate)
        _polish_native_panel(self)
        _set_button_role(self.apply_button, "primary")

    def _load_controller(self, field):
        selection = cmds.ls(selection=True, long=True) or []
        try:
            if len(selection) != 1:
                raise ValueError("Select exactly one controller.")
            field.setText(_resolve_hierarchy_root(selection[0]))
        except ValueError as exc:
            self.summary.setText(str(exc))

    def _load_both(self, *_args):
        selection = cmds.ls(selection=True, long=True) or []
        try:
            if len(selection) != 2:
                raise ValueError("Select source first, then Shift-select target.")
            source, target = [_resolve_hierarchy_root(node) for node in selection]
            self.source_field.setText(source)
            self.target_field.setText(target)
        except ValueError as exc:
            self.summary.setText(str(exc))

    def _invalidate(self, *_args):
        self._plan = None
        self.apply_button.setEnabled(False)
        self.table.clear()
        self.summary.setText("Controllers or options changed. Scan custom attributes again.")

    def _selected(self):
        return [self.table.topLevelItem(index).data(0, QtCore.Qt.UserRole)
                for index in range(self.table.topLevelItemCount())
                if self.table.topLevelItem(index).checkState(0) == QtCore.Qt.Checked]

    def _update_apply_state(self, *_args):
        self.apply_button.setEnabled(self._plan is not None and bool(self._selected()))

    def _populate(self, plan, selected=None):
        self.table.blockSignals(True)
        try:
            self.table.clear()
            for row in plan["rows"]:
                item = QtWidgets.QTreeWidgetItem([row["attribute"], row["type"],
                    "Exists" if row["exists"] else "New", row["status"]])
                item.setData(0, QtCore.Qt.UserRole, row["attribute"])
                item.setToolTip(0, plan["source"] + "." + row["attribute"])
                item.setToolTip(3, row["reason"])
                actionable = row["status"] in ("Ready", "Copy only")
                if actionable:
                    item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                    item.setCheckState(0, QtCore.Qt.Checked if selected is None or row["attribute"] in selected else QtCore.Qt.Unchecked)
                self.table.addTopLevelItem(item)
        finally:
            self.table.blockSignals(False)

    def _scan(self, *_args):
        try:
            plan = plan_custom_attribute_transfer(self.source_field.text(), self.target_field.text(),
                replace_source_inputs=self.replace_inputs_cb.isChecked(), unlock_source=self.unlock_source_cb.isChecked())
            self.source_field.setText(plan["source"])
            self.target_field.setText(plan["target"])
            self._plan = plan
            self._populate(plan)
            self._update_apply_state()
            self.summary.setText("{} custom attributes found. Check the attributes to copy; target will drive source. Hover status for details.".format(len(plan["rows"])))
        except (ValueError, RuntimeError) as exc:
            self._plan = None
            self.apply_button.setEnabled(False)
            self.table.clear()
            self.summary.setText(str(exc))

    def _apply(self, *_args):
        selected = self._selected()
        if not selected or self._plan is None:
            return
        self.apply_button.setEnabled(False)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            result = copy_custom_attributes_and_connect(self.source_field.text(), self.target_field.text(),
                attributes=selected, copy_values=self.copy_values_cb.isChecked(),
                replace_source_inputs=self.replace_inputs_cb.isChecked(), unlock_source=self.unlock_source_cb.isChecked())
            self._populate(result["plan"], selected=[])
            self._plan = None
            blocked = sum(row["status"] in ("Blocked", "Unsupported") for row in result["plan"]["rows"])
            self.summary.setText("{} attributes added · {} connections made · {} copied only · {} blocked · {} failed.{}".format(
                len(result["created"]), len(result["connected"]), len(result["copied_only"]), blocked, len(result["failed"]),
                " Undo once to undo this action." if result["changed"] else " No changes made."))
        except (ValueError, RuntimeError) as exc:
            self._plan = None
            self.summary.setText(str(exc))
            cmds.warning(str(exc))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()


_POSE_DRIVER_TAG = "rtkPoseDriverVersion"
_POSE_DRIVER_STATE = "rtkPoseDriverState"
_POSE_DRIVER_SOURCE = "rtkPoseDriverJoint"
_POSE_DRIVER_EPSILON = 1e-8
_POSE_DRIVER_WEIGHT_SCALE = 1e8
_POSE_DRIVER_CONTROLLER_TYPES = ("double", "float", "doubleAngle", "doubleLinear", "long", "short", "byte", "bool", "enum")


def _pd_controller_value(kind, value, restore=False):
    """Cache typed angles in degrees and distances in centimeters."""
    if kind == "doubleAngle":
        if cmds.currentUnit(query=True, angle=True) in ("rad", "radian"):
            return math.radians(value) if restore else math.degrees(value)
    elif kind == "doubleLinear":
        centimeters = {"mm":.1, "cm":1, "m":100, "km":100000,
                       "in":2.54, "ft":30.48, "yd":91.44, "mi":160934.4}
        factor = centimeters[cmds.currentUnit(query=True, linear=True)]
        return value/factor if restore else value*factor
    return value


def _pd_controller_snapshot_valid(snapshot, owned):
    if snapshot is None:
        return
    if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("controller"), str)
            or not snapshot["controller"] or snapshot["controller"] in owned
            or not isinstance(snapshot.get("path"), str)
            or snapshot.get("rotate_order") not in range(6)
            or (snapshot.get("parent") is not None and not isinstance(snapshot["parent"], str))
            or not isinstance(snapshot.get("channels"), dict) or not snapshot["channels"]):
        raise ValueError("Invalid cached controller pose")
    for attribute, channel in snapshot["channels"].items():
        if (not isinstance(attribute, str) or not attribute.isidentifier()
                or not isinstance(channel, dict) or channel.get("type") not in _POSE_DRIVER_CONTROLLER_TYPES
                or not isinstance(channel.get("value"), (int, float)) or not math.isfinite(channel["value"])):
            raise ValueError("Invalid cached controller channel")


def _pd_controller_plugs(node, attribute):
    """Include compound parents when checking incoming drivers and locks."""
    plugs, seen = [], set()
    while attribute and attribute not in seen:
        seen.add(attribute)
        plugs.append(node + "." + attribute)
        parents = cmds.attributeQuery(attribute, node=node, listParent=True) or []
        attribute = parents[0] if parents else None
    return plugs


def _pd_capture_controller(controller):
    controller = _resolve_hierarchy_root(controller)
    channels = {}
    for attribute in sorted(set(cmds.listAttr(controller, keyable=True, scalar=True) or [])):
        if not attribute.isidentifier():
            continue
        plug = controller + "." + attribute
        kind = cmds.getAttr(plug, type=True)
        if kind not in _POSE_DRIVER_CONTROLLER_TYPES:
            continue
        plugs = _pd_controller_plugs(controller, attribute)
        if any(cmds.getAttr(p, lock=True) for p in plugs):
            continue
        inputs = [source for p in plugs for source in
                  (cmds.listConnections(p, source=True, destination=False, plugs=True) or [])]
        if inputs and any(cmds.nodeType(p.rsplit(".",1)[0]) not in ("animCurveTA", "animCurveTL", "animCurveTU") for p in inputs):
            continue
        value = cmds.getAttr(plug)
        if not isinstance(value, (int,float)) or not math.isfinite(value):
            raise ValueError("Controller channel needs a finite scalar value: {}".format(plug))
        channels[attribute] = {"type":kind, "value":_pd_controller_value(kind, value)}
    if not channels:
        raise ValueError("No editable keyable numeric attributes found on driver controller: {}".format(controller))
    parents = cmds.listRelatives(controller, parent=True, fullPath=True) or []
    return {"controller":_pd_uuid(controller), "path":controller,
            "parent":_pd_uuid(parents[0]) if parents else None,
            "rotate_order":int(cmds.getAttr(controller + ".rotateOrder")), "channels":channels}


def _pd_controller_target_matches(state, position):
    live = _pd_center_position(state)
    frame = _pd_node(state["frame"])
    matrix = cmds.xform(frame, query=True, worldSpace=True, matrix=True)
    origin = cmds.xform(frame, query=True, worldSpace=True, translation=True)
    vectors = [_pd_frame_vector(matrix, [b-a for a,b in zip(origin,p)], inverse=True) for p in (live,position)]
    return _pd_vector_angle(*vectors) <= .001


def _pd_controller_pose_for_target(state, position):
    identity = state.get("driver_controller")
    if not identity:
        return None
    controller = _guide_ik_resolve_uuid(identity)
    if not controller:
        raise ValueError("The saved driver controller is missing. Get its replacement or Clear the driver field before capturing.")
    if not _pd_controller_target_matches(state, position):
        return None
    return _pd_capture_controller(controller)


def set_pose_driver_controller(group, controller=None):
    """Choose a controller for future caches; existing per-pose caches stay intact."""
    group, state = _pd_read(group)
    _pd_check_edit(group, state)
    identity = None
    if controller:
        controller = _resolve_hierarchy_root(controller)
        identity = _pd_uuid(controller)
        if identity in state["members"]:
            raise ValueError("Choose the rig controller that drives the joint, rather than a PoseDriver helper.")
        _pd_capture_controller(controller)  # Validate without altering the rig.
    if identity == state.get("driver_controller"):
        return controller
    state["driver_controller"] = identity
    state.pop("default_controller_pose", None)
    with _tool_action("SetPoseDriverController"):
        _pd_write(group, state)
    return controller


def cache_pose_driver_controller_pose(group, pose_id):
    """Cache the current controller at an existing target without changing its cone."""
    group, state = _pd_read(group)
    _pd_check_edit(group, state)
    pose = next((p for p in state["poses"] if p["id"] == pose_id), None)
    if pose is None:
        raise ValueError("The target pose no longer exists. Reload the setup.")
    if not state.get("driver_controller"):
        raise ValueError("Get the driver controller first, then cache its pose.")
    position = cmds.xform(_pd_node(pose["center"]), query=True, worldSpace=True, translation=True)
    snapshot = _pd_controller_pose_for_target(state, position)
    if snapshot is None:
        raise ValueError("Pose the joint at this target first, then Cache controller pose. The current joint direction does not match this target.")
    pose["controller_pose"] = snapshot
    with _tool_action("CachePoseDriverControllerPose"):
        _pd_write(group, state)
    return snapshot


def goto_pose_driver_pose(group, pose_id=None):
    """Restore cached local controller channels in one undoable operation."""
    group, state = _pd_read(group)
    pose = next((p for p in state["poses"] if p["id"] == pose_id), None) if pose_id else None
    if pose_id and pose is None:
        raise ValueError("The target pose no longer exists. Reload the setup.")
    snapshot = pose.get("controller_pose") if pose else state.get("default_controller_pose")
    if not snapshot:
        raise ValueError("No controller pose is cached. Pose the rig and use Cache controller pose, or Set default from current joint for the default.")
    controller = _guide_ik_resolve_uuid(snapshot["controller"])
    if not controller:
        raise ValueError("Cached driver controller is missing: {}".format(snapshot["path"]))
    if (cmds.lockNode(controller, query=True, lock=True) or [False])[0]:
        raise ValueError("Driver controller node is locked: {}".format(controller))
    parents = cmds.listRelatives(controller, parent=True, fullPath=True) or []
    parent = _pd_uuid(parents[0]) if parents else None
    if parent != snapshot["parent"] or int(cmds.getAttr(controller + ".rotateOrder")) != snapshot["rotate_order"]:
        raise ValueError("Driver controller parent or rotation order changed. Cache this pose again in the new rig space.")
    writes = []
    for attribute, channel in snapshot["channels"].items():
        plug = controller + "." + attribute
        if not cmds.attributeQuery(attribute, node=controller, exists=True) or cmds.getAttr(plug, type=True) != channel["type"]:
            raise ValueError("Cached controller channel is missing or changed type: {}".format(plug))
        plugs = _pd_controller_plugs(controller, attribute)
        if any(cmds.getAttr(p, lock=True) for p in plugs):
            raise ValueError("Controller channel is locked: {}".format(plug))
        if any(cmds.listConnections(p, source=True, destination=False, plugs=True) for p in plugs):
            raise ValueError("Controller channel is animated or driven: {}. Its input was kept.".format(plug))
        if not cmds.getAttr(plug, settable=True):
            raise ValueError("Controller channel is not editable: {}".format(plug))
        value = _pd_controller_value(channel["type"], channel["value"], restore=True)
        writes.append((plug, value))
    if _TOOL_UNDO_DEPTH or not cmds.undoInfo(query=True, state=True):
        raise ValueError("Enable Maya Undo and go to a pose outside another tool action so a failed restore can be rolled back.")
    if pose:
        position = cmds.xform(_pd_node(pose["center"]), query=True, worldSpace=True, translation=True)
    else:
        frame = _pd_node(state["frame"])
        matrix = cmds.xform(frame, query=True, worldSpace=True, matrix=True)
        origin = cmds.xform(frame, query=True, worldSpace=True, translation=True)
        ray = _pd_frame_vector(matrix, [state["axis"]*v for v in state.get("default_direction_local",(1,0,0))])
        position = [a+b for a,b in zip(origin,ray)]
    undo_name = "GoToPoseDriverPose_" + uuid.uuid4().hex
    changed = False
    try:
        with _tool_action(undo_name):
            # Space-switch/custom channels precede local transforms.
            for plug,value in sorted(writes, key=lambda item:item[0].rsplit(".",1)[1].startswith(("translate","rotate","scale"))):
                changed = True
                cmds.setAttr(plug, value)
            if not _pd_controller_target_matches(state, position):
                raise ValueError("The cached controller no longer reproduces this target direction. Check the rig/space settings and cache this pose again.")
    except Exception as exc:
        if changed and cmds.undoInfo(query=True, undoName=True) == undo_name:
            cmds.undo()
            raise RuntimeError("Go to pose was rolled back: {}".format(exc)) from exc
        raise
    return {"controller":controller, "channels":len(writes), "pose":pose["name"] if pose else "default"}


def pose_driver_weights(direction, targets, normalize=0.0, falloff="linear"):
    """Reference math for angular cone weights; no scene operations."""
    def unit(vector):
        vector = tuple(float(v) for v in vector)
        if len(vector) != 3 or not all(math.isfinite(v) for v in vector):
            raise ValueError("Directions require three finite coordinates.")
        length = math.sqrt(sum(v*v for v in vector))
        return tuple(v/length for v in vector) if length > 1e-8 else None
    normalize = float(normalize)
    if not math.isfinite(normalize) or not 0 <= normalize <= 1:
        raise ValueError("Normalize must be between 0 and 1.")
    falloff = _pd_falloff_mode(falloff)
    live = unit(direction)
    raw = []
    for target in targets:
        radius = _pd_radius(target["radius"])
        center = unit(target["direction"])
        dot = sum(a*b for a,b in zip(live, center)) if live and center else -1.0
        edge = math.cos(math.radians(radius))
        t = max(0.0, min(1.0, (dot-edge)/(1.0-edge))) if live and center else 0.0
        if falloff == "linear":
            value = max(0.0, 1.0-math.degrees(math.acos(max(-1.0,min(1.0,dot))))/radius) if live and center else 0.0
        else:
            value = t*t*(3.0-2.0*t)
        raw.append(value)
    total = sum(raw)
    denominator = max(total, _POSE_DRIVER_EPSILON)
    final = [(1-normalize)*w + normalize*w/denominator for w in raw]
    return {"raw": raw, "weights": final, "sum": total}


def _pd_radius(value):
    value = float(value)
    if not math.isfinite(value) or not 0.1 <= value <= 180.0:
        raise ValueError("Falloff angle must be between 0.1 and 180 degrees.")
    return value


def _pd_radius_mode(radius, pose=None):
    if radius is None:
        return pose.get("radius_mode", "manual") if pose is not None else "auto"
    return "auto" if radius == "auto" else "manual"


def _pd_auto_radius(state, position):
    """Measure in the same start-frame space as the live weight graph."""
    frame = _pd_node(state["frame"])
    matrix = cmds.xform(frame, query=True, worldSpace=True, matrix=True)
    origin = cmds.xform(frame, query=True, worldSpace=True, translation=True)
    direction = _pd_frame_vector(matrix, [b-a for a,b in zip(origin, position)], inverse=True)
    default = [state["axis"]*v for v in state.get("default_direction_local", (1, 0, 0))]
    angle = _pd_vector_angle(default, direction)
    if angle <= 1e-6:
        raise ValueError("Automatic falloff needs a target direction different from the default pose. Rotate the joint farther, choose another target object, or use a manual falloff angle.")
    return _pd_radius(max(0.1, angle))


def _pd_pose_attribute(name):
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the pose a name before capturing it.")
    base = "".join(c if c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" else "_" for c in name)
    base = base.strip("_")
    if not base:
        raise ValueError("Use at least one English letter or number in the pose name.")
    if base[0].isdigit():
        base = "pose_" + base
    return base + "Weight"


def _pd_uuid(node):
    return _guide_ik_uuid(node)


def _pd_node(identity):
    node = _guide_ik_resolve_uuid(identity)
    if not node:
        raise ValueError("A PoseDriver member is missing. Undo the manual deletion or remove the setup: {}".format(identity))
    return node


def _pd_joint(joint):
    return _guide_ik_joint(joint)


def find_pose_drivers(joint):
    joint = _pd_joint(joint)
    groups = []
    for plug in cmds.listConnections(joint + ".message", source=False, destination=True, plugs=True) or []:
        node, attribute = plug.rsplit(".", 1)
        if attribute == _POSE_DRIVER_SOURCE:
            for group in cmds.ls(node, long=True) or []:
                if (cmds.attributeQuery(_POSE_DRIVER_TAG, node=group, exists=True)
                        and cmds.getAttr(group + "." + _POSE_DRIVER_TAG) == "1"):
                    groups.append(group)
    return list(dict.fromkeys(groups))


def list_pose_drivers():
    return [node for node in (cmds.ls("*." + _POSE_DRIVER_TAG, objectsOnly=True, long=True, recursive=True) or [])
            if cmds.getAttr(node + "." + _POSE_DRIVER_TAG) == "1"]


def _pd_read(group):
    group = _resolve_hierarchy_root(group)
    if (cmds.nodeType(group) != "transform" or not cmds.attributeQuery(_POSE_DRIVER_TAG, node=group, exists=True)
            or cmds.getAttr(group + "." + _POSE_DRIVER_TAG) != "1"):
        raise ValueError("Choose a PoseDriver setup group.")
    try:
        state = json.loads(cmds.getAttr(group + "." + _POSE_DRIVER_STATE))
        if (not isinstance(state, dict) or not isinstance(state["members"], list)
                or not all(isinstance(i, str) for i in state["members"])
                or not isinstance(state["poses"], list) or not isinstance(state["next_index"], int)):
            raise ValueError("Invalid setup data")
        for key in ("joint", "frame", "cone", "aim", "targets", "live", "sum", "denominator"):
            if not isinstance(state[key], str):
                raise ValueError("Invalid member reference")
        if _pd_uuid(group) not in state["members"] or state["joint"] in state["members"]:
            raise ValueError("Invalid setup ownership")
        owned = set(state["members"])
        if (state.get("driver_controller") is not None
                and (not isinstance(state["driver_controller"],str) or state["driver_controller"] in owned)):
            raise ValueError("Invalid driver controller reference")
        _pd_controller_snapshot_valid(state.get("default_controller_pose"), owned)
        base_ids = {state[key] for key in ("frame", "cone", "aim", "targets", "live", "sum", "denominator")}
        for key in ("normalization_sum", "normalization_divisor"):
            if key in state:
                if not isinstance(state[key],str) or state[key] not in owned:raise ValueError("Invalid normalization ownership")
                base_ids.add(state[key])
        if bool(state.get("normalization_sum"))!=bool(state.get("normalization_divisor")):
            raise ValueError("Incomplete normalization references")
        if not base_ids.issubset(owned) or state["axis"] not in (-1, 1) or state["next_index"] < 1:
            raise ValueError("Invalid setup references")
        for key in ("default_rotation_degrees", "default_direction_local"):
            if key in state and (not isinstance(state[key], (list, tuple)) or len(state[key]) != 3
                    or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in state[key])):
                raise ValueError("Invalid default rotation data")
        if "default_rotate_order" in state and state["default_rotate_order"] not in range(6):
            raise ValueError("Invalid default rotate order")
        _pd_falloff_mode(state.get("falloff_mode", "smooth"))
        attributes, indices, pose_ids, pose_members, joint_attributes = set(), set(), set(), set(), set()
        for pose in state["poses"]:
            if (not isinstance(pose, dict) or not isinstance(pose["id"], str)
                    or pose["id"] in pose_ids
                    or not isinstance(pose["name"], str) or not isinstance(pose["center"], str)
                    or not isinstance(pose["ramp"], str)
                    or not isinstance(pose["nodes"], list) or not all(isinstance(i, str) for i in pose["nodes"])
                    or not isinstance(pose["index"], int) or pose["index"] < 0
                    or pose["attribute"] != _pd_pose_attribute(pose["name"])
                    or pose["attribute"] in attributes or pose["index"] in indices
                    or not {pose["center"], pose["ramp"]}.issubset(set(pose["nodes"]))
                    or not set(pose["nodes"]).issubset(owned)
                    or set(pose["nodes"]) & (pose_members | base_ids)
                    or pose["index"] >= state["next_index"]
                    or (pose.get("target_object") is not None and not isinstance(pose["target_object"], str))):
                raise ValueError("Invalid pose data")
            _pd_radius(pose["radius"])
            _pd_controller_snapshot_valid(pose.get("controller_pose"), owned)
            if pose.get("radius_mode", "manual") not in ("auto", "manual"):
                raise ValueError("Invalid falloff angle mode")
            if bool(pose.get("linear_ramp")) != bool(pose.get("falloff_blend")):
                raise ValueError("Invalid linear falloff references")
            for key in ("linear_ramp", "falloff_blend", "normalization_numerator", "normalizer"):
                if key in pose and (not isinstance(pose[key],str) or pose[key] not in pose["nodes"]):
                    raise ValueError("Invalid linear falloff ownership")
            mapping = pose.get("joint_attributes", {})
            if not isinstance(mapping, dict):
                raise ValueError("Invalid joint weight display data")
            for output, attribute in mapping.items():
                if (output not in (pose["attribute"], pose["attribute"]+"Raw")
                        or not isinstance(attribute, str) or attribute in joint_attributes
                        or not (attribute in (output, "pd_"+output)
                            or (attribute.startswith("pd_"+output+"_") and attribute[len("pd_"+output+"_"):].isdigit()))):
                    raise ValueError("Invalid joint weight display ownership")
                joint_attributes.add(attribute)
            attributes.add(pose["attribute"])
            indices.add(pose["index"])
            pose_ids.add(pose["id"])
            pose_members.update(pose["nodes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Cannot read PoseDriver data: {}".format(exc))
    return group, state


def _pd_write(group, state):
    plug = group + "." + _POSE_DRIVER_STATE
    if not cmds.attributeQuery(_POSE_DRIVER_STATE, node=group, exists=True):
        cmds.addAttr(group, longName=_POSE_DRIVER_STATE, dataType="string", hidden=True)
    locked = cmds.getAttr(plug, lock=True)
    try:
        if locked:
            cmds.setAttr(plug, lock=False)
        cmds.setAttr(plug, json.dumps(state), type="string")
    finally:
        cmds.setAttr(plug, lock=True)


def _pd_check_members(state, identities=None):
    owned = set(state["members"])
    identities = list(identities if identities is not None else owned)
    for identity in identities:
        node = _guide_ik_resolve_uuid(identity)
        if not node:
            continue  # Removal can clean a setup after an owned node was deleted.
        if cmds.referenceQuery(node, isNodeReferenced=True) or (cmds.lockNode(node, query=True, lock=True) or [False])[0]:
            raise ValueError("PoseDriver member is locked or referenced: {}".format(node))
        children = (cmds.listRelatives(node, allDescendents=True, fullPath=True) or []) if cmds.objectType(node, isAType="dagNode") else []
        for child in children:
            if _pd_uuid(child) not in owned:
                raise ValueError("Move unrelated object '{}' out of the PoseDriver setup before deleting it.".format(child))


def _pd_check_edit(group, state):
    _pd_check_members(state)
    for key in ("frame", "cone", "targets", "live", "sum", "denominator"):
        _pd_node(state[key])
    linked = cmds.listConnections(group + "." + _POSE_DRIVER_SOURCE, source=True, destination=False) or []
    if len(linked) != 1 or _pd_uuid(linked[0]) != state["joint"]:
        raise ValueError("The PoseDriver source joint link is missing or changed.")


class _PoseDriverBuilder:
    """Capture every new DAG/DG node, including automatic conversion nodes."""
    def __init__(self, prefix):
        self.prefix = prefix
        self.members = []

    def remember(self, node):
        identity = _pd_uuid(node)
        if identity not in self.members:
            self.members.append(identity)
        return (cmds.ls(node, long=True) or [node])[0]

    def node(self, kind, suffix):
        return self.remember(cmds.createNode(kind, name=self.prefix + suffix + "#", skipSelect=True))

    def connect(self, source, destination):
        cmds.connectAttr(source, destination)
        # Maya may insert a unitConversion for typed plugs. It belongs to us.
        inputs = cmds.listConnections(destination, source=True, destination=False, plugs=True) or []
        for plug in inputs:
            node = plug.rsplit(".", 1)[0]
            if cmds.nodeType(node) == "unitConversion" and _pd_uuid(node) != _pd_uuid(source.rsplit(".", 1)[0]):
                self.remember(node)

    def locator(self, suffix, parent, size=.15):
        locator = self.remember(cmds.spaceLocator(name=self.prefix + suffix + "#")[0])
        locator = cmds.parent(locator, parent, relative=True)[0]
        locator = cmds.ls(locator, long=True)[0]
        for shape in cmds.listRelatives(locator, shapes=True, fullPath=True) or []:
            self.remember(shape)
            for axis in "XYZ":
                cmds.setAttr(shape + ".localScale" + axis, size)
            cmds.setAttr(shape + ".overrideEnabled", True)
            cmds.setAttr(shape + ".overrideColor", 17 if suffix == "cone" else 18 if suffix == "start" else 6)
        return locator

    def direction(self, target, frame, suffix):
        matrix = self.node("multMatrix", suffix + "_matrix")
        decompose = self.node("decomposeMatrix", suffix + "_position")
        squared = self.node("vectorProduct", suffix + "_lengthSquared")
        distance = self.node("multiplyDivide", suffix + "_length")
        safe = self.node("condition", suffix + "_safeLength")
        divide = self.node("multiplyDivide", suffix + "_unit")
        self.connect(target + ".worldMatrix[0]", matrix + ".matrixIn[0]")
        self.connect(frame + ".worldInverseMatrix[0]", matrix + ".matrixIn[1]")
        self.connect(matrix + ".matrixSum", decompose + ".inputMatrix")
        # Compute a numerical length to avoid scene distance-unit conversions.
        cmds.setAttr(squared + ".operation", 1)
        cmds.setAttr(squared + ".normalizeOutput", False)
        self.connect(decompose + ".outputTranslate", squared + ".input1")
        self.connect(decompose + ".outputTranslate", squared + ".input2")
        cmds.setAttr(distance + ".operation", 3)  # Power: sqrt(length squared)
        cmds.setAttr(distance + ".input2X", .5)
        self.connect(squared + ".outputX", distance + ".input1X")
        cmds.setAttr(safe + ".operation", 2)  # Greater than
        cmds.setAttr(safe + ".secondTerm", 1e-8)
        cmds.setAttr(safe + ".colorIfFalseR", 1.0)
        self.connect(distance + ".outputX", safe + ".firstTerm")
        self.connect(distance + ".outputX", safe + ".colorIfTrueR")
        cmds.setAttr(divide + ".input2", 1, 1, 1, type="float3")
        self.connect(decompose + ".outputTranslate", divide + ".input1")
        for axis in "XYZ":
            self.connect(safe + ".outColorR", divide + ".input2" + axis)
        cmds.setAttr(divide + ".operation", 2)  # Enable Divide after safe inputs are wired.
        return {"vector": divide, "length": distance}

    def cleanup(self):
        _guide_ik_delete_owned(self.members)


def _pd_build_normalization_divisor(builder,total):
    scaled=builder.node("multiplyDivide","scaledWeightSum")
    divisor=builder.node("clamp","normalizationDivisor")
    cmds.setAttr(scaled+".operation",1)
    cmds.setAttr(scaled+".input2X",_POSE_DRIVER_WEIGHT_SCALE)
    cmds.setAttr(divisor+".maxR",1e30)
    cmds.setAttr(divisor+".minR",1.0)
    builder.connect(total+".output1D",scaled+".input1X")
    builder.connect(scaled+".outputX",divisor+".inputR")
    return {"normalization_sum":_pd_uuid(scaled),"normalization_divisor":_pd_uuid(divisor)}


def _pd_build_normalization_numerator(builder,raw):
    scaled=builder.node("multiplyDivide","scaledRawWeight")
    cmds.setAttr(scaled+".operation",1)
    cmds.setAttr(scaled+".input2X",_POSE_DRIVER_WEIGHT_SCALE)
    builder.connect(raw,scaled+".input1X")
    return scaled


def build_pose_driver(joint, axis=1, driver_controller=None):
    """Capture the start frame without changing the source joint."""
    joint = _pd_joint(joint)
    if axis not in (-1, 1):
        raise ValueError("Choose +X or -X for the cone direction.")
    if find_pose_drivers(joint):
        raise ValueError("This joint already has a PoseDriver. Load the existing setup.")
    controller_pose = _pd_capture_controller(driver_controller) if driver_controller else None
    parents = cmds.listRelatives(joint, parent=True, fullPath=True) or []
    builder = _PoseDriverBuilder(":" + joint.rsplit("|", 1)[-1].replace(":", "_") + "_poseDriver_" + uuid.uuid4().hex[:8] + "_")
    constraint_scope=_constraint_context(joint.rsplit('|',1)[-1]+'_PoseDriver',builder.remember)
    selection = cmds.ls(selection=True, long=True) or []
    try:
        with _tool_action("BuildPoseDriverStart"):
            try:
                group = builder.remember(cmds.group(empty=True, name=builder.prefix + "grp#"))
                frame = builder.locator("start", group, .25)
                cmds.matchTransform(frame, joint, position=True, rotation=True)
                if parents:
                    for node in _constraint_command('parentConstraint',parents[0], frame, maintainOffset=True,
                            name=builder.prefix + "parentConstraint#", _scope=constraint_scope):
                        builder.remember(node)
                aim = builder.remember(cmds.group(empty=True, name=builder.prefix + "rotation#", parent=frame))
                cmds.setAttr(aim + ".translate", 0, 0, 0, type="double3")
                cmds.setAttr(aim + ".rotate", 0, 0, 0, type="double3")
                cmds.setAttr(aim + ".scale", 1, 1, 1, type="double3")
                for node in _constraint_command('orientConstraint',joint, aim, maintainOffset=False, name=builder.prefix + "orientConstraint#", _scope=constraint_scope):
                    builder.remember(node)
                cone = builder.locator("cone", aim)
                cmds.setAttr(cone + ".translateX", axis)
                for attr in ("translate", "rotate", "scale"):
                    for component in "XYZ":
                        cmds.setAttr(cone + "." + attr + component, lock=True, keyable=False)
                targets = builder.remember(cmds.group(empty=True, name=builder.prefix + "targets#", parent=frame))
                cmds.setAttr(targets + ".translate", 0, 0, 0, type="double3")
                cmds.setAttr(targets + ".rotate", 0, 0, 0, type="double3")
                cmds.setAttr(targets + ".scale", 1, 1, 1, type="double3")
                cmds.addAttr(cone, longName="normalize", attributeType="double", minValue=0, maxValue=1, defaultValue=0, keyable=True)
                cmds.addAttr(cone, longName="rawWeightSum", attributeType="double", keyable=False)
                live = builder.direction(cone, frame, "live")
                total = builder.node("plusMinusAverage", "rawSum")
                cmds.setAttr(total + ".operation", 1)
                cmds.setAttr(total + ".input1D[0]", 0)
                denominator = builder.node("condition", "safeSum")
                cmds.setAttr(denominator + ".operation", 2)
                cmds.setAttr(denominator + ".secondTerm", _POSE_DRIVER_EPSILON)
                cmds.setAttr(denominator + ".colorIfFalseR", _POSE_DRIVER_EPSILON)
                builder.connect(total + ".output1D", denominator + ".firstTerm")
                builder.connect(total + ".output1D", denominator + ".colorIfTrueR")
                builder.connect(total + ".output1D", cone + ".rawWeightSum")
                normalization = _pd_build_normalization_divisor(builder,total)
                cmds.setAttr(cone + ".rawWeightSum", lock=False, keyable=True, channelBox=True)
                cmds.addAttr(group, longName=_POSE_DRIVER_TAG, dataType="string", hidden=True)
                cmds.setAttr(group + "." + _POSE_DRIVER_TAG, "1", type="string", lock=True)
                cmds.addAttr(group, longName=_POSE_DRIVER_SOURCE, attributeType="message", hidden=True)
                builder.connect(joint + ".message", group + "." + _POSE_DRIVER_SOURCE)
                state = {"joint": _pd_uuid(joint), "axis": axis, "frame": _pd_uuid(frame),
                         "aim": _pd_uuid(aim), "cone": _pd_uuid(cone), "targets": _pd_uuid(targets),
                         "live": _pd_uuid(live["vector"]), "sum": _pd_uuid(total),
                         "denominator": _pd_uuid(denominator), "next_index": 1, "poses": [],
                         "falloff_mode": "linear",
                         "members": builder.members[:], "start_matrix": cmds.xform(joint, query=True, worldSpace=True, matrix=True)}
                state.update(_pd_default_data(state))
                if controller_pose:
                    state["driver_controller"] = controller_pose["controller"]
                    state["default_controller_pose"] = controller_pose
                state.update(normalization)
                _pd_write(group, state)
            except Exception:
                builder.cleanup()
                raise
    finally:
        _restore_locator_view_selection(selection)
    return {"group": group, "cone": cone, "frame": frame, "state": state}


def pose_driver_unit_center(origin, endpoint):
    """Place a center exactly one world-space unit along the joint-to-object ray."""
    origin, endpoint = tuple(float(v) for v in origin), tuple(float(v) for v in endpoint)
    if (len(origin) != 3 or len(endpoint) != 3
            or not all(math.isfinite(v) for v in origin + endpoint)):
        raise ValueError("Joint and target positions require three finite coordinates.")
    direction = tuple(b-a for a,b in zip(origin, endpoint))
    length = math.sqrt(sum(v*v for v in direction))
    if length <= 1e-8 or not math.isfinite(length):
        raise ValueError("The target pose object must be away from the target joint.")
    return tuple(a + v/length for a,v in zip(origin, direction))


def _pd_center_position(state, center=None):
    joint = _pd_node(state["joint"])
    origin = cmds.xform(joint, query=True, worldSpace=True, translation=True)
    frame_origin = cmds.xform(_pd_node(state["frame"]), query=True, worldSpace=True, translation=True)
    if math.sqrt(sum((a-b)**2 for a,b in zip(origin, frame_origin))) > 1e-4:
        raise ValueError("The joint moved away from the captured start origin. Restore its translation or rebuild the start reference before capturing a rotation pose.")
    if center:
        center = _resolve_hierarchy_root(center)
        if _pd_uuid(center) == state["cone"]:
            raise ValueError("Choose a target pose object, not the live cone. The target must define the desired direction.")
        endpoint = cmds.xform(center, query=True, worldSpace=True, translation=True)
    else:
        # Maya world matrices are row-major: row zero is the joint's world X axis.
        matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
        endpoint = tuple(origin[i] + state["axis"]*matrix[i] for i in range(3))
    return pose_driver_unit_center(origin, endpoint)


def _pd_origin_change(state):
    """Preflight a legacy cone group offset; no source joint edits."""
    aim = _pd_node(state["aim"])
    old = tuple(cmds.getAttr(aim + ".translate" + axis) for axis in "XYZ")
    if any(abs(value) > 1e-10 for value in old):
        for attr in ("translate", "translateX", "translateY", "translateZ"):
            plug = aim + "." + attr
            if cmds.getAttr(plug, lock=True) or cmds.listConnections(plug, source=True, destination=False):
                raise ValueError("The cone rotation-group origin is locked or driven: {}".format(plug))
        return aim, old
    return None


def _pd_target_reference(state, center):
    if not center:
        return None
    identity = _pd_uuid(_resolve_hierarchy_root(center))
    return identity if identity not in set(state["members"]) else None


def _pd_same_plug(first, second):
    a, aa = first.rsplit(".", 1)
    b, ba = second.rsplit(".", 1)
    return aa == ba and _pd_uuid(a) == _pd_uuid(b)


def _pd_joint_weight_input(state, output, attribute):
    joint = _guide_ik_resolve_uuid(state["joint"])
    cone = _guide_ik_resolve_uuid(state["cone"])
    if not joint or not cone or not cmds.attributeQuery(attribute, node=joint, exists=True):
        return False
    inputs = cmds.listConnections(joint + "." + attribute, source=True, destination=False, plugs=True) or []
    return len(inputs) == 1 and _pd_same_plug(inputs[0], cone + "." + output)


def _pd_joint_weight_editable(state):
    joint = _pd_node(state["joint"])
    return not (cmds.referenceQuery(joint, isNodeReferenced=True)
                or (cmds.lockNode(joint, query=True, lock=True) or [False])[0])


def _pd_delete_created_joint_weights(state, attributes):
    if not attributes:
        return
    joint = _pd_node(state["joint"])
    for attribute in attributes:
        if cmds.attributeQuery(attribute, node=joint, exists=True):
            cmds.setAttr(joint + "." + attribute, lock=False)
            cmds.deleteAttr(joint + "." + attribute)


def _pd_publish_joint_weights(state, pose):
    """Create only owned custom display plugs; never force an existing input."""
    if not _pd_joint_weight_editable(state):
        return []  # A referenced/locked source may still drive a cone.
    joint, cone = _pd_node(state["joint"]), _pd_node(state["cone"])
    previous = dict(pose.get("joint_attributes", {}))
    mapping, created = dict(previous), []
    try:
        for output in (pose["attribute"], pose["attribute"] + "Raw"):
            attribute = mapping.get(output)
            if attribute and cmds.attributeQuery(attribute, node=joint, exists=True):
                if not _pd_joint_weight_input(state, output, attribute):
                    raise ValueError("Joint weight display '{}.{}' was disconnected or given another driver; its input was kept.".format(joint, attribute))
                continue
            if not attribute:
                attribute = output
                if cmds.attributeQuery(attribute, node=joint, exists=True):
                    base = "pd_" + output
                    attribute, suffix = base, 2
                    while cmds.attributeQuery(attribute, node=joint, exists=True):
                        attribute = base + "_" + str(suffix)
                        suffix += 1
            cmds.addAttr(joint, longName=attribute, attributeType="double", minValue=0, maxValue=1, keyable=True)
            created.append(attribute)
            cmds.connectAttr(cone + "." + output, joint + "." + attribute)
            cmds.setAttr(joint + "." + attribute, lock=False, keyable=True, channelBox=True)
            mapping[output] = attribute
        pose["joint_attributes"] = mapping
    except Exception:
        _pd_delete_created_joint_weights(state, created)
        if previous:
            pose["joint_attributes"] = previous
        else:
            pose.pop("joint_attributes", None)
        raise
    return created


def expose_pose_driver_joint_weights(group):
    """Connect setup outputs to unlocked SDK driver attributes on its joint."""
    group, state = _pd_read(group)
    _pd_check_edit(group, state)
    if not _pd_joint_weight_editable(state):
        raise ValueError("The joint is locked or referenced. Its weights remain available on the cone.")
    old_state = json.loads(json.dumps(state))
    created = []
    with _tool_action("ExposePoseDriverJointWeights"):
        try:
            for pose in state["poses"]:
                created.extend(_pd_publish_joint_weights(state, pose))
            if state != old_state:
                _pd_write(group, state)
            unlock_pose_driver_weights(group)
        except Exception:
            _pd_delete_created_joint_weights(state, created)
            _pd_write(group, old_state)
            raise
    joint = _pd_node(state["joint"])
    return {"joint": joint, "attributes": [joint + "." + attribute for pose in state["poses"]
            for attribute in pose.get("joint_attributes", {}).values()]}


def unlock_pose_driver_weights(group):
    """Upgrade owned weight attributes for SDK without changing values or inputs."""
    group,state = _pd_read(group)
    _pd_check_edit(group,state)
    cone = _pd_node(state["cone"])
    plugs = [cone + ".normalize", cone + ".rawWeightSum"]
    for pose in state["poses"]:
        plugs.extend(cone + "." + attr for attr in (pose["attribute"],pose["attribute"]+"Raw"))
    joint = _guide_ik_resolve_uuid(state["joint"])
    editable_joint = bool(joint and _pd_joint_weight_editable(state))
    if editable_joint:
        for pose in state["poses"]:
            plugs.extend(joint + "." + attribute for output,attribute in pose.get("joint_attributes",{}).items()
                         if _pd_joint_weight_input(state,output,attribute))
    snapshots = [(plug,cmds.getAttr(plug,lock=True),cmds.getAttr(plug,keyable=True),cmds.getAttr(plug,channelBox=True))
                 for plug in dict.fromkeys(plugs) if cmds.objExists(plug)]
    changed = []
    with _tool_action("UnlockPoseDriverSDKWeights"):
        try:
            for plug,locked,keyable,visible in snapshots:
                if locked or not keyable or not visible:
                    changed.append((plug,locked,keyable,visible))
                    cmds.setAttr(plug,lock=False,keyable=True,channelBox=True)
        except Exception:
            for plug,locked,keyable,visible in reversed(changed):
                cmds.setAttr(plug,lock=False,keyable=keyable,channelBox=visible)
                cmds.setAttr(plug,lock=locked)
            raise
    return {"attributes":[item[0] for item in snapshots],"skipped_joint":not editable_joint}


def _pd_check_joint_weight_removal(state, poses):
    joint = _guide_ik_resolve_uuid(state["joint"])
    if not joint:
        return
    for pose in poses:
        for output, attribute in pose.get("joint_attributes", {}).items():
            if not _pd_joint_weight_input(state, output, attribute):
                continue  # A manually disconnected/repurposed attribute is kept.
            if not _pd_joint_weight_editable(state):
                raise ValueError("Unlock the joint before removing its owned weight display attributes.")
            consumers = cmds.listConnections(joint + "." + attribute, source=False, destination=True, plugs=True) or []
            if consumers:
                raise ValueError("Joint weight '{}.{}' drives '{}'. Disconnect that consumer before removing this pose/system.".format(joint, attribute, consumers[0]))


def _pd_remove_joint_weights(state, poses):
    attributes = [attribute for pose in poses for output, attribute in pose.get("joint_attributes", {}).items()
                  if _pd_joint_weight_input(state, output, attribute)]
    _pd_delete_created_joint_weights(state, attributes)


def _pd_falloff_mode(mode):
    if mode not in ("smooth", "linear"):
        raise ValueError("Choose Smooth cosine or Linear angle falloff.")
    return mode


def _pd_falloff_links(state, pose):
    cone, ramp = _pd_node(state["cone"]), _pd_node(pose["ramp"])
    inputs = cmds.listConnections(cone + "." + pose["attribute"] + "Raw", source=True, destination=False, plugs=True) or []
    if len(inputs) != 1:
        raise ValueError("The raw weight input was changed; reload or repair this pose.")
    gate, attribute = inputs[0].rsplit(".",1)
    if cmds.nodeType(gate) != "condition" or attribute != "outColorR" or _pd_uuid(gate) not in pose["nodes"]:
        raise ValueError("The raw weight gate no longer belongs to this pose.")
    destination = gate + ".colorIfTrueR"
    current = cmds.listConnections(destination, source=True, destination=False, plugs=True) or []
    expected = _pd_node(pose["falloff_blend"]) + ".outputR" if pose.get("falloff_blend") else ramp + ".outValue"
    if len(current) != 1 or not _pd_same_plug(current[0],expected) or cmds.getAttr(destination,lock=True):
        raise ValueError("The pose falloff input is locked or has another driver.")
    dot_inputs = cmds.listConnections(ramp + ".inputValue", source=True, destination=False, plugs=True) or []
    if len(dot_inputs) != 1:
        raise ValueError("The pose direction comparison input is missing.")
    dot = dot_inputs[0].rsplit(".",1)[0]
    target_inputs = cmds.listConnections(dot + ".input2", source=True, destination=False, plugs=True) or []
    if (_pd_uuid(dot) not in pose["nodes"] or len(target_inputs) != 1
            or _pd_uuid(target_inputs[0].rsplit(".",1)[0]) not in pose["nodes"]):
        raise ValueError("The target direction does not belong to this pose.")
    if pose.get("falloff_blend"):
        plug = _pd_node(pose["falloff_blend"]) + ".blender"
        if cmds.getAttr(plug,lock=True) or cmds.listConnections(plug,source=True,destination=False):
            raise ValueError("The falloff mode is locked or driven.")
    return destination, current[0], target_inputs[0]


def _pd_add_linear_falloff(builder, state, pose, destination, old_source, target_vector):
    angle = builder.node("angleBetween", "angularDistance")
    conversion = builder.node("unitConversion", "angleRadians")
    linear = builder.node("remapValue", "linearAngle")
    blend = builder.node("blendColors", "falloffMode")
    builder.connect(_pd_node(state["live"]) + ".output", angle + ".vector1")
    builder.connect(target_vector, angle + ".vector2")
    # Typed angular plugs carry radians internally. Keep the numeric path in
    # radians regardless of the UI angle units at creation or later changes.
    builder.connect(angle + ".angle", conversion + ".input")
    cmds.setAttr(conversion + ".conversionFactor", 1.0)
    builder.connect(conversion + ".output", linear + ".inputValue")
    for destination_plug in (conversion + ".input", linear + ".inputValue"):
        for source in cmds.listConnections(destination_plug,source=True,destination=False,plugs=True) or []:
            node = source.rsplit(".",1)[0]
            if cmds.nodeType(node) == "unitConversion":
                cmds.setAttr(node + ".conversionFactor", 1.0)
    cmds.setAttr(linear + ".inputMin", 0)
    cmds.setAttr(linear + ".inputMax", math.radians(pose["radius"]))
    cmds.setAttr(linear + ".outputMin", 1)
    cmds.setAttr(linear + ".outputMax", 0)
    for index,value in ((0,0.0),(1,1.0)):
        cmds.setAttr(linear + ".value[{}].value_Position".format(index), value)
        cmds.setAttr(linear + ".value[{}].value_FloatValue".format(index), value)
        cmds.setAttr(linear + ".value[{}].value_Interp".format(index), 1)
    builder.connect(linear + ".outValue", blend + ".color1R")
    builder.connect(_pd_node(pose["ramp"]) + ".outValue", blend + ".color2R")
    cmds.setAttr(blend + ".blender", 1.0)
    cmds.disconnectAttr(old_source,destination)
    try:
        builder.connect(blend + ".outputR", destination)
    except Exception:
        cmds.connectAttr(old_source,destination)
        raise
    pose["linear_ramp"] = _pd_uuid(linear)
    pose["falloff_blend"] = _pd_uuid(blend)


def set_pose_driver_falloff(group, mode):
    """Upgrade/switch saved poses without replacing cone or joint output plugs."""
    mode = _pd_falloff_mode(mode)
    group,state = _pd_read(group)
    _pd_check_edit(group,state)
    links = [(pose,_pd_falloff_links(state,pose)) for pose in state["poses"]]
    if _TOOL_UNDO_DEPTH or not cmds.undoInfo(query=True,state=True):
        raise ValueError("Enable Maya Undo and set falloff outside another tool action so the entire change can be rolled back.")
    undo_name = "SetPoseDriverFalloff_" + uuid.uuid4().hex
    changed = False
    try:
        with _tool_action(undo_name):
            changed = True
            for pose,(destination,old_source,target_vector) in links:
                if mode == "linear" and not pose.get("linear_ramp"):
                    builder = _PoseDriverBuilder(":" + group.rsplit("|",1)[-1] + "_" + pose["attribute"] + "_")
                    _pd_add_linear_falloff(builder,state,pose,destination,old_source,target_vector)
                    pose["nodes"].extend(builder.members)
                    state["members"].extend(builder.members)
                if pose.get("falloff_blend"):
                    cmds.setAttr(_pd_node(pose["falloff_blend"]) + ".blender", 1 if mode == "linear" else 0)
            state["falloff_mode"] = mode
            _pd_write(group,state)
    except Exception as exc:
        if changed and cmds.undoInfo(query=True,undoName=True) == undo_name:
            cmds.undo()
            raise RuntimeError("Falloff change was rolled back; existing weights and connections were kept: {}".format(exc)) from exc
        raise
    return mode


def add_pose_driver_pose(group, name, radius=None, center=None):
    """Capture a unit-offset center; omitted/\"auto\" radius measures from default."""
    group, state = _pd_read(group)
    _pd_check_edit(group, state)
    radius_mode = _pd_radius_mode(radius)
    if radius_mode == "manual":
        radius = _pd_radius(radius)
    attribute = _pd_pose_attribute(name)
    cone = _pd_node(state["cone"])
    if cmds.attributeQuery(attribute, node=cone, exists=True) or cmds.attributeQuery(attribute + "Raw", node=cone, exists=True):
        raise ValueError("Pose attribute '{}' already exists. Use another pose name.".format(attribute))
    position = _pd_center_position(state, center)
    if radius_mode == "auto":
        radius = _pd_auto_radius(state, position)
    controller_pose = _pd_controller_pose_for_target(state, position)
    target_reference = _pd_target_reference(state, center)
    origin_change = _pd_origin_change(state)
    if not state.get("normalization_divisor"):
        repair_pose_driver_division(group)
        group,state = _pd_read(group)
    builder = _PoseDriverBuilder(":" + group.rsplit("|", 1)[-1] + "_" + attribute + "_")
    selection = cmds.ls(selection=True, long=True) or []
    attributes, joint_attributes = [], []
    old_state = json.loads(json.dumps(state))
    try:
        with _tool_action("CapturePoseDriverTarget"):
            try:
                if origin_change:
                    cmds.setAttr(origin_change[0] + ".translate", 0, 0, 0, type="double3")
                target = builder.locator("center", _pd_node(state["targets"]))
                cmds.xform(target, worldSpace=True, translation=position)
                target_direction = builder.direction(target, _pd_node(state["frame"]), "target")
                dot = builder.node("vectorProduct", "cosine")
                cmds.setAttr(dot + ".operation", 1)
                cmds.setAttr(dot + ".normalizeOutput", False)
                builder.connect(_pd_node(state["live"]) + ".output", dot + ".input1")
                builder.connect(target_direction["vector"] + ".output", dot + ".input2")
                ramp = builder.node("remapValue", "falloff")
                cmds.setAttr(ramp + ".inputMin", math.cos(math.radians(radius)))
                cmds.setAttr(ramp + ".inputMax", 1)
                cmds.setAttr(ramp + ".outputMin", 0)
                cmds.setAttr(ramp + ".outputMax", 1)
                for index, value in ((0, 0.0), (1, 1.0)):
                    cmds.setAttr(ramp + ".value[{}].value_Position".format(index), value)
                    cmds.setAttr(ramp + ".value[{}].value_FloatValue".format(index), value)
                    cmds.setAttr(ramp + ".value[{}].value_Interp".format(index), 2)  # Smooth
                builder.connect(dot + ".outputX", ramp + ".inputValue")
                valid = builder.node("condition", "validCenter")
                cmds.setAttr(valid + ".operation", 2)
                cmds.setAttr(valid + ".secondTerm", 1e-8)
                cmds.setAttr(valid + ".colorIfFalseR", 0)
                builder.connect(target_direction["length"] + ".outputX", valid + ".firstTerm")
                builder.connect(ramp + ".outValue", valid + ".colorIfTrueR")
                raw = valid + ".outColorR"
                numerator = _pd_build_normalization_numerator(builder,raw)
                normalized = builder.node("multiplyDivide", "normalized")
                cmds.setAttr(normalized + ".input2", 1, 1, 1, type="float3")
                builder.connect(_pd_node(state["normalization_divisor"]) + ".outputR", normalized + ".input2X")
                builder.connect(numerator + ".outputX", normalized + ".input1X")
                cmds.setAttr(normalized + ".operation", 2)
                blend = builder.node("blendColors", "weight")
                builder.connect(normalized + ".outputX", blend + ".color1R")
                builder.connect(raw, blend + ".color2R")
                builder.connect(cone + ".normalize", blend + ".blender")
                builder.connect(raw, _pd_node(state["sum"]) + ".input1D[{}]".format(state["next_index"]))
                for attr, source in ((attribute, blend + ".outputR"), (attribute + "Raw", raw)):
                    cmds.addAttr(cone, longName=attr, attributeType="double", minValue=0, maxValue=1, keyable=True)
                    attributes.append(attr)
                    builder.connect(source, cone + "." + attr)
                    cmds.setAttr(cone + "." + attr, lock=False, keyable=True, channelBox=True)
                record = {"id": uuid.uuid4().hex, "name": name.strip(), "attribute": attribute,
                          "center": _pd_uuid(target), "radius": radius, "radius_mode": radius_mode, "ramp": _pd_uuid(ramp),
                          "target_object": target_reference, "center_offset": 1.0,
                          "index": state["next_index"], "nodes": builder.members[:]}
                record.update(normalization_numerator=_pd_uuid(numerator),normalizer=_pd_uuid(normalized))
                if controller_pose:
                    record["controller_pose"] = controller_pose
                if state.get("falloff_mode", "smooth") == "linear":
                    _pd_add_linear_falloff(builder,state,record,valid+".colorIfTrueR",ramp+".outValue",target_direction["vector"]+".output")
                    record["nodes"] = builder.members[:]
                joint_attributes = _pd_publish_joint_weights(state, record)
                state["members"].extend(builder.members)
                state["poses"].append(record)
                state["next_index"] += 1
                _pd_write(group, state)
            except Exception:
                _pd_delete_created_joint_weights(state, joint_attributes)
                for attr in attributes:
                    if cmds.attributeQuery(attr, node=cone, exists=True):
                        cmds.setAttr(cone + "." + attr, lock=False)
                        cmds.deleteAttr(cone + "." + attr)
                builder.cleanup()
                if origin_change:
                    cmds.setAttr(origin_change[0] + ".translate", *origin_change[1], type="double3")
                cmds.setAttr(_pd_node(old_state["sum"]) + ".input1D[{}]".format(old_state["next_index"]), 0)
                _pd_write(group, old_state)
                raise
    finally:
        _restore_locator_view_selection(selection)
    return record


def update_pose_driver_pose(group, pose_id, radius=None, center=None, recapture=False):
    """Keep output/graph stable; None keeps angle mode, \"auto\" remeasures it."""
    group, state = _pd_read(group)
    _pd_check_edit(group, state)
    pose = next((p for p in state["poses"] if p["id"] == pose_id), None)
    if pose is None:
        raise ValueError("The target pose no longer exists. Reload the setup.")
    radius_mode = _pd_radius_mode(radius, pose)
    target, ramp = _pd_node(pose["center"]), _pd_node(pose["ramp"])
    # A supplied target always wins, including legacy callers passing recapture.
    center = center.strip() if isinstance(center, str) else center
    position = _pd_center_position(state, center) if recapture or center else None
    radius_position = position if position is not None else cmds.xform(target, query=True, worldSpace=True, translation=True)
    new_radius = (_pd_auto_radius(state, radius_position) if radius_mode == "auto"
                  else _pd_radius(radius if radius is not None else pose["radius"]))
    target_reference = _pd_target_reference(state, center) if center else None
    origin_change = _pd_origin_change(state) if position is not None else None
    old_state = json.loads(json.dumps(state))
    for attr in ("translate", "translateX", "translateY", "translateZ"):
        if position is not None and (cmds.getAttr(target + "." + attr, lock=True)
                or cmds.listConnections(target + "." + attr, source=True, destination=False)):
            raise ValueError("The captured target center is locked or driven: {}".format(target))
    if cmds.getAttr(ramp + ".inputMin", lock=True) or cmds.listConnections(ramp + ".inputMin", source=True, destination=False):
        raise ValueError("The pose falloff node is locked or driven.")
    linear = _pd_node(pose["linear_ramp"]) if pose.get("linear_ramp") else None
    if linear and (cmds.getAttr(linear+".inputMax",lock=True) or cmds.listConnections(linear+".inputMax",source=True,destination=False)):
        raise ValueError("The linear falloff radius is locked or driven.")
    old_position = cmds.xform(target, query=True, worldSpace=True, translation=True)
    controller_pose = _pd_controller_pose_for_target(state, position) if position is not None else None
    changed_direction = position is not None and any(abs(a-b) > 1e-6 for a,b in zip(position,old_position))
    old_radius = pose["radius"]
    with _tool_action("UpdatePoseDriverTarget"):
        try:
            if origin_change:
                cmds.setAttr(origin_change[0] + ".translate", 0, 0, 0, type="double3")
            if position is not None:
                cmds.xform(target, worldSpace=True, translation=position)
            cmds.setAttr(ramp + ".inputMin", math.cos(math.radians(new_radius)))
            if linear:
                cmds.setAttr(linear + ".inputMax", math.radians(new_radius))
            pose["radius"] = new_radius
            pose["radius_mode"] = radius_mode
            if position is not None:
                pose["target_object"] = target_reference
                pose["center_offset"] = 1.0
                if controller_pose:
                    pose["controller_pose"] = controller_pose
                elif changed_direction:
                    pose.pop("controller_pose", None)
            _pd_write(group, state)
        except Exception:
            if position is not None:
                cmds.xform(target, worldSpace=True, translation=old_position)
            cmds.setAttr(ramp + ".inputMin", math.cos(math.radians(old_radius)))
            if linear:
                cmds.setAttr(linear + ".inputMax", math.radians(old_radius))
            if origin_change:
                cmds.setAttr(origin_change[0] + ".translate", *origin_change[1], type="double3")
            _pd_write(group, old_state)
            raise
    return pose


def _pd_check_output_attributes(cone, attributes, owned, allowed_plugs=()):
    for attribute in attributes:
        if cmds.attributeQuery(attribute, node=cone, exists=True):
            for plug in cmds.listConnections(cone + "." + attribute, source=False, destination=True, plugs=True) or []:
                if (_pd_uuid(plug.rsplit(".", 1)[0]) not in owned
                        and not any(_pd_same_plug(plug, allowed) for allowed in allowed_plugs)):
                    raise ValueError("'{}' drives '{}'. Disconnect that consumer before removing this pose/system.".format(attribute, plug))


def _pd_check_consumers(cone, pose, owned, state=None):
    joint = _guide_ik_resolve_uuid(state["joint"]) if state else None
    allowed = [joint + "." + attribute for output, attribute in pose.get("joint_attributes", {}).items()
               if joint and _pd_joint_weight_input(state, output, attribute)]
    _pd_check_output_attributes(cone, (pose["attribute"], pose["attribute"] + "Raw"), owned, allowed)


def remove_pose_driver_pose(group, pose_id):
    group, state = _pd_read(group)
    pose = next((p for p in state["poses"] if p["id"] == pose_id), None)
    if pose is None:
        raise ValueError("The target pose no longer exists.")
    _pd_check_members(state, [_pd_uuid(group)] + pose["nodes"])
    cone = _pd_node(state["cone"])
    _pd_check_consumers(cone, pose, set(state["members"]), state)
    _pd_check_joint_weight_removal(state, [pose])
    total = _pd_node(state["sum"])
    slot = total + ".input1D[{}]".format(pose["index"])
    if cmds.getAttr(slot, lock=True):
        raise ValueError("The pose's sum input is locked.")
    for driver in cmds.listConnections(slot, source=True, destination=False) or []:
        if _pd_uuid(driver) not in set(pose["nodes"]):
            raise ValueError("The pose's sum input has a new external driver.")
    with _tool_action("RemovePoseDriverTarget"):
        _pd_remove_joint_weights(state, [pose])
        for attribute in (pose["attribute"], pose["attribute"] + "Raw"):
            if cmds.attributeQuery(attribute, node=cone, exists=True):
                cmds.setAttr(cone + "." + attribute, lock=False)
                cmds.deleteAttr(cone + "." + attribute)
        _guide_ik_delete_owned(pose["nodes"])
        total = _pd_node(state["sum"])
        cmds.setAttr(total + ".input1D[{}]".format(pose["index"]), 0)
        state["poses"].remove(pose)
        state["members"] = [identity for identity in state["members"] if identity not in set(pose["nodes"])]
        _pd_write(group, state)
    return pose


def set_pose_driver_normalize(group, value):
    group, state = _pd_read(group)
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Normalize must be between 0 and 1.")
    cone = _pd_node(state["cone"])
    plug = cone + ".normalize"
    if cmds.getAttr(plug, lock=True) or cmds.listConnections(plug, source=True, destination=False):
        raise ValueError("Normalize is locked or driven; edit its driver instead.")
    with _tool_action("SetPoseDriverNormalize"):
        cmds.setAttr(plug, value)


def repair_pose_driver_division(group):
    """Upgrade normalization so every active Divide divisor is at least one."""
    group,state = _pd_read(group);_pd_check_edit(group,state)
    original=json.loads(json.dumps(state))
    denominator,total,cone = (_pd_node(state[key]) for key in ('denominator','sum','cone'))
    if cmds.nodeType(denominator)!='condition' or cmds.nodeType(total)!='plusMinusAverage':
        raise ValueError('The normalization guard was replaced; repair stopped.')
    values={denominator+'.operation':2,denominator+'.secondTerm':_POSE_DRIVER_EPSILON,
            denominator+'.colorIfFalseR':_POSE_DRIVER_EPSILON}
    expected=[(total+'.output1D',denominator+'.'+attr) for attr in ('firstTerm','colorIfTrueR')]
    normalizers=[];raws=[];migrate=not state.get('normalization_divisor')
    def owned_node(identity,kind):
        node=_pd_node(identity)
        if cmds.nodeType(node)!=kind:raise ValueError('The saved normalization node type changed: '+node)
        return node
    if not migrate:
        scaled_sum=owned_node(state['normalization_sum'],'multiplyDivide')
        divisor=owned_node(state['normalization_divisor'],'clamp')
        values.update({scaled_sum+'.operation':1,scaled_sum+'.input2X':_POSE_DRIVER_WEIGHT_SCALE,
                       divisor+'.minR':1.,divisor+'.maxR':1e30})
        expected.extend([(total+'.output1D',scaled_sum+'.input1X'),(scaled_sum+'.outputX',divisor+'.inputR')])
    for pose in state['poses']:
        outputs=cmds.listConnections(cone+'.'+pose['attribute'],source=True,destination=False,plugs=True) or []
        raw_inputs=cmds.listConnections(cone+'.'+pose['attribute']+'Raw',source=True,destination=False,plugs=True) or []
        if len(outputs)!=1 or len(raw_inputs)!=1:raise ValueError('The pose weight output has changed; repair stopped.')
        blend,attr=outputs[0].rsplit('.',1);raw=raw_inputs[0]
        if (attr!='outputR' or cmds.nodeType(blend)!='blendColors' or _pd_uuid(blend) not in pose['nodes']
                or _pd_uuid(raw.rsplit('.',1)[0]) not in pose['nodes']):
            raise ValueError('The pose output no longer belongs to its saved graph.')
        inputs=cmds.listConnections(blend+'.color1R',source=True,destination=False,plugs=True) or []
        if len(inputs)!=1:raise ValueError('The normalized weight connection is missing or ambiguous.')
        node,attr=inputs[0].rsplit('.',1)
        if attr!='outputX' or cmds.nodeType(node)!='multiplyDivide' or _pd_uuid(node) not in pose['nodes']:
            raise ValueError('The normalization node no longer belongs to this pose.')
        normalizers.append(node);raws.append(raw);values[node+'.operation']=2
        if pose.get('normalizer') and pose['normalizer']!=_pd_uuid(node):raise ValueError('Normalizer ownership changed.')
        if pose.get('normalization_numerator'):
            numerator=owned_node(pose['normalization_numerator'],'multiplyDivide')
            values.update({numerator+'.operation':1,numerator+'.input2X':_POSE_DRIVER_WEIGHT_SCALE})
            expected.extend([(raw,numerator+'.input1X'),(numerator+'.outputX',node+'.input1X')])
        else:expected.append((raw,node+'.input1X'))
        expected.append(((denominator+'.outColorR') if migrate else (divisor+'.outputR'),node+'.input2X'))
        for axis in 'YZ':
            if cmds.listConnections(node+'.output'+axis,source=False,destination=True,plugs=True):
                raise ValueError('Unused normalization channels have custom consumers; repair stopped.')
            values[node+'.input2'+axis]=1.
    missing=[]
    for source,destination in expected:
        inputs=cmds.listConnections(destination,source=True,destination=False,plugs=True) or []
        if cmds.getAttr(destination,lock=True) or (inputs and (len(inputs)!=1 or not _pd_same_plug(inputs[0],source))):
            raise ValueError('Normalization input is locked or has another driver: '+destination)
        if not inputs:missing.append((source,destination))
    old={}
    for plug,value in values.items():
        if cmds.getAttr(plug,lock=True) or cmds.listConnections(plug,source=True,destination=False):
            raise ValueError('Normalization setting is locked or driven: '+plug)
        old[plug]=cmds.getAttr(plug)
    needs_numerators=any(not pose.get('normalization_numerator') for pose in state['poses'])
    if (not migrate and not needs_numerators and not missing
            and all(math.isclose(float(old[plug]),float(value),rel_tol=1e-6,abs_tol=0) for plug,value in values.items())):
        return {'normalizers':len(normalizers),'changed':False}
    builder=_PoseDriverBuilder(':'+group.rsplit('|',1)[-1]+'_normalizationRepair_')
    changed_links=[];metadata_attempted=False
    def wire(source,destination):
        current=cmds.listConnections(destination,source=True,destination=False,plugs=True) or []
        if current and _pd_same_plug(current[0],source):return
        previous=current[0] if current else None
        changed_links.append((destination,previous,source,cmds.getAttr(destination) if previous is None else None))
        if previous:cmds.disconnectAttr(previous,destination)
        builder.connect(source,destination)
    with _tool_action('RepairPoseDriverDivision'):
        try:
            for node in normalizers:cmds.setAttr(node+'.operation',0)
            for plug,value in values.items():
                if plug not in {node+'.operation' for node in normalizers}:cmds.setAttr(plug,value)
            if migrate:
                state.update(_pd_build_normalization_divisor(builder,total))
                divisor=_pd_node(state['normalization_divisor'])
            for source,destination in missing:
                if destination not in {node+'.input2X' for node in normalizers}:wire(source,destination)
            for pose,node,raw in zip(state['poses'],normalizers,raws):
                if not pose.get('normalization_numerator'):
                    before=len(builder.members);numerator=_pd_build_normalization_numerator(builder,raw)
                    pose['normalization_numerator']=_pd_uuid(numerator);pose['nodes'].extend(builder.members[before:])
                else:numerator=_pd_node(pose['normalization_numerator'])
                pose['normalizer']=_pd_uuid(node)
                wire(numerator+'.outputX',node+'.input1X');wire(divisor+'.outputR',node+'.input2X')
            state['members'].extend(identity for identity in builder.members if identity not in state['members'])
            metadata_attempted=True;_pd_write(group,state)
            for node in normalizers:cmds.setAttr(node+'.operation',2)
        except Exception:
            for node in normalizers:cmds.setAttr(node+'.operation',0)
            for destination,previous,source,previous_value in reversed(changed_links):
                current=cmds.listConnections(destination,source=True,destination=False,plugs=True) or []
                if current:cmds.disconnectAttr(current[0],destination)
                if previous:cmds.connectAttr(previous,destination)
                else:cmds.setAttr(destination,previous_value)
            builder.cleanup()
            if metadata_attempted:_pd_write(group,original)
            for plug,value in old.items():
                if plug not in {node+'.operation' for node in normalizers}:cmds.setAttr(plug,value)
            for node in normalizers:cmds.setAttr(node+'.operation',old[node+'.operation'])
            raise
    return {'normalizers':len(normalizers),'changed':True}


def _pd_prepare_weight_consumers(state):
    """Sample all external weight receivers before changing any connections."""
    cone, joint = _guide_ik_resolve_uuid(state["cone"]), _guide_ik_resolve_uuid(state["joint"])
    owned = set(state["members"])
    displays, outputs = [], [cone + ".normalize", cone + ".rawWeightSum"] if cone else []
    for pose in state["poses"]:
        if cone:
            outputs.extend(cone + "." + attribute for attribute in (pose["attribute"],pose["attribute"]+"Raw"))
        for source,attribute in pose.get("joint_attributes",{}).items():
            if joint and _pd_joint_weight_input(state,source,attribute):
                plug = joint + "." + attribute
                displays.append(plug)
                outputs.append(plug)
    receivers = []
    seen = set()
    for source in outputs:
        if not cmds.objExists(source):
            continue
        for destination in cmds.listConnections(source,source=False,destination=True,plugs=True) or []:
            node,attribute = destination.rsplit(".",1)
            identity = _pd_uuid(node)
            key = (identity,attribute)
            if identity in owned or any(_pd_same_plug(destination,plug) for plug in displays) or key in seen:
                continue
            if cmds.referenceQuery(node,isNodeReferenced=True) or (cmds.lockNode(node,query=True,lock=True) or [False])[0]:
                raise ValueError("Cannot keep the connected value on locked/referenced '{}'.".format(destination))
            inputs = cmds.listConnections(destination,source=True,destination=False,plugs=True) or []
            if len(inputs) != 1 or not _pd_same_plug(inputs[0],source):
                raise ValueError("The weight receiver input changed: {}".format(destination))
            value = cmds.getAttr(destination)
            if not isinstance(value,(int,float)) or not math.isfinite(value):
                raise ValueError("Cannot keep a non-scalar weight receiver value: {}".format(destination))
            receivers.append({"source":inputs[0],"destination":destination,"value":value,
                              "locked":cmds.getAttr(destination,lock=True)})
            seen.add(key)
    return receivers


def _pd_keep_weight_values(receivers):
    for receiver in receivers:
        plug = receiver["destination"]
        try:
            if receiver["locked"]:
                cmds.setAttr(plug,lock=False)
            cmds.disconnectAttr(receiver["source"],plug)
            cmds.setAttr(plug,receiver["value"])
        finally:
            if receiver["locked"] and cmds.objExists(plug):
                cmds.setAttr(plug,lock=True)


def remove_pose_driver(group, preserve_consumers=False):
    """Remove owned nodes/displays, optionally keeping connected weight values."""
    group, state = _pd_read(group)
    _pd_check_members(state)
    receivers = _pd_prepare_weight_consumers(state) if preserve_consumers else []
    if preserve_consumers and (_TOOL_UNDO_DEPTH or not cmds.undoInfo(query=True,state=True)):
        raise ValueError("Enable Maya Undo and remove outside another tool action so connected values can be kept safely.")
    selection = cmds.ls(selection=True, long=True) or []
    undo_name = "RemovePoseDriver_" + uuid.uuid4().hex
    changed = False
    try:
        try:
            with _tool_action(undo_name):
                if preserve_consumers:
                    changed = bool(receivers)
                    _pd_keep_weight_values(receivers)
                cone = _guide_ik_resolve_uuid(state["cone"])
                if cone:
                    _pd_check_output_attributes(cone, ("normalize", "rawWeightSum"), set(state["members"]))
                    for pose in state["poses"]:
                        _pd_check_consumers(cone, pose, set(state["members"]), state)
                _pd_check_joint_weight_removal(state, state["poses"])
                changed = True
                _pd_remove_joint_weights(state, state["poses"])
                _guide_ik_delete_owned(state["members"])
        except Exception as exc:
            if preserve_consumers and changed and cmds.undoInfo(query=True,undoName=True) == undo_name:
                cmds.undo()
                raise RuntimeError("Removal was rolled back; the setup and connected targets were kept: {}".format(exc)) from exc
            raise
    finally:
        _restore_locator_view_selection(selection)
    return group


def _pd_mirror_tokens(search, replace):
    search, replace = str(search), str(replace)
    if not search or not replace or search == replace:
        raise ValueError("Search and Replace must be nonempty and different.")
    if any(c in search + replace for c in "|:*?[]"):
        raise ValueError("Use literal name tokens, without paths, namespaces or wildcards.")
    return search, replace


def _pd_mirror_name(path, search, replace):
    # Preserve namespace prefixes; replace only each DAG component's basename.
    parts = []
    for part in path.split("|"):
        namespace, sep, leaf = part.rpartition(":")
        parts.append(namespace + sep + leaf.replace(search, replace))
    return "|".join(parts)


def _pd_mirror_object(node, search, replace, require_change=False):
    node = _resolve_hierarchy_root(node)
    expected = _pd_mirror_name(node, search, replace)
    if expected == node:
        if require_change:
            raise ValueError("The source joint name/path does not contain '{}'.".format(search))
        return node  # Shared centerline target.
    exact = cmds.ls(expected, long=True) or []
    if len(exact) == 1:
        return _resolve_hierarchy_root(exact[0])
    # The opposite hierarchy may have different ancestors. Match a unique leaf
    # in the SAME namespace rather than accepting Maya's current namespace.
    leaf = expected.rsplit("|", 1)[-1]
    candidates = [n for n in (cmds.ls(long=True) or [])
                  if n.rsplit("|", 1)[-1] == leaf and cmds.nodeType(n) in ("transform", "joint")]
    if len(candidates) != 1:
        raise ValueError("{} counterpart for '{}': expected '{}'.".format(
            "Missing" if not candidates else "Ambiguous", node, expected))
    return _resolve_hierarchy_root(candidates[0])


def plan_pose_driver_mirror(group, search="_L", replace="_R", flip_axis=True, reflection_axis="X"):
    """Read-only counterpart search. Resolve everything before creating nodes."""
    search, replace = _pd_mirror_tokens(search, replace)
    reflection_axis = str(reflection_axis).upper()
    if reflection_axis not in "XYZ" or len(reflection_axis) != 1:
        raise ValueError("Reflection axis must be X, Y or Z.")
    group, state = _pd_read(group)
    source_joint = _pd_node(state["joint"])
    target_joint = _pd_joint(_pd_mirror_object(source_joint, search, replace, require_change=True))
    if _pd_uuid(target_joint) == state["joint"]:
        raise ValueError("Mirror requires a different destination joint.")
    groups = find_pose_drivers(target_joint)
    if len(groups) > 1:
        raise ValueError("The destination joint has multiple PoseDriver setups.")
    destination, destination_state = _pd_read(groups[0]) if groups else (None, None)
    if destination_state:
        _pd_check_edit(destination, destination_state)
    origin = cmds.xform(source_joint, query=True, worldSpace=True, translation=True)
    target_origin = cmds.xform(target_joint, query=True, worldSpace=True, translation=True)
    if destination_state:
        frame_origin = cmds.xform(_pd_node(destination_state["frame"]), query=True, worldSpace=True, translation=True)
        if any(abs(a-b) > 1e-4 for a,b in zip(target_origin, frame_origin)):
            raise ValueError("The destination joint moved away from its captured start origin.")
    existing = {p["attribute"]: p for p in destination_state["poses"]} if destination_state else {}
    poses, attributes = [], set()
    for pose in state["poses"]:
        name = pose["name"].replace(search, replace)
        attribute = _pd_pose_attribute(name)
        if attribute in attributes:
            raise ValueError("Search/Replace produces duplicate pose output '{}'.".format(attribute))
        attributes.add(attribute)
        target, source_target = None, None
        if pose.get("target_object"):
            source_target = _pd_node(pose["target_object"])
            target = _pd_mirror_object(source_target, search, replace)
            # Reject a live cone or any source-owned helper as an external pose.
            owned = set(state["members"]) | (set(destination_state["members"]) if destination_state else set())
            if _pd_uuid(target) in owned:
                raise ValueError("A mirror target must be an external pose object: {}".format(target))
            position = pose_driver_unit_center(target_origin,
                cmds.xform(target, query=True, worldSpace=True, translation=True))
        else:
            source_center = cmds.xform(_pd_node(pose["center"]), query=True, worldSpace=True, translation=True)
            direction = [b-a for a,b in zip(origin, source_center)]
            direction["XYZ".index(reflection_axis)] *= -1
            position = pose_driver_unit_center(target_origin, [a+b for a,b in zip(target_origin, direction)])
        current = existing.get(attribute)
        if destination_state:
            cone = _pd_node(destination_state["cone"])
            if not current and any(cmds.attributeQuery(a, node=cone, exists=True) for a in (attribute, attribute+"Raw")):
                raise ValueError("Destination output '{}' already exists outside its saved poses.".format(attribute))
        poses.append({"name": name, "radius": pose["radius"], "radius_mode": pose.get("radius_mode", "manual"), "attribute": attribute,
                      "source_target": source_target, "target": target, "position": position,
                      "existing_id": current["id"] if current else None})
    return {"source": group, "source_joint": source_joint, "joint": target_joint,
            "group": destination, "axis": -state["axis"] if flip_axis else state["axis"],
            "reflection_axis": reflection_axis, "poses": poses}


def _pd_set_axis(group, axis):
    group, state = _pd_read(group)
    _pd_check_edit(group, state)
    cone = _pd_node(state["cone"])
    plug = cone + ".translateX"
    if cmds.listConnections(plug, source=True, destination=False):
        raise ValueError("The destination cone offset has an external driver.")
    old_lock = cmds.getAttr(plug, lock=True)
    try:
        cmds.setAttr(plug, lock=False)
        cmds.setAttr(plug, axis)
        state["axis"] = axis
        _pd_write(group, state)
    finally:
        cmds.setAttr(plug, lock=old_lock)


def mirror_pose_driver(group, search="_L", replace="_R", flip_axis=True, reflection_axis="X"):
    """Create/update opposite-side poses using the standard capture/update graph."""
    plan = plan_pose_driver_mirror(group, search, replace, flip_axis, reflection_axis)
    # A single rollback boundary protects existing output graphs if any edit fails.
    if _TOOL_UNDO_DEPTH or not cmds.undoInfo(query=True, state=True):
        raise ValueError("Enable Maya Undo and run Mirror outside another tool action, so the whole mirror can be rolled back if an edit fails.")
    selection = cmds.ls(selection=True, long=True) or []
    undo_name = "MirrorPoseDriver_" + uuid.uuid4().hex
    changed = False
    destination = plan["group"]
    try:
        try:
            with _tool_action(undo_name):
                changed = True
                if not destination:
                    destination = build_pose_driver(plan["joint"], plan["axis"])["group"]
                    _source_group, source_state = _pd_read(plan["source"])
                    set_pose_driver_normalize(destination, cmds.getAttr(_pd_node(source_state["cone"]) + ".normalize"))
                    _destination, destination_state = _pd_read(destination)
                    destination_state["falloff_mode"] = source_state.get("falloff_mode", "smooth")
                    _pd_write(destination,destination_state)
                _pd_set_axis(destination, plan["axis"])
                for pose in plan["poses"]:
                    temporary = None
                    try:
                        target = pose["target"]
                        if not target:
                            temporary = cmds.createNode("transform", name=":rtkMirrorRay_" + uuid.uuid4().hex, skipSelect=True)
                            cmds.xform(temporary, worldSpace=True, translation=pose["position"])
                            target = temporary
                        if pose["existing_id"]:
                            record = update_pose_driver_pose(destination, pose["existing_id"],
                                radius="auto" if pose["radius_mode"] == "auto" else pose["radius"], center=target)
                        else:
                            record = add_pose_driver_pose(destination, pose["name"],
                                radius="auto" if pose["radius_mode"] == "auto" else pose["radius"], center=target)
                        if temporary:
                            _group, state = _pd_read(destination)
                            next(p for p in state["poses"] if p["id"] == record["id"])["target_object"] = None
                            _pd_write(destination, state)
                    finally:
                        if temporary and cmds.objExists(temporary):
                            cmds.delete(temporary)
        except Exception as exc:
            if changed and cmds.undoInfo(query=True, undoName=True) == undo_name:
                cmds.undo()
                raise RuntimeError("Mirror was rolled back; the existing setups were kept: {}".format(exc)) from exc
            raise
    finally:
        _restore_locator_view_selection(selection)
    plan["group"] = destination
    return plan


def _pd_vector_angle(first, second):
    a = pose_driver_unit_center((0, 0, 0), first)
    b = pose_driver_unit_center((0, 0, 0), second)
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x*y for x,y in zip(a,b))))))


def _pd_frame_vector(matrix, vector, inverse=False):
    if len(matrix) != 16 or not all(math.isfinite(v) for v in matrix):
        raise ValueError("The start frame matrix is invalid.")
    rows = [matrix[i:i+3] for i in (0, 4, 8)]
    if not inverse:
        return tuple(sum(vector[i]*rows[i][j] for i in range(3)) for j in range(3))
    def cross(a,b):
        return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    cofactors = [cross(rows[1],rows[2]), cross(rows[2],rows[0]), cross(rows[0],rows[1])]
    determinant = sum(a*b for a,b in zip(rows[0],cofactors[0]))
    if abs(determinant) < 1e-12:
        raise ValueError("The start frame has zero scale; restore its scale before capturing.")
    return tuple(sum(a*b for a,b in zip(vector,c))/determinant for c in cofactors)


def _pd_rotation_degrees(joint):
    factor = 180.0/math.pi if cmds.currentUnit(query=True, angle=True) in ("rad", "radian") else 1.0
    rotation = [float(cmds.getAttr(joint + ".rotate" + axis))*factor for axis in "XYZ"]
    if not all(math.isfinite(v) for v in rotation):
        raise ValueError("The joint rotation must contain finite values.")
    return rotation


def _pd_default_data(state):
    joint = _pd_node(state["joint"])
    matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
    direction = pose_driver_unit_center((0,0,0), matrix[:3])
    frame = cmds.xform(_pd_node(state["frame"]), query=True, worldSpace=True, matrix=True)
    return {"default_rotation_degrees": _pd_rotation_degrees(joint),
            "default_rotate_order": int(cmds.getAttr(joint + ".rotateOrder")),
            "default_direction_local": _pd_frame_vector(frame, direction, inverse=True)}


def set_pose_driver_default_rotation(group):
    """Store the default for spacing/names and future auto-angle updates."""
    group, state = _pd_read(group)
    _pd_check_edit(group, state)
    _pd_center_position(state)  # Validate the joint is still at the frame origin.
    if state.get("driver_controller"):
        controller = _guide_ik_resolve_uuid(state["driver_controller"])
        if not controller:
            raise ValueError("The saved driver controller is missing. Get its replacement or Clear the driver field first.")
        state["default_controller_pose"] = _pd_capture_controller(controller)
    state.update(_pd_default_data(state))
    with _tool_action("SetPoseDriverDefaultRotation"):
        _pd_write(group, state)
    return state


def _pd_rotation_pose_name(joint, default, current):
    if len(default) != 3 or len(current) != 3 or not all(math.isfinite(v) for v in list(default)+list(current)):
        raise ValueError("The captured default rotation is invalid; Set default from current joint again.")
    delta = [(b-a+180.0) % 360.0 - 180.0 for a,b in zip(default,current)]
    # Whole-degree names match the user's convention; the saved direction is
    # never rounded. An output collision receives a numeric suffix below.
    parts = []
    for axis,value in zip("XYZ",delta):
        magnitude = int(math.floor(abs(value)+.5))
        parts.append(("n" if value < 0 and magnitude else "p") + axis + str(magnitude))
    leaf = joint.rsplit("|",1)[-1].rsplit(":",1)[-1]
    return leaf + "_" + "_".join(parts)


def plan_pose_driver_rotation(group, name="", minimum_angle=15.0, pose_id=None):
    """Read-only eligibility check using the same swing directions as weights."""
    group, state = _pd_read(group)
    _pd_check_edit(group, state)
    minimum_angle = float(minimum_angle)
    if not math.isfinite(minimum_angle) or not 0 <= minimum_angle <= 180:
        raise ValueError("Minimum pose distance must be between 0 and 180 degrees.")
    joint = _pd_node(state["joint"])
    position = _pd_center_position(state)
    origin = cmds.xform(joint, query=True, worldSpace=True, translation=True)
    direction = [b-a for a,b in zip(origin,position)]
    frame_matrix = cmds.xform(_pd_node(state["frame"]), query=True, worldSpace=True, matrix=True)
    local_default = state.get("default_direction_local", (1,0,0))
    if len(local_default) != 3 or not all(math.isfinite(v) for v in local_default):
        raise ValueError("The default direction is invalid; Set default from current joint again.")
    default = _pd_frame_vector(frame_matrix, [state["axis"]*v for v in local_default])
    distances = [("default", _pd_vector_angle(direction, default))]
    record = next((p for p in state["poses"] if p["id"] == pose_id),None) if pose_id else None
    if pose_id and record is None:
        raise ValueError("The target pose no longer exists. Reload the setup.")
    for pose in state["poses"]:
        if pose["id"] == pose_id:
            continue
        center = cmds.xform(_pd_node(pose["center"]),query=True,worldSpace=True,translation=True)
        distances.append((pose["name"], _pd_vector_angle(direction, [b-a for a,b in zip(origin,center)])))
    nearest, distance = min(distances, key=lambda item:item[1])
    if distance <= 1e-6 or distance+1e-6 < minimum_angle:
        raise ValueError("Pose not added: {:.2f}° from '{}'; minimum is {:.2f}°. Rotate farther from the default and existing poses.".format(distance,nearest,minimum_angle))
    name = record["name"] if record else (name or "").strip()
    if not name:
        if "default_rotation_degrees" not in state:
            raise ValueError("This older setup has no saved default rotation for names. Restore the default pose and use Set default from current joint once, or supply a pose name.")
        if int(cmds.getAttr(joint+".rotateOrder")) != state.get("default_rotate_order"):
            raise ValueError("The joint rotation order changed. Restore its default and Set default from current joint before generating names.")
        name = _pd_rotation_pose_name(joint,state["default_rotation_degrees"],_pd_rotation_degrees(joint))
        cone = _pd_node(state["cone"])
        base, suffix = name, 2
        while any(cmds.attributeQuery(a,node=cone,exists=True) for a in (_pd_pose_attribute(name),_pd_pose_attribute(name)+"Raw")):
            name = base + "_" + str(suffix)
            suffix += 1
    return {"group":group, "name":name, "position":position, "nearest":nearest,
            "angle":distance, "minimum_angle":minimum_angle, "pose_id":pose_id}


def capture_pose_driver_rotation(group, name="", minimum_angle=15.0, radius=None, pose_id=None):
    """Capture a separated direction; new poses default to an automatic angle."""
    plan = plan_pose_driver_rotation(group,name,minimum_angle,pose_id)
    if pose_id:
        return update_pose_driver_pose(plan["group"],pose_id,radius=radius,recapture=True)
    return add_pose_driver_pose(plan["group"],plan["name"],radius=radius)


class PoseDriverPoseRow(QtWidgets.QGroupBox):
    def __init__(self, owner, record=None):
        super(PoseDriverPoseRow, self).__init__("Target pose")
        self.owner = owner
        self.pose_id = record["id"] if record else None
        form = QtWidgets.QFormLayout(self)
        self.name = QtWidgets.QLineEdit(record["name"] if record else "")
        self.name.setPlaceholderText("Optional for joint capture · joint_nX20_pY10_pZ0")
        self.name.setReadOnly(record is not None)
        self.name.setToolTip("A captured pose keeps its name/output plug stable. Add a new pose for a different output name.")
        form.addRow("Pose name:", self.name)
        self.center = QtWidgets.QLineEdit()
        self.center.setPlaceholderText("Optional · blank uses the current joint rotation")
        if record:
            node = _guide_ik_resolve_uuid(record.get("target_object") or record["center"])
            self.center.setText(node or "")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.center, 1)
        selected = QtWidgets.QPushButton("Get selected")
        selected.clicked.connect(self._get_selected)
        row.addWidget(selected)
        form.addRow("Target pose object:", row)
        self.radius = QtWidgets.QDoubleSpinBox()
        self.radius.setRange(.1, 180)
        self.radius.setDecimals(2)
        self.radius.setValue(record["radius"] if record else .1)
        self.radius.setSuffix("°")
        self.auto_radius = QtWidgets.QCheckBox("Auto from default")
        self.auto_radius.setToolTip("Compute the angle between the saved default and this target direction on capture/update. Uncheck to enter a custom angle. Angles below 0.1° use a 0.1° minimum.")
        self.auto_radius.setChecked(record.get("radius_mode", "manual") == "auto" if record else True)
        self.auto_radius.toggled.connect(self._radius_mode_changed)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.auto_radius)
        row.addWidget(self.radius, 1)
        form.addRow("Falloff angle:", row)
        self._radius_mode_changed(self.auto_radius.isChecked())
        row = QtWidgets.QHBoxLayout()
        capture = QtWidgets.QPushButton("Recapture current joint" if record else "Capture current joint")
        capture.setToolTip("Clear the target pose object field to sample the current joint direction. A supplied target object is always used instead.")
        capture.clicked.connect(lambda: self.owner._apply_pose(self, True))
        capture.setEnabled(not self.center.text().strip())
        self.center.textChanged.connect(lambda text: capture.setEnabled(not text.strip()))
        apply = QtWidgets.QPushButton("Update pose / angle" if record else "Capture pose")
        apply.setToolTip("With a target object: capture its direction. With an empty target field: capture the current joint rotation, check minimum spacing and generate a name if blank.")
        apply.setProperty("role", "primary")
        apply.clicked.connect(lambda: self.owner._apply_pose(self, False))
        delete = QtWidgets.QPushButton("Remove pose" if record else "Remove row")
        delete.clicked.connect(lambda: self.owner._remove_pose(self))
        row.addWidget(apply)
        row.addWidget(capture)
        row.addWidget(delete)
        form.addRow(row)
        cache = record.get("controller_pose") if record else None
        row = QtWidgets.QHBoxLayout()
        self.goto_button = QtWidgets.QPushButton("Go to pose")
        self.goto_button.setEnabled(cache is not None)
        self.goto_button.setToolTip("Restore this pose's saved controller values. Locked or driven channels stop the action before edits; Undo restores the previous pose.")
        self.goto_button.clicked.connect(lambda: self.owner._goto_pose(self))
        self.cache_button = QtWidgets.QPushButton("Cache controller pose")
        self.cache_button.setEnabled(record is not None and bool(owner.controller_id))
        self.cache_button.setToolTip("With the joint at this target, save the selected driver controller's current keyable numeric values. Keeps the target center and weight graph.")
        self.cache_button.clicked.connect(lambda: self.owner._cache_controller_pose(self))
        row.addWidget(self.goto_button)
        row.addWidget(self.cache_button)
        form.addRow(row)
        cache_path = (_guide_ik_resolve_uuid(cache["controller"]) or cache["path"]) if cache else None
        self.controller_cache = QtWidgets.QLabel("Saved: " + cache_path if cache_path else "No controller pose cached. Pose the joint here, then Cache controller pose.")
        self.controller_cache.setWordWrap(True)
        self.controller_cache.setProperty("role", "muted")
        form.addRow(self.controller_cache)
        plug = record["attribute"] if record else "Capture creates a persistent cone weight attribute."
        self.output = QtWidgets.QLabel(plug)
        self.output.setProperty("role", "muted")
        self.output.setWordWrap(True)
        form.addRow("Output:", self.output)
        _polish_native_panel(self)

    def _radius_mode_changed(self, automatic):
        self.radius.setEnabled(not automatic)
        if self.pose_id is None:
            self.radius.setSpecialValueText("On capture" if automatic else "")
            if automatic:
                self.radius.setValue(self.radius.minimum())
            elif self.radius.value() == self.radius.minimum():
                self.radius.setValue(45)

    def _get_selected(self, *_args):
        try:
            selected = cmds.ls(selection=True, long=True) or []
            if len(selected) != 1:
                raise ValueError("Select the object that defines the joint-to-target direction.")
            self.center.setText(_resolve_hierarchy_root(selected[0]))
            self.owner.status.setText("Capture pose / Update pose places the center 1 unit from the joint toward this object, independently of the cone.")
        except (ValueError, RuntimeError) as exc:
            self.owner.status.setText(str(exc))


_POSE_SDK_MODULES={}


def _pd_sdk_module(name):
    """Reloadable UI/backend siblings; no registered Python Maya command."""
    if name not in _POSE_SDK_MODULES:
        import importlib.util
        import os
        import sys
        location=globals().get('__file__') or _pd_sdk_module.__code__.co_filename
        path=os.path.join(os.path.dirname(os.path.abspath(location)),name+'.py')
        if not os.path.isfile(path):raise RuntimeError('Toolkit helper is missing. Replace the complete toolkit folder: '+name+'.py')
        key='_rtk_'+name+'_'+uuid.uuid4().hex
        spec=importlib.util.spec_from_file_location(key,path);module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module);_POSE_SDK_MODULES[name]=module
    return _POSE_SDK_MODULES[name]


def _pd_sdk_output(group,pose_id,mode):
    _,state=_pd_read(group)
    if mode not in ('raw','final'):raise ValueError('Choose Raw or Weight / Normalize blend.')
    pose=next((p for p in state['poses'] if p['id']==pose_id),None)
    if pose is None:raise ValueError('Choose a saved target pose for its SDK weight.')
    return _pd_node(state['cone'])+'.'+pose['attribute']+('Raw' if mode=='raw' else '')


def _pd_sdk_mirror_output(group,pose_id,mode,search='_L',replace='_R'):
    search,replace=_pd_mirror_tokens(search,replace);_,state=_pd_read(group)
    pose=next((p for p in state['poses'] if p['id']==pose_id),None)
    if pose is None:raise ValueError('Choose a saved source pose.')
    joint=_pd_mirror_object(_pd_node(state['joint']),search,replace,require_change=True)
    systems=find_pose_drivers(joint)
    if len(systems)!=1:raise ValueError('Build/load one opposite PoseDriver first, or enter its weight plug manually.')
    _,target=_pd_read(systems[0]);name=_pd_mirror_name(pose['name'],search,replace)
    attr=_pd_mirror_name(pose['attribute'],search,replace)
    candidates=[p for p in target['poses'] if p['name']==name or p['attribute']==attr]
    if len(candidates)!=1:raise ValueError('Opposite pose output was not uniquely matched. Enter the mirror weight plug manually.')
    return _pd_sdk_output(systems[0],candidates[0]['id'],mode)


def _pd_sdk_widget(owner):
    return _pd_sdk_module('pose_driver_sdk_ui').SDKPanel(owner,globals(),_pd_sdk_module('pose_driver_sdk'))


class TabPoseDriver(QtWidgets.QWidget):
    """Scene-backed direction poses. No timers, expressions or evaluation callbacks."""
    def __init__(self, parent=None):
        super(TabPoseDriver, self).__init__(parent)
        self.group_id = None
        self.controller_id = None
        self.rows = []
        layout = QtWidgets.QVBoxLayout(self)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        left, right = QtWidgets.QWidget(), QtWidgets.QWidget()
        left_layout, right_layout = QtWidgets.QVBoxLayout(left), QtWidgets.QVBoxLayout(right)
        left_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setContentsMargins(0, 0, 0, 0)
        setup = QtWidgets.QGroupBox("Joint & start pose")
        form = QtWidgets.QFormLayout(setup)
        row = QtWidgets.QHBoxLayout()
        self.joint = QtWidgets.QLineEdit()
        self.joint.setPlaceholderText("Target joint")
        self.joint.textEdited.connect(self._joint_field_changed)
        row.addWidget(self.joint, 1)
        get = QtWidgets.QPushButton("Get selected")
        get.clicked.connect(self._get_joint)
        row.addWidget(get)
        form.addRow("Joint:", row)
        self.driver = QtWidgets.QLineEdit()
        self.driver.setReadOnly(True)
        self.driver.setPlaceholderText("Optional · controller that poses this joint")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.driver, 1)
        get_driver = QtWidgets.QPushButton("Get selected")
        get_driver.clicked.connect(self._get_driver)
        row.addWidget(get_driver)
        clear_driver = QtWidgets.QPushButton("Clear")
        clear_driver.clicked.connect(self._clear_driver)
        row.addWidget(clear_driver)
        form.addRow("Driver controller:", row)
        self.axis = QtWidgets.QComboBox()
        self.axis.addItem("+X · offset 1", 1)
        self.axis.addItem("−X · offset −1", -1)
        self.axis.setToolTip("Chosen when building the start frame. Remove and rebuild to change the axis.")
        form.addRow("Cone axis:", self.axis)
        row = QtWidgets.QHBoxLayout()
        start = QtWidgets.QPushButton("Capture start / Build")
        start.setProperty("role", "primary")
        start.clicked.connect(self._build_start)
        load = QtWidgets.QPushButton("Load existing")
        load.clicked.connect(self._load_existing)
        row.addWidget(start)
        row.addWidget(load)
        form.addRow(row)
        self.goto_default = QtWidgets.QPushButton("Go to default pose")
        self.goto_default.setEnabled(False)
        self.goto_default.clicked.connect(lambda: self._goto_pose())
        form.addRow(self.goto_default)
        self.saved = QtWidgets.QComboBox()
        self.saved.activated.connect(self._load_saved)
        form.addRow("Saved setups:", self.saved)
        left_layout.addWidget(setup)
        mirror = QtWidgets.QGroupBox("Mirror / Search counterparts")
        mirror_form = QtWidgets.QFormLayout(mirror)
        self.mirror_search = QtWidgets.QLineEdit("_L")
        self.mirror_replace = QtWidgets.QLineEdit("_R")
        mirror_form.addRow("Search:", self.mirror_search)
        mirror_form.addRow("Replace:", self.mirror_replace)
        self.mirror_flip = QtWidgets.QCheckBox("Flip cone offset +1 ↔ −1")
        self.mirror_flip.setChecked(True)
        mirror_form.addRow(self.mirror_flip)
        self.mirror_plane = QtWidgets.QComboBox()
        for axis in "XYZ":
            self.mirror_plane.addItem("Reflect {} direction".format(axis), axis)
        self.mirror_plane.setToolTip("For poses captured without a target object: reflect the saved world direction around this axis. Named targets always use their matching object.")
        mirror_form.addRow("Joint-only poses:", self.mirror_plane)
        row = QtWidgets.QHBoxLayout()
        swap = QtWidgets.QPushButton("Swap tokens")
        swap.clicked.connect(self._swap_mirror)
        preview = QtWidgets.QPushButton("Search / Preview")
        preview.clicked.connect(self._preview_mirror)
        apply_mirror = QtWidgets.QPushButton("Mirror / Update")
        apply_mirror.setProperty("role", "primary")
        apply_mirror.clicked.connect(self._mirror_setup)
        for button in (swap, preview, apply_mirror):
            row.addWidget(button)
        mirror_form.addRow(row)
        self.mirror_preview = QtWidgets.QPlainTextEdit()
        self.mirror_preview.setReadOnly(True)
        self.mirror_preview.setMaximumHeight(110)
        self.mirror_preview.setPlaceholderText("Search finds the opposite joint and pose objects. Mirror updates matching outputs and keeps extra destination poses.")
        mirror_form.addRow(self.mirror_preview)
        left_layout.addWidget(mirror)
        row = QtWidgets.QHBoxLayout()
        hint = QtWidgets.QLabel("Capture pose uses the target object when supplied; otherwise it captures the current joint rotation. Blank joint-capture names are generated automatically.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        row.addWidget(hint, 1)
        add = QtWidgets.QPushButton("+ Target pose")
        add.clicked.connect(lambda: self._add_row())
        row.addWidget(add)
        left_layout.addLayout(row)
        self.pose_container = QtWidgets.QWidget()
        self.pose_layout = QtWidgets.QVBoxLayout(self.pose_container)
        self.pose_layout.setContentsMargins(0, 0, 0, 0)
        self.pose_layout.addStretch()
        pose_scroll = QtWidgets.QScrollArea()
        pose_scroll.setWidgetResizable(True)
        pose_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        pose_scroll.setMinimumHeight(240)
        pose_scroll.setWidget(self.pose_container)
        left_layout.addWidget(pose_scroll, 1)
        self.cone_label = QtWidgets.QLabel("Capture a start pose to create the cone.")
        self.cone_label.setWordWrap(True)
        self.cone_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        right_layout.addWidget(self.cone_label)
        rotation_box = QtWidgets.QGroupBox("Capture rotated joint")
        form = QtWidgets.QFormLayout(rotation_box)
        self.rotation_name = QtWidgets.QLineEdit()
        self.rotation_name.setPlaceholderText("Optional · joint_nX20_pY10_pZ0")
        form.addRow("Pose name:", self.rotation_name)
        self.rotation_minimum = QtWidgets.QDoubleSpinBox()
        self.rotation_minimum.setRange(0, 180)
        self.rotation_minimum.setDecimals(1)
        self.rotation_minimum.setValue(15)
        self.rotation_minimum.setSuffix("°")
        self.rotation_minimum.setToolTip("Minimum cone-direction angle from the default and every saved pose. Twist around X alone does not create a new weight direction.")
        form.addRow("Minimum distance:", self.rotation_minimum)
        self.rotation_radius = QtWidgets.QDoubleSpinBox()
        self.rotation_radius.setRange(.1, 180)
        self.rotation_radius.setDecimals(2)
        self.rotation_radius.setSuffix("°")
        self.rotation_auto_radius = QtWidgets.QCheckBox("Auto from default")
        self.rotation_auto_radius.setToolTip("Use the angle between the default and captured joint directions. Minimum distance remains a separate pose-spacing check.")
        self.rotation_auto_radius.setChecked(True)
        self.rotation_auto_radius.toggled.connect(self._rotation_radius_mode_changed)
        self._rotation_radius_mode_changed(True)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.rotation_auto_radius)
        row.addWidget(self.rotation_radius, 1)
        form.addRow("Falloff angle:", row)
        self.rotation_default = QtWidgets.QLabel("Build a start pose to store the default rotation.")
        self.rotation_default.setWordWrap(True)
        self.rotation_default.setProperty("role", "muted")
        form.addRow(self.rotation_default)
        row = QtWidgets.QHBoxLayout()
        capture_rotation = QtWidgets.QPushButton("Capture rotation")
        capture_rotation.setProperty("role", "primary")
        capture_rotation.clicked.connect(self._capture_rotation)
        default_rotation = QtWidgets.QPushButton("Set default from current joint")
        default_rotation.setToolTip("New builds already save the default. For older setups, restore the default rotation and press this once. Changes only the spacing/naming reference; existing weight graphs stay intact.")
        default_rotation.clicked.connect(self._set_rotation_default)
        row.addWidget(capture_rotation)
        row.addWidget(default_rotation)
        form.addRow(row)
        right_layout.addWidget(rotation_box)
        falloff_box = QtWidgets.QGroupBox("Weight falloff")
        form = QtWidgets.QFormLayout(falloff_box)
        self.falloff = QtWidgets.QComboBox()
        self.falloff.addItem("Linear angle", "linear")
        self.falloff.addItem("Smooth cosine", "smooth")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.falloff, 1)
        apply_falloff = QtWidgets.QPushButton("Set falloff")
        apply_falloff.clicked.connect(self._set_falloff)
        row.addWidget(apply_falloff)
        form.addRow(row)
        hint = QtWidgets.QLabel("Linear angle: 1 − angular distance ÷ falloff angle, clamped to 0–1. Use Normalize 0 for linear final weights.")
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        form.addRow(hint)
        right_layout.addWidget(falloff_box)
        normalize_box = QtWidgets.QGroupBox("Weight normalization")
        form = QtWidgets.QFormLayout(normalize_box)
        self.normalize = QtWidgets.QDoubleSpinBox()
        self.normalize.setRange(0, 1)
        self.normalize.setDecimals(3)
        self.normalize.setSingleStep(.1)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.normalize, 1)
        apply_normalize = QtWidgets.QPushButton("Set Normalize")
        apply_normalize.clicked.connect(self._set_normalize)
        row.addWidget(apply_normalize)
        form.addRow("Normalize:", row)
        description = QtWidgets.QLabel("0: raw weights. 1: raw ÷ sum. Intermediate values blend both. Zero total gives zero weights. Overlap can reduce a normalized center weight below 1.")
        description.setWordWrap(True)
        description.setProperty("role", "muted")
        form.addRow(description)
        repair = QtWidgets.QPushButton("Repair divide protection")
        repair.setToolTip("Protect normalization with a positive denominator floor; preserve weight output and SDK connections. Undo restores the previous graph.")
        repair.clicked.connect(self._repair_division)
        form.addRow(repair)
        right_layout.addWidget(normalize_box)
        self.weights = QtWidgets.QTableWidget(0, 3)
        self.weights.setHorizontalHeaderLabels(["Pose / output", "Raw", "Weight"])
        self.weights.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.weights.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.weights.setMinimumHeight(180)
        right_layout.addWidget(self.weights)
        row = QtWidgets.QHBoxLayout()
        refresh = QtWidgets.QPushButton("Refresh weights / setups")
        refresh.clicked.connect(self._refresh)
        select = QtWidgets.QPushButton("Select cone")
        select.clicked.connect(self._select_cone)
        row.addWidget(refresh)
        row.addWidget(select)
        right_layout.addLayout(row)
        joint_weights = QtWidgets.QPushButton("Connect weights / Select joint")
        joint_weights.setToolTip("Expose/unlock saved Weight and WeightRaw outputs on the joint for Channel Box and Set Driven Key use. Existing attribute names/drivers are preserved.")
        joint_weights.clicked.connect(self._show_joint_weights)
        right_layout.addWidget(joint_weights)
        sdk_weights = QtWidgets.QPushButton("Unlock weights for SDK")
        sdk_weights.clicked.connect(self._unlock_sdk_weights)
        right_layout.addWidget(sdk_weights)
        info = QtWidgets.QLabel("Weights update live in Maya, including after this window closes. This table is a snapshot: Refresh after posing or Undo/Redo. Target objects define joint-to-object directions; generated centers sit 1 unit from the joint. Twist around the chosen X axis is ignored.")
        info.setProperty("role", "muted")
        info.setWordWrap(True)
        right_layout.addWidget(info)
        self.keep_connected_weights = QtWidgets.QCheckBox("Keep current values on connected targets")
        self.keep_connected_weights.setChecked(True)
        self.keep_connected_weights.setToolTip("Sample current weight receiver values, disconnect them and keep those values while deleting this system. Undo restores the system and its connections.")
        right_layout.addWidget(self.keep_connected_weights)
        remove = QtWidgets.QPushButton("Remove PoseDriver system")
        remove.clicked.connect(self._remove_system)
        right_layout.addWidget(remove)
        right_layout.addStretch()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([440, 300])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)
        self.sdk_group=_CollapsibleRigGroup('Set Driven Key · pose weights and curve mirror',expanded=False)
        self.sdk_panel=_pd_sdk_widget(self)
        sdk_layout=QtWidgets.QVBoxLayout(self.sdk_group.body);sdk_layout.setContentsMargins(0,0,0,0);sdk_layout.addWidget(self.sdk_panel)
        layout.addWidget(self.sdk_group)
        self.status = QtWidgets.QLabel("Select a joint at its start pose. Its parent will drive the captured frame with maintain offset; the joint drives the cone rotation.")
        self.status.setWordWrap(True)
        self.status.setProperty("role", "muted")
        layout.addWidget(self.status)
        self._refresh_saved()
        self._add_row()

    def _group(self):
        if not self.group_id:
            raise ValueError("Capture a start pose or load an existing PoseDriver first.")
        group = _pd_node(self.group_id)
        _group, state = _pd_read(group)
        if _pd_uuid(_pd_joint(self.joint.text())) != state["joint"]:
            raise ValueError("The joint field differs from the loaded setup. Load that joint's existing setup or capture its start first.")
        return group

    def _error(self, exc):
        self.status.setText(str(exc))
        cmds.warning(str(exc))

    def _mirror_options(self):
        return dict(search=self.mirror_search.text(), replace=self.mirror_replace.text(),
                    flip_axis=self.mirror_flip.isChecked(), reflection_axis=self.mirror_plane.currentData())

    def _get_driver(self, *_args):
        try:
            selection = cmds.ls(selection=True, long=True) or []
            if len(selection) != 1:
                raise ValueError("Select one driver controller, then Get selected.")
            controller = _resolve_hierarchy_root(selection[0])
            _pd_capture_controller(controller)
            if self.group_id:
                group = self._group()
                set_pose_driver_controller(group, controller)
                self._load_group(group, preserve_drafts=True)
            else:
                self.controller_id = _pd_uuid(controller)
                self.driver.setText(controller)
            self.status.setText("Driver saved. Future matching pose captures cache its values. For existing poses, pose the rig and click Cache controller pose. Set default from current joint also caches the default.")
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _clear_driver(self, *_args):
        try:
            if self.group_id:
                group = self._group()
                set_pose_driver_controller(group)
                self._load_group(group, preserve_drafts=True)
            else:
                self.controller_id = None
                self.driver.clear()
            self.status.setText("Driver binding cleared. Previously saved pose caches can still restore their own controller.")
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _cache_controller_pose(self, row):
        try:
            group = self._group()
            cache_pose_driver_controller_pose(group, row.pose_id)
            self._load_group(group, preserve_drafts=True)
            self.status.setText("Controller pose cached in the scene. Go to pose will restore it; Undo restores the previous cache.")
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _goto_pose(self, row=None):
        try:
            result = goto_pose_driver_pose(self._group(), row.pose_id if row else None)
            self._refresh_weights()
            self.status.setText("Restored '{}' on {} ({} channels). Undo once returns to the previous controller pose.".format(result["pose"],result["controller"],result["channels"]))
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _show_joint_weights(self, *_args):
        try:
            result = expose_pose_driver_joint_weights(self._group())
            cmds.select(result["joint"], replace=True)
            self.status.setText("Connected {} live weight attributes, unlocked and keyable for Set Driven Key. Select the joint as Driver and rotate it to set weight values.".format(len(result["attributes"])))
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _unlock_sdk_weights(self, *_args):
        try:
            result = unlock_pose_driver_weights(self._group())
            self.status.setText("{} weight attributes are unlocked/keyable for Set Driven Key; values and connections kept.{}".format(len(result["attributes"]),
                " Joint attributes were skipped because the joint is locked or referenced." if result["skipped_joint"] else ""))
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _set_falloff(self, *_args):
        try:
            group = self._group()
            mode = set_pose_driver_falloff(group, self.falloff.currentData())
            self._refresh_weights()
            self.status.setText("{} falloff applied to saved and future poses; cone/joint weight connections kept. Normalize 0 preserves the raw curve in the final weight.".format("Linear angle" if mode == "linear" else "Smooth cosine"))
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _capture_rotation(self, *_args):
        try:
            group = self._group()
            record = capture_pose_driver_rotation(group,self.rotation_name.text(),
                minimum_angle=self.rotation_minimum.value(),
                radius="auto" if self.rotation_auto_radius.isChecked() else self.rotation_radius.value())
            self._load_group(group,preserve_drafts=True)
            self.rotation_name.clear()
            self.status.setText("Added '{}': falloff {:.2f}° ({}). The center remains fixed as you rotate.".format(
                record["name"],record["radius"],"angle from default" if record.get("radius_mode") == "auto" else "manual"))
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _rotation_radius_mode_changed(self, automatic):
        self.rotation_radius.setEnabled(not automatic)
        self.rotation_radius.setSpecialValueText("On capture" if automatic else "")
        if automatic:
            self.rotation_radius.setValue(self.rotation_radius.minimum())
        elif self.rotation_radius.value() == self.rotation_radius.minimum():
            self.rotation_radius.setValue(45)

    def _set_rotation_default(self, *_args):
        try:
            group = self._group()
            set_pose_driver_default_rotation(group)
            self._load_group(group,preserve_drafts=True)
            self.status.setText("Stored the default for distance checks, automatic names and falloff angles. Update/recapture an automatic pose to measure its angle from this new default.")
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _swap_mirror(self, *_args):
        search, replace = self.mirror_search.text(), self.mirror_replace.text()
        self.mirror_search.setText(replace)
        self.mirror_replace.setText(search)
        self.mirror_preview.clear()

    def _show_mirror_plan(self, plan):
        lines = ["Joint: {} → {}".format(plan["source_joint"], plan["joint"]),
                 "Cone offset: {:+d}; {} setup".format(plan["axis"], "update existing" if plan["group"] else "create")]
        for pose in plan["poses"]:
            target = pose["target"] or "saved direction, reflect " + plan["reflection_axis"]
            lines.append("{}: {} → {} ({})".format(pose["name"], pose["source_target"] or "joint-only pose",
                         target, "update" if pose["existing_id"] else "add"))
        self.mirror_preview.setPlainText("\n".join(lines))

    def _preview_mirror(self, *_args):
        try:
            plan = plan_pose_driver_mirror(self._group(), **self._mirror_options())
            self._show_mirror_plan(plan)
            self.status.setText("Counterparts found. Mirror / Update uses the saved poses and these matching objects. Put a new destination joint at its start pose before building.")
        except (ValueError, RuntimeError) as exc:
            self.mirror_preview.setPlainText(str(exc))
            self._error(exc)

    def _mirror_setup(self, *_args):
        try:
            plan = mirror_pose_driver(self._group(), **self._mirror_options())
            self._show_mirror_plan(plan)
            self._refresh_saved()
            self._refresh_weights()
            self.status.setText("Mirrored {} poses to {}. The source stays loaded: run Mirror again to update the same outputs. To mirror back, load the destination from Saved setups and Swap tokens.".format(len(plan["poses"]), plan["joint"]))
        except (ValueError, RuntimeError) as exc:
            self.mirror_preview.setPlainText(str(exc))
            self._error(exc)

    def _refresh_saved(self):
        self.saved.blockSignals(True)
        self.saved.clear()
        self.saved.addItem("Choose a scene setup…", None)
        for group in list_pose_drivers():
            self.saved.addItem(group.rsplit("|", 1)[-1], _pd_uuid(group))
        self.saved.blockSignals(False)

    def _load_saved(self, index):
        identity = self.saved.itemData(index)
        if identity:
            try:
                self._load_group(_pd_node(identity))
            except (ValueError, RuntimeError) as exc:
                self._error(exc)

    def _joint_field_changed(self, *_args):
        self.group_id = None
        self.controller_id = None
        self.driver.clear()
        self.goto_default.setEnabled(False)
        self.axis.setEnabled(True)
        self.weights.setRowCount(0)
        self.cone_label.setText("Joint changed. Capture its start or Load existing.")

    def _get_joint(self, *_args):
        try:
            selection = cmds.ls(selection=True, long=True) or []
            if len(selection) != 1:
                raise ValueError("Select one joint, then Get selected.")
            chosen = _pd_joint(selection[0])
            if self.group_id:
                _group, state = _pd_read(_pd_node(self.group_id))
                if _pd_uuid(chosen) != state["joint"]:
                    self._joint_field_changed()
            self.joint.setText(chosen)
            self.status.setText("Set the start pose, choose +X or −X, then Capture start / Build; or Load existing.")
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _build_start(self, *_args):
        try:
            controller = _guide_ik_resolve_uuid(self.controller_id) if self.controller_id else None
            if self.controller_id and not controller:
                raise ValueError("The selected driver controller is missing. Get its replacement or Clear the field.")
            result = build_pose_driver(self.joint.text(), self.axis.currentData(), driver_controller=controller)
            self._load_group(result["group"])
            self.status.setText("Start captured. Capture pose uses a target object when supplied, otherwise the current joint rotation. Leave the joint-capture name blank to generate it automatically.")
            self._refresh_saved()
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _load_existing(self, *_args):
        try:
            groups = find_pose_drivers(self.joint.text())
            if len(groups) != 1:
                raise ValueError("Expected one saved PoseDriver for this joint; use Saved setups to choose.")
            self._load_group(groups[0])
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _add_row(self, record=None):
        row = PoseDriverPoseRow(self, record)
        self.pose_layout.insertWidget(self.pose_layout.count()-1, row)
        self.rows.append(row)

    def _load_group(self, group, preserve_drafts=False, consumed_row=None):
        drafts = [(row.name.text(), row.center.text(), row.radius.value(), row.auto_radius.isChecked()) for row in self.rows
                  if preserve_drafts and row.pose_id is None and row is not consumed_row]
        group, state = _pd_read(group)
        self.group_id = _pd_uuid(group)
        self.controller_id = state.get("driver_controller")
        controller = _guide_ik_resolve_uuid(self.controller_id) if self.controller_id else None
        self.driver.setText(controller or ("Missing controller — Get replacement or Clear" if self.controller_id else ""))
        self.goto_default.setEnabled(bool(state.get("default_controller_pose")))
        self.joint.setText(_pd_node(state["joint"]))
        self.axis.setCurrentIndex(0 if state["axis"] == 1 else 1)
        self.axis.setEnabled(False)
        default = state.get("default_rotation_degrees")
        self.rotation_default.setText("Default rotation: X {:.2f}°, Y {:.2f}°, Z {:.2f}°. Blank names use signed whole-degree changes.".format(*default)
            if default else "Older setup: restore its default joint rotation, then Set default from current joint to enable automatic names.")
        for row in self.rows:
            self.pose_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self.rows = []
        for record in state["poses"]:
            self._add_row(record)
        for name, center, radius, automatic in drafts:
            self._add_row()
            self.rows[-1].name.setText(name)
            self.rows[-1].center.setText(center)
            self.rows[-1].auto_radius.setChecked(automatic)
            self.rows[-1].radius.setValue(radius)
        if not self.rows:
            self._add_row()
        self._refresh_weights()
        if hasattr(self,'sdk_panel'):self.sdk_panel.refresh_poses()
        self.status.setText("Loaded scene setup. Recapture preserves each existing output plug and downstream connection.")

    def _apply_pose(self, row, capture_joint):
        try:
            group = self._group()
            target_input = row.center.text().strip()
            radius = "auto" if row.auto_radius.isChecked() else row.radius.value()
            # Both buttons share the same input routing: a supplied target wins,
            # otherwise sample the joint and allow an automatically generated name.
            use_joint = not target_input
            if use_joint:
                capture_pose_driver_rotation(group,row.name.text(),minimum_angle=self.rotation_minimum.value(),
                    radius=radius,pose_id=row.pose_id)
            elif row.pose_id:
                update_pose_driver_pose(group, row.pose_id, radius=radius,
                    center=target_input or None, recapture=use_joint)
            else:
                add_pose_driver_pose(group, row.name.text(), radius=radius,
                    center=target_input or None)
            self._load_group(group, preserve_drafts=True, consumed_row=row)
            self.status.setText("Target saved: center is 1 unit along the joint-to-target-object direction; the cone was not sampled." if target_input else
                "Current joint direction captured. Its raw weight is 1 here by design; rotate the joint to compare against this fixed pose.")
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _remove_pose(self, row):
        try:
            if row.pose_id:
                group = self._group()
                remove_pose_driver_pose(group, row.pose_id)
                self._load_group(group)
            else:
                self.rows.remove(row)
                self.pose_layout.removeWidget(row)
                row.hide()
                row.deleteLater()
            self.status.setText("Pose removed. Undo once to restore a captured pose.")
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _refresh_weights(self):
        group, state = _pd_read(self._group())
        self.falloff.setCurrentIndex(self.falloff.findData(state.get("falloff_mode", "smooth")))
        cone = _pd_node(state["cone"])
        self.cone_label.setText("Weight outputs on:\n" + cone)
        self.normalize.setValue(cmds.getAttr(cone + ".normalize"))
        self.weights.setRowCount(len(state["poses"]))
        for index, pose in enumerate(state["poses"]):
            values = [pose["attribute"], "{:.4f}".format(cmds.getAttr(cone + "." + pose["attribute"] + "Raw")),
                      "{:.4f}".format(cmds.getAttr(cone + "." + pose["attribute"]))]
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip(cone + "." + pose["attribute"] + ("Raw" if column == 1 else ""))
                self.weights.setItem(index, column, item)

    def _refresh(self, *_args):
        try:
            self._refresh_saved()
            if self.group_id:
                self._load_group(self._group())
                self.status.setText("Scene pose records and current weights refreshed. Unsaved rows were discarded.")
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _set_normalize(self, *_args):
        try:
            set_pose_driver_normalize(self._group(), self.normalize.value())
            self._refresh_weights()
            self.status.setText("Normalize saved on the cone; you can also animate that attribute in Maya.")
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _repair_division(self, *_args):
        try:
            result = repair_pose_driver_division(self._group())
            self._refresh_weights()
            self.status.setText("Divide protection checked for {} pose(s). {}".format(result["normalizers"],"Repair applied; Undo restores the previous settings." if result["changed"] else "Already protected."))
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _select_cone(self, *_args):
        try:
            _group, state = _pd_read(self._group())
            cmds.select(_pd_node(state["cone"]), replace=True)
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _remove_system(self, *_args):
        try:
            remove_pose_driver(self._group(),preserve_consumers=self.keep_connected_weights.isChecked())
            self.group_id = None
            self.axis.setEnabled(True)
            for row in self.rows:
                self.pose_layout.removeWidget(row)
                row.hide()
                row.deleteLater()
            self.rows = []
            self._add_row()
            self.weights.setRowCount(0)
            self.goto_default.setEnabled(False)
            self.cone_label.setText("No active setup.")
            self._refresh_saved()
            self.status.setText("PoseDriver removed. Source joints are preserved. Undo once restores the setup.")
        except (ValueError, RuntimeError) as exc:
            self._error(exc)


# Modular rigs: common ownership contract, with FK as the first implementation.
_RIG_MODULE_TAG = "rtkRigModuleVersion"
_RIG_MODULE_STATE = "rtkRigModuleState"
_RIG_MODULE_TYPES = ("FK", "IK3", "IKFK", "ROOT", "FOOT")


def _rig_module_node(identity):
    node = _guide_ik_resolve_uuid(identity)
    if not node:
        raise ValueError("A rig module node is missing: {}".format(identity))
    return node


def _rig_module_inputs(plug):
    return cmds.listConnections(plug, source=True, destination=False, plugs=True) or []


def _rig_module_link(plug):
    links = _rig_module_inputs(plug)
    return [_guide_ik_uuid(item.split(".", 1)[0]) for item in links]


def _rig_module_plug_key(plug):
    """Compare a plug by UUID and canonical attribute, never DAG/name spelling."""
    node, attribute = plug.split(".", 1)
    return (_guide_ik_uuid(node), cmds.attributeName(plug, long=True, leaf=False))


def _rig_module_read(module):
    nodes = cmds.ls(module, long=True) or []
    if len(nodes) != 1:
        raise ValueError("Choose one existing rig module.")
    meta = nodes[0]
    if cmds.nodeType(meta) != "network" or not cmds.attributeQuery(_RIG_MODULE_TAG, node=meta, exists=True):
        raise ValueError("Choose a Modular Rig module, rather than a source joint.")
    if cmds.getAttr(meta + "." + _RIG_MODULE_TAG) != "1":
        raise ValueError("Unsupported rig module version.")
    try:
        state = json.loads(cmds.getAttr(meta + "." + _RIG_MODULE_STATE))
        members = state["members"]
        identities = [row["uuid"] for row in members]
        sources = [row["uuid"] for row in state["joints"]]
        if (state["schema"] != 1 or state["type"] not in _RIG_MODULE_TYPES
                or state["meta"] != _guide_ik_uuid(meta)
                or len(set(identities)) != len(identities)
                or len(set(sources)) != len(sources) or (not sources and state["type"] != "ROOT")
                or set(identities).intersection(sources)
                or state["root"] not in identities or state["meta"] not in identities):
            raise ValueError("Invalid ownership records")
        rows = state["controls"]
        kinds = {row["uuid"]: row["type"] for row in members}
        if state.get('constraint_group') and kinds.get(state['constraint_group'])!='transform':
            raise ValueError('Invalid module constraint group')
        if state['type'] in ('ROOT','FOOT'):
            allowed=_rig_module_validate_extra(state,kinds,sources)
        else:
            driver_kind = "transform" if state["type"] == "FK" else "joint"
            offset_kinds = {"transform"} if state["type"] == "FK" else {"transform", "joint"}
            matrix_mode=state["type"] in ("IK3","IKFK") and state.get("ik",{}).get("solver")=="x_translate_v1"
            expected_channels = {"offsetParentMatrix"} if matrix_mode else {prefix+axis for prefix in ("translate", "rotate", "scale") for axis in "XYZ"}
            if (kinds.get(state["root"]) != "transform" or kinds.get(state["meta"]) != "network"
                    or len(rows) != len(sources) or {row["joint"] for row in rows} != set(sources)
                    or len({row["control"] for row in rows}) != len(rows)
                    or len({row["offset"] for row in rows}) != len(rows)
                    or any(kinds.get(row["control"]) != driver_kind or kinds.get(row["offset"]) not in offset_kinds
                           or row["control"] == row["offset"]
                           or len(row["constraints"]) != (1 if matrix_mode else 2)
                           or {kinds.get(identity) for identity in row["constraints"]} != ({"multMatrix"} if matrix_mode else {"parentConstraint", "scaleConstraint"})
                           or set(row["inputs"]) != expected_channels
                           or any(value["node"] not in row["constraints"] for value in row["inputs"].values())
                           for row in rows)):
                raise ValueError("Invalid module driver records")
            allowed = {"network", "transform", "nurbsCurve", "parentConstraint", "scaleConstraint"}
            if state["type"] in ("IK3","IKFK"):
                ik = state["ik"]
                expected = {"driver_group":"transform", "end":"transform", "pole":"transform",
                            "handle":"ikHandle", "effector":"ikEffector",
                            "pole_constraint":"poleVectorConstraint", "end_constraint":"orientConstraint"}
                if (len(sources) != 3 or len(ik["drivers"]) != 3
                        or set(ik["drivers"]) != {row["control"] for row in rows}
                        or (state["type"]=="IK3" and state["ui_controls"] != [ik["end"], ik["pole"]])
                        or any(kinds.get(ik[key]) != kind for key,kind in expected.items())
                        or {identity for identity,kind in kinds.items() if kind == "joint"} != set(ik["drivers"])):
                    raise ValueError("Invalid three-bone IK records")
                allowed.update({"joint", "ikHandle", "ikEffector", "poleVectorConstraint", "orientConstraint"})
                if matrix_mode:
                    if (len(ik["orientation_buffers"])!=2 or len(ik["outputs"])!=3 or len(set(ik["outputs"]))!=3
                            or ik["orientation_buffers"]!=ik["outputs"][:2]
                            or any(kinds.get(identity)!="transform" for identity in ik["outputs"])
                            or not set(ik["matrix_nodes"]).issubset(identities)
                            or any(row["type"] in ("scaleConstraint","parentConstraint") and row["uuid"] not in state.get("connection_nodes",[]) for row in members)):
                        raise ValueError("Invalid X-axis matrix IK ownership records")
                    allowed.update({"locator","pickMatrix","blendMatrix","decomposeMatrix","composeMatrix","inverseMatrix","vectorProduct"})
                features = ik.get("length_system")
                if features:
                    if (features["version"]!=1 or kinds.get(features["goal"])!="transform"
                            or not set(features["nodes"]).issubset(identities)
                            or set(features["attributes"])!=set(_RIG_MODULE_IK_LENGTH_ATTRS)
                            or len(features["rest_lengths"])!=2 or min(features["rest_lengths"])<=0):
                        raise ValueError("Invalid IK length ownership records")
                    allowed.update(_RIG_MODULE_IK_LENGTH_NODES)
                if state["type"]=="IKFK":
                    blend=state["ikfk"]
                    fk=blend["fk_controls"]
                    if (not features or blend["version"]!=1 or blend["attribute"]!="ikFkBlend"
                            or len(fk)!=3 or len(set(fk))!=3
                            or len(set(state["ui_controls"]))!=6
                            or set(state["ui_controls"]).intersection({state["root"],blend["fk_group"],ik["driver_group"]})
                            or kinds.get(blend["reverse"])!="plusMinusAverage" or kinds.get(blend["weight_node"])!="clamp"
                            or not {blend["reverse"],blend["weight_node"]}.issubset(blend["nodes"])
                            or any(kinds.get(identity)!="transform" for identity in fk+[ik["base"],blend["fk_group"]])
                            or state["ui_controls"]!=fk+[ik["base"],ik["end"],ik["pole"]]
                            or not set(blend["nodes"]).issubset(identities)):
                        raise ValueError("Invalid IK/FK ownership records")
                    if matrix_mode and (blend.get("length_mode")!="local_rotation_explicit_length_v1"
                            or len(blend.get("segment_lengths",[]))!=2
                            or any(kinds.get(row.get("node"))!="blendColors" or row.get("attribute")!="outputR"
                                   for row in blend["segment_lengths"])):
                        raise ValueError("Invalid IK/FK explicit length blend records")
        if state.get('output_version'):
            allowed.add('multMatrix')
        if state.get('connection_nodes'):
            allowed.update({'parentConstraint','scaleConstraint'})
        _rig_module_output_validate(meta, state, kinds)
        _rig_module_registration_validate(meta, state, kinds)
        _rig_module_native_connection_validate(meta, state, kinds)
        for index, row in enumerate(members):
            node = _guide_ik_resolve_uuid(row["uuid"])
            if row["type"] not in allowed or (node and cmds.nodeType(node) != row["type"]):
                raise ValueError("Invalid member type")
            if node and row["uuid"] != state["meta"] and _rig_module_link(meta + ".members[{}]".format(index)) != [row["uuid"]]:
                raise ValueError("A member ownership link changed")
        for index, row in enumerate(state["joints"]):
            node = _guide_ik_resolve_uuid(row["uuid"])
            if node and (cmds.nodeType(node) != "joint" or _rig_module_link(meta + ".sources[{}]".format(index)) != [row["uuid"]]):
                raise ValueError("A source joint link changed")
        root = _guide_ik_resolve_uuid(state["root"])
        if root and _rig_module_link(meta + ".root") != [state["root"]]:
            raise ValueError("The root link changed")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Rig module metadata is incomplete or changed: {}".format(exc)) from exc
    return meta, state



def _rig_module_inferred_start(state):
    if state['type'] == 'ROOT':
        return state.get('root_joint') or state.get('start_joint')
    if state['type'] == 'FOOT':
        return state['foot']['ankle']
    return state['joints'][0]['uuid']


def _rig_module_start_controller(state):
    return state['roles']['placement'] if state['type'] == 'ROOT' else state['root']


def _rig_module_registration_validate(meta, state, kinds):
    if 'registration_version' not in state:
        return
    controller_id = state['start_controller']
    joint_id = state.get('start_joint')
    if (state['registration_version'] != 1 or controller_id != _rig_module_start_controller(state)
            or kinds.get(controller_id) != 'transform'
            or (state['type'] != 'ROOT' and joint_id != _rig_module_inferred_start(state))
            or (state.get('root_joint') and joint_id != state['root_joint'])):
        raise ValueError('Invalid module start registration')
    controller = _guide_ik_resolve_uuid(controller_id)
    joint = _guide_ik_resolve_uuid(joint_id) if joint_id else None
    expected = [joint_id] if joint else []
    if joint and cmds.nodeType(joint) != 'joint':
        raise ValueError('Module start is not a joint')
    if controller and (_rig_module_link(meta + '.startController') != [controller_id]
            or _rig_module_link(controller + '.rtkStartModule') != [state['meta']]
            or _rig_module_link(controller + '.rtkModuleStartJoint') != expected):
        raise ValueError('The module start controller message link changed')
    if _rig_module_link(meta + '.startJoint') != expected:
        raise ValueError('The module start joint message link changed')


def _rig_module_registration_plan(meta, state, start_joint=None):
    _rig_module_output_editable(meta)
    if cmds.getAttr(meta + '.' + _RIG_MODULE_STATE, lock=True):
        raise ValueError('Unlock module metadata before registering its start joint.')
    controller = _rig_module_node(_rig_module_start_controller(state))
    _rig_module_output_editable(controller)
    identity = _rig_module_inferred_start(state)
    if start_joint is not None:
        requested = _guide_ik_uuid(_guide_ik_joint(start_joint)) if start_joint else None
        required = state.get('root_joint') if state['type'] == 'ROOT' else _rig_module_inferred_start(state)
        if required and requested != required:
            raise ValueError('The start joint must match this module\'s original first joint. A placement-only Root can use a separate scan anchor.')
        identity = requested
    if identity:
        _guide_ik_joint(_rig_module_node(identity))
    for node, attrs in ((meta, ('startJoint','startController')), (controller, ('rtkModuleStartJoint','rtkStartModule'))):
        for attr in attrs:
            if cmds.attributeQuery(attr, node=node, exists=True):
                if not state.get('registration_version'):
                    raise ValueError('An unregistered start attribute already exists: ' + node + '.' + attr)
                if cmds.getAttr(node + '.' + attr, type=True) != 'message' or cmds.getAttr(node + '.' + attr, lock=True):
                    raise ValueError('The module start attribute is locked or has another type: ' + node + '.' + attr)
    return identity, controller


def _rig_module_install_registration(meta, state, start_joint=None):
    identity, controller = _rig_module_registration_plan(meta, state, start_joint)
    if state.get('registration_version') and state.get('start_joint') == identity:
        return False
    if not state.get('registration_version'):
        for node, attrs in ((meta, ('startJoint','startController')), (controller, ('rtkModuleStartJoint','rtkStartModule'))):
            for attr in attrs:cmds.addAttr(node, longName=attr, attributeType='message')
        cmds.connectAttr(controller + '.message', meta + '.startController')
        cmds.connectAttr(meta + '.message', controller + '.rtkStartModule')
    for plug in (meta + '.startJoint', controller + '.rtkModuleStartJoint'):
        for source in _rig_module_inputs(plug):cmds.disconnectAttr(source, plug)
        if identity:cmds.connectAttr(_rig_module_node(identity) + '.message', plug)
    state.update(registration_version=1, start_joint=identity, start_controller=_guide_ik_uuid(controller))
    return True


def register_rig_start(module, start_joint=None):
    """Message-link the logical first joint; never drive or rename that joint."""
    meta, state = _rig_module_read(module)
    identity, _controller = _rig_module_registration_plan(meta, state, start_joint)
    if state.get('registration_version') and state.get('start_joint') == identity:
        return {'module':meta, 'start_joint':_guide_ik_resolve_uuid(identity) if identity else None}
    _rig_module_require_undo()
    undo_name = 'RegisterModuleStart_' + uuid.uuid4().hex
    try:
        with _tool_action(undo_name):
            _rig_module_install_registration(meta, state, start_joint)
            _rig_module_save(meta, state)
            _rig_module_read(meta)
    except Exception as exc:
        if cmds.undoInfo(query=True, undoName=True) == undo_name:
            cmds.undo();raise RuntimeError('Start registration was rolled back: ' + str(exc)) from exc
        raise
    return {'module':meta, 'start_joint':_guide_ik_resolve_uuid(identity) if identity else None}


def find_rig_starts(joint):
    """Find modules by live message connections, including shared scan anchors."""
    joint = _guide_ik_joint(joint)
    result = []
    for plug in cmds.listConnections(joint + '.message', source=False, destination=True, plugs=True) or []:
        node, attribute = plug.split('.',1)
        if attribute == 'startJoint' and cmds.attributeQuery(_RIG_MODULE_TAG, node=node, exists=True):
            meta, state = _rig_module_read(node)
            if state.get('start_joint') == _guide_ik_uuid(joint):result.append(meta)
    return sorted(set(result))


def _rig_module_output_editable(node):
    if (cmds.referenceQuery(node, isNodeReferenced=True)
            or (cmds.lockNode(node, query=True, lock=True) or [False])[0]):
        raise ValueError('Module node is locked or referenced: ' + node)


def _rig_module_output_plugs_match(actual, expected):
    return (len(actual) == len(expected)
            and [_rig_module_plug_key(plug) for plug in actual] == [_rig_module_plug_key(plug) for plug in expected])


def _rig_module_output_remember(meta, state, node):
    identity = _guide_ik_uuid(node)
    if identity not in {row['uuid'] for row in state['members']}:
        index = len(state['members'])
        state['members'].append({'uuid': identity, 'type': cmds.nodeType(node)})
        cmds.connectAttr(node + '.message', meta + '.members[{}]'.format(index))
    return identity


def _rig_module_output_child(joint, parent, remember):
    """A joint-aligned frame upstream of native source-joint constraints."""
    node = cmds.createNode('transform', name=':' + _rig_module_joint_label(joint) + '_OUTPUT', skipSelect=True)
    identity = remember(node)
    cmds.parent(node, _rig_module_node(parent), relative=True)
    node = _rig_module_node(identity)
    offset = _rig_module_matrix_product(_rig_module_matrix_value(joint + '.worldMatrix[0]'),
        _rig_module_matrix_inverse(_rig_module_matrix_value(_rig_module_node(parent) + '.worldMatrix[0]')))
    cmds.setAttr(node + '.offsetParentMatrix', *offset, type='matrix')
    return identity


def _rig_module_output_validate(meta, state, kinds):
    """Optional extension: saved modules without outputs remain readable."""
    if 'output_version' not in state:
        return
    records = state['outputs']
    if (state['output_version'] != 1 or not records
            or kinds.get(state['input']) != 'transform'
            or len({row['node'] for row in records}) != len(records)
            or len({row['role'] for row in records}) != len(records)
            or any(kinds.get(row['node']) != 'transform' for row in records)
            or {row['joint'] for row in records if row['joint']} != {row['uuid'] for row in state['joints']}
            or any(row.get('output') not in {out['node'] for out in records} for row in state['controls'])
            or (state.get('input_matrix') and kinds.get(state['input_matrix']) != 'multMatrix')):
        raise ValueError('Invalid module output/input ownership')
    joint_outputs = {row['joint']: row['node'] for row in records if row['joint']}
    if any(row['output'] != joint_outputs.get(row['joint']) for row in state['controls']):
        raise ValueError('A joint output mapping changed')
    input_node = _guide_ik_resolve_uuid(state['input'])
    if input_node and _rig_module_link(meta + '.input') != [state['input']]:
        raise ValueError('Module input link changed')
    for index, row in enumerate(records):
        node = _guide_ik_resolve_uuid(row['node'])
        if node and (_rig_module_link(meta + '.outputs[{}]'.format(index)) != [row['node']]
                or _rig_module_link(node + '.rtkOutputOwner') != [state['meta']]
                or cmds.getAttr(node + '.rtkRigOutput') != row['role']
                or _rig_module_link(node + '.rtkOutputJoint') != ([row['joint']] if row['joint'] and _guide_ik_resolve_uuid(row['joint']) else [])):
            raise ValueError('A published output link or role changed')
    attachment = state.get('attachment')
    if input_node and state.get('input_matrix'):
        matrix = _guide_ik_resolve_uuid(state['input_matrix'])
        if matrix and not _rig_module_output_plugs_match(_rig_module_inputs(input_node + '.offsetParentMatrix'), [matrix + '.matrixSum']):
            raise ValueError('Module input driver changed')
    if attachment:
        method = attachment.get('method','matrix_parent')
        if (method not in ('matrix_parent','parent_constraint') or attachment.get('module') == state['meta']
                or not attachment.get('module') or not attachment.get('output') or not attachment.get('role')
                or (method == 'matrix_parent' and not state.get('input_matrix'))):
            raise ValueError('Invalid module attachment record')
        parent = _guide_ik_resolve_uuid(attachment['output'])
        if parent and _rig_module_link(meta + '.parentOutput') != [attachment['output']]:
            raise ValueError('Module parent output link changed')
        if method == 'parent_constraint':return
        matrix = _guide_ik_resolve_uuid(state['input_matrix'])
        if input_node and matrix and not _rig_module_output_plugs_match(_rig_module_inputs(input_node + '.offsetParentMatrix'), [matrix + '.matrixSum']):
            raise ValueError('Module input driver changed')
        if matrix and parent and _rig_module_link(matrix + '.matrixIn[1]') != [attachment['output']]:
            raise ValueError('Module attachment matrix source changed')


def _rig_module_output_preflight(meta, state):
    _rig_module_output_editable(meta)
    if cmds.getAttr(meta + '.' + _RIG_MODULE_STATE, lock=True):
        raise ValueError('Unlock the module metadata before publishing outputs.')
    root = _rig_module_node(state['root'])
    _rig_module_output_editable(root)
    owned = {row['uuid'] for row in state['members']}
    top = root
    while True:
        parent = (cmds.listRelatives(top, parent=True, fullPath=True) or [None])[0]
        if not parent or _guide_ik_uuid(parent) not in owned:
            break
        top = parent
        _rig_module_output_editable(top)
    if state.get('output_version'):
        return top
    for attr in ('input', 'outputs', 'parentOutput'):
        if cmds.attributeQuery(attr, node=meta, exists=True):
            raise ValueError('An unregistered module attribute already exists: ' + meta + '.' + attr)
    matrix_mode = state['type'] in ('ROOT', 'FOOT') or state.get('ik', {}).get('solver') == 'x_translate_v1'
    for row in state['controls']:
        joint = _rig_module_node(row['joint'])
        if matrix_mode:
            matrix = _rig_module_node(row['constraints'][0])
            _rig_module_output_editable(matrix)
            end = 4 if state.get('ik', {}).get('solver') == 'x_translate_v1' else 3
            actual = _rig_module_inputs(joint + '.offsetParentMatrix')
            if not _rig_module_output_plugs_match(actual, [matrix + '.matrixSum']):
                raise ValueError('The source joint has another matrix driver: ' + joint)
            for index in range(1, end):
                plug = matrix + '.matrixIn[{}]'.format(index)
                if cmds.getAttr(plug, lock=True):
                    raise ValueError('Unlock the source matrix input: ' + plug)
                incoming = _rig_module_inputs(plug)
                if incoming and _guide_ik_uuid(incoming[0].split('.', 1)[0]) not in owned:
                    raise ValueError('The source matrix has an external input: ' + plug)
        elif not row.get('output'):
            _rig_module_output_editable(_rig_module_node(row['control']))
    return top


def _rig_module_install_outputs(meta, state):
    """Publish final frames and insert an identity input buffer, in caller's Undo."""
    if state.get('output_version'):
        return
    top = _rig_module_output_preflight(meta, state)
    prefix = ':' + _rig_module_validate_name(state['name']) + '_' + state['type'] + '_'
    remember = lambda node: _rig_module_output_remember(meta, state, node)
    root_id = state['root']
    original_parent = (cmds.listRelatives(top, parent=True, fullPath=True) or [None])[0]
    top_id = _guide_ik_uuid(top)
    input_node = cmds.createNode('transform', name=prefix + 'INPUT', skipSelect=True)
    input_id = remember(input_node)
    if original_parent:
        cmds.parent(input_node, original_parent, relative=True)
    cmds.parent(_rig_module_node(top_id), _rig_module_node(input_id), relative=True)
    state['input'] = input_id
    cmds.addAttr(meta, longName='input', attributeType='message')
    cmds.addAttr(meta, longName='outputs', attributeType='message', multi=True)
    cmds.addAttr(meta, longName='parentOutput', attributeType='message')
    cmds.connectAttr(_rig_module_node(input_id) + '.message', meta + '.input')
    group_id = None
    def world_output(label):
        nonlocal group_id
        if group_id is None:
            group = cmds.createNode('transform', name=prefix + 'OUTPUTS', skipSelect=True)
            group_id = remember(group)
            cmds.parent(group, _rig_module_node(root_id), relative=True)
            # A world-space output is already scaled by its final solution.
            cmds.setAttr(_rig_module_node(group_id) + '.inheritsTransform', False)
        node = cmds.createNode('transform', name=':' + label + '_OUTPUT', skipSelect=True)
        identity = remember(node)
        cmds.parent(node, _rig_module_node(group_id), relative=True)
        return identity
    records = []
    matrix_mode = state['type'] in ('ROOT', 'FOOT') or state.get('ik', {}).get('solver') == 'x_translate_v1'
    for row in state['controls']:
        joint = _rig_module_node(row['joint'])
        label = _rig_module_joint_label(joint)
        identity = row.get('output')
        if not identity and matrix_mode:
            identity = world_output(label)
            matrix = _rig_module_node(row['constraints'][0])
            end = 4 if state.get('ik', {}).get('solver') == 'x_translate_v1' else 3
            world = cmds.createNode('multMatrix', name=':' + label + '_outputWorldMatrix', skipSelect=True)
            world_id = remember(world)
            for index in range(1, end):
                source = matrix + '.matrixIn[{}]'.format(index)
                destination = world + '.matrixIn[{}]'.format(index - 1)
                incoming = _rig_module_inputs(source)
                if incoming:
                    cmds.connectAttr(incoming[0], destination)
                    cmds.disconnectAttr(incoming[0], source)
                else:
                    cmds.setAttr(destination, *_rig_module_matrix_value(source), type='matrix')
                cmds.setAttr(source, *_rig_module_matrix_identity(), type='matrix')
            cmds.connectAttr(world + '.matrixSum', _rig_module_node(identity) + '.offsetParentMatrix')
            cmds.connectAttr(_rig_module_node(identity) + '.worldMatrix[0]', matrix + '.matrixIn[1]')
            row['output_matrix'] = world_id
        elif not identity and state['type'] == 'IKFK':
            # Older constraint-blended rigs have no final matrix branch. Expose
            # their evaluated joint frame without changing their saved solve.
            identity = world_output(label)
            cmds.connectAttr(joint + '.worldMatrix[0]', _rig_module_node(identity) + '.offsetParentMatrix')
        elif not identity:
            identity = _rig_module_output_child(joint, row['control'], remember)
        row['output'] = identity
        records.append({'role': 'joint:' + row['joint'], 'joint': row['joint'], 'node': identity, 'label': label})
    if state['type'] == 'ROOT':
        parent = state['roles']['placement']
        node = cmds.createNode('transform', name=prefix + 'placement_OUTPUT', skipSelect=True)
        identity = remember(node)
        cmds.parent(node, _rig_module_node(parent), relative=True)
        records.insert(0, {'role': 'placement', 'joint': None, 'node': identity, 'label': 'Placement'})
    elif state['type'] == 'FOOT' and not state['foot']['drive_ankle']:
        # A reverse foot can offer a leg-IK goal without also driving the ankle.
        node = cmds.createNode('transform', name=prefix + 'ankleTarget_OUTPUT', skipSelect=True)
        identity = remember(node)
        cmds.parent(node, _rig_module_node(state['foot']['ankle_target']), relative=True)
        records.insert(0, {'role': 'ankle_target', 'joint': None, 'node': identity, 'label': 'Ankle target'})
    for index, record in enumerate(records):
        node = _rig_module_node(record['node'])
        cmds.addAttr(node, longName='rtkRigOutput', dataType='string')
        cmds.setAttr(node + '.rtkRigOutput', record['role'], type='string')
        for attribute in ('rtkOutputOwner', 'rtkOutputJoint'):
            cmds.addAttr(node, longName=attribute, attributeType='message')
        cmds.connectAttr(meta + '.message', node + '.rtkOutputOwner')
        if record['joint']:
            cmds.connectAttr(_rig_module_node(record['joint']) + '.message', node + '.rtkOutputJoint')
        cmds.connectAttr(node + '.message', meta + '.outputs[{}]'.format(index))
    state['output_version'], state['outputs'] = 1, records


def _rig_module_output_snapshots(state):
    return [{'uuid': row['uuid'], 'world': cmds.xform(_rig_module_node(row['uuid']), query=True, worldSpace=True, matrix=True),
             **{attr: cmds.getAttr(_rig_module_node(row['uuid']) + '.' + attr)
                for attr in ('jointOrient', 'rotateAxis', 'segmentScaleCompensate')}}
            for row in state['joints'] if _guide_ik_resolve_uuid(row['uuid'])]


def _rig_module_output_rows(meta, state):
    result = []
    for row in state.get('outputs', []):
        node = _guide_ik_resolve_uuid(row['node'])
        result.append(dict(row, node=node, uuid=row['node'], module=meta,
                           joint=_guide_ik_resolve_uuid(row['joint']) if row['joint'] else None,
                           available=bool(node)))
    return result


def list_rig_outputs(module):
    """Named final transforms; read-only, including for legacy modules."""
    return _rig_module_output_rows(*_rig_module_read(module))


def publish_rig_outputs(module):
    """Upgrade saved modules in place without resetting their current pose."""
    meta, state = _rig_module_read(module)
    if state.get('output_version') and state.get('registration_version'):
        return _rig_module_output_rows(meta, state)
    _rig_module_require_undo()
    _rig_module_output_preflight(meta, state)
    snapshots = _rig_module_output_snapshots(state)
    undo_name = 'PublishModuleOutputs_' + uuid.uuid4().hex
    selection = cmds.ls(selection=True, long=True) or []
    try:
        try:
            with _tool_action(undo_name):
                _rig_module_install_outputs(meta, state)
                _rig_module_install_registration(meta, state)
                _rig_module_save(meta, state)
                _rig_module_verify_pose(snapshots)
                _rig_module_read(meta)
        except Exception as exc:
            if cmds.undoInfo(query=True, undoName=True) == undo_name:
                cmds.undo()
                raise RuntimeError('Publishing outputs was rolled back: ' + str(exc)) from exc
            raise
    finally:
        _restore_locator_view_selection(selection)
    return _rig_module_output_rows(meta, state)


def _rig_module_resolve_output(output):
    nodes = cmds.ls(output, long=True) or []
    if len(nodes) != 1:
        raise ValueError('Choose one existing published module output.')
    node = nodes[0]
    if not cmds.attributeQuery('rtkOutputOwner', node=node, exists=True):
        raise ValueError('Choose a marked OUTPUT transform from the module output list.')
    owners = _rig_module_link(node + '.rtkOutputOwner')
    if len(owners) != 1:
        raise ValueError('The output owner link is missing or ambiguous.')
    meta, state = _rig_module_read(_rig_module_node(owners[0]))
    identity = _guide_ik_uuid(node)
    records = [row for row in state.get('outputs', []) if row['node'] == identity]
    if len(records) != 1:
        raise ValueError('The output is not registered by its owning module.')
    return meta, state, records[0]


def _rig_module_output_depends_on(node, owned):
    """Walk evaluation inputs and DAG parents, ignoring ownership messages."""
    pending, visited = [node], set()
    while pending:
        current = pending.pop()
        identity = _guide_ik_uuid(current)
        if identity in owned:
            return True
        if identity in visited:
            continue
        visited.add(identity)
        if len(visited) > 20000:
            raise ValueError('Output dependency check is too large; simplify the external driver graph first.')
        if cmds.objectType(current, isAType='dagNode') and not cmds.nodeType(current).endswith('Constraint'):
            pending.extend(cmds.listRelatives(current, parent=True, fullPath=True) or [])
        for plug in _rig_module_inputs(current):
            if cmds.getAttr(plug, type=True) != 'message':
                pending.append(plug.split('.', 1)[0])
    return False


def _rig_module_attachment_preflight(meta, state, output):
    if state.get('attachment',{}).get('method') == 'parent_constraint':
        raise ValueError('Detach the existing parent constraint connection before choosing another method.')
    parent_meta, parent_state, record = _rig_module_resolve_output(output)
    _rig_module_output_editable(meta)
    if not state.get('output_version'):
        raise ValueError('Publish outputs / input for the child module first.')
    if parent_state['meta'] == state['meta']:
        raise ValueError('A module cannot attach to its own output.')
    owned = {row['uuid'] for row in state['members']}
    if _rig_module_output_depends_on(_rig_module_node(record['node']), owned):
        raise ValueError('This attachment would create a dependency cycle. Choose an upstream module output.')
    input_node = _rig_module_node(state['input'])
    _rig_module_output_editable(input_node)
    if not cmds.getAttr(input_node + '.inheritsTransform'):
        raise ValueError('Enable inheritsTransform on the module INPUT before attaching it.')
    plug = input_node + '.offsetParentMatrix'
    if cmds.getAttr(plug, lock=True):
        raise ValueError('Unlock the module INPUT offsetParentMatrix before attaching it.')
    incoming = _rig_module_inputs(plug)
    expected = _rig_module_node(state['input_matrix']) + '.matrixSum' if state.get('input_matrix') else None
    if not _rig_module_output_plugs_match(incoming, [expected] if expected else []):
        raise ValueError('The module INPUT has another driver; it was kept.')
    if expected:
        _rig_module_output_editable(_rig_module_node(state['input_matrix']))
        _rig_module_attachment_matrix_preflight(meta, state)
    if cmds.getAttr(meta + '.' + _RIG_MODULE_STATE, lock=True):
        raise ValueError('Unlock module metadata before attaching it.')
    _rig_module_check_matrix(_rig_module_node(record['node']))
    parent = (cmds.listRelatives(input_node, parent=True, fullPath=True) or [None])[0]
    if parent:
        _rig_module_check_matrix(parent)
    # No animated controller channel is written by attachment.
    return parent_meta, parent_state, record


def _rig_module_attachment_matrix_preflight(meta, state):
    matrix = _rig_module_node(state['input_matrix'])
    input_node = _rig_module_node(state['input'])
    parent = (cmds.listRelatives(input_node, parent=True, fullPath=True) or [None])[0]
    attachment = state.get('attachment')
    expected = {0: [], 1: [], 2: []}
    if attachment:
        output = _guide_ik_resolve_uuid(attachment['output'])
        expected[1] = [output + '.worldMatrix[0]'] if output else []
        expected[2] = [parent + '.worldInverseMatrix[0]'] if parent else []
    for index in (0, 1, 2):
        plug = matrix + '.matrixIn[{}]'.format(index)
        if cmds.getAttr(plug, lock=True) or not _rig_module_output_plugs_match(_rig_module_inputs(plug), expected[index]):
            raise ValueError('The module attachment matrix was changed externally: ' + plug)
    if cmds.getAttr(meta + '.parentOutput', lock=True):
        raise ValueError('Unlock the module parentOutput message before changing the attachment.')


def _rig_module_connect_output(meta, state, output):
    parent_meta, parent_state, record = _rig_module_attachment_preflight(meta, state, output)
    input_node = _rig_module_node(state['input'])
    parent_output = _rig_module_node(record['node'])
    # Bind the effective parent frame. INPUT local channels remain usable and
    # must not be included twice if someone has already moved that buffer.
    parent = (cmds.listRelatives(input_node, parent=True, fullPath=True) or [None])[0]
    world = _rig_module_matrix_value(input_node + '.offsetParentMatrix')
    if parent:
        world = _rig_module_matrix_product(world, _rig_module_matrix_value(parent + '.worldMatrix[0]'))
    offset = _rig_module_matrix_product(world, _rig_module_matrix_inverse(_rig_module_matrix_value(parent_output + '.worldMatrix[0]')))
    if not state.get('input_matrix'):
        matrix = cmds.createNode('multMatrix', name=':' + _rig_module_validate_name(state['name']) + '_inputMatrix', skipSelect=True)
        state['input_matrix'] = _rig_module_output_remember(meta, state, matrix)
        cmds.connectAttr(matrix + '.matrixSum', input_node + '.offsetParentMatrix')
    matrix = _rig_module_node(state['input_matrix'])
    for index in (1, 2):
        plug = matrix + '.matrixIn[{}]'.format(index)
        for source in _rig_module_inputs(plug):
            cmds.disconnectAttr(source, plug)
        cmds.setAttr(plug, *_rig_module_matrix_identity(), type='matrix')
    cmds.setAttr(matrix + '.matrixIn[0]', *offset, type='matrix')
    cmds.connectAttr(parent_output + '.worldMatrix[0]', matrix + '.matrixIn[1]')
    parent = (cmds.listRelatives(input_node, parent=True, fullPath=True) or [None])[0]
    if parent:
        cmds.connectAttr(parent + '.worldInverseMatrix[0]', matrix + '.matrixIn[2]')
    for source in _rig_module_inputs(meta + '.parentOutput'):
        cmds.disconnectAttr(source, meta + '.parentOutput')
    cmds.connectAttr(parent_output + '.message', meta + '.parentOutput')
    state['attachment'] = {'method':'matrix_parent', 'module': parent_state['meta'], 'output': record['node'], 'role': record['role']}
    return parent_meta


def attach_rig_module(module, output):
    """Full transform with maintain offset; native matrix, no controller locks."""
    meta, state = _rig_module_read(module)
    _rig_module_require_undo()
    _rig_module_attachment_preflight(meta, state, output)
    snapshots = _rig_module_output_snapshots(state)
    root_before = _rig_module_matrix_value(_rig_module_node(state['root']) + '.worldMatrix[0]')
    undo_name = 'AttachRigModule_' + uuid.uuid4().hex
    try:
        with _tool_action(undo_name):
            parent_meta = _rig_module_connect_output(meta, state, output)
            _rig_module_save(meta, state)
            _rig_module_verify_pose(snapshots)
            root_after = _rig_module_matrix_value(_rig_module_node(state['root']) + '.worldMatrix[0]')
            if any(abs(a-b) > 1e-5 * max(1, abs(a), abs(b)) for a,b in zip(root_before,root_after)):
                raise RuntimeError('Module controller pose changed during attachment.')
            _rig_module_read(meta)
    except Exception as exc:
        if cmds.undoInfo(query=True, undoName=True) == undo_name:
            cmds.undo()
            raise RuntimeError('Module attachment was rolled back: ' + str(exc)) from exc
        raise
    return {'module': meta, 'parent_module': parent_meta, 'output': _rig_module_node(state['attachment']['output'])}


def detach_rig_module(module):
    """Remove only the recorded attachment, holding this frame in the input."""
    meta, state = _rig_module_read(module)
    if not state.get('attachment'):
        return {'module': meta, 'detached': False}
    if state['attachment'].get('method') == 'parent_constraint':
        return _rig_module_detach_native(module)
    _rig_module_require_undo()
    _rig_module_output_editable(meta)
    if cmds.getAttr(meta + '.' + _RIG_MODULE_STATE, lock=True):
        raise ValueError('Unlock module metadata before detaching it.')
    input_node = _rig_module_node(state['input'])
    matrix = _rig_module_node(state['input_matrix'])
    for node in (input_node, matrix):
        _rig_module_output_editable(node)
    _rig_module_attachment_matrix_preflight(meta, state)
    if cmds.getAttr(input_node + '.offsetParentMatrix', lock=True):
        raise ValueError('Unlock the module INPUT offsetParentMatrix before detaching it.')
    current = _rig_module_matrix_value(input_node + '.offsetParentMatrix')
    snapshots = _rig_module_output_snapshots(state)
    root_before = _rig_module_matrix_value(_rig_module_node(state['root']) + '.worldMatrix[0]')
    undo_name = 'DetachRigModule_' + uuid.uuid4().hex
    try:
        with _tool_action(undo_name):
            for index in (0, 1, 2):
                plug = matrix + '.matrixIn[{}]'.format(index)
                for source in _rig_module_inputs(plug):
                    cmds.disconnectAttr(source, plug)
                cmds.setAttr(plug, *(current if index == 0 else _rig_module_matrix_identity()), type='matrix')
            for source in _rig_module_inputs(meta + '.parentOutput'):
                cmds.disconnectAttr(source, meta + '.parentOutput')
            del state['attachment']
            _rig_module_save(meta, state)
            _rig_module_verify_pose(snapshots)
            root_after = _rig_module_matrix_value(_rig_module_node(state['root']) + '.worldMatrix[0]')
            if any(abs(a-b) > 1e-5 * max(1, abs(a), abs(b)) for a,b in zip(root_before,root_after)):
                raise RuntimeError('Module controller pose changed during detachment.')
            _rig_module_read(meta)
    except Exception as exc:
        if cmds.undoInfo(query=True, undoName=True) == undo_name:
            cmds.undo()
            raise RuntimeError('Module detachment was rolled back: ' + str(exc)) from exc
        raise
    return {'module': meta, 'detached': True}


def _rig_module_finish_outputs(meta, state, parent_output=None, parent_method='matrix_parent', parent_follow_scale=True):
    _rig_module_install_outputs(meta, state)
    _rig_module_install_registration(meta, state)
    if parent_output:
        if parent_method == 'parent_constraint':_rig_module_connect_native(meta,state,parent_output,parent_follow_scale)
        elif parent_method == 'matrix_parent':_rig_module_connect_output(meta,state,parent_output)
        else:raise ValueError('This module connection method is not implemented: '+str(parent_method))
    _rig_module_save(meta, state)


def _rig_module_mirror_parent_output(state, search, replace):
    attachment = state.get('attachment')
    if not attachment:
        return None
    _meta, parent, record = _rig_module_resolve_output(_rig_module_node(attachment['output']))
    source_joint = record['joint']
    owner_joint = source_joint or parent.get('root_joint') or parent.get('foot', {}).get('ankle')
    # A central Root placement/output remains shared on both sides.
    if not owner_joint:
        return _rig_module_node(record['node'])
    joint = _rig_module_node(owner_joint)
    if search not in joint.rsplit('|', 1)[-1]:
        return _rig_module_node(record['node'])
    counterpart = _guide_ik_uuid(_pd_mirror_object(joint, search, replace, require_change=True))
    candidates = []
    for module in list_rig_modules():
        _other_meta, other = _rig_module_read(module)
        if other['type'] != parent['type']:
            continue
        if not source_joint and (other.get('root_joint') or other.get('foot', {}).get('ankle')) != counterpart:
            continue
        for candidate in other.get('outputs', []):
            if ((source_joint and candidate['joint'] == counterpart)
                    or (not source_joint and candidate['role'] == record['role'])):
                if _guide_ik_resolve_uuid(candidate['node']):
                    candidates.append(candidate['node'])
    if len(candidates) != 1:
        raise ValueError('Mirror the parent module and publish its matching output first. Found {} counterpart outputs.'.format(len(candidates)))
    return _rig_module_node(candidates[0])


_RIG_MODULE_CONNECTION_METHODS = (
    {'id':'parent_constraint','label':'Parent constraint','available':True},
    {'id':'matrix_parent','label':'Matrix parent','available':True},
    {'id':'space_switch','label':'Space switch (planned)','available':False})


def rig_connection_methods():
    return [dict(row) for row in _RIG_MODULE_CONNECTION_METHODS]


def _rig_module_native_connection_validate(meta, state, kinds):
    nodes = state.get('connection_nodes', [])
    if (len(nodes) != len(set(nodes))
            or any(kinds.get(identity) not in ('parentConstraint','scaleConstraint') for identity in nodes)
            or (state.get('connection_space') and kinds.get(state['connection_space']) != 'transform')):
        raise ValueError('Invalid module connection ownership')
    attachment = state.get('attachment', {})
    if attachment.get('method', 'matrix_parent') != 'parent_constraint':
        return
    constraints = attachment['constraints']
    if (not constraints or len(constraints) not in (1,2)
            or not set(constraints).issubset(nodes)
            or kinds.get(constraints[0]) != 'parentConstraint'
            or (len(constraints) == 2 and kinds.get(constraints[1]) != 'scaleConstraint')
            or attachment['space'] != state.get('connection_space')
            or kinds.get(attachment['target']) != 'transform'):
        raise ValueError('Invalid native module connection records')
    space = _guide_ik_resolve_uuid(attachment['space'])
    input_node = _guide_ik_resolve_uuid(state['input'])
    target = _guide_ik_resolve_uuid(attachment['target'])
    if input_node and space:
        parent = (cmds.listRelatives(input_node, parent=True, fullPath=True) or [None])[0]
        if not parent or _guide_ik_uuid(parent) != attachment['space']:
            raise ValueError('The module connection space no longer parents its INPUT')
    if target:
        parent = (cmds.listRelatives(target, parent=True, fullPath=True) or [None])[0]
        if not parent or _guide_ik_uuid(parent) != attachment['output']:
            raise ValueError('The matched connection target has another parent')
    if space:
        for base, allowed in (('translate',constraints[:1]),('rotate',constraints[:1]),('scale',constraints[1:])):
            for axis in 'XYZ':
                actual = _rig_module_link(space + '.' + base + axis)
                live = [identity for identity in allowed if _guide_ik_resolve_uuid(identity)]
                if actual != live:raise ValueError('A module connection space channel has another driver')


def _rig_module_frame_path(state):
    result, node = [], _rig_module_node(state['root'])
    owned = {row['uuid'] for row in state['members']}
    while node:
        if _guide_ik_uuid(node) not in owned:
            return result, node
        result.append(node)
        node = (cmds.listRelatives(node, parent=True, fullPath=True) or [None])[0]
    return result, None


def _rig_module_scan_status(meta, state, member_owners):
    if not _guide_ik_resolve_uuid(state['root']):
        return 'broken', 'The module root is missing.', None
    if state.get('attachment'):
        attachment = state['attachment']
        expected = [state['input'],attachment['output'],attachment['module']]
        if attachment.get('method','matrix_parent') == 'parent_constraint':
            expected += attachment['constraints'] + [attachment['space'],attachment['target']]
        else:expected += [state['input_matrix']]
        if any(not _guide_ik_resolve_uuid(identity) for identity in expected):
            return 'broken', 'A recorded connection node is missing. Inspect or detach this connection.', attachment['module']
        return 'connected', attachment.get('method','matrix_parent'), attachment['module']
    frames, external = _rig_module_frame_path(state)
    if state.get('output_version') and state['input'] not in {_guide_ik_uuid(node) for node in frames}:
        return 'external', 'The root was moved outside its recorded INPUT. Restore the hierarchy before connecting.', None
    if external:
        owners = member_owners.get(_guide_ik_uuid(external), [])
        return ('parented' if owners else 'external',
                'Already parented under ' + external + '. No additional connection will be added.', owners[0] if len(owners)==1 else None)
    owned = {row['uuid'] for row in state['members']}
    expected_matrix = state.get('input_matrix')
    for node in frames:
        for attribute in ['offsetParentMatrix'] + [base+axis for base in ('translate','rotate','scale') for axis in 'XYZ']:
            for source in _rig_module_inputs(node+'.'+attribute):
                source_node = source.split('.',1)[0]
                identity = _guide_ik_uuid(source_node)
                if identity in owned:
                    # A detached 2.40 matrix is a stored local offset.
                    if attribute == 'offsetParentMatrix' and identity != expected_matrix:
                        return 'external', 'The module frame has an unrecorded matrix driver: '+node, None
                    continue
                if cmds.nodeType(source_node).startswith('animCurve'):
                    continue
                return 'external', 'A transform already has an external driver: '+node+'.'+attribute, None
    return 'missing', 'No module connection.', None


def _rig_module_scan_summary(meta, state):
    identity = _rig_module_inferred_start(state)
    return {'module':state['meta'],'node':meta,'name':state['name'],'type':state['type'],
            'start_joint':identity,'start_node':_guide_ik_resolve_uuid(identity) if identity else None,
            'registered':bool(state.get('registration_version')),'published':bool(state.get('output_version')),
            'outputs':_rig_module_output_rows(meta,state)}


def scan_rig_connections(root_module):
    """Read-only assembly plan from the Root's joint hierarchy, never names."""
    root_meta, root = _rig_module_read(root_module)
    if root['type'] != 'ROOT':raise ValueError('Choose a Root module as the scan scope.')
    start_id = _rig_module_inferred_start(root)
    if not start_id or not _guide_ik_resolve_uuid(start_id):
        raise ValueError('Get a start joint and Set Root start first. This links messages without driving the joint.')
    start = _guide_ik_joint(_rig_module_node(start_id))
    joints = [start] + (cmds.listRelatives(start,allDescendents=True,type='joint',fullPath=True) or [])
    joint_ids = {_guide_ik_uuid(node) for node in joints}
    states, summaries, all_summaries, owners, member_owners, issues = {}, {}, {}, {}, {}, []
    for module in list_rig_modules():
        try:
            meta, state = _rig_module_read(module)
            summary = _rig_module_scan_summary(meta,state)
        except (ValueError,RuntimeError) as exc:
            issues.append({'module':module,'message':str(exc)});continue
        identity = state['meta'];states[identity] = state;all_summaries[identity] = summary
        for row in state['members']:member_owners.setdefault(row['uuid'],[]).append(identity)
        for row in state['joints']:owners.setdefault(row['uuid'],[]).append(identity)
        if identity == root['meta'] or summary['start_joint'] in joint_ids:
            summaries[identity] = summary
    rows = []
    for identity, summary in summaries.items():
        if identity == root['meta']:continue
        state = states[identity]
        status, detail, current_parent = _rig_module_scan_status(summary['node'],state,member_owners)
        ancestor = summary['start_node']; suggested = None; ambiguous = False
        while ancestor:
            matches = [owner for owner in owners.get(_guide_ik_uuid(ancestor),[]) if owner != identity and owner in summaries]
            if len(matches)>1:
                ambiguous = True;break
            if matches:
                parent_id = matches[0]
                output = next((out for out in summaries[parent_id]['outputs'] if out['joint'] and _guide_ik_uuid(out['joint'])==_guide_ik_uuid(ancestor)),None)
                suggested = (parent_id,output['uuid'] if output and output['available'] else None)
                break
            if _guide_ik_uuid(ancestor)==start_id:break
            ancestor = (cmds.listRelatives(ancestor,parent=True,fullPath=True) or [None])[0]
        if not suggested and not ambiguous:
            outputs = summaries[root['meta']]['outputs']
            placement = next((out for out in outputs if out['role']=='placement' and out['available']),None)
            suggested = (root['meta'],placement['uuid'] if placement else None)
        if ambiguous and status=='missing':
            status,detail='ambiguous','More than one module drives the nearest ancestor joint. Choose/repair ownership explicitly.'
        parent_id, output_id = suggested or (None,None)
        prepared = summary['registered'] and summary['published']
        attachment = state.get('attachment', {})
        effective_parent = attachment.get('module',parent_id)
        parent_summary = all_summaries.get(effective_parent,{})
        parent_prepared = bool(parent_summary.get('registered') and parent_summary.get('published'))
        ready = status=='missing' and prepared and parent_prepared and bool(output_id)
        rows.append(dict(summary,status=status,detail=detail,current_parent=current_parent,
                         parent_module=attachment.get('module',parent_id),output=attachment.get('output',output_id),
                         method=attachment.get('method','matrix_parent') if attachment else 'parent_constraint',follow_scale=attachment.get('follow_scale',True),
                         ready=ready,needs_prepare=not prepared or not parent_prepared))
    rows.sort(key=lambda row:((row['start_node'] or '').count('|'),row['start_node'] or '',row['name']))
    return {'root_module':root['meta'],'root_start':start_id,'joint_count':len(joint_ids),
            'modules':list(all_summaries.values()),'rows':rows,'issues':issues}


def prepare_rig_modules(modules):
    """One undoable upgrade: output/input frames plus start message links."""
    records = [];seen=set()
    for module in modules:
        meta,state=_rig_module_read(module)
        if state['meta'] in seen:continue
        seen.add(state['meta'])
        if state.get('output_version') and state.get('registration_version'):continue
        _rig_module_output_preflight(meta,state);_rig_module_registration_plan(meta,state)
        records.append((meta,state,_rig_module_output_snapshots(state)))
    if not records:return {'count':0}
    _rig_module_require_undo();undo_name='PrepareRigModules_'+uuid.uuid4().hex
    selection=cmds.ls(selection=True,long=True) or []
    try:
        try:
            with _tool_action(undo_name):
                for meta,state,snapshots in records:
                    _rig_module_install_outputs(meta,state);_rig_module_install_registration(meta,state)
                    _rig_module_save(meta,state);_rig_module_verify_pose(snapshots);_rig_module_read(meta)
        except Exception as exc:
            if cmds.undoInfo(query=True,undoName=True)==undo_name:
                cmds.undo();raise RuntimeError('Module preparation was rolled back: '+str(exc)) from exc
            raise
    finally:_restore_locator_view_selection(selection)
    return {'count':len(records)}


def _rig_module_connection_preflight(meta, state, output, method):
    available = {row['id'] for row in _RIG_MODULE_CONNECTION_METHODS if row['available']}
    if method not in available:raise ValueError('This connection method is not implemented: '+str(method))
    if state.get('attachment'):raise ValueError('This module already has a connection. Detach it before changing methods or parent.')
    if not state.get('registration_version'):raise ValueError('Prepare saved modules to register the child start joint first.')
    parent_meta, parent, record = _rig_module_attachment_preflight(meta,state,output)
    if not parent.get('registration_version'):raise ValueError('Prepare the parent module start registration first.')
    frames, external = _rig_module_frame_path(state)
    if state['input'] not in {_guide_ik_uuid(node) for node in frames}:
        raise ValueError('The root is outside its INPUT. Restore its recorded hierarchy first.')
    if external:raise ValueError('The module already has an external DAG parent. Review that parent before automatic connection.')
    status,detail,_parent=_rig_module_scan_status(meta,state,{})
    if status!='missing':raise ValueError(detail)
    if state.get('connection_space'):
        space = _rig_module_node(state['connection_space']);_rig_module_output_editable(space)
        for base in ('translate','rotate','scale'):
            for axis in 'XYZ':
                plug=space+'.'+base+axis
                if cmds.getAttr(plug,lock=True) or _rig_module_inputs(plug):raise ValueError('Connection space channel is occupied: '+plug)
    if method=='parent_constraint':_constraint_root(False)
    return parent_meta,parent,record


def _rig_module_connect_native(meta, state, output, follow_scale=True):
    parent_meta,parent,record=_rig_module_connection_preflight(meta,state,output,'parent_constraint')
    remember=lambda node:_rig_module_output_remember(meta,state,node)
    input_node=_rig_module_node(state['input'])
    prefix=':'+_rig_module_validate_name(state['name'])+'_'+state['type']+'_'
    if not state.get('connection_space'):
        previous=(cmds.listRelatives(input_node,parent=True,fullPath=True) or [None])[0]
        space=cmds.createNode('transform',name=prefix+'CONNECTION_SPACE',skipSelect=True)
        space_id=remember(space)
        if previous:cmds.parent(space,previous,relative=True)
        cmds.parent(input_node,_rig_module_node(space_id),relative=True)
        state['connection_space']=space_id
    space=_rig_module_node(state['connection_space'])
    # A matched child target carries the maintained offset through DAG matrices.
    # Native constraints have zero target offset, including under global scale.
    target=cmds.createNode('transform',name=prefix+'CONNECTION_TARGET',skipSelect=True)
    target_id=remember(target)
    cmds.parent(target,_rig_module_node(record['node']),relative=True)
    target=_rig_module_node(target_id)
    offset=_rig_module_matrix_product(_rig_module_matrix_value(space+'.worldMatrix[0]'),
        _rig_module_matrix_inverse(_rig_module_matrix_value(_rig_module_node(record['node'])+'.worldMatrix[0]')))
    cmds.setAttr(target+'.offsetParentMatrix',*offset,type='matrix')
    scope=_constraint_context(state['name']+'_'+state['type'],remember)
    if state.get('constraint_group') and _guide_ik_resolve_uuid(state['constraint_group']):scope['node']=state['constraint_group']
    constraints=[]
    for command,label in [('parentConstraint','moduleParent')]+([('scaleConstraint','moduleScale')] if follow_scale else []):
        constraint=_constraint_command(command,target,space,maintainOffset=True,name=prefix+label+'#',_scope=scope)[0]
        constraints.append(remember(constraint))
    state['constraint_group']=scope['node']
    state.setdefault('connection_nodes',[]).extend(constraints)
    cmds.connectAttr(_rig_module_node(record['node'])+'.message',meta+'.parentOutput')
    state['attachment']={'method':'parent_constraint','module':parent['meta'],'output':record['node'],
                         'role':record['role'],'space':state['connection_space'],'target':target_id,
                         'constraints':constraints,'follow_scale':bool(follow_scale)}
    return parent_meta


def _rig_module_detach_native(module):
    meta,state=_rig_module_read(module);attachment=state['attachment']
    _rig_module_require_undo();_rig_module_output_editable(meta)
    if cmds.getAttr(meta+'.'+_RIG_MODULE_STATE,lock=True):raise ValueError('Unlock module metadata before detaching.')
    space=_rig_module_node(attachment['space']);_rig_module_output_editable(space)
    owned={row['uuid'] for row in state['members']}
    for identity in attachment['constraints']+[attachment['target']]:
        node=_guide_ik_resolve_uuid(identity)
        if not node:continue
        _rig_module_output_editable(node)
        if cmds.objectType(node,isAType='dagNode'):
            if any(_guide_ik_uuid(child) not in owned for child in cmds.listRelatives(node,allDescendents=True,fullPath=True) or []):
                raise ValueError('Move foreign objects out of the connection target before detaching.')
        if any(_guide_ik_uuid(plug.split('.',1)[0]) not in owned for plug in cmds.listConnections(node,source=False,destination=True,plugs=True) or []):
            raise ValueError('Another system uses a module connection node; disconnect that consumer first.')
    values={base+axis:cmds.getAttr(space+'.'+base+axis) for base in ('translate','rotate','scale') for axis in 'XYZ'}
    for attr in values:
        if cmds.getAttr(space+'.'+attr,lock=True):raise ValueError('Unlock the connection space before detaching.')
    snapshots=_rig_module_output_snapshots(state)
    root_before=_rig_module_matrix_value(_rig_module_node(state['root'])+'.worldMatrix[0]')
    undo_name='DetachNativeModule_'+uuid.uuid4().hex
    selection=cmds.ls(selection=True,long=True) or []
    try:
        with _tool_action(undo_name):
            _constraint_delete_owned(attachment['constraints']+[attachment['target']])
            for attr,value in values.items():cmds.setAttr(space+'.'+attr,value)
            for source in _rig_module_inputs(meta+'.parentOutput'):cmds.disconnectAttr(source,meta+'.parentOutput')
            del state['attachment'];_rig_module_save(meta,state)
            _rig_module_verify_pose(snapshots)
            root_after=_rig_module_matrix_value(_rig_module_node(state['root'])+'.worldMatrix[0]')
            if any(abs(a-b)>1e-5*max(1,abs(a),abs(b)) for a,b in zip(root_before,root_after)):
                raise RuntimeError('Controller pose changed during detachment.')
            _rig_module_read(meta)
    except Exception as exc:
        if cmds.undoInfo(query=True,undoName=True)==undo_name:
            cmds.undo();raise RuntimeError('Module detachment was rolled back: '+str(exc)) from exc
        raise
    finally:_restore_locator_view_selection(selection)
    return {'module':meta,'detached':True}


def connect_rig_modules(plans):
    """Preflight a reviewed plan, reject planned cycles, then apply in one Undo."""
    records=[];planned={};seen=set()
    for row in plans:
        meta,state=_rig_module_read(row['module'])
        if state['meta'] in seen:raise ValueError('A child module appears twice in the connection plan.')
        seen.add(state['meta']);method=row.get('method','parent_constraint')
        parent_meta,parent,_record=_rig_module_connection_preflight(meta,state,row['output'],method)
        planned[state['meta']]=parent['meta']
        records.append((meta,state,_guide_ik_uuid(row['output']),method,bool(row.get('follow_scale',True))))
    if not records:return {'count':0,'modules':[]}
    # Include existing DAG/driver dependencies on any other proposed child.
    # This catches mixed planned connections and manually parented modules.
    dependencies={identity:set() for identity in planned}
    dependency_cache={}
    for _meta,state,output,_method,_scale in records:
        key=_guide_ik_uuid(output)
        if key not in dependency_cache:
            dependency_cache[key]={other['meta'] for _,other,_,_,_ in records
                if _rig_module_output_depends_on(_rig_module_node(output),{row['uuid'] for row in other['members']})}
        dependencies[state['meta']].update(dependency_cache[key])
        if planned[state['meta']] in planned:dependencies[state['meta']].add(planned[state['meta']])
    remaining={node:len(parents) for node,parents in dependencies.items()}
    children={node:[] for node in dependencies}
    for child,parents in dependencies.items():
        for parent in parents:children[parent].append(child)
    pending=[node for node,count in remaining.items() if count==0];done=set()
    while pending:
        node=pending.pop();done.add(node)
        for child in children[node]:
            remaining[child]-=1
            if remaining[child]==0:pending.append(child)
    if len(done)!=len(dependencies):raise ValueError('The proposed connections contain a dependency cycle.')
    # Also follow existing recorded attachments outside this plan.
    for start in planned:
        visited=set();node=start
        while node:
            if node in visited:raise ValueError('The proposed connections contain a dependency cycle.')
            visited.add(node)
            if node in planned:node=planned[node]
            else:
                existing=_rig_module_read(_rig_module_node(node))[1]
                node=existing.get('attachment',{}).get('module')
    _rig_module_require_undo();undo_name='ConnectRigModules_'+uuid.uuid4().hex
    selection=cmds.ls(selection=True,long=True) or []
    snapshots=[(state,_rig_module_output_snapshots(state),_rig_module_matrix_value(_rig_module_node(state['root'])+'.worldMatrix[0]')) for _,state,_,_,_ in records]
    try:
        try:
            with _tool_action(undo_name):
                for meta,state,output,method,follow_scale in records:
                    if method=='parent_constraint':_rig_module_connect_native(meta,state,_rig_module_node(output),follow_scale)
                    else:_rig_module_connect_output(meta,state,_rig_module_node(output))
                    _rig_module_save(meta,state);_rig_module_read(meta)
                for state,pose,before in snapshots:
                    _rig_module_verify_pose(pose)
                    after=_rig_module_matrix_value(_rig_module_node(state['root'])+'.worldMatrix[0]')
                    if any(abs(a-b)>1e-5*max(1,abs(a),abs(b)) for a,b in zip(before,after)):
                        raise RuntimeError('Module controller pose changed during connection.')
        except Exception as exc:
            if cmds.undoInfo(query=True,undoName=True)==undo_name:
                cmds.undo();raise RuntimeError('Connection plan was rolled back: '+str(exc)) from exc
            raise
    finally:_restore_locator_view_selection(selection)
    return {'count':len(records),'modules':[meta for meta,_,_,_,_ in records]}


def connect_rig_module(module, output, method='parent_constraint', follow_scale=True):
    return connect_rig_modules([{'module':module,'output':output,'method':method,'follow_scale':follow_scale}])


def organize_rig_constraints(module):
    """Move only an existing module's native solvers, preserving links and pose."""
    meta,state=_rig_module_read(module)
    nodes=[_rig_module_node(row['uuid']) for row in state['members']
           if row['type'].endswith('Constraint') and _guide_ik_resolve_uuid(row['uuid'])]
    if not nodes:return {'module':meta,'count':0,'group':None}
    _constraint_root(False);_rig_module_require_undo()
    owned={row['uuid'] for row in state['members']}
    previous=state.get('constraint_group')
    previous_node=_guide_ik_resolve_uuid(previous) if previous else None
    for node in nodes+([previous_node] if previous_node else []):
        if cmds.referenceQuery(node,isNodeReferenced=True) or (cmds.lockNode(node,query=True,lock=True) or [False])[0]:
            raise ValueError('Module constraint/group is locked or referenced: '+node)
    if previous_node:
        for child in cmds.listRelatives(previous_node,allDescendents=True,fullPath=True) or []:
            if _guide_ik_uuid(child) not in owned:raise ValueError('Move foreign objects out of the constraint subgroup before organizing it.')
    snapshots=[]
    for row in state['joints']:
        joint=_guide_ik_resolve_uuid(row['uuid'])
        if joint:snapshots.append({'uuid':row['uuid'],'world':cmds.xform(joint,query=True,worldSpace=True,matrix=True),
            **{attr:cmds.getAttr(joint+'.'+attr) for attr in ('jointOrient','rotateAxis','segmentScaleCompensate')}})
    def remember(node):
        identity=_guide_ik_uuid(node)
        if identity not in owned:
            index=len(state['members']);owned.add(identity)
            state['members'].append({'uuid':identity,'type':cmds.nodeType(node)})
            cmds.connectAttr(node+'.message',meta+'.members[{}]'.format(index))
        return identity
    scope=_constraint_context(state['name']+'_'+state['type'],remember);scope['node']=previous if previous_node else None
    undo_name='OrganizeModuleConstraints_'+uuid.uuid4().hex
    try:
        with _tool_action(undo_name):
            if previous_node:
                parent=_constraint_root(True)
                parents=cmds.listRelatives(previous_node,parent=True,fullPath=True) or []
                if not parents or _guide_ik_uuid(parents[0])!=_guide_ik_uuid(parent):
                    cmds.parent(previous_node,parent,relative=True)
            _constraint_organize(nodes,scope)
            state['constraint_group']=scope['node']
            cmds.setAttr(meta+'.'+_RIG_MODULE_STATE,json.dumps(state),type='string')
            _rig_module_verify_pose(snapshots);_rig_module_read(meta)
    except Exception as exc:
        if cmds.undoInfo(query=True,undoName=True)==undo_name:
            cmds.undo();raise RuntimeError('Constraint organization was rolled back: '+str(exc)) from exc
        raise
    return {'module':meta,'count':len(nodes),'group':_rig_module_node(scope['node'])}


def list_rig_modules():
    """Read-only scene discovery; nothing is evaluated by Python per frame."""
    modules = []
    for meta in cmds.ls(type="network") or []:
        if cmds.attributeQuery(_RIG_MODULE_TAG, node=meta, exists=True):
            # Keep damaged modules visible so a metadata problem is reported.
            modules.append(meta)
    return sorted(modules)


def _rig_module_check_matrix(node):
    matrix = list(cmds.xform(node, query=True, worldSpace=True, matrix=True))
    if len(matrix) != 16 or not all(math.isfinite(float(value)) for value in matrix):
        raise ValueError("Invalid world matrix: {}".format(node))
    axes = [matrix[index:index + 3] for index in (0, 4, 8)]
    lengths = [math.sqrt(sum(value * value for value in axis)) for axis in axes]
    if min(lengths) < 1e-8 or max(lengths) - min(lengths) > 1e-5 * max(lengths):
        raise ValueError("FK modules require positive uniform world scale: {}".format(node))
    for first, second in ((0, 1), (0, 2), (1, 2)):
        if abs(sum(a * b for a, b in zip(axes[first], axes[second]))) > 1e-5 * lengths[first] * lengths[second]:
            raise ValueError("FK modules do not support sheared joint transforms: {}".format(node))
    a, b, c = axes
    determinant = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
    if determinant <= 0:
        raise ValueError("FK modules do not support reflected or negative scale: {}".format(node))
    return matrix


def plan_fk_module(joints, include_children=False, control_size=1.0, name="FK"):
    """Resolve a connected joint tree, preflight all writes, then build nothing."""
    if isinstance(joints, str):
        joints = [joints]
    if not joints:
        raise ValueError("Get a root joint or a connected selection of joints first.")
    size = float(control_size)
    if not math.isfinite(size) or size <= 0:
        raise ValueError("Control size must be greater than zero.")
    label = (name or "").strip()
    if not label:
        raise ValueError("Give the module a name.")
    label = "".join(char if char.isascii() and (char.isalnum() or char == "_") else "_" for char in label)
    if label[0].isdigit():
        label = "module_" + label
    nodes = set()
    for value in joints:
        joint = _guide_ik_joint(value)
        nodes.add(joint)
        if include_children:
            nodes.update(cmds.listRelatives(joint, allDescendents=True, type="joint", fullPath=True) or [])
    ordered = sorted(nodes, key=lambda node: (node.count("|"), node))
    parents = {}
    roots = []
    snapshots = []
    checked_ancestors = set()
    for joint in ordered:
        _guide_ik_joint(joint)
        if cmds.referenceQuery(joint, isNodeReferenced=True) or (cmds.lockNode(joint, query=True, lock=True) or [False])[0]:
            raise ValueError("Joint is locked or referenced: {}".format(joint))
        parent = (cmds.listRelatives(joint, parent=True, fullPath=True) or [None])[0]
        if parent in nodes:
            parents[joint] = parent
        else:
            roots.append(joint)
            parents[joint] = None
        if cmds.getAttr(joint + ".inIKSolveFlag"):
            raise ValueError("Joint is currently driven by an IK solver: {}".format(joint))
        ancestor = joint
        while ancestor and ancestor not in checked_ancestors:
            checked_ancestors.add(ancestor)
            if any(float(cmds.getAttr(ancestor+".scale"+axis)) <= 0 for axis in "XYZ"):
                raise ValueError("FK modules require positive scales on joints and their parents: {}".format(ancestor))
            _rig_module_check_matrix(ancestor)
            ancestor = (cmds.listRelatives(ancestor, parent=True, fullPath=True) or [None])[0]
        for prefix in ("translate", "rotate", "scale"):
            for attribute in (prefix,) + tuple(prefix + axis for axis in "XYZ"):
                plug = joint + "." + attribute
                if cmds.getAttr(plug, lock=True) or _rig_module_inputs(plug) or not cmds.getAttr(plug, settable=True):
                    raise ValueError("Joint channel is locked, animated or already driven: {}".format(plug))
        snapshots.append({"uuid": _guide_ik_uuid(joint), "world": _rig_module_check_matrix(joint),
                          "jointOrient": cmds.getAttr(joint + ".jointOrient"),
                          "rotateAxis": cmds.getAttr(joint + ".rotateAxis"),
                          "segmentScaleCompensate": cmds.getAttr(joint + ".segmentScaleCompensate")})
    if len(roots) != 1:
        raise ValueError("Choose one connected joint tree, including every joint between the selected joints. Branches are supported.")
    for module in list_rig_modules():
        _meta, state = _rig_module_read(module)
        if set(row["uuid"] for row in snapshots).intersection(row["uuid"] for row in state["joints"]):
            raise ValueError("Some joints already belong to module '{}'. Remove that module first.".format(state["name"]))
    return {"joints": ordered, "parents": parents, "root_joint": roots[0], "size": size, "name": label, "snapshots": snapshots}


def _rig_module_verify_pose(records):
    for record in records:
        joint = _rig_module_node(record["uuid"])
        actual = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
        if any(abs(a-b) > 1e-5 * max(1, abs(a), abs(b)) for a, b in zip(actual, record["world"])):
            raise RuntimeError("Joint pose changed unexpectedly: {}".format(joint))
        for attribute in ("jointOrient", "rotateAxis", "segmentScaleCompensate"):
            # JSON turns tuple values into lists; compare canonical encodings.
            if json.dumps(cmds.getAttr(joint + "." + attribute)) != json.dumps(record[attribute]):
                raise RuntimeError("Joint orientation/scale definition changed: {}".format(joint))


def _rig_module_require_undo():
    if _TOOL_UNDO_DEPTH or not cmds.undoInfo(query=True, state=True):
        raise ValueError("Enable Maya Undo and run outside another tool action so failures can be rolled back.")


def _rig_module_joint_label(joint):
    label = joint.rsplit("|",1)[-1]
    for suffix in ("_JNT", "_jnt", "_joint", "_Joint"):
        if label.endswith(suffix): return label[:-len(suffix)]
    return label


def _rig_module_name_rows(module_type, joints):
    """Role keys are stable source UUIDs; displayed names are readable joint names."""
    if module_type=='ROOT':return [('root','MAIN','Main_ctrl'),('placement','ROOT','Root_ctrl')]
    if module_type=='FOOT':
        return [('root','FOOT ROOT',_rig_module_joint_label(joints[0])+'_Foot_ROOT'),
                ('ankle','ANKLE / IK FOOT',_rig_module_joint_label(joints[0])+'_Foot_CTRL'),
                ('ball','BALL',_rig_module_joint_label(joints[1])+'_Foot_CTRL')]
    first = _rig_module_joint_label(joints[0])
    kind = "FK" if module_type == "FK" else "IKFK" if module_type=="IKFK" else "IK"
    rows = [("root", "ROOT", first+"_"+kind+"_ROOT")]
    if module_type == "FK":
        rows += [(_guide_ik_uuid(joint), joint.rsplit("|",1)[-1], _rig_module_joint_label(joint)+"_FK_CTRL") for joint in joints]
    else:
        rows += [("end", "END", _rig_module_joint_label(joints[2])+"_IK_END_CTRL"),
                 ("pole", "POLE", _rig_module_joint_label(joints[1])+"_IK_POLE_CTRL")]
        if module_type=="IKFK":
            rows += [("base","IK BASE",first+"_IK_BASE_CTRL")]
            rows += [(_guide_ik_uuid(joint),joint.rsplit("|",1)[-1]+" FK",_rig_module_joint_label(joint)+"_FK_CTRL") for joint in joints]
    return rows


def _rig_module_validate_name(value):
    name = str(value).strip().lstrip(":")
    parts = name.split(":")
    if not name or any(not part or not (part[0].isascii() and (part[0].isalpha() or part[0] == "_"))
                       or any(not (c.isascii() and (c.isalnum() or c == "_")) for c in part) for part in parts):
        raise ValueError("Use a valid Maya controller name (letters, digits, underscores, optional namespace): {}".format(value))
    if len(parts)>1 and not cmds.namespace(exists=":"+":".join(parts[:-1])):
        raise ValueError("Controller namespace does not exist: {}".format(":".join(parts[:-1])))
    return name


def _rig_module_names(module_type, joints, overrides=None, renaming=None):
    rows = _rig_module_name_rows(module_type,joints)
    overrides = dict(overrides or {})
    if set(overrides) - {row[0] for row in rows}:
        raise ValueError("Controller names contain roles/joints that are not in this module. Refresh the name fields.")
    result = {}
    for key,_label,default in rows:
        value = str(overrides.get(key,"") or "").strip()
        name = _rig_module_validate_name(value or default)
        # Auto names can receive Maya's numeric collision suffix; explicit names
        # must not silently take another object's name.
        if value:
            collisions = cmds.ls(":"+name,long=True) or cmds.ls(name,long=True) or []
            if any(_guide_ik_uuid(node) != (renaming or {}).get(key) for node in collisions):
                raise ValueError("Custom controller name is already used: {}".format(name))
        if name in result.values():
            if value: raise ValueError("Give each controller a different name.")
            index,base = 2,name
            while name in result.values():
                name = base+str(index)
                index += 1
        result[key] = name
    return result


def _rig_module_controller_roles(state):
    if state["type"] in ("ROOT","FOOT"):return dict(state["roles"])
    roles = {"root":state["root"]}
    if state["type"] == "FK": roles.update({row["joint"]:row["control"] for row in state["controls"]})
    else: roles.update({"end":state["ik"]["end"], "pole":state["ik"]["pole"]})
    if state["type"]=="IKFK":
        roles["base"]=state["ik"]["base"]
        roles.update({row["uuid"]:control for row,control in zip(state["joints"],state["ikfk"]["fk_controls"])})
    return roles


def _rig_module_units():
    return {"angle":cmds.currentUnit(query=True,angle=True), "linear":cmds.currentUnit(query=True,linear=True)}


def _rig_module_unit_value(attribute, value, source, destination):
    if attribute.startswith("rotate"):
        rad = ("rad","radian")
        degrees = math.degrees(value) if source["angle"] in rad else value
        return math.radians(degrees) if destination["angle"] in rad else degrees
    if attribute.startswith("translate"):
        cm = {"mm":.1,"millimeter":.1,"cm":1,"centimeter":1,"m":100,"meter":100,
              "km":100000,"kilometer":100000,"in":2.54,"inch":2.54,"ft":30.48,"foot":30.48,
              "yd":91.44,"yard":91.44,"mi":160934.4,"mile":160934.4}
        return value*cm[source["linear"]]/cm[destination["linear"]]
    return value


def _rig_module_capture_defaults(state):
    defaults = []
    for role,identity in _rig_module_controller_roles(state).items():
        node = _rig_module_node(identity)
        channels = [base+axis for base in ("translate","rotate","scale") for axis in "XYZ"
                    if role != "root" or base != "scale"]
        if role == "root": channels.append("globalScale")
        if role == "root" and state["type"]=="IKFK": channels.append("ikFkBlend")
        if role == "end" and state["ik"].get("length_system"): channels.extend(_RIG_MODULE_IK_LENGTH_ATTRS)
        channels.extend(_rig_module_extra_channels(state,role))
        values = {attribute:float(cmds.getAttr(node+"."+attribute)) for attribute in channels}
        if not all(math.isfinite(value) for value in values.values()): raise ValueError("Controller has invalid values: {}".format(node))
        defaults.append({"uuid":identity,"role":role,"values":values})
    return defaults


def _rig_module_save(meta,state):
    if cmds.referenceQuery(meta,isNodeReferenced=True) or (cmds.lockNode(meta,query=True,lock=True) or [False])[0] or cmds.getAttr(meta+"."+_RIG_MODULE_STATE,lock=True):
        raise ValueError("Rig metadata is locked or referenced: {}".format(meta))
    cmds.setAttr(meta+"."+_RIG_MODULE_STATE,json.dumps(state),type="string")


def rename_rig_controllers(module, controller_names=None):
    """Rename ROOT and animator controls, including older UUID-based names."""
    meta,state = _rig_module_read(module)
    roles = _rig_module_controller_roles(state)
    joints = _rig_module_extra_names(state)
    names = _rig_module_names(state["type"],joints,controller_names,roles)
    _rig_module_require_undo()
    for identity in roles.values():
        node = _rig_module_node(identity)
        if cmds.referenceQuery(node,isNodeReferenced=True) or (cmds.lockNode(node,query=True,lock=True) or [False])[0]:
            raise ValueError("Controller is locked or referenced: {}".format(node))
    undo_name = "RenameRigControllers_"+uuid.uuid4().hex
    try:
        with _tool_action(undo_name):
            for role,identity in roles.items(): cmds.rename(_rig_module_node(identity),":"+names[role])
            state["controller_names"] = {role:_rig_module_node(identity).rsplit("|",1)[-1] for role,identity in roles.items()}
            _rig_module_save(meta,state)
    except Exception as exc:
        if cmds.undoInfo(query=True,undoName=True)==undo_name:
            cmds.undo()
            raise RuntimeError("Controller naming was rolled back: {}".format(exc)) from exc
        raise
    return state["controller_names"]


def store_rig_default(module):
    """Explicitly store the current local ROOT/animator values as the default."""
    meta,state = _rig_module_read(module)
    defaults,units = _rig_module_capture_defaults(state),_rig_module_units()
    _rig_module_require_undo()
    with _tool_action("StoreRigDefault"):
        state["defaults"],state["default_units"] = defaults,units
        _rig_module_save(meta,state)
    return len(defaults)


def goto_rig_default(module, include_root=False, keyframe=False):
    """Restore saved local controller values; never write source joints directly."""
    _meta,state = _rig_module_read(module)
    roles = _rig_module_controller_roles(state)
    defaults = state.get("defaults")
    units = _rig_module_units()
    if defaults is None:
        if include_root: raise ValueError("This older module has no saved ROOT default. Store current as default first, or leave Include root off.")
        defaults = [{"uuid":identity,"role":role,"values":{base+axis:(1.0 if base=="scale" else 0.0)
                     for base in ("translate","rotate","scale") for axis in "XYZ"}}
                    for role,identity in roles.items() if role != "root"]
        for record in defaults:
            if record["role"]=="end" and state["ik"].get("length_system"):
                record["values"].update({name:data[0] for name,data in _RIG_MODULE_IK_LENGTH_ATTRS.items()})
    writes = []
    allowed = {base+axis for base in ("translate","rotate","scale") for axis in "XYZ"}|{"globalScale","ikFkBlend"}|set(_RIG_MODULE_IK_LENGTH_ATTRS)|set(_RIG_MODULE_FOOT_ATTRS)
    seen = set()
    for record in defaults:
        role,identity = record["role"],record["uuid"]
        if roles.get(role) != identity or identity in seen: raise ValueError("Default pose ownership is incomplete or changed.")
        seen.add(identity)
        if role == "root" and not include_root and state["type"]!="IKFK": continue
        node = _rig_module_node(identity)
        if cmds.referenceQuery(node,isNodeReferenced=True) or (cmds.lockNode(node,query=True,lock=True) or [False])[0]:
            raise ValueError("Controller is locked or referenced: {}".format(node))
        required_channels = {base+axis for base in ("translate","rotate","scale") for axis in "XYZ"
                             if role != "root" or base != "scale"}
        if role == "root": required_channels.add("globalScale")
        if role == "root" and state["type"]=="IKFK": required_channels.add("ikFkBlend")
        if role == "end" and state["ik"].get("length_system"): required_channels.update(_RIG_MODULE_IK_LENGTH_ATTRS)
        required_channels.update(_rig_module_extra_channels(state,role))
        if set(record["values"]) != required_channels: raise ValueError("The saved default is missing controller channels.")
        for attribute,value in record["values"].items():
            if role=="root" and not include_root and attribute!="ikFkBlend":continue
            if attribute not in allowed or (role == "root" and attribute.startswith("scale")) or not math.isfinite(float(value)):
                raise ValueError("Invalid default controller values.")
            plug = node+"."+attribute
            if cmds.getAttr(plug,lock=True) or cmds.getAttr(node+"."+attribute.rstrip("XYZ"),lock=True):
                raise ValueError("Controller channel is locked: {}".format(plug))
            inputs = _rig_module_inputs(plug)
            if inputs:
                drivers = [item.split(".",1)[0] for item in inputs]
                timed = all(cmds.nodeType(driver) in ("animCurveTA","animCurveTL","animCurveTU") for driver in drivers)
                if not keyframe or not timed:
                    raise ValueError("Controller channel is driven/animated: {}. Enable Key default for time animation; other drivers are kept.".format(plug))
            value = _rig_module_unit_value(attribute,float(value),state.get("default_units",units),units)
            writes.append((node,attribute,value))
    required = {identity for role,identity in roles.items() if include_root or role != "root" or state["type"]=="IKFK"}
    if not required.issubset(seen): raise ValueError("The saved default is missing a controller. Store current as default or rebuild the module.")
    _rig_module_require_undo()
    undo_name = "GoToRigDefault_"+uuid.uuid4().hex
    try:
        with _tool_action(undo_name):
            for node,attribute,value in writes:
                if keyframe: cmds.setKeyframe(node,attribute=attribute,value=value)
                else: cmds.setAttr(node+"."+attribute,value)
    except Exception as exc:
        if cmds.undoInfo(query=True,undoName=True)==undo_name:
            cmds.undo()
            raise RuntimeError("Go to Default was rolled back: {}".format(exc)) from exc
        raise
    return len(writes)


def plan_rig_mirror(module, search="_L", replace="_R"):
    """Build a counterpart setup on existing matching joints, without copying animation."""
    search,replace = _pd_mirror_tokens(search,replace)
    _meta,state = _rig_module_read(module)
    parent_output = _rig_module_mirror_parent_output(state, search, replace)
    if state['type'] in ('ROOT','FOOT'):
        plan = _rig_module_extra_mirror(state,search,replace)
        if parent_output: plan.update(parent_output=parent_output,parent_method=state['attachment'].get('method','matrix_parent'),parent_follow_scale=state['attachment'].get('follow_scale',True))
        return plan
    source = [_rig_module_node(row["uuid"]) for row in state["joints"]]
    target = [_guide_ik_joint(_pd_mirror_object(node,search,replace,require_change=True)) for node in source]
    source_ids = {_guide_ik_uuid(node) for node in source}
    if source_ids.intersection(_guide_ik_uuid(node) for node in target):
        raise ValueError("Mirror joints must be different from the source joints.")
    mapping = {_guide_ik_uuid(a):_guide_ik_uuid(b) for a,b in zip(source,target)}
    # Validate the same parent relationships, including branching FK trees.
    for a,b in zip(source,target):
        parent_a = (cmds.listRelatives(a,parent=True,fullPath=True) or [None])[0]
        if parent_a and _guide_ik_uuid(parent_a) in mapping:
            parent_b = (cmds.listRelatives(b,parent=True,fullPath=True) or [None])[0]
            if not parent_b or _guide_ik_uuid(parent_b) != mapping[_guide_ik_uuid(parent_a)]:
                raise ValueError("Mirror joint hierarchy differs at {}.".format(b))
    name = _pd_mirror_name(state["name"],search,replace)
    if name == state["name"]: name = _rig_module_joint_label(target[0])+"_"+("FK" if state["type"]=="FK" else "IKFK" if state["type"]=="IKFK" else "IK")
    size = state["control_size"]
    if state["type"] == "FK": plan_fk_module(target,False,size,name)
    else: plan_ik_module(*target,name=name,control_size=size,pole_distance=state.get("pole_distance",1.0))
    overrides = {}
    for role,identity in _rig_module_controller_roles(state).items():
        current_name = _rig_module_node(identity).rsplit("|",1)[-1]
        mirrored = _pd_mirror_name(current_name,search,replace)
        if current_name != mirrored: overrides[mapping.get(role,role)] = mirrored
    _rig_module_names(state["type"],target,overrides)
    return {"type":state["type"],"name":name,"joints":target,"source_joints":source,"control_size":size,
            "pole_distance":state.get("pole_distance",1.0),"controller_names":overrides,"parent_output":parent_output,"parent_method":state.get("attachment",{}).get("method","matrix_parent"),"parent_follow_scale":state.get("attachment",{}).get("follow_scale",True)}


def mirror_rig_module(module, search="_L", replace="_R"):
    plan = plan_rig_mirror(module,search,replace)
    if plan['type']=='ROOT':
        return build_root_module(**{k:plan[k] for k in ('placement','root_joint','name','control_size','controller_names','parent_output','parent_method','parent_follow_scale') if k in plan})
    if plan['type']=='FOOT':
        keys=('toe_tip','left_pivot','right_pivot','heel_pivot','mode','name','control_size','parent_control','drive_ankle','up_axis','bank_sign','controller_names','parent_output','parent_method','parent_follow_scale')
        return build_foot_module(*plan['joints'],**{k:plan[k] for k in keys if k in plan})
    if plan["type"] == "FK":
        return build_fk_module(plan["joints"],name=plan["name"],control_size=plan["control_size"],controller_names=plan["controller_names"],parent_output=plan.get('parent_output'),parent_method=plan.get('parent_method','matrix_parent'),parent_follow_scale=plan.get('parent_follow_scale',True))
    if plan["type"]=="IKFK":
        return build_ikfk_module(*plan["joints"],name=plan["name"],control_size=plan["control_size"],pole_distance=plan["pole_distance"],controller_names=plan["controller_names"],parent_output=plan.get('parent_output'),parent_method=plan.get('parent_method','matrix_parent'),parent_follow_scale=plan.get('parent_follow_scale',True))
    return build_ik_module(*plan["joints"],name=plan["name"],control_size=plan["control_size"],pole_distance=plan["pole_distance"],controller_names=plan["controller_names"],parent_output=plan.get('parent_output'),parent_method=plan.get('parent_method','matrix_parent'),parent_follow_scale=plan.get('parent_follow_scale',True))


class _RigControllerNames(QtWidgets.QWidget):
    def __init__(self,parent=None):
        super(_RigControllerNames,self).__init__(parent)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0,0,0,0)
        self.custom = QtWidgets.QCheckBox("Use custom controller names (blank fields use joint names)")
        outer.addWidget(self.custom)
        self.body = QtWidgets.QWidget()
        self.form = QtWidgets.QFormLayout(self.body)
        self.form.setContentsMargins(0,0,0,0)
        outer.addWidget(self.body)
        self.fields = {}
        self.custom.toggled.connect(self.body.setVisible)
        self.body.setVisible(False)

    def sync(self,module_type,joints,reset=False):
        old = {} if reset else {key:field.text() for key,field in self.fields.items()}
        while self.form.rowCount(): self.form.removeRow(0)
        self.fields = {}
        for key,label,default in _rig_module_name_rows(module_type,joints):
            field = QtWidgets.QLineEdit(old.get(key,""))
            field.setPlaceholderText(default)
            self.form.addRow(label+":",field)
            self.fields[key] = field

    def values(self):
        return {key:field.text().strip() for key,field in self.fields.items() if field.text().strip()} if self.custom.isChecked() else {}


def build_fk_module(joints, name="FK", include_children=False, control_size=1.0, controller_names=None, parent_output=None, parent_method="matrix_parent", parent_follow_scale=True):
    """Build an independent FK control tree without reparenting source joints."""
    plan = plan_fk_module(joints, include_children, control_size, name)
    names = _rig_module_names("FK",plan["joints"],controller_names)
    _rig_module_require_undo()
    selection = cmds.ls(selection=True, long=True) or []
    prefix = ":" + _rig_module_joint_label(plan["root_joint"]) + "_FK_"
    undo_name = "BuildFKModule_" + uuid.uuid4().hex
    members = []
    member_ids = set()
    def remember(node):
        identity = _guide_ik_uuid(node)
        if identity not in member_ids:
            members.append({"uuid": identity, "type": cmds.nodeType(node)})
            member_ids.add(identity)
        return identity
    def circle(suffix, size):
        node = cmds.circle(name=":"+suffix, normal=(1, 0, 0), radius=size, constructionHistory=False)[0]
        identity = remember(node)
        for shape in cmds.listRelatives(node, shapes=True, fullPath=True) or []:
            remember(shape)
        return identity
    constraint_scope=_constraint_context(prefix,remember)
    changed = False
    try:
        try:
            with _tool_action(undo_name):
                changed = True
                root_id = circle(names["root"], plan["size"] * 1.7)
                root = _rig_module_node(root_id)
                cmds.matchTransform(root, plan["root_joint"], position=True, rotation=True)
                cmds.addAttr(root, longName="globalScale", attributeType="double", defaultValue=1.0, minValue=0.001, keyable=True)
                for axis in "XYZ":
                    cmds.connectAttr(root+".globalScale", root+".scale"+axis)
                control_ids, rows = {}, []
                for index, joint in enumerate(plan["joints"]):
                    label = joint.rsplit("|", 1)[-1].replace(":", "_")
                    suffix = "{:03d}_{}".format(index+1, label)
                    offset_id = remember(cmds.group(empty=True, name=prefix+suffix+"_ZERO"))
                    parent_id = control_ids.get(plan["parents"][joint], root_id)
                    cmds.parent(_rig_module_node(offset_id), _rig_module_node(parent_id))
                    cmds.matchTransform(_rig_module_node(offset_id), joint, position=True, rotation=True)
                    ctrl_id = circle(names[_guide_ik_uuid(joint)], plan["size"])
                    cmds.setAttr(_rig_module_node(ctrl_id)+".rotateOrder", cmds.getAttr(joint+".rotateOrder"))
                    cmds.parent(_rig_module_node(ctrl_id), _rig_module_node(offset_id), relative=True)
                    control_ids[joint] = ctrl_id
                    rows.append({"joint": _guide_ik_uuid(joint), "control": ctrl_id, "offset": offset_id, "constraints": []})
                # All bind frames are sampled before any source joint is driven.
                for row in rows:
                    joint, ctrl = _rig_module_node(row["joint"]), _rig_module_node(row["control"])
                    row["output"] = _rig_module_output_child(joint, row["control"], remember)
                    ctrl = _rig_module_node(row["output"])
                    for command, suffix in (("parentConstraint", "parent"), ("scaleConstraint", "scale")):
                        constraint = _constraint_command(command,ctrl, joint, maintainOffset=True, name=prefix+suffix+"#", _scope=constraint_scope)[0]
                        row["constraints"].append(remember(constraint))
                    row["inputs"] = {}
                    for channel in (prefix+axis for prefix in ("translate", "rotate", "scale") for axis in "XYZ"):
                        inputs = _rig_module_inputs(joint+"."+channel)
                        if len(inputs) != 1 or _guide_ik_uuid(inputs[0].split(".",1)[0]) not in row["constraints"]:
                            raise RuntimeError("Unexpected FK channel connection: {}.{}".format(joint, channel))
                        node, attribute = inputs[0].split(".", 1)
                        row["inputs"][channel] = {"node": _guide_ik_uuid(node), "attribute": attribute}
                meta_id = remember(cmds.createNode("network", name=prefix+"META", skipSelect=True))
                meta = _rig_module_node(meta_id)
                for attribute in (_RIG_MODULE_TAG, _RIG_MODULE_STATE, "moduleType", "moduleName"):
                    cmds.addAttr(meta, longName=attribute, dataType="string")
                cmds.setAttr(meta+"."+_RIG_MODULE_TAG, "1", type="string")
                cmds.setAttr(meta+".moduleType", "FK", type="string")
                cmds.setAttr(meta+".moduleName", plan["name"], type="string")
                for attribute in ("sources", "members"):
                    cmds.addAttr(meta, longName=attribute, attributeType="message", multi=True)
                cmds.addAttr(meta, longName="root", attributeType="message")
                cmds.connectAttr(root+".message", meta+".root")
                for index, record in enumerate(plan["snapshots"]):
                    cmds.connectAttr(_rig_module_node(record["uuid"])+".message", meta+".sources[{}]".format(index))
                for index, record in enumerate(members):
                    if record["uuid"] != meta_id:
                        cmds.connectAttr(_rig_module_node(record["uuid"])+".message", meta+".members[{}]".format(index))
                state = {"schema": 1, "type": "FK", "name": plan["name"], "meta": meta_id, "root": root_id,
                         "members": members, "joints": plan["snapshots"], "controls": rows, "control_size": plan["size"]}
                state["controller_names"] = {role:_rig_module_node(identity).rsplit("|",1)[-1] for role,identity in _rig_module_controller_roles(state).items()}
                if constraint_scope["node"]:state["constraint_group"]=constraint_scope["node"]
                state["defaults"],state["default_units"] = _rig_module_capture_defaults(state),_rig_module_units()
                _rig_module_finish_outputs(meta, state, parent_output,parent_method,parent_follow_scale)
                _rig_module_verify_pose(plan["snapshots"])
        except Exception as exc:
            if changed and cmds.undoInfo(query=True, undoName=True) == undo_name:
                cmds.undo()
                raise RuntimeError("FK build was rolled back; the original joints were kept: {}".format(exc)) from exc
            raise
    finally:
        _restore_locator_view_selection(selection)
    return {"module": meta, "root": _rig_module_node(root_id), "controls": [_rig_module_node(row["control"]) for row in rows],
            "joint_count": len(rows), "owned_node_count": len(members),
            "outputs": _rig_module_output_rows(meta, state), "input": _rig_module_node(state['input'])}


def remove_rig_module(module):
    """Delete owned nodes and retain the evaluated joint pose at this frame."""
    meta, state = _rig_module_read(module)
    for other in list_rig_modules():
        if _guide_ik_uuid(other) == state['meta']: continue
        try:
            child = json.loads(cmds.getAttr(other + '.' + _RIG_MODULE_STATE))
        except (ValueError, TypeError, RuntimeError):
            continue  # Unrelated damaged metadata must not block this removal.
        if child.get('attachment', {}).get('module') == state['meta']:
            raise ValueError("Detach child module '{}' before deleting '{}'; use Detach · keep pose.".format(child.get('name', other), state['name']))
    _rig_module_require_undo()
    owned = set(row["uuid"] for row in state["members"])
    allowed_outputs, snapshots = set(), []
    for row in state["controls"]:
        joint = _guide_ik_resolve_uuid(row["joint"])
        if not joint:
            continue
        if cmds.referenceQuery(joint, isNodeReferenced=True) or (cmds.lockNode(joint, query=True, lock=True) or [False])[0]:
            raise ValueError("Source joint is locked or referenced: {}".format(joint))
        snapshot = {"uuid": row["joint"], "world": cmds.xform(joint, query=True, worldSpace=True, matrix=True), "channels": {}}
        for attribute in ("jointOrient", "rotateAxis", "segmentScaleCompensate"):
            snapshot[attribute] = cmds.getAttr(joint+"."+attribute)
        if state["type"] in ("ROOT","FOOT") or state.get("ik",{}).get("solver")=="x_translate_v1":
            plug=joint+".offsetParentMatrix"
            if cmds.getAttr(plug,lock=True):raise ValueError("Unlock offsetParentMatrix before removal: "+joint)
            for driver in _rig_module_inputs(plug):
                if _guide_ik_uuid(driver.split(".",1)[0]) not in row["constraints"]:
                    raise ValueError("Joint offsetParentMatrix has another driver: "+plug)
            snapshot["opm"]=_rig_module_matrix_value(plug)
            allowed_outputs.add(_rig_module_plug_key(plug))
            snapshots.append(snapshot)
            continue
        for prefix in ("translate", "rotate", "scale"):
            if cmds.getAttr(joint+"."+prefix, lock=True):
                raise ValueError("Unlock the joint channel before removal: {}.{}".format(joint, prefix))
            if any(_guide_ik_uuid(plug.split(".",1)[0]) not in row["constraints"] for plug in _rig_module_inputs(joint+"."+prefix)):
                raise ValueError("Joint channel has another driver; removal stopped: {}.{}".format(joint, prefix))
            # Native constraints can expose the whole compound as a destination.
            allowed_outputs.add(_rig_module_plug_key(joint+"."+prefix))
        for channel, expected in row["inputs"].items():
            plug = joint+"."+channel
            if cmds.getAttr(plug, lock=True):
                raise ValueError("Unlock the joint channel before removal: {}".format(plug))
            inputs = _rig_module_inputs(plug)
            if any(_guide_ik_uuid(driver.split(".",1)[0]) not in row["constraints"] for driver in inputs):
                raise ValueError("Joint channel has another driver; removal stopped: {} ← {}".format(plug, ", ".join(inputs)))
            if inputs:
                allowed_outputs.add(_rig_module_plug_key(plug))
            snapshot["channels"][channel] = cmds.getAttr(plug)
        snapshots.append(snapshot)
    snapshots.sort(key=lambda row: _rig_module_node(row["uuid"]).count("|"))
    for record in state["members"]:
        node = _guide_ik_resolve_uuid(record["uuid"])
        if not node:
            continue
        if cmds.referenceQuery(node, isNodeReferenced=True) or (cmds.lockNode(node, query=True, lock=True) or [False])[0]:
            raise ValueError("Module member is locked or referenced: {}".format(node))
        if cmds.objectType(node, isAType="dagNode"):
            for child in cmds.listRelatives(node, allDescendents=True, fullPath=True) or []:
                if _guide_ik_uuid(child) not in owned:
                    raise ValueError("Move '{}' out of the module before removal.".format(child))
        for plug in cmds.listConnections(node, source=False, destination=True, plugs=True) or []:
            if _guide_ik_uuid(plug.split(".", 1)[0]) not in owned and _rig_module_plug_key(plug) not in allowed_outputs:
                raise ValueError("Another system uses module output '{}'. Disconnect it before removal.".format(plug))
    selection = cmds.ls(selection=True, long=True) or []
    undo_name = "RemoveRigModule_"+uuid.uuid4().hex
    changed = False
    try:
        try:
            with _tool_action(undo_name):
                changed = True
                _guide_ik_delete_owned(owned)
                for snapshot in snapshots:
                    joint = _rig_module_node(snapshot["uuid"])
                    if "opm" in snapshot:cmds.setAttr(joint+".offsetParentMatrix",*snapshot["opm"],type="matrix")
                    for channel, value in snapshot["channels"].items():
                        cmds.setAttr(joint+"."+channel, value)
                _rig_module_verify_pose(snapshots)
        except Exception as exc:
            if changed and cmds.undoInfo(query=True, undoName=True) == undo_name:
                cmds.undo()
                raise RuntimeError("Removal was rolled back; the rig module was kept: {}".format(exc)) from exc
            raise
    finally:
        _restore_locator_view_selection(selection)
    return {"name": state["name"], "joint_count": len(snapshots)}


_RIG_MODULE_IK_LENGTH_ATTRS = {
    "stretch": (0.0,0.0,1.0), "antiPop": (0.0,0.0,1.0),
    "upperSlide": (0.0,-0.95,10.0), "lowerSlide": (0.0,-0.95,10.0),
    "slide": (0.0,-1.0,1.0), "poleLock": (0.0,0.0,1.0)}
_RIG_MODULE_IK_LENGTH_NODES = {"multMatrix","pointMatrixMult","distanceBetween","multiplyDivide",
                              "plusMinusAverage","condition","clamp","blendColors","unitConversion"}


def ik_length_solution(upper, lower, distance, start_pole, pole_end, stretch=0, anti_pop=0,
                       upper_slide=0, lower_slide=0, slide=0, pole_lock=0):
    """Reference math in ROOT space. Runtime uses native nodes, not this function."""
    values = (upper,lower,distance,start_pole,pole_end,stretch,anti_pop,upper_slide,lower_slide,slide,pole_lock)
    if not all(math.isfinite(float(value)) for value in values) or min(upper,lower)<=0 or min(distance,start_pole,pole_end)<0:
        raise ValueError("Lengths/distances must be finite and nonnegative, with positive rest lengths.")
    clamp = lambda value,lo,hi:max(lo,min(hi,float(value)))
    stretch,anti_pop,pole_lock = [clamp(v,0,1) for v in (stretch,anti_pop,pole_lock)]
    upper_slide,lower_slide = [clamp(v,-.95,10) for v in (upper_slide,lower_slide)]
    slide = clamp(slide,-1,1)
    epsilon = (upper+lower)*1e-4
    u,l = upper*(1+upper_slide),lower*(1+lower_slide)
    total = u+l
    u += slide*((l-epsilon) if slide>=0 else (u-epsilon))
    l = total-u
    zone = anti_pop*.2*total
    threshold = total-zone
    soft = distance
    if distance>threshold:
        soft = total-zone*math.exp(-min(60,max(0,distance-threshold)/max(zone,epsilon)))
    soft = min(distance,soft)
    factor = 1+stretch*(max(1,distance/max(soft,epsilon))-1)
    upper_out = max(epsilon,u*factor*(1-pole_lock)+start_pole*pole_lock)
    lower_out = max(epsilon,l*factor*(1-pole_lock)+pole_end*pole_lock)
    goal = soft*factor*(1-pole_lock)+distance*pole_lock
    return {"upper":upper_out,"lower":lower_out,"goal":goal,"stretch_factor":factor,"soft_reach":soft}


class _IKLengthGraph:
    def __init__(self,prefix,remember):
        self.prefix,self.remember,self.members = prefix,remember,[]

    def node(self,kind,label):
        node = cmds.createNode(kind,name=self.prefix+label+"#",skipSelect=True)
        identity = self.remember(node)
        if identity not in self.members:self.members.append(identity)
        return _rig_module_node(identity)

    def connect(self,source,destination):
        cmds.connectAttr(source,destination)
        for plug in _rig_module_inputs(destination):
            node = plug.split(".",1)[0]
            if cmds.nodeType(node)=="unitConversion":
                identity = self.remember(node)
                if identity not in self.members:self.members.append(identity)
                # Matrix points are centimeters internally. Keep numeric lengths
                # in that space even when Maya's UI linear unit changes.
                cmds.setAttr(node+".conversionFactor",1.0)

    def put(self,value,plug):
        self.connect(value,plug) if isinstance(value,str) else cmds.setAttr(plug,float(value))

    def math(self,a,b,operation,label):
        node = self.node("multiplyDivide",label)
        cmds.setAttr(node+".operation",operation)
        self.put(a,node+".input1X");self.put(b,node+".input2X")
        return node+".outputX"

    def sum(self,a,b,subtract=False,label="sum"):
        node = self.node("plusMinusAverage",label)
        cmds.setAttr(node+".operation",2 if subtract else 1)
        self.put(a,node+".input1D[0]");self.put(b,node+".input1D[1]")
        return node+".output1D"

    def clamp(self,value,lo,hi,label="clamp"):
        node = self.node("clamp",label)
        self.put(value,node+".inputR");self.put(lo,node+".minR");self.put(hi,node+".maxR")
        return node+".outputR"

    def choose(self,a,b,yes,no,operation=2,label="condition"):
        node = self.node("condition",label)
        cmds.setAttr(node+".operation",operation)
        for value,attribute in ((a,"firstTerm"),(b,"secondTerm"),(yes,"colorIfTrueR"),(no,"colorIfFalseR")):
            self.put(value,node+"."+attribute)
        return node+".outColorR"

    def mix(self,a,b,weight,label="blend"):
        node = self.node("blendColors",label)
        self.put(a,node+".color2R");self.put(b,node+".color1R");self.put(weight,node+".blender")
        return node+".outputR"

    def point(self,node,root,label):
        matrix = self.node("multMatrix",label+"_matrix")
        self.connect(node+".worldMatrix[0]",matrix+".matrixIn[0]")
        self.connect(root+".worldInverseMatrix[0]",matrix+".matrixIn[1]")
        point = self.node("pointMatrixMult",label+"_point")
        self.connect(matrix+".matrixSum",point+".inMatrix")
        return point+".output"

    def distance(self,a,b,label):
        node = self.node("distanceBetween",label)
        for value,attribute in ((a,"point1"),(b,"point2")):
            if isinstance(value,str):self.connect(value,node+"."+attribute)
            elif value is not None:cmds.setAttr(node+"."+attribute,*value,type="double3")
        return node+".distance"

    def vector(self,vector,ratio,destination,label):
        node = self.node("multiplyDivide",label)
        for index,axis in enumerate("XYZ"):
            self.put(vector+axis if isinstance(vector,str) else vector[index],node+".input1"+axis)
            self.put(ratio,node+".input2"+axis)
            self.connect(node+".output"+axis,destination+axis)


def _rig_module_length_matrix(node):
    value = cmds.getAttr(node+".worldMatrix[0]")
    if len(value)==1 and isinstance(value[0],(list,tuple)):value=value[0]
    return list(value)


def _rig_module_install_lengths(state,prefix,remember):
    """Called only inside a guarded build/upgrade Undo action."""
    root,end,pole,handle = [_rig_module_node(state["root"] if key=="root" else state["ik"][key])
                          for key in ("root","end","pole","handle")]
    drivers = [_rig_module_node(identity) for identity in state["ik"]["drivers"]]
    units = _rig_module_units()
    vectors = [[_rig_module_unit_value("translate"+axis,float(cmds.getAttr(joint+".translate"+axis)),units,{"angle":"deg","linear":"cm"})
                for axis in "XYZ"] for joint in drivers[1:]]
    root_matrix = _rig_module_length_matrix(root)
    root_scale = math.sqrt(sum(value*value for value in root_matrix[:3]))
    first_matrix = _rig_module_length_matrix(drivers[0])
    delta = [first_matrix[12+i]-root_matrix[12+i] for i in range(3)]
    anchor = [sum(delta[i]*root_matrix[axis*4+i] for i in range(3))/(root_scale*root_scale) for axis in range(3)]
    lengths = []
    for vector,parent in zip(vectors,drivers[:2]):
        matrix = _rig_module_length_matrix(parent)
        parent_scale = math.sqrt(sum(value*value for value in matrix[:3]))/root_scale
        lengths.append(math.sqrt(sum(value*value for value in vector))*parent_scale)
    if min(lengths)<=1e-8:raise ValueError("IK driver bones must have positive rest lengths.")
    graph = _IKLengthGraph(prefix,remember)
    for attribute,(default,minimum,maximum) in _RIG_MODULE_IK_LENGTH_ATTRS.items():
        cmds.addAttr(end,longName=attribute,attributeType="double",defaultValue=default,minValue=minimum,maxValue=maximum,keyable=True)
    for attribute in ("upperLength","lowerLength"):
        cmds.addAttr(end,longName=attribute,attributeType="doubleLinear",minValue=0,keyable=False)
        cmds.setAttr(end+"."+attribute,channelBox=True)
    goal = graph.node("transform","softGoal")
    goal_id = _guide_ik_uuid(goal)
    cmds.parent(goal,root,relative=True)
    goal = _rig_module_node(goal_id)
    cmds.matchTransform(goal,end,position=True,rotation=True)
    cmds.parent(handle,goal,absolute=True)
    endpoint,polepoint = graph.point(end,root,"end"),graph.point(pole,root,"pole")
    startpoint=graph.point(_rig_module_node(state["ik"]["base"]),root,"start") if state["ik"].get("base") else anchor
    distance = graph.distance(startpoint,endpoint,"reachDistance")
    upper_pin = graph.distance(startpoint,polepoint,"upperPinDistance")
    lower_pin = graph.distance(polepoint,endpoint,"lowerPinDistance")
    controls = {name:graph.clamp(end+"."+name,lo,hi,label=name+"Range")
                for name,(_default,lo,hi) in _RIG_MODULE_IK_LENGTH_ATTRS.items()}
    epsilon = sum(lengths)*1e-4
    upper = graph.math(lengths[0],graph.sum(1,controls["upperSlide"],label="upperAdjust"),1,"upperManual")
    lower = graph.math(lengths[1],graph.sum(1,controls["lowerSlide"],label="lowerAdjust"),1,"lowerManual")
    total = graph.sum(upper,lower,label="manualTotal")
    transfer = graph.choose(controls["slide"],0,graph.sum(lower,epsilon,True,"lowerAvailable"),
                            graph.sum(upper,epsilon,True,"upperAvailable"),operation=3,label="slideSide")
    upper = graph.sum(upper,graph.math(controls["slide"],transfer,1,"slideTransfer"),label="slidUpper")
    lower = graph.sum(total,upper,True,"slidLower")
    zone = graph.math(graph.math(controls["antiPop"],.2,1,"softFraction"),total,1,"softZone")
    threshold = graph.sum(total,zone,True,"softThreshold")
    excess = graph.clamp(graph.sum(distance,threshold,True,"softExcess"),0,1e20,"positiveExcess")
    exponent = graph.clamp(graph.math(graph.math(excess,-1,1,"negativeExcess"),graph.clamp(zone,epsilon,1e20,"safeZone"),2,"softExponent"),-60,0,"exponentRange")
    exponential = graph.math(math.e,exponent,3,"softExp")
    curve = graph.sum(total,graph.math(zone,exponential,1,"softTail"),True,"softCurve")
    soft = graph.choose(distance,threshold,curve,distance,label="softReach")
    ratio = graph.clamp(graph.math(distance,graph.clamp(soft,epsilon,1e20,"safeSoft"),2,"stretchRatio"),1,1e20,"extendOnly")
    factor = graph.mix(1,ratio,controls["stretch"],"stretchBlend")
    upper_out = graph.clamp(graph.mix(graph.math(upper,factor,1,"stretchedUpper"),upper_pin,controls["poleLock"],"upperPin"),epsilon,1e20,"safeUpper")
    lower_out = graph.clamp(graph.mix(graph.math(lower,factor,1,"stretchedLower"),lower_pin,controls["poleLock"],"lowerPin"),epsilon,1e20,"safeLower")
    goal_radius = graph.mix(graph.math(soft,factor,1,"softGoalRadius"),distance,controls["poleLock"],"pinGoal")
    goal_ratio = graph.math(goal_radius,graph.clamp(distance,epsilon,1e20,"safeDistance"),2,"goalRatio")
    if not isinstance(startpoint,str) and max(abs(value) for value in anchor)<1e-10:
        graph.vector(endpoint,goal_ratio,goal+".translate","goalPosition")
    else:
        for index,axis in enumerate("XYZ"):
            origin=startpoint+axis if isinstance(startpoint,str) else anchor[index]
            direction = graph.sum(endpoint+axis,origin,True,"goalDirection"+axis)
            position = graph.sum(origin,graph.math(direction,goal_ratio,1,"goalOffset"+axis),label="goalPosition"+axis)
            graph.connect(position,goal+".translate"+axis)
    for index,output in enumerate((upper_out,lower_out)):
        bone_ratio = graph.math(output,lengths[index],2,"boneRatio"+str(index))
        if state["ik"].get("solver")=="x_translate_v1":
            value=graph.math(vectors[index][0],bone_ratio,1,"boneTranslateX"+str(index))
            graph.connect(value,drivers[index+1]+".translateX")
        else:graph.vector(vectors[index],bone_ratio,drivers[index+1]+".translate","boneTranslate"+str(index))
        graph.connect(output,end+"."+("upperLength" if index==0 else "lowerLength"))
    return {"version":1,"goal":goal_id,"nodes":graph.members,"rest_lengths":lengths,"rest_vectors_cm":vectors,"start_point_root_cm":anchor,
            "attributes":list(_RIG_MODULE_IK_LENGTH_ATTRS),"outputs":["upperLength","lowerLength"]}


def enable_ik_length_features(module):
    """Upgrade an existing IK3 rig in one Undo action; leave its current pose intact."""
    meta,state = _rig_module_read(module)
    if state["type"] not in ("IK3","IKFK"):raise ValueError("Choose a Three-Bone IK or IK/FK module.")
    if state["ik"].get("length_system"):return {"module":meta,"existing":True}
    end = _rig_module_node(state["ik"]["end"])
    for attribute in list(_RIG_MODULE_IK_LENGTH_ATTRS)+["upperLength","lowerLength"]:
        if cmds.attributeQuery(attribute,node=end,exists=True):raise ValueError("END already has a custom attribute named {}. Keep it or rename it before upgrading.".format(attribute))
    for identity in [state["meta"],state["root"],state["ik"]["end"],state["ik"]["handle"]]+state["ik"]["drivers"]:
        node = _rig_module_node(identity)
        if cmds.referenceQuery(node,isNodeReferenced=True) or (cmds.lockNode(node,query=True,lock=True) or [False])[0]:
            raise ValueError("IK member is locked or referenced: {}".format(node))
    for identity in state["ik"]["drivers"][1:]:
        node = _rig_module_node(identity)
        for attribute in ["translate"]+["translate"+axis for axis in "XYZ"]:
            if cmds.getAttr(node+"."+attribute,lock=True) or _rig_module_inputs(node+"."+attribute):
                raise ValueError("IK bone translation is locked or already driven: {}.{}".format(node,attribute))
    snapshots = [{"uuid":row["uuid"],"world":cmds.xform(_rig_module_node(row["uuid"]),query=True,worldSpace=True,matrix=True),
                  **{attribute:cmds.getAttr(_rig_module_node(row["uuid"])+"."+attribute)
                     for attribute in ("jointOrient","rotateAxis","segmentScaleCompensate")}} for row in state["joints"]]
    _rig_module_require_undo()
    undo_name = "UpgradeIKLengths_"+uuid.uuid4().hex
    def remember(node):
        identity = _guide_ik_uuid(node)
        if identity not in {row["uuid"] for row in state["members"]}:state["members"].append({"uuid":identity,"type":cmds.nodeType(node)})
        return identity
    try:
        with _tool_action(undo_name):
            state["ik"]["length_system"] = _rig_module_install_lengths(state,":"+_rig_module_joint_label(_rig_module_node(state["joints"][0]["uuid"]))+"_IK_",remember)
            for index,row in enumerate(state["members"]):
                destination = meta+".members[{}]".format(index)
                if row["uuid"]!=state["meta"] and not _rig_module_inputs(destination):cmds.connectAttr(_rig_module_node(row["uuid"])+".message",destination)
            for record in state.get("defaults",[]):
                if record["uuid"]==state["ik"]["end"]:
                    record["values"].update({name:data[0] for name,data in _RIG_MODULE_IK_LENGTH_ATTRS.items()})
            _rig_module_save(meta,state)
            _rig_module_verify_pose(snapshots)
            _rig_module_read(meta)
    except Exception as exc:
        if cmds.undoInfo(query=True,undoName=True)==undo_name:
            cmds.undo()
            raise RuntimeError("IK length upgrade was rolled back: {}".format(exc)) from exc
        raise
    return {"module":meta,"existing":False}


def set_ik_length_controls(module,values,keyframe=False):
    _meta,state = _rig_module_read(module)
    if state["type"] not in ("IK3","IKFK") or not state["ik"].get("length_system"):
        raise ValueError("Choose an IK module with length features. Upgrade the selected older IK first.")
    end = _rig_module_node(state["ik"]["end"])
    if cmds.referenceQuery(end,isNodeReferenced=True) or (cmds.lockNode(end,query=True,lock=True) or [False])[0]:
        raise ValueError("END controller is locked or referenced.")
    if set(values)-set(_RIG_MODULE_IK_LENGTH_ATTRS):raise ValueError("Unknown IK length control.")
    for name,value in values.items():
        _default,lo,hi = _RIG_MODULE_IK_LENGTH_ATTRS[name]
        if not math.isfinite(float(value)) or not lo<=float(value)<=hi:raise ValueError("{} must be between {} and {}.".format(name,lo,hi))
        plug = end+"."+name
        inputs = _rig_module_inputs(plug)
        if cmds.getAttr(plug,lock=True) or (inputs and (not keyframe or any(cmds.nodeType(item.split(".",1)[0]) not in ("animCurveTA","animCurveTL","animCurveTU") for item in inputs))):
            raise ValueError("{} is locked or driven. Enable keying for direct time animation; other drivers are kept.".format(plug))
    _rig_module_require_undo()
    undo_name = "SetIKLengths_"+uuid.uuid4().hex
    try:
        with _tool_action(undo_name):
            for name,value in values.items():
                if keyframe:cmds.setKeyframe(end,attribute=name,value=float(value))
                else:cmds.setAttr(end+"."+name,float(value))
    except Exception as exc:
        if cmds.undoInfo(query=True,undoName=True)==undo_name:
            cmds.undo();raise RuntimeError("IK length values were rolled back: {}".format(exc)) from exc
        raise
    return dict(values)


def plan_ik_module(first_joint, second_joint, third_joint, name="IK", control_size=1.0, pole_distance=1.0):
    """Three consecutive joints (two bend segments), using the shared module guards."""
    ik_plan = plan_guide_ik(first_joint, second_joint, third_joint, control_size, pole_distance)
    plan = plan_fk_module(ik_plan["joints"], False, control_size, name)
    plan["pole"] = ik_plan["pole"]
    return plan


def build_ik_module(first_joint, second_joint, third_joint, name="IK", control_size=1.0, pole_distance=1.0, controller_names=None, _module_type="IK3", _matrix_solver=True, parent_output=None, parent_method="matrix_parent", parent_follow_scale=True):
    """Native RP IK on owned driver joints; original joints retain their hierarchy."""
    if _matrix_solver:
        return _rig_module_build_xik(first_joint,second_joint,third_joint,name,control_size,pole_distance,controller_names,_module_type,parent_output,parent_method,parent_follow_scale)
    plan = plan_ik_module(first_joint, second_joint, third_joint, name, control_size, pole_distance)
    if _module_type not in ("IK3","IKFK"):raise ValueError("Unknown IK module type.")
    names = _rig_module_names(_module_type,plan["joints"],controller_names)
    _rig_module_require_undo()
    selection = cmds.ls(selection=True, long=True) or []
    prefix = ":" + _rig_module_joint_label(plan["root_joint"]) + ("_IKFK_" if _module_type=="IKFK" else "_IK_")
    undo_name = "BuildIKModule_" + uuid.uuid4().hex
    members, identities = [], set()
    def remember(node):
        identity = _guide_ik_uuid(node)
        if identity not in identities:
            identities.add(identity)
            members.append({"uuid":identity, "type":cmds.nodeType(node)})
        return identity
    def control(suffix, normal, radius):
        node = cmds.circle(name=":"+suffix, normal=normal, radius=radius, constructionHistory=False)[0]
        identity = remember(node)
        for shape in cmds.listRelatives(node, shapes=True, fullPath=True) or []: remember(shape)
        return identity
    constraint_scope=_constraint_context(prefix,remember)
    changed = False
    try:
        try:
            with _tool_action(undo_name):
                changed = True
                root_id = control(names["root"], (1,0,0), plan["size"]*1.7)
                root = _rig_module_node(root_id)
                cmds.matchTransform(root, plan["root_joint"], position=True, rotation=True)
                cmds.addAttr(root, longName="globalScale", attributeType="double", defaultValue=1, minValue=.001, keyable=True)
                for axis in "XYZ": cmds.connectAttr(root+".globalScale", root+".scale"+axis)
                driver_group = remember(cmds.group(empty=True, name=prefix+"DRIVERS"))
                cmds.parent(_rig_module_node(driver_group), root, relative=True)
                base_id=None
                if _module_type=="IKFK":
                    base_zero=remember(cmds.group(empty=True,name=prefix+"BASE_ZERO"))
                    cmds.parent(_rig_module_node(base_zero),root,relative=True)
                    cmds.xform(_rig_module_node(base_zero),worldSpace=True,matrix=plan["snapshots"][0]["world"])
                    base_id=control(names["base"],(1,0,0),plan["size"]*.8)
                    cmds.parent(_rig_module_node(base_id),_rig_module_node(base_zero),relative=True)
                    cmds.parent(_rig_module_node(driver_group),_rig_module_node(base_id),absolute=True)
                drivers, rows = [], []
                for index, joint in enumerate(plan["joints"]):
                    parent_id = drivers[-1] if drivers else driver_group
                    driver_id = remember(cmds.createNode("joint", name=prefix+"driver{:02d}_JNT".format(index+1),
                                                         parent=_rig_module_node(parent_id), skipSelect=True))
                    driver = _rig_module_node(driver_id)
                    cmds.setAttr(driver+".segmentScaleCompensate", False)
                    cmds.setAttr(driver+".rotateOrder", cmds.getAttr(joint+".rotateOrder"))
                    for attribute in ("jointOrient", "rotateAxis"):
                        cmds.setAttr(driver+"."+attribute, *cmds.getAttr(joint+"."+attribute)[0], type="double3")
                    cmds.xform(driver, worldSpace=True, matrix=plan["snapshots"][index]["world"])
                    cmds.setAttr(driver+".preferredAngle", *cmds.getAttr(driver+".rotate")[0], type="double3")
                    drivers.append(driver_id)
                    rows.append({"joint":_guide_ik_uuid(joint), "control":driver_id, "offset":parent_id, "constraints":[]})
                end_zero = remember(cmds.group(empty=True, name=prefix+"END_ZERO"))
                cmds.parent(_rig_module_node(end_zero), root, relative=True)
                cmds.matchTransform(_rig_module_node(end_zero), plan["joints"][2], position=True, rotation=True)
                end_id = control(names["end"], (0,1,0), plan["size"])
                cmds.parent(_rig_module_node(end_id), _rig_module_node(end_zero), relative=True)
                pole_zero = remember(cmds.group(empty=True, name=prefix+"POLE_ZERO"))
                cmds.parent(_rig_module_node(pole_zero), root, relative=True)
                cmds.xform(_rig_module_node(pole_zero), worldSpace=True, translation=plan["pole"]["position"])
                pole_id = control(names["pole"], (0,0,1), plan["size"]*.6)
                cmds.parent(_rig_module_node(pole_id), _rig_module_node(pole_zero), relative=True)
                handle, effector = cmds.ikHandle(name=prefix+"HANDLE", startJoint=_rig_module_node(drivers[0]),
                                                endEffector=_rig_module_node(drivers[2]), solver="ikRPsolver")
                handle_id, effector_id = remember(handle), remember(effector)
                cmds.parent(_rig_module_node(handle_id), _rig_module_node(end_id), absolute=True)
                cmds.setAttr(_rig_module_node(handle_id)+".visibility", False)
                pole_constraint = remember(_constraint_command('poleVectorConstraint',_rig_module_node(pole_id), _rig_module_node(handle_id), name=prefix+"poleConstraint", _scope=constraint_scope)[0])
                end_constraint = remember(_constraint_command('orientConstraint',_rig_module_node(end_id), _rig_module_node(drivers[2]), maintainOffset=True, name=prefix+"endOrient", _scope=constraint_scope)[0])
                cmds.setAttr(_rig_module_node(driver_group)+".visibility", False)
                length_context = {"root":root_id,"ik":{"end":end_id,"pole":pole_id,"handle":handle_id,"drivers":drivers}}
                if base_id:length_context["ik"]["base"]=base_id
                length_system = _rig_module_install_lengths(length_context,prefix,remember)
                blend=None
                if _module_type=="IKFK":
                    blend=_rig_module_build_ikfk(plan,root_id,end_zero,pole_zero,base_id,names,prefix,control,remember)
                for index,row in enumerate(rows):
                    joint, driver = _rig_module_node(row["joint"]), _rig_module_node(row["control"])
                    for command,suffix in (("parentConstraint","parent"),("scaleConstraint","scale")):
                        targets=[driver,_rig_module_node(blend["fk_controls"][index])] if blend else [driver]
                        constraint = _constraint_command(command,*targets, joint, maintainOffset=True, name=prefix+suffix+"#", _scope=constraint_scope)[0]
                        row["constraints"].append(remember(constraint))
                        if blend:
                            aliases=_constraint_command(command,constraint,query=True,weightAliasList=True) or []
                            if len(aliases)!=2:raise RuntimeError("IK/FK constraint needs two weight aliases.")
                            cmds.connectAttr(_rig_module_node(blend["weight_node"])+".outputR",constraint+"."+aliases[0])
                            cmds.connectAttr(_rig_module_node(blend["reverse"])+".output1D",constraint+"."+aliases[1])
                            if command=="parentConstraint":cmds.setAttr(constraint+".interpType",2)
                    row["inputs"] = {}
                    for channel in (base+axis for base in ("translate","rotate","scale") for axis in "XYZ"):
                        inputs = _rig_module_inputs(joint+"."+channel)
                        if len(inputs) != 1 or _guide_ik_uuid(inputs[0].split(".",1)[0]) not in row["constraints"]:
                            raise RuntimeError("Unexpected IK joint connection: {}.{}".format(joint,channel))
                        node,attribute = inputs[0].split(".",1)
                        row["inputs"][channel] = {"node":_guide_ik_uuid(node), "attribute":attribute}
                meta_id = remember(cmds.createNode("network", name=prefix+"META", skipSelect=True))
                meta = _rig_module_node(meta_id)
                for attribute in (_RIG_MODULE_TAG,_RIG_MODULE_STATE,"moduleType","moduleName"):
                    cmds.addAttr(meta,longName=attribute,dataType="string")
                for attribute,value in ((_RIG_MODULE_TAG,"1"),("moduleType",_module_type),("moduleName",plan["name"])):
                    cmds.setAttr(meta+"."+attribute,value,type="string")
                for attribute in ("sources","members"):
                    cmds.addAttr(meta,longName=attribute,attributeType="message",multi=True)
                cmds.addAttr(meta,longName="root",attributeType="message")
                cmds.connectAttr(root+".message",meta+".root")
                for index,record in enumerate(plan["snapshots"]):
                    cmds.connectAttr(_rig_module_node(record["uuid"])+".message",meta+".sources[{}]".format(index))
                for index,record in enumerate(members):
                    if record["uuid"] != meta_id:
                        cmds.connectAttr(_rig_module_node(record["uuid"])+".message",meta+".members[{}]".format(index))
                state = {"schema":1,"type":_module_type,"name":plan["name"],"meta":meta_id,"root":root_id,
                         "members":members,"joints":plan["snapshots"],"controls":rows,"ui_controls":[end_id,pole_id],
                         "control_size":plan["size"],"ik":{"drivers":drivers,"driver_group":driver_group,
                         "end":end_id,"pole":pole_id,"handle":handle_id,"effector":effector_id,
                         "pole_constraint":pole_constraint,"end_constraint":end_constraint,"length_system":length_system}}
                if blend:
                    state["ikfk"]=blend
                    state["ik"]["base"]=base_id
                    state["ui_controls"]=blend["fk_controls"]+[base_id,end_id,pole_id]
                state["controller_names"] = {role:_rig_module_node(identity).rsplit("|",1)[-1] for role,identity in _rig_module_controller_roles(state).items()}
                if constraint_scope["node"]:state["constraint_group"]=constraint_scope["node"]
                state["defaults"],state["default_units"] = _rig_module_capture_defaults(state),_rig_module_units()
                state["pole_distance"] = float(pole_distance)
                _rig_module_finish_outputs(meta, state, parent_output,parent_method,parent_follow_scale)
                _rig_module_verify_pose(plan["snapshots"])
                _rig_module_read(meta)
        except Exception as exc:
            if changed and cmds.undoInfo(query=True,undoName=True) == undo_name:
                cmds.undo()
                raise RuntimeError("IK module build was rolled back; original joints were kept: {}".format(exc)) from exc
            raise
    finally:
        _restore_locator_view_selection(selection)
    result={"module":meta,"root":_rig_module_node(root_id),"end_controller":_rig_module_node(end_id),
            "pole_controller":_rig_module_node(pole_id),"handle":_rig_module_node(handle_id),
            "joint_count":3,"owned_node_count":len(members),
            "outputs":_rig_module_output_rows(meta,state),"input":_rig_module_node(state["input"])}
    if blend:result.update({"base_controller":_rig_module_node(base_id),"fk_controllers":[_rig_module_node(identity) for identity in blend["fk_controls"]]})
    return result


def _rig_module_matrix_value(plug):
    value=cmds.getAttr(plug)
    if len(value)==1 and isinstance(value[0],(tuple,list)):value=value[0]
    value=list(value)
    if len(value)!=16 or not all(math.isfinite(float(v)) for v in value):raise ValueError("Invalid matrix: "+plug)
    return value


def _rig_module_matrix_identity():
    return [1.0 if r==c else 0.0 for r in range(4) for c in range(4)]


def _rig_module_matrix_product(a,b):
    return [sum(a[r*4+k]*b[k*4+c] for k in range(4)) for r in range(4) for c in range(4)]


def _rig_module_matrix_inverse(value):
    rows=[list(value[r*4:r*4+4])+[float(r==c) for c in range(4)] for r in range(4)]
    for col in range(4):
        pivot=max(range(col,4),key=lambda r:abs(rows[r][col]))
        if abs(rows[pivot][col])<1e-12:raise ValueError("Cannot invert a singular matrix.")
        rows[col],rows[pivot]=rows[pivot],rows[col]
        divisor=rows[col][col];rows[col]=[v/divisor for v in rows[col]]
        for r in range(4):
            if r!=col:
                factor=rows[r][col];rows[r]=[a-factor*b for a,b in zip(rows[r],rows[col])]
    return [rows[r][c] for r in range(4) for c in range(4,8)]


def _rig_module_x_frames(points):
    """Right-handed unit frames: +X aims at child, shared Z is the bend normal."""
    def subtract(a,b):return [a[i]-b[i] for i in range(3)]
    def normalize(v):
        length=math.sqrt(sum(x*x for x in v))
        if length<1e-10:raise ValueError("X-axis IK needs a nonzero, bent joint chain.")
        return [x/length for x in v]
    def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    upper,lower=normalize(subtract(points[1],points[0])),normalize(subtract(points[2],points[1]))
    normal=normalize(cross(upper,lower))
    result=[]
    for position,x in zip(points,(upper,lower,lower)):
        y=normalize(cross(normal,x))
        result.append(x+[0]+y+[0]+normal+[0]+list(position)+[1])
    return result


def _rig_module_x_pick(graph,plug,label):
    node=graph.node("pickMatrix",label)
    graph.connect(plug,node+".inputMatrix")
    cmds.setAttr(node+".useScale",False);cmds.setAttr(node+".useShear",False)
    return node+".outputMatrix"


def _rig_module_x_local_inverse(graph,joint,label):
    """Bind local compensation with live SSC, without source matrix feedback."""
    inverse=_rig_module_matrix_inverse(_rig_module_matrix_value(joint+".matrix"))
    if not cmds.getAttr(joint+".segmentScaleCompensate"):return inverse
    values=cmds.getAttr(joint+".inverseScale")[0]
    if any(abs(v)<1e-12 for v in values):raise ValueError("Zero joint inverseScale: "+joint)
    units=_rig_module_units()
    translation=_rig_module_matrix_identity()
    translation[12:15]=[_rig_module_unit_value("translate"+a,cmds.getAttr(joint+".translate"+a),units,{"angle":"deg","linear":"cm"}) for a in "XYZ"]
    is_bind=_rig_module_matrix_identity()
    for i,value in enumerate(values):is_bind[i*5]=1/value
    tail=_rig_module_matrix_product(_rig_module_matrix_product(is_bind,translation),inverse)
    scale=graph.node("composeMatrix",label+"SSC")
    cmds.setAttr(scale+".inputScale",*values,type="double3")
    incoming=_rig_module_inputs(joint+".inverseScale")
    if len(incoming)==1:graph.connect(incoming[0],scale+".inputScale")
    elif incoming:
        for axis in "XYZ":
            plugs=_rig_module_inputs(joint+".inverseScale"+axis)
            if plugs:graph.connect(plugs[0],scale+".inputScale"+axis)
    matrix=graph.node("multMatrix",label+"LocalInverse")
    cmds.setAttr(matrix+".matrixIn[0]",*_rig_module_matrix_inverse(translation),type="matrix")
    graph.connect(scale+".outputMatrix",matrix+".matrixIn[1]")
    cmds.setAttr(matrix+".matrixIn[2]",*tail,type="matrix")
    return matrix+".matrixSum"


def _rig_module_x_pose_blend(graph,root,outputs,blend):
    """Blend local rotations and explicit lengths, then rebuild root-to-tip.

    Blending independent world positions traces chords and shortens bones.
    All branch matrices here are rigid and in unscaled ROOT space.
    """
    def root_frame(identity,label):
        matrix=graph.node("multMatrix",label+"RootSpace")
        graph.connect(_rig_module_node(identity)+".worldMatrix[0]",matrix+".matrixIn[0]")
        graph.connect(root+".worldInverseMatrix[0]",matrix+".matrixIn[1]")
        return _rig_module_x_pick(graph,matrix+".matrixSum",label+"Rigid")
    ik=[root_frame(identity,"ik"+str(i)) for i,identity in enumerate(outputs)]
    if not blend:return ik
    fk=[root_frame(identity,"fk"+str(i)) for i,identity in enumerate(blend["fk_controls"])]
    weight=_rig_module_node(blend["weight_node"])+".outputR"
    result=[];length_outputs=[]
    for i in range(3):
        locals_=[]
        for branch,label in ((fk,"fk"),(ik,"ik")):
            value=branch[i]
            if i:
                inverse=graph.node("inverseMatrix",label+"ParentInverse"+str(i))
                graph.connect(branch[i-1],inverse+".inputMatrix")
                local=graph.node("multMatrix",label+"LocalPose"+str(i))
                graph.connect(value,local+".matrixIn[0]");graph.connect(inverse+".outputMatrix",local+".matrixIn[1]")
                value=local+".matrixSum"
            locals_.append(value)
        matrix=graph.node("blendMatrix","localPoseBlend"+str(i))
        graph.connect(locals_[0],matrix+".inputMatrix")
        graph.connect(locals_[1],matrix+".target[0].targetMatrix")
        graph.connect(weight,matrix+".target[0].weight")
        pose=matrix+".outputMatrix"
        if i:
            decomposed=[];lengths=[]
            for value,label in zip(locals_+[pose],("fk","ik","mixed")):
                node=graph.node("decomposeMatrix",label+"LocalComponents"+str(i))
                graph.connect(value,node+".inputMatrix");decomposed.append(node)
                lengths.append(graph.distance(node+".outputTranslate",None,label+"SegmentLength"+str(i)))
            length=graph.mix(lengths[0],lengths[1],weight,"segmentLengthBlend"+str(i))
            direction=graph.node("vectorProduct","segmentDirection"+str(i))
            cmds.setAttr(direction+".operation",0);cmds.setAttr(direction+".normalizeOutput",True)
            for axis in "XYZ":
                value=graph.choose(lengths[2],1e-8,decomposed[2]+".outputTranslate"+axis,
                                   decomposed[1]+".outputTranslate"+axis,label="safeDirection"+str(i)+axis)
                graph.connect(value,direction+".input1"+axis)
            composed=graph.node("composeMatrix","lengthPreservedLocal"+str(i))
            cmds.setAttr(composed+".useEulerRotation",False)
            graph.connect(decomposed[2]+".outputQuat",composed+".inputQuat")
            for axis in "XYZ":
                value=graph.math(direction+".output"+axis,length,1,"segmentTranslate"+str(i)+axis)
                graph.connect(value,composed+".inputTranslate"+axis)
            accumulated=graph.node("multMatrix","blendedChainPose"+str(i))
            graph.connect(composed+".outputMatrix",accumulated+".matrixIn[0]")
            graph.connect(result[-1],accumulated+".matrixIn[1]")
            pose=accumulated+".matrixSum";length_outputs.append(length)
        result.append(pose)
    blend["length_mode"]="local_rotation_explicit_length_v1"
    blend["segment_lengths"]=[{"node":_guide_ik_uuid(value.split(".",1)[0]),"attribute":value.split(".",1)[1]} for value in length_outputs]
    return result


def _rig_module_build_xik(first,second,third,name,size,pole_distance,controller_names,module_type,parent_output=None,parent_method="matrix_parent",parent_follow_scale=True):
    """X-only solver lengths, orientation buffers, rigid matrix source outputs."""
    if module_type not in ("IK3","IKFK"):raise ValueError("Unknown IK module type.")
    plan=plan_ik_module(first,second,third,name,size,pole_distance)
    names=_rig_module_names(module_type,plan["joints"],controller_names)
    for joint in plan["joints"]:
        if not cmds.attributeQuery("offsetParentMatrix",node=joint,exists=True):raise ValueError("Matrix IK requires offsetParentMatrix support in Maya.")
        if cmds.getAttr(joint+".offsetParentMatrix",lock=True) or _rig_module_inputs(joint+".offsetParentMatrix"):
            raise ValueError("Joint offsetParentMatrix is locked or already driven: "+joint)
        if not cmds.getAttr(joint+".inheritsTransform"):raise ValueError("Matrix IK requires inheritsTransform on: "+joint)
    # xform matrices are queried/set through the same Maya command. Internal
    # centimeter matrices are separately used for native matrix offsets.
    frames=_rig_module_x_frames([row["world"][12:15] for row in plan["snapshots"]])
    bind=[_rig_module_length_matrix(joint) for joint in plan["joints"]]
    lengths=[math.sqrt(sum((bind[i+1][12+j]-bind[i][12+j])**2 for j in range(3))) for i in range(2)]
    _rig_module_require_undo()
    selection=cmds.ls(selection=True,long=True) or []
    prefix=":"+_rig_module_joint_label(plan["root_joint"])+("_IKFK_" if module_type=="IKFK" else "_IK_")
    members=[];identities=set()
    def remember(node):
        identity=_guide_ik_uuid(node)
        if identity not in identities:
            identities.add(identity);members.append({"uuid":identity,"type":cmds.nodeType(node)})
        return identity
    constraint_scope=_constraint_context(prefix,remember)
    graph=_IKLengthGraph(prefix,remember)
    def transform(label,parent):
        identity=remember(cmds.createNode("transform",name=prefix+label,skipSelect=True))
        cmds.parent(_rig_module_node(identity),_rig_module_node(parent),relative=True)
        return identity
    def control(label,normal,radius):
        node=cmds.circle(name=":"+label,normal=normal,radius=radius,constructionHistory=False)[0]
        identity=remember(node)
        for shape in cmds.listRelatives(node,shapes=True,fullPath=True) or []:remember(shape)
        return identity
    undo_name="BuildXMatrixIK_"+uuid.uuid4().hex
    try:
        try:
            with _tool_action(undo_name):
                root_id=control(names["root"],(1,0,0),plan["size"]*1.7);root=_rig_module_node(root_id)
                cmds.matchTransform(root,plan["root_joint"],position=True,rotation=True)
                cmds.addAttr(root,longName="globalScale",attributeType="double",defaultValue=1,minValue=.001,keyable=True)
                for axis in "XYZ":cmds.connectAttr(root+".globalScale",root+".scale"+axis)
                group=transform("DRIVERS",root_id)
                root_scale_node=graph.node("decomposeMatrix","rootWorldScale")
                graph.connect(root+".worldMatrix[0]",root_scale_node+".inputMatrix")
                base_id=None
                if module_type=="IKFK":
                    base_zero=transform("BASE_ZERO",root_id)
                    cmds.xform(_rig_module_node(base_zero),worldSpace=True,matrix=plan["snapshots"][0]["world"])
                    base_id=control(names["base"],(1,0,0),plan["size"]*.8)
                    cmds.parent(_rig_module_node(base_id),_rig_module_node(base_zero),relative=True)
                    # BASE scale must not scale solver bones. Preserve ROOT's
                    # deliberate global scale while taking BASE position/rotation.
                    base_rt=_rig_module_x_pick(graph,_rig_module_node(base_id)+".worldMatrix[0]","baseRigid")
                    scale=graph.node("composeMatrix","baseGlobalScale")
                    graph.connect(root_scale_node+".outputScale",scale+".inputScale")
                    matrix=graph.node("multMatrix","baseDriverSpace")
                    for i,plug in enumerate((scale+".outputMatrix",base_rt,root+".worldInverseMatrix[0]")):graph.connect(plug,matrix+".matrixIn[{}]".format(i))
                    graph.connect(matrix+".matrixSum",_rig_module_node(group)+".offsetParentMatrix")
                drivers=[]
                units=_rig_module_units()
                for i,frame in enumerate(frames):
                    parent=drivers[-1] if drivers else group
                    identity=remember(cmds.createNode("joint",name=prefix+"xDriver{:02d}_JNT".format(i+1),parent=_rig_module_node(parent),skipSelect=True))
                    driver=_rig_module_node(identity)
                    cmds.setAttr(driver+".segmentScaleCompensate",False)
                    cmds.xform(driver,worldSpace=True,matrix=frame)
                    cmds.makeIdentity(driver,apply=True,translate=False,rotate=True,scale=False)
                    for axis in "XYZ":cmds.setAttr(driver+".scale"+axis,1)
                    if i:
                        cmds.setAttr(driver+".translateX",_rig_module_unit_value("translateX",lengths[i-1],{"angle":"deg","linear":"cm"},units))
                        for axis in "YZ":cmds.setAttr(driver+".translate"+axis,0)
                    cmds.setAttr(driver+".preferredAngle",0,0,0,type="double3")
                    drivers.append(identity)
                outputs=[]
                for i,identity in enumerate(drivers):
                    buffer=transform("ORIENT_BUFFER{:02d}".format(i+1) if i<2 else "TIP_OUTPUT",identity)
                    if i<2:
                        shape=cmds.createNode("locator",name=prefix+"ORIENT_BUFFER{:02d}Shape".format(i+1),parent=_rig_module_node(buffer),skipSelect=True)
                        remember(shape)
                        for axis in "XYZ":cmds.setAttr(shape+".localScale"+axis,plan["size"]*.25)
                    offset=_rig_module_matrix_product(bind[i],_rig_module_matrix_inverse(_rig_module_length_matrix(_rig_module_node(identity))))
                    cmds.setAttr(_rig_module_node(buffer)+".offsetParentMatrix",*offset,type="matrix")
                    outputs.append(buffer)
                end_zero=transform("END_ZERO",root_id)
                cmds.matchTransform(_rig_module_node(end_zero),plan["joints"][2],position=True,rotation=True)
                end_id=control(names["end"],(0,1,0),plan["size"])
                cmds.parent(_rig_module_node(end_id),_rig_module_node(end_zero),relative=True)
                pole_zero=transform("POLE_ZERO",root_id)
                cmds.xform(_rig_module_node(pole_zero),worldSpace=True,translation=plan["pole"]["position"])
                pole_id=control(names["pole"],(0,0,1),plan["size"]*.6)
                cmds.parent(_rig_module_node(pole_id),_rig_module_node(pole_zero),relative=True)
                handle,effector=cmds.ikHandle(name=prefix+"HANDLE",startJoint=_rig_module_node(drivers[0]),endEffector=_rig_module_node(drivers[2]),solver="ikRPsolver")
                handle_id,effector_id=remember(handle),remember(effector)
                cmds.parent(_rig_module_node(handle_id),_rig_module_node(end_id),absolute=True)
                cmds.setAttr(_rig_module_node(handle_id)+".visibility",False)
                pole_constraint=remember(_constraint_command('poleVectorConstraint',_rig_module_node(pole_id),_rig_module_node(handle_id),name=prefix+"poleConstraint", _scope=constraint_scope)[0])
                end_constraint=remember(_constraint_command('orientConstraint',_rig_module_node(end_id),_rig_module_node(drivers[2]),maintainOffset=True,name=prefix+"endOrient", _scope=constraint_scope)[0])
                cmds.setAttr(_rig_module_node(group)+".visibility",False)
                ik={"solver":"x_translate_v1","drivers":drivers,"driver_group":group,"end":end_id,"pole":pole_id,
                    "handle":handle_id,"effector":effector_id,"pole_constraint":pole_constraint,"end_constraint":end_constraint,
                    "orientation_buffers":outputs[:2],"outputs":outputs}
                if base_id:ik["base"]=base_id
                ik["length_system"]=_rig_module_install_lengths({"root":root_id,"ik":ik},prefix,remember)
                blend=_rig_module_build_ikfk(plan,root_id,end_zero,pole_zero,base_id,names,prefix,control,remember) if module_type=="IKFK" else None
                poses=_rig_module_x_pose_blend(graph,root,outputs,blend)
                rows=[]
                for i,joint in enumerate(plan["joints"]):
                    # Bind scale is constant. ROOT supplies deliberate global
                    # scale once when root-space rigid poses return to world.
                    bind_scale=math.sqrt(sum(v*v for v in bind[i][:3]))
                    scale_matrix=graph.node("composeMatrix","bindScaleMatrix"+str(i))
                    cmds.setAttr(scale_matrix+".inputScale",bind_scale,bind_scale,bind_scale,type="double3")
                    output=graph.node("multMatrix","sourceMatrix"+str(i))
                    local_inverse=_rig_module_x_local_inverse(graph,joint,"source"+str(i))
                    if isinstance(local_inverse,str):graph.connect(local_inverse,output+".matrixIn[0]")
                    else:cmds.setAttr(output+".matrixIn[0]",*local_inverse,type="matrix")
                    graph.connect(scale_matrix+".outputMatrix",output+".matrixIn[1]")
                    graph.connect(poses[i],output+".matrixIn[2]")
                    graph.connect(root+".worldMatrix[0]",output+".matrixIn[3]")
                    parent=(cmds.listRelatives(joint,parent=True,fullPath=True) or [None])[0]
                    if parent:graph.connect(parent+".worldInverseMatrix[0]",output+".matrixIn[4]")
                    # Use the actual DAG parent's inverse, never the driven
                    # node's parentInverseMatrix (which already includes OPM).
                    graph.connect(output+".matrixSum",joint+".offsetParentMatrix")
                    out_id=_guide_ik_uuid(output)
                    rows.append({"joint":_guide_ik_uuid(joint),"control":drivers[i],"offset":drivers[i-1] if i else group,
                                 "constraints":[out_id],"inputs":{"offsetParentMatrix":{"node":out_id,"attribute":"matrixSum"}}})
                ik["matrix_nodes"]=graph.members[:]
                meta_id=remember(cmds.createNode("network",name=prefix+"META",skipSelect=True));meta=_rig_module_node(meta_id)
                for attribute in (_RIG_MODULE_TAG,_RIG_MODULE_STATE,"moduleType","moduleName"):cmds.addAttr(meta,longName=attribute,dataType="string")
                for attribute,value in ((_RIG_MODULE_TAG,"1"),("moduleType",module_type),("moduleName",plan["name"])):cmds.setAttr(meta+"."+attribute,value,type="string")
                for attribute in ("sources","members"):cmds.addAttr(meta,longName=attribute,attributeType="message",multi=True)
                cmds.addAttr(meta,longName="root",attributeType="message");cmds.connectAttr(root+".message",meta+".root")
                for i,row in enumerate(plan["snapshots"]):cmds.connectAttr(_rig_module_node(row["uuid"])+".message",meta+".sources[{}]".format(i))
                for i,row in enumerate(members):
                    if row["uuid"]!=meta_id:cmds.connectAttr(_rig_module_node(row["uuid"])+".message",meta+".members[{}]".format(i))
                state={"schema":1,"type":module_type,"name":plan["name"],"meta":meta_id,"root":root_id,"members":members,
                       "joints":plan["snapshots"],"controls":rows,"ui_controls":[end_id,pole_id],"control_size":plan["size"],
                       "pole_distance":float(pole_distance),"ik":ik}
                if blend:state.update({"ikfk":blend,"ui_controls":blend["fk_controls"]+[base_id,end_id,pole_id]})
                state["controller_names"]={role:_rig_module_node(identity).rsplit("|",1)[-1] for role,identity in _rig_module_controller_roles(state).items()}
                if constraint_scope["node"]:state["constraint_group"]=constraint_scope["node"]
                state["defaults"],state["default_units"]=_rig_module_capture_defaults(state),_rig_module_units()
                _rig_module_finish_outputs(meta, state, parent_output,parent_method,parent_follow_scale);_rig_module_verify_pose(plan["snapshots"]);_rig_module_read(meta)
        except Exception as exc:
            if cmds.undoInfo(query=True,undoName=True)==undo_name:
                cmds.undo();raise RuntimeError("X-axis matrix IK build was rolled back; original joints were kept: {}".format(exc)) from exc
            raise
    finally:_restore_locator_view_selection(selection)
    result={"module":meta,"root":_rig_module_node(root_id),"end_controller":_rig_module_node(end_id),"pole_controller":_rig_module_node(pole_id),
            "handle":_rig_module_node(handle_id),"joint_count":3,"owned_node_count":len(members),
            "outputs":_rig_module_output_rows(meta,state),"input":_rig_module_node(state["input"])}
    if blend:result.update({"base_controller":_rig_module_node(base_id),"fk_controllers":[_rig_module_node(identity) for identity in blend["fk_controls"]]})
    return result


def _rig_module_build_ikfk(plan,root_id,end_zero,pole_zero,base_id,names,prefix,control,remember):
    root=_rig_module_node(root_id)
    cmds.addAttr(root,longName="ikFkBlend",attributeType="double",defaultValue=0,minValue=0,maxValue=1,keyable=True)
    group=remember(cmds.group(empty=True,name=prefix+"FK_CONTROLS"))
    cmds.parent(_rig_module_node(group),root,relative=True)
    fk=[]
    for index,joint in enumerate(plan["joints"]):
        zero=remember(cmds.group(empty=True,name=prefix+"FK{:02d}_ZERO".format(index+1)))
        cmds.parent(_rig_module_node(zero),_rig_module_node(fk[-1] if fk else group),relative=True)
        # Both targets must have the same bind scale before creating the
        # weighted scale constraints; copying position/rotation alone is insufficient.
        cmds.xform(_rig_module_node(zero),worldSpace=True,matrix=plan["snapshots"][index]["world"])
        identity=control(names[_guide_ik_uuid(joint)],(1,0,0),plan["size"])
        cmds.parent(_rig_module_node(identity),_rig_module_node(zero),relative=True)
        cmds.setAttr(_rig_module_node(identity)+".rotateOrder",cmds.getAttr(joint+".rotateOrder"))
        fk.append(identity)
    graph=_IKLengthGraph(prefix,remember)
    weight=graph.clamp(root+".ikFkBlend",0,1,"blendRange")
    reverse=graph.sum(1,weight,True,"fkWeight")
    fk_visible=graph.choose(weight,1,1,0,operation=4,label="fkVisible")
    ik_visible=graph.choose(weight,0,1,0,label="ikVisible")
    graph.connect(fk_visible,_rig_module_node(group)+".visibility")
    base_zero=(cmds.listRelatives(_rig_module_node(base_id),parent=True,fullPath=True) or [None])[0]
    for zero in (_rig_module_node(end_zero),_rig_module_node(pole_zero),base_zero):graph.connect(ik_visible,zero+".visibility")
    return {"version":1,"attribute":"ikFkBlend","fk_group":group,"fk_controls":fk,
            "reverse":_guide_ik_uuid(reverse.split(".",1)[0]),"weight_node":_guide_ik_uuid(weight.split(".",1)[0]),"nodes":graph.members}


def build_ikfk_module(first_joint,second_joint,third_joint,name="IKFK",control_size=1.0,pole_distance=1.0,controller_names=None,parent_output=None,parent_method="matrix_parent",parent_follow_scale=True):
    """One owned three-joint module: 0 FK, 1 IK, native weighted constraints."""
    return build_ik_module(first_joint,second_joint,third_joint,name,control_size,pole_distance,controller_names,_module_type="IKFK",parent_output=parent_output,parent_method=parent_method,parent_follow_scale=parent_follow_scale)


def _rig_module_ikfk_state(module):
    meta,state=_rig_module_read(module)
    if state["type"]!="IKFK":raise ValueError("Select an IK/FK module in Scene modules.")
    return meta,state


def _rig_module_ikfk_preflight(writes,keyframe):
    for node,attributes in writes:
        if cmds.referenceQuery(node,isNodeReferenced=True) or (cmds.lockNode(node,query=True,lock=True) or [False])[0]:
            raise ValueError("Controller is locked or referenced: {}".format(node))
        for attribute in attributes:
            plug=node+"."+attribute
            compound=attribute.rstrip("XYZ")
            inputs=_rig_module_inputs(plug)
            if compound!=attribute:inputs+=_rig_module_inputs(node+"."+compound)
            if (cmds.getAttr(plug,lock=True) or cmds.getAttr(node+"."+compound,lock=True)
                    or (inputs and (not keyframe or any(cmds.nodeType(p.split(".",1)[0]) not in ("animCurveTA","animCurveTL","animCurveTU") for p in inputs)))):
                raise ValueError("{} is locked or driven. Enable keying for direct time animation; other drivers are kept.".format(plug))


def _rig_module_ikfk_write(node,attribute,value,keyframe):
    if keyframe:
        cmds.setKeyframe(node,attribute=attribute,value=float(value))
        # Explicit value keys need a DG reevaluation before decomposing a
        # child control or checking the newly switched output pose.
        cmds.dgdirty(node)
    else:cmds.setAttr(node+"."+attribute,float(value))


def set_ikfk_blend(module,value,keyframe=False):
    """Set/animate the blend only; use switch_ikfk for pose matching."""
    _meta,state=_rig_module_ikfk_state(module)
    value=float(value)
    if not math.isfinite(value) or not 0<=value<=1:raise ValueError("IK/FK blend must be between 0 and 1.")
    root=_rig_module_node(state["root"])
    _rig_module_ikfk_preflight([(root,["ikFkBlend"])],keyframe)
    _rig_module_require_undo()
    undo_name="SetIKFKBlend_"+uuid.uuid4().hex
    try:
        with _tool_action(undo_name):_rig_module_ikfk_write(root,"ikFkBlend",value,keyframe)
    except Exception as exc:
        if cmds.undoInfo(query=True,undoName=True)==undo_name:
            cmds.undo();raise RuntimeError("IK/FK blend was rolled back: {}".format(exc)) from exc
        raise
    return value


def _rig_module_ikfk_match_matrix(node,world,keyframe,world_position=None):
    """Decompose using Maya, in the control's actual parent/rotation/pivot space."""
    parent=(cmds.listRelatives(node,parent=True,fullPath=True) or [None])[0]
    temporary=cmds.createNode("transform",name=":rtkIKFKMatch_"+uuid.uuid4().hex,skipSelect=True,
                              **({"parent":parent} if parent else {}))
    try:
        for attribute in ("rotateOrder","rotateAxis","rotatePivot","rotatePivotTranslate","scalePivot","scalePivotTranslate","inheritsTransform"):
            if cmds.attributeQuery(attribute,node=node,exists=True):
                value=cmds.getAttr(node+"."+attribute)
                if isinstance(value,(list,tuple)):
                    if len(value)==1 and isinstance(value[0],(list,tuple)):value=value[0]
                    cmds.setAttr(temporary+"."+attribute,*value,type="double3")
                else:cmds.setAttr(temporary+"."+attribute,value)
        cmds.xform(temporary,worldSpace=True,matrix=world)
        if world_position is not None:cmds.xform(temporary,worldSpace=True,translation=world_position)
        values={base+axis:cmds.getAttr(temporary+"."+base+axis) for base in ("translate","rotate","scale") for axis in "XYZ"}
    finally:
        if cmds.objExists(temporary):cmds.delete(temporary)
    for attribute,value in values.items():_rig_module_ikfk_write(node,attribute,value,keyframe)


def _rig_module_ikfk_orientation_matrix(node,world):
    """Match position/rotation while retaining the control's current world scale."""
    current=cmds.xform(node,query=True,worldSpace=True,matrix=True)
    result=list(world)
    for start in (0,4,8):
        target_scale=math.sqrt(sum(result[start+i]**2 for i in range(3)))
        current_scale=math.sqrt(sum(current[start+i]**2 for i in range(3)))
        if min(target_scale,current_scale)<=1e-8:raise ValueError("Cannot match a zero-scale pose.")
        for i in range(3):result[start+i]*=current_scale/target_scale
    return result


def _rig_module_ikfk_pole(points,current,multiplier):
    """Use the visible bend plane, retaining the old pole side for straight poses."""
    try:return calculate_guide_ik_pole(*points,distance_scale=multiplier)["position"]
    except ValueError:
        a,b,c=points
        axis=[c[i]-a[i] for i in range(3)];length=math.sqrt(sum(v*v for v in axis))
        if length<=1e-8:raise ValueError("Overlapping first/end joints cannot be matched to RP IK.")
        axis=[v/length for v in axis]
        delta=[current[i]-a[i] for i in range(3)]
        projected=sum(delta[i]*axis[i] for i in range(3))
        direction=[delta[i]-projected*axis[i] for i in range(3)]
        norm=math.sqrt(sum(v*v for v in direction))
        if norm<=1e-8:raise ValueError("Move POLE away from the straight joint axis before matching.")
        return [b[i]+direction[i]/norm*length*multiplier for i in range(3)]


def switch_ikfk(module,mode,keyframe=False):
    """Snapshot output joints, match the destination controls, switch, verify pose.

    A pose the RP solver cannot reproduce is rolled back, never accepted with a jump.
    Keying touches only this frame; this action does not bake a frame range.
    """
    _meta,state=_rig_module_ikfk_state(module)
    mode=str(mode).upper()
    if mode not in ("FK","IK"):raise ValueError("Choose FK or IK.")
    root=_rig_module_node(state["root"])
    controls=([_rig_module_node(identity) for identity in state["ikfk"]["fk_controls"]] if mode=="FK"
              else [_rig_module_node(state["ik"][name]) for name in ("base","end","pole")])
    channels=[base+axis for base in ("translate","rotate","scale") for axis in "XYZ"]
    writes=[(node,channels) for node in controls]+[(root,["ikFkBlend"])]
    end=_rig_module_node(state["ik"]["end"])
    if mode=="IK":writes.append((end,list(_RIG_MODULE_IK_LENGTH_ATTRS)))
    _rig_module_ikfk_preflight(writes,keyframe)
    snapshots=[{"uuid":row["uuid"],"world":cmds.xform(_rig_module_node(row["uuid"]),query=True,worldSpace=True,matrix=True),
                **{a:cmds.getAttr(_rig_module_node(row["uuid"])+"."+a) for a in ("jointOrient","rotateAxis","segmentScaleCompensate")}} for row in state["joints"]]
    matrices=[row["world"] for row in snapshots]
    if mode=="IK":
        _rig_module_check_matrix(root)
        for row in snapshots:_rig_module_check_matrix(_rig_module_node(row["uuid"]))
        # Use the linear-typed position query for distances/pole calculation;
        # do not interpret untyped matrix translation entries as UI units.
        points=[cmds.xform(_rig_module_node(row["uuid"]),query=True,worldSpace=True,translation=True) for row in snapshots]
        root_world=cmds.xform(root,query=True,worldSpace=True,matrix=True)
        root_scale=math.sqrt(sum(v*v for v in root_world[:3]))
        units=_rig_module_units()
        rest=state["ik"]["length_system"]["rest_lengths"]
        lengths=[math.sqrt(sum((points[i+1][j]-points[i][j])**2 for j in range(3)))/root_scale for i in range(2)]
        adjustments=[_rig_module_unit_value("translateX",length,units,{"angle":"deg","linear":"cm"})/original-1 for length,original in zip(lengths,rest)]
        if any(not -.95<=value<=10 for value in adjustments):raise ValueError("This pose exceeds the IK upper/lower slide range.")
        pole_position=_rig_module_ikfk_pole(points,cmds.xform(controls[2],query=True,worldSpace=True,translation=True),state.get("pole_distance",1))
        pole_matrix=cmds.xform(controls[2],query=True,worldSpace=True,matrix=True)
        match_matrices=[_rig_module_ikfk_orientation_matrix(controls[0],matrices[0]),
                        _rig_module_ikfk_orientation_matrix(controls[1],matrices[2]),pole_matrix]
        settings={"stretch":1,"antiPop":0,"upperSlide":adjustments[0],"lowerSlide":adjustments[1],"slide":0,"poleLock":0}
    else:match_matrices=matrices
    _rig_module_require_undo()
    selection=cmds.ls(selection=True,long=True) or []
    undo_name="MatchSwitchIKFK_"+uuid.uuid4().hex
    try:
        try:
            with _tool_action(undo_name):
                for node,world in zip(controls,match_matrices):
                    _rig_module_ikfk_match_matrix(node,world,keyframe,pole_position if mode=="IK" and node==controls[2] else None)
                if mode=="IK":
                    for attribute,value in settings.items():_rig_module_ikfk_write(end,attribute,value,keyframe)
                _rig_module_ikfk_write(root,"ikFkBlend",1 if mode=="IK" else 0,keyframe)
                _rig_module_verify_pose(snapshots)
        except Exception as exc:
            if cmds.undoInfo(query=True,undoName=True)==undo_name:
                cmds.undo()
                raise RuntimeError("IK/FK matching was rolled back; current pose was kept. RP IK cannot reproduce every FK twist/scale pose. {}".format(exc)) from exc
            raise
    finally:_restore_locator_view_selection(selection)
    return {"mode":mode,"controllers":controls,"keyed":bool(keyframe)}


class _CollapsibleRigGroup(QtWidgets.QFrame):
    """Hide the body rather than disable it; expanding keeps all inputs intact."""
    def __init__(self, title, expanded=True, parent=None):
        super(_CollapsibleRigGroup,self).__init__(parent)
        # A titled QGroupBox reserves a title margin/padding even when our body
        # is hidden. Use a frame with a single compact, full-width header.
        self.setObjectName("RigModuleGroup")
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Maximum)
        self.setAccessibleName(title)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        self.header = QtWidgets.QToolButton()
        self.header.setObjectName("RigModuleHeader")
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Fixed)
        self.header.setAutoRaise(True)
        self.header.setToolTip("Click to expand or collapse this section. Scene nodes are unchanged.")
        self.body = QtWidgets.QWidget()
        self.body.setObjectName("RigModuleBody")
        body_policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Minimum)
        body_policy.setRetainSizeWhenHidden(False)
        self.body.setSizePolicy(body_policy)
        layout.addWidget(self.header)
        layout.addWidget(self.body)
        self.header.toggled.connect(self.set_expanded)
        self.set_expanded(expanded)

    def set_expanded(self, expanded):
        self.header.setChecked(bool(expanded))
        self.header.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)
        self.body.setVisible(bool(expanded))


class _IKLengthPanel(QtWidgets.QGroupBox):
    def __init__(self,owner):
        super(_IKLengthPanel,self).__init__("Selected IK · length controls (translation)")
        self.owner,self.fields = owner,{}
        form = QtWidgets.QFormLayout(self)
        note = QtWidgets.QLabel("Choose an IK in Scene modules, then Load. New builds multiply default solver translateX; joint scale is not driven. Upper/lower slide: 0.1 = +10% rest length. Slide redistributes length; poleLock 1 pins the bend to POLE. Older saved rigs need Remove/rebuild for the X-axis matrix backend.")
        note.setWordWrap(True)
        note.setProperty("role","muted")
        form.addRow(note)
        tips = {"stretch":"0: original/manual lengths; 1: extend bones to reach END. Does not auto-shrink.",
                "antiPop":"Soft IK near full extension. 1 uses a 20% soft zone; combine with stretch 1 to reach END.",
                "upperSlide":"Fractional upper rest-length adjustment: 0.1 = +10%, -0.1 = -10%.",
                "lowerSlide":"Fractional lower rest-length adjustment: 0.1 = +10%, -0.1 = -10%.",
                "slide":"Transfer length between bones. Positive lengthens upper; negative lengthens lower. Total stays constant.",
                "poleLock":"Blend lengths toward start-to-POLE and POLE-to-END distances. 1 pins the bend joint to POLE."}
        for name,(default,minimum,maximum) in _RIG_MODULE_IK_LENGTH_ATTRS.items():
            field = QtWidgets.QDoubleSpinBox()
            field.setRange(minimum,maximum)
            field.setDecimals(3)
            field.setSingleStep(.05)
            field.setValue(default)
            field.setToolTip(tips[name])
            self.fields[name] = field
            form.addRow(name+":",field)
        self.key = QtWidgets.QCheckBox("Key values on current frame")
        form.addRow(self.key)
        row = QtWidgets.QHBoxLayout()
        for label,callback in (("Load values",self._load),("Apply values",self._apply),("Select END attributes",self._select)):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        form.addRow(row)
        upgrade = QtWidgets.QPushButton("Add length controls to older IK · keeps legacy solver")
        upgrade.clicked.connect(self._upgrade)
        form.addRow(upgrade)

    def _state(self):
        meta,state = self.owner._state()
        if state["type"] not in ("IK3","IKFK"):raise ValueError("Select a Three-Bone IK or IK/FK module in Scene modules.")
        if not state["ik"].get("length_system"):raise ValueError("Add length features to this older IK first.")
        return meta,state

    def _load(self,*_args):
        try:
            _meta,state = self._state()
            end = _rig_module_node(state["ik"]["end"])
            for name,field in self.fields.items():field.setValue(cmds.getAttr(end+"."+name))
            self.owner.status.setText("Loaded length controls from {}.".format(end))
        except (ValueError,RuntimeError) as exc:self.owner._error(exc)

    def _apply(self,*_args):
        try:
            meta,_state = self._state()
            set_ik_length_controls(meta,{name:field.value() for name,field in self.fields.items()},self.key.isChecked())
            self.owner.status.setText("Applied IK length values through bone translation. Global scale was kept.")
        except (ValueError,RuntimeError) as exc:self.owner._error(exc)

    def _select(self,*_args):
        try:
            _meta,state = self._state()
            cmds.select(_rig_module_node(state["ik"]["end"]),replace=True)
            self.owner.status.setText("END selected: stretch, antiPop, upperSlide, lowerSlide, slide, poleLock and length readouts are in the Channel Box.")
        except (ValueError,RuntimeError) as exc:self.owner._error(exc)

    def _upgrade(self,*_args):
        try:
            meta,_state = self.owner._state()
            result = enable_ik_length_features(meta)
            self._load()
            self.owner.status.setText("Length controls available. Older saved graphs keep their solver; Remove/rebuild to replace old scale constraints with X-axis matrix outputs.")
        except (ValueError,RuntimeError) as exc:self.owner._error(exc)


# Root and reverse-foot modules use the same scene ownership and action manager.
_RIG_MODULE_FOOT_ATTRS = {
    'footRoll':(0.,None,None),'ballBreak':(45.,.001,None),'toeStraight':(70.,.002,None),
    'heelRoll':(0.,None,None),'ballRoll':(0.,None,None),'toeRoll':(0.,None,None),
    'bank':(0.,None,None),'heelTwist':(0.,None,None),'toeTwist':(0.,None,None),
    'toeTap':(0.,None,None)}


def foot_roll_solution(roll, ball_break=45., toe_straight=70.):
    """Degree-valued reference; runtime uses the equivalent native DG graph."""
    if not all(math.isfinite(float(v)) for v in (roll,ball_break,toe_straight)):
        raise ValueError('Foot roll values must be finite.')
    threshold=max(.001,float(ball_break));span=max(.001,float(toe_straight)-threshold)
    positive=max(0.,float(roll));t=max(0.,min(1.,(positive-threshold)/span))
    ball=min(positive,threshold)*(1.-t)
    return {'heel':min(0.,float(roll)),'ball':ball,'toe':positive-ball}


def _rig_module_extra_names(state):
    if state['type']=='FOOT':return [_rig_module_node(state['foot'][key]) for key in ('ankle','ball')]
    return [_rig_module_node(row['uuid']) for row in state['joints']]


def _rig_module_extra_channels(state,role):
    return list(_RIG_MODULE_FOOT_ATTRS) if state['type']=='FOOT' and state['foot']['mode']=='IK' and role=='ankle' else []


def _rig_module_validate_extra(state,kinds,sources):
    roles=state['roles'];rows=state['controls']
    expected={'root','placement'} if state['type']=='ROOT' else {'root','ankle','ball'}
    if (set(roles)!=expected or roles['root']!=state['root'] or len(set(roles.values()))!=len(roles)
            or any(kinds.get(v)!='transform' for v in roles.values())
            or state['ui_controls']!=list(roles.values()) or len(rows)!=len(sources)
            or {row['joint'] for row in rows}!=set(sources)):
        raise ValueError('Invalid Root/Foot controller ownership')
    allowed={'network','transform','nurbsCurve'}
    if state['type']=='ROOT':
        if (len(sources)>1 or (sources and state.get('root_joint')!=sources[0])
                or (not sources and state.get('root_joint'))):
            raise ValueError('Invalid optional Root joint source')
        if sources:
            allowed.update({'multMatrix','composeMatrix'})
            if rows[0]['control']!=roles['placement'] or rows[0]['offset']!=roles['root']:
                raise ValueError('Invalid Root joint attachment')
    else:
        foot=state['foot']
        if (foot['mode'] not in ('IK','FK') or foot['bank_sign'] not in (-1,1)
                or foot['up_axis'] not in ('Y','Z') or foot['ankle']==foot['ball']
                or set(sources)!={foot['ball']}|({foot['ankle']} if foot['drive_ankle'] else set())
                or kinds.get(foot['ankle_target'])!='transform'):
            raise ValueError('Invalid Foot setup')
        allowed.update({'multMatrix','composeMatrix','clamp','condition','multiplyDivide','plusMinusAverage','unitConversion'})
    for row in rows:
        if (kinds.get(row['control'])!='transform' or kinds.get(row['offset'])!='transform'
                or len(row['constraints'])!=1 or kinds.get(row['constraints'][0])!='multMatrix'
                or row['inputs']!={'offsetParentMatrix':{'node':row['constraints'][0],'attribute':'matrixSum'}}):
            raise ValueError('Invalid Root/Foot matrix driver')
    return allowed


def _rig_module_extra_transform(value,optional=False):
    if not value and optional:return None
    node=_resolve_hierarchy_root(value)
    if not cmds.objectType(node,isAType='transform'):
        raise ValueError('Choose a transform, locator or joint: '+str(value))
    if len(cmds.ls(node,long=True,allPaths=True) or [])!=1:raise ValueError('Instanced transforms are not supported: '+node)
    return node


def _rig_module_extra_parent(parent,joints=()):
    parent=_rig_module_extra_transform(parent,True)
    if parent:
        _rig_module_check_matrix(parent)
        if any(parent==j or parent.startswith(j+'|') for j in joints):
            raise ValueError('Parent control must be outside the joints driven by this module.')
    return parent


def plan_root_module(placement=None,name='Root',control_size=10.,root_joint=None):
    """Optional skeleton root follows Root_ctrl; placement defaults to its bind frame."""
    size=float(control_size)
    if not math.isfinite(size) or size<=0:raise ValueError('Control size must be positive.')
    _rig_module_validate_name(name)
    joint=_guide_ik_joint(root_joint) if root_joint else None
    snapshots=plan_fk_module([joint],False,size,name)['snapshots'] if joint else []
    if joint:
        if not cmds.attributeQuery('offsetParentMatrix',node=joint,exists=True):
            raise ValueError('Root joint attachment requires Maya 2020 or newer.')
        plug=joint+'.offsetParentMatrix'
        if cmds.getAttr(plug,lock=True) or _rig_module_inputs(plug) or not cmds.getAttr(plug,settable=True):
            raise ValueError('Root joint offsetParentMatrix is already driven or locked: '+joint)
    node=_rig_module_extra_transform(placement,True) or joint
    matrix=_rig_module_check_matrix(node) if node else _rig_module_matrix_identity()
    # The placement supplies a rigid frame; globalScale starts at one.
    for row in range(3):
        length=math.sqrt(sum(v*v for v in matrix[row*4:row*4+3]))
        matrix[row*4:row*4+3]=[v/length for v in matrix[row*4:row*4+3]]
    return {'name':name,'size':size,'matrix':matrix,'snapshots':snapshots,'root_joint':joint,
            'placement':_rig_module_extra_transform(placement,True)}


def _rig_module_foot_frame(ankle,toe,heel,up_axis):
    def norm(v):
        length=math.sqrt(sum(x*x for x in v))
        if length<1e-8:raise ValueError('Heel and toe must define a foot direction away from the up axis.')
        return [x/length for x in v]
    def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    up=[0.,1.,0.] if up_axis=='Y' else [0.,0.,1.]
    forward=[toe[i]-heel[i] for i in range(3)]
    x=norm(cross(up,forward));z=norm(cross(x,up))
    return x+[0.]+up+[0.]+z+[0.]+list(ankle)+[1.]


def plan_foot_module(ankle,ball,toe_tip=None,left_pivot=None,right_pivot=None,heel_pivot=None,
                     mode='IK',name='Foot',control_size=1.,parent_control=None,drive_ankle=True,up_axis='Y',bank_sign=1):
    mode=str(mode).upper();up_axis=str(up_axis).upper()
    if mode not in ('IK','FK') or up_axis not in ('Y','Z') or bank_sign not in (-1,1):
        raise ValueError('Choose IK/FK, Y/Z up and bank sign +1/-1.')
    ankle,ball=_guide_ik_joint(ankle),_guide_ik_joint(ball)
    if (cmds.listRelatives(ball,parent=True,fullPath=True) or [None])[0]!=ankle:
        raise ValueError('Ball must be a direct child of ankle.')
    joints=[ankle,ball] if drive_ankle else [ball]
    plan=plan_fk_module(joints,False,control_size,name)
    for joint in joints:
        if not cmds.attributeQuery('offsetParentMatrix',node=joint,exists=True):raise ValueError('Foot modules require Maya 2020 or newer.')
        plug=joint+'.offsetParentMatrix'
        if cmds.getAttr(plug,lock=True) or _rig_module_inputs(plug) or not cmds.getAttr(plug,settable=True):
            raise ValueError('Joint offsetParentMatrix is already driven or locked: '+joint)
    points={};guides={}
    for key,value in (('toe_tip',toe_tip),('left_pivot',left_pivot),('right_pivot',right_pivot),('heel_pivot',heel_pivot)):
        if mode=='IK' or value:
            node=_rig_module_extra_transform(value);guides[key]=_guide_ik_uuid(node)
            points[key]=list(cmds.xform(node,query=True,worldSpace=True,matrix=True))[12:15]
            if not all(math.isfinite(float(v)) for v in points[key]):raise ValueError('Pivot position is invalid: '+node)
    ankle_matrix=list(cmds.xform(ankle,query=True,worldSpace=True,matrix=True))
    ball_matrix=list(cmds.xform(ball,query=True,worldSpace=True,matrix=True))
    if sum((a-b)**2 for a,b in zip(ankle_matrix[12:15],ball_matrix[12:15]))<1e-12:
        raise ValueError('Ankle and ball positions must differ.')
    frame=_rig_module_foot_frame(ankle_matrix[12:15],points['toe_tip'],points['heel_pivot'],up_axis) if mode=='IK' else ankle_matrix[:]
    if mode=='IK':
        width=sum((points['right_pivot'][i]-points['left_pivot'][i])*frame[i] for i in range(3))
        if abs(width)<1e-6:raise ValueError('Left and right pivots must define separate sides of the foot.')
        if sum((points['toe_tip'][i]-ball_matrix[12+i])**2 for i in range(3))<1e-12:
            raise ValueError('Toe tip must be beyond the ball, not at its position.')
    plan.update(ankle=ankle,ball=ball,mode=mode,frame=frame,guides=guides,points=points,up_axis=up_axis,
                bank_sign=bank_sign,drive_ankle=bool(drive_ankle),parent_control=_rig_module_extra_parent(parent_control,joints))
    return plan


def _rig_module_extra_graph(prefix,remember):
    graph=_IKLengthGraph(prefix,remember)
    # Foot numbers are degrees in every scene angle unit. Native angle plugs
    # use radians internally; keep that conversion separate from length math.
    def connect(source,destination):
        cmds.connectAttr(source,destination)
        for plug in _rig_module_inputs(destination):
            node=plug.split('.',1)[0]
            if cmds.nodeType(node)=='unitConversion':
                identity=remember(node)
                if identity not in graph.members:graph.members.append(identity)
                if cmds.getAttr(destination,type=True)=='doubleAngle':
                    cmds.setAttr(node+'.conversionFactor',math.pi/180.)
    graph.connect=connect
    return graph


def _rig_module_foot_roll_graph(graph,ctrl,pivots,tap_zero,bank_sign):
    r=ctrl+'.footRoll';br=ctrl+'.ballBreak';straight=ctrl+'.toeStraight'
    pos=graph.choose(r,0,r,0,label='positiveRoll')
    threshold=graph.choose(br,.001,br,.001,label='safeBallBreak')
    span=graph.sum(straight,threshold,True,'rollSpan')
    safe=graph.choose(span,.001,span,.001,label='safeRollSpan')
    phase=graph.clamp(graph.math(graph.sum(pos,threshold,True,'rollPastBall'),safe,2,'rollPhase'),0,1,'rollBlend')
    before=graph.choose(pos,threshold,threshold,pos,label='ballPeak')
    ball=graph.math(before,graph.sum(1,phase,True,'ballFade'),1,'ballAuto')
    toe=graph.sum(pos,ball,True,'toeAuto')
    heel=graph.choose(r,0,0,r,label='heelAuto')
    for role,auto,manual in (('heel',heel,'heelRoll'),('ball',ball,'ballRoll'),('toe',toe,'toeRoll')):
        graph.connect(graph.sum(auto,ctrl+'.'+manual,label=role+'RollSum'),pivots[role]+'.rotateX')
    positive=graph.choose(ctrl+'.bank',0,ctrl+'.bank',0,label='bankPositive')
    negative=graph.choose(ctrl+'.bank',0,0,ctrl+'.bank',label='bankNegative')
    for role,angle in (('left',positive),('right',negative)):
        graph.connect(graph.math(angle,bank_sign,1,role+'BankSign'),pivots[role]+'.rotateZ')
    graph.connect(ctrl+'.heelTwist',pivots['heel']+'.rotateY')
    graph.connect(ctrl+'.toeTwist',pivots['toe']+'.rotateY')
    graph.connect(ctrl+'.toeTap',tap_zero+'.rotateX')


def _rig_module_build_extra(plan,kind,controller_names,parent_output=None,parent_method="matrix_parent",parent_follow_scale=True):
    inputs=[] if kind=='ROOT' else [plan['ankle'],plan['ball']]
    names=_rig_module_names(kind,inputs,controller_names)
    _rig_module_require_undo();selection=cmds.ls(selection=True,long=True) or []
    prefix=':'+_rig_module_validate_name(plan['name'])+'_'+kind+'_'
    members=[];identities=set();undo_name='Build'+kind+'Module_'+uuid.uuid4().hex
    def remember(node):
        identity=_guide_ik_uuid(node)
        if identity not in identities:
            identities.add(identity);members.append({'uuid':identity,'type':cmds.nodeType(node)})
        return identity
    def transform(label,parent=None,matrix=None):
        node=cmds.createNode('transform',name=prefix+label,skipSelect=True,
                             **({'parent':_rig_module_node(parent)} if parent else {}))
        identity=remember(node)
        if matrix is not None:cmds.xform(node,worldSpace=True,matrix=matrix)
        return identity
    def control(role,parent,size):
        node=cmds.circle(name=':'+names[role],normal=(0,1,0),radius=size,constructionHistory=False)[0]
        identity=remember(node)
        for shape in cmds.listRelatives(node,shapes=True,fullPath=True) or []:remember(shape)
        cmds.parent(_rig_module_node(identity),_rig_module_node(parent),relative=True)
        return identity
    try:
        try:
            with _tool_action(undo_name):
                parent=_guide_ik_uuid(plan['parent_control']) if plan.get('parent_control') else None
                zero=transform('MAIN_ZERO' if kind=='ROOT' else 'ROOT_ZERO',parent,plan['matrix'] if kind=='ROOT' else plan['frame'])
                root_id=control('root',zero,plan['size']*1.7);root=_rig_module_node(root_id)
                cmds.addAttr(root,longName='globalScale',attributeType='double',defaultValue=1.,minValue=.001,keyable=True)
                for axis in 'XYZ':cmds.connectAttr(root+'.globalScale',root+'.scale'+axis)
                roles={'root':root_id};rows=[];foot=None
                if kind=='ROOT':
                    roles['placement']=control('placement',root_id,plan['size'])
                    if plan['snapshots']:
                        graph=_rig_module_extra_graph(prefix,remember)
                        outputs={record['uuid']:roles['placement'] for record in plan['snapshots']}
                else:
                    graph=_rig_module_extra_graph(prefix,remember)
                    ankle_matrix=list(cmds.xform(plan['ankle'],query=True,worldSpace=True,matrix=True))
                    ball_matrix=list(cmds.xform(plan['ball'],query=True,worldSpace=True,matrix=True))
                    ankle_zero=transform('ANKLE_ZERO',root_id,plan['frame'] if plan['mode']=='IK' else ankle_matrix)
                    ankle_id=control('ankle',ankle_zero,plan['size']);roles['ankle']=ankle_id
                    ankle_ctrl=_rig_module_node(ankle_id)
                    if plan['mode']=='IK':
                        for attr,(default,minimum,maximum) in _RIG_MODULE_FOOT_ATTRS.items():
                            kw={'minValue':minimum} if minimum is not None else {}
                            cmds.addAttr(ankle_ctrl,longName=attr,attributeType='double',defaultValue=default,keyable=True,**kw)
                        pivots={};parent=ankle_id
                        for role,key in (('heel','heel_pivot'),('left','left_pivot'),('right','right_pivot'),('toe','toe_tip'),('ball',None)):
                            matrix=plan['frame'][:];matrix[12:15]=plan['points'][key] if key else ball_matrix[12:15]
                            parent=transform(role.upper()+'_PIVOT',parent,matrix);pivots[role]=_rig_module_node(parent)
                        ankle_output=transform('ANKLE_TARGET',parent,ankle_matrix)
                        # A toe tap rotates at the ball about the ground-frame X,
                        # before the joint-aligned ball ZERO, independent of JO.
                        tap_frame=plan['frame'][:];tap_frame[12:15]=ball_matrix[12:15]
                        tap_zero=transform('TOE_TAP',_guide_ik_uuid(pivots['toe']),tap_frame)
                        ball_zero=transform('BALL_ZERO',tap_zero,ball_matrix)
                        _rig_module_foot_roll_graph(graph,ankle_ctrl,pivots,_rig_module_node(tap_zero),plan['bank_sign'])
                    else:
                        ankle_output=transform('ANKLE_TARGET',ankle_id,ankle_matrix)
                        ball_zero=transform('BALL_ZERO',ankle_id,ball_matrix)
                    ball_id=control('ball',ball_zero,plan['size']*.6);roles['ball']=ball_id
                    outputs={_guide_ik_uuid(plan['ankle']):ankle_output,_guide_ik_uuid(plan['ball']):ball_id}
                    foot={'mode':plan['mode'],'ankle':_guide_ik_uuid(plan['ankle']),'ball':_guide_ik_uuid(plan['ball']),
                          'guides':plan['guides'],'drive_ankle':plan['drive_ankle'],'up_axis':plan['up_axis'],
                          'bank_sign':plan['bank_sign'],'ankle_target':ankle_output,
                          'parent_control':_guide_ik_uuid(plan['parent_control']) if plan['parent_control'] else None}
                for record in plan['snapshots']:
                    joint=_rig_module_node(record['uuid']);output_id=outputs[record['uuid']];output_node=_rig_module_node(output_id)
                    offset=_rig_module_matrix_product(_rig_module_matrix_value(joint+'.worldMatrix[0]'),
                                                     _rig_module_matrix_inverse(_rig_module_matrix_value(output_node+'.worldMatrix[0]')))
                    matrix=graph.node('multMatrix','sourceMatrix');inverse=_rig_module_x_local_inverse(graph,joint,'rootLocal' if kind=='ROOT' else 'footLocal')
                    if isinstance(inverse,str):graph.connect(inverse,matrix+'.matrixIn[0]')
                    else:cmds.setAttr(matrix+'.matrixIn[0]',*inverse,type='matrix')
                    cmds.setAttr(matrix+'.matrixIn[1]',*offset,type='matrix')
                    graph.connect(output_node+'.worldMatrix[0]',matrix+'.matrixIn[2]')
                    actual_parent=(cmds.listRelatives(joint,parent=True,fullPath=True) or [None])[0]
                    if actual_parent:graph.connect(actual_parent+'.worldInverseMatrix[0]',matrix+'.matrixIn[3]')
                    graph.connect(matrix+'.matrixSum',joint+'.offsetParentMatrix');matrix_id=_guide_ik_uuid(matrix)
                    rows.append({'joint':record['uuid'],'control':output_id,'offset':root_id,'constraints':[matrix_id],
                                 'inputs':{'offsetParentMatrix':{'node':matrix_id,'attribute':'matrixSum'}}})
                meta_id=remember(cmds.createNode('network',name=prefix+'META',skipSelect=True));meta=_rig_module_node(meta_id)
                for attribute in (_RIG_MODULE_TAG,_RIG_MODULE_STATE,'moduleType','moduleName'):
                    cmds.addAttr(meta,longName=attribute,dataType='string')
                for attribute,value in ((_RIG_MODULE_TAG,'1'),('moduleType',kind),('moduleName',plan['name'])):
                    cmds.setAttr(meta+'.'+attribute,value,type='string')
                for attribute in ('sources','members'):cmds.addAttr(meta,longName=attribute,attributeType='message',multi=True)
                cmds.addAttr(meta,longName='root',attributeType='message');cmds.connectAttr(root+'.message',meta+'.root')
                for i,record in enumerate(plan['snapshots']):cmds.connectAttr(_rig_module_node(record['uuid'])+'.message',meta+'.sources[{}]'.format(i))
                for i,record in enumerate(members):
                    if record['uuid']!=meta_id:cmds.connectAttr(_rig_module_node(record['uuid'])+'.message',meta+'.members[{}]'.format(i))
                state={'schema':1,'type':kind,'name':plan['name'],'meta':meta_id,'root':root_id,'members':members,
                       'joints':plan['snapshots'],'controls':rows,'control_size':plan['size'],'roles':roles,'ui_controls':list(roles.values())}
                if foot:state['foot']=foot
                if kind=='ROOT' and plan['root_joint']:state['root_joint']=_guide_ik_uuid(plan['root_joint'])
                if kind=='ROOT' and plan.get('placement'):state['root_placement']=_guide_ik_uuid(plan['placement'])
                state['controller_names']={role:_rig_module_node(identity).rsplit('|',1)[-1] for role,identity in roles.items()}
                state['defaults'],state['default_units']=_rig_module_capture_defaults(state),_rig_module_units()
                _rig_module_finish_outputs(meta, state, parent_output,parent_method,parent_follow_scale)
                _rig_module_verify_pose(plan['snapshots']);_rig_module_read(meta)
        except Exception as exc:
            if cmds.undoInfo(query=True,undoName=True)==undo_name:
                cmds.undo();raise RuntimeError(kind+' build was rolled back: '+str(exc)) from exc
            raise
    finally:_restore_locator_view_selection(selection)
    result={'module':meta,'root':_rig_module_node(root_id),'controls':[_rig_module_node(v) for v in roles.values()],
            'joint_count':len(rows),'owned_node_count':len(members),
            'outputs':_rig_module_output_rows(meta,state),'input':_rig_module_node(state['input'])}
    if kind=='ROOT':result.update(main_controller=result['root'],root_controller=_rig_module_node(roles['placement']),
                                  attachment=_rig_module_node(roles['placement']),root_joint=plan['root_joint'],
                                  placement_output=_rig_module_node(state['outputs'][0]['node']))
    else:result.update(ankle_target=_rig_module_node(foot['ankle_target']),ankle_controller=_rig_module_node(roles['ankle']),ball_controller=_rig_module_node(roles['ball']))
    return result


def build_root_module(placement=None,name='Root',control_size=10.,controller_names=None,root_joint=None,parent_output=None,parent_method="matrix_parent",parent_follow_scale=True):
    return _rig_module_build_extra(plan_root_module(placement,name,control_size,root_joint),'ROOT',controller_names,parent_output,parent_method,parent_follow_scale)


def build_foot_module(ankle,ball,toe_tip=None,left_pivot=None,right_pivot=None,heel_pivot=None,
                      mode='IK',name='Foot',control_size=1.,parent_control=None,drive_ankle=True,up_axis='Y',bank_sign=1,controller_names=None,parent_output=None,parent_method="matrix_parent",parent_follow_scale=True):
    plan=plan_foot_module(ankle,ball,toe_tip,left_pivot,right_pivot,heel_pivot,mode,name,control_size,parent_control,drive_ankle,up_axis,bank_sign)
    return _rig_module_build_extra(plan,'FOOT',controller_names,parent_output,parent_method,parent_follow_scale)


def _rig_module_extra_mirror(state,search,replace):
    if state['type']=='ROOT':
        if not state.get('root_joint'):
            raise ValueError('Root is a central placement module; mirror limb/Foot modules instead, or bind a side-specific Root joint.')
        source=[_rig_module_node(state['root_joint'])]
        target=[_guide_ik_joint(_pd_mirror_object(source[0],search,replace,require_change=True))]
        placement=_rig_module_node(state['root_placement']) if state.get('root_placement') else None
        if placement and search in placement.rsplit('|',1)[-1]:
            placement=_pd_mirror_object(placement,search,replace,require_change=True)
        name=_pd_mirror_name(state['name'],search,replace)
        if name==state['name']:name=_rig_module_joint_label(target[0])+'_Root'
        options={'placement':placement,'root_joint':target[0],'name':name,'control_size':state['control_size']}
        plan_root_module(**options)
        overrides={}
        for role,identity in state['roles'].items():
            current=_rig_module_node(identity).rsplit('|',1)[-1];mirrored=_pd_mirror_name(current,search,replace)
            if current!=mirrored:overrides[role]=mirrored
        _rig_module_names('ROOT',target,overrides)
        return dict(type='ROOT',source_joints=source,joints=target,controller_names=overrides,**options)
    foot=state['foot']
    source=[_rig_module_node(foot[k]) for k in ('ankle','ball')]
    target=[_guide_ik_joint(_pd_mirror_object(n,search,replace,require_change=True)) for n in source]
    guides={k:_pd_mirror_object(_rig_module_node(v),search,replace,require_change=True) for k,v in foot['guides'].items()}
    parent=_rig_module_node(foot['parent_control']) if foot['parent_control'] else None
    # Central Root_ctrl stays shared; side-specific parents require a counterpart.
    if parent and search in parent.rsplit('|',1)[-1]:parent=_pd_mirror_object(parent,search,replace,require_change=True)
    name=_pd_mirror_name(state['name'],search,replace)
    if name==state['name']:name=_rig_module_joint_label(target[0])+'_Foot'
    kw=dict(guides,mode=foot['mode'],name=name,control_size=state['control_size'],parent_control=parent,
            drive_ankle=foot['drive_ankle'],up_axis=foot['up_axis'],bank_sign=-foot['bank_sign'])
    plan_foot_module(*target,**kw)
    overrides={}
    for role,identity in state['roles'].items():
        current=_rig_module_node(identity).rsplit('|',1)[-1];mirrored=_pd_mirror_name(current,search,replace)
        if current!=mirrored:overrides[role]=mirrored
    _rig_module_names('FOOT',target,overrides)
    return dict(type='FOOT',source_joints=source,joints=target,controller_names=overrides,**kw)


class _IKModulePanel(QtWidgets.QWidget):
    def __init__(self, owner, module_type="IK3"):
        super(_IKModulePanel,self).__init__(owner)
        self.owner = owner
        self.module_type=module_type
        form = QtWidgets.QFormLayout(self)
        form.setContentsMargins(10,8,10,10)
        self.name = QtWidgets.QLineEdit("IKFK" if module_type=="IKFK" else "IK")
        form.addRow("Module name:", self.name)
        self.joints = []
        for label in ("First joint:","Second joint:","Third joint:"):
            field = QtWidgets.QLineEdit()
            field.setPlaceholderText("Consecutive chain joint")
            self.joints.append(field)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(field,1)
            get = QtWidgets.QPushButton("Get selected")
            get.clicked.connect(lambda _checked=False,field=field:self._get(field))
            row.addWidget(get)
            form.addRow(label,row)
        get_chain = QtWidgets.QPushButton("Get chain from selected first joint")
        get_chain.clicked.connect(self._get_chain)
        form.addRow(get_chain)
        self.size, self.pole_distance = QtWidgets.QDoubleSpinBox(), QtWidgets.QDoubleSpinBox()
        for field in (self.size,self.pole_distance):
            field.setRange(.001,10000)
            field.setDecimals(3)
            field.setValue(1)
        form.addRow("Control size:",self.size)
        form.addRow("Pole distance multiplier:",self.pole_distance)
        self.controller_names = _RigControllerNames(self)
        form.addRow(self.controller_names)
        load_names = QtWidgets.QPushButton("Load all IK/FK controller name fields" if module_type=="IKFK" else "Load ROOT / END / POLE name fields")
        load_names.clicked.connect(self._load_name_fields)
        form.addRow(load_names)
        note = QtWidgets.QLabel("Three X-aligned solver joints / two orientation locator buffers. Lengths drive second/third translateX; matrix offsets preserve source joint frames. Animate END/POLE; ROOT.globalScale scales the module. Existing rigs keep their saved graph until removed and rebuilt.")
        note.setWordWrap(True)
        note.setProperty("role","muted")
        form.addRow(note)
        row = QtWidgets.QHBoxLayout()
        validate = QtWidgets.QPushButton("Validate IK joints")
        validate.clicked.connect(self._preview)
        build = QtWidgets.QPushButton("Build IK/FK module" if module_type=="IKFK" else "Build Three-Bone IK module")
        build.setProperty("role","primary")
        build.clicked.connect(self._build)
        row.addWidget(validate)
        row.addWidget(build)
        form.addRow(row)
        remove = QtWidgets.QPushButton("Remove selected scene module · keep current pose")
        remove.clicked.connect(owner._remove)
        form.addRow(remove)
        self.length_panel = _IKLengthPanel(owner)
        form.addRow(self.length_panel)

    def _get(self,field):
        try:
            selected = cmds.ls(selection=True,long=True) or []
            if len(selected) != 1: raise ValueError("Select one joint for this field.")
            field.setText(_guide_ik_joint(selected[0]))
        except (ValueError,RuntimeError) as exc: self.owner._error(exc)

    def _get_chain(self,*_args):
        try:
            selected = cmds.ls(selection=True,long=True) or []
            if len(selected) != 1: raise ValueError("Select the first joint of the IK chain.")
            chain = [_guide_ik_joint(selected[0])]
            for _index in range(2):
                children = cmds.listRelatives(chain[-1],children=True,type="joint",fullPath=True) or []
                if len(children) != 1: raise ValueError("Chain branches or ends early. Get the three joints individually.")
                chain.append(children[0])
            for field,joint in zip(self.joints,chain): field.setText(joint)
        except (ValueError,RuntimeError) as exc: self.owner._error(exc)

    def _args(self):
        return [field.text().strip() for field in self.joints]+[self.name.text(),self.size.value(),self.pole_distance.value()]

    def _load_name_fields(self,*_args):
        try:
            plan = plan_ik_module(*self._args())
            self.controller_names.sync(self.module_type,plan["joints"])
            self.controller_names.custom.setChecked(True)
            self.owner.status.setText("Controller name fields loaded. Blank fields use joint-based names.")
        except (ValueError,RuntimeError) as exc: self.owner._error(exc)

    def _preview(self,*_args):
        try:
            plan = plan_ik_module(*self._args())
            self.controller_names.sync(self.module_type,plan["joints"])
            _rig_module_names(self.module_type,plan["joints"],self.controller_names.values())
            self.owner.status.setText("Ready: 3 joints, end and pole controls. Pole at {}.".format(tuple(round(v,3) for v in plan["pole"]["position"])))
        except (ValueError,RuntimeError) as exc: self.owner._error(exc)

    def _build(self,*_args):
        try:
            plan = plan_ik_module(*self._args())
            self.controller_names.sync(self.module_type,plan["joints"])
            builder=build_ikfk_module if self.module_type=="IKFK" else build_ik_module
            result = builder(*self._args(),controller_names=self.controller_names.values())
            self.owner._refresh(result["module"])
            self.owner.status.setText("Built IK/FK: ROOT.ikFkBlend 0 = FK, 1 = IK. Match & switch to keep the current pose." if self.module_type=="IKFK" else "Built Three-Bone IK. Select module controls for END/POLE, or ROOT for globalScale.")
        except (ValueError,RuntimeError) as exc: self.owner._error(exc)


class _IKFKModulePanel(_IKModulePanel):
    def __init__(self,owner):
        super(_IKFKModulePanel,self).__init__(owner,"IKFK")
        form=self.layout()
        note=QtWidgets.QLabel("ROOT.ikFkBlend: 0 = FK, 1 = IK. Intermediate values blend local rotations and explicit bone lengths. Match & switch keeps the current joint pose, or rolls back if it cannot match. IK BASE positions the start of the IK chain.")
        note.setWordWrap(True)
        form.addRow(note)
        self.blend=QtWidgets.QDoubleSpinBox()
        self.blend.setRange(0,1);self.blend.setDecimals(3);self.blend.setSingleStep(.1)
        form.addRow("Selected rig · IK/FK blend:",self.blend)
        self.key_switch=QtWidgets.QCheckBox("Key matched controls / blend on current frame")
        form.addRow(self.key_switch)
        row=QtWidgets.QHBoxLayout()
        for label,callback in (("Load blend",self._load_blend),("Apply blend",self._apply_blend)):
            button=QtWidgets.QPushButton(label);button.clicked.connect(callback);row.addWidget(button)
        form.addRow(row)
        row=QtWidgets.QHBoxLayout()
        for mode in ("FK","IK"):
            button=QtWidgets.QPushButton("Match & switch to "+mode)
            button.clicked.connect(lambda _checked=False,mode=mode:self._switch(mode))
            row.addWidget(button)
        form.addRow(row)

    def _load_blend(self,*_args):
        try:
            meta,_state=self.owner._state();_meta,state=_rig_module_ikfk_state(meta)
            self.blend.setValue(cmds.getAttr(_rig_module_node(state["root"])+".ikFkBlend"))
        except (ValueError,RuntimeError) as exc:self.owner._error(exc)

    def _apply_blend(self,*_args):
        try:
            meta,_state=self.owner._state()
            set_ikfk_blend(meta,self.blend.value(),self.key_switch.isChecked())
            self.owner.status.setText("Applied blend: 0 FK, 1 IK. Use Match & switch when the destination controls need matching.")
        except (ValueError,RuntimeError) as exc:self.owner._error(exc)

    def _switch(self,mode):
        try:
            meta,_state=self.owner._state();switch_ikfk(meta,mode,self.key_switch.isChecked())
            self.blend.setValue(1 if mode=="IK" else 0)
            self.owner.status.setText("Matched controls and switched to {}; current joint pose was verified.".format(mode))
        except (ValueError,RuntimeError) as exc:self.owner._error(exc)


class _RootFootModulePanel(QtWidgets.QWidget):
    """Compact input pickers; shared manager owns reset/mirror/remove actions."""
    def __init__(self,owner,kind):
        super(_RootFootModulePanel,self).__init__(owner)
        self.owner,self.kind=owner,kind;self.fields={};self.guide_rows=[]
        form=QtWidgets.QFormLayout(self);form.setContentsMargins(10,8,10,10)
        self.name=QtWidgets.QLineEdit('Root' if kind=='ROOT' else 'Foot_L');form.addRow('Module name:',self.name)
        self.mode=QtWidgets.QComboBox();self.mode.addItems(['IK','FK'])
        if kind=='FOOT':form.addRow('Foot type:',self.mode)
        entries=(('root_joint','Root joint (optional)'),('placement','Placement (optional)')) if kind=='ROOT' else (
            ('ankle','Ankle joint'),('ball','Ball joint'),('toe_tip','Toe tip locator'),
            ('left_pivot','Left side pivot'),('right_pivot','Right side pivot'),('heel_pivot','Heel pivot'),
            ('parent_control','Parent control (optional)'))
        for key,label in entries:
            field=QtWidgets.QLineEdit();self.fields[key]=field
            if key=='root_joint':field.setPlaceholderText('Optional skeleton root; blank creates placement controls only')
            elif kind=='ROOT' and key=='placement':field.setPlaceholderText('Blank uses root joint frame, or world origin')
            row=QtWidgets.QHBoxLayout();row.addWidget(field,1)
            button=QtWidgets.QPushButton('Get');row.addWidget(button)
            button.clicked.connect(lambda _checked=False,k=key:self.pick(k))
            clear=QtWidgets.QPushButton('Clear');row.addWidget(clear);clear.clicked.connect(field.clear)
            form.addRow(label+':',row)
            if key in ('toe_tip','left_pivot','right_pivot','heel_pivot'):self.guide_rows.append((field,button,clear))
        self.size=QtWidgets.QDoubleSpinBox();self.size.setRange(.001,10000);self.size.setDecimals(3)
        self.size.setValue(10 if kind=='ROOT' else 1);form.addRow('Control size:',self.size)
        if kind=='FOOT':
            self.drive_ankle=QtWidgets.QCheckBox('Drive ankle joint (off when a leg rig owns ankle)');self.drive_ankle.setChecked(True)
            form.addRow(self.drive_ankle)
            self.up=QtWidgets.QComboBox();self.up.addItems(['Y','Z']);form.addRow('Ground up axis:',self.up)
            self.bank_sign=QtWidgets.QComboBox();self.bank_sign.addItem('+1',1);self.bank_sign.addItem('-1',-1)
            form.addRow('Bank direction:',self.bank_sign)
            self.mode.currentIndexChanged.connect(self.mode_changed)
        self.names=_RigControllerNames(self);form.addRow(self.names)
        load=QtWidgets.QPushButton('Load controller name fields');load.clicked.connect(self.load_names);form.addRow(load)
        row=QtWidgets.QHBoxLayout()
        for label,action in (('Validate',False),('Build '+('Root' if kind=='ROOT' else 'Foot')+' module',True)):
            button=QtWidgets.QPushButton(label);button.clicked.connect(lambda _checked=False,build=action:self.execute(build));row.addWidget(button)
        form.addRow(row)
        text=('Main_ctrl > Root_ctrl. Optional root joint follows Root_ctrl with its current offset and inherits Main.globalScale. '
              'Blank Placement uses the joint frame. Joint hierarchy and local channels are preserved; attach other module roots under Root_ctrl.' if kind=='ROOT' else
              'IK: foot roll, heel/ball/toe, side bank, twists and toe tap. FK: ankle and ball controls. '
              'IK needs four pivot guides; only their positions are sampled. Parent control can be Root_ctrl. '
              'With Drive ankle off, use the ankle target output for the leg IK attachment.')
        note=QtWidgets.QLabel(text);note.setWordWrap(True);form.addRow(note)
        if kind=='ROOT':self.names.sync('ROOT',[])
        else:self.mode_changed()

    def mode_changed(self,*_):
        for widgets in self.guide_rows:
            for widget in widgets:widget.setEnabled(self.mode.currentText()=='IK')

    def pick(self,key):
        try:
            selected=cmds.ls(selection=True,long=True) or []
            if len(selected)!=1:raise ValueError('Select exactly one object for '+key.replace('_',' ')+'.')
            node=_guide_ik_joint(selected[0]) if key in ('root_joint','ankle','ball') else _rig_module_extra_transform(selected[0])
            self.fields[key].setText(node)
        except (ValueError,RuntimeError) as exc:self.owner._error(exc)

    def settings(self):
        kw=dict(name=self.name.text().strip(),control_size=self.size.value())
        if self.kind=='ROOT':kw.update({key:self.fields[key].text().strip() or None for key in ('placement','root_joint')})
        else:
            kw.update({k:f.text().strip() or None for k,f in self.fields.items()})
            if self.mode.currentText()=='FK':
                for k in ('toe_tip','left_pivot','right_pivot','heel_pivot'):kw[k]=None
            kw.update(mode=self.mode.currentText(),drive_ankle=self.drive_ankle.isChecked(),up_axis=self.up.currentText(),bank_sign=self.bank_sign.currentData())
        return kw

    def load_names(self,*_):
        try:
            inputs=[] if self.kind=='ROOT' else [_guide_ik_joint(self.fields[k].text()) for k in ('ankle','ball')]
            self.names.sync(self.kind,inputs)
        except (ValueError,RuntimeError) as exc:self.owner._error(exc)

    def execute(self,build):
        try:
            kw=self.settings();planner=plan_root_module if self.kind=='ROOT' else plan_foot_module
            plan=planner(**kw)
            inputs=[] if self.kind=='ROOT' else [plan['ankle'],plan['ball']]
            self.names.sync(self.kind,inputs);_rig_module_names(self.kind,inputs,self.names.values())
            if not build:
                self.owner.status.setText('Ready: '+('Main_ctrl > Root_ctrl; {} root joint output(s).'.format(len(plan['snapshots'])) if self.kind=='ROOT' else self.mode.currentText()+' foot; {} joint outputs.'.format(len(plan['snapshots']))));return
            builder=build_root_module if self.kind=='ROOT' else build_foot_module
            result=builder(controller_names=self.names.values(),**kw);self.owner._refresh(result['module'])
            self.owner.status.setText('Built '+('Root: {} joint output(s); Main.globalScale controls the placement hierarchy.'.format(result['joint_count']) if self.kind=='ROOT' else self.mode.currentText()+' foot. Select ankle / foot control for roll attributes.'))
        except (ValueError,RuntimeError) as exc:self.owner._error(exc)


class _RigModulesPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(_RigModulesPanel, self).__init__(parent)
        self.setObjectName("ModularRigPage")
        self.setAttribute(QtCore.Qt.WA_StyledBackground,True)
        self.setProperty("qtPanel", True)
        self.joint_ids = []
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(8)
        layout.setAlignment(QtCore.Qt.AlignTop)
        self.root_group=_CollapsibleRigGroup('Root module',expanded=False)
        self.root_panel=_RootFootModulePanel(self,'ROOT')
        root_layout=QtWidgets.QVBoxLayout(self.root_group.body);root_layout.setContentsMargins(0,0,0,0);root_layout.addWidget(self.root_panel)
        layout.addWidget(self.root_group)
        self.fk_group = build = _CollapsibleRigGroup("FK module", expanded=False)
        form = QtWidgets.QFormLayout(build.body)
        form.setContentsMargins(10,8,10,10)
        self.module_name = QtWidgets.QLineEdit("FK")
        form.addRow("Module name:", self.module_name)
        self.root_joint = QtWidgets.QLineEdit()
        self.root_joint.setPlaceholderText("Root joint; or use a connected selection below")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.root_joint, 1)
        get = QtWidgets.QPushButton("Get root")
        get.clicked.connect(self._get_root)
        row.addWidget(get)
        form.addRow("Root joint:", row)
        self.children = QtWidgets.QCheckBox("Include descendant joints (branches supported)")
        self.children.setChecked(True)
        form.addRow(self.children)
        row = QtWidgets.QHBoxLayout()
        selected = QtWidgets.QPushButton("Use selected joints")
        selected.clicked.connect(self._get_selection)
        clear = QtWidgets.QPushButton("Clear selection list")
        clear.clicked.connect(self._clear)
        row.addWidget(selected)
        row.addWidget(clear)
        form.addRow(row)
        self.joints_list = QtWidgets.QListWidget()
        self.joints_list.setMaximumHeight(135)
        form.addRow("Explicit joints:", self.joints_list)
        self.size = QtWidgets.QDoubleSpinBox()
        self.size.setRange(0.001, 10000)
        self.size.setDecimals(3)
        self.size.setValue(1)
        form.addRow("Control size:", self.size)
        self.controller_names = _RigControllerNames(self)
        form.addRow(self.controller_names)
        load_names = QtWidgets.QPushButton("Load controller name fields from joints")
        load_names.clicked.connect(self._load_name_fields)
        form.addRow(load_names)
        row = QtWidgets.QHBoxLayout()
        preview = QtWidgets.QPushButton("Validate joints")
        preview.clicked.connect(self._preview)
        generate = QtWidgets.QPushButton("Build FK module")
        generate.setProperty("role", "primary")
        generate.clicked.connect(self._build)
        row.addWidget(preview)
        row.addWidget(generate)
        form.addRow(row)
        layout.addWidget(build)
        self.ik_group = _CollapsibleRigGroup("Three-Bone IK module", expanded=True)
        self.ik_panel = _IKModulePanel(self)
        ik_layout = QtWidgets.QVBoxLayout(self.ik_group.body)
        ik_layout.setContentsMargins(0,0,0,0)
        ik_layout.addWidget(self.ik_panel)
        layout.addWidget(self.ik_group)
        self.ikfk_group=_CollapsibleRigGroup("IK/FK blend module",expanded=False)
        self.ikfk_panel=_IKFKModulePanel(self)
        ikfk_layout=QtWidgets.QVBoxLayout(self.ikfk_group.body)
        ikfk_layout.setContentsMargins(0,0,0,0);ikfk_layout.addWidget(self.ikfk_panel)
        layout.addWidget(self.ikfk_group)
        self.foot_group=_CollapsibleRigGroup('Foot module',expanded=False)
        self.foot_panel=_RootFootModulePanel(self,'FOOT')
        foot_layout=QtWidgets.QVBoxLayout(self.foot_group.body);foot_layout.setContentsMargins(0,0,0,0);foot_layout.addWidget(self.foot_panel)
        layout.addWidget(self.foot_group)
        self.manage_group = manage = _CollapsibleRigGroup("Scene modules", expanded=True)
        form = QtWidgets.QFormLayout(manage.body)
        form.setContentsMargins(10,8,10,10)
        self.modules = QtWidgets.QComboBox()
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self._refresh)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.modules, 1)
        row.addWidget(refresh)
        form.addRow("Module:", row)
        row = QtWidgets.QHBoxLayout()
        root = QtWidgets.QPushButton("Select root / globalScale")
        root.clicked.connect(self._select_root)
        controls = QtWidgets.QPushButton("Select module controls")
        controls.clicked.connect(self._select_controls)
        row.addWidget(root)
        row.addWidget(controls)
        form.addRow(row)
        output=QtWidgets.QPushButton('Select Root control / Foot ankle target')
        output.clicked.connect(self._select_attachment);form.addRow(output)
        self.output_group = _CollapsibleRigGroup('Module outputs / attachment', expanded=True)
        output_form = QtWidgets.QFormLayout(self.output_group.body)
        output_form.setContentsMargins(8, 6, 8, 8)
        self.outputs_table = QtWidgets.QTableWidget(0, 3)
        self.outputs_table.setObjectName('RigModuleOutputs')
        self.outputs_table.setHorizontalHeaderLabels(['Output', 'Driven joint', ''])
        self.outputs_table.verticalHeader().hide()
        self.outputs_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.outputs_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.outputs_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.outputs_table.setAlternatingRowColors(True)
        self.outputs_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.outputs_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.outputs_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.outputs_table.setMinimumHeight(120)
        self.outputs_table.setMaximumHeight(230)
        output_form.addRow(self.outputs_table)
        row = QtWidgets.QHBoxLayout()
        publish = QtWidgets.QPushButton('Publish outputs · saved rigs')
        publish.clicked.connect(self._publish_outputs)
        use_output = QtWidgets.QPushButton('Use output as parent')
        use_output.clicked.connect(self._use_output)
        row.addWidget(publish); row.addWidget(use_output)
        output_form.addRow(row)
        self.parent_output_uuid = None
        self.parent_output = QtWidgets.QLineEdit()
        self.parent_output.setReadOnly(True)
        self.parent_output.setPlaceholderText('Choose a published OUTPUT transform')
        get_output = QtWidgets.QPushButton('Get selected')
        get_output.clicked.connect(self._get_parent_output)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.parent_output, 1); row.addWidget(get_output)
        output_form.addRow('Parent output:', row)
        row = QtWidgets.QHBoxLayout()
        attach = QtWidgets.QPushButton('Attach selected module · keep offset')
        attach.clicked.connect(self._attach_output)
        detach = QtWidgets.QPushButton('Detach · keep pose')
        detach.clicked.connect(self._detach_output)
        row.addWidget(attach); row.addWidget(detach)
        output_form.addRow(row)
        self.attachment_status = QtWidgets.QLabel()
        self.attachment_status.setWordWrap(True)
        output_form.addRow(self.attachment_status)
        note = QtWidgets.QLabel('Choose the parent module and an output, click Use output as parent, then choose the child module above and Attach. Outputs include the final IK/FK blend and global scale.')
        note.setWordWrap(True); note.setProperty('role', 'muted')
        output_form.addRow(note)
        form.addRow(self.output_group)
        self.modules.currentIndexChanged.connect(self._refresh_outputs)
        self.module_rows=QtWidgets.QTableWidget(0,3)
        self.module_rows.setObjectName('RigModuleRows')
        self.module_rows.setAlternatingRowColors(True)
        self.module_rows.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.module_rows.setHorizontalHeaderLabels(['Module','Type','Actions'])
        self.module_rows.verticalHeader().hide()
        self.module_rows.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.module_rows.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch)
        self.module_rows.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.ResizeToContents)
        self.module_rows.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.ResizeToContents)
        self.module_rows.setMinimumHeight(160)
        form.addRow(self.module_rows)
        remove = QtWidgets.QPushButton("Delete selected rig · keep current joint pose")
        remove.clicked.connect(self._remove)
        form.addRow(remove)
        self.include_default_root = QtWidgets.QCheckBox("Include ROOT / globalScale")
        self.key_default = QtWidgets.QCheckBox("Key default on current frame")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.include_default_root)
        row.addWidget(self.key_default)
        form.addRow("Go to Default:",row)
        row = QtWidgets.QHBoxLayout()
        reset = QtWidgets.QPushButton("Go to Default")
        reset.clicked.connect(self._goto_default)
        store = QtWidgets.QPushButton("Store current as default")
        store.clicked.connect(self._store_default)
        row.addWidget(reset)
        row.addWidget(store)
        form.addRow(row)
        self.existing_names = _RigControllerNames(self)
        self.names_module_uuid = None
        form.addRow(self.existing_names)
        row = QtWidgets.QHBoxLayout()
        load_names = QtWidgets.QPushButton("Load selected rig name fields")
        load_names.clicked.connect(self._load_existing_names)
        rename = QtWidgets.QPushButton("Apply controller names")
        rename.clicked.connect(self._rename_controls)
        row.addWidget(load_names)
        row.addWidget(rename)
        form.addRow(row)
        self.mirror_search,self.mirror_replace = QtWidgets.QLineEdit("_L"),QtWidgets.QLineEdit("_R")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.mirror_search)
        row.addWidget(self.mirror_replace)
        swap = QtWidgets.QPushButton("Swap")
        swap.clicked.connect(self._swap_mirror)
        row.addWidget(swap)
        form.addRow("Mirror Search / Replace:",row)
        row = QtWidgets.QHBoxLayout()
        preview = QtWidgets.QPushButton("Preview mirror joints")
        preview.clicked.connect(self._mirror_preview)
        mirror = QtWidgets.QPushButton("Mirror rig to matching joints")
        mirror.clicked.connect(self._mirror)
        row.addWidget(preview)
        row.addWidget(mirror)
        form.addRow(row)
        note = QtWidgets.QLabel("Animate the module controls; globalScale scales the rig uniformly. Detach child modules before deleting their parent. Removal keeps the current frame; it does not bake animation.")
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        form.addRow(note)
        layout.addWidget(manage)
        self.status = QtWidgets.QLabel("Root, FK, Three-Bone IK, IK/FK and Foot modules. Click section headers to collapse/expand.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        self._refresh()

    def _error(self, exc):
        self.status.setText(str(exc))
        cmds.warning(str(exc))

    def _clear(self, *_args):
        self.joint_ids = []
        self.joints_list.clear()

    def _get_root(self, *_args):
        try:
            nodes = cmds.ls(selection=True, long=True) or []
            if len(nodes) != 1: raise ValueError("Select one root joint.")
            self.root_joint.setText(_guide_ik_joint(nodes[0]))
            self._clear()
        except (ValueError, RuntimeError) as exc: self._error(exc)

    def _get_selection(self, *_args):
        try:
            joints = [_guide_ik_joint(node) for node in cmds.ls(selection=True, long=True) or []]
            if not joints: raise ValueError("Select joints first.")
            self.joint_ids = [_guide_ik_uuid(node) for node in joints]
            self.joints_list.clear()
            self.joints_list.addItems(joints)
            self.root_joint.clear()
            self.children.setChecked(False)
            self.status.setText("{} explicit joints loaded. Include every intermediate joint; selection order is not important.".format(len(joints)))
        except (ValueError, RuntimeError) as exc: self._error(exc)

    def _inputs(self):
        return [_rig_module_node(identity) for identity in self.joint_ids] if self.joint_ids else [self.root_joint.text().strip()]

    def _load_name_fields(self,*_args):
        try:
            plan = plan_fk_module(self._inputs(),self.children.isChecked(),self.size.value(),self.module_name.text())
            self.controller_names.sync("FK",plan["joints"])
            self.controller_names.custom.setChecked(True)
            self.status.setText("One name field per controller. Blank fields use joint-based names.")
        except (ValueError,RuntimeError) as exc: self._error(exc)

    def _preview(self, *_args):
        try:
            plan = plan_fk_module(self._inputs(), self.children.isChecked(), self.size.value(), self.module_name.text())
            self.controller_names.sync("FK",plan["joints"])
            _rig_module_names("FK",plan["joints"],self.controller_names.values())
            self.status.setText("Ready: {} joints, {} FK controls, {} native constraints. Root: {}.".format(len(plan["joints"]), len(plan["joints"]), 2*len(plan["joints"]), plan["root_joint"]))
        except (ValueError, RuntimeError) as exc: self._error(exc)

    def _build(self, *_args):
        try:
            plan = plan_fk_module(self._inputs(),self.children.isChecked(),self.size.value(),self.module_name.text())
            self.controller_names.sync("FK",plan["joints"])
            result = build_fk_module(self._inputs(), self.module_name.text(), self.children.isChecked(), self.size.value(), controller_names=self.controller_names.values())
            self._refresh(result["module"])
            self.status.setText("Built {} FK controls ({} owned nodes). Select root to animate globalScale.".format(result["joint_count"], result["owned_node_count"]))
        except (ValueError, RuntimeError) as exc: self._error(exc)

    def _refresh(self, module=None, *_args):
        current = self.modules.currentData()
        wanted = _guide_ik_uuid(module) if isinstance(module, str) else current
        previous_block = self.modules.blockSignals(True)
        self.modules.clear();self.module_rows.setRowCount(0)
        for node in list_rig_modules():
            identity = _guide_ik_uuid(node);state=None
            try:
                _meta, state = _rig_module_read(node)
                label = "{} · {} ({} joints)".format(state["name"], state["type"], len(state["joints"]))
            except (ValueError, RuntimeError): label = node+" · metadata needs checking"
            self.modules.addItem(label, identity)
            row=self.module_rows.rowCount();self.module_rows.insertRow(row)
            self.module_rows.setItem(row,0,QtWidgets.QTableWidgetItem(state['name'] if state else node))
            self.module_rows.setItem(row,1,QtWidgets.QTableWidgetItem(state['type'] if state else '?'))
            cell=QtWidgets.QWidget();buttons=QtWidgets.QHBoxLayout(cell);buttons.setContentsMargins(2,2,2,2)
            for text,action in (('Constraints','constraints'),('Mirror','mirror'),('Delete Rig','delete')):
                button=QtWidgets.QPushButton(text);button.setAutoDefault(False)
                button.clicked.connect(lambda _checked=False,i=identity,a=action:self._module_action(i,a))
                if action=='constraints':
                    button.setEnabled(bool(state and any(r['type'].endswith('Constraint') for r in state['members'])))
                    button.setToolTip('Organize this module’s native solver nodes under constraintNode. Matrix-only modules need no constraint subgroup.')
                elif action=='mirror':
                    button.setEnabled(bool(state and (state['type']!='ROOT' or state.get('root_joint'))))
                    button.setToolTip('Use Search / Replace below to find existing counterpart joints. Central placement Roots remain shared.')
                else:button.setProperty('role','danger')
                buttons.addWidget(button)
            self.module_rows.setCellWidget(row,2,cell);self.module_rows.setRowHeight(row,38)
        index = self.modules.findData(wanted)
        if index >= 0: self.modules.setCurrentIndex(index)
        self.modules.blockSignals(previous_block)
        self._refresh_outputs()

    def _refresh_outputs(self, *_args):
        self.outputs_table.setRowCount(0)
        if not self.modules.currentData():
            self.attachment_status.setText('Build a module to view its outputs.')
            return
        try:
            meta, state = self._state()
            for record in _rig_module_output_rows(meta, state):
                row = self.outputs_table.rowCount(); self.outputs_table.insertRow(row)
                label = record['node'].rsplit('|', 1)[-1] if record['node'] else record['label'] + ' · missing'
                item = QtWidgets.QTableWidgetItem(label)
                item.setData(QtCore.Qt.UserRole, record['uuid'])
                item.setToolTip(record['node'] or 'This output was deleted outside the tool.')
                self.outputs_table.setItem(row, 0, item)
                joint = record['joint']
                item = QtWidgets.QTableWidgetItem(joint.rsplit('|', 1)[-1] if joint else record['label'])
                item.setToolTip(joint or 'Module attachment frame')
                self.outputs_table.setItem(row, 1, item)
                button = QtWidgets.QPushButton('Select'); button.setAutoDefault(False)
                button.setEnabled(record['available'])
                button.clicked.connect(lambda _checked=False, identity=record['uuid']: self._select_output(identity))
                self.outputs_table.setCellWidget(row, 2, button)
                self.outputs_table.setRowHeight(row, 36)
            self.outputs_table.setFixedHeight(max(110, min(230, self.outputs_table.horizontalHeader().height() + 36*self.outputs_table.rowCount() + 8)))
            if self.outputs_table.rowCount():
                self.outputs_table.selectRow(self.outputs_table.rowCount() - 1)
            attachment = state.get('attachment')
            if attachment:
                output = _guide_ik_resolve_uuid(attachment['output'])
                self.attachment_status.setText('Child module: {} · attached to {}'.format(state['name'], output.rsplit('|',1)[-1] if output else 'missing output'))
                self.attachment_status.setToolTip(output or 'The producing output is missing.')
            elif state.get('output_version'):
                self.attachment_status.setText('Child module: {} · no output attachment.'.format(state['name']))
            else:
                self.attachment_status.setText('Saved rig: Publish outputs once to add named outputs and its input buffer. Current pose is kept.')
            if self.parent_output_uuid:
                node = _guide_ik_resolve_uuid(self.parent_output_uuid)
                self.parent_output.setText(node.rsplit('|',1)[-1] if node else 'Chosen output is missing')
                self.parent_output.setToolTip(node or 'The chosen output is missing.')
        except (ValueError, RuntimeError) as exc:
            self.attachment_status.setText(str(exc))

    def _select_output(self, identity):
        try:
            cmds.select(_rig_module_node(identity), replace=True)
        except (ValueError, RuntimeError) as exc: self._error(exc)

    def _publish_outputs(self, *_args):
        try:
            meta, _state = self._state()
            records = publish_rig_outputs(meta)
            self._refresh(meta)
            self.status.setText('{} published output(s). Source joint pose and controller values were kept.'.format(len(records)))
        except (ValueError, RuntimeError) as exc: self._error(exc)

    def _set_parent_output(self, identity):
        node = _rig_module_node(identity)
        _meta, state, _record = _rig_module_resolve_output(node)
        self.parent_output_uuid = identity
        self.parent_output.setText(node.rsplit('|',1)[-1])
        self.parent_output.setToolTip(node)
        self.status.setText('Parent output from {} loaded. Choose the child module above, then Attach.'.format(state['name']))

    def _use_output(self, *_args):
        try:
            item = self.outputs_table.item(self.outputs_table.currentRow(), 0)
            if item is None: raise ValueError('Choose an output row first, or Publish outputs for a saved rig.')
            self._set_parent_output(item.data(QtCore.Qt.UserRole))
        except (ValueError, RuntimeError) as exc: self._error(exc)

    def _get_parent_output(self, *_args):
        try:
            nodes = cmds.ls(selection=True, long=True) or []
            if len(nodes) != 1: raise ValueError('Select one marked OUTPUT transform.')
            self._set_parent_output(_guide_ik_uuid(nodes[0]))
        except (ValueError, RuntimeError) as exc: self._error(exc)

    def _attach_output(self, *_args):
        try:
            meta, _state = self._state()
            if not self.parent_output_uuid: raise ValueError('Get a parent output first.')
            attach_rig_module(meta, _rig_module_node(self.parent_output_uuid))
            self._refresh(meta)
            self.status.setText('Module attached with its current offset. Animate the parent module; global scale is inherited once.')
        except (ValueError, RuntimeError) as exc: self._error(exc)

    def _detach_output(self, *_args):
        try:
            meta, _state = self._state()
            result = detach_rig_module(meta)
            self._refresh(meta)
            self.status.setText('Output attachment removed; current pose kept.' if result['detached'] else 'This module has no output attachment.')
        except (ValueError, RuntimeError) as exc: self._error(exc)

    def _module_action(self,identity,action):
        def execute():
            try:index=self.modules.findData(identity)
            except RuntimeError:return  # Window closed before the queued action ran.
            if index<0:
                self._error(ValueError('That module no longer exists. Refresh the module list.'));return
            self.modules.setCurrentIndex(index)
            if action=='constraints':self._organize_constraints()
            elif action=='mirror':self._mirror()
            elif action=='delete':self._remove()
        QtCore.QTimer.singleShot(0,execute)

    def _organize_constraints(self):
        try:
            meta,_state=self._state();result=organize_rig_constraints(meta)
            self._refresh(meta)
            self.status.setText('Organized {} native constraint nodes for this module.'.format(result['count']))
        except (ValueError,RuntimeError) as exc:self._error(exc)

    def _state(self):
        identity = self.modules.currentData()
        if not identity: raise ValueError("Build a module or refresh the scene module list first.")
        return _rig_module_read(_rig_module_node(identity))

    def _select_root(self, *_args):
        try:
            _meta, state = self._state()
            cmds.select(_rig_module_node(state["root"]), replace=True)
            self.status.setText("ROOT selected: ikFkBlend 0 = FK, 1 = IK; globalScale 1 = original size." if state["type"]=="IKFK" else "ROOT selected. globalScale is visible in the Channel Box; 1 = original size.")
        except (ValueError, RuntimeError) as exc: self._error(exc)

    def _select_attachment(self,*_args):
        try:
            _meta,state=self._state()
            identity=state['roles']['placement'] if state['type']=='ROOT' else state['foot']['ankle_target'] if state['type']=='FOOT' else state['root']
            cmds.select(_rig_module_node(identity),replace=True)
            self.status.setText('Attachment output selected. Keep attachments acyclic; detach them before removing this parent module.')
        except (ValueError,RuntimeError) as exc:self._error(exc)

    def _select_controls(self, *_args):
        try:
            _meta, state = self._state()
            identities = state.get("ui_controls", [row["control"] for row in state["controls"]])
            cmds.select([_rig_module_node(identity) for identity in identities], replace=True)
        except (ValueError, RuntimeError) as exc: self._error(exc)

    def _goto_default(self,*_args):
        try:
            meta,_state = self._state()
            count = goto_rig_default(meta,self.include_default_root.isChecked(),self.key_default.isChecked())
            self.status.setText("Restored {} controller values to default. Undo restores the previous pose.".format(count))
        except (ValueError,RuntimeError,KeyError) as exc: self._error(exc)

    def _store_default(self,*_args):
        try:
            meta,_state = self._state()
            count = store_rig_default(meta)
            self.status.setText("Stored current local values for {} controllers as default, including ROOT.".format(count))
        except (ValueError,RuntimeError) as exc: self._error(exc)

    def _load_existing_names(self,*_args):
        try:
            meta,state = self._state()
            self.existing_names.sync(state["type"],_rig_module_extra_names(state),reset=True)
            self.names_module_uuid = _guide_ik_uuid(meta)
            self.existing_names.custom.setChecked(True)
            self.status.setText("Loaded name fields for the selected rig. Leave blank to use joint-based names.")
        except (ValueError,RuntimeError) as exc: self._error(exc)

    def _rename_controls(self,*_args):
        try:
            meta,_state = self._state()
            if self.existing_names.custom.isChecked() and self.names_module_uuid != _guide_ik_uuid(meta):
                raise ValueError("Load name fields for the selected rig first.")
            result = rename_rig_controllers(meta,self.existing_names.values())
            self.status.setText("Renamed {} controllers. Joint connections and pose were kept.".format(len(result)))
        except (ValueError,RuntimeError) as exc: self._error(exc)

    def _swap_mirror(self,*_args):
        search,replace = self.mirror_search.text(),self.mirror_replace.text()
        self.mirror_search.setText(replace)
        self.mirror_replace.setText(search)

    def _mirror_preview(self,*_args):
        try:
            meta,_state = self._state()
            plan = plan_rig_mirror(meta,self.mirror_search.text(),self.mirror_replace.text())
            self.status.setText("{} mirror ready: {}".format(plan["type"],"; ".join(a.rsplit("|",1)[-1]+" → "+b.rsplit("|",1)[-1] for a,b in zip(plan["source_joints"],plan["joints"]))))
        except (ValueError,RuntimeError) as exc: self._error(exc)

    def _mirror(self,*_args):
        try:
            meta,_state = self._state()
            result = mirror_rig_module(meta,self.mirror_search.text(),self.mirror_replace.text())
            self._refresh(result["module"])
            self.status.setText("Built mirrored rig on {} existing counterpart joints. Source rig was kept; animation was not copied.".format(result["joint_count"]))
        except (ValueError,RuntimeError) as exc: self._error(exc)

    def _remove(self, *_args):
        try:
            meta, _state = self._state()
            result = remove_rig_module(meta)
            self._refresh()
            self.status.setText("Removed '{}'; kept {} joints at their current pose. Undo restores the module.".format(result["name"], result["joint_count"]))
        except (ValueError, RuntimeError) as exc: self._error(exc)


class _RigConnectionsPanel(QtWidgets.QWidget):
    """Read-only discovery followed by an explicit, reviewed connection action."""
    def __init__(self, parent=None):
        super(_RigConnectionsPanel,self).__init__(parent)
        self.setObjectName('RigConnectionsPage');self.setProperty('qtPanel',True)
        self.report=None;self.plans={};self.checked=set();self.start_uuid=None;self.scope_uuid=None;self._loading=False
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(10,10,10,10)
        title=QtWidgets.QLabel('Connect modules from the joint hierarchy')
        title.setProperty('role','heading');layout.addWidget(title)
        scope=QtWidgets.QFormLayout();scope.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        self.roots=QtWidgets.QComboBox();self.roots.setMinimumContentsLength(12)
        self.roots.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        refresh=QtWidgets.QPushButton('Refresh');refresh.clicked.connect(self.refresh)
        row=QtWidgets.QHBoxLayout();row.addWidget(self.roots,1);row.addWidget(refresh);scope.addRow('Root module:',row)
        self.start_field=QtWidgets.QLineEdit();self.start_field.setReadOnly(True);self.start_field.setPlaceholderText('Get the skeleton start joint')
        get=QtWidgets.QPushButton('Get joint');get.clicked.connect(self._get_start)
        store=QtWidgets.QPushButton('Set Root start');store.clicked.connect(self._set_start)
        row=QtWidgets.QHBoxLayout();row.addWidget(self.start_field,1);row.addWidget(get);row.addWidget(store);scope.addRow('Scan start:',row)
        layout.addLayout(scope)
        row=QtWidgets.QHBoxLayout()
        scan=QtWidgets.QPushButton('Scan hierarchy');scan.clicked.connect(self.scan)
        prepare=QtWidgets.QPushButton('Prepare saved modules');prepare.clicked.connect(self._prepare)
        self.missing_only=QtWidgets.QCheckBox('Needs attention only');self.missing_only.setChecked(True)
        self.missing_only.toggled.connect(self._render)
        row.addWidget(scan);row.addWidget(prepare);row.addStretch();row.addWidget(self.missing_only);layout.addLayout(row)
        self.splitter=QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.tree=QtWidgets.QTreeWidget();self.tree.setObjectName('RigConnectionList')
        self.tree.setHeaderLabels(['Module','Start joint','State']);self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True);self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.tree.setMinimumWidth(210);self.tree.setColumnWidth(0,150);self.tree.setColumnWidth(1,120)
        self.tree.itemSelectionChanged.connect(self._choose);self.tree.itemChanged.connect(self._checked)
        self.splitter.addWidget(self.tree)
        editor=QtWidgets.QWidget();editor.setMinimumWidth(260)
        form=QtWidgets.QFormLayout(editor);form.setContentsMargins(10,0,0,0)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows);form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.child_name=QtWidgets.QLabel('Choose a module on the left.');self.child_name.setWordWrap(True)
        form.addRow(self.child_name)
        self.start_label=QtWidgets.QLabel();self.start_label.setWordWrap(True);form.addRow('Start joint:',self.start_label)
        self.controller_label=QtWidgets.QLabel();self.controller_label.setWordWrap(True);form.addRow('Controller:',self.controller_label)
        self.parents=QtWidgets.QComboBox();self.outputs=QtWidgets.QComboBox();self.method=QtWidgets.QComboBox()
        for combo in (self.parents,self.outputs,self.method):
            combo.setMinimumContentsLength(9);combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for entry in rig_connection_methods():
            self.method.addItem(entry['label'],entry['id'])
            if not entry['available']:
                self.method.model().item(self.method.count()-1).setEnabled(False)
                self.method.setItemData(self.method.count()-1,'Reserved for a future connection method.',QtCore.Qt.ToolTipRole)
        form.addRow('Parent module:',self.parents);form.addRow('Parent output:',self.outputs);form.addRow('Method:',self.method)
        self.follow_scale=QtWidgets.QCheckBox('Follow parent scale');self.follow_scale.setChecked(True)
        form.addRow(self.follow_scale)
        self.parents.currentIndexChanged.connect(self._parent_changed)
        self.outputs.currentIndexChanged.connect(self._store_plan)
        self.method.currentIndexChanged.connect(self._store_plan);self.follow_scale.toggled.connect(self._store_plan)
        self.detail=QtWidgets.QLabel();self.detail.setWordWrap(True);form.addRow(self.detail)
        row=QtWidgets.QHBoxLayout()
        select_joint=QtWidgets.QPushButton('Select joint');select_joint.clicked.connect(lambda:self._select('joint'))
        select_ctrl=QtWidgets.QPushButton('Select controller');select_ctrl.clicked.connect(lambda:self._select('controller'))
        row.addWidget(select_joint);row.addWidget(select_ctrl);form.addRow(row)
        self.connect_button=QtWidgets.QPushButton('Connect selected · keep offset');self.connect_button.setProperty('role','primary')
        self.connect_button.clicked.connect(self._connect_selected);form.addRow(self.connect_button)
        self.detach_button=QtWidgets.QPushButton('Detach selected · keep pose');self.detach_button.clicked.connect(self._detach);form.addRow(self.detach_button)
        note=QtWidgets.QLabel('Parent and output are suggestions. Review them before connecting. Parent constraint uses a scale constraint when Follow parent scale is enabled. Matrix parent always carries scale.')
        note.setWordWrap(True);note.setProperty('role','muted');form.addRow(note)
        self.splitter.addWidget(editor);self.splitter.setSizes([370,300]);self.splitter.setMinimumHeight(340)
        layout.addWidget(self.splitter,1)
        self.apply_button=QtWidgets.QPushButton('Connect checked modules · one Undo')
        self.apply_button.setProperty('role','primary');self.apply_button.clicked.connect(self._connect_checked);layout.addWidget(self.apply_button)
        self.status=QtWidgets.QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.issues=QtWidgets.QPlainTextEdit();self.issues.setObjectName('RigConnectionIssues');self.issues.setReadOnly(True);self.issues.setMaximumHeight(85);self.issues.hide();layout.addWidget(self.issues)
        for button in self.findChildren(QtWidgets.QPushButton):button.setAutoDefault(False)
        self.roots.currentIndexChanged.connect(self._root_changed)
        self.refresh()

    def _error(self,exc):
        self.status.setText(str(exc));cmds.warning(str(exc))

    def refresh(self,*_args):
        wanted=self.roots.currentData();self.roots.blockSignals(True);self.roots.clear()
        for module in list_rig_modules():
            try:
                # Root choices need labels only. Full validation happens in the
                # single registry scan, rather than once more for every module.
                state=json.loads(cmds.getAttr(module+'.'+_RIG_MODULE_STATE))
                if state['type']=='ROOT':self.roots.addItem(state['name'],_guide_ik_uuid(module))
            except (ValueError,RuntimeError,TypeError,KeyError):continue
        index=self.roots.findData(wanted)
        if index>=0:self.roots.setCurrentIndex(index)
        self.roots.blockSignals(False);self._root_changed()

    def _root_changed(self,*_args):
        identity=self.roots.currentData()
        if identity!=self.scope_uuid:self.plans={};self.checked=set()
        self.scope_uuid=identity;self.report=None;self.start_uuid=None;self.start_field.clear()
        if not identity:
            self._render();self.status.setText('Build a Root module first, or refresh after loading a scene.');return
        try:
            _meta,state=_rig_module_read(_rig_module_node(identity));self.start_uuid=_rig_module_inferred_start(state)
            self._show_start()
            if self.start_uuid:self.scan()
            else:self._render();self.status.setText('Get a joint and Set Root start. This creates message links and does not constrain that joint.')
        except (ValueError,RuntimeError) as exc:self._render();self._error(exc)

    def _show_start(self):
        node=_guide_ik_resolve_uuid(self.start_uuid) if self.start_uuid else None
        self.start_field.setText(node.rsplit('|',1)[-1] if node else '')
        self.start_field.setToolTip(node or '')

    def _get_start(self,*_args):
        try:
            nodes=cmds.ls(selection=True,long=True) or []
            if len(nodes)!=1:raise ValueError('Select one joint for the Root scan start.')
            self.start_uuid=_guide_ik_uuid(_guide_ik_joint(nodes[0]));self._show_start()
            self.status.setText('Joint loaded. Click Set Root start to store the message link.')
        except (ValueError,RuntimeError) as exc:self._error(exc)

    def _set_start(self,*_args):
        try:
            if not self.scope_uuid or not self.start_uuid:raise ValueError('Choose a Root module and Get a start joint first.')
            register_rig_start(_rig_module_node(self.scope_uuid),_rig_module_node(self.start_uuid));self.scan()
        except (ValueError,RuntimeError) as exc:self._error(exc)

    def scan(self,*_args):
        try:
            if not self.scope_uuid:raise ValueError('Choose a Root module first.')
            previous_ready={row['module'] for row in (self.report or {}).get('rows',[]) if row['ready']}
            report=scan_rig_connections(_rig_module_node(self.scope_uuid))
            self.report=report;self.start_uuid=report['root_start'];self._show_start()
            for row in report['rows']:
                identity=row['module']
                if identity not in self.plans or row['status']=='connected':
                    self.plans[identity]={key:row[key] for key in ('module','parent_module','output','method','follow_scale')}
                if row['ready'] and identity not in previous_ready:self.checked.add(identity)
                if not row['ready']:self.checked.discard(identity)
            self._render()
            missing=sum(row['status']=='missing' for row in report['rows']);ready=sum(row['ready'] for row in report['rows'])
            self.status.setText('{} joints · {} modules · {} missing connections · {} ready. Scan made no scene edits.'.format(report['joint_count'],len(report['rows']),missing,ready))
            self.issues.setVisible(bool(report['issues']))
            self.issues.setPlainText('\n'.join(row['module']+': '+row['message'] for row in report['issues']))
        except (ValueError,RuntimeError) as exc:
            self.report=None;self._render();self._error(exc)

    def _render(self,*_args):
        selected=self.tree.currentItem();wanted=selected.data(0,QtCore.Qt.UserRole) if selected else None
        self._loading=True;self.tree.clear()
        for row in (self.report or {}).get('rows',[]):
            if self.missing_only.isChecked() and row['status'] in ('connected','parented'):continue
            label={'missing':'Missing','connected':'Connected','parented':'DAG parent','external':'External driver','broken':'Broken','ambiguous':'Ambiguous'}[row['status']]
            if row['needs_prepare']:label+=' · prepare'
            node=row['start_node'];item=QtWidgets.QTreeWidgetItem([row['name']+' · '+row['type'],node.rsplit('|',1)[-1] if node else '(missing)',label])
            item.setData(0,QtCore.Qt.UserRole,row['module']);item.setToolTip(0,row['node']);item.setToolTip(1,node or '');item.setToolTip(2,row['detail'])
            if row['ready']:
                item.setFlags(item.flags()|QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(0,QtCore.Qt.Checked if row['module'] in self.checked else QtCore.Qt.Unchecked)
            self.tree.addTopLevelItem(item)
            if row['module']==wanted:self.tree.setCurrentItem(item)
        if not self.tree.currentItem() and self.tree.topLevelItemCount():self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._loading=False;self._choose()
        self.apply_button.setEnabled(any(row['ready'] and row['module'] in self.checked for row in (self.report or {}).get('rows',[])))

    def _row(self):
        item=self.tree.currentItem()
        if not item:return None
        identity=item.data(0,QtCore.Qt.UserRole)
        return next((row for row in self.report['rows'] if row['module']==identity),None) if self.report else None

    def _choose(self):
        if self._loading:return
        row=self._row();self._loading=True;self.parents.clear();self.outputs.clear()
        if not row:
            self.child_name.setText('Choose a module on the left.');self.start_label.clear();self.controller_label.clear();self.detail.clear()
            self._loading=False;self._set_enabled(None);return
        plan=self.plans[row['module']]
        self.child_name.setText(row['name']+' · '+row['type'])
        self.start_label.setText(row['start_node'].rsplit('|',1)[-1] if row['start_node'] else '(missing)')
        try:
            _meta,state=_rig_module_read(_rig_module_node(row['module']))
            ctrl=_rig_module_node(_rig_module_start_controller(state));self.controller_label.setText(ctrl.rsplit('|',1)[-1]);self.controller_label.setToolTip(ctrl)
        except (ValueError,RuntimeError):self.controller_label.setText('(missing)')
        for parent in (self.report or {}).get('modules',[]):
            if parent['module']!=row['module']:self.parents.addItem(parent['name']+' · '+parent['type'],parent['module'])
        index=self.parents.findData(plan['parent_module'])
        if index>=0:self.parents.setCurrentIndex(index)
        self._fill_outputs(plan['output'])
        index=self.method.findData(plan['method']);self.method.setCurrentIndex(max(0,index))
        self.follow_scale.setChecked(plan['follow_scale'])
        self.detail.setText(row['detail']+(' Prepare saved modules before connecting.' if row['needs_prepare'] else ''))
        self._loading=False;self._set_enabled(row)

    def _fill_outputs(self,wanted=None):
        self.outputs.clear();identity=self.parents.currentData()
        parent=next((item for item in (self.report or {}).get('modules',[]) if item['module']==identity),None)
        for output in parent['outputs'] if parent else []:
            if output['available']:self.outputs.addItem(output['label']+' · '+output['node'].rsplit('|',1)[-1],output['uuid'])
        index=self.outputs.findData(wanted)
        if index>=0:self.outputs.setCurrentIndex(index)

    def _parent_changed(self,*_args):
        if self._loading:return
        self._loading=True;self._fill_outputs();self._loading=False;self._store_plan()

    def _store_plan(self,*_args):
        if self._loading:return
        row=self._row()
        if not row:return
        self.plans[row['module']].update(parent_module=self.parents.currentData(),output=self.outputs.currentData(),
            method=self.method.currentData(),follow_scale=self.follow_scale.isChecked())
        if self.method.currentData()=='matrix_parent':
            self._loading=True;self.follow_scale.setChecked(True);self._loading=False
            self.plans[row['module']]['follow_scale']=True
        self._set_enabled(row)

    def _set_enabled(self,row):
        editable=bool(row and row['status']=='missing' and not row['needs_prepare'])
        for widget in (self.parents,self.outputs,self.method):widget.setEnabled(editable)
        self.follow_scale.setEnabled(editable and self.method.currentData()=='parent_constraint')
        self.connect_button.setEnabled(editable and bool(self.outputs.currentData()))
        self.detach_button.setEnabled(bool(row and row['status'] in ('connected','broken')))

    def _checked(self,item,column):
        if self._loading or column!=0:return
        identity=item.data(0,QtCore.Qt.UserRole)
        if item.checkState(0)==QtCore.Qt.Checked:self.checked.add(identity)
        else:self.checked.discard(identity)
        self.apply_button.setEnabled(bool(self.checked))

    def _prepare(self,*_args):
        try:
            if not self.report:raise ValueError('Set the Root start and scan its hierarchy first.')
            modules=[self.report['root_module']]+[row['module'] for row in self.report['rows']]
            result=prepare_rig_modules([_rig_module_node(identity) for identity in modules]);self.scan()
            self.status.setText('Prepared {} saved module(s). Current poses and controllers were kept.'.format(result['count']))
        except (ValueError,RuntimeError) as exc:self._error(exc)

    def _apply(self,identities):
        try:
            if not identities:raise ValueError('Choose at least one missing connection.')
            plans=[]
            for identity in identities:
                plan=dict(self.plans[identity])
                if not plan['output']:raise ValueError('Choose a parent output for each checked module.')
                plan['module']=_rig_module_node(identity);plan['output']=_rig_module_node(plan['output']);plans.append(plan)
            result=connect_rig_modules(plans);self.scan()
            self.status.setText('Connected {} module(s); current offsets and controller values kept. Undo restores the complete plan.'.format(result['count']))
        except (ValueError,RuntimeError) as exc:self._error(exc)

    def _connect_selected(self,*_args):
        row=self._row();self._apply([row['module']] if row else [])

    def _connect_checked(self,*_args):
        rows=(self.report or {}).get('rows',[])
        self._apply([row['module'] for row in rows if row['ready'] and row['module'] in self.checked])

    def _detach(self,*_args):
        try:
            row=self._row()
            if not row:raise ValueError('Choose a connected module.')
            detach_rig_module(_rig_module_node(row['module']));self.scan()
            self.status.setText('Connection removed; current joint and controller pose kept.')
        except (ValueError,RuntimeError) as exc:self._error(exc)

    def _select(self,kind):
        try:
            row=self._row()
            if not row:raise ValueError('Choose a module first.')
            _meta,state=_rig_module_read(_rig_module_node(row['module']))
            identity=_rig_module_inferred_start(state) if kind=='joint' else _rig_module_start_controller(state)
            cmds.select(_rig_module_node(identity),replace=True)
        except (ValueError,RuntimeError) as exc:self._error(exc)


class TabModularRig(QtWidgets.QWidget):
    def __init__(self,parent=None):
        super(TabModularRig,self).__init__(parent)
        self.setObjectName('ModularRigPage')
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.tabs=QtWidgets.QTabWidget();self.tabs.setObjectName('RigModuleTabs');layout.addWidget(self.tabs)
        self.modules_panel=_RigModulesPanel();self.connections_panel=None
        self.module_scroll=QtWidgets.QScrollArea();self.module_scroll.setWidgetResizable(True);self.module_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.module_scroll.setWidget(self.modules_panel);self.tabs.addTab(self.module_scroll,'Modules')
        self.connection_scroll=QtWidgets.QScrollArea();self.connection_scroll.setWidgetResizable(True);self.connection_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.tabs.addTab(self.connection_scroll,'Connections');self.tabs.currentChanged.connect(self._activate)
        self.setMinimumHeight(580)

    def _activate(self,index):
        if index!=1:return
        if self.connections_panel is None:
            self.connections_panel=_RigConnectionsPanel();self.connection_scroll.setWidget(self.connections_panel)
        else:self.connections_panel.refresh()


class TabWaveJoints(QtWidgets.QWidget):
    """Lazy sibling modules; closing the page leaves the native wave graph alive."""
    def __init__(self, parent=None):
        super(TabWaveJoints, self).__init__(parent)
        backend = _pd_sdk_module('wave_joints')
        ui = _pd_sdk_module('wave_joints_ui')
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = ui.WaveJointsPanel(self, backend)
        layout.addWidget(self.panel)


class TabCopySkinning(QtWidgets.QWidget):
    """Lazy load Weight Editor and Copy Skinning in one Skinning Tools page."""
    def __init__(self,parent=None):
        super(TabCopySkinning,self).__init__(parent)
        import importlib.util
        import os
        import sys
        directories=[os.path.dirname(globals().get("__file__", "")),cmds.internalVar(userScriptDir=True)]+list(sys.path)
        filename=next((os.path.join(d,"skinning_ui.py") for d in directories if isinstance(d,str) and os.path.isfile(os.path.join(d,"skinning_ui.py"))),None)
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        if not filename:
            note=QtWidgets.QLabel("Skinning Tools requires the accompanying skinning_ui.py, skinning_backend.py, skinning_core.py and all three copy_skinning files. Extract the complete toolkit folder and import master_rigging_toolkit from that folder, then reopen this window.")
            note.setWordWrap(True);layout.addWidget(note);return
        spec=importlib.util.spec_from_file_location("_rtk_copy_skin_panel_01",filename)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self._copy_module=module
        layout.addWidget(module.SkinningToolsPanel(self))


class TabJointCleanup(QtWidgets.QWidget):
    """Audit mesh influences and prune unused joint branches explicitly."""

    def __init__(self, parent=None):
        super(TabJointCleanup, self).__init__(parent)
        import importlib.util
        import os
        import sys
        directories = [os.path.dirname(globals().get("__file__", "")),
                       cmds.internalVar(userScriptDir=True)] + list(sys.path)
        filename = next((os.path.join(folder, "joint_cleanup.py") for folder in directories
                         if isinstance(folder, str) and os.path.isfile(os.path.join(folder, "joint_cleanup.py"))), None)
        if not filename:
            raise ValueError("Extract the complete toolkit folder, including joint_cleanup.py, and reopen the toolkit.")
        spec = importlib.util.spec_from_file_location("_rtk_joint_cleanup", filename)
        self._backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self._backend)
        self._report = None
        self._meshes = []
        self.setObjectName("JointCleanupPage")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setProperty("qtPanel", True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        inputs = QtWidgets.QGroupBox("Meshes && joint hierarchy")
        inputs.setObjectName("JointCleanupInputs")
        form = QtWidgets.QVBoxLayout(inputs)
        form.addWidget(QtWidgets.QLabel("Meshes to check"))
        self.mesh_list = QtWidgets.QListWidget()
        self.mesh_list.setObjectName("JointCleanupMeshes")
        self.mesh_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.mesh_list.setFixedHeight(76)
        self.mesh_list.setToolTip("Load mesh transforms or output shapes. Every loaded mesh is checked.")
        form.addWidget(self.mesh_list)
        mesh_actions = QtWidgets.QHBoxLayout()
        for label, callback in (("Get selected meshes", self._load_meshes),
                                ("Remove selected", self._remove_meshes), ("Clear", self._clear_meshes)):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            mesh_actions.addWidget(button)
        form.addLayout(mesh_actions)
        root_row = QtWidgets.QHBoxLayout()
        root_row.addWidget(QtWidgets.QLabel("Joint root"))
        self.root = QtWidgets.QLineEdit()
        self.root.setPlaceholderText("Select the top joint of the chain…")
        self.root.textChanged.connect(self._invalidate)
        root_row.addWidget(self.root, 1)
        get_root = QtWidgets.QPushButton("Get selected")
        get_root.clicked.connect(self._load_root)
        root_row.addWidget(get_root)
        form.addLayout(root_row)
        layout.addWidget(inputs)

        self.scan_button = QtWidgets.QPushButton("Scan unused joints")
        _set_button_role(self.scan_button, "primary")
        self.scan_button.clicked.connect(self._scan)
        layout.addWidget(self.scan_button)
        self.summary = QtWidgets.QLabel("Load meshes and a joint root, then scan. The root is included.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.skin_summary = QtWidgets.QLabel()
        self.skin_summary.setProperty("role", "muted")
        self.skin_summary.setWordWrap(True)
        layout.addWidget(self.skin_summary)

        self.table = QtWidgets.QTreeWidget()
        self.table.setColumnCount(4)
        self.table.setHeaderLabels(["Joint", "Status", "Select", "Delete"])
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setUniformRowHeights(True)
        self.table.setMinimumHeight(180)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setToolTip("Click Select or double-click a joint to select it in Maya. Hover for its full path and protection reason.")
        header = self.table.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)
        header.resizeSection(2, 78)
        header.resizeSection(3, 82)
        self.table.itemDoubleClicked.connect(self._select_joint)
        layout.addWidget(self.table, 1)

        actions = QtWidgets.QHBoxLayout()
        self.delete_all = QtWidgets.QPushButton("Delete All")
        _set_button_role(self.delete_all, "danger")
        self.delete_all.setEnabled(False)
        self.delete_all.setToolTip("Delete all eligible joints from the displayed results, tips first. Protected rows are kept. One Maya Undo step.")
        self.delete_all.clicked.connect(self._delete_all)
        actions.addStretch()
        actions.addWidget(self.delete_all)
        layout.addLayout(actions)
        note = QtWidgets.QLabel("Zero-weight influences are kept. Other skins, rig drivers and retained children are protected. No reparenting. Undo restores a delete action.")
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)

    def _invalidate(self, *_args):
        self._report = None
        self.table.clear()
        self.delete_all.setEnabled(False)
        self.skin_summary.clear()
        self.summary.setText("Inputs changed. Scan unused joints to refresh the results.")

    def _error(self, exc):
        self.summary.setText(str(exc))
        cmds.warning("Cleanup: {}".format(exc))

    def _show_meshes(self):
        self.mesh_list.clear()
        for mesh in self._meshes:
            item = QtWidgets.QListWidgetItem(mesh["path"].rsplit("|", 1)[-1])
            item.setData(QtCore.Qt.UserRole, mesh["uuid"])
            item.setToolTip(mesh["path"])
            self.mesh_list.addItem(item)

    def _load_meshes(self, *_args):
        try:
            meshes = self._backend.mesh_records(cmds.ls(selection=True, long=True) or [])
            existing = {mesh["uuid"]: mesh for mesh in self._meshes}
            existing.update((mesh["uuid"], mesh) for mesh in meshes)
            self._meshes = list(existing.values())
            self._show_meshes()
            self._invalidate()
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _remove_meshes(self, *_args):
        selected = {item.data(QtCore.Qt.UserRole) for item in self.mesh_list.selectedItems()}
        self._meshes = [mesh for mesh in self._meshes if mesh["uuid"] not in selected]
        self._show_meshes()
        self._invalidate()

    def _clear_meshes(self, *_args):
        self._meshes = []
        self._show_meshes()
        self._invalidate()

    def _load_root(self, *_args):
        try:
            selected = cmds.ls(selection=True, long=True) or []
            if len(selected) != 1:
                raise ValueError("Select exactly one joint root.")
            self.root.setText(self._backend.joint_record(selected[0])["path"])
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _scan(self, *_args):
        old = self._report
        self._invalidate()
        try:
            # Reuse UUIDs after a successful scan; renaming an input must not
            # silently redirect a cleanup action to another object.
            if old is not None:
                report = self._backend.refresh_scan(old)
            else:
                meshes = [self._backend._from_identity(mesh["uuid"]) for mesh in self._meshes]
                report = self._backend.scan_unused_joints(meshes, self.root.text().strip())
            self._render(report)
        except (ValueError, RuntimeError) as exc:
            self._error(exc)

    def _render(self, report):
        self.table.clear()
        self._report = report
        if report is None:
            self.delete_all.setEnabled(False)
            self.skin_summary.clear()
            return
        self._meshes = report["meshes"]
        self._show_meshes()
        blocker = QtCore.QSignalBlocker(self.root)
        self.root.setText(report["root"]["path"])
        del blocker
        for row in report["rows"]:
            item = QtWidgets.QTreeWidgetItem([row["path"].rsplit("|", 1)[-1], row["reason"], "", ""])
            item.setData(0, QtCore.Qt.UserRole, row["uuid"])
            item.setToolTip(0, row["path"])
            item.setToolTip(1, row["reason"])
            self.table.addTopLevelItem(item)
            select = QtWidgets.QPushButton("Select")
            select.setToolTip("Select this joint in Maya, including protected joints.")
            select.clicked.connect(lambda _checked=False, identity=row["uuid"]: self._select_joint_id(identity))
            self.table.setItemWidget(item, 2, select)
            button = QtWidgets.QPushButton("Delete")
            _set_button_role(button, "danger")
            button.setEnabled(row["can_delete"])
            button.setToolTip("Delete this joint; one Maya Undo step." if row["can_delete"] else row["reason"])
            button.clicked.connect(lambda _checked=False, identity=row["uuid"]: self._delete([identity]))
            self.table.setItemWidget(item, 3, button)
        self.delete_all.setEnabled(report["deletable_count"] > 0)
        self.summary.setText("{} joints checked · {} skin influences kept · {} absent from these skins · {} can delete"
                             .format(report["joint_count"], report["bound_count"], len(report["rows"]), report["deletable_count"]))
        text = "SkinClusters: " + ", ".join(report["skins"])
        if report["unskinned_meshes"]:
            text += " · No skin on: " + ", ".join(path.rsplit("|", 1)[-1] for path in report["unskinned_meshes"])
        self.skin_summary.setText(text)

    def _delete_all(self, *_args):
        self._delete(None)

    def _delete(self, identities):
        if self._report is None:
            self._error(ValueError("Scan the inputs before deleting."))
            return
        snapshot = self._report
        try:
            result = self._backend.delete_unused_joints(snapshot, identities)
            self._render(result["scan"])
            message = "Deleted {} joints. Undo restores this action.".format(len(result["deleted"]))
            if result["skipped_count"]:
                message += " Kept {} protected or changed joints.".format(result["skipped_count"])
            if result["scan"] is None:
                blocker = QtCore.QSignalBlocker(self.root)
                self.root.clear()
                del blocker
                message += " The unused root was removed. Load a new joint root to scan."
            self.summary.setText(message)
        except (ValueError, RuntimeError) as exc:
            # Invalidate every destructive control on a failed/stale action.
            self._invalidate()
            self._error(exc)

    def _select_joint(self, item, _column):
        self._select_joint_id(item.data(0, QtCore.Qt.UserRole))

    def _select_joint_id(self, identity):
        try:
            node = self._backend._from_identity(identity)
            cmds.select(node, replace=True)
        except (ValueError, RuntimeError) as exc:
            self._error(exc)


class MasterRiggingUI(QtWidgets.QDialog):
    """Searchable navigation, lazy pages, and explicit Maya UI ownership."""

    WORKFLOWS = (
        ("controllers", "Controllers", "Create controller shapes, constraints, and display layers.", "control shape circle cube sphere joint layer"),
        ("mirror", "Mirror shapes", "Mirror selected curve controls across the YZ plane.", "mirror left right curve color"),
        ("weights", "Skin weights", "Move influence weights between two namespaces.", "skin transfer namespace weight joint"),
        ("copy_skinning", "Skinning Tools", "Edit weights with Nudge Skin or copy by vertex IDs, closest surface and masks.", "copy skinning skin weights nudge set average smooth hammer prune hold unhold influence mirror vertex clipboard transfer vertex id closest point surface triangle barycentric interpolation face region paint mask source target current deform base rest"),
        ("cleanup", "Cleanup", "Find joints outside the loaded meshes' skinClusters and delete unused branches.", "cleanup clean up unused joint skincluster influence mesh root hierarchy prune delete remove skeleton"),
        ("custom_attributes", "Custom attributes", "Copy source custom attributes to target, then let target drive source.", "custom user attribute copy connect controller enum channel"),
        ("hierarchy", "Constraints", "Create Driver → Driven constraints or match complete hierarchies.", "constraint driver driven maintain offset parent point orient scale aim hierarchy matching old new rig root"),
        ("naming", "Naming & hierarchy", "Rename objects and organize hierarchy constraints.", "rename suffix swap group collect constraint"),
        ("modular_rig", "Modular Rig", "Build rig modules, mark their start joints and connect them from the skeleton hierarchy.", "modular rig system connection assembly start joint message registration parent constraint space switch module output input attachment chain parent child root main foot ankle ball toe heel bank reverse ik foot fk foot fk three bone ik ikfk blend switch match joint pole end base hierarchy root global scale controller stretchy stretch antipop soft slide pole lock length translation naming custom default reset mirror search replace performance remove collapse expand"),
        ("wave_joints", "waveJoints", "Create native joint waves with translation, rotation and position-based amplitude falloff.", "wave sine sin joint chain offset phase frequency amplitude envelope falloff position power center peak time speed translate rotate tx ty tz rx ry rz tail tentacle flag ripple"),
        ("fk_aim", "FK & Aim", "Build FK chains, curve aim, and distance-driven aim setups.", "fk aim chain distance falloff slider cache"),
        ("sdk", "Group SDK", "Create matched groups around target objects.", "sdk group parent child prefix suffix transform"),
        ("vertex", "Vertex constraints", "Drive an object from the influence weights on a vertex.", "vertex constraint skin threshold driven"),
        ("pose_driver", "PoseDriver", "Capture joint swing poses, drive SDK transforms and mirror their curves.", "pose driver cone sdk set driven key raw normalized weight curve mirror flip keep neutral channel target falloff joint mirror search replace rotation default automatic names minimum angle linear smooth easy remove"),
        ("guides", "Guides & joints", "Create guides, build three-joint IK, orient joints, and clean timeline keys.", "locator view guide ik inverse kinematics pole joint orient axis snap center key animation match transform source target position rotation scale"),
    )

    def __init__(self, parent=None):
        super(MasterRiggingUI, self).__init__(parent if parent is not None else get_maya_main_window())
        self.setObjectName("MasterRiggingToolkit")
        self.setWindowTitle("Master Rigging Toolkit v2.41")
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)
        # Maya-owned child controls are released first, outside the close event.
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setAttribute(QtCore.Qt.WA_QuitOnClose, False)
        self.setProperty("rtkLifecycleVersion", "2.4")
        self.setMinimumSize(680, 480)
        self.resize(860, 760)
        self.setStyleSheet(TOOLKIT_STYLE)
        self._settings = QtCore.QSettings("MayaRiggingTools", "MasterRiggingToolkit")
        self._pages = {}
        self._active_key = "controllers"
        self._jobs = []
        self._save_callback = None
        self._exit_callback = None
        self._cleanup_done = False
        self._shutdown_state = _install_maya_shutdown_guard()
        self._closed = False
        self._reset_pending = False
        self.unified_tool = EmbeddedUnifiedRiggingToolkit()
        self._filter_timer = QtCore.QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(120)
        self._filter_timer.timeout.connect(self._filter_navigation)
        self._scene_timer = QtCore.QTimer(self)
        self._scene_timer.setSingleShot(True)
        self._scene_timer.timeout.connect(self._reload_scene_pages)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(14)
        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Rigging Toolkit")
        title.setObjectName("ToolkitTitle")
        header.addWidget(title)
        header.addStretch()
        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName("ToolSearch")
        self.search.setPlaceholderText("Find a tool…  Ctrl+K")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(285)
        self.search.textChanged.connect(lambda _text: self._filter_timer.start())
        self.search.returnPressed.connect(self._activate_first_match)
        header.addWidget(self.search)
        outer.addLayout(header)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(16)
        sidebar = QtWidgets.QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(174)
        sidebar_layout = QtWidgets.QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(5, 12, 5, 8)
        category = QtWidgets.QLabel("  WORKFLOWS")
        category.setProperty("role", "muted")
        sidebar_layout.addWidget(category)
        self.navigation = QtWidgets.QListWidget()
        self.navigation.setObjectName("Navigation")
        self.navigation.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        for key, label, description, _keywords in self.WORKFLOWS:
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, key)
            item.setToolTip(description)
            self.navigation.addItem(item)
        sidebar_layout.addWidget(self.navigation, 1)
        self.match_hint = QtWidgets.QLabel("")
        self.match_hint.setProperty("role", "muted")
        self.match_hint.setWordWrap(True)
        sidebar_layout.addWidget(self.match_hint)
        body.addWidget(sidebar)

        content = QtWidgets.QVBoxLayout()
        content.setSpacing(8)
        self.page_title = QtWidgets.QLabel()
        self.page_title.setObjectName("PageTitle")
        self.page_description = QtWidgets.QLabel()
        self.page_description.setProperty("role", "muted")
        self.page_description.setWordWrap(True)
        content.addWidget(self.page_title)
        content.addWidget(self.page_description)
        self.stack = QtWidgets.QStackedWidget()
        content.addWidget(self.stack, 1)
        body.addLayout(content, 1)
        outer.addLayout(body, 1)
        self.status = QtWidgets.QLabel("Ready")
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.navigation.currentItemChanged.connect(self._navigation_changed)

        shortcut_type = getattr(QtGui, "QShortcut", None) or QtWidgets.QShortcut
        self._search_shortcut = shortcut_type(QtGui.QKeySequence("Ctrl+K"), self)
        self._search_shortcut.activated.connect(self._focus_search)
        geometry = self._settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        saved_key = self._settings.value("active_workflow", "controllers")
        self.select_workflow(saved_key)
        for event in ("NewSceneOpened", "SceneOpened"):
            self._jobs.append(cmds.scriptJob(event=[event, self._queue_scene_reload], protected=True))
        self._save_callback = om.MSceneMessage.addCallback(om.MSceneMessage.kBeforeSave, self._before_scene_save)
        self._exit_callback = om.MSceneMessage.addCallback(om.MSceneMessage.kMayaExiting, self._on_maya_exiting)
        self._qt_app = QtWidgets.QApplication.instance()
        self._qt_app.aboutToQuit.connect(self._on_maya_exiting)

    def _focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def _filter_navigation(self):
        query = self.search.text().strip().lower()
        words = query.split()
        visible = 0
        for index, (_key, label, description, keywords) in enumerate(self.WORKFLOWS):
            text = " ".join((label, description, keywords)).lower()
            matches = all(word in text for word in words)
            self.navigation.item(index).setHidden(not matches)
            visible += int(matches)
        self.match_hint.setText("No matching tools." if visible == 0 else ("{} tools found".format(visible) if query else ""))

    def _activate_first_match(self):
        self._filter_timer.stop()
        self._filter_navigation()
        for index in range(self.navigation.count()):
            item = self.navigation.item(index)
            if not item.isHidden():
                self.navigation.setCurrentItem(item)
                return

    def select_workflow(self, key):
        for index, entry in enumerate(self.WORKFLOWS):
            if entry[0] == key:
                self.navigation.setCurrentRow(index)
                return
        self.navigation.setCurrentRow(0)

    def _navigation_changed(self, current, _previous):
        if current is None or self._closed or self._reset_pending or _maya_is_exiting():
            return
        key = current.data(QtCore.Qt.UserRole)
        entry = next(entry for entry in self.WORKFLOWS if entry[0] == key)
        if key not in self._pages:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                if key in self.unified_tool.BUILDERS:
                    page = self.unified_tool.get_page(key)
                elif key == "sdk":
                    page = TabGroupUtils()
                elif key == "vertex":
                    page = TabVertexConstraint()
                else:
                    if key == "hierarchy":
                        panel = TabHierarchyConstraints()
                    elif key == "copy_skinning":
                        panel = TabCopySkinning()
                    elif key == "cleanup":
                        panel = TabJointCleanup()
                    elif key == "custom_attributes":
                        panel = TabCustomAttributes()
                    elif key == "pose_driver":
                        panel = TabPoseDriver()
                    elif key == "modular_rig":
                        panel = TabModularRig()
                    elif key == "wave_joints":
                        panel = TabWaveJoints()
                    else:
                        panel = TabMiniRig()
                    _polish_native_panel(panel)
                    page = QtWidgets.QScrollArea()
                    page.setWidgetResizable(True)
                    page.setFrameShape(QtWidgets.QFrame.NoFrame)
                    page.setWidget(panel)
                self.stack.addWidget(page)
                self._pages[key] = page
            except Exception as exc:
                self.status.setText("Could not open {}: {}. Select the workflow again to retry.".format(entry[1], exc))
                cmds.warning("Rigging Toolkit: {}".format(exc))
                traceback.print_exc()
                self.navigation.setCurrentRow(-1)
                return
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
        self.stack.setCurrentWidget(self._pages[key])
        self._active_key = key
        self.page_title.setText(entry[1])
        self.page_description.setText(entry[2])
        self.status.setText("Ready · Setup settings are saved with the scene.")

    def _cached_panels(self):
        # Duck typing also works when an existing window closes after importlib.reload.
        return [page for page in self._pages.values() if hasattr(page, "flush_cache")]

    def _before_scene_save(self, *_args):
        if not self._closed and not self._reset_pending and not _maya_is_exiting():
            for panel in self._cached_panels():
                panel.flush_cache()

    def _queue_scene_reload(self, *_args):
        if self._closed or _maya_is_exiting():
            return
        self._reset_pending = True
        for panel in self._cached_panels():
            panel._cache_timer.stop()
        guides = self._pages.get("guides")
        if guides is not None and guides.widget() is not None:
            guides.widget()._radius_timer.stop()
        self._scene_timer.start(0)

    def _quiesce_ui(self):
        for timer in self.findChildren(QtCore.QTimer):
            if _qt_object_valid(timer):
                timer.stop()
        # Hiding a focused spin box can emit editingFinished. Suppress those
        # slots too, so guide edits cannot run Maya commands during teardown.
        for widget in self.findChildren(QtWidgets.QWidget):
            if _qt_object_valid(widget):
                widget.blockSignals(True)

    def _remove_scene_hooks(self, include_exit=False):
        # Idempotent: remove stored identities before invoking Maya cleanup APIs.
        jobs, self._jobs = self._jobs, []
        callback, self._save_callback = self._save_callback, None
        if not _maya_is_exiting():
            for job in jobs:
                try:
                    if cmds.scriptJob(exists=job):
                        cmds.scriptJob(kill=job, force=True)
                except RuntimeError:
                    pass
            if callback is not None:
                try:
                    om.MMessage.removeCallback(callback)
                except RuntimeError:
                    pass
        if include_exit:
            callback, self._exit_callback = self._exit_callback, None
            if callback is not None and not _maya_is_exiting():
                try:
                    om.MMessage.removeCallback(callback)
                except RuntimeError:
                    pass
            app = getattr(self, "_qt_app", None)
            if _qt_object_valid(app):
                try:
                    app.aboutToQuit.disconnect(self._on_maya_exiting)
                except (RuntimeError, TypeError):
                    pass

    def _discard_pages(self, shutdown=False):
        # Remove every page from the Qt stack BEFORE native hosts may be deleted.
        pages, self._pages = self._pages, {}
        for page in pages.values():
            if _qt_object_valid(page):
                # removeWidget()/hide() can release keyboard focus. Quiesce
                # each page first during both close and scene-page replacement.
                page.blockSignals(True)
                for widget in page.findChildren(QtWidgets.QWidget):
                    if _qt_object_valid(widget):
                        widget.blockSignals(True)
                for timer in page.findChildren(QtCore.QTimer):
                    if _qt_object_valid(timer):
                        timer.stop()
        for page in pages.values():
            if _qt_object_valid(page):
                self.stack.removeWidget(page)
        restored = self.unified_tool.dispose(shutdown=shutdown)
        for key, page in pages.items():
            if key in self.unified_tool.BUILDERS or not _qt_object_valid(page):
                continue
            page.hide()
            if not shutdown:
                page.deleteLater()  # Only Python-created Qt pages use Qt deletion.
        return restored

    def _reload_scene_pages(self):
        if self._closed or _maya_is_exiting():
            return
        if not self._discard_pages():
            self._reset_pending = False
            self.status.setText("Native UI owner was lost. Restart Maya before reopening this toolkit.")
            return
        self.unified_tool = EmbeddedUnifiedRiggingToolkit()
        self._reset_pending = False
        self._navigation_changed(self.navigation.currentItem(), None)

    def _on_maya_exiting(self, *_args):
        self._shutdown_state["exiting"] = True
        if self._cleanup_done or not _qt_object_valid(self):
            return
        self._closed = True
        self._cleanup_done = True
        self._quiesce_ui()
        # Native owners still exist at kMayaExiting. Restore Qt parenting, but
        # perform NO deleteUI, scene cache writes, or callback-removal commands.
        self._discard_pages(shutdown=True)

    def _finish_close(self):
        if self._cleanup_done or not _qt_object_valid(self):
            return
        if _maya_is_exiting():
            self._on_maya_exiting()
            return
        restored = self._discard_pages()
        if not restored:
            # Keep the shell and its exit hook alive; do not destroy orphaned
            # Maya-owned controls from a Qt parent destructor.
            return
        self._remove_scene_hooks(include_exit=True)
        self._cleanup_done = True
        self.deleteLater()

    def closeEvent(self, event):
        if self._closed:
            event.accept()
            return
        # The previous implementation set this AFTER destructive cleanup.
        # Mark closed first to suppress reentrant scene/UI callbacks.
        self._closed = True
        panels = [panel for panel in self._cached_panels() if _qt_object_valid(panel)]
        if not _maya_is_exiting():
            # Commit typed cache values before suppressing focus-loss signals.
            # Only cache editors are interpreted, not scene-editing guide fields.
            for panel in panels:
                for editor in panel.findChildren(QtWidgets.QAbstractSpinBox):
                    if _qt_object_valid(editor):
                        editor.interpretText()
        pending_caches = [panel for panel in panels if panel._cache_timer.isActive()]
        self._quiesce_ui()
        if _maya_is_exiting():
            self._on_maya_exiting()
            event.accept()
            return
        self._remove_scene_hooks()
        try:
            if not self._reset_pending:
                for panel in pending_caches:
                    # Timers have already stopped, so flush captured dirty panels
                    # explicitly instead of testing isActive() again.
                    panel._save_pending_cache()
            self._settings.setValue("geometry", self.saveGeometry())
            self._settings.setValue("active_workflow", self._active_key)
        except (RuntimeError, ValueError, TypeError) as exc:
            if not _maya_is_exiting():
                cmds.warning("Toolkit close settings could not be saved: {}".format(exc))
        finally:
            # No parent changes, deleteUI, or QWidget destruction in closeEvent.
            QtCore.QTimer.singleShot(0, self._finish_close)
            event.accept()


# ==============================================================================
# LAUNCH
# ==============================================================================
def show():
    """Open one window, without invoking a legacy window's unsafe close handler."""
    global _master_rig_ui
    state = _install_maya_shutdown_guard()
    if state["exiting"]:
        raise RuntimeError("Maya is shutting down; the toolkit cannot be opened.")
    app = QtWidgets.QApplication.instance()
    candidates = []
    for widget in app.topLevelWidgets():
        if _qt_object_valid(widget) and widget.objectName() == "MasterRiggingToolkit":
            candidates.append(widget)
    previous = globals().get("_master_rig_ui")
    if _qt_object_valid(previous) and previous not in candidates:
        candidates.append(previous)
    for widget in candidates:
        if widget.property("rtkLifecycleVersion") != "2.4":
            # Original native parents were not recorded in earlier revisions.
            # Calling that version's close() can invoke the unsafe teardown.
            raise RuntimeError("An earlier Rigging Toolkit window is still loaded. Restart Maya once before loading this crash-fix version.")
    for widget in candidates:
        widget.close()
    _master_rig_ui = MasterRiggingUI()
    _master_rig_ui.show()
    _master_rig_ui.raise_()
    _master_rig_ui.activateWindow()
    return _master_rig_ui


if __name__ == "__main__":
    show()
