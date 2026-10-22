"""Paint/callback lifecycle and influence-add orchestration, with explicit API fakes."""
import copy
import hashlib
import json
import sys
import types
import unittest
from unittest import mock
import layer_skin_core as core
import layer_skin_session as session_module


class FakeBrowser:
    def __init__(self):
        self.paths=[];self.roots=[];self.closed=False;self.weighted=set();self.members=set();self.known={}
    def joints(self):return list(self.paths)
    def scope(self,root):self.roots.append(root)
    def close(self):self.closed=True
    def select_joint(self,path):self.paths=[path]
    def set_layer_status(self,weighted,members,paths):
        self.weighted=set(weighted);self.members=set(members);self.known=dict(paths)


class FakePaintBuffer:
    def __init__(self):self.values=[];self.owner=None
    def attribute(self):return 'paintBuffer.values'
    def write(self,values):self.values=list(values)
    def read(self):return self.values[:]
    def geometry_sources(self):return ['meshShape.outMesh']


class FakeWeightView:
    """Recording display adapter; VP2 API calls have separate recording tests."""
    def __init__(self):self.visible=False;self.updates=0;self.values=[];self.closed=False
    def show(self,mesh,values,display,force=False):
        self.visible=True;self.mesh=mesh;self.values=list(values);self.display=display;self.updates+=1
    def clear(self):self.visible=False
    def close(self):self.clear();self.closed=True
    def abandon(self):self.visible=False;self.closed=True
    def report(self):return dict(visible=self.visible,updates=self.updates)


class FakeAPI:
    """Plain scene snapshots and command invocation, not dependency-graph emulation."""
    def __init__(self):
        self.core=core;self.VERSION='0.4.1';self.WINDOW='LayerSkinQtTest';self.paint_context=session_module.CONTEXT
        self.paint_buffer=FakePaintBuffer();self.make_paint_buffer=lambda mesh:self.paint_buffer
        self.weight_view=FakeWeightView();self.make_weight_view=lambda:self.weight_view
        self.make_brush_controller=lambda session:None
        self.ids=['a','b'];self.weights=[1.,0.]*3;self.state=core.create(self.weights,3,self.ids,'topology')
        self.state=core.edit(self.state,'add',{'name':'Arm'});self.layer=self.state['layers'][0]['id']
        self.state=core.edit(self.state,'membership',dict(layer=self.layer,joints=['a','b']))
        self.attached=True;self.calls=[];self.warnings=[];self.undo_stack=[];self.redo_stack=[]
        self.selected=['mesh'];self.tool='selectSuperContext';self.context_exists=False;self.events=[];self.fail=False
        self.selection_types={};self.hilited=[]
        self.callbacks={};self.serial=0;self.browsers=[];self.context_settings={};self.object_mode=True
        self.mel=types.SimpleNamespace(eval=self.mel_eval)
        self.plugin_details=lambda:dict(name='layer_skin_test.py',path='/test/layer_skin_test.py',version=self.VERSION)
        def add(kind,callback):
            self.serial+=1;self.callbacks[self.serial]=(kind,callback);return self.serial
        self.om=types.SimpleNamespace(MEventMessage=types.SimpleNamespace(addEventCallback=add),
            MSceneMessage=types.SimpleNamespace(kBeforeNew='BeforeNew',kBeforeOpen='BeforeOpen',kMayaExiting='MayaExiting',addCallback=add),
            MMessage=types.SimpleNamespace(removeCallback=lambda identity:self.callbacks.pop(identity)),
            MFnDependencyNode=lambda node:types.SimpleNamespace(isLocked=False,uuid=lambda:types.SimpleNamespace(asString=lambda:str(node).split('|')[-1])))
        self.cmds=types.SimpleNamespace(rtkLayerSkin=self.command,warning=self.warnings.append,ls=self.ls,nodeType=self.node_type,
            listRelatives=self.relatives,artUserPaintCtx=self.paint_ctx,currentCtx=lambda:self.tool,setToolTo=self.set_tool,
            select=self.select,selectMode=self.select_mode,selectType=self.select_type,hilite=self.hilite,deleteUI=lambda *a,**kw:self.events.append(('delete',a,kw)),undo=self.undo,redo=self.redo,
            undoInfo=self.undo_info,referenceQuery=lambda *a,**kw:False,skinCluster=self.add_influence)
        self._chunk=None;self._chunk_before=None;self._chunk_mutated=False;self._chunk_depth=0;self._undo_name='Older unrelated edit'
    def same(self,a,b,tolerance=1e-7):return len(a)==len(b) and all(abs(x-y)<=tolerance for x,y in zip(a,b))
    def obj(self,path):return path
    def joint_id(self,path):return path.split('|')[-1]
    def roots(self,ctx):return ['|a']
    def clear_cache(self):self.events.append(('clear_cache',))
    def cache_stats(self):return dict(builds=0,hits=0)
    def inspect(self,panel):panel.message('Inspect OK')
    def context(self,target):
        if target not in ('mesh','meshShape'):raise ValueError('Missing mesh')
        return dict(count=3,shape='meshShape',skin='skin',uuid='mesh-id',ids=list(self.ids),weights=list(self.weights),topology='topology',
                    influences=[types.SimpleNamespace(fullPathName=lambda identity=identity:'|'+identity) for identity in self.ids])
    def metadata(self,ctx):return ('meta',core.remap(self.state,self.ids)) if self.attached else (None,None)
    def snapshot(self):return copy.deepcopy((self.state,self.ids,self.weights,self.attached))
    def restore(self,snapshot):self.state,self.ids,self.weights,self.attached=copy.deepcopy(snapshot)
    def command(self,action,data):
        data=json.loads(data);self.calls.append((action,data))
        if self.fail:raise RuntimeError('Locked or driven weights')
        before=self.snapshot()
        state=core.remap(self.state,self.ids) if self.attached else core.create(self.weights,3,self.ids,'topology')
        if data.get('expected') and data['expected']!=hashlib.sha256(core.encode(state).encode()).hexdigest():raise RuntimeError('Layer data changed during stroke')
        if action in ('assign','flood'):
            vertices=list(range(3)) if data.get('whole',action=='assign') else [int(name.split('[')[1][:-1]) for name in self.selected if name.startswith('mesh.vtx[')]
            if not vertices:raise ValueError('Select mesh vertices, or enable Whole mesh explicitly.')
            if action=='flood':
                action='paint';data.update(mode='weights',values={str(v):data['value'] for v in vertices})
            else:
                import layer_skin_assignment as geometry
                if not state.get('reference'):
                    frames={identity:dict(position=[i*2.,0.,0.],end=[i*2.+1.,0.,0.],x=[1.,0.,0.],y=[0.,1.,0.],z=[0.,0.,1.]) for i,identity in enumerate(self.ids)}
                    ref=dict(points=[[0.,0.,0.],[1.,0.,0.],[2.,0.,0.]],joints=frames,time=1.)
                    state=core.edit(state,'reference',dict(reference=ref))
                row=next(row for row in state['layers'] if row['id']==data['layer'])
                generated,info=geometry.CACHE.generate(state['reference'],self.ids,data.get('joints',row['joints']),data['settings'],vertices)
                data.update(generated=generated,scope=vertices,assignment=info)
        if action=='value_operation':
            import layer_skin_operations
            vertices=list(range(3)) if data.get('whole',False) else [int(name.split('[')[1][:-1]) for name in self.selected if name.startswith('mesh.vtx[')]
            self.state,_,_=layer_skin_operations.edit(state,data,core,vertices)
        elif action=='relax':
            import layer_skin_relax
            vertices=[int(name.split('[')[1][:-1]) for name in self.selected if name.startswith('mesh.vtx[')] or list(range(3))
            graph={0:[1],1:[0,2],2:[1]}
            if data.get('mode')=='mask':
                row=next(row for row in state['layers'] if row['id']==data['layer'])
                values=layer_skin_relax.relax_mask_rows(row['mask'],graph,vertices,data.get('iterations',3),data.get('strength',.5))
                self.state=core.edit(state,'paint',dict(layer=row['id'],mode='mask',values=values))
            else:self.state,_=layer_skin_relax.relax_samples(state,data['layer'],graph,vertices,
                data.get('iterations',3),data.get('strength',.5),data.get('max_new',0),data.get('joints',()),preserve_coverage=data.get('preserve_coverage',False))
        elif action=='relax_stroke':
            import layer_skin_relax
            self.state,_,_=layer_skin_relax.prepare_stroke(self.context(data['target']),state,data,core)
        else:self.state=core.edit(state,action,data)
        self.weights=core.composite(self.state);self.attached=True
        if self._chunk:self._chunk_mutated=True
        else:self.undo_stack.append(before);self.redo_stack=[]
        return 'Layer Skin: '+action
    def undo(self):
        self.redo_stack.append(self.snapshot());self.restore(self.undo_stack.pop())
    def redo(self):
        self.undo_stack.append(self.snapshot());self.restore(self.redo_stack.pop())
    def undo_info(self,**kw):
        if kw.get('query'):
            if kw.get('state'):return True
            if kw.get('undoName'):return self._undo_name
        if kw.get('openChunk'):
            if not self._chunk_depth:
                self._chunk=kw['chunkName'];self._chunk_before=self.snapshot();self._chunk_mutated=False
            self._chunk_depth+=1
        if kw.get('closeChunk'):
            if not self._chunk_depth:raise RuntimeError('No recording Undo chunk is open')
            self._chunk_depth-=1
            if not self._chunk_depth:
                if self._chunk_mutated:self.undo_stack.append(self._chunk_before);self._undo_name=self._chunk
                self._chunk=None
    def add_influence(self,skin,**kw):
        self.events.append(('add_influence',kw));identity=self.joint_id(kw['addInfluence'])
        old=len(self.ids);self.weights=[value for v in range(3) for value in self.weights[v*old:(v+1)*old]+[0.]]
        self.ids.append(identity);self._chunk_mutated=True
    def ls(self,*args,**kw):
        result=list(self.selected) if kw.get('selection') else list(self.hilited) if kw.get('hilite') else list(args[:1])
        return [name.split('.')[0] for name in result] if kw.get('objectsOnly') else result
    def node_type(self,path):return 'mesh' if path=='meshShape' else 'transform' if path=='mesh' else 'joint'
    def relatives(self,node,**kw):
        if node=='meshShape' and kw.get('parent'):return ['mesh']
        return ['meshShape'] if node=='mesh' and kw.get('shapes') else []
    def paint_ctx(self,name,**kw):
        if kw.get('exists'):return self.context_exists
        if kw.get('query'):
            flag=next(key for key in kw if key!='query')
            return ['meshShape'] if flag=='paintNodeArray' else self.context_settings.get(flag)
        # Enforce the documented Artisan profile enum. Accepting arbitrary flags
        # here previously hid an invalid native brush configuration.
        if 'stampProfile' in kw and kw['stampProfile'] not in ('gaussian','poly','solid','square'):
            raise RuntimeError('Unsupported Artisan stamp profile: '+str(kw['stampProfile']))
        if not kw.get('edit'):self.context_exists=True
        self.context_settings.update({key:value for key,value in kw.items() if key!='edit'})
        self.events.append(('paint_ctx',name,kw))
    def mel_eval(self,source):
        self.events.append(('mel',source))
        if source.startswith('rtkLSSurface041('):return session_module.dispatch('surface',json.loads(source[len('rtkLSSurface041('):-1]))
        if source=='rtkLSGet041(1,0)':return session_module.dispatch('get_value',1,0)
        if source.startswith('rtkLSArray041('):return session_module.dispatch('array_attribute',json.loads(source[len('rtkLSArray041('):-1]))
    def select_mode(self,**kw):
        if kw.get('query'):return not self.object_mode if kw.get('component') else self.object_mode
        self.object_mode=not bool(kw['component']) if 'component' in kw else bool(kw.get('object'))
        self.events.append(('select_mode',self.object_mode))
    def select_type(self,**kw):
        if kw.get('allComponents') is False:self.selection_types={}
        self.selection_types.update({name:value for name,value in kw.items() if name!='allComponents'})
        self.events.append(('select_type',dict(kw)))
    def hilite(self,target,**kw):
        self.hilited=[target] if kw.get('replace') else self.hilited+[target]
        self.events.append(('hilite',target,kw))
    def set_tool(self,name):self.events.append(('tool',name));self.tool=name
    def select(self,target,**kw):
        if kw.get('add'):
            if target not in self.selected:self.selected.append(target)
        else:self.selected=[target]
    def make_session(self):
        session=session_module.Session(self)
        def make(parent,selected):
            browser=FakeBrowser();session.browsers.append(browser);self.browsers.append(browser);return browser
        session.make_browser=make;return session
    def make_joint_tree(self,parent,selected):
        browser=FakeBrowser();self.browsers.append(browser);return browser


class PaintTests(unittest.TestCase):
    def setUp(self):self.api=FakeAPI();self.session=session_module.Session(self.api)
    def tearDown(self):self.session.close();sys.modules.pop(session_module.BRIDGE,None)
    def start(self,**kw):self.session.start('mesh',self.api.layer,joint='b',**kw)
    def test_select_cleanup_keeps_view_without_array_or_tool_ownership(self):
        self.start(mode='weights');self.session.before_stroke();self.api.paint_buffer.write([.7,0.,0.])
        self.api.tool='selectSuperContext';self.api.selected=['mesh.vtx[0]'];self.api.object_mode=False
        self.session.tool_cleanup()
        self.assertTrue(self.session.viewing);self.assertFalse(self.session.active)
        self.assertTrue(self.api.weight_view.visible);self.assertEqual(self.api.weight_view.values,[.7,0.,0.])
        self.assertEqual(self.api.selected,['mesh.vtx[0]']);self.assertFalse(self.api.object_mode)
        self.assertEqual(self.api.tool,'selectSuperContext');self.assertIsNone(self.session.buffer)
        self.assertEqual(len(self.api.calls),1);self.assertIsNone(self.api._chunk)
    def test_paused_view_changes_display_and_joint_without_skin_edits(self):
        self.start(mode='weights');self.api.tool='selectSuperContext';self.session.tool_cleanup()
        self.api.selected=['mesh.e[0]'];self.api.object_mode=False;before=self.api.snapshot()
        self.session.set_display('heatmap');self.session.view('mesh',self.api.layer,'a')
        self.assertEqual(self.api.weight_view.display,'heatmap');self.assertEqual(self.api.snapshot(),before)
        self.assertEqual(self.api.tool,'selectSuperContext');self.assertEqual(self.api.selected,['mesh.e[0]'])
    def test_shaded_stop_clears_preview_and_explicit_paint_rebinds_native_array(self):
        self.start(mode='weights');self.api.tool='selectSuperContext';self.session.tool_cleanup()
        self.session.stop();self.assertFalse(self.session.viewing);self.assertFalse(self.api.weight_view.visible)
        self.start(mode='weights');self.assertTrue(self.session.active);self.assertIs(self.session.buffer.owner,self.session)
        self.assertEqual(self.api.tool,session_module.CONTEXT);self.assertTrue(self.api.object_mode)
    def test_stop_still_releases_brush_when_native_preview_cleanup_fails(self):
        self.start(mode='weights')
        with mock.patch.object(self.api.weight_view,'clear',side_effect=RuntimeError('Display cleanup failed')):
            with self.assertRaisesRegex(RuntimeError,'Display cleanup'):self.session.stop()
        self.assertEqual(self.api.tool,'selectSuperContext');self.assertFalse(self.session.active)
        self.assertIsNone(self.session.buffer);self.assertFalse(self.session.viewing)
    def test_file_save_suspends_and_restores_preview_without_weights_or_selection_changes(self):
        self.start(mode='weights');self.api.tool='selectSuperContext';self.session.tool_cleanup()
        before=self.api.snapshot();self.api.selected=['mesh.e[0]']
        self.session.before_file_io();self.assertFalse(self.api.weight_view.visible)
        self.session.after_file_io();self.assertTrue(self.api.weight_view.visible)
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.selected,['mesh.e[0]'])
    def test_paused_refresh_updates_values_and_report_without_activating_brush(self):
        self.start(mode='weights');self.api.tool='selectSuperContext';self.session.tool_cleanup()
        self.api.command('paint',json.dumps(dict(layer=self.api.layer,mode='weights',joint='b',values={'1':.8})))
        self.session.refresh_view();self.assertEqual(self.api.weight_view.values,[0.,.8,0.])
        self.assertFalse(self.session.active);self.assertTrue(self.session.paint_report()['persistent_display']['visible'])
    def test_heatmap_only_changes_native_feedback_flags_and_keeps_scalar_values(self):
        before=self.api.snapshot();self.session.set_display('heatmap');self.start(mode='weights')
        self.assertTrue(self.api.context_settings['useColorRamp']);self.assertFalse(self.api.context_settings['useMaxMinColor'])
        encoded=self.api.context_settings['colorRamp'].split(',');self.assertEqual(len(encoded),25)
        self.assertEqual([float(encoded[i]) for i in range(3,25,5)],[0.,.25,.5,.75,1.])
        self.session.set_display('grayscale');self.assertFalse(self.api.context_settings['useColorRamp'])
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[])
        self.assertEqual(self.session.values,[0.,0.,0.])
    def test_display_switch_saves_pending_stroke_once_before_rebinding_colors(self):
        self.start(mode='weights');self.session.before_stroke();self.api.paint_buffer.write([.7,0.,0.])
        self.session.set_display('heatmap');self.session.after_stroke()
        self.assertEqual(len(self.api.calls),1);self.assertEqual(self.session.values,[.7,0.,0.])
        self.assertEqual(self.session.last_stroke['commit_reason'],'display_change')
    def test_mask_stays_grayscale_and_weight_view_restores_chosen_heatmap(self):
        self.session.set_display('heatmap');self.start(mode='mask')
        self.assertFalse(self.api.context_settings['useColorRamp']);self.assertEqual(self.session.effective_display(),'grayscale')
        self.start(mode='weights');self.assertTrue(self.api.context_settings['useColorRamp'])
    def test_native_context_binds_the_native_array_and_stroke_hooks(self):
        self.start(mode='mask');self.assertTrue(self.session.active)
        config=next(event[2] for event in self.api.events if event[0]=='paint_ctx' and event[2].get('edit'))
        self.assertEqual(config['setValueCommand'],'');self.assertEqual(config['getValueCommand'],'')
        self.assertEqual(config['initializeCmd'],'');self.assertEqual(config['finalizeCmd'],'')
        self.assertEqual(config['getArrayAttrCommand'],'rtkLSArray041')
        self.assertFalse(config['colorfeedback']);self.assertTrue(self.api.context_settings['colorfeedback']);self.assertEqual(self.api.tool,session_module.CONTEXT)
        self.assertEqual(config['toolSetupCmd'],'rtkLSSetup041');self.assertEqual(config['chunkCommand'],'')
        self.assertEqual(config['stampProfile'],'solid');self.assertEqual(config['paintoperationtype'],'Paint')
        self.assertEqual(config['whichTool'],'userPaint');self.assertEqual(config['setArrayValueCommand'],'')
        self.assertEqual(config['beforeStrokeCmd'],'rtkLSBefore041');self.assertEqual(config['afterStrokeCmd'],'rtkLSAfter041')
        self.assertTrue(config['outline']);self.assertTrue(config['tangentOutline']);self.assertFalse(config['colorfeedbackOverride']);self.assertFalse(config['disablelighting'])
        self.assertTrue(self.api.context_settings['colorfeedbackOverride']);self.assertTrue(self.api.context_settings['disablelighting'])
        self.assertTrue(self.api.object_mode);self.assertEqual(self.api.selected,['mesh'])
    def test_wrong_native_artisan_backend_is_rejected_even_when_context_name_matches(self):
        original=self.api.cmds.setToolTo
        def activate(name):
            original(name)
            if name==session_module.CONTEXT:self.api.context_settings['whichTool']='general'
        self.api.cmds.setToolTo=activate
        with self.assertRaisesRegex(RuntimeError,"requires userPaint"):self.start(mode='mask')
        self.assertFalse(self.session.active);self.assertEqual(self.api.tool,'selectSuperContext');self.assertEqual(self.api.calls,[])
        self.assertIn('general',self.session.last_error)
    def test_display_feedback_is_reapplied_after_native_activation(self):
        original=self.api.cmds.setToolTo
        def activate(name):
            original(name)
            if name==session_module.CONTEXT:self.api.context_settings.update(colorfeedback=False,colorfeedbackOverride=False,disablelighting=False,outline=False,stampProfile='poly')
        self.api.cmds.setToolTo=activate;self.start(mode='mask')
        self.assertTrue(self.api.context_settings['colorfeedback']);self.assertTrue(self.api.context_settings['colorfeedbackOverride'])
        self.assertTrue(self.api.context_settings['disablelighting'])
        self.assertTrue(self.api.context_settings['outline']);self.assertEqual(self.api.context_settings['stampProfile'],'solid')
    def test_feedback_setup_can_read_saved_values_before_tool_activation(self):
        self.api.state=core.edit(self.api.state,'paint',dict(layer=self.api.layer,mode='mask',values={'0':.25,'1':.6}))
        original=self.api.cmds.artUserPaintCtx;observed=[]
        def configure(name,**kwargs):
            result=original(name,**kwargs)
            if kwargs.get('edit') and kwargs.get('getArrayAttrCommand'):
                # An initialization request while installing feedback must have
                # a valid read-only surface even before the tool is active.
                attribute=self.session.array_attribute('meshShape')
                observed.append((attribute,self.session.buffer.read(),self.session.stroke))
            return result
        self.api.cmds.artUserPaintCtx=configure;before=self.api.snapshot();self.start(mode='mask')
        self.assertEqual(observed,[('paintBuffer.values',[.25,.6,1.],None)]);self.assertEqual(self.api.snapshot(),before)
    def test_view_activation_explicitly_reloads_feedback_after_tool_selection(self):
        self.start(mode='mask');self.session.stop();self.api.events=[];self.start(mode='mask',readonly=True)
        activation=next(i for i,event in enumerate(self.api.events) if event[0]=='tool' and event[1]==session_module.CONTEXT)
        states=[event[2]['colorfeedback'] for event in self.api.events[activation+1:] if event[0]=='paint_ctx' and 'colorfeedback' in event[2]]
        self.assertEqual(states,[True]);self.assertEqual(self.api.calls,[])
    def test_last_save_receipt_survives_view_switches(self):
        self.start(mode='weights');self.session.initialize('meshShape');self.session.set_value(1,0,.7);self.session.finalize(1)
        saved=dict(self.session.last_stroke);self.start(mode='mask',readonly=True)
        self.assertEqual(self.session.paint_report()['last_stroke'],saved)
    def test_feedback_reload_does_not_open_a_stroke_or_change_saved_data(self):
        self.start(mode='weights');before=self.api.snapshot()
        original=self.api.cmds.artUserPaintCtx;observed=[]
        def configure(name,**kwargs):
            result=original(name,**kwargs)
            if 'colorfeedback' in kwargs:
                observed.append(self.session.initialize('meshShape'))
            return result
        self.api.cmds.artUserPaintCtx=configure;self.session.refresh_view(force=True)
        self.assertEqual(observed,['-id 1']);self.assertIsNone(self.session.stroke)
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[])
    def test_saved_masks_and_weights_survive_repeated_view_switches_and_serialization(self):
        self.start(mode='mask');self.session.before_stroke();self.session.set_value(1,0,.25);self.session.set_value(1,1,.6);self.session.after_stroke()
        self.start(mode='weights');self.session.before_stroke();self.session.set_value(1,1,.75);self.session.after_stroke()
        saved=self.api.snapshot();calls=len(self.api.calls)
        for repeat in range(3):
            self.api.state=core.decode(core.encode(self.api.state))
            self.start(mode='mask',readonly=True);self.assertEqual(self.session.values,[.25,.6,1.])
            self.assertIsNone(self.session.stroke);self.assertEqual(self.session.initialize('meshShape'),'-id 1');self.assertIsNone(self.session.stroke)
            self.session.start('mesh',self.api.layer,joint='a',mode='weights');self.assertEqual(self.session.values,[0.]*3)
            self.start(mode='weights');self.assertEqual(self.session.values,[0.,.75,0.])
        self.assertEqual(self.api.snapshot(),saved);self.assertEqual(len(self.api.calls),calls)
    def test_base_white_mask_survives_skin_and_weight_view_switches(self):
        before=self.api.snapshot()
        self.session.start('mesh',session_module.BASE,mode='mask',readonly=True);self.assertEqual(self.session.values,[1.]*3)
        self.start(mode='weights');self.start(mode='skin',readonly=True)
        self.session.start('mesh',session_module.BASE,mode='mask',readonly=True)
        self.assertEqual(self.session.values,[1.]*3);self.assertEqual(self.api.snapshot(),before)
    def test_final_skin_view_reads_actual_skin_weights_instead_of_empty_layer_samples(self):
        self.api.weights=[.2,.8]*3;before=self.api.snapshot()
        self.start(mode='skin',readonly=True)
        self.assertEqual(self.session.values,[.8]*3)
        self.session.initialize('meshShape');self.session.set_value(1,0,0.);self.session.finalize(1)
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[])
        report=self.session.paint_report();self.assertEqual(report['display_values']['min'],.8)
        self.assertEqual(report['display_source'],'skinCluster weights (read-only)')
    def test_final_skin_view_can_inspect_an_unbound_joint_without_binding_it(self):
        before=self.api.snapshot()
        self.session.start('mesh',self.api.layer,joint='new',joint_path='|new',mode='skin',readonly=True)
        self.assertEqual(self.session.values,[0.]*3);self.session.stop()
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.undo_stack,[])
    def test_final_skin_view_requires_readonly_mode(self):
        with self.assertRaisesRegex(ValueError,'read-only'):self.start(mode='skin',readonly=False)
        self.assertEqual(self.api.calls,[]);self.assertEqual(self.api.tool,'selectSuperContext')
    def test_layer_and_final_skin_views_use_different_data_sources(self):
        self.start(mode='weights');self.assertEqual(self.session.values,[0.]*3);self.session.stop()
        self.api.weights=[.3,.7]*3;self.start(mode='skin',readonly=True)
        self.assertEqual(self.session.values,[.7]*3)
    def test_final_skin_view_refresh_uses_current_native_weights(self):
        self.start(mode='skin',readonly=True);self.assertEqual(self.session.values,[0.]*3)
        self.api.weights=[.4,.6]*3;self.session.refresh_view()
        self.assertEqual(self.session.values,[.6]*3);self.assertEqual(self.api.calls,[])
    def test_failed_mel_surface_return_does_not_switch_tools_or_report_active(self):
        original=self.api.mel.eval
        self.api.mel.eval=lambda source:None if source.startswith('rtkLSSurface041(') else original(source)
        with self.assertRaisesRegex(RuntimeError,'resolve the loaded mesh'):self.start(mode='mask')
        self.assertEqual(self.api.tool,'selectSuperContext');self.assertEqual(self.api.selected,['mesh'])
        self.assertFalse(self.session.active);self.assertEqual(self.api.calls,[])
        self.assertIn('resolve the loaded mesh',self.session.last_error)
    def test_failed_mel_scalar_return_does_not_activate_brush(self):
        original=self.api.mel.eval
        for value in (None,float('nan'),.4):
            with self.subTest(value=value):
                self.api.mel.eval=lambda source:value if source=='rtkLSGet041(1,0)' else original(source)
                with self.assertRaisesRegex(RuntimeError,'vertex value'):self.start(mode='mask')
                self.assertFalse(self.session.active);self.assertEqual(self.api.tool,'selectSuperContext')
    def test_tool_switch_failure_cleans_the_session_and_retains_error(self):
        self.api.cmds.setToolTo=mock.Mock(side_effect=RuntimeError('tool activation failed'))
        with self.assertRaisesRegex(RuntimeError,'activation failed'):self.start(mode='mask')
        self.assertFalse(self.session.active);self.assertEqual(self.session.last_error,'tool activation failed')
        self.assertIsNone(self.session.stroke);self.assertEqual(self.api.calls,[])
    def test_brush_started_from_components_preserves_mode_and_hilites_mesh(self):
        self.api.selected=['mesh.vtx[1]'];self.api.object_mode=False;self.start(mode='mask')
        self.assertEqual(self.api.selected,['mesh.vtx[1]','mesh']);self.assertFalse(self.api.object_mode)
        self.assertEqual(self.api.hilited,['mesh'])
        self.assertLess(next(i for i,event in enumerate(self.api.events) if event[0]=='hilite'),
                        next(i for i,event in enumerate(self.api.events) if event[0]=='tool'))
    def test_surface_accepts_transform_shape_and_component_but_rejects_another_mesh(self):
        self.start(mode='mask')
        for name in ('mesh','meshShape','mesh.vtx[1]'):self.assertEqual(self.session.surface(name),'meshShape')
        self.assertEqual(self.session.surface('otherMesh'),'');self.assertEqual(self.session.surface('meshShapeOrig'),'')
        self.assertEqual(self.session.surface(''),'')
    def test_surface_resolves_namespaced_aliases_to_the_full_loaded_dag_path(self):
        self.start(mode='mask');self.session.target='|char|ns:mesh|ns:meshShape'
        self.api.cmds.ls=lambda *args,**kw:['|char|ns:mesh']
        self.api.cmds.listRelatives=lambda *args,**kw:['|char|ns:mesh|ns:meshShape']
        self.assertEqual(self.session.surface('ns:mesh'),self.session.target)
    def test_report_is_read_only_during_an_uncommitted_stroke(self):
        self.start(mode='mask');self.session.initialize('meshShape');self.session.set_value(1,0,.2)
        before=self.api.snapshot();pending=copy.deepcopy(self.session.stroke);tool=self.api.tool
        with mock.patch.object(self.api,'context',side_effect=AssertionError('Report must not read skin weights')):
            report=self.session.paint_report()
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.session.stroke,pending);self.assertEqual(self.api.tool,tool)
        self.assertEqual(report['selected_surfaces'],['meshShape']);self.assertEqual(report['registered_plugin']['version'],self.api.VERSION)
        self.assertEqual(report['context_settings']['paintNodeArray'],['meshShape']);self.assertEqual(self.api.calls,[])
    def test_report_retains_callback_failures_and_explains_unsupported_queries(self):
        self.start(mode='mask');self.session.initialize('meshShape')
        session_module.dispatch('set_value',1,99,.5)
        original=self.api.cmds.artUserPaintCtx
        def query(name,**kw):
            if kw.get('query') and kw.get('profileShapeFile'):raise RuntimeError('query unsupported')
            return original(name,**kw)
        self.api.cmds.artUserPaintCtx=query
        report=self.session.paint_report()
        self.assertIn('outside',report['last_callback_error']);self.assertEqual(report['query_errors']['profileShapeFile'],'query unsupported')
    def test_report_shows_a_different_current_context_instead_of_claiming_active_paint(self):
        self.start(mode='mask');self.api.tool='art3dPaintContext'
        report=self.session.paint_report()
        self.assertEqual(report['active_context'],'art3dPaintContext');self.assertEqual(report['layer_skin_context'],session_module.CONTEXT)
        self.assertFalse(report['active'])
    def test_mel_scalar_bridge_uses_a_returning_python_expression(self):
        self.start(mode='mask');self.session.initialize('meshShape')
        source=session_module.mel_procedures()
        self.assertNotIn('import sys;',source)
        expression="__import__('sys').modules['"+session_module.BRIDGE+"'].dispatch('get_value',1,0)"
        self.assertEqual(eval(expression),1.)
        initialize=next(line for line in source.splitlines() if "dispatch('initialize'" in line)
        self.assertIn('encodeString($name)',initialize)
        self.assertNotIn('\\\\\\"',initialize)
    def test_mask_samples_commit_once_at_stroke_end_and_undo(self):
        self.start(mode='mask');self.session.initialize('meshShape')
        self.session.set_value(1,0,.4);self.session.set_value(1,0,.2);self.session.set_value(1,1,.8)
        self.assertEqual(self.api.calls,[]);self.assertEqual(self.session.get_value(1,0),.2)
        self.session.finalize(1);self.assertEqual(len(self.api.calls),1)
        self.assertEqual(self.api.state['layers'][0]['mask'],{'0':.2,'1':.8})
        self.api.undo();self.assertEqual(self.api.state['layers'][0]['mask'],{})
    def test_weight_paint_updates_only_touched_vertices(self):
        self.start(mode='weights');self.session.initialize('meshShape');self.session.set_value(1,1,.75);self.session.finalize(1)
        self.assertEqual(self.api.weights,[1,0,.25,.75,1,0]);self.assertEqual(len(self.api.undo_stack),1)
    def test_samples_without_initialization_are_saved_before_switching_views(self):
        self.start(mode='weights');self.session.set_value(1,1,.75)
        self.session.start('mesh',self.api.layer,joint='a',mode='weights')
        self.start(mode='weights')
        self.assertEqual(self.session.values,[0.,.75,0.]);self.assertEqual(len(self.api.undo_stack),1)
    def test_repeated_before_callback_does_not_erase_collected_samples(self):
        self.start(mode='weights');self.session.before_stroke();self.session.set_value(1,0,.8)
        self.session.before_stroke();self.session.after_stroke()
        self.assertEqual(self.session.values,[.8,0.,0.]);self.assertEqual(len(self.api.undo_stack),1)
    def test_tool_cleanup_saves_samples_before_native_tool_setup_and_closes_undo(self):
        self.start(mode='weights');self.session.set_value(1,0,.8);self.session.tool_cleanup()
        self.assertIsNone(self.session.stroke);self.assertFalse(self.session.active)
        self.assertIsNone(self.api._chunk);self.assertEqual(self.api._chunk_depth,0)
        self.assertIsNone(self.api.paint_buffer.owner);self.assertIsNone(self.session.buffer)
        # Incoming native-tool settings can reject later writes. There must be
        # no deferred Layer Skin command left to run under those settings.
        self.api.fail=True;self.api.tool='artAttrSkinContext'
        self.session.flush_pending('tool_change')
        self.assertTrue(self.api.same(self.api.weights,[.2,.8,1.,0.,1.,0.]));self.assertEqual(len(self.api.undo_stack),1)
        self.assertEqual(self.session.last_stroke['commit_reason'],'tool_change');self.assertEqual(len(self.api.calls),1)
    def test_tool_cleanup_saves_native_array_once_and_ignores_late_callbacks(self):
        self.start(mode='weights');self.session.before_stroke();self.api.paint_buffer.write([.7,0.,.2])
        self.session.tool_cleanup();saved=self.api.snapshot();self.api.tool='artAttrSkinContext'
        self.session.before_stroke();self.session.set_value(1,0,0.);self.session.after_stroke();self.session.finalize(1)
        self.session.tool_cleanup();self.session.flush_pending('mouse_release_fallback')
        self.assertEqual(self.api.snapshot(),saved);self.assertEqual(len(self.api.calls),1)
        self.assertEqual(self.session.initialize('meshShape'),'-id -1')
        self.assertEqual(self.session.array_attribute('meshShape'),'')
        self.assertIsNone(self.api.paint_buffer.owner);self.assertIsNone(self.api._chunk)
        self.assertEqual(self.api.tool,'artAttrSkinContext')
    def test_rejected_tool_handoff_releases_array_closes_chunk_and_warns_once(self):
        self.start(mode='weights');self.session.before_stroke();self.session.set_value(1,0,.7);self.api.fail=True
        session_module.dispatch('tool_cleanup');self.api.tool='artAttrSkinContext'
        self.session.flush_pending('late_release');self.session.after_stroke()
        self.assertEqual(len(self.api.warnings),1);self.assertEqual(len(self.api.calls),1)
        self.assertEqual(self.api.weights,[1.,0.]*3);self.assertIsNone(self.api._chunk)
        self.assertFalse(self.session.active);self.assertFalse(self.session._view_ready)
        self.assertIsNone(self.session.stroke);self.assertIsNone(self.api.paint_buffer.owner)
        self.assertEqual(self.session.last_stroke['status'],'rejected')
    def test_readonly_handoff_disables_layer_feedback_without_skin_writes(self):
        self.start(mode='skin',readonly=True);before=self.api.snapshot();self.session.tool_cleanup()
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[])
        self.assertFalse(self.api.context_settings['colorfeedback']);self.assertFalse(self.api.context_settings['disablelighting'])
        self.assertIsNone(self.api.paint_buffer.owner)
    def test_native_skin_edits_reject_before_reactivating_layer_brush_then_undo_allows_resume(self):
        self.start(mode='weights');self.session.set_value(1,0,.8);self.session.tool_cleanup()
        saved=self.api.snapshot();self.api.tool='artAttrSkinContext';self.api.weights[2:4]=[.5,.5]
        self.api.events=[];before=self.api.snapshot();calls=len(self.api.calls)
        with self.assertRaisesRegex(ValueError,'Undo the native strokes'):self.start(mode='weights')
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.tool,'artAttrSkinContext')
        self.assertFalse(self.session.active);self.assertEqual(len(self.api.calls),calls)
        self.assertFalse(any(event[0]=='tool' for event in self.api.events))
        self.api.restore(saved);self.start(mode='weights');self.assertEqual(self.session.values,[.8,0.,0.])
    def test_native_skin_edits_still_allow_readonly_final_weight_inspection(self):
        self.api.weights[:2]=[.25,.75]
        self.start(mode='skin',readonly=True);self.assertEqual(self.session.values,[.75,0.,0.])
        self.assertEqual(self.api.calls,[])
    def test_uninitialized_unbound_samples_bind_only_when_the_switch_saves_them(self):
        before=self.api.snapshot();self.session.start('mesh',self.api.layer,joint='new',joint_path='|new',mode='weights')
        self.session.set_value(1,0,.8);self.assertNotIn('new',self.api.ids)
        self.start(mode='mask',readonly=True)
        self.assertIn('new',self.api.ids);self.assertEqual(len(self.api.undo_stack),1)
        self.api.undo();self.assertEqual(self.api.snapshot(),before)
    def test_display_setup_cannot_capture_samples_or_schedule_a_write(self):
        self.start(mode='weights');pending=mock.Mock();self.session.on_pending=pending
        self.session._configuring_view=True;self.session.set_value(1,0,.8);self.session._configuring_view=False
        self.assertIsNone(self.session.stroke);pending.assert_not_called();self.assertEqual(self.api.calls,[])
    def test_repeated_surface_initialization_preserves_pending_paint(self):
        self.start(mode='weights');self.session.initialize('meshShape');self.session.set_value(1,0,.8)
        self.session.initialize('meshShape');self.session.set_value(1,1,.4);self.session.finalize(1)
        self.assertEqual(self.session.values,[.8,.4,0.]);self.assertEqual(len(self.api.calls),1)
    def test_commit_keeps_new_values_available_to_reentrant_display_reads(self):
        self.start(mode='weights');self.session.initialize('meshShape');self.session.set_value(1,0,.8)
        command=self.api.cmds.rtkLayerSkin;observed=[]
        def commit(**kwargs):
            observed.append(self.session.get_value(1,0))
            self.session.initialize('meshShape')
            observed.append(self.session.get_value(1,0))
            return command(**kwargs)
        self.api.cmds.rtkLayerSkin=commit;self.session.finalize(1)
        self.assertEqual(observed,[.8,.8]);self.assertEqual(self.session.get_value(1,0),.8)
        self.assertIsNone(self.session.stroke);self.assertEqual(len(self.api.calls),1)
    def test_reentrant_set_and_finalize_during_commit_cannot_create_a_second_edit(self):
        self.start(mode='weights');self.session.initialize('meshShape');self.session.set_value(1,0,.8)
        command=self.api.cmds.rtkLayerSkin
        def commit(**kwargs):
            self.session.set_value(1,0,0.);self.session.finalize(1);self.session.before_stroke()
            return command(**kwargs)
        self.api.cmds.rtkLayerSkin=commit;self.session.finalize(1)
        self.assertEqual(self.session.values,[.8,0.,0.]);self.assertEqual(len(self.api.undo_stack),1)
    def test_release_fallback_commits_once_and_successive_gestures_need_no_reinitialization(self):
        self.start(mode='weights');self.session.initialize('meshShape')
        self.session.before_stroke();self.session.set_value(1,0,.6);self.session.after_stroke();self.session.finalize(1)
        self.session.before_stroke();self.session.set_value(1,1,.8);self.session.finalize(1);self.session.after_stroke()
        self.assertEqual(self.session.values,[.6,.8,0.]);self.assertEqual(len(self.api.undo_stack),2)
        self.api.undo();self.assertEqual(self.api.weights,[.4,.6,1.,0.,1.,0.])
    def test_late_setters_outside_a_stroke_do_not_create_another_edit(self):
        self.start(mode='weights');self.session.initialize('meshShape')
        self.session.set_value(1,0,.6);self.session.finalize(1)
        self.session.can_begin_stroke=lambda:False
        self.session.set_value(1,1,.8);self.session.finalize(1)
        self.assertEqual(self.session.values,[.6,0.,0.]);self.assertEqual(len(self.api.undo_stack),1)
    def test_rejected_stroke_recovers_on_next_gesture_and_clears_old_error(self):
        self.start(mode='weights');self.session.initialize('meshShape');self.api.fail=True
        self.session.before_stroke();self.session.set_value(1,0,.8);session_module.dispatch('finalize',1)
        self.assertEqual(self.session.get_value(1,0),0.);self.assertEqual(self.session.last_stroke['status'],'rejected')
        self.assertTrue(self.session.active);self.assertEqual(len(self.api.undo_stack),0)
        self.api.fail=False;self.session.before_stroke();self.session.set_value(1,1,.7);self.session.after_stroke()
        report=self.session.paint_report()
        self.assertEqual(self.session.values,[0.,.7,0.]);self.assertIsNone(report['last_callback_error'])
        self.assertEqual(report['last_stroke']['status'],'saved');self.assertTrue(report['last_stroke']['layer_values_verified'])
        self.assertEqual(len(self.api.undo_stack),1)
    def test_repeated_initialize_does_not_hide_a_stale_data_conflict(self):
        self.start(mode='weights');self.session.initialize('meshShape');self.session.set_value(1,0,.8)
        self.api.state=core.edit(self.api.state,'properties',dict(layer=self.api.layer,name='External change'))
        self.session.initialize('meshShape')
        with self.assertRaisesRegex(RuntimeError,'changed'):self.session.finalize(1)
        self.assertEqual(self.api.weights,[1.,0.]*3);self.assertEqual(self.session.last_stroke['status'],'rejected')
    def test_stored_value_mismatch_is_reported_instead_of_claiming_saved(self):
        self.start(mode='weights');self.session.initialize('meshShape');self.session.set_value(1,0,.8)
        self.api.cmds.rtkLayerSkin=lambda **kwargs:'unexpected command owner did not save'
        with self.assertRaisesRegex(RuntimeError,'saved layer values'):self.session.finalize(1)
        self.assertEqual(self.session.last_stroke['status'],'verification_failed')
        self.assertFalse(self.session.last_stroke['layer_values_verified']);self.assertEqual(self.session.values,[0.]*3)
    def test_post_commit_ui_refresh_does_not_reconfigure_the_brush(self):
        self.start(mode='weights');self.session.initialize('meshShape');self.session.set_value(1,0,.8);self.session.finalize(1)
        self.api.events=[];self.session.refresh_view(self.session.snapshot('meshShape'))
        self.assertEqual(self.api.events,[]);self.assertEqual(self.session.values,[.8,0.,0.])
    def test_foreign_finalize_does_not_erase_the_valid_surface_stroke(self):
        self.start(mode='weights');self.session.initialize('meshShape');self.session.set_value(1,0,.8)
        self.session.finalize(-1);self.session.finalize(1)
        self.assertEqual(self.session.get_value(1,0),.8);self.assertEqual(len(self.api.calls),1)
    def test_first_paint_adds_a_bound_joint_to_an_empty_layer_in_one_undo(self):
        self.api.state=core.edit(self.api.state,'membership',dict(layer=self.api.layer,joints=[]))
        before=self.api.snapshot();self.start(mode='weights')
        self.assertEqual(self.api.snapshot(),before)
        self.session.initialize('meshShape');self.session.set_value(1,1,.6);self.session.finalize(1)
        self.assertEqual(self.api.state['layers'][0]['joints'],['b']);self.assertEqual(len(self.api.undo_stack),1)
        self.api.undo();self.assertEqual(self.api.snapshot(),before)
        self.api.redo();self.assertEqual(self.api.state['layers'][0]['joints'],['b'])
    def test_unbound_first_stroke_binds_membership_and_weights_together_with_undo_redo(self):
        before=self.api.snapshot()
        self.session.start('mesh',self.api.layer,joint='new',joint_path='|new',mode='weights')
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.session.values,[0.,0.,0.])
        self.session.initialize('meshShape');self.session.set_value(1,1,.7);self.session.finalize(1)
        self.assertEqual(self.api.ids,['a','b','new']);self.assertEqual(len(self.api.undo_stack),1)
        self.assertTrue(self.api.same(self.api.weights,[1,0,0,.3,0,.7,1,0,0]))
        self.assertEqual(self.api.state['base'],[1,0,0]*3);self.assertIn('new',self.api.state['layers'][0]['joints'])
        after=self.api.snapshot();self.api.undo();self.assertEqual(self.api.snapshot(),before)
        self.api.redo();self.assertEqual(self.api.snapshot(),after)
    def test_cancelled_or_zero_unbound_stroke_does_not_bind_or_add_membership(self):
        before=self.api.snapshot()
        self.session.start('mesh',self.api.layer,joint='new',joint_path='|new',mode='weights')
        self.session.initialize('meshShape');self.session.set_value(1,0,.6);self.session.stop()
        self.assertEqual(self.api.snapshot(),before)
        self.session.start('mesh',self.api.layer,joint='new',joint_path='|new',mode='weights')
        self.session.initialize('meshShape');self.session.set_value(1,0,0.);self.session.finalize(1)
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.undo_stack,[])
    def test_unbound_stroke_command_failure_rolls_back_its_binding(self):
        before=self.api.snapshot();self.api.fail=True
        self.session.start('mesh',self.api.layer,joint='new',joint_path='|new',mode='weights')
        self.session.initialize('meshShape');self.session.set_value(1,0,.7)
        with self.assertRaisesRegex(RuntimeError,'Locked'):self.session.finalize(1)
        self.assertEqual(self.api.snapshot(),before)
    def test_stale_unbound_stroke_is_rejected_before_binding(self):
        self.session.start('mesh',self.api.layer,joint='new',joint_path='|new',mode='weights')
        self.session.initialize('meshShape');self.session.set_value(1,0,.7)
        self.api.state=core.edit(self.api.state,'properties',dict(layer=self.api.layer,name='Changed elsewhere'))
        before=self.api.snapshot()
        with self.assertRaisesRegex(RuntimeError,'changed'):self.session.finalize(1)
        self.assertEqual(self.api.snapshot(),before);self.assertNotIn('new',self.api.ids)
        self.assertFalse(any(event[0]=='add_influence' for event in self.api.events))
    def test_native_binding_side_effect_cannot_bypass_stale_stroke_guard(self):
        before=self.api.snapshot();native_add=self.api.cmds.skinCluster
        def add(*args,**kw):
            native_add(*args,**kw)
            self.api.state=core.edit(self.api.state,'properties',dict(layer=self.api.layer,name='Changed during binding'))
        self.api.cmds.skinCluster=add
        self.session.start('mesh',self.api.layer,joint='new',joint_path='|new',mode='weights')
        self.session.initialize('meshShape');self.session.set_value(1,0,.7)
        with self.assertRaisesRegex(RuntimeError,'changed while binding'):self.session.finalize(1)
        self.assertEqual(self.api.snapshot(),before)
    def test_read_only_mask_view_never_writes(self):
        self.start(mode='mask',readonly=True);self.session.initialize('meshShape');self.session.set_value(1,0,0);self.session.finalize(1)
        self.assertEqual(self.api.calls,[]);self.assertEqual(self.session.get_value(1,0),1.)
    def test_base_is_visible_but_cannot_be_painted(self):
        self.session.start('mesh',session_module.BASE,mode='mask',readonly=True)
        self.assertEqual(self.session.values,[1.]*3)
        with self.assertRaisesRegex(ValueError,'Base is preserved'):self.session.start('mesh',session_module.BASE,mode='mask')
    def test_stopping_discards_unfinished_stroke_and_restores_tool(self):
        self.start(mode='mask');self.session.initialize('meshShape');self.session.set_value(1,0,0);self.session.stop()
        self.assertEqual(self.api.calls,[]);self.assertEqual(self.api.tool,'selectSuperContext');self.assertIsNone(self.session.stroke)
        self.assertFalse(self.api.context_settings['colorfeedback']);self.assertFalse(self.api.context_settings['colorfeedbackOverride'])
        self.assertFalse(self.api.context_settings['disablelighting'])
    def test_stop_does_not_replace_another_tool(self):
        self.start(mode='mask');self.api.tool='moveSuperContext';self.session.stop();self.assertEqual(self.api.tool,'moveSuperContext')
    def test_unchanged_stroke_creates_no_undo(self):
        self.start(mode='mask');self.session.initialize('meshShape');self.session.set_value(1,0,1);self.session.finalize(1)
        self.assertEqual(self.api.calls,[])
    def test_external_metadata_change_rejects_stroke(self):
        self.start(mode='mask');self.session.initialize('meshShape');self.session.set_value(1,0,0)
        self.api.state=core.edit(self.api.state,'properties',dict(layer=self.api.layer,name='Changed'))
        with self.assertRaisesRegex(RuntimeError,'changed'):self.session.finalize(1)
        self.assertEqual(self.api.state['layers'][0]['mask'],{})
    def test_invalid_sample_discards_whole_stroke(self):
        self.start(mode='mask');self.session.initialize('meshShape')
        session_module.dispatch('set_value',1,0,float('nan'));session_module.dispatch('set_value',1,1,.2)
        session_module.dispatch('finalize',1);self.assertEqual(self.api.calls,[])
    def test_foreign_surface_and_ids_are_ignored(self):
        self.start(mode='mask');self.assertEqual(self.session.initialize('other'),'-id -1')
        self.assertEqual(self.session.get_value(-1,0),0)
    def test_no_skin_or_joint_transforms_are_changed_by_view(self):
        before=self.api.snapshot();self.start(mode='mask',readonly=True);self.session.stop()
        self.assertEqual(self.api.snapshot(),before)


class LifecycleTests(unittest.TestCase):
    def setUp(self):self.api=FakeAPI();self.session=session_module.Session(self.api)
    def tearDown(self):self.session.close();sys.modules.pop(session_module.BRIDGE,None)
    def test_save_and_export_callbacks_suspend_temporary_colors_and_are_removed(self):
        for name in ('kBeforeSave','kAfterSave','kBeforeExport','kAfterExport'):setattr(self.api.om.MSceneMessage,name,name)
        self.session.listen(lambda:None,lambda:None);self.assertEqual(len(self.api.callbacks),13)
        self.session.start('mesh',self.api.layer,joint='b',mode='weights')
        self.api.tool='selectSuperContext';self.session.tool_cleanup()
        callbacks={kind:callback for kind,callback in self.api.callbacks.values()}
        for before,after in (('kBeforeSave','kAfterSave'),('kBeforeExport','kAfterExport')):
            callbacks[before]();self.assertFalse(self.api.weight_view.visible)
            callbacks[after]();self.assertTrue(self.api.weight_view.visible)
        self.session.unlisten();self.assertEqual(self.api.callbacks,{})
    def test_listeners_install_once_and_all_are_removed(self):
        changed=mock.Mock();reset=mock.Mock();self.session.listen(changed,reset);self.session.listen(changed,reset)
        self.assertEqual(len(self.api.callbacks),9);self.session.unlisten();self.assertEqual(self.api.callbacks,{})
    def test_tool_changed_fallback_saves_once_without_stealing_incoming_context(self):
        self.session.listen(lambda:None,lambda:None);self.session.start('mesh',self.api.layer,joint='b',mode='weights')
        self.session.before_stroke();self.api.paint_buffer.write([.6,0.,0.]);self.api.tool='artAttrSkinContext'
        callback=next(callback for kind,callback in self.api.callbacks.values() if kind=='ToolChanged')
        callback();callback();self.session.flush_pending('late_release')
        self.assertFalse(self.session.active);self.assertEqual(self.api.tool,'artAttrSkinContext')
        self.assertEqual(len(self.api.calls),1);self.assertEqual(self.api.weights,[.4,.6,1.,0.,1.,0.])
        self.assertIsNone(self.api._chunk);self.assertIsNone(self.api.paint_buffer.owner)
    def test_history_marks_refresh_but_selection_does_not(self):
        self.session.listen(lambda:None,lambda:None)
        callbacks={kind:callback for kind,callback in self.api.callbacks.values()}
        callbacks['SelectionChanged']();self.assertFalse(self.session.needs_refresh)
        callbacks['Undo']();self.assertTrue(self.session.needs_refresh)
    def test_late_callback_after_close_is_inert(self):
        changed=mock.Mock();reset=mock.Mock();self.session.listen(changed,reset);callbacks=list(self.api.callbacks.values())
        self.session.close()
        for _,callback in callbacks:callback()
        changed.assert_not_called();reset.assert_not_called()
    def test_close_clears_bridge_and_context(self):
        self.session.start('mesh',self.api.layer,mode='mask');self.session.close()
        self.assertIsNone(sys.modules[session_module.BRIDGE].session)
        self.assertTrue(any(event[0]=='delete' for event in self.api.events))
        self.assertEqual(session_module.dispatch('get_value',1,0),0.)
    def test_joint_selection_keeps_current_mesh(self):
        self.api.selected=['|a'];self.assertEqual(self.session.selection(),(None,['|a']))
        self.api.selected=['mesh'];self.assertEqual(self.session.selection(),('meshShape',[]))
    def test_close_cleans_remaining_resources_after_stop_failure(self):
        browser=FakeBrowser();self.session.browsers=[browser];self.session.stop=mock.Mock(side_effect=RuntimeError('stop error'))
        self.session.close();self.assertTrue(browser.closed);self.assertTrue(self.session.closed)
    def test_maya_exit_drops_callbacks_and_buffers_without_native_ui_calls(self):
        self.session.listen(mock.Mock(),mock.Mock())
        self.session.start('mesh',self.api.layer,mode='mask');self.session.initialize('meshShape')
        browser=FakeBrowser();browser.close=mock.Mock();self.session.browsers=[browser]
        self.session.set_value(1,0,.2);self.api.events=[]
        callback=next(callback for kind,callback in self.api.callbacks.values() if kind=='MayaExiting')
        callback();self.session.close()
        self.assertEqual(self.api.callbacks,{});self.assertEqual(self.api.events,[]);self.assertEqual(self.api.calls,[])
        self.assertTrue(self.session.closed);self.assertIsNone(self.session.stroke);self.assertIsNone(self.session.state)
        self.assertEqual(self.session.values,[]);self.assertEqual(self.session.browsers,[])
        self.assertTrue(browser.closed);browser.close.assert_not_called()
        self.assertIsNone(sys.modules[session_module.BRIDGE].session)
    def test_second_active_paint_session_is_rejected(self):
        self.session.start('mesh',self.api.layer,mode='mask');other=session_module.Session(self.api)
        try:
            with self.assertRaisesRegex(ValueError,'other Layer Skin'):other.start('mesh',self.api.layer,mode='mask')
            self.assertIs(sys.modules[session_module.BRIDGE].session,self.session);self.assertTrue(self.session.active)
        finally:other.close()
    def test_old_window_cleanup_cannot_delete_new_window_paint_context(self):
        self.session.start('mesh',self.api.layer,mode='mask');self.session.stop()
        other=session_module.Session(self.api);other.start('mesh',self.api.layer,mode='mask');self.api.events=[]
        try:
            self.session.close();self.session.close()
            self.assertTrue(other.active);self.assertIs(sys.modules[session_module.BRIDGE].session,other)
            self.assertFalse(any(event[0]=='delete' for event in self.api.events))
        finally:other.close()
    def test_closed_session_cannot_restart(self):
        self.session.close()
        with self.assertRaisesRegex(ValueError,'closed'):self.session.start('mesh',self.api.layer,mode='mask')


class MembershipTests(unittest.TestCase):
    def setUp(self):self.api=FakeAPI();self.session=session_module.Session(self.api)
    def tearDown(self):self.session.close()
    def test_axis_assignment_orders_descendants_first_and_reuses_that_order_for_repeats(self):
        import layer_skin_assignment as geometry
        geometry.CACHE.clear()
        frame=lambda x:dict(position=[x,0.,0.],end=[x+1.,0.,0.],x=[1.,0.,0.],y=[0.,1.,0.],z=[0.,0.,1.])
        ref=dict(points=[[-1.,0.,0.],[1.,1000.,0.],[3.,0.,0.]],joints={'a':frame(0),'b':frame(2)},time=0)
        self.api.state=core.edit(self.api.state,'reference',dict(reference=ref))
        self.session.edit_joints('mesh',self.api.layer,['|a','|a|b'],'assign',dict(whole=True,settings=dict(method='axis')))
        self.assertEqual(self.api.calls[-1][1]['joints'],['b','a'])
        generated=self.api.state['layers'][0]['generated']
        self.assertEqual(generated['2']['weights'],[0.,1.]);self.assertEqual(generated['1']['weights'],[1.,0.]);self.assertEqual(generated['0']['weights'],[1.,0.])
        tests=geometry.CACHE.vertex_tests
        self.session.edit_joints('mesh',self.api.layer,['|a|b','|a'],'assign',dict(whole=True,settings=dict(method='axis')))
        self.assertEqual(self.api.calls[-1][1]['joints'],['b','a']);self.assertEqual(geometry.CACHE.vertex_tests,tests)
        geometry.CACHE.clear()
    def test_existing_joint_only_updates_membership(self):
        self.api.state['layers'][0]['joints']=[]
        self.session.add_joints('mesh',self.api.layer,['|b'])
        self.assertEqual(self.api.state['layers'][0]['joints'],['b'])
        self.assertFalse(any(event[0]=='add_influence' for event in self.api.events))
    def test_unbound_joint_is_added_at_zero_and_remapped_in_one_undo(self):
        before=self.api.snapshot();self.session.add_joints('mesh',self.api.layer,['|new'])
        self.assertEqual(self.api.ids,['a','b','new']);self.assertEqual(self.api.weights,[1,0,0]*3)
        self.assertEqual(self.api.state['base'],[1,0,0]*3)
        call=next(event for event in self.api.events if event[0]=='add_influence')
        self.assertEqual(call[1]['weight'],0.);self.assertNotIn('lockWeights',call[1])
        self.api.undo();self.assertEqual(self.api.snapshot(),before)
    def test_membership_failure_rolls_back_native_addition(self):
        before=self.api.snapshot();self.api.fail=True
        with self.assertRaisesRegex(RuntimeError,'Locked'):self.session.add_joints('mesh',self.api.layer,['|new'])
        self.assertEqual(self.api.snapshot(),before)
    def test_preflight_rejection_never_undoes_older_commands(self):
        before=self.api.snapshot()
        with self.assertRaises(ValueError):self.session.add_joints('mesh',self.api.layer,[])
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.undo_stack,[])
    def test_selected_assignment_adds_an_unbound_joint_and_weights_in_one_undo(self):
        before=self.api.snapshot()
        self.session.edit_joints('mesh',self.api.layer,['|new'],'assign',dict(whole=True,settings=dict(method='point',radius=10.)))
        self.assertEqual(self.api.ids,['a','b','new']);self.assertEqual(len(self.api.undo_stack),1)
        self.assertTrue(self.api.state['layers'][0]['generated'])
        self.assertEqual(self.api.calls[-1][1]['joints'],['new'])
        self.assertTrue(all(sample['weights']==[0.,0.,1.] for sample in self.api.state['layers'][0]['generated'].values()))
        self.api.undo();self.assertEqual(self.api.snapshot(),before)
    def test_assignment_failure_rolls_back_binding_and_preserves_existing_layers(self):
        before=self.api.snapshot()
        with self.assertRaisesRegex(ValueError,'Unknown assignment'):
            self.session.edit_joints('mesh',self.api.layer,['|new'],'assign',dict(whole=True,settings=dict(method='invalid')))
        self.assertEqual(self.api.snapshot(),before)
    def test_selected_assignment_without_selected_vertices_rolls_back_new_binding(self):
        before=self.api.snapshot()
        with self.assertRaisesRegex(ValueError,'Select mesh vertices'):
            self.session.edit_joints('mesh',self.api.layer,['|new'],'assign',dict(whole=False,settings=dict(radius=10.)))
        self.assertEqual(self.api.snapshot(),before)
    def test_flood_automatically_binds_the_selected_joint_as_one_undo(self):
        before=self.api.snapshot()
        self.session.edit_joints('mesh',self.api.layer,['|new'],'flood',dict(whole=True,value=.8,joint='new'))
        self.assertEqual(len(self.api.undo_stack),1);self.assertIn('new',self.api.state['layers'][0]['joints'])
        self.api.undo();self.assertEqual(self.api.snapshot(),before)


if __name__=='__main__':unittest.main(verbosity=2)
