"""One-ring Jacobi layer relaxation, topology cache and command integration.

No runtime solver. All iterations finish before one native layer command writes
weights/metadata. Input and output use existing sample/coverage schema 2.
"""
from collections import OrderedDict
import math
import time

EPS=1e-12
_RULES=None


def influence_rules():
    global _RULES
    if _RULES is None:
        import importlib.util
        import os
        spec=importlib.util.spec_from_file_location('_rtk_relax_influence_18',os.path.join(os.path.dirname(__file__),'layer_skin_influence.py'))
        _RULES=importlib.util.module_from_spec(spec);spec.loader.exec_module(_RULES)
    return _RULES


def sample_at(layer,vertex):
    key=str(vertex)
    return layer['samples'].get(key) or (layer.get('generated') or {}).get(key)


def contribution(sample):
    if not sample or sample['coverage']<=EPS:return {}
    return {j:w*sample['coverage'] for j,w in enumerate(sample['weights']) if w*sample['coverage']>EPS}


def relax_rows(state,layer_id,adjacency,vertices,iterations=3,strength=.5,max_new=0,joints=(),check=None,
               factors=None,preserve_coverage=False,initial_supports=None):
    """Compute sparse overrides. Only the scope and its one-ring halo are read."""
    if type(iterations) is not int or not 1<=iterations<=100:
        raise ValueError('Iterations must be an integer from 1 to 100.')
    if type(max_new) is not int or max_new<0:
        raise ValueError('Max new influences must be a nonnegative integer; 0 means unlimited.')
    strength=float(strength)
    if not math.isfinite(strength) or not 0.<=strength<=1.:raise ValueError('Relax strength must be between 0 and 1.')
    if type(preserve_coverage) is not bool:raise ValueError('Preserve coverage must be true or false.')
    n=state['vertex_count'];identities=state['influences'];width=len(identities)
    vertices=sorted(set(vertices))
    if any(type(v) is not int or not 0<=v<n for v in vertices):raise ValueError('Invalid relax vertices.')
    selected=list(dict.fromkeys(joints))
    if len(selected)>1 and any(j not in identities for j in selected):raise ValueError('A selected relax joint is not a skin influence.')
    columns={identity:i for i,identity in enumerate(identities)}
    subset={columns[j] for j in selected} if len(selected)>1 else None
    layer=next((row for row in state['layers'] if row['id']==layer_id),None)
    if layer is None:raise ValueError('Select an editable layer to relax.')
    locked=influence_rules().columns(state,layer) if layer.get('influence_locks') else set()
    if subset is not None:subset-=locked
    if not vertices or not strength:return {},[],set()
    graph={};needed=set(vertices);steps={}
    for v in vertices:
        neighbors=tuple(sorted(set(adjacency[v])))
        if any(type(u) is not int or not 0<=u<n or u==v for u in neighbors):raise ValueError('Invalid one-ring topology.')
        graph[v]=neighbors;needed.update(neighbors)
        factor=float(factors.get(v,0.)) if factors is not None else 1.
        if not math.isfinite(factor) or not 0<=factor<=1:raise ValueError('Brush factors must be between 0 and 1.')
        steps[v]=strength*factor
    field={v:contribution(sample_at(layer,v)) for v in needed}
    original={v:dict(field[v]) for v in vertices}
    supports={v:set(initial_supports[v]) if initial_supports is not None and v in initial_supports else set(original[v]) for v in vertices}
    operations=0
    for _ in range(iterations):
        if check:check()
        updates={};progress=False
        for v in vertices:
            operations+=1
            if check and operations & 255==0:check()
            neighbors=graph[v];step=steps[v]
            if not neighbors or not step:continue
            before=field[v];average={}
            for neighbor in neighbors:
                for col,value in field[neighbor].items():
                    if col not in locked and (subset is None or col in subset):average[col]=average.get(col,0.)+value/len(neighbors)
            if subset is None:
                editable={col:(1.-step)*before.get(col,0.)+step*average.get(col,0.) for col in before.keys()|average.keys() if col not in locked}
                fixed={col:value for col,value in original[v].items() if col in locked}
                budget=sum(value for col,value in original[v].items() if col not in locked) if preserve_coverage else min(sum(editable.values()),max(0.,1.-sum(fixed.values())))
                result=fixed
            else:
                budget=sum(value for col,value in original[v].items() if col in subset)
                total=sum(average.values())
                if budget<=EPS or total<=EPS:continue
                editable={col:(1.-step)*before.get(col,0.)+step*budget*average.get(col,0.)/total for col in subset}
                result={col:value for col,value in original[v].items() if col not in subset}
            editable={col:value for col,value in editable.items() if value>EPS}
            if max_new:
                added=sorted((col for col in editable if col not in supports[v]),key=lambda col:(-editable[col],identities[col]))
                for col in added[max_new:]:editable.pop(col)
            total=sum(editable.values())
            # At full strength an empty one-ring has no distribution to
            # normalize. Coverage preservation must retain the current row.
            if total<=EPS and budget>EPS and subset is None and preserve_coverage:
                editable={col:value for col,value in before.items() if col not in locked};total=sum(editable.values())
            if total<=EPS or budget<=EPS:editable={}
            else:editable={col:value*budget/total for col,value in editable.items()}
            result.update(editable)
            updates[v]=result
            if any(abs(result.get(col,0.)-before.get(col,0.))>EPS for col in result.keys()|before.keys()):progress=True
        field.update(updates)
        if not progress:break
    if check:check()
    changed=[v for v in vertices if any(abs(field[v].get(col,0.)-original[v].get(col,0.))>1e-10 for col in field[v].keys()|original[v].keys())]
    samples={};used=set()
    for v in changed:
        amounts=field[v];total=sum(amounts.values())
        if total>EPS:
            row=[amounts.get(j,0.)/total for j in range(width)];used.update(identities[j] for j in amounts)
        else:row=(sample_at(layer,v) or {'weights':[1.]+[0.]*(width-1)})['weights'][:]
        samples[str(v)]=dict(weights=row,coverage=min(1.,max(0.,total)))
    return samples,changed,used


def relax_samples(state,layer_id,adjacency,vertices,iterations=3,strength=.5,max_new=0,joints=(),check=None,
                  factors=None,preserve_coverage=False,initial_supports=None):
    samples,changed,used=relax_rows(state,layer_id,adjacency,vertices,iterations,strength,max_new,joints,check,
                                  factors,preserve_coverage,initial_supports)
    if not changed:return state,[]
    index=next(i for i,row in enumerate(state['layers']) if row['id']==layer_id);layer=state['layers'][index]
    result=dict(state,layers=list(state['layers']));updated=dict(layer,samples=dict(layer['samples']))
    result['layers'][index]=updated;updated['samples'].update(samples)
    updated['joints']=list(dict.fromkeys(layer.get('joints',[])+[j for j in state['influences'] if j in used]))
    return result,changed


def relax_mask_rows(mask,adjacency,vertices,iterations=1,strength=.5,factors=None,check=None):
    vertices=sorted(set(vertices));needed=set(vertices)
    for v in vertices:needed.update(adjacency[v])
    field={v:mask.get(str(v),1.) for v in needed};original={v:field[v] for v in vertices}
    for _ in range(iterations):
        if check:check()
        updates={}
        for index,v in enumerate(vertices):
            if check and not index%256:check()
            neighbors=adjacency[v];step=strength*(factors.get(v,0.) if factors is not None else 1.)
            if neighbors and step:updates[v]=field[v]+step*(sum(field[u] for u in neighbors)/len(neighbors)-field[v])
        field.update(updates)
    return {str(v):max(0.,min(1.,field[v])) for v in vertices if abs(field[v]-original[v])>1e-10}


class AdjacencyCache:
    def __init__(self,max_bytes=32*1024*1024,max_items=4):
        self.max_bytes=max_bytes;self.max_items=max_items;self.entries=OrderedDict();self.bytes=0;self._generation=0
    def clear(self):self.entries.clear();self.bytes=0;self._generation+=1
    def get(self,ctx,vertices,om,check=None):
        key=(ctx.get('uuid',ctx['shape']),ctx['topology'],ctx['count'])
        previous=self.entries.pop(key,({},0));rows,cost=previous;self.bytes-=cost
        iterator=None;answer={};generation=self._generation
        try:
            for i,v in enumerate(vertices):
                if check and i & 255==0:check()
                if v not in rows:
                    if iterator is None:iterator=om.MItMeshVertex(ctx['dag'])
                    iterator.setIndex(v)
                    row=tuple(iterator.getConnectedVertices())
                    rows[v]=row;cost+=100+len(row)*40
                answer[v]=rows[v]
        finally:
            # Count only newly queried rows. A tiny selection must not walk
            # every cached vertex after a previous whole-mesh operation.
            # Successfully read topology is also reusable after cancellation;
            # the action still raises and no weights are authored here.
            if generation==self._generation and rows and self.max_items>0 and cost<=self.max_bytes:
                while self.entries and (self.bytes+cost>self.max_bytes or len(self.entries)>=self.max_items):
                    _,(_,old)=self.entries.popitem(last=False);self.bytes-=old
                self.entries[key]=(rows,cost);self.bytes+=cost
        return answer


CACHE=AdjacencyCache()


def selected_scope(ctx,om,all_if_empty=True):
    selected=om.MGlobal.getActiveSelectionList();vertices=set()
    for i in range(selected.length()):
        try:path,component=selected.getComponent(i)
        except RuntimeError:continue
        if component.isNull():continue
        if path.node().hasFn(om.MFn.kTransform):path.extendToShape()
        if path.node()!=ctx['dag'].node():raise ValueError('Select only components on the loaded mesh for Relax.')
        if component.hasFn(om.MFn.kMeshVertComponent):
            vertices.update(om.MFnSingleIndexedComponent(component).getElements())
        elif hasattr(om.MFn,'kMeshEdgeComponent') and component.hasFn(om.MFn.kMeshEdgeComponent):
            mesh=om.MFnMesh(path)
            for edge in om.MFnSingleIndexedComponent(component).getElements():vertices.update(mesh.getEdgeVertices(edge))
        else:raise ValueError('Select vertices or edges on the loaded mesh for Relax. With no components selected, the whole mesh is relaxed.')
    if vertices:return sorted(vertices)
    return list(range(ctx['count'])) if all_if_empty else None


def prepare(ctx,state,data,core,om):
    layer=next((row for row in state['layers'] if row['id']==data.get('layer')),None)
    if layer is None:raise ValueError('Select an editable layer to relax.')
    mode=data.get('mode','weights')
    if mode not in ('mask','weights'):raise ValueError('Choose Weights or Mask for Relax.')
    if mode=='weights':
        authored=dict(layer.get('generated') or {});authored.update(layer['samples'])
        if not any(row['coverage']>EPS for row in authored.values()):return state,[],False
    iterations=data.get('iterations',3);strength=float(data.get('strength',.5))
    if type(iterations) is not int or not 1<=iterations<=100:raise ValueError('Iterations must be an integer from 1 to 100.')
    if not math.isfinite(strength) or not 0.<=strength<=1.:raise ValueError('Relax strength must be between 0 and 1.')
    import maya.OpenMaya as legacy
    vertices=selected_scope(ctx,om)
    interrupt=legacy.MComputation();interrupt.beginComputation(False,True,False)
    started=time.monotonic()
    try:
        def check():
            if interrupt.isInterruptRequested():raise RuntimeError('Relax cancelled before any skin writes.')
            if time.monotonic()-started>120.:raise RuntimeError('Relax time limit reached before any skin writes.')
        graph=CACHE.get(ctx,vertices,om,check)
        if mode=='mask':
            values=relax_mask_rows(layer['mask'],graph,vertices,iterations,strength,check=check)
            result=core.edit(state,'paint',dict(layer=layer['id'],mode='mask',values=values));changed=[int(v) for v in values]
        else:
            result,changed=relax_samples(state,data['layer'],graph,vertices,iterations,strength,
                                        data.get('max_new',0),data.get('joints',()),check,preserve_coverage=data.get('preserve_coverage',False))
        core.validate(result)
    finally:interrupt.endComputation()
    layer=next(row for row in result['layers'] if row['id']==data['layer'])
    return result,(changed if layer['enabled'] and layer['opacity'] else []),False


def prepare_stroke(ctx,state,data,core):
    """Commit a validated brush preview with the native command's usual guards."""
    index=next((i for i,row in enumerate(state['layers']) if row['id']==data.get('layer')),None)
    if index is None:raise ValueError('Select an editable layer to relax.')
    mode=data.get('mode');layer=state['layers'][index]
    if mode=='mask':
        values=data.get('values')
        if not isinstance(values,dict):raise ValueError('Invalid relaxed mask values.')
        result=core.edit(state,'paint',dict(layer=layer['id'],mode='mask',values=values))
        changed=[int(key) for key in values]
    elif mode=='weights':
        samples=data.get('samples')
        if not isinstance(samples,dict):raise ValueError('Invalid relaxed layer samples.')
        if layer.get('influence_locks'):
            rules=influence_rules();locked=rules.columns(state,layer);width=len(state['influences'])
            for key,candidate in samples.items():
                if rules.project(rules.row(layer,key),candidate,locked,width) is not candidate:
                    raise ValueError('Relax stroke would change a locked influence. Start a new stroke.')
        result=dict(state,layers=list(state['layers']));updated=dict(layer,samples=dict(layer['samples']))
        result['layers'][index]=updated;updated['samples'].update(samples)
        used={identity for sample in samples.values() if sample.get('coverage',0)>EPS
              for identity,value in zip(state['influences'],sample.get('weights',())) if value>EPS}
        updated['joints']=list(dict.fromkeys(layer.get('joints',[])+[j for j in state['influences'] if j in used]))
        core.validate(result);changed=[int(key) for key in samples]
    else:raise ValueError('Unknown Relax brush mode.')
    return result,(sorted(changed) if layer['enabled'] and layer['opacity'] else []),False


def replace_assignment_overrides(state,data,dirty):
    """Also works with the older loaded core during a warm UI update."""
    if type(data.get('replace_manual',False)) is not bool:raise ValueError('Replace painted edits must be true or false.')
    if not data.get('replace_manual'):return state,dirty
    index=next((i for i,row in enumerate(state['layers']) if row['id']==data.get('layer')),None)
    if index is None:return state,dirty
    layer=state['layers'][index];scope=data.get('scope');allowed=None if scope is None else {str(v) for v in scope}
    removed={key for key in layer['samples'] if allowed is None or key in allowed}
    if not removed:return state,dirty
    result=dict(state,layers=list(state['layers']))
    result['layers'][index]=dict(layer,samples={key:row for key,row in layer['samples'].items() if key not in removed})
    return result,sorted(set(dirty)|{int(key) for key in removed}) if layer['enabled'] and layer['opacity'] else dirty


def install(owner):
    """Extend a loaded command's planner; keep its MPxCommand class/Undo alive."""
    if not callable(owner.get('prepare_edit')):return False
    previous=owner['prepare_edit']
    original=getattr(previous,'_layer_skin_relax_original',previous)
    def planner(ctx,meta,state,action,data):
        if action not in ('relax','relax_stroke'):
            result,dirty,reused=original(ctx,meta,state,action,data)
            if action=='assign':result,dirty=replace_assignment_overrides(result,data,dirty)
            return result,dirty,reused
        # Use the existing planner for outside-edit and stale-stroke guards.
        validated,_,_=original(ctx,meta,state,'properties',dict(layer=data.get('layer'),expected=data.get('expected')))
        if action=='relax_stroke':return prepare_stroke(ctx,validated,data,owner['core'])
        return prepare(ctx,validated,data,owner['core'],owner['om'])
    planner._layer_skin_relax_original=original
    owner['prepare_edit']=planner
    return True
