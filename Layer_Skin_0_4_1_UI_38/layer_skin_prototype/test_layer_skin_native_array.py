"""Native-array contract/lifecycle with recording APIs, not a Maya viewport test."""
import copy
import sys
import types
import unittest

import layer_skin_core as core
import layer_skin_session as sessions
import layer_skin_artisan as artisan
from test_layer_skin_session import FakeAPI


class ArrayAPI(FakeAPI):
    """Model native array painting and nested Undo independently of scalar setters."""
    def snapshot(self):return super().snapshot(), self.paint_buffer.read()
    def restore(self, state):
        super().restore(state[0]);self.paint_buffer.write(state[1])
    def stamp(self, values):
        before=self.snapshot()
        array=self.paint_buffer.read()
        for index,value in values.items():array[index]=value
        self.paint_buffer.write(array)
        if self._chunk:self._chunk_mutated=True
        else:self.undo_stack.append(before)


class NativeArrayTests(unittest.TestCase):
    def setUp(self):
        self.api=ArrayAPI();self.session=sessions.Session(self.api)
    def tearDown(self):
        self.session.close();sys.modules.pop(sessions.BRIDGE,None)
    def start(self,joint='b',mode='weights',**kwargs):
        self.session.start('mesh',self.api.layer,joint=joint,joint_path='|'+joint,mode=mode,**kwargs)
    def stroke(self, values):
        self.session.before_stroke();self.api.stamp(values);self.session.after_stroke()
    def test_array_only_brush_saves_with_no_scalar_callbacks(self):
        self.start();before=self.api.snapshot()
        self.stroke({0:.65,2:.9})
        self.assertEqual(self.session.values,[.65,0.,.9])
        self.assertEqual(self.session.buffer.read(),[.65,0.,.9])
        self.assertEqual(self.session.paint_events.get('set_value',0),0)
        self.assertEqual(self.session.last_stroke['status'],'saved')
        self.assertTrue(self.session.last_stroke['layer_values_verified'])
        self.assertEqual(len(self.api.undo_stack),1)
        self.assertEqual(self.api._chunk_depth,0)
        self.api.undo();self.assertEqual(self.api.snapshot(),before)
    def test_original_joint_saved_array_returns_after_switching_away(self):
        self.start();self.stroke({0:.988858,1:.65667,2:.509804})
        authoring=copy.deepcopy(self.api.state);original=self.api.paint_buffer.read()
        self.start('a');self.assertEqual(self.api.paint_buffer.read(),[0.,0.,0.])
        self.start('b');self.assertEqual(self.api.paint_buffer.read(),original)
        self.assertEqual(self.api.state,authoring)
        self.assertEqual(len(self.api.undo_stack),1)
    def test_duplicate_before_events_do_not_reset_native_array_samples(self):
        self.start();self.session.before_stroke();self.api.stamp({1:.8})
        self.session.before_stroke()
        self.assertEqual(self.api.paint_buffer.read(),[0.,.8,0.])
        self.assertEqual(self.api._chunk_depth,1)
        self.session.after_stroke();self.session.after_stroke()
        self.assertEqual(self.session.values,[0.,.8,0.]);self.assertEqual(len(self.api.calls),1)
        self.assertEqual(self.api._chunk_depth,0)
    def test_array_is_saved_before_joint_switch_when_after_hook_is_missing(self):
        self.start();self.session.before_stroke();self.api.stamp({1:.72})
        self.start('a');self.start('b')
        self.assertEqual(self.session.buffer.read(),[0.,.72,0.])
        self.assertEqual(self.api._chunk_depth,0);self.assertEqual(len(self.api.undo_stack),1)
    def test_array_is_saved_before_mask_switch_and_restored_per_mode(self):
        self.start();self.stroke({0:.8})
        self.start(mode='mask');self.assertEqual(self.session.buffer.read(),[1.,1.,1.])
        self.stroke({0:.25})
        self.start(mode='weights');self.assertEqual(self.session.buffer.read(),[.8,0.,0.])
        self.start(mode='mask');self.assertEqual(self.session.buffer.read(),[.25,1.,1.])
    def test_readonly_view_has_zero_brush_opacity_and_restores_attempted_change(self):
        self.start(mode='mask',readonly=True);before=self.api.state
        self.assertEqual(self.api.context_settings['opacity'],0.)
        self.session.before_stroke();self.api.paint_buffer.write([0.,0.,0.]);self.session.after_stroke()
        self.assertEqual(self.session.buffer.read(),[1.,1.,1.])
        self.assertIs(self.api.state,before);self.assertEqual(self.api.calls,[])
        self.assertEqual(self.api._chunk_depth,0)
    def test_feedback_reentry_does_not_open_an_authoring_stroke(self):
        original=self.api.paint_buffer.write
        def reenter(values):
            if self.session._configuring_view:self.session.before_stroke();self.session.after_stroke()
            original(values)
        self.api.paint_buffer.write=reenter
        self.start();self.assertIsNone(self.session.stroke);self.assertEqual(self.api._chunk_depth,0)
        self.stroke({1:.9});self.assertEqual(self.session.values,[0.,.9,0.])
    def test_unbound_joint_and_native_array_paint_share_one_undo(self):
        self.start('new');before=self.api.snapshot()
        self.stroke({2:.6});after=self.api.snapshot()
        self.assertIn('new',self.api.ids);self.assertEqual(len(self.api.undo_stack),1)
        self.api.undo();self.assertEqual(self.api.snapshot(),before)
        self.api.redo();self.assertEqual(self.api.snapshot(),after)
    def test_failed_unbound_commit_rolls_back_binding_and_native_array(self):
        self.start('new');before=self.api.snapshot();self.api.fail=True
        self.session.before_stroke();self.api.stamp({2:.8})
        with self.assertRaisesRegex(RuntimeError,'Locked'):self.session.after_stroke()
        self.assertEqual(self.api.snapshot(),before)
        self.assertEqual(self.api._chunk_depth,0)
    def test_native_array_unchanged_stroke_does_not_write_layer(self):
        self.start();before=core.encode(self.api.state)
        self.session.before_stroke();self.session.after_stroke()
        self.assertEqual(core.encode(self.api.state),before);self.assertEqual(self.api.calls,[])
        self.assertEqual(self.api._chunk_depth,0)
    def test_invalid_vertex_count_rejects_and_resets_buffer_without_open_chunk(self):
        self.start();self.session.before_stroke();self.api.paint_buffer.write([.8])
        with self.assertRaisesRegex(ValueError,'vertex count'):self.session.after_stroke()
        self.assertEqual(self.session.last_stroke['status'],'rejected')
        self.assertEqual(self.session.buffer.read(),[0.,0.,0.]);self.assertEqual(self.api._chunk_depth,0)
    def test_nonfinite_native_weight_is_rejected_and_array_restored(self):
        self.start();self.session.before_stroke();self.api.paint_buffer.write([float('nan'),0.,0.])
        with self.assertRaisesRegex(ValueError,'non-finite'):self.session.after_stroke()
        self.assertEqual(self.session.buffer.read(),[0.,0.,0.]);self.assertEqual(self.api.calls,[])
        self.assertEqual(self.api._chunk_depth,0)
    def test_buffer_creation_error_records_failure_and_leaves_no_active_view(self):
        self.api.make_paint_buffer=lambda mesh:(_ for _ in ()).throw(RuntimeError('buffer setup failed'))
        with self.assertRaisesRegex(RuntimeError,'buffer setup'):self.start()
        self.assertFalse(self.session.active);self.assertFalse(self.session._view_ready)
        self.assertIsNone(self.session.buffer);self.assertIn('buffer setup',self.session.last_error)
    def test_tool_exit_preserves_array_samples_for_release_fallback(self):
        self.start();self.session.before_stroke();self.api.stamp({1:.77})
        self.session.tool_cleanup();self.assertFalse(self.session.active)
        self.session.flush_pending('mouse_release_fallback')
        self.assertEqual(self.session.values,[0.,.77,0.]);self.assertEqual(self.api._chunk_depth,0)
    def test_pending_old_session_cannot_read_or_overwrite_new_session_array(self):
        self.start();self.session.before_stroke();self.api.stamp({1:.7})
        self.session.tool_cleanup()
        other=sessions.Session(self.api)
        try:
            other.start('mesh',self.api.layer,joint='a',mode='weights')
            self.session.flush_pending('late_release')
            self.assertEqual(other.buffer.read(),[0.,0.,0.])
            self.assertEqual(self.api.state['layers'][0]['samples']['1']['coverage'],.7)
        finally:other.close()
    def test_returning_array_vertex_to_baseline_removes_previous_capture(self):
        self.start();self.session.before_stroke();self.api.stamp({1:.7})
        self.session._capture_array();self.api.stamp({1:0.})
        self.session.after_stroke()
        self.assertEqual(self.session.last_stroke['status'],'unchanged');self.assertEqual(self.api.calls,[])
    def test_stop_releases_owner_but_keeps_array_alive_for_native_undo(self):
        self.start();self.stroke({0:.8});buffer=self.session.buffer
        self.session.stop();self.assertIsNone(buffer.owner)
        self.assertEqual(buffer.read(),[.8,0.,0.]);self.api.undo()
        self.start();self.assertEqual(self.session.buffer.read(),[0.,0.,0.])


class BufferAdapterTests(unittest.TestCase):
    def setUp(self):
        artisan._buffers={};self.nodes=[];nodes=self.nodes
        class Plug:
            def __init__(self,node,name):self.node=node;self.key=name;self.incoming=[]
            def name(self):return self.node.name+'.'+self.key
            def setMObject(self,value):self.node.values=list(value)
            def asMObject(self):return self.node.values
            def connectedTo(self,as_destination,as_source):return self.incoming[:]
        class Modifier:
            def __init__(self):self.node=None;self.ops=[];self.previous=[]
            def createNode(self,kind):
                self.node=types.SimpleNamespace(kind=kind,alive=False,name='',attributes={},values=[],plugs={})
                return self.node
            def connect(self,source,destination):self.ops.append(('connect',source,destination))
            def disconnect(self,source,destination):self.ops.append(('disconnect',source,destination))
            def doIt(self):
                if self.node is not None:self.node.alive=True;nodes.append(self.node)
                for op,source,destination in self.ops:
                    self.previous.append((destination,destination.incoming[:]))
                    if op=='connect':destination.incoming.append(source)
                    else:destination.incoming.remove(source)
            def undoIt(self):
                if self.node is not None:self.node.alive=False
                for destination,previous in reversed(self.previous):destination.incoming=previous
        class NodeFn:
            def __init__(self,node):self.node=node
            def setName(self,name):self.node.name=name.lstrip(':')+str(len(nodes))
            def setDoNotWrite(self,value):self.node.do_not_write=value
            def addAttribute(self,attribute):self.node.attributes[attribute.long_name]=attribute
            def uuid(self):return types.SimpleNamespace(asString=lambda:self.node.identity)
            def findPlug(self,name,want_networked):
                node=self.node
                if name not in node.plugs:node.plugs[name]=Plug(node,name)
                return node.plugs[name]
        class Typed:
            def create(self,long_name,short_name,kind):self.long_name=long_name;self.kind=kind;return self
        class Generic:
            def create(self,long_name,short_name):self.long_name=long_name;self.accepts=[];return self
            def addDataType(self,kind):self.accepts.append(kind)
        class Data:
            def __init__(self,values=None):self.values=values
            def create(self,values):return list(values)
            def array(self):return self.values
        om=types.SimpleNamespace(MDGModifier=Modifier,MFnDependencyNode=NodeFn,MFnTypedAttribute=Typed,MFnGenericAttribute=Generic,
            MFnData=types.SimpleNamespace(kDoubleArray='doubleArray',kMesh='mesh'),MDoubleArray=list,MFnDoubleArrayData=Data,
            MObjectHandle=lambda node:types.SimpleNamespace(isValid=lambda:node.alive,isAlive=lambda:node.alive))
        self.meshes={name:types.SimpleNamespace(name=name,identity=name+'-id',plugs={}) for name in ('meshA','meshB')}
        self.api=types.SimpleNamespace(om=om,obj=lambda name:self.meshes[name])
    def tearDown(self):artisan._buffers={}
    def test_reuse_keeps_one_nonserialized_object_bound_to_the_mesh(self):
        buffer=artisan.get_buffer(self.api,'meshA');buffer.write([0.,.5,1.])
        again=artisan.get_buffer(self.api,'meshA')
        self.assertIs(again,buffer);self.assertEqual(len(self.nodes),1)
        self.assertEqual(buffer.read(),[0.,.5,1.])
        node=self.nodes[0];self.assertEqual(node.kind,'network');self.assertTrue(node.do_not_write)
        attribute=node.attributes['values'];self.assertFalse(attribute.storable)
        self.assertFalse(attribute.keyable);self.assertTrue(attribute.hidden)
        self.assertEqual(buffer.geometry_sources(),['meshA.outMesh'])
        self.assertEqual(node.attributes['surface'].accepts,['mesh'])
        self.assertFalse(node.attributes['surface'].cached)
    def test_new_scene_invalidates_handle_and_gets_new_empty_buffer(self):
        old=artisan.get_buffer(self.api,'meshA');old.write([.8]);self.nodes[0].alive=False
        with self.assertRaisesRegex(RuntimeError,'removed'):old.read()
        new=artisan.get_buffer(self.api,'meshA');self.assertIsNot(new,old);self.assertEqual(new.read(),[])
    def test_initialization_failure_removes_only_the_node_it_created(self):
        self.api.om.MFnTypedAttribute=lambda:(_ for _ in ()).throw(RuntimeError('typed attribute failed'))
        with self.assertRaisesRegex(RuntimeError,'typed attribute'):artisan.get_buffer(self.api,'meshA')
        self.assertEqual(artisan._buffers,{});self.assertEqual(sum(node.alive for node in self.nodes),0)
    def test_native_plug_name_tracks_renaming_instead_of_using_cached_name(self):
        buffer=artisan.get_buffer(self.api,'meshA');self.nodes[0].name='renamedBuffer'
        self.assertEqual(buffer.attribute(),'renamedBuffer.values')
    def test_two_meshes_keep_separate_native_arrays_and_geometry_links(self):
        a=artisan.get_buffer(self.api,'meshA');a.write([.7]*3)
        b=artisan.get_buffer(self.api,'meshB');b.write([.2]*8)
        self.assertIsNot(a,b);self.assertEqual(a.read(),[.7]*3);self.assertEqual(b.read(),[.2]*8)
        self.assertEqual(a.geometry_sources(),['meshA.outMesh']);self.assertEqual(b.geometry_sources(),['meshB.outMesh'])
    def test_same_mesh_rename_reuses_uuid_buffer_and_repairs_removed_link(self):
        buffer=artisan.get_buffer(self.api,'meshA');buffer.surface.incoming=[]
        mesh=self.meshes.pop('meshA');mesh.name='renamedMesh';self.meshes['renamedMesh']=mesh
        again=artisan.get_buffer(self.api,'renamedMesh')
        self.assertIs(again,buffer);self.assertEqual(again.geometry_sources(),['renamedMesh.outMesh'])


if __name__=='__main__':unittest.main()
