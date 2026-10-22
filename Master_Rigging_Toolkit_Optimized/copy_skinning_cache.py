"""Bounded, content-validated geometry caches. Contains no Maya objects or callbacks."""
import array
from collections import OrderedDict
import hashlib

VERSION='0.4.3'


def fingerprint(values,kind='d',check=None):
    def checked():
        for number,value in enumerate(values):
            if number%4096==0:check()
            yield value
    return hashlib.sha256(array.array(kind,checked() if check else values).tobytes()).hexdigest()


def geometry_token(identity,topology,positions,matrix,check=None):
    return (identity,topology,fingerprint((v for p in positions for v in p),check=check),fingerprint(matrix))


class CacheService:
    """LRU bounds use conservative payload estimates; oversize entries are not retained."""
    geometry_token=staticmethod(geometry_token)
    fingerprint=staticmethod(fingerprint)
    def __init__(self,max_bytes=128*1024*1024,max_items=12):
        self.max_bytes=max_bytes;self.max_items=max_items;self.entries=OrderedDict();self.bytes=0
        self.hits=0;self.misses=0;self.builds=0;self.queries=0;self.reused_queries=0
    def get(self,key):
        record=self.entries.pop(key,None)
        if record is None:self.misses+=1;return None
        self.entries[key]=record;self.hits+=1;return record[0]
    def put(self,key,value,cost):
        previous=self.entries.pop(key,None)
        if previous:self.bytes-=previous[1]
        if cost>self.max_bytes or self.max_items<=0:return False
        while self.entries and (len(self.entries)>=self.max_items or self.bytes+cost>self.max_bytes):
            _,(_,size)=self.entries.popitem(last=False);self.bytes-=size
        self.entries[key]=(value,cost);self.bytes+=cost;return True
    def clear(self):
        self.entries.clear();self.bytes=0
        self.hits=0;self.misses=0;self.builds=0;self.queries=0;self.reused_queries=0
    def stats(self):
        return dict(items=len(self.entries),estimated_bytes=self.bytes,hits=self.hits,misses=self.misses,
                    surface_builds=self.builds,nearest_queries=self.queries,reused_queries=self.reused_queries)
    def surface_key(self,points,triangles,mask,threshold,token=None,check=None):
        if token is None:token=fingerprint((v for p in points for v in p),check=check)
        return ('surface',token,fingerprint((v for face,ids in triangles for v in (face,)+tuple(ids)),'q',check),
             fingerprint(mask,check=check) if mask is not None else None,float(threshold))
    def surface(self,core,points,triangles,mask,threshold,token=None,check=None,key=None):
        key=key or self.surface_key(points,triangles,mask,threshold,token,check)
        cached=self.get(key)
        if cached is not None:return (*cached,key,True)
        records,skipped=core.prepare_triangles(points,triangles,mask,threshold,check=check)
        index=core.SurfaceIndex(records,check=check);result=(index,len(records),skipped)
        # Dicts, points, barycentrics and tree nodes are included in this estimate.
        self.put(key,result,len(records)*1800+len(index.nodes)*256);self.builds+=1
        return (*result,key,False)
    def correspondence(self,surface_key,target_token,vertices,max_distance,check=None):
        key=('hits',surface_key,target_token,fingerprint(vertices,'q',check),float(max_distance))
        cost=len(vertices)*640
        if cost>self.max_bytes:return key,None,False,cost
        hits=self.get(key)
        if hits is not None:return key,hits,True,cost
        # False = not sampled (e.g. black target mask); None = a confirmed miss.
        return key,[False]*len(vertices),False,cost


CACHE=CacheService()
