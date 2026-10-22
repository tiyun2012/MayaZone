"""Mesh-scoped authoring cleanup. Never decodes state or reads/writes skin weights.

Saved data is removed using Maya's native undoable delete command. Live paint
arrays are retained because Artisan Undo can still reference them.
"""
import sys
import uuid

STATE='rtkLayerSkinData'
ATTRIBUTES={STATE,'skin','mesh'}


def _one(cmds,name):
    nodes=list(dict.fromkeys(cmds.ls(name,long=True,objectsOnly=True) or []))
    if len(nodes)!=1:raise ValueError('Choose one mesh for cleanup; its name must be unambiguous.')
    return nodes[0]


def _identity(api,name):
    node=api.obj(name);fn=api.om.MFnDependencyNode(node)
    return dict(uuid=fn.uuid().asString(),handle=api.om.MObjectHandle(node))


def _valid(record):return record['handle'].isValid() and record['handle'].isAlive()


def _source(cmds,plug):
    return cmds.listConnections(plug,source=True,destination=False,plugs=True) or []


def inspect(api,target):
    """Inspect only explicit mesh/skin message links, not all scene networks."""
    if not target:raise ValueError('Load a mesh before opening its saved-data cleanup.')
    cmds=api.cmds;node=_one(cmds,target)
    if cmds.nodeType(node)=='mesh':shape=node
    elif cmds.nodeType(node)=='transform':
        shapes=[p for p in cmds.listRelatives(node,shapes=True,noIntermediate=True,fullPath=True) or [] if cmds.nodeType(p)=='mesh']
        if len(shapes)!=1:raise ValueError('Choose a transform with exactly one polygon mesh shape.')
        shape=shapes[0]
    else:raise ValueError('Cleanup requires a polygon mesh.')
    plan=dict(mesh=shape,identity=_identity(api,shape),nodes=[],skipped=[])
    history=cmds.listHistory(shape,pruneDagObjects=True) or []
    skins=list(dict.fromkeys(cmds.ls(history,type='skinCluster',long=True) or [])) if history else []
    skin_ids={_identity(api,p)['uuid'] for p in skins}
    candidates=set()
    for owner in [shape]+skins:
        for plug in cmds.listConnections(owner+'.message',source=False,destination=True,type='network',plugs=True) or []:
            candidates.add(_one(cmds,plug.split('.',1)[0]))
    for name in sorted(candidates):
        if cmds.nodeType(name)!='network' or not cmds.attributeQuery(STATE,node=name,exists=True):continue
        linked=_source(cmds,name+'.mesh') if cmds.attributeQuery('mesh',node=name,exists=True) else []
        if len(linked)!=1:
            plan['skipped'].append(dict(node=name,reason='No single mesh ownership link.'))
            continue
        source=linked[0].split('.',1)
        if len(source)!=2 or source[1]!='message':
            plan['skipped'].append(dict(node=name,reason='Unrecognized mesh ownership link.'));continue
        if _identity(api,source[0])['uuid']!=plan['identity']['uuid']:continue
        record=dict(node=name,identity=_identity(api,name),blocked=[])
        reasons=record['blocked']
        try:
            if set(cmds.listAttr(name,userDefined=True) or [])!=ATTRIBUTES:
                reasons.append('Unexpected custom attributes; node was customized or is from another schema.')
            for attr,kind in ((STATE,'string'),('skin','message'),('mesh','message')):
                if not cmds.attributeQuery(attr,node=name,exists=True) or cmds.getAttr(name+'.'+attr,type=True)!=kind:
                    reasons.append('Unrecognized '+attr+' attribute.')
                elif cmds.getAttr(name+'.'+attr,lock=True):reasons.append(attr+' attribute is locked.')
            if cmds.referenceQuery(name,isNodeReferenced=True):reasons.append('Data node is referenced.')
            if any(cmds.lockNode(name,query=True,lock=True) or []):reasons.append('Data node is locked.')
            skin=_source(cmds,name+'.skin') if cmds.attributeQuery('skin',node=name,exists=True) else []
            allowed={('mesh',plan['identity']['uuid'],'message')}
            if len(skin)>1:reasons.append('Multiple skin ownership links.')
            elif skin:
                parts=skin[0].split('.',1)
                skin_id=_identity(api,parts[0])['uuid']
                if len(parts)!=2 or parts[1]!='message' or skin_id not in skin_ids:
                    reasons.append('Skin ownership does not match this mesh history.')
                allowed.add(('skin',skin_id,parts[1] if len(parts)>1 else ''))
            record['skin']=skin[0].split('.',1)[0] if len(skin)==1 else None
            links=cmds.listConnections(name,source=True,destination=True,connections=True,plugs=True) or []
            if len(links)%2:reasons.append('Incomplete connection report.')
            for i in range(0,len(links)-1,2):
                own=links[i].split('.',1);other=links[i+1].split('.',1)
                if len(own)!=2 or len(other)!=2 or _identity(api,own[0])['uuid']!=record['identity']['uuid']:
                    reasons.append('Unrecognized external connection.');break
                key=(own[1],_identity(api,other[0])['uuid'],other[1])
                if key not in allowed:reasons.append('Unexpected connection on '+own[1]+'.');break
        except (RuntimeError,ValueError) as exc:reasons.append('Could not inspect data node: '+str(exc))
        plan['nodes'].append(record)
    return plan


def _same_plan(before,after):
    return before['identity']['uuid']==after['identity']['uuid'] and {
        row['identity']['uuid'] for row in before['nodes']}=={row['identity']['uuid'] for row in after['nodes']}


def validate(api,plan,target=None):
    """Recheck scene identity and ownership immediately before an action."""
    if not _valid(plan['identity']) or any(not _valid(row['identity']) for row in plan['nodes']):
        raise ValueError('The scene or data nodes changed. Refresh cleanup before removing saved layers.')
    fresh=inspect(api,plan['mesh'] if target is None else target)
    if not _same_plan(plan,fresh):raise ValueError('Saved layer data changed. Refresh cleanup before removing it.')
    nodes=fresh['nodes']
    blocked=[row['node']+': '+' '.join(row['blocked']) for row in nodes if row['blocked']]
    if blocked:raise ValueError('Cleanup stopped: '+'; '.join(blocked))
    return fresh


def remove(api,plan):
    """Delete only previewed owned metadata, with one native Undo and rollback."""
    fresh=validate(api,plan);nodes=fresh['nodes']
    if not nodes:return dict(removed=[],mesh=fresh['mesh'])
    cmds=api.cmds
    if not cmds.undoInfo(query=True,state=True):raise ValueError('Enable Maya Undo before removing saved layers.')
    chunk='LayerSkinCleanup_'+uuid.uuid4().hex
    failure=None;cmds.undoInfo(openChunk=True,chunkName=chunk)
    try:
        cmds.delete([row['node'] for row in nodes])
        if any(_valid(row['identity']) for row in nodes):raise RuntimeError('Maya did not remove every requested layer-data node.')
    except Exception as exc:failure=exc
    finally:cmds.undoInfo(closeChunk=True)
    if failure:
        if cmds.undoInfo(query=True,undoName=True)==chunk:
            cmds.undo()
            if any(not _valid(row['identity']) for row in nodes):
                raise RuntimeError('Cleanup rollback did not restore all data nodes. Inspect Maya Undo before continuing.') from failure
        elif any(not _valid(row['identity']) for row in nodes):
            raise RuntimeError('Cleanup failed and its Undo entry is unavailable. Inspect the data nodes before continuing.') from failure
        raise failure
    result=dict(removed=[row['node'] for row in nodes],mesh=fresh['mesh'])
    try:clear_caches(api)
    except Exception as exc:result['cache_warning']='Saved data was removed, but memory-cache cleanup failed: '+str(exc)
    return result


def clear_caches(api):
    """Drop transient caches, retaining saved layers and valid native Undo arrays."""
    api.clear_cache()
    function=getattr(api.clear_cache,'__func__',api.clear_cache)
    owner=getattr(api,'_layer_skin_command_owner',getattr(function,'__globals__',{}))
    modules=list(owner.get('_modules',{}).values())
    names={'layer_skin_assignment','layer_skin_relax','layer_skin_artisan',
           '_rtk_layer_skin_assignment_041','_rtk_layer_skin_relax_041','_rtk_layer_skin_artisan_041',
           '_rtk_layer_skin_geometry_binding_041'}
    modules += [module for name,module in list(sys.modules.items()) if name in names or
                (name.startswith('_rtk_layer_skin_authoring_') and name.endswith('_layer_skin_relax'))]
    for name in ('_decoded','_composed'):
        cache=owner.get(name)
        if cache is not None:cache.clear()
    seen=set();cleared=0;pruned=0
    for module in modules:
        if module is None or id(module) in seen:continue
        seen.add(id(module));cache=getattr(module,'CACHE',None)
        if callable(getattr(cache,'clear',None)):cache.clear();cleared+=1
        buffers=getattr(module,'_buffers',{})
        for key in list(buffers):
            if not buffers[key].valid():del buffers[key];pruned+=1
    return dict(cache_modules=cleared,invalid_buffer_references=pruned)
