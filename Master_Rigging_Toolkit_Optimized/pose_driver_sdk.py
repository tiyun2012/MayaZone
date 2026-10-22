"""Native one-driver SDK capture and explicit local-channel curve mirroring.

No callbacks, expressions or attribute locking. Public functions preflight a
whole action before mutation. SDK records are independent of PoseDriver rigs.
"""
import copy
import json
import math
import uuid
from contextlib import contextmanager
import maya.cmds as cmds

TAG='rtkPoseSDKVersion'
STATE='rtkPoseSDKState'
CHANNELS=tuple(base+axis for base in ('translate','rotate','scale') for axis in 'XYZ')
CURVES={'animCurveUA','animCurveUL','animCurveUU'}
RULES=('keep_delta','flip_delta','keep_values','skip')
INPUT_RULES=('keep','reverse')
_ACTIVE=False


def node(value):
    found=cmds.ls(value,long=True) or []
    if len(found)!=1:raise ValueError('Choose one existing, unambiguous object: '+str(value))
    return found[0]


def identity(value):return (cmds.ls(node(value),uuid=True) or [None])[0]


def resolve(value):
    found=cmds.ls(value,long=True) or []
    if len(found)!=1:raise ValueError('An SDK object is missing or ambiguous: '+str(value))
    return found[0]


def incoming(plug):return cmds.listConnections(plug,source=True,destination=False,plugs=True) or []


def plug_ref(plug):
    name,attr=plug.split('.',1);name=node(name)
    if not cmds.objExists(name+'.'+attr):raise ValueError('Attribute is missing: '+plug)
    return {'node':identity(name),'attr':cmds.attributeName(name+'.'+attr,long=True,leaf=False)}


def plug_name(ref):return resolve(ref['node'])+'.'+ref['attr']


def same(a,b):return plug_ref(a)==plug_ref(b)


def finite(value):
    value=float(value)
    if not math.isfinite(value):raise ValueError('SDK values must be finite.')
    return value


def editable(value):
    value=node(value)
    if cmds.referenceQuery(value,isNodeReferenced=True) or (cmds.lockNode(value,query=True,lock=True) or [False])[0]:
        raise ValueError('SDK object is referenced or locked: '+value)


def transform(value):
    value=node(value)
    if not cmds.objectType(value,isAType='transform'):raise ValueError('Choose a transform or joint: '+value)
    if len(cmds.ls(value,long=True,allPaths=True) or [])!=1:raise ValueError('Instanced transforms are not supported.')
    return value


def driver(value):
    if not isinstance(value,str) or '.' not in value:raise ValueError('Choose a pose weight plug, such as cone.poseWeightRaw.')
    ref=plug_ref(value);plug=plug_name(ref)
    if cmds.getAttr(plug,type=True) not in ('double','float'):raise ValueError('Choose a unitless float/double pose weight.')
    finite(cmds.getAttr(plug));return plug


def units():return {'linear':cmds.currentUnit(query=True,linear=True),'angle':cmds.currentUnit(query=True,angle=True)}


def convert(channel,value,source,destination):
    value=finite(value)
    if channel.startswith('rotate'):
        value=value if source['angle'] in ('rad','radian') else math.radians(value)
        return value if destination['angle'] in ('rad','radian') else math.degrees(value)
    if channel.startswith('translate'):
        cm={'mm':.1,'millimeter':.1,'cm':1,'centimeter':1,'m':100,'meter':100,'km':100000,'kilometer':100000,
            'in':2.54,'inch':2.54,'ft':30.48,'foot':30.48,'yd':91.44,'yard':91.44,'mi':160934.4,'mile':160934.4}
        return value*cm[source['linear']]/cm[destination['linear']]
    return value


def read(meta):
    meta=node(meta)
    if cmds.nodeType(meta)!='network' or not cmds.attributeQuery(TAG,node=meta,exists=True) or cmds.getAttr(meta+'.'+TAG)!='1':
        raise ValueError('Choose a PoseDriver SDK binding.')
    try:
        data=json.loads(cmds.getAttr(meta+'.'+STATE))
        if data['schema']!=1 or data['meta']!=identity(meta) or set(data['rows'])-set(CHANNELS):raise ValueError('Invalid SDK ownership')
        for channel,row in data['rows'].items():
            if row['rule'] not in RULES or row['input_rule'] not in INPUT_RULES or row['mirror_channel'] not in CHANNELS:raise ValueError('Invalid SDK mirror rule')
            if channel[:-1]!=row['mirror_channel'][:-1]:raise ValueError('Mirror channels must use the same units')
            finite(row['neutral']);finite(row['target_neutral'])
        curves=[r['curve'] for r in data['rows'].values() if r.get('curve')]
        if len(curves)!=len(set(curves)):raise ValueError('An SDK curve was assigned twice')
    except (KeyError,TypeError,ValueError) as exc:raise ValueError('SDK metadata is incomplete or changed: '+str(exc)) from exc
    return meta,data


def bindings():
    result=[]
    for n in cmds.ls(type='network') or []:
        if cmds.attributeQuery(TAG,node=n,exists=True):result.append(n)
    return result


def find(weight,driven):
    key=plug_ref(weight);target=identity(transform(driven));found=[]
    for meta in bindings():
        _,data=read(meta)
        if data['driver']==key and data['driven']==target:found.append(meta)
    if len(found)>1:raise ValueError('Duplicate SDK records found for this driver and transform.')
    return found[0] if found else None


def _cycle_check(weight,driven):
    """Conservative upstream plug traversal, including evaluated DAG inputs."""
    import maya.api.OpenMaya as om
    sel=om.MSelectionList();sel.add(weight);plug=sel.getPlug(0)
    iterator=om.MItDependencyGraph(plug,om.MFn.kInvalid,om.MItDependencyGraph.kUpstream,
                                 om.MItDependencyGraph.kDepthFirst,om.MItDependencyGraph.kPlugLevel)
    iterator.traversingOverWorldSpaceDependents=True
    target=identity(driven);visited=set()
    while not iterator.isDone():
        obj=iterator.currentNode()
        if obj.isNull():raise ValueError('Cannot inspect an unknown dependency in the driver graph.')
        fn=om.MFnDependencyNode(obj);uid=fn.uuid().asString()
        candidates={uid}
        if uid not in visited and obj.hasFn(om.MFn.kDagNode):
            # DAG parent dependencies are implicit and are not followed by the
            # DG iterator, even with world-space traversal enabled.
            for path in om.MDagPath.getAllPathsTo(obj):
                while path.length():
                    candidates.add(om.MFnDependencyNode(path.node()).uuid().asString());path.pop()
        visited.add(uid)
        if target in candidates:
            raise ValueError('This transform contributes to its own pose weight. Choose a separate SDK/offset transform to avoid a dependency cycle.')
        iterator.next()


def direct_curve(plug):
    """Only direct scalar native SDKs: reject blends, constraints and time curves."""
    inputs=incoming(plug)
    if not inputs:return None
    if len(inputs)!=1:raise ValueError('Several inputs drive '+plug)
    curve,attribute=inputs[0].split('.',1)
    if cmds.nodeType(curve) not in CURVES or attribute!='output':
        raise ValueError('Another driver or blend already uses '+plug+'. This version needs a direct SDK channel.')
    return node(curve)


def _check_curve(curve,weight,destination):
    editable(curve)
    inputs=incoming(curve+'.input')
    if len(inputs)!=1 or not same(inputs[0],weight):raise ValueError('SDK curve uses a different/missing driver: '+curve)
    consumers=cmds.listConnections(curve+'.output',source=False,destination=True,plugs=True) or []
    if len(consumers)!=1 or not same(consumers[0],destination):raise ValueError('SDK curve is shared or its driven connection changed: '+curve)


def _channel(driven,channel):
    if channel not in CHANNELS:raise ValueError('Only local transform TRS channels are supported.')
    destination=driven+'.'+channel;editable(driven)
    if cmds.getAttr(destination,lock=True) or cmds.getAttr(driven+'.'+channel[:-1],lock=True):raise ValueError('Driven channel is locked: '+destination)
    if cmds.connectionInfo(driven+'.'+channel[:-1],isExactDestination=True):raise ValueError('A compound driver uses '+destination)
    return destination


@contextmanager
def action(label):
    global _ACTIVE
    if _ACTIVE or not cmds.undoInfo(query=True,state=True):raise ValueError('Enable Undo and finish the current SDK action first.')
    name=label+'_'+uuid.uuid4().hex;_ACTIVE=True;opened=False
    try:
        cmds.undoInfo(openChunk=True,chunkName=name);opened=True
        try:yield
        except Exception as exc:
            cmds.undoInfo(closeChunk=True);opened=False
            if cmds.undoInfo(query=True,undoName=True)==name:
                cmds.undo();raise RuntimeError('SDK action was rolled back: '+str(exc)) from exc
            raise
    finally:
        if opened:cmds.undoInfo(closeChunk=True)
        _ACTIVE=False


def _new_data(weight,driven):
    return {'schema':1,'driver':plug_ref(weight),'driven':identity(driven),'meta':None,'rows':{},'units':units(),
            'mirror_driver':None,'mirror_driven':None}


def _write(meta,data):
    if meta is None:
        meta=cmds.createNode('network',name=':rtkPoseSDK_META#',skipSelect=True)
        cmds.addAttr(meta,longName=TAG,dataType='string');cmds.setAttr(meta+'.'+TAG,'1',type='string')
        cmds.addAttr(meta,longName=STATE,dataType='string')
        data['meta']=identity(meta)
    else:editable(meta)
    cmds.setAttr(meta+'.'+STATE,json.dumps(data),type='string');return meta


def _current_data(weight,driven):
    meta=find(weight,driven)
    if not meta:return None,_new_data(weight,driven)
    meta,data=read(meta);data=copy.deepcopy(data);now=units()
    for channel,row in data['rows'].items():
        row['neutral']=convert(channel,row['neutral'],data['units'],now)
        row['target_neutral']=convert(row['mirror_channel'],row['target_neutral'],data['units'],now)
    data['units']=now;return meta,data


def inspect(weight,driven):
    weight=driver(weight);driven=transform(driven);meta,data=_current_data(weight,driven)
    result=[]
    for channel in CHANNELS:
        current=finite(cmds.getAttr(driven+'.'+channel))
        row=copy.deepcopy(data['rows'].get(channel,dict(neutral=current,target_neutral=0. if not channel.startswith('scale') else 1.,
                           mirror_channel=channel,rule='keep_delta',input_rule='keep',enabled=not channel.startswith('scale'),curve=None)))
        row.update(channel=channel,value=current,status='Ready')
        try:
            _channel(driven,channel);curve=direct_curve(driven+'.'+channel)
            if curve:
                _check_curve(curve,weight,driven+'.'+channel)
                if row.get('curve')!=identity(curve):raise ValueError('Existing SDK is not owned by this binding')
                row['status']='SDK · {} keys'.format(cmds.keyframe(curve,query=True,keyframeCount=True))
        except (ValueError,RuntimeError) as exc:row['status']=str(exc)
        result.append(row)
    return {'meta':meta,'driver':weight,'driven':driven,'rows':result,'data':data}


def _rows(rows):
    result=[];seen=set()
    for original in rows:
        row=copy.deepcopy(original);channel=row['channel']
        if channel not in CHANNELS or channel in seen:raise ValueError('Duplicate or unsupported SDK channel.')
        seen.add(channel)
        if row['mirror_channel'] not in CHANNELS or channel[:-1]!=row['mirror_channel'][:-1]:raise ValueError('Map translation to translation, rotation to rotation, or scale to scale.')
        if row['rule'] not in RULES or row['input_rule'] not in INPUT_RULES:raise ValueError('Invalid mirror rule.')
        for key in ('neutral','target_neutral','value'):row[key]=finite(row[key])
        result.append(row)
    return result


def save_map(weight,driven,rows,mirror_weight=None,mirror_driven=None):
    weight=driver(weight);driven=transform(driven);rows=_rows(rows);meta,data=_current_data(weight,driven)
    if meta:editable(meta)
    data['mirror_driver']=plug_ref(driver(mirror_weight)) if mirror_weight else None
    data['mirror_driven']=identity(transform(mirror_driven)) if mirror_driven else None
    for row in rows:
        old=data['rows'].get(row['channel'],{});stored={k:row[k] for k in ('neutral','target_neutral','mirror_channel','rule','input_rule','enabled')}
        stored['curve']=old.get('curve');data['rows'][row['channel']]=stored
    with action('SavePoseSDKMap'):meta=_write(meta,data)
    return meta


def capture(weight,driven,rows,input_value=1.,tangent='linear'):
    weight=driver(weight);driven=transform(driven);all_rows=_rows(rows);rows=[r for r in all_rows if r['enabled']]
    if not rows:raise ValueError('Enable at least one channel.')
    x=finite(input_value)
    if not 0<=x<=1:raise ValueError('Driver key value must be from 0 to 1.')
    if tangent not in ('linear','auto','clamped','flat','step'):raise ValueError('Choose a supported SDK tangent.')
    meta,data=_current_data(weight,driven)
    if meta:editable(meta)
    _cycle_check(weight,driven)
    for row in rows:
        dst=_channel(driven,row['channel']);curve=direct_curve(dst)
        owned=data['rows'].get(row['channel'],{}).get('curve')
        if curve:
            if identity(curve)!=owned:raise ValueError('Existing SDK is not owned by this binding: '+dst)
            _check_curve(curve,weight,dst)
        elif owned:raise ValueError('Saved SDK was deleted/disconnected; remove that binding before rebuilding '+dst)
        if x==0 and abs(row['value']-row['neutral'])>1e-10:raise ValueError('At driver 0, key the neutral value or choose another driver key value.')
        row['_curve']=curve
    with action('CapturePoseSDK'):
        for row in rows:
            dst=driven+'.'+row['channel']
            values=[(x,row['value'])] if row['_curve'] else [(0.,row['neutral'])]+([] if x==0 else [(x,row['value'])])
            for key,value in values:
                count=cmds.setDrivenKeyframe(dst,currentDriver=weight,driverValue=key,value=value,
                           inTangentType=tangent,outTangentType=tangent,insertBlend=False,hierarchy='none',shape=False)
                if not count:raise RuntimeError('Maya did not set the SDK key: '+dst)
            curve=direct_curve(dst);_check_curve(curve,weight,dst)
            stored={k:row[k] for k in ('neutral','target_neutral','mirror_channel','rule','input_rule','enabled')}
            stored['curve']=identity(curve);data['rows'][row['channel']]=stored
        for row in all_rows:
            if row['enabled']:continue
            previous=data['rows'].get(row['channel'],{})
            stored={k:row[k] for k in ('neutral','target_neutral','mirror_channel','rule','input_rule','enabled')}
            stored['curve']=previous.get('curve');data['rows'][row['channel']]=stored
        meta=_write(meta,data)
    return {'meta':meta,'channels':len(rows),'driver_value':x}


def _mirror_plan(weight,driven,target_weight,target,rows,replace):
    weight=driver(weight);driven=transform(driven);target_weight=driver(target_weight);target=transform(target)
    if same(weight,target_weight) or identity(driven)==identity(target):raise ValueError('Mirror needs a different driver output and driven transform.')
    rows=[r for r in _rows(rows) if r['enabled'] and r['rule']!='skip']
    if not rows:raise ValueError('Enable at least one non-Skip mirror row.')
    if len({r['mirror_channel'] for r in rows})!=len(rows):raise ValueError('Two rows map to the same target channel.')
    _cycle_check(target_weight,target);meta,data=_current_data(target_weight,target)
    if meta:editable(meta)
    for row in rows:
        src=driven+'.'+row['channel'];dst=_channel(target,row['mirror_channel'])
        curve=direct_curve(src)
        if not curve:raise ValueError('Source has no direct SDK: '+src)
        _check_curve(curve,weight,src)
        if cmds.getAttr(src,type=True)!=cmds.getAttr(dst,type=True):raise ValueError('Source and mirror channel types differ.')
        keys=int(cmds.keyframe(curve,query=True,keyframeCount=True) or 0)
        if not keys:raise ValueError('Source SDK has no keys: '+src)
        old=direct_curve(dst);owned=data['rows'].get(row['mirror_channel'],{}).get('curve')
        if old:
            if not replace:raise ValueError('Target SDK already exists; enable Replace owned mirror SDKs: '+dst)
            if identity(old)!=owned:raise ValueError('Target curve is not owned by this binding: '+dst)
            _check_curve(old,target_weight,dst)
        elif owned:raise ValueError('Saved target SDK is missing/disconnected; remove that binding before rebuilding.')
        row.update(source_curve=curve,target_curve=old,destination=dst,key_count=keys)
    return target_weight,target,rows,meta,data


def preview_mirror(weight,driven,target_weight,target,rows,replace=False):
    _,_,planned,_,_=_mirror_plan(weight,driven,target_weight,target,rows,replace)
    return [{k:r[k] for k in ('channel','mirror_channel','rule','input_rule','neutral','target_neutral','key_count')} for r in planned]


def mirror(weight,driven,target_weight,target,rows,replace=False):
    all_rows=_rows(rows)
    target_weight,target,rows,meta,data=_mirror_plan(weight,driven,target_weight,target,all_rows,replace)
    source_meta,source_data=_current_data(weight,transform(driven))
    if source_meta:editable(source_meta)
    with action('MirrorPoseSDK'):
        for row in rows:
            source=row['source_curve'];keys=(0,row['key_count']-1)
            duplicate=cmds.duplicate(source,inputConnections=False,upstreamNodes=False,returnRootsOnly=True,name=':rtkPoseSDK_curve#')[0]
            if incoming(duplicate+'.input') or cmds.listConnections(duplicate+'.output',source=False,destination=True,plugs=True):
                raise RuntimeError('Duplicated curve unexpectedly retained connections.')
            if row['rule']!='keep_values':
                sign=-1. if row['rule']=='flip_delta' else 1.
                cmds.scaleKey(duplicate,animation='objects',index=keys,valueScale=sign,valuePivot=row['neutral'],autoSnap=False)
                cmds.keyframe(duplicate,animation='objects',edit=True,index=keys,relative=True,valueChange=row['target_neutral']-row['neutral'])
            if row['input_rule']=='reverse':
                pre,post=cmds.getAttr(source+'.preInfinity'),cmds.getAttr(source+'.postInfinity')
                cmds.scaleKey(duplicate,animation='objects',index=keys,floatScale=-1.,floatPivot=.5,autoSnap=False)
                cmds.setAttr(duplicate+'.preInfinity',post);cmds.setAttr(duplicate+'.postInfinity',pre)
            if row['target_curve']:cmds.delete(row['target_curve'])
            cmds.connectAttr(target_weight,duplicate+'.input');cmds.connectAttr(duplicate+'.output',row['destination'])
            channel=row['mirror_channel'];neutral=row['neutral'] if row['rule']=='keep_values' else row['target_neutral']
            data['rows'][channel]={'curve':identity(duplicate),'neutral':neutral,
                    'target_neutral':row['neutral'],'mirror_channel':row['channel'],'rule':row['rule'],'input_rule':row['input_rule'],'enabled':True}
        meta=_write(meta,data)
        source_data['mirror_driver']=plug_ref(target_weight);source_data['mirror_driven']=identity(target)
        for row in all_rows:
            previous=source_data['rows'].get(row['channel'],{})
            stored={k:row[k] for k in ('neutral','target_neutral','mirror_channel','rule','input_rule','enabled')}
            stored['curve']=previous.get('curve');source_data['rows'][row['channel']]=stored
        _write(source_meta,source_data)
    return {'meta':meta,'channels':len(rows)}


def remove(meta):
    meta,data=read(meta);editable(meta)
    found=cmds.ls(data['driven'],long=True) or []
    if len(found)>1:raise ValueError('The SDK driven object is ambiguous.')
    driven=found[0] if found else None;planned=[]
    for channel,row in data['rows'].items():
        if not row.get('curve'):continue
        found=cmds.ls(row['curve'],long=True) or []
        if not found:continue  # Deleted curves do not prevent metadata cleanup.
        if len(found)!=1:raise ValueError('An SDK curve is ambiguous.')
        curve=found[0];editable(curve)
        if cmds.nodeType(curve) not in CURVES:raise ValueError('The saved SDK curve type changed.')
        outs=cmds.listConnections(curve+'.output',source=False,destination=True,plugs=True) or []
        dst=driven+'.'+channel if driven else None
        if outs and (not dst or len(outs)!=1 or not same(outs[0],dst)):
            raise ValueError('SDK output is shared or connected to another object.')
        inputs=incoming(curve+'.input')
        if inputs:
            try:weight=plug_name(data['driver'])
            except ValueError:raise ValueError('SDK acquired an input after its original driver was removed.')
            if len(inputs)!=1 or not same(inputs[0],weight):raise ValueError('SDK input was changed to another driver.')
        if outs:
            _channel(driven,channel)
            if direct_curve(dst)!=curve:raise ValueError('SDK driven connection changed: '+dst)
            planned.append((curve,dst,finite(cmds.getAttr(dst))))
        else:planned.append((curve,None,None))
    with action('RemovePoseSDK'):
        for curve,dst,value in planned:
            cmds.delete(curve)
            if dst:cmds.setAttr(dst,value)
        cmds.delete(meta)
    return len(planned)
