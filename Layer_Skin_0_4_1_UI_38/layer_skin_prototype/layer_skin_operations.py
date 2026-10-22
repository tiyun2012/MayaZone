"""Scalar layer operations shared by flood planning and native brush setup.

Artisan supplies final absolute values to the existing paint transaction. Never
apply Add or Scale a second time when committing its native doubleArray.
"""
import math


LIMITS={'replace':(0.,1.),'add':(-1.,1.),'scale':(0.,100.)}
NATIVE={'replace':'absolute','add':'additive','scale':'scale','relax':'absolute'}


def parameter(operation,value):
    if operation not in LIMITS:raise ValueError('Choose Replace, Add or Scale.')
    value=float(value);low,high=LIMITS[operation]
    if not math.isfinite(value) or not low<=value<=high:
        raise ValueError('{} value must be between {} and {}.'.format(operation.title(),low,high))
    return value


def brush_flags(operation,amount):
    if operation=='relax':amount=1.  # The viewport handler owns Relax gestures.
    else:amount=parameter(operation,amount)
    return dict(selectedattroper=NATIVE[operation],value=amount,
                minvalue=min(0.,amount),maxvalue=max(1.,amount),
                clamp='both',clamplower=0.,clampupper=1.,paintoperationtype='Paint')


def edit(state,data,core,vertices):
    """Calculate from this layer's contribution, independent of mask/alpha/Base."""
    operation=data.get('operation');amount=parameter(operation,data.get('amount'))
    mode=data.get('mode')
    if mode not in ('weights','mask'):raise ValueError('Choose Weights or Mask.')
    layer=next((row for row in state['layers'] if row['id']==data.get('layer')),None)
    if layer is None:raise ValueError('Select an editable layer.')
    joint=data.get('joint');column=None
    if mode=='weights':
        if joint not in state['influences']:raise ValueError('Choose a joint in the hierarchy.')
        column=state['influences'].index(joint)
    vertices=sorted(set(vertices))
    if not vertices or any(type(v) is not int or not 0<=v<state['vertex_count'] for v in vertices):
        raise ValueError('Select mesh vertices, or enable Whole mesh explicitly.')
    values={}
    for v in vertices:
        key=str(v)
        if mode=='mask':before=layer['mask'].get(key,1.)
        else:
            sample=layer['samples'].get(key) or layer.get('generated',{}).get(key)
            before=sample['weights'][column]*sample['coverage'] if sample else 0.
        value=amount if operation=='replace' else before+amount if operation=='add' else before*amount
        after=max(0.,min(1.,value))
        if abs(before-after)>1e-12:values[key]=after
    if not values:return state,[],False
    result=core.edit(state,'paint',dict(layer=layer['id'],mode=mode,joint=joint,values=values))
    dirty=[int(v) for v in values] if layer['enabled'] and layer['opacity'] else []
    return result,dirty,False


def prepare(ctx,state,data,core,scope):
    if type(data.get('whole',False)) is not bool:raise ValueError('Whole mesh must be true or false.')
    return edit(state,data,core,scope(ctx,data.get('whole',False)))


def install(owner):
    """Refresh only the planner; registered command objects retain native Undo."""
    previous=owner.get('prepare_edit')
    if not callable(previous):return False
    original=getattr(previous,'_layer_skin_operations_original',previous)
    def planner(ctx,meta,state,action,data):
        if action!='value_operation':return original(ctx,meta,state,action,data)
        validated,_,_=original(ctx,meta,state,'properties',dict(layer=data.get('layer'),expected=data.get('expected')))
        return prepare(ctx,validated,data,owner['core'],owner['selected_vertices'])
    planner._layer_skin_operations_original=original
    owner['prepare_edit']=planner
    return True
