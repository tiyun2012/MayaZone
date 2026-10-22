"""Layer-local influence protection and redistribution. No Maya or Qt imports."""
EPS=1e-12


def validate(layer):
    locks=layer.get('influence_locks',[])
    if not isinstance(locks,list) or any(not isinstance(j,str) or not j for j in locks) or len(set(locks))!=len(locks):
        raise ValueError('Layer influence locks must be unique joint identities.')
    if layer.get('redistribution','proportional') not in ('proportional','equal'):
        raise ValueError('Choose Proportional or Equal redistribution.')


def row(layer,key):return layer['samples'].get(key) or layer.get('generated',{}).get(key)


def amounts(sample,width):
    return [w*sample['coverage'] for w in sample['weights']] if sample else [0.]*width


def sample(values,fallback=None):
    total=sum(values)
    weights=[v/total for v in values] if total>EPS else (fallback['weights'][:] if fallback else [1.]+[0.]*(len(values)-1))
    return dict(weights=weights,coverage=max(0.,min(1.,total)))


def columns(state,layer):
    locked=set(layer.get('influence_locks',()))
    return {i for i,j in enumerate(state['influences']) if j in locked}


def distribute(values,budget,method='proportional'):
    total=sum(values.values())
    if total<=EPS or budget<=EPS:return {}
    if method=='equal':return {j:budget/len(values) for j in values}
    return {j:v*budget/total for j,v in values.items()}


def paint(before,column,value,locked,width,method):
    original=amounts(before,width)
    if column in locked:return before
    fixed=sum(original[j] for j in locked)
    value=min(value,max(0.,1.-fixed))
    others={j:q for j,q in enumerate(original) if j!=column and j not in locked and q>EPS}
    budget=min(sum(others.values()),max(0.,1.-fixed-value))
    result=[original[j] if j in locked else 0. for j in range(width)]
    result[column]=value
    for j,q in distribute(others,budget,method).items():result[j]=q
    return sample(result,before)


def project(before,candidate,locked,width,method='proportional'):
    """Keep locked contributions and cap the computed unlocked contribution."""
    original=amounts(before,width);values=amounts(candidate,width)
    budget=max(0.,1.-sum(original[j] for j in locked))
    free={j:q for j,q in enumerate(values) if j not in locked and q>EPS}
    if all(abs(values[j]-original[j])<=EPS for j in locked) and sum(free.values())<=budget+EPS:return candidate
    result=[original[j] if j in locked else 0. for j in range(width)]
    for j,q in distribute(free,min(budget,sum(free.values())),method).items():result[j]=q
    return sample(result,before or candidate)


def protect(state,result,layer_id,keys):
    before=next(layer for layer in state['layers'] if layer['id']==layer_id)
    locked=columns(state,before)
    if not locked:return result
    index=next(i for i,layer in enumerate(result['layers']) if layer['id']==layer_id)
    layer=result['layers'][index];width=len(state['influences']);samples=None
    for key in keys:
        old=row(before,key);candidate=row(layer,key)
        protected=project(old,candidate,locked,width)
        if protected is not candidate:
            if samples is None:samples=dict(layer['samples'])
            samples[key]=protected
    if samples is not None:
        result=dict(result,layers=list(result['layers']));result['layers'][index]=dict(layer,samples=samples)
    return result


def clamp_values(state,layer_id,joint,values):
    layer=next(layer for layer in state['layers'] if layer['id']==layer_id)
    if not layer.get('influence_locks'):return values
    width=len(state['influences']);locked=columns(state,layer)
    column=state['influences'].index(joint) if joint in state['influences'] else None
    result={}
    for key,value in values.items():
        q=amounts(row(layer,key),width)
        result[key]=q[column] if column in locked else min(value,max(0.,1.-sum(q[j] for j in locked)))
    return result
