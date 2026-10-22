"""Node-free, tool-independent Viewport 2.0 weight colors for component selection.

The native render pass owns transient geometry/color arrays and model-panel
attachments. Artist color sets, shaders, mesh history and display plugs are not
modified. Native Artisan remains responsible for active brush feedback.
"""
import math
import time

HEAT_STOPS=((0.,(.02,.05,.35)),(.25,(0.,.8,1.)),(.5,(.1,1.,.15)),(.75,(1.,.9,0.)),(1.,(1.,.05,0.)))


def color(value,display='heatmap'):
    value=max(0.,min(1.,float(value)))
    if display=='grayscale':return value,value,value,1.
    i=min(3,int(value*4));position,a=HEAT_STOPS[i];_,b=HEAT_STOPS[i+1]
    t=(value-position)*4
    return tuple(x+(y-x)*t for x,y in zip(a,b))+(1.,)


class Palette:
    """4097-entry lookup: <=1/8192 weight error; reuse tuples for large meshes."""
    def __init__(self):
        self.tables={name:tuple(color(i/4096.,name) for i in range(4097)) for name in ('heatmap','grayscale')}
    def map(self,values,display,table=None):
        if table is None:table=self.tables[display]
        return [table[int(max(0.,min(1.,value))*4096.+.5)] for value in values]


class WeightView:
    """Selection display with no mesh/color-set/history edits."""
    def __init__(self,api):
        self.api=api;self.palette=Palette();self.renderer=None;self.mesh=None;self.values=None
        self.display=None;self.token=None;self.updates=0;self.seconds=0.;self.closed=False;self.busy=False

    @property
    def visible(self):return self.renderer is not None and self.renderer.visible

    def _renderer(self):
        if self.renderer is None:
            factory=getattr(self.api,'make_weight_renderer',None)
            if factory:self.renderer=factory(self.palette)
            else:
                import importlib.util
                import os
                import sys
                name='_rtk_layer_skin_vp2_35'
                if name not in sys.modules:
                    spec=importlib.util.spec_from_file_location(name,os.path.join(os.path.dirname(__file__),'layer_skin_vp2.py'))
                    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.modules[name]=module
                self.renderer=sys.modules[name].WeightRenderer(self.api,self.palette)
        return self.renderer

    def show_versioned(self,mesh,values,display,token,force=False):
        return self.show(mesh,values,display,force=force,token=token)

    def reveal(self):
        if self.renderer is not None and not self.closed:self.renderer.reveal()

    def show(self,mesh,values,display='heatmap',force=False,token=None):
        if self.closed:raise RuntimeError('The weight display is closed.')
        if self.busy:return
        if not force and token is not None and self.visible and (mesh,display,token)==(self.mesh,self.display,self.token):
            self.reveal();return
        if display not in ('heatmap','grayscale'):raise ValueError('Unknown weight display.')
        if any(not math.isfinite(value) for value in values):raise ValueError('Non-finite viewport weight.')
        if not force and self.visible and (mesh,display)==(self.mesh,self.display) and values==self.values:
            self.reveal();return
        started=time.perf_counter();self.busy=True
        try:
            candidate=list(values);self._renderer().show(mesh,candidate,display)
            self.values=candidate;self.mesh=mesh;self.display=display;self.token=token;self.updates+=1
        except Exception:
            self.clear();raise
        finally:self.busy=False;self.seconds=time.perf_counter()-started

    def clear(self):
        if self.renderer is not None:self.renderer.clear()
        self.mesh=None;self.values=None;self.token=None

    def close(self):
        if self.renderer is not None:self.renderer.close()
        self.mesh=None;self.values=None;self.token=None;self.closed=True

    def abandon(self):
        if self.renderer is not None:self.renderer.abandon()
        self.mesh=None;self.values=None;self.token=None;self.closed=True

    def report(self):
        result=self.renderer.report() if self.renderer else dict(backend='VP2 viewport draw pass',visible=False,scene_nodes_created=0)
        return dict(result,vertices=len(self.values or ()),updates=self.updates,last_update_seconds=self.seconds)
