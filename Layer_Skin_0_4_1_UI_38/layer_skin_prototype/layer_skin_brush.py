"""Brush-local relaxation math and staging; no Maya or Qt imports.

The brush edits an owned working copy, previews values, and sends only final
changed rows to one guarded native authoring command on mouse release.
"""
import math


def falloff(ratio):
    return (1.-ratio*ratio)**2 if 0.<=ratio<1. else 0.


class PointSampler:
    """Deterministic spacing along the input polyline, independent of event count."""
    def __init__(self,spacing,max_samples=64):
        self.spacing=max(.5,float(spacing));self.max_samples=max_samples;self.previous=None;self.carry=0.
    def feed(self,point):
        point=tuple(point)
        if self.previous is None:self.previous=point;return [point]
        start=self.previous;self.previous=point
        dx=point[0]-start[0];dy=point[1]-start[1];length=math.hypot(dx,dy)
        if length<1e-10:return []
        first=self.spacing-self.carry;positions=[];distance=first
        while distance<=length+1e-9 and len(positions)<self.max_samples:
            t=distance/length;positions.append((start[0]+dx*t,start[1]+dy*t));distance+=self.spacing
        if len(positions)==self.max_samples and distance<=length:self.carry=0.
        else:self.carry=(self.carry+length)%self.spacing
        return positions


class SurfaceGrid:
    """One position hash per gesture; connected candidates avoid nearby islands."""
    def __init__(self,points,radius):
        self.radius=float(radius)
        if not math.isfinite(self.radius) or self.radius<=0:raise ValueError('Brush radius must be positive.')
        self.points=points;self.cells={}
        for i,point in enumerate(points):self.cells.setdefault(self.key(point),[]).append(i)
    def key(self,point):return tuple(math.floor(value/self.radius) for value in point)
    def footprint(self,center,seeds,neighbors,max_vertices=50000,*,radius=None,clip=None):
        """Clip candidates before connectivity; outside rows are never solver scope.

        The hash cell size stays fixed for the gesture. A screen-space native
        brush may report a different world radius as the cursor changes depth;
        query it without rebuilding the full position hash on every mouse move.
        ``clip(vertex)`` supplies an optional additional [0, 1] falloff.
        """
        radius=self.radius if radius is None else float(radius)
        if not math.isfinite(radius) or radius<=0:raise ValueError('Brush radius must be positive.')
        low=self.key(tuple(value-radius for value in center));high=self.key(tuple(value+radius for value in center))
        count=math.prod(b-a+1 for a,b in zip(low,high))
        # Avoid walking a huge mostly-empty cube after a large depth change.
        if count>max(27,len(self.cells)*2):
            cells=(rows for cell,rows in self.cells.items() if all(a<=v<=b for a,v,b in zip(low,cell,high)))
        else:
            cells=(self.cells.get((x,y,z),()) for x in range(low[0],high[0]+1)
                for y in range(low[1],high[1]+1) for z in range(low[2],high[2]+1))
        candidates={};r2=radius*radius;visited=0
        for rows in cells:
            for v in rows:
                point=self.points[v];d2=sum((a-b)**2 for a,b in zip(center,point))
                if d2<r2:
                    visited+=1
                    if visited>max_vertices:raise ValueError('Brush area exceeds 50,000 candidate vertices. Reduce the radius or use Flood relax.')
                    factor=falloff(math.sqrt(d2/r2))
                    if clip is not None:factor=min(factor,clip(v))
                    if factor>0:candidates[v]=factor
        pending=[v for v in seeds if v in candidates];seen=set(pending);result={}
        while pending:
            v=pending.pop();result[v]=candidates[v]
            for u in neighbors(v):
                if u in candidates and u not in seen:seen.add(u);pending.append(u)
        return result


class ConnectedSurface:
    """Query only the connected footprint and its boundary, with lazy points.

    The previous global hash ultimately returned the same graph traversal:
    only vertices inside BOTH the world sphere and screen clip can connect a
    hit-face seed to another vertex. No positions survive a native gesture.
    """
    def __init__(self,point):self.point=point
    def footprint(self,center,seeds,neighbors,max_vertices=50000,*,radius,clip=None):
        radius=float(radius)
        if not math.isfinite(radius) or radius<=0:raise ValueError('Brush radius must be positive.')
        pending=list(seeds);seen=set();result={};inside=0;r2=radius*radius
        while pending:
            v=pending.pop()
            if v in seen:continue
            seen.add(v)
            point=self.point(v);d2=sum((a-b)**2 for a,b in zip(center,point))
            if d2>=r2:continue
            inside+=1
            if inside>max_vertices:raise ValueError('Brush area exceeds 50,000 candidate vertices. Reduce the radius or use Flood relax.')
            factor=falloff(math.sqrt(d2/r2))
            if clip is not None:factor=min(factor,clip(v))
            if factor<=0:continue
            result[v]=factor
            pending.extend(u for u in neighbors(v) if u not in seen)
        return result


class RelaxStroke:
    def __init__(self,state,layer_id,mode,settings,relax):
        if mode not in ('weights','mask'):raise ValueError('Choose Weights or Mask to relax.')
        self.relax=relax;self.original=state;self.layer_id=layer_id;self.mode=mode
        self.settings=dict(settings);self.touched=set();self.supports={};self.stamps=0
        self.strength=float(settings.get('strength',.5));self.opacity=float(settings.get('opacity',1.))
        self.iterations=settings.get('iterations',1);self.max_new=settings.get('max_new',0)
        self.preserve=settings.get('preserve_coverage',False);self.joints=list(dict.fromkeys(settings.get('joints',())))
        if type(self.iterations) is not int or not 1<=self.iterations<=100:raise ValueError('Brush passes must be between 1 and 100.')
        if type(self.max_new) is not int or self.max_new<0:raise ValueError('Invalid new influence limit.')
        if type(self.preserve) is not bool:raise ValueError('Preserve coverage must be true or false.')
        if any(not math.isfinite(v) or not 0<=v<=1 for v in (self.strength,self.opacity)):raise ValueError('Brush strength and opacity must be between 0 and 1.')
        if mode=='weights' and len(self.joints)>1 and any(j not in state['influences'] for j in self.joints):
            raise ValueError('Choose bound skin influences for a joint-group Relax brush.')
        index=next((i for i,row in enumerate(state['layers']) if row['id']==layer_id),None)
        if index is None:raise ValueError('Select an editable layer to relax.')
        self.source=state['layers'][index]
        self.working=dict(state,layers=list(state['layers']))
        self.layer=dict(self.source,samples=dict(self.source['samples']),mask=dict(self.source['mask']))
        self.working['layers'][index]=self.layer

    def stamp(self,factors,neighbors):
        n=self.original['vertex_count']
        if any(type(v) is not int or not 0<=v<n for v in factors):raise ValueError('Brush vertex is outside the loaded mesh.')
        if any(not math.isfinite(f) or not 0<=f<=1 for f in factors.values()):raise ValueError('Invalid brush falloff.')
        vertices=sorted(v for v,factor in factors.items() if factor>0)
        if not vertices or not self.strength or not self.opacity:return []
        graph={v:tuple(neighbors(v)) for v in vertices}
        scaled={v:factors[v]*self.opacity for v in vertices}
        self.stamps+=1
        if self.mode=='mask':
            values=self.relax.relax_mask_rows(self.layer['mask'],graph,vertices,self.iterations,self.strength,scaled)
            for key,value in values.items():
                if value>=1.-1e-12:self.layer['mask'].pop(key,None)
                else:self.layer['mask'][key]=value
            changed=[int(key) for key in values]
        else:
            if self.max_new:
                for v in vertices:
                    if v not in self.supports:self.supports[v]=set(self.relax.contribution(self.relax.sample_at(self.source,v)))
            samples,changed,used=self.relax.relax_rows(self.working,self.layer_id,graph,vertices,
                self.iterations,self.strength,self.max_new,self.joints,factors=scaled,
                preserve_coverage=self.preserve,initial_supports=self.supports if self.max_new else None)
            self.layer['samples'].update(samples)
            self.layer['joints']=list(dict.fromkeys(self.layer.get('joints',[])+[j for j in self.original['influences'] if j in used]))
        self.touched.update(changed)
        return changed

    def preview(self,vertices,joint):
        if self.mode=='mask':return {v:self.layer['mask'].get(str(v),1.) for v in vertices}
        column=self.original['influences'].index(joint) if joint in self.original['influences'] else None
        values={}
        for v in vertices:
            sample=self.relax.sample_at(self.layer,v)
            values[v]=sample['weights'][column]*sample['coverage'] if sample and column is not None else 0.
        return values

    def payload(self):
        data=dict(layer=self.layer_id,mode=self.mode)
        if self.mode=='mask':
            data['values']={str(v):self.layer['mask'].get(str(v),1.) for v in sorted(self.touched)
                if abs(self.layer['mask'].get(str(v),1.)-self.source['mask'].get(str(v),1.))>1e-10}
        else:
            data['samples']={}
            for v in sorted(self.touched):
                a=self.relax.contribution(self.relax.sample_at(self.source,v))
                b=self.relax.contribution(self.relax.sample_at(self.layer,v))
                if any(abs(a.get(j,0.)-b.get(j,0.))>1e-10 for j in a.keys()|b.keys()):
                    data['samples'][str(v)]=self.relax.sample_at(self.layer,v)
        return data
