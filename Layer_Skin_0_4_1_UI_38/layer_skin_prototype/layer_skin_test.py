"""Layer Skin 0.4.1 Python Maya plug-in. Load this file, then cmds.rtkLayerSkin(action='ui')."""
import array
import hashlib
import importlib.util
import json
import os
import sys
from collections import OrderedDict

import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma

VERSION = "0.4.1"
core = None
_modules = {}
_decoded = OrderedDict()
_composed = OrderedDict()


def sibling(name):
    if name not in _modules:
        shared_name='_rtk_'+name+'_041'
        if name in ('layer_skin_assignment','layer_skin_artisan','layer_skin_relax') and shared_name in sys.modules:
            _modules[name]=sys.modules[shared_name];return _modules[name]
        filename = os.path.join(os.path.dirname(_load_core().__file__), name+'.py')
        if not os.path.isfile(filename):raise ImportError('Missing '+name+'.py. Extract the complete Layer Skin 0.4.1 folder.')
        spec = importlib.util.spec_from_file_location('_rtk_'+name+'_041',filename)
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module);_modules[name]=module
        if name in ('layer_skin_assignment','layer_skin_artisan','layer_skin_relax'):sys.modules[shared_name]=module
    return _modules[name]


def state_cost(state):
    return sibling('layer_skin_performance').state_cost(state)


def remember(raw,state,weights=None):
    key=hashlib.sha256(raw.encode()).hexdigest();cost=state_cost(state)
    _decoded.pop(key,None)
    if cost<=64*1024*1024:
        while _decoded and (len(_decoded)>=3 or sum(v[1] for v in _decoded.values())+cost>64*1024*1024):_decoded.popitem(last=False)
        _decoded[key]=(state,cost)
    if weights is not None:
        _composed.clear()
        if cost<=64*1024*1024:_composed[id(state)]=(state,weights)


def expected_weights(state):
    cached=_composed.get(id(state))
    if cached and cached[0] is state:return cached[1]
    values=core.composite(state);_composed.clear()
    if state_cost(state)<=64*1024*1024:_composed[id(state)]=(state,values)
    return values


def _load_core(plugin_path=None, required=True):
    """Find the sibling module even when Maya doesn't define __file__."""
    global core
    if core is not None:
        return core
    for location in (plugin_path, globals().get("__file__"), _load_core.__code__.co_filename):
        if not location or not (os.path.isfile(location) or os.path.isdir(location)):
            continue
        directory = location if os.path.isdir(location) else os.path.dirname(os.path.abspath(location))
        filename = os.path.join(directory, "layer_skin_core.py")
        if not os.path.isfile(filename):
            continue
        spec = importlib.util.spec_from_file_location("rtk_layer_skin_core_01", filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        core = module
        return core
    if required:
        raise ImportError("Layer Skin cannot find layer_skin_core.py beside the plug-in. Extract the complete layer_skin_prototype folder and keep its Python files together.")
    return None


# Normal imports can use the helpers immediately. Maya may require its
# authoritative loadPath, which is available only inside initializePlugin.
_load_core(required=False)
COMMAND = "rtkLayerSkin"
STATE = "rtkLayerSkinData"
WINDOW = "rtkLayerSkinPrototypeWindow"


def maya_useNewAPI():
    pass


def obj(name):
    selection = om.MSelectionList(); selection.add(name)
    return selection.getDependNode(0)


def topology(mesh):
    counts, indices = mesh.getVertices()
    digest = hashlib.sha256()
    digest.update(str(mesh.numVertices).encode("ascii"))
    for values in (counts, indices):
        digest.update(array.array('q', values).tobytes())
    return digest.hexdigest()


def context(target):
    return sibling('layer_skin_memory').context(globals(),target)


context._layer_skin_native_context=True


def metadata(ctx):
    candidates = []
    for node in cmds.listConnections(ctx["skin"]+".message", source=False, destination=True, type="network") or []:
        if cmds.attributeQuery(STATE, node=node, exists=True):
            candidates.append(node)
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) > 1:
        raise ValueError("Multiple layer data nodes found; resolve the duplicate setup first.")
    if not candidates:
        return None, None
    node = candidates[0]
    linked = cmds.listConnections(node+".mesh", source=True, destination=False, shapes=True) or []
    if len(linked) != 1 or obj(linked[0]) != ctx["dag"].node():
        raise ValueError("Layer mesh ownership link changed.")
    raw=cmds.getAttr(node+"."+STATE);ctx['raw_metadata']=raw;key=hashlib.sha256(raw.encode()).hexdigest()
    state=_decoded[key][0] if key in _decoded else core.decode(raw)
    if state["vertex_count"] != ctx["count"] or state["topology"] != ctx["topology"]:
        raise ValueError("Mesh topology changed. Restore the original topology before editing.")
    if key not in _decoded:remember(raw,state)
    return node, core.remap(state,ctx['ids'])


def selected_vertices(ctx, whole=False):
    if whole:
        return list(range(ctx["count"]))
    result = set(); selection = om.MGlobal.getActiveSelectionList()
    for i in range(selection.length()):
        try:
            path, component = selection.getComponent(i)
        except RuntimeError:
            continue
        if component.isNull():
            continue
        if path.node().hasFn(om.MFn.kTransform):
            path.extendToShape()
        if path.node() != ctx["dag"].node() or not component.hasFn(om.MFn.kMeshVertComponent):
            raise ValueError("Select only vertices on the loaded mesh, or enable Whole mesh.")
        result.update(om.MFnSingleIndexedComponent(component).getElements())
    if not result:
        raise ValueError("Select mesh vertices, or enable Whole mesh explicitly.")
    return sorted(result)


def same(a, b, tolerance=1e-7):
    return sibling('layer_skin_performance').same(a,b,tolerance)


def state_hash(ctx,state):
    return sibling('layer_skin_performance').state_hash(globals(),ctx,state)


def reference_joint_paths(ctx):
    """Read bound joints and unbound descendants without changing the scene."""
    # Include currently unbound descendants at the same frozen pose. They can
    # be painted or assigned later without mixing animated frames with old points.
    paths={path.fullPathName():path for path in ctx['influences']}
    for root in joint_roots(ctx):
        for name in [root]+(cmds.listRelatives(root,allDescendents=True,type='joint',fullPath=True) or []):
            if name not in paths:
                selection=om.MSelectionList();selection.add(name);paths[name]=selection.getDagPath(0)
    return list(paths.values())


def reference_capture(ctx):
    """Capture consistent visible geometry and joint frames at the current pose."""
    return sibling('layer_skin_assignment_scene').capture_reference(globals(),ctx)


def prepare_edit(ctx,meta,state,action,data):
    if state is None:
        if action not in ('add','initialize'):raise ValueError('Add a layer first.')
        state=core.create(ctx['weights'],ctx['count'],ctx['ids'],ctx['topology'])
    elif action=='initialize':raise ValueError('This mesh already has layers.')
    if action not in ('bake','restore') and not same(ctx['weights'],expected_weights(state),2e-6):
        raise ValueError('Weights changed outside Layer Skin. Use Cleanup > Remove saved layers to keep them, then add a layer again.')
    if data.get('expected') and data['expected']!=state_hash(ctx,state):
        raise ValueError('Layer data changed during the stroke. The unfinished stroke was discarded.')
    if action in ('bake','restore'):
        return state,list(range(ctx['count'])) if action=='restore' else [],False
    if action=='initialize':return state,[],False
    if action=='relax':return sibling('layer_skin_relax').prepare(ctx,state,data,core,om)
    if action=='relax_stroke':return sibling('layer_skin_relax').prepare_stroke(ctx,state,data,core)
    if action=='value_operation':return sibling('layer_skin_operations').prepare(ctx,state,data,core,selected_vertices)
    dirty=[];reused=False
    if action=='reference':
        data['reference']=reference_capture(ctx)
    if action=='assign':
        layer=next((row for row in state['layers'] if row['id']==data.get('layer')),None)
        if not layer:raise ValueError('Select a layer before assigning.')
        joints=data.get('joints',layer.get('joints',[]))
        if not isinstance(joints,list) or not joints or any(not isinstance(identity,str) or identity not in ctx['ids'] for identity in joints):
            raise ValueError('Choose joints in the hierarchy before assigning.')
        joints=list(dict.fromkeys(joints))
        if state.get('reference') is None:state=core.edit(state,'reference',{'reference':reference_capture(ctx)})
        state=sibling('layer_skin_assignment_scene').ensure_reference(globals(),ctx,state)
        scope=selected_vertices(ctx,bool(data.get('whole',True)))
        settings=dict(data.get('settings',{}))
        import maya.OpenMaya as legacy
        interrupt=legacy.MComputation();interrupt.beginComputation(False,True,False)
        try:
            def check():
                if interrupt.isInterruptRequested():raise RuntimeError('Assignment cancelled before weight writes.')
            generated,info=sibling('layer_skin_assignment').CACHE.generate(state['reference'],ctx['ids'],joints,settings,scope,check)
        finally:interrupt.endComputation()
        reused=info.pop('reused');info['joints']=joints;data.update(generated=generated,assignment=info,scope=scope)
        if layer['enabled'] and layer['opacity']:
            old_gen=layer.get('generated',{})
            samples={} if data.get('replace_manual') else layer['samples']
            candidates=old_gen.keys()|generated.keys()|(layer['samples'].keys() if data.get('replace_manual') else set())
            if len(scope)==ctx['count']:
                dirty=sorted(int(v) for v in candidates if v not in samples and (v in layer['samples'] or old_gen.get(v)!=generated.get(v)))
            else:
                scope_keys={str(v) for v in scope}
                dirty=sorted(int(v) for v in (candidates&scope_keys) if v not in samples and (v in layer['samples'] or old_gen.get(v)!=generated.get(v)))
    if action in ('flood','mask','clear'):
        data['vertices']=selected_vertices(ctx,bool(data.get('whole',False)));dirty=data['vertices']
        layer=next((row for row in state['layers'] if row['id']==data.get('layer')),None)
        active=bool(layer and layer['enabled'] and layer['opacity'])
        if action=='flood':
            joint=data.get('joint') or ctx['ids'][int(data['influence'])]
            if layer:
                return core.edit(state,'paint',dict(layer=layer['id'],mode='weights',joint=joint,
                                 values={str(v):data['value'] for v in dirty})),(dirty if active else []),False
            if not active:dirty=[]
        elif action=='mask' and layer:
            active_keys=layer.get('generated',{}).keys()|layer['samples'].keys()
            dirty=[v for v in dirty if str(v) in active_keys] if active else []
        elif action=='clear' and layer:
            dirty=[v for v in dirty if str(v) in layer['samples']] if active else []
    elif action=='paint':
        layer=next((row for row in state['layers'] if row['id']==data.get('layer')),None)
        if not layer or (layer['enabled'] and layer['opacity']):
            dirty=sorted(int(key) for key in data['values'])
    elif action=='reorder':
        order=data.get('order')
        expected=[row['id'] for row in state['layers']]
        if isinstance(order,list) and len(order)==len(expected) and len(set(order))==len(order) and set(order)==set(expected) and order!=expected:
            rank={identity:i for i,identity in enumerate(order)}
            active=[(rank[layer['id']],layer.get('generated',{}).keys()|layer['samples'].keys())
                    for layer in state['layers'] if layer['enabled'] and layer['opacity']]
            affected=set()
            for i,(ra,ka) in enumerate(active):
                for rb,kb in active[i+1:]:
                    if ra>rb:
                        affected|=ka&kb
            dirty=sorted(int(key) for key in affected)
    elif action=='properties':
        layer=next((row for row in state['layers'] if row['id']==data.get('layer')),None)
        if layer:
            new_opacity=core.unit(data.get('opacity',layer['opacity']))
            new_enabled=data.get('enabled',layer['enabled'])
            old_active=layer['enabled'] and bool(layer['opacity'])
            new_active=bool(new_enabled) and bool(new_opacity)
            if (old_active or new_active) and (new_opacity!=layer['opacity'] or new_enabled!=layer['enabled']):
                dirty=sorted(int(key) for key in (layer.get('generated',{}).keys()|layer['samples'].keys()))
    elif action=='delete':
        layer=next((row for row in state['layers'] if row['id']==data.get('layer')),None)
        if layer and layer['enabled'] and layer['opacity']:
            dirty=sorted(int(key) for key in (layer.get('generated',{}).keys()|layer['samples'].keys()))
    elif action=='move':
        index=next((i for i,row in enumerate(state['layers']) if row['id']==data.get('layer')),None)
        if index is not None:
            dest=index+int(data.get('direction',0))
            if 0<=dest<len(state['layers']):
                la,lb=state['layers'][index],state['layers'][dest]
                if la['enabled'] and la['opacity'] and lb['enabled'] and lb['opacity']:
                    ka=la.get('generated',{}).keys()|la['samples'].keys()
                    kb=lb.get('generated',{}).keys()|lb['samples'].keys()
                    dirty=sorted(int(key) for key in (ka&kb))
    state=core.edit(state,action,data)
    # Preserve a newly captured reference even when no vertices are in range.
    return state,dirty,reused


def preflight(ctx, meta, before, after, candidates=None):
    return sibling('layer_skin_performance').preflight(globals(),ctx,meta,before,after,candidates)


class LayerCommand(om.MPxCommand):
    @staticmethod
    def creator():
        return LayerCommand()

    @staticmethod
    def syntax():
        syntax = om.MSyntax()
        syntax.addFlag("-a", "-action", om.MSyntax.kString)
        syntax.addFlag("-d", "-data", om.MSyntax.kString)
        return syntax

    def isUndoable(self):
        return getattr(self, "undoable", False)

    def doIt(self, args):
        arguments = om.MArgDatabase(self.syntax(), args)
        action = arguments.flagArgumentString("-action", 0) if arguments.isFlagSet("-action") else "ui"
        if action == "ui":
            show_ui(); return
        if not cmds.undoInfo(query=True, state=True):
            raise ValueError("Enable Maya Undo before editing layers.")
        data = json.loads(arguments.flagArgumentString("-data", 0)) if arguments.isFlagSet("-data") else {}
        self.ctx = context(data.get("target", ""))
        meta, state = metadata(self.ctx)
        before_full = self.ctx['weights']
        self.mods = []; self.skip_create_once = False
        state, dirty, reused = prepare_edit(self.ctx,meta,state,action,data)
        raw=core.encode(state)
        if meta and action not in ('bake','restore') and raw==(self.ctx['raw_metadata'] if 'raw_metadata' in self.ctx else cmds.getAttr(meta+'.'+STATE)):
            self.undoable=False;self.setResult('Layer Skin: unchanged (cached assignment reused)' if reused else 'Layer Skin: unchanged');return
        if action == 'restore':after_full=state['base']
        elif dirty and len(dirty)==self.ctx['count'] and dirty==list(range(self.ctx['count'])):
            after_full=core.composite(state)
        else:
            after_full=core.storage().copy_values(before_full) if dirty else before_full
            if dirty:
                values=core.composite_vertices(state,dirty)
                width=len(self.ctx['ids'])
                for i,v in enumerate(dirty):after_full[v*width:(v+1)*width]=values[i*width:(i+1)*width]
        self.vertices = preflight(self.ctx, meta, before_full, after_full, dirty)
        width=len(self.ctx['ids']);self.snap_ids=list(self.ctx['ids'])
        self.before=core.storage().snapshot_rows(before_full,self.vertices,width)
        self.after=core.storage().snapshot_rows(after_full,self.vertices,width)
        self.component = None
        if self.vertices:
            self.component = om.MFnSingleIndexedComponent().create(om.MFn.kMeshVertComponent)
            om.MFnSingleIndexedComponent(self.component).addElements(self.vertices)
        if not meta:
            create = om.MDGModifier(); node = create.createNode("network")
            create.renameNode(node, "rtkLayerSkinData#")
            typed = om.MFnTypedAttribute(); state_attr = typed.create(STATE, "rlsd", om.MFnData.kString)
            create.addAttribute(node, state_attr)
            for name, short in (("skin", "sk"), ("mesh", "me")):
                create.addAttribute(node, om.MFnMessageAttribute().create(name, short))
            try:
                create.doIt()
            except Exception:
                try:
                    create.undoIt()
                except Exception as recovery:
                    om.MGlobal.displayError("Initialization rollback could not finish: " + str(recovery))
                raise
            self.mods.append(create); self.skip_create_once = True
            try:
                fn = om.MFnDependencyNode(node); modifier = om.MDGModifier()
                modifier.connect(self.ctx["fn"].findPlug("message", False), fn.findPlug("skin", False))
                modifier.connect(om.MFnDependencyNode(self.ctx["dag"].node()).findPlug("message", False), fn.findPlug("mesh", False))
                modifier.newPlugValueString(fn.findPlug(STATE, False), raw)
                self.mods.append(modifier)
            except Exception:
                create.undoIt(); raise
        else:
            modifier = om.MDGModifier()
            if action in ("bake", "restore"):
                modifier.deleteNode(obj(meta))
            else:
                modifier.newPlugValueString(om.MFnDependencyNode(obj(meta)).findPlug(STATE, False), raw)
            self.mods.append(modifier)
        self.ctx={key:self.ctx[key] for key in ('shape','skin','fn','dag','count','ids','topology')}
        self.undoable = True
        self.redoIt()
        if action not in ('bake','restore'):remember(raw,state,after_full)
        else:_decoded.clear();_composed.clear()
        self.setResult("Layer Skin: " + action + (' (assignment cache reused)' if reused else ''))

    def write(self, weights):
        return sibling('layer_skin_memory').write_weights(self,weights,globals())

    def redoIt(self):
        applied = []
        try:
            for i, modifier in enumerate(self.mods):
                applied.append(modifier)
                # The initial node/attribute creation made plugs available for planning.
                if not (i == 0 and self.skip_create_once):
                    modifier.doIt()
            self.skip_create_once = False
            self.write(self.after)
        except Exception:
            self.skip_create_once = False
            try:
                self.write(self.before)
            finally:
                for modifier in reversed(applied):
                    modifier.undoIt()
            self.undoable = False
            raise

    def undoIt(self):
        undone = []
        try:
            self.write(self.before)
            for modifier in reversed(self.mods):
                modifier.undoIt(); undone.append(modifier)
        except Exception:
            for modifier in reversed(undone):
                modifier.doIt()
            self.write(self.after)
            raise


_ui_module = None


def inspect_ui(ui):
    ctx = context(ui.target.text().strip())
    identity=ui.active_joint()
    if identity not in ctx['ids']:
        raise ValueError("Choose an influence first.")
    column=ctx['ids'].index(identity)
    if not ui.ctx or ui.ctx["ids"] != ctx["ids"]:
        raise ValueError("Influence order changed. Refresh first.")
    vertices = selected_vertices(ctx, ui.whole.isChecked())
    width = len(ctx["ids"])
    weights = [ctx["weights"][v*width+column] for v in vertices]
    ui.message("{} vertices · {} · final skin weight min {:.4f}, max {:.4f}, mean {:.4f}".format(
        len(vertices), ctx["influences"][column].partialPathName(), min(weights), max(weights), sum(weights)/len(weights)))


def show_ui():
    global _ui_module
    from types import SimpleNamespace
    if _ui_module is None:
        filename = os.path.join(os.path.dirname(_load_core().__file__), "layer_skin_ui.py")
        if not os.path.isfile(filename):
            raise ImportError("Missing layer_skin_ui.py. Replace the complete Layer Skin 0.4.1 folder.")
        spec = importlib.util.spec_from_file_location("_rtk_layer_skin_ui_041", filename)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        _ui_module = module
    return _ui_module.show(editor_api())


def editor_api():
    from types import SimpleNamespace
    import maya.mel as mel
    sibling('layer_skin_memory').install(globals())
    sibling('layer_skin_assignment_scene').install(globals())
    sibling('layer_skin_io_backend').install(globals())
    sibling('layer_skin_performance').install(globals())
    sibling('layer_skin_paint_commit').install(globals())
    api = SimpleNamespace(cmds=cmds,om=om,mel=mel,obj=obj,same=same,core=core,context=context,metadata=metadata,
                          inspect=inspect_ui,VERSION=VERSION,WINDOW=WINDOW,roots=joint_roots,joint_id=joint_id,
                          clear_cache=clear_cache,cache_stats=lambda:sibling('layer_skin_assignment').CACHE.stats(),
                          state_hash=state_hash,paint_context='rtkLayerSkinPaint041',
                          plugin_details=lambda:sibling('layer_skin_launch').registered_plugin(cmds))
    api._layer_skin_command_owner=globals()
    api.commit_paint=lambda data,scope:sibling('layer_skin_paint_commit').commit(globals(),data,scope)
    api.commit_edit=lambda action,data,scope:sibling('layer_skin_paint_commit').commit(globals(),data,scope,action)
    api.make_session=lambda:sibling('layer_skin_session').Session(api)
    api.make_paint_buffer=lambda mesh:sibling('layer_skin_artisan').get_buffer(api,mesh)
    api.make_joint_tree=lambda parent,selected:sibling('layer_skin_joint_view').JointTree(api,parent,selected,sibling('layer_skin_session').protect_browser_widget)
    return api


def joint_id(path):return om.MFnDependencyNode(obj(path)).uuid().asString()


def joint_roots(ctx):
    return sibling('layer_skin_assignment_scene').joint_roots(globals(),ctx)


def clear_cache():
    _decoded.clear();_composed.clear()
    runtime=globals().get('_layer_skin_performance_runtime')
    if runtime is not None:runtime['hashes'].clear()
    if 'layer_skin_assignment' in _modules:_modules['layer_skin_assignment'].CACHE.clear()
    if 'layer_skin_relax' in _modules:_modules['layer_skin_relax'].CACHE.clear()


def initializePlugin(plugin):
    fn = om.MFnPlugin(plugin, "RTK", VERSION, "Any")
    _load_core(fn.loadPath())
    fn.registerCommand(COMMAND, LayerCommand.creator, LayerCommand.syntax)


def uninitializePlugin(plugin):
    if _ui_module is not None:
        _ui_module.close_dialog()
    clear_cache()
    om.MFnPlugin(plugin).deregisterCommand(COMMAND)
