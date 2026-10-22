"""Copy Skinning 0.4.3: world-space triangle BVH, clipping and weight interpolation."""
import heapq
import math
import re

VERSION='0.4.3'


def sub(a,b): return tuple(x-y for x,y in zip(a,b))
def dot(a,b): return sum(x*y for x,y in zip(a,b))
def blend(points,weights): return tuple(sum(p[i]*w for p,w in zip(points,weights)) for i in range(3))
def unit(v):
    v=float(v)
    if not math.isfinite(v) or not 0<=v<=1: raise ValueError('Expected a finite value in [0, 1].')
    return v


def normalize(row):
    if not row or any(not math.isfinite(x) or x<0 for x in row): raise ValueError('Invalid skin weights.')
    total=sum(row)
    if total<=1e-14: raise ValueError('Zero-sum skin weights cannot be transferred.')
    return [x/total for x in row]


def closest_triangle(p,a,b,c):
    """Ericson region tests; return nearest point and barycentrics in A/B/C order."""
    ab,ac,ap=sub(b,a),sub(c,a),sub(p,a)
    d1,d2=dot(ab,ap),dot(ac,ap)
    if d1<=0 and d2<=0:return a,(1.,0.,0.)
    bp=sub(p,b);d3,d4=dot(ab,bp),dot(ac,bp)
    if d3>=0 and d4<=d3:return b,(0.,1.,0.)
    vc=d1*d4-d3*d2
    if vc<=0 and d1>=0 and d3<=0:
        v=d1/(d1-d3);w=(1-v,v,0.);return blend((a,b,c),w),w
    cp=sub(p,c);d5,d6=dot(ab,cp),dot(ac,cp)
    if d6>=0 and d5<=d6:return c,(0.,0.,1.)
    vb=d5*d2-d1*d6
    if vb<=0 and d2>=0 and d6<=0:
        w=d2/(d2-d6);weights=(1-w,0.,w);return blend((a,b,c),weights),weights
    va=d3*d6-d5*d4
    if va<=0 and d4-d3>=0 and d5-d6>=0:
        w=(d4-d3)/((d4-d3)+(d5-d6));weights=(0.,1-w,w);return blend((a,b,c),weights),weights
    denominator=va+vb+vc
    if abs(denominator)<=1e-30:raise ValueError('Degenerate triangle.')
    v,w=vb/denominator,vc/denominator;weights=(1-v-w,v,w)
    return blend((a,b,c),weights),weights


def triangle_valid(points):
    ab,ac=sub(points[1],points[0]),sub(points[2],points[0])
    cross=(ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0])
    longest=max(dot(ab,ab),dot(ac,ac),dot(sub(points[2],points[1]),sub(points[2],points[1])))
    return longest>0 and dot(cross,cross)>longest*longest*1e-24


def clip_mask(points,values,threshold):
    """Clip linear mask support; retain original-triangle barycentrics at every corner."""
    polygon=[(tuple(p),tuple(float(i==j) for j in range(3)),unit(m)) for i,(p,m) in enumerate(zip(points,values))]
    result=[]
    for current,following in zip(polygon,polygon[1:]+polygon[:1]):
        inside=current[2]>=threshold;next_inside=following[2]>=threshold
        if inside:result.append(current)
        if inside!=next_inside:
            t=(threshold-current[2])/(following[2]-current[2])
            p=tuple(a+(b-a)*t for a,b in zip(current[0],following[0]))
            bary=tuple(a+(b-a)*t for a,b in zip(current[1],following[1]))
            result.append((p,bary,threshold))
    return [(result[0],result[i],result[i+1]) for i in range(1,len(result)-1)]


def prepare_triangles(points,triangles,source_mask=None,threshold=.001,check=None):
    if not 0<threshold<=1:raise ValueError('Source mask threshold must be in (0, 1].')
    if source_mask is not None and len(source_mask)!=len(points):raise ValueError('Source mask size mismatch.')
    result=[];skipped=0
    for number,(face,ids) in enumerate(triangles):
        if check and number%128==0:check()
        positions=[points[i] for i in ids]
        if not triangle_valid(positions):skipped+=1;continue
        values=[source_mask[i] for i in ids] if source_mask is not None else [1.,1.,1.]
        for clipped in clip_mask(positions,values,threshold):
            corners=tuple(v[0] for v in clipped)
            if triangle_valid(corners):result.append({'points':corners,'bary':tuple(v[1] for v in clipped),'ids':tuple(ids),'face':face,'mask':values})
    if not result:raise ValueError('Source region has no usable triangles. Check source faces and painted mask.')
    return result,skipped


def bounds(records):
    return tuple(min(p[i] for record in records for p in record['points']) for i in range(3)),tuple(max(p[i] for record in records for p in record['points']) for i in range(3))


def box_distance(p,box):
    lo,hi=box
    return sum((lo[i]-p[i])**2 if p[i]<lo[i] else (p[i]-hi[i])**2 if p[i]>hi[i] else 0 for i in range(3))


class SurfaceIndex:
    """Median-split AABB tree built once per preview/copy, independent of Maya."""
    def __init__(self,records,check=None):
        if not records:raise ValueError('Empty source surface.')
        self.check=check;self.nodes=[]
        try:self.root=self.build(records)
        finally:self.check=None

    def build(self,records):
        if self.check:self.check()
        box=bounds(records);index=len(self.nodes);self.nodes.append(None)
        if len(records)<=8:self.nodes[index]=(box,records,None)
        else:
            axis=max(range(3),key=lambda i:box[1][i]-box[0][i]);ordered=sorted(records,key=lambda r:sum(p[axis] for p in r['points']))
            middle=len(ordered)//2;children=(self.build(ordered[:middle]),self.build(ordered[middle:]))
            self.nodes[index]=(box,None,children)
        return index

    def nearest(self,p,max_distance=0,check=None):
        check=check or self.check
        best=max_distance*max_distance if max_distance>0 else float('inf');hit=None
        queue=[(box_distance(p,self.nodes[self.root][0]),self.root)]
        visits=0
        while queue:
            if check and visits%128==0:check()
            visits+=1
            distance,index=heapq.heappop(queue)
            if distance>best:break
            box,records,children=self.nodes[index]
            if records is not None:
                for record in records:
                    point,weights=closest_triangle(p,*record['points']);delta=sub(p,point);distance=dot(delta,delta)
                    if distance<=best:
                        best=distance;bary=blend(record['bary'],weights)
                        hit={'ids':record['ids'],'bary':bary,'point':point,'distance':math.sqrt(distance),
                             'face':record['face'],'source_alpha':sum(a*b for a,b in zip(record['mask'],bary))}
            else:
                for child in children:
                    distance=box_distance(p,self.nodes[child][0])
                    if distance<=best:heapq.heappush(queue,(distance,child))
        return hit


def influence_mapping(source,target,search='',replace='',ignore_namespace=False):
    """Records contain uuid and path; reject missing or ambiguous names."""
    def name(path):
        leaf=path.rsplit('|',1)[-1]
        return leaf.rsplit(':',1)[-1] if ignore_namespace else leaf
    result=[];used=set()
    for source_joint in source:
        candidates=[i for i,j in enumerate(target) if j['uuid']==source_joint['uuid']]
        if not candidates:
            key=name(source_joint['path']);key=key.replace(search,replace) if search else key
            candidates=[i for i,j in enumerate(target) if name(j['path'])==key]
        if len(candidates)!=1:raise ValueError('Missing or ambiguous target influence: '+source_joint['path'])
        index=candidates[0]
        if index in used:raise ValueError('Two source influences map to the same target influence.')
        used.add(index);result.append(index)
    return result


def edit_distance(a,b,limit=None):
    """Levenshtein distance: insertion, deletion or replacement costs one."""
    if limit is not None and abs(len(a)-len(b))>limit:return limit+1
    previous=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        if limit is None:
            current=[i]
            for j,y in enumerate(b,1):current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(x!=y)))
        else:
            current=[limit+1]*(len(b)+1);current[0]=i
            for j in range(max(1,i-limit),min(len(b),i+limit)+1):current[j]=min(current[j-1]+1,previous[j]+1,previous[j-1]+(x!=b[j-1]))
            if min(current)>limit:return limit+1
        previous=current
    return previous[-1]


def resolve_influences(source,target,use_name=True,use_distance=True,tolerance=.01,
                       max_edits=3,search='',replace='',ignore_namespace=True,manual=None,check=None):
    """Deterministic, one-to-one mapping. Positions and tolerance use the same units.

    Manual UUID pairs, identity, unique exact names, then mutual unique best
    proximity/name candidates. Equal scores remain unresolved instead of using
    source list order as a tie-breaker. No changes are made to either rig.
    """
    tolerance=float(tolerance)
    if not math.isfinite(tolerance) or tolerance<0:raise ValueError('Joint distance tolerance must be finite and nonnegative.')
    if type(max_edits) is not int or not 0<=max_edits<=10:raise ValueError('Name edit limit must be an integer from 0 to 10.')
    source_ids=[r['uuid'] for r in source];target_ids=[r['uuid'] for r in target]
    if len(set(source_ids))!=len(source_ids) or len(set(target_ids))!=len(target_ids):raise ValueError('Duplicate influence identities.')
    manual=manual or {}
    if not isinstance(manual,dict):raise ValueError('Manual mapping must contain source and target UUID pairs.')
    if set(manual)-set(source_ids) or any(value is not None and value not in target_ids for value in manual.values()):
        raise ValueError('Manual mapping is stale. Refresh influences and assign the removed joint again.')
    def name(path):
        value=path.rsplit('|',1)[-1]
        return value.rsplit(':',1)[-1] if ignore_namespace else value
    names=[name(r['path']).replace(search,replace) if search else name(r['path']) for r in source]
    target_names=[name(r['path']) for r in target]
    positions_left=[r.get('position') for r in source];positions_right=[r.get('position') for r in target]
    for position in positions_left+positions_right:
        if position is not None and (len(position)!=3 or any(not math.isfinite(v) for v in position)):raise ValueError('Invalid influence position.')
    def side(value):
        value=value.rsplit(':',1)[-1]
        tokens=re.split(r'[^a-z0-9]+',re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',value).lower())
        values={('L' if t in ('l','left') else 'R') for t in tokens if t in ('l','left','r','right')}
        return next(iter(values)) if len(values)==1 else None
    def distance(i,j):
        a,b=positions_left[i],positions_right[j]
        if a is None or b is None:return None
        return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))
    mapping=[None]*len(source);methods=['Unmatched']*len(source);blocked=set();used=set();errors=[]
    for i,identity in enumerate(source_ids):
        if check and i%32==0:check()
        if identity not in manual:continue
        value=manual[identity]
        if value is None:blocked.add(i);methods[i]='Manually unmapped';continue
        j=target_ids.index(value);mapping[i]=j;methods[i]='Manual';used.add(j)
    for j in used:
        owners=[i for i,v in enumerate(mapping) if v==j]
        if len(owners)>1:
            errors.append('Multiple manual rows use '+target[j]['path'])
            for i in owners:methods[i]='Manual conflict'
    for i,identity in enumerate(source_ids):
        if check and i%32==0:check()
        if mapping[i] is not None or i in blocked:continue
        if identity in target_ids:
            j=target_ids.index(identity)
            if j in used:blocked.add(i);methods[i]='Identity reserved by manual mapping'
            else:mapping[i]=j;used.add(j);methods[i]='Same joint UUID'

    def assign(edges):
        # Resolve only mutual unique minima; ties cannot depend on list order.
        while True:
            if check:check()
            available={i:[e for e in candidates if e[1] not in used] for i,candidates in edges.items() if mapping[i] is None and i not in blocked}
            source_best={};target_best={}
            for i,candidates in available.items():
                if not candidates:continue
                best=min(e[0] for e in candidates);winners=[e for e in candidates if e[0]==best]
                if len(winners)==1:source_best[i]=winners[0]
                for score,j,method in candidates:target_best.setdefault(j,[]).append((score,i))
            targets={}
            for j,candidates in target_best.items():
                best=min(score for score,_ in candidates);winners=[i for score,i in candidates if score==best]
                if len(winners)==1:targets[j]=winners[0]
            pairs=[(i,e) for i,e in source_best.items() if targets.get(e[1])==i]
            if not pairs:break
            for i,(_score,j,method) in pairs:mapping[i]=j;used.add(j);methods[i]=method
    exact={}
    if use_name:
        for i,key in enumerate(names):
            if check:check()
            if mapping[i] is None and i not in blocked:
                exact[i]=[((0,),j,'Exact name') for j,value in enumerate(target_names) if key==value and j not in used]
        assign(exact)
    edges={}
    for i,key in enumerate(names):
        if check:check()
        if mapping[i] is not None or i in blocked:continue
        candidates=[];near=[];source_side=side(key);pool=[]
        for j,value in enumerate(target_names):
            if check and j%128==0:check()
            if j in used:continue
            target_side=side(value)
            if source_side and target_side and source_side!=target_side:continue
            d=distance(i,j) if use_distance else None
            pool.append((j,value,d))
        nearby=[item for item in pool if use_distance and item[2] is not None and item[2]<=tolerance]
        # Most duplicate rigs have one nearby joint: do not compare its name
        # against every distant influence when those candidates cannot win.
        for j,value,d in (nearby or pool):
            if check:check()
            edits=edit_distance(key.lower(),value.lower(),max_edits) if use_name else None
            similar=use_name and edits<=max_edits and (1-edits/max(1,len(key),len(value)))>=.6
            if use_distance and d is not None and d<=tolerance:
                score=(0 if similar else 1,edits if similar else 0,round(d,12))
                near.append((score,j,'Name + distance ({} edits)'.format(edits) if similar else 'Distance'))
            if similar:candidates.append(((2,edits,0),j,'Similar name ({} edits)'.format(edits)))
        edges[i]=near if near else candidates
    assign(edges)
    rows=[]
    for i,j in enumerate(mapping):
        candidates=edges.get(i,exact.get(i,[]))
        status=methods[i]
        if j is None and status=='Unmatched':status='Ambiguous / conflicting candidates' if candidates else 'No match within enabled rules'
        rows.append({'source_uuid':source_ids[i],'source':source[i]['path'],'target_uuid':target_ids[j] if j is not None else None,
                     'target':target[j]['path'] if j is not None else None,'method':status,
                     'distance':distance(i,j) if j is not None else None,
                     'edits':edit_distance(names[i].lower(),target_names[j].lower()) if j is not None and use_name else None})
    unresolved=[r['source'] for r in rows if r['target_uuid'] is None]
    if unresolved:errors.append('{} unresolved influences. Adjust the mapping table: {}'.format(len(unresolved),', '.join(unresolved[:8])))
    return {'mapping':mapping,'rows':rows,'complete':not errors,'errors':errors,'source_ids':source_ids,'target_ids':target_ids,
            'target_influences':[{'uuid':r['uuid'],'path':r['path']} for r in target]}


def interpolate(weights,width,ids,bary,mapping,target_width):
    if width<=0 or len(weights)%width or len(mapping)!=width or len(ids)!=3 or len(bary)!=3:raise ValueError('Invalid interpolation dimensions.')
    if any(type(i) is not int or not 0<=i<target_width for i in mapping):raise ValueError('Invalid influence mapping.')
    if any(type(i) is not int or not 0<=i<len(weights)//width for i in ids):raise ValueError('Invalid triangle vertex ID.')
    if any(not math.isfinite(v) or v < -1e-10 for v in bary):raise ValueError('Invalid barycentric coordinates.')
    bary=normalize([max(0.,v) for v in bary])
    result=[0.]*target_width
    for vertex,factor in zip(ids,bary):
        if factor==0:continue
        row=normalize(weights[vertex*width:(vertex+1)*width])
        for j,destination in enumerate(mapping):result[destination]+=factor*row[j]
    return normalize(result)


def transfer_row(original,sampled,alpha):
    if len(original)!=len(sampled):raise ValueError('Weight row size mismatch.')
    alpha=unit(alpha)
    if alpha==0:return list(original)
    return normalize([(1-alpha)*a+alpha*b for a,b in zip(normalize(original),normalize(sampled))])
