"""Deterministic skin-weight editing math, independent of Maya/Qt."""
import math

VERSION='0.4.3'
EPS=1e-12


def row_values(row):
    values=[float(v) for v in row]
    if not values or any(not math.isfinite(v) or v<0 for v in values):
        raise ValueError('Skin weights must be finite and nonnegative.')
    if abs(sum(values)-1)>1e-5:
        raise ValueError('Normalize the selected vertex weights before editing (row sum must be 1).')
    return values


def indices(values,width):
    values=set(values)
    if any(type(i) is not int or not 0<=i<width for i in values):raise ValueError('Invalid influence index.')
    return values


def distribute(total,columns,basis,result):
    columns=sorted(columns)
    if not columns:
        if total>EPS:raise ValueError('No unlocked influence can receive the remaining weight.')
        return
    mass=sum(basis[i] for i in columns)
    for i in columns:result[i]=total*basis[i]/mass if mass>EPS else total/len(columns)


def fit_locked(original,desired,locked=()):
    """Keep held values exact; fit desired unlocked ratios into the free budget."""
    original=row_values(original);width=len(original);locked=indices(locked,width)
    desired=[float(v) for v in desired]
    if len(desired)!=width or any(not math.isfinite(v) or v<0 for v in desired):raise ValueError('Invalid requested weight row.')
    result=list(original);free=set(range(width))-locked;budget=1-sum(original[i] for i in locked)
    if budget < -EPS:raise ValueError('Held weights exceed a total of 1.')
    if not free:return result
    if sum(desired[i] for i in free)<=EPS:
        if budget<=EPS:
            for i in free:result[i]=0.
            return result
        raise ValueError('Requested row has no unlocked weight. Unhold an influence or choose another operation.')
    distribute(max(0.,budget),free,desired,result)
    return result


def set_total(original,selected,value,locked=(),relative=False):
    """Set/nudge the combined selected weight, keeping selected ratios when possible."""
    original=row_values(original);width=len(original)
    selected=indices(selected,width);locked=indices(locked,width)
    if not selected:raise ValueError('Select at least one influence in the list.')
    value=float(value)
    if not math.isfinite(value) or (not relative and not 0<=value<=1):raise ValueError('Set weight must be between 0 and 1; nudge must be finite.')
    active=selected-locked
    if not active:raise ValueError('All selected influences are held. Unhold explicitly before editing.')
    held_selected=sum(original[i] for i in selected&locked)
    budget=max(0.,1-sum(original[i] for i in locked))
    requested=sum(original[i] for i in selected)+value if relative else value
    amount=max(0.,min(budget,requested-held_selected))
    other=set(range(width))-selected-locked;remaining=budget-amount
    result=list(original)
    distribute(amount,active,original,result);distribute(remaining,other,original,result)
    return result


def average(rows,check=None):
    """Stream rows so a whole-mesh average does not duplicate the weight buffer."""
    total=None;count=0
    for row in rows:
        if check and count%128==0:check()
        row=row_values(row)
        if total is None:total=[0.]*len(row)
        if len(row)!=len(total):raise ValueError('Cannot average mismatched weight rows.')
        for i,value in enumerate(row):total[i]+=value
        count+=1
    if not count:raise ValueError('Cannot average empty weight rows.')
    return [value/count for value in total]


def prune(original,threshold,locked=()):
    original=row_values(original);locked=indices(locked,len(original));threshold=float(threshold)
    if not math.isfinite(threshold) or not 0<=threshold<=1:raise ValueError('Prune threshold must be between 0 and 1.')
    desired=[v if i in locked or v>=threshold else 0. for i,v in enumerate(original)]
    free=set(range(len(original)))-locked
    if free and not any(desired[i]>EPS for i in free):
        winner=max(sorted(free),key=lambda i:original[i]);desired[winner]=1.
    return fit_locked(original,desired,locked)


def mirror_mapping(records,left='_L',right='_R'):
    """Symmetric name mapping; untagged center influences retain their columns."""
    if not left or not right or left==right or left in right or right in left:
        raise ValueError('Mirror tokens must be distinct, nonempty and must not contain each other.')
    names=[r['path'].rsplit('|',1)[-1] for r in records];result=[];lookup={}
    for i,name in enumerate(names):lookup.setdefault(name,[]).append(i)
    for i,name in enumerate(names):
        if left in name and right in name:raise ValueError('Both mirror tokens occur in '+name)
        if left not in name and right not in name:result.append(i);continue
        counterpart=name.replace(left,right) if left in name else name.replace(right,left) if right in name else name
        hits=lookup.get(counterpart,[])
        if len(hits)!=1:raise ValueError('Missing or ambiguous mirror influence: '+counterpart)
        result.append(hits[0])
    if len(set(result))!=len(result) or any(result[result[i]]!=i for i in range(len(result))):raise ValueError('Mirror influence mapping must be reciprocal and one-to-one.')
    return result
