"""Cleanup ownership/transaction contracts with recorded Maya commands, no DG emulator."""
import copy
import sys
import types
import unittest
from unittest import mock
import layer_skin_cleanup as cleanup


class Node:
    def __init__(self,name,kind,attrs=None):
        self.name=name;self.kind=kind;self.uuid=name+'-uuid';self.attrs=dict(attrs or {})
        self.valid=True;self.alive=True;self.locked=False;self.referenced=False;self.locks=set()


class Handle:
    def __init__(self,node):self.node=node
    def isValid(self):return self.node.valid
    def isAlive(self):return self.node.alive


class RecordingAPI:
    def __init__(self):
        self.nodes={};self.links=[];self.history={};self.log=[];self.undo_stack=[];self.redo_stack=[]
        self.enabled=True;self.chunk=None;self.fail_after=None;self.skip_delete=False;self.skin_weights=(.2,.8,.6,.4)
        self.add('mesh','transform');self.add('meshShape','mesh');self.add('skin','skinCluster')
        self.history['meshShape']=['skin'];self.add_data('data')
        self.cmds=types.SimpleNamespace(ls=self.ls,nodeType=lambda n:self.obj(n).kind,
            listRelatives=lambda n,**kw:['meshShape'] if n=='mesh' else [],listHistory=lambda n,**kw:self.history.get(n,[]),
            listConnections=self.connections,attributeQuery=lambda a,node,**kw:a in self.obj(node).attrs,
            getAttr=self.get_attr,listAttr=lambda n,**kw:list(self.obj(n).attrs),
            referenceQuery=lambda n,**kw:self.obj(n).referenced,lockNode=lambda n,**kw:[self.obj(n).locked],
            undoInfo=self.undo_info,delete=self.delete,undo=self.undo,redo=self.redo)
        self.om=types.SimpleNamespace(MObjectHandle=Handle,MFnDependencyNode=lambda n:types.SimpleNamespace(uuid=lambda:types.SimpleNamespace(asString=lambda:n.uuid)))
    def add(self,name,kind,attrs=None):self.nodes[name]=Node(name,kind,attrs);return self.nodes[name]
    def add_data(self,name,shape='meshShape',skin='skin'):
        result=self.add(name,'network',{cleanup.STATE:'string','mesh':'message','skin':'message'})
        self.links.append((shape+'.message',name+'.mesh'))
        if skin:self.links.append((skin+'.message',name+'.skin'))
        return result
    def obj(self,name):
        node=self.nodes[name]
        if not node.valid:raise RuntimeError('Missing node: '+name)
        return node
    def ls(self,names,**kw):
        self.log.append(('ls',names,dict(kw)))
        if isinstance(names,str):names=[names.split('.',1)[0]]
        return [n for n in names if n in self.nodes and self.nodes[n].valid and (not kw.get('type') or self.nodes[n].kind==kw['type'])]
    def get_attr(self,plug,**kw):
        node,attr=plug.split('.',1);obj=self.obj(node)
        if kw.get('type'):return obj.attrs[attr]
        if kw.get('lock'):return attr in obj.locks
        raise AssertionError('Cleanup must not decode payloads or read weights.')
    def connections(self,name,**kw):
        result=[]
        for src,dst in self.links:
            for own,other,flag in ((dst,src,'source'),(src,dst,'destination')):
                if not kw.get(flag,True) or (own!=name if '.' in name else own.split('.',1)[0]!=name):continue
                if kw.get('type') and self.obj(other.split('.',1)[0]).kind!=kw['type']:continue
                if kw.get('connections'):result += [own,other]
                else:result.append(other if kw.get('plugs') else other.split('.',1)[0])
        return result
    def snapshot(self):
        return ({name:node.valid for name,node in self.nodes.items()},copy.deepcopy(self.links),self.skin_weights)
    def restore(self,snapshot):
        valid,links,weights=snapshot
        for name,node in self.nodes.items():node.valid=valid.get(name,False)
        self.links=copy.deepcopy(links);self.skin_weights=weights
    def undo_info(self,**kw):
        if kw.get('query'):
            if kw.get('state'):return self.enabled
            if kw.get('undoName'):return self.undo_stack[-1][1] if self.undo_stack else 'Older unrelated edit'
        elif kw.get('openChunk'):
            self.chunk=(self.snapshot(),kw['chunkName'])
        elif kw.get('closeChunk'):
            before,name=self.chunk;self.chunk=None
            if before!=self.snapshot():self.undo_stack.append((before,name));self.redo_stack=[]
    def delete(self,names):
        self.log.append(('delete',list(names)))
        for i,name in enumerate(names):
            if self.fail_after==i:raise RuntimeError('Recording delete failure')
            if self.skip_delete:continue
            self.obj(name).valid=False
            self.links=[(a,b) for a,b in self.links if name not in (a.split('.',1)[0],b.split('.',1)[0])]
    def undo(self):
        before,name=self.undo_stack.pop();self.redo_stack.append((self.snapshot(),name));self.restore(before)
    def redo(self):
        after,name=self.redo_stack.pop();self.undo_stack.append((self.snapshot(),name));self.restore(after)
    def clear_cache(self):self.log.append(('clear_cache',))
    def context(self,*a):raise AssertionError('Cleanup must not use heavy skin context.')
    def metadata(self,*a):raise AssertionError('Cleanup must not decode metadata.')


class CleanupTests(unittest.TestCase):
    def setUp(self):self.api=RecordingAPI()
    def inspect(self):return cleanup.inspect(self.api,'mesh')
    def test_inspection_is_readonly_and_does_not_decode_or_read_weights(self):
        before=self.api.snapshot();plan=self.inspect()
        self.assertEqual(plan['mesh'],'meshShape');self.assertEqual([r['node'] for r in plan['nodes']],['data'])
        self.assertEqual(plan['nodes'][0]['blocked'],[]);self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.undo_stack,[])
    def test_remove_uses_native_delete_only_and_undo_redo_restores_exact_data_links(self):
        before=self.api.snapshot();result=cleanup.remove(self.api,self.inspect())
        self.assertEqual(result['removed'],['data']);self.assertFalse(self.api.nodes['data'].valid)
        self.assertEqual(self.api.skin_weights,before[2]);self.assertTrue(self.api.nodes['skin'].valid);self.assertTrue(self.api.nodes['meshShape'].valid)
        self.assertEqual(len(self.api.undo_stack),1);self.api.undo();self.assertEqual(self.api.snapshot(),before)
        self.api.redo();self.assertFalse(self.api.nodes['data'].valid);self.assertEqual(self.api.skin_weights,before[2])
    def test_multiple_owned_nodes_are_deleted_together_in_one_undo(self):
        self.api.add_data('duplicate');plan=self.inspect();before=self.api.snapshot()
        self.assertEqual(len(plan['nodes']),2);cleanup.remove(self.api,plan)
        self.assertEqual(len(self.api.undo_stack),1);self.api.undo();self.assertEqual(self.api.snapshot(),before)
    def test_no_payload_read_allows_corrupt_duplicate_and_unskinned_mesh_recovery(self):
        self.api.add_data('duplicate');self.api.history['meshShape']=[]
        self.api.links=[(a,b) for a,b in self.api.links if not b.endswith('.skin')]
        plan=self.inspect();self.assertTrue(all(not r['blocked'] for r in plan['nodes']))
        cleanup.remove(self.api,plan);self.assertFalse(self.api.nodes['data'].valid)
        self.assertFalse(any(not row[1] for row in self.api.log if row[0]=='ls'))
    def test_foreign_mesh_even_with_shared_skin_is_retained(self):
        self.api.add('otherShape','mesh');self.api.history['otherShape']=['skin'];self.api.add_data('otherData','otherShape')
        cleanup.remove(self.api,self.inspect());self.assertTrue(self.api.nodes['otherData'].valid)
    def test_artist_network_and_native_paint_buffer_are_not_candidates(self):
        self.api.add('artist','network',{'mesh':'message'});self.api.add('paintBuffer','network',{'values':'doubleArray','surface':'mesh'})
        self.api.links += [('meshShape.message','artist.mesh'),('meshShape.outMesh','paintBuffer.surface')]
        cleanup.remove(self.api,self.inspect())
        self.assertTrue(self.api.nodes['artist'].valid);self.assertTrue(self.api.nodes['paintBuffer'].valid)
    def test_missing_mesh_owner_is_reported_and_never_deleted(self):
        self.api.links=[(a,b) for a,b in self.api.links if b!='data.mesh'];plan=self.inspect()
        self.assertEqual(plan['nodes'],[]);self.assertEqual(len(plan['skipped']),1)
        cleanup.remove(self.api,plan);self.assertTrue(self.api.nodes['data'].valid);self.assertEqual(self.api.undo_stack,[])
    def test_locked_referenced_customized_and_foreign_connected_nodes_block_all_removal(self):
        for kind in ('node_lock','attribute_lock','referenced','extra_attr','extra_connection','skin_mismatch'):
            with self.subTest(kind=kind):
                self.api=RecordingAPI();node=self.api.nodes['data'];self.api.add_data('duplicate')
                if kind=='node_lock':node.locked=True
                elif kind=='attribute_lock':node.locks.add(cleanup.STATE)
                elif kind=='referenced':node.referenced=True
                elif kind=='extra_attr':node.attrs['artistNotes']='string'
                elif kind=='extra_connection':
                    self.api.add('artist','network');self.api.links.append(('data.message','artist.message'))
                else:
                    self.api.add('otherSkin','skinCluster');self.api.links=[('otherSkin.message' if b=='data.skin' else a,b) for a,b in self.api.links]
                before=self.api.snapshot();plan=self.inspect()
                self.assertTrue(plan['nodes'][0]['blocked'])
                with self.assertRaisesRegex(ValueError,'Cleanup stopped'):cleanup.remove(self.api,plan)
                self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.undo_stack,[])
    def test_stale_plan_rejects_new_node_or_different_current_mesh(self):
        plan=self.inspect();self.api.add_data('added_later')
        with self.assertRaisesRegex(ValueError,'changed'):cleanup.remove(self.api,plan)
        self.api.add('otherShape','mesh')
        with self.assertRaisesRegex(ValueError,'changed'):cleanup.validate(self.api,plan,'otherShape')
        self.assertTrue(self.api.nodes['data'].valid)
    def test_dead_handles_reject_scene_reload_even_if_names_and_uuids_are_reused(self):
        plan=self.inspect();old=self.api.nodes['meshShape'];old.valid=False;old.alive=False
        self.api.add('meshShape','mesh')
        with self.assertRaisesRegex(ValueError,'scene or data nodes changed'):cleanup.remove(self.api,plan)
        self.assertTrue(self.api.nodes['data'].valid)
    def test_lock_added_after_preview_is_checked_again_before_delete(self):
        plan=self.inspect();self.api.nodes['data'].locked=True
        with self.assertRaisesRegex(ValueError,'locked'):cleanup.remove(self.api,plan)
        self.assertEqual(self.api.undo_stack,[])
    def test_disabled_undo_rejects_without_mutation(self):
        self.api.enabled=False;before=self.api.snapshot()
        with self.assertRaisesRegex(ValueError,'Enable Maya Undo'):cleanup.remove(self.api,self.inspect())
        self.assertEqual(self.api.snapshot(),before)
    def test_partial_delete_failure_rolls_back_owned_chunk_without_touching_older_edit(self):
        self.api.add_data('duplicate');before=self.api.snapshot();self.api.fail_after=1
        with self.assertRaisesRegex(RuntimeError,'delete failure'):cleanup.remove(self.api,self.inspect())
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.undo_stack,[]);self.assertIsNone(self.api.chunk)
    def test_failure_before_delete_never_undoes_an_unrelated_previous_edit(self):
        before=self.api.snapshot();self.api.fail_after=0
        self.api.undo_stack.append((before,'Unrelated previous edit'))
        with self.assertRaisesRegex(RuntimeError,'delete failure'):cleanup.remove(self.api,self.inspect())
        self.assertEqual(len(self.api.undo_stack),1);self.assertEqual(self.api.snapshot(),before)
    def test_incomplete_native_delete_is_detected(self):
        self.api.skip_delete=True
        with self.assertRaisesRegex(RuntimeError,'every requested'):cleanup.remove(self.api,self.inspect())
        self.assertTrue(self.api.nodes['data'].valid)
    def test_memory_cache_failure_after_delete_is_reported_without_claiming_delete_failed(self):
        self.api.clear_cache=lambda:(_ for _ in ()).throw(RuntimeError('cache failure'))
        result=cleanup.remove(self.api,self.inspect())
        self.assertEqual(result['removed'],['data']);self.assertIn('cache failure',result['cache_warning'])
        self.assertEqual(len(self.api.undo_stack),1)
    def test_memory_cleanup_clears_old_owner_and_shared_topology_without_deleting_live_buffers(self):
        live=types.SimpleNamespace(valid=lambda:True);dead=types.SimpleNamespace(valid=lambda:False)
        topology=types.SimpleNamespace(CACHE=mock.Mock());geometry=types.SimpleNamespace(CACHE=mock.Mock())
        buffers=types.SimpleNamespace(_buffers={'valid':live,'expired':dead})
        owner={'_decoded':{'state':1},'_composed':{'weights':1},'_modules':{'layer_skin_assignment':geometry}}
        self.api._layer_skin_command_owner=owner
        with mock.patch.dict(sys.modules,{'_rtk_layer_skin_relax_041':topology,'_rtk_layer_skin_artisan_041':buffers}):
            result=cleanup.clear_caches(self.api)
        self.assertEqual(owner['_decoded'],{});self.assertEqual(owner['_composed'],{})
        topology.CACHE.clear.assert_called_once();geometry.CACHE.clear.assert_called_once()
        self.assertEqual(buffers._buffers,{'valid':live});self.assertEqual(result['invalid_buffer_references'],1)
        self.assertEqual(self.api.undo_stack,[]);self.assertTrue(self.api.nodes['data'].valid)
    def test_cleanup_rejects_ambiguous_and_non_mesh_selection(self):
        with self.assertRaisesRegex(ValueError,'polygon mesh'):cleanup.inspect(self.api,'skin')
        with self.assertRaises(ValueError):cleanup.inspect(self.api,'')
