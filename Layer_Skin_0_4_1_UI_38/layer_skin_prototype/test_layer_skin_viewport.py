"""Recording VP2 adapter: no DG edits, render API contracts and panel cleanup.

This does not emulate rasterization or verify a Maya GPU/driver combination.
"""
import copy
import sys
import types
import unittest
from unittest import mock
import layer_skin_viewport as viewport
import layer_skin_vp2 as vp2


class NativeColor(tuple):pass


class DisplayAPI:
    def __init__(self,count=3):
        self.count=count;self.sets={'artistColors':[(.1,.2,.3,1.)]*count};self.current='artistColors'
        self.flags=dict(displayColors=False,displayColorChannel='alpha',materialBlend=2)
        self.selection=['mesh.e[0:1]'];self.mode='edge';self.tool='selectSuperContext';self.weights=[1.,0.]*count
        self.dirty=False;self.alive=True;self.history=['skinCluster'];self.locked=None;self.fail=False
        self.panels={'view1':dict(rendererName='vp2Renderer',rendererOverrideName='',polymeshes=True)}
        self.registry={};self.callbacks={};self.serial=0;self.scheduled=[];self.logs=[];self.mesh_visible=True;self.isolated={};self.members={}
        self.positions=[(float(i),0.,0.) for i in range(count)];self.triangles=[v for i in range(1,count-1) for v in (0,i,i+1)]
        self.point_reads=0;self.triangle_reads=0;self.fail_panel=None;api=self
        class Dag:
            def node(self):return 'meshShape'
            def transform(self):return 'mesh'
            def fullPathName(self):return '|mesh|meshShape'
            def isVisible(self):return api.mesh_visible
        class Selection:
            def add(self,name):self.name=name
            def getDagPath(self,index):return Dag()
        class Mesh:
            def __init__(self,node):pass
            @property
            def numVertices(self):return api.count
            def getPoints(self,space):api.point_reads+=1;return list(api.positions)
            def getTriangles(self):api.triangle_reads+=1;return [1]*(len(api.triangles)//3),list(api.triangles)
            def createColorSet(self,*args):raise AssertionError('Color set creation is forbidden')
            def setVertexColors(self,*args):raise AssertionError('Mesh color writes are forbidden')
        def add(node,callback):api.serial+=1;api.callbacks[api.serial]=(node,callback);return api.serial
        def colors(values):
            if api.fail:raise RuntimeError('VP2 color upload failed')
            return list(values)
        self.om=types.SimpleNamespace(MSelectionList=Selection,MFnMesh=Mesh,MSpace=types.SimpleNamespace(kWorld=4),
            MObjectHandle=lambda node:types.SimpleNamespace(isValid=lambda:api.alive,isAlive=lambda:api.alive),
            MColor=NativeColor,MColorArray=colors,MUintArray=list,
            MNodeMessage=types.SimpleNamespace(addNodeDirtyCallback=add),
            MMessage=types.SimpleNamespace(removeCallback=lambda identity:api.callbacks.pop(identity)),
            MDGModifier=mock.Mock(side_effect=AssertionError('DG modifiers are forbidden')))
        class Clear:
            kClearAll=7
            def setMask(self,value):self.mask=value
            def setOverridesColors(self,value):self.overrides=value
        class Scene:
            kRenderAllItems=-1
            def __init__(self,name):self.name=name;self.mClearOperation=Clear()
        class Override:
            def __init__(self,name):self.name=name
        class Operation:
            def __init__(self,name):self.name=name
        class HUD:
            # Autodesk's HUD constructor has no operation-name argument.
            def __init__(self):self.name='MayaHUD'
        class Renderer:
            kAllDevices=7
            @staticmethod
            def registerOverride(value):api.registry[value.name]=value
            @staticmethod
            def deregisterOverride(value):api.registry.pop(value.name)
        self.r=types.SimpleNamespace(MSceneRender=Scene,MRenderOverride=Override,MHUDRender=HUD,MPresentTarget=Operation,
            MRenderer=Renderer,MClearOperation=Clear,MUIDrawManager=types.SimpleNamespace(kNonSelectable=0,kFlat=1,kTriangles=3),
            MRenderItem=types.SimpleNamespace(sDormantFilledDepthPriority=0))
        self.ui=types.SimpleNamespace(M3dView=types.SimpleNamespace(getM3dViewFromModelPanel=lambda panel:types.SimpleNamespace(scheduleRefresh=lambda:api.scheduled.append(panel))))
        self.cmds=types.SimpleNamespace(getPanel=lambda **kw:list(api.panels),modelEditor=self.model_editor,
            isolateSelect=self.isolate,sets=lambda group,**kw:api.members.get(group,[]),ls=lambda names,**kw:list(names))
        self.make_weight_renderer=lambda palette:vp2.WeightRenderer(self,palette,self.r,self.ui)
    def model_editor(self,panel,**kw):
        if kw.get('exists'):return panel in self.panels
        if kw.get('query'):
            return self.panels[panel][next(key for key in ('rendererName','rendererOverrideName','polymeshes') if kw.get(key))]
        assert kw.get('edit') and kw.get('noUndo')
        if self.fail_panel==panel:raise RuntimeError('Panel restore failed')
        self.panels[panel]['rendererOverrideName']=kw['rendererOverrideName'];self.logs.append(('panel',panel,kw['rendererOverrideName']))
    def isolate(self,panel,**kw):return self.isolated.get(panel) if kw.get('viewObjects') else bool(self.isolated.get(panel))
    def snapshot(self):return copy.deepcopy((self.sets,self.current,self.flags,self.selection,self.mode,self.tool,self.weights,self.history,self.dirty))
    def draw(self,view,panel='view1'):
        renderer=view.renderer;operation=renderer.override
        operation.setup(panel);scene=operation.operations[0];draws=[]
        manager=types.SimpleNamespace(beginDrawable=lambda value:draws.append(('begin',value)),
            setPaintStyle=lambda value:draws.append(('style',value)),setDepthPriority=lambda value:draws.append(('depth',value)),
            mesh=lambda mode,points,**kw:draws.append(('mesh',mode,list(points),kw)),endDrawable=lambda:draws.append(('end',)))
        scene.addPostUIDrawables(manager,None)
        return draws


class ViewportTests(unittest.TestCase):
    def test_bulk_draw_keeps_artist_colors_history_selection_scene_and_skin_unchanged(self):
        api=DisplayAPI();before=api.snapshot();view=viewport.WeightView(api);view.show('mesh',[0.,.5,1.])
        self.assertTrue(view.visible);self.assertEqual(api.snapshot(),before);api.om.MDGModifier.assert_not_called()
        draw=api.draw(view);mesh=next(row for row in draw if row[0]=='mesh')
        self.assertEqual(mesh[3]['color'],[viewport.color(v) for v in (0.,.5,1.)]);self.assertEqual(mesh[3]['index'],[0,1,2])
        self.assertIn(('begin',api.r.MUIDrawManager.kNonSelectable),draw);self.assertIn(('depth',1),draw)
        view.clear();self.assertEqual(api.snapshot(),before);self.assertEqual(api.registry,{});self.assertEqual(api.callbacks,{})
        self.assertEqual(api.panels['view1']['rendererOverrideName'],'')
    def test_artist_colors_and_modified_scene_are_retained_across_display_switch(self):
        api=DisplayAPI();api.dirty=True;before=api.snapshot();view=viewport.WeightView(api)
        view.show('mesh',[0.,.5,1.]);view.show('mesh',[1.,.25,0.],'grayscale')
        self.assertEqual(api.snapshot(),before);self.assertEqual(view.renderer.colors,[(1.,1.,1.,1.),(.25,.25,.25,1.),(0.,0.,0.,1.)])
        view.close();self.assertEqual(api.snapshot(),before)
    def test_unchanged_display_reveals_without_rebuilding_arrays_and_force_updates_colors(self):
        api=DisplayAPI();view=viewport.WeightView(api);view.show('mesh',[0.,0.,0.]);host=view.renderer;requests=len(api.scheduled)
        view.show('mesh',[0.,0.,0.]);self.assertEqual(host.color_updates,1);self.assertGreater(len(api.scheduled),requests)
        view.show('mesh',[0.,0.,0.],force=True);self.assertEqual(host.color_updates,2);self.assertEqual(host.geometry_updates,1)
        view.close()
    def test_failed_upload_clears_only_its_view_resources(self):
        api=DisplayAPI();before=api.snapshot();api.fail=True;view=viewport.WeightView(api)
        with self.assertRaisesRegex(RuntimeError,'VP2 color upload'):view.show('mesh',[0.,0.,0.])
        self.assertEqual(api.snapshot(),before);self.assertFalse(view.visible);self.assertEqual(api.registry,{})
        self.assertEqual(api.callbacks,{})
    def test_locked_artist_display_setting_does_not_block_the_node_free_view(self):
        api=DisplayAPI();api.locked='displayColors';before=api.snapshot();view=viewport.WeightView(api)
        view.show('mesh',[0.,0.,0.]);self.assertTrue(view.visible);self.assertEqual(api.snapshot(),before);view.close()
    def test_topology_mismatch_and_nonfinite_values_do_not_attach_a_renderer(self):
        api=DisplayAPI();before=api.snapshot();view=viewport.WeightView(api)
        with self.assertRaisesRegex(ValueError,'topology'):view.show('mesh',[0.,0.])
        with self.assertRaisesRegex(ValueError,'Non-finite'):view.show('mesh',[0.,float('nan'),0.])
        self.assertEqual(api.snapshot(),before);self.assertEqual(api.registry,{});self.assertEqual(api.callbacks,{})
    def test_large_view_reuses_geometry_and_bounded_native_palette_across_camera_frames(self):
        api=DisplayAPI(250000);view=viewport.WeightView(api);view.show('mesh',[.4]*api.count)
        self.assertEqual(len(view.renderer.native_palettes['heatmap']),4097)
        with mock.patch.object(view.renderer.fn,'getPoints',side_effect=AssertionError('Reread on camera/selection draw')):
            for _ in range(3):api.draw(view)
        self.assertEqual(view.renderer.geometry_updates,1);self.assertEqual(view.renderer.color_updates,1);view.close()
    def test_exit_and_deleted_mesh_do_not_write_dead_native_objects(self):
        api=DisplayAPI();view=viewport.WeightView(api);view.show('mesh',[0.,0.,0.]);api.alive=False
        self.assertFalse(view.visible);view.clear();self.assertEqual(api.registry,{})
        view.abandon();self.assertTrue(view.closed)
    def test_changed_colors_never_create_history_and_keep_one_renderer_registration(self):
        api=DisplayAPI();before=api.snapshot();view=viewport.WeightView(api);view.show('mesh',[0.,0.,0.]);host=view.renderer
        for i in range(30):
            view.show('mesh',[i/30.,.5,1.],'heatmap' if i%2 else 'grayscale')
            self.assertIs(view.renderer,host);self.assertEqual(len(api.registry),1);self.assertEqual(len(api.callbacks),2)
            self.assertEqual(api.snapshot(),before)
        self.assertEqual(host.geometry_updates,1);view.close();self.assertEqual(api.snapshot(),before)
    def test_versioned_unchanged_view_does_not_scan_values_and_rebinds_after_tool_setup(self):
        api=DisplayAPI();view=viewport.WeightView(api);view.show_versioned('mesh',[0.,.5,1.],'heatmap',4)
        class Unreadable:
            def __iter__(self):raise AssertionError('Unchanged view scanned')
        api.panels['view1']['rendererOverrideName']=''
        view.show_versioned('mesh',Unreadable(),'heatmap',4)
        self.assertEqual(api.panels['view1']['rendererOverrideName'],view.renderer.name)
        self.assertEqual(view.renderer.color_updates,1);view.close()
    def test_palette_matches_ramp_stops_clamps_and_preserves_scalar_inputs(self):
        palette=viewport.Palette();values=[-1.,0.,.25,.5,.75,1.,2.];before=values[:]
        colors=palette.map(values,'heatmap');self.assertEqual(values,before)
        for i,value in enumerate(values):self.assertEqual(colors[i],viewport.color(value))
        self.assertEqual(palette.map([.5],'grayscale'),[(.5,.5,.5,1.)])
    def test_dirty_geometry_follows_deformation_without_reading_skin_or_changing_colors(self):
        api=DisplayAPI();view=viewport.WeightView(api);view.show('mesh',[0.,.5,1.]);host=view.renderer
        api.positions[1]=(9.,8.,7.)
        for _,callback in list(api.callbacks.values()):callback()
        draw=api.draw(view);self.assertEqual(host.geometry_updates,2);self.assertEqual(host.color_updates,1)
        self.assertEqual(next(row for row in draw if row[0]=='mesh')[2][1],(9.,8.,7.));view.close()
    def test_hide_isolate_and_panel_polygon_filters_hide_the_overlay(self):
        api=DisplayAPI();view=viewport.WeightView(api);view.show('mesh',[0.,.5,1.])
        api.mesh_visible=False;self.assertEqual(api.draw(view),[]);api.mesh_visible=True
        api.panels['view1']['polymeshes']=False;self.assertEqual(api.draw(view),[]);api.panels['view1']['polymeshes']=True
        api.isolated['view1']='isolated';api.members['isolated']=['|other'];self.assertEqual(api.draw(view),[])
        api.members['isolated']=['|mesh'];self.assertTrue(api.draw(view));view.close()
    def test_other_custom_renderers_are_preserved_and_not_replaced_on_cleanup(self):
        api=DisplayAPI();api.panels['custom']=dict(rendererName='vp2Renderer',rendererOverrideName='ArtistRender',polymeshes=True)
        view=viewport.WeightView(api);view.show('mesh',[0.,.5,1.]);self.assertEqual(view.renderer.skipped,['custom'])
        api.panels['view1']['rendererOverrideName']='NewArtistRender';view.close()
        self.assertEqual(api.panels['custom']['rendererOverrideName'],'ArtistRender');self.assertEqual(api.panels['view1']['rendererOverrideName'],'NewArtistRender')
    def test_no_supported_panel_reports_a_clear_error_without_color_history_fallback(self):
        api=DisplayAPI();api.panels['view1']['rendererOverrideName']='ArtistRender';before=api.snapshot();view=viewport.WeightView(api)
        with self.assertRaisesRegex(RuntimeError,'custom renderer overrides were preserved'):view.show('mesh',[0.,.5,1.])
        self.assertEqual(api.snapshot(),before);self.assertEqual(api.registry,{});self.assertEqual(api.callbacks,{})
    def test_render_pass_preserves_default_selection_scene_hud_and_background(self):
        api=DisplayAPI();view=viewport.WeightView(api);view.show('mesh',[0.,.5,1.]);host=view.renderer;render=host.override
        self.assertFalse(render.select(None,None,None,None,None));self.assertEqual(render.supportedDrawAPIs(),api.r.MRenderer.kAllDevices)
        render.startOperationIterator();names=[]
        while True:
            names.append(render.renderOperation().name)
            if not render.nextRenderOperation():break
        self.assertEqual(names,['rtkLayerSkinScene','MayaHUD','rtkLayerSkinPresent'])
        self.assertIsInstance(render.operations[1],api.r.MHUDRender)
        self.assertTrue(host.report()['hud_enabled']);self.assertIsNone(host.report()['hud_constructor_error'])
        clear=render.operations[0].clearOperation();self.assertFalse(clear.overrides);self.assertEqual(clear.mask,7);view.close()
    def test_failed_panel_restore_keeps_registration_available_for_retry(self):
        api=DisplayAPI();view=viewport.WeightView(api);view.show('mesh',[0.,.5,1.]);api.fail_panel='view1'
        with self.assertRaisesRegex(RuntimeError,'Panel restore'):view.clear()
        self.assertEqual(len(api.registry),1);self.assertFalse(view.visible);api.fail_panel=None;view.clear();self.assertEqual(api.registry,{})
    def test_deleted_node_callback_ids_do_not_block_remaining_cleanup(self):
        api=DisplayAPI();view=viewport.WeightView(api);view.show('mesh',[0.,.5,1.]);ids=list(api.callbacks)
        def remove(identity):
            api.callbacks.pop(identity,None)
            if identity==ids[-1]:raise RuntimeError('Callback already removed with deleted node')
        api.om.MMessage.removeCallback=remove;view.close()
        self.assertEqual(api.callbacks,{});self.assertEqual(api.registry,{})

    def test_hud_constructor_failure_keeps_heat_map_and_scene_unchanged(self):
        api=DisplayAPI();before=api.snapshot()
        api.r.MHUDRender=mock.Mock(side_effect=TypeError('MHUDRender : no matching constructor found'))
        view=viewport.WeightView(api);view.show('mesh',[0.,.5,1.])
        self.assertTrue(view.visible);draw=api.draw(view)
        self.assertEqual(next(row for row in draw if row[0]=='mesh')[3]['color'],[viewport.color(v) for v in (0.,.5,1.)])
        self.assertEqual([operation.name for operation in view.renderer.override.operations],['rtkLayerSkinScene','rtkLayerSkinPresent'])
        report=view.report();self.assertEqual(report['renderer_revision'],35);self.assertFalse(report['hud_enabled'])
        self.assertIn('no matching constructor',report['hud_constructor_error']);self.assertEqual(report['last_draw_error'],'')
        view.show('mesh',[1.,.5,0.]);api.r.MHUDRender.assert_called_once_with()
        self.assertEqual(api.snapshot(),before);view.close()
        self.assertEqual(api.panels['view1']['rendererOverrideName'],'');self.assertEqual(api.registry,{});self.assertEqual(api.callbacks,{})

    def test_required_scene_and_present_constructor_failures_are_not_hidden(self):
        for operation in ('MSceneRender','MPresentTarget'):
            with self.subTest(operation=operation):
                api=DisplayAPI();before=api.snapshot()
                class BrokenScene(api.r.MSceneRender):
                    def __init__(self,name):raise TypeError('Required scene operation failed')
                if operation=='MSceneRender':api.r.MSceneRender=BrokenScene
                else:api.r.MPresentTarget=mock.Mock(side_effect=TypeError('Required present operation failed'))
                view=viewport.WeightView(api)
                with self.assertRaisesRegex(TypeError,'Required'):view.show('mesh',[0.,.5,1.])
                self.assertFalse(view.visible);self.assertEqual(api.snapshot(),before)
                self.assertEqual(api.registry,{});self.assertEqual(api.callbacks,{})

    def test_default_factories_ignore_both_pre_fix_cached_modules(self):
        import layer_skin_session as sessions
        api=DisplayAPI();del api.make_weight_renderer
        old_view=types.SimpleNamespace(WeightView=mock.Mock(side_effect=AssertionError('Old WeightView reused')))
        old_renderer=types.SimpleNamespace(WeightRenderer=mock.Mock(side_effect=AssertionError('Old VP2 renderer reused')))
        maya=types.ModuleType('maya');maya.__path__=[]
        package=types.ModuleType('maya.api');package.__path__=[];maya.api=package
        render=types.ModuleType('maya.api.OpenMayaRender');render.__dict__.update(vars(api.r))
        ui=types.ModuleType('maya.api.OpenMayaUI');ui.__dict__.update(vars(api.ui))
        package.OpenMayaRender=render;package.OpenMayaUI=ui
        with mock.patch.dict(sys.modules,{'maya':maya,'maya.api':package,'maya.api.OpenMayaRender':render,
                'maya.api.OpenMayaUI':ui,'_rtk_layer_skin_viewport_33':old_view,'_rtk_layer_skin_vp2_33':old_renderer}):
            sys.modules.pop('_rtk_layer_skin_viewport_35',None);sys.modules.pop('_rtk_layer_skin_vp2_35',None)
            view=sessions.make_weight_view(api)
            try:
                view.show('mesh',[0.,.5,1.]);self.assertTrue(view.visible);self.assertTrue(api.draw(view))
                self.assertEqual(type(view).__module__,'_rtk_layer_skin_viewport_35')
                self.assertEqual(type(view.renderer).__module__,'_rtk_layer_skin_vp2_35')
                self.assertEqual(view.report()['renderer_revision'],35)
                old_view.WeightView.assert_not_called();old_renderer.WeightRenderer.assert_not_called()
            finally:view.close()
        self.assertEqual(api.registry,{});self.assertEqual(api.callbacks,{})


if __name__=='__main__':unittest.main()
