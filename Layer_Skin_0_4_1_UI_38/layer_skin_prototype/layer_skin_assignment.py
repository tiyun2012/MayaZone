"""Frozen-reference assignment. Pure Python, bounded caches, no Maya objects."""
import array
from collections import OrderedDict
import hashlib
import heapq
import itertools
import importlib.util
import os
import sys
import json
import math
import time


def digest(value):
    if isinstance(value, dict) and 'points' in value:
        try:
            header = {k: v for k, v in value.items() if k not in ('key', 'points')}
            h = hashlib.sha256(json.dumps(header, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
            pts = value['points']
            flat = array.array('d', itertools.chain.from_iterable(pts))
            if not math.isfinite(sum(flat) * 0.0):
                raise ValueError('Out of range float values are not JSON compliant')
            h.update(f':{len(pts)}:'.encode())
            h.update(flat.tobytes())
            return h.hexdigest()
        except TypeError:
            pass
    if isinstance(value, list) and value and type(value[0]) is int:
        try:
            return hashlib.sha256(array.array('q', value).tobytes()).hexdigest()
        except (TypeError, OverflowError):
            pass
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2]) if len(a) == 3 and len(b) == 3 else tuple(x - y for x, y in zip(a, b))


def dot(a, b):
    return (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) if len(a) == 3 and len(b) == 3 else sum(x * y for x, y in zip(a, b))


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2]) if len(a) == 3 and len(b) == 3 else tuple(x + y for x, y in zip(a, b))


def mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s) if len(a) == 3 else tuple(x * s for x in a)


def unit(vector):
    x, y, z = vector[0], vector[1], vector[2]
    size = math.sqrt(x * x + y * y + z * z)
    if not math.isfinite(size) or size < 1e-12:
        raise ValueError('Reference joint axis has zero length.')
    inv = 1.0 / size
    return (x * inv, y * inv, z * inv)


def local_axis_plane(record, axis):
    """World plane normal with the sign of a local inverse-matrix axis.

    A reciprocal basis handles shear and negative/nonuniform scale. A dot with
    the transformed X direction alone does not. Only a sign test is needed,
    so vertices do not need matrix objects or full matrix multiplication.
    """
    basis=[]
    for name in ('x','y','z'):
        vector=record[name];size=math.hypot(*vector)
        if not math.isfinite(size) or size==0.:
            raise ValueError('Joint reference frame has zero scale. Recapture reference with nonzero scale.')
        basis.append(tuple(value/size for value in vector))
    def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
    x,y,z=basis;det=dot(x,cross(y,z))
    if not math.isfinite(det) or abs(det)<1e-12:
        raise ValueError('Joint reference frame is singular. Recapture reference with nonzero scale.')
    normal={'X':lambda:cross(y,z),'Y':lambda:cross(z,x),'Z':lambda:cross(x,y)}[axis[-1]]()
    size=math.hypot(*normal)
    sign=(-1. if axis[0]=='-' else 1.)*(-1. if det<0. else 1.)
    return tuple(value*sign/size for value in normal)


def segment_distance(point, start, end):
    ux = end[0] - start[0]; uy = end[1] - start[1]; uz = end[2] - start[2]
    vx = point[0] - start[0]; vy = point[1] - start[1]; vz = point[2] - start[2]
    squared = ux * ux + uy * uy + uz * uz
    if squared > 1e-20:
        t = (vx * ux + vy * uy + vz * uz) / squared
        if t <= 0.0:
            return math.sqrt(vx * vx + vy * vy + vz * vz)
        if t >= 1.0:
            rx = vx - ux; ry = vy - uy; rz = vz - uz
            return math.sqrt(rx * rx + ry * ry + rz * rz)
        rx = vx - ux * t; ry = vy - uy * t; rz = vz - uz * t
        return math.sqrt(rx * rx + ry * ry + rz * rz)
    return math.sqrt(vx * vx + vy * vy + vz * vz)


def axis_hierarchy(joints,frames):
    """Selected topology and logical depth, independent of names/buffer counts."""
    if not all('parent' in frames[joint] for joint in joints):return sorted(joints),{},False
    depths={}
    for joint in joints:
        path=[];seen=set();cursor=joint
        while cursor is not None and cursor not in depths:
            if cursor in seen or cursor not in frames:raise ValueError('Assignment hierarchy is missing or cyclic. Recapture reference.')
            seen.add(cursor);path.append(cursor);cursor=frames[cursor].get('parent')
        depth=depths[cursor] if cursor is not None else -1
        for identity in reversed(path):depth+=1;depths[identity]=depth
    selected=set(joints);children={};roots=0
    for joint in joints:
        parent=frames[joint]['parent']
        while parent is not None and parent not in selected:parent=frames[parent].get('parent')
        if parent is None:roots+=1
        else:children[parent]=children.get(parent,0)+1
    order=sorted(joints,key=lambda identity:(-depths[identity],identity))
    return order,depths,roots>1 or any(count>1 for count in children.values())


def storage():
    name='_rtk_layer_skin_storage_20'
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,os.path.join(os.path.dirname(__file__),'layer_skin_storage.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.modules[name]=module
    return sys.modules[name]


class JointIndex:
    """Exact nearest pivots or finite bone segments in a balanced BVH.

    Distance always comes first. Axis mode prefers positive local coordinates
    only among equally near bones, then deeper joints and stable UUIDs. Every
    primitive remains eligible, including vertices behind all selected axes.
    """
    def __init__(self,joints,frames,columns,method,depths,axis='+X',check=None):
        self.records=[];self.nodes=[]
        def point(value):
            if len(value)!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in value):
                raise ValueError('Invalid frozen joint position. Recapture reference.')
            return tuple(value)
        for ordinal,joint in enumerate(joints):
            if check and ordinal & 255==0:check()
            frame=frames[joint];start=point(frame['position'])
            normal=local_axis_plane(frame,axis) if method=='axis' else None
            ends=[start] if method=='point' else frame.get('ends') or [frame.get('end',start)]
            tie=(-depths.get(joint,0),joint)
            for end in ends:
                end=point(end);delta=sub(end,start);squared=dot(delta,delta)
                segment=(*delta,1./squared if squared>1e-20 else 0.)
                low=tuple(min(start[a],end[a]) for a in range(3))
                high=tuple(max(start[a],end[a]) for a in range(3))
                self.records.append((columns[joint],start,normal,segment,low,high,tie))
        self._build(list(range(len(self.records))),check)

    def _build(self,indices,check):
        if check and len(self.nodes) & 127==0:check()
        low=tuple(min(self.records[i][4][a] for i in indices) for a in range(3))
        high=tuple(max(self.records[i][5][a] for i in indices) for a in range(3))
        index=len(self.nodes);self.nodes.append(None)
        if len(indices)<=6:self.nodes[index]=(low,high,(),indices)
        else:
            axis=max(range(3),key=lambda a:high[a]-low[a])
            indices.sort(key=lambda i:self.records[i][4][axis]+self.records[i][5][axis])
            middle=len(indices)//2
            children=(self._build(indices[:middle],check),self._build(indices[middle:],check))
            self.nodes[index]=(low,high,children,())
        return index

    @staticmethod
    def bound(point,low,high):
        x,y,z=point
        dx=low[0]-x if x<low[0] else x-high[0] if x>high[0] else 0.
        dy=low[1]-y if y<low[1] else y-high[1] if y>high[1] else 0.
        dz=low[2]-z if z<low[2] else z-high[2] if z>high[2] else 0.
        return dx*dx+dy*dy+dz*dz

    def closest(self,point,check=None):
        queue=[(self.bound(point,*self.nodes[0][:2]),0)];best=math.inf;priority=None;column=None;tests=0;visits=0
        while queue:
            bound,node=heapq.heappop(queue);visits+=1
            if check and visits & 1023==0:check()
            tolerance=1e-12*max(1.,best) if column is not None else 0.
            if column is not None and bound>best+tolerance:break
            low,high,children,indices=self.nodes[node]
            for child in children:
                lower=self.bound(point,*self.nodes[child][:2])
                if column is None or lower<=best+tolerance:heapq.heappush(queue,(lower,child))
            for index in indices:
                col,start,normal,segment,lo,hi,tie=self.records[index]
                if column is not None and self.bound(point,lo,hi)>best+tolerance:continue
                tests+=1;vx,vy,vz=sub(point,start);ux,uy,uz,inv=segment
                t=max(0.,min(1.,(vx*ux+vy*uy+vz*uz)*inv)) if inv else 0.
                rx=vx-ux*t;ry=vy-uy*t;rz=vz-uz*t
                distance=rx*rx+ry*ry+rz*rz
                rank=(0 if normal is None or vx*normal[0]+vy*normal[1]+vz*normal[2]>0. else 1,*tie)
                tolerance=1e-12*max(1.,distance,best if column is not None else 0.)
                if column is None or distance<best-tolerance or (abs(distance-best)<=tolerance and rank<priority):
                    best=distance;priority=rank;column=col
        return column,tests


class AssignmentCache:
    def __init__(self, max_bytes=64 * 1024 * 1024, max_items=8):
        self.max_bytes = max_bytes; self.max_items = max_items; self.entries = OrderedDict(); self.bytes = 0
        self.hits = 0; self.builds = 0; self.vertex_tests = 0

    def get(self, key):
        if key not in self.entries:
            return None
        value, cost = self.entries.pop(key); self.entries[key] = (value, cost); self.hits += 1; return value

    def put(self, key, value, cost):
        if key in self.entries:
            self.bytes -= self.entries.pop(key)[1]
        if cost > self.max_bytes:
            return
        while self.entries and (self.bytes + cost > self.max_bytes or len(self.entries) >= self.max_items):
            _, (_, old) = self.entries.popitem(last=False); self.bytes -= old
        self.entries[key] = (value, cost); self.bytes += cost

    def clear(self):
        self.entries.clear(); self.bytes = 0

    def stats(self):
        return dict(items=len(self.entries), estimated_bytes=self.bytes, hits=self.hits, builds=self.builds, vertex_tests=self.vertex_tests)

    def generate(self, reference, influences, joints, settings, scope=None, check=None):
        points = reference['points']; n_points = len(points); joints = list(dict.fromkeys(joints))
        if not joints:
            raise ValueError('Add joints to the layer before assigning.')
        influence_set = set(influences); ref_joints = reference['joints']
        if any(joint not in influence_set or joint not in ref_joints for joint in joints):
            raise ValueError('A layer joint has no frozen reference. Capture reference at the intended pose first.')
        method = settings.get('method', 'bone'); axis = settings.get('axis', '+X')
        limit = float(settings.get('max_seconds', 120))
        if method not in ('point', 'bone', 'axis') or axis not in ('+X', '-X', '+Y', '-Y', '+Z', '-Z'):
            raise ValueError('Unknown assignment method or axis.')
        if not math.isfinite(limit) or limit < 0:raise ValueError('Time limit must be nonnegative.')
        # Radius/length/falloff and legacy axis-overlap settings are obsolete.
        # Canonical topology/UUID order also makes distance ties independent of
        # the pick order. No positive-side filter can leave holes in the scope.
        joints,depths,_=axis_hierarchy(joints,ref_joints)
        params=dict(method=method,algorithm=2,rule={'point':'nearest_joint','bone':'nearest_bone','axis':'nearest_bone_axis_ties'}[method])
        if method=='axis':params['axis']=axis
        if scope is None:
            full_scope = True
            scope_key = f'all:{n_points}'
        else:
            scope = sorted(set(scope))
            if any(type(v) is not int or not 0 <= v < n_points for v in scope):
                raise ValueError('Invalid assignment vertices.')
            full_scope = len(scope) == n_points
            scope_key = f'all:{n_points}' if full_scope else digest(scope)
        # Validate content on an explicit assignment. Animation never calls this.
        # A stale/corrupted stored key cannot reuse another geometry's index.
        reference_key = digest(reference)
        key = ('result', reference_key, tuple(influences), tuple(joints), scope_key, digest(params))
        def info(samples,reused):
            return dict(key=digest(key),reference=reference_key,settings=params,reused=reused,
                        assigned_vertices=len(samples),scope_vertices=n_points if full_scope else len(scope))
        cached = self.get(key)
        if cached is not None:
            return cached, info(cached,True)
        started = time.monotonic()

        def checkpoint():
            if check:
                check()
            if limit and time.monotonic() - started > limit:
                raise RuntimeError('Assignment time limit reached before any weight writes.')

        checkpoint()
        columns={identity:i for i,identity in enumerate(influences)}
        index_key=('joint_index_v2',reference_key,tuple(influences),tuple(joints),method,axis if method=='axis' else None)
        index=self.get(index_key);built=index is None
        if built:index=JointIndex(joints,ref_joints,columns,method,depths,axis,checkpoint)
        width=len(influences);compact=n_points*width>storage().PACK_THRESHOLD
        generated={};rows={}
        for iteration,vertex in enumerate(range(n_points) if full_scope else scope):
            if iteration & 511==0:checkpoint()
            column,tests=index.closest(points[vertex],checkpoint);self.vertex_tests+=tests
            if column not in rows:
                if compact:rows[column]=storage().SparseWeights(width,[(column,1.)])
                else:
                    row=[0.]*width;row[column]=1.;rows[column]=row
            row=rows[column]
            generated[str(vertex)]=dict(weights=row if compact else row[:],coverage=1.)
        checkpoint();self.builds+=1
        # Only complete assignments publish new caches, including their index.
        if built:self.put(index_key,index,len(index.records)*600+len(index.nodes)*300)
        self.put(key,generated,len(generated)*(600 if compact else 600+40*width)+len(rows)*width*8)
        return generated,info(generated,False)


CACHE = AssignmentCache()
