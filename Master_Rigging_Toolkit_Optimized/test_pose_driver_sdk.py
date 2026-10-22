"""SDK transactions and curve contracts with a recorded native-command adapter."""
import ast
import copy
import json
import math
from pathlib import Path
import types
import unittest


class SDKCommands:
    def __init__(self):
        self.nodes={};self.edges={};self.serial=0;self.calls=[];self.selection=[]
        self.enabled=True;self.open=None;self.history=[];self.future=[];self.unit={'angle':'deg','linear':'cm'}
        self.fail_on=None;self.blocked=set()
    def add(self,name,kind='transform'):
        while name in self.nodes:name+='1'
        self.serial+=1;attrs={};types_={}
        if kind in ('transform','joint'):
            for base in ('translate','rotate','scale'):
                attrs[base]=0
                for a in 'XYZ':attrs[base+a]=1. if base=='scale' else 0.;types_[base+a]='doubleAngle' if base=='rotate' else 'doubleLinear' if base=='translate' else 'double'
        self.nodes[name]={'uuid':'u'+str(self.serial),'type':kind,'attrs':attrs,'types':types_,'locked':set(),'ref':False}
        if kind.startswith('animCurve'):
            attrs.update(input=0.,preInfinity=0,postInfinity=0,weightedTangents=False)
            self.nodes[name]['keys']=[];self.nodes[name]['tangents']={}
        return name
    def weight(self,name):
        n=self.add(name,'network');self.nodes[n]['attrs'].update(Weight=0.,WeightRaw=0.);self.nodes[n]['types'].update(Weight='double',WeightRaw='double');return n
    def ls(self,value=None,**kw):
        if kw.get('selection'):return self.selection[:]
        if value is None:found=list(self.nodes)
        else:found=[n for n,d in self.nodes.items() if value in (n,d['uuid'])]
        if kw.get('type'):found=[n for n in found if self.nodes[n]['type']==kw['type']]
        return [self.nodes[n]['uuid'] for n in found] if kw.get('uuid') else found
    def connectionInfo(self,p,**kw):return p in self.edges
    def nodeType(self,n):return self.nodes[n]['type']
    def objExists(self,value):
        if '.' not in value:return value in self.nodes
        n,a=value.split('.',1);return n in self.nodes and (a in self.nodes[n]['attrs'] or a=='output' and self.nodes[n]['type'].startswith('animCurve'))
    def objectType(self,n,**kw):return self.nodes[n]['type'] in ('transform','joint')
    def referenceQuery(self,n,**kw):return self.nodes[n]['ref']
    def lockNode(self,n,**kw):return [False]
    def attributeName(self,p,**kw):return p.split('.',1)[1]
    def attributeQuery(self,a,node,**kw):return a in self.nodes[node]['attrs']
    def currentUnit(self,**kw):return self.unit['linear'] if kw.get('linear') else self.unit['angle']
    def listConnections(self,p,**kw):
        if kw.get('source'):return [src for dst,src in self.edges.items() if dst==p]
        return [dst for dst,src in self.edges.items() if src==p]
    def getAttr(self,p,**kw):
        n,a=p.split('.',1)
        if kw.get('lock'):return a in self.nodes[n]['locked']
        if kw.get('type'):return self.nodes[n]['types'].get(a,'double')
        if p in self.edges:return self.getAttr(self.edges[p])
        if a=='output' and self.nodes[n]['type'].startswith('animCurve'):return self.eval(n,self.getAttr(n+'.input'))
        return self.nodes[n]['attrs'].get(a,0.)
    def setAttr(self,p,*values,**kw):
        if self.fail_on==p:raise RuntimeError('Injected write failure')
        n,a=p.split('.',1)
        if 'lock' in kw:
            self.nodes[n]['locked'].add(a) if kw['lock'] else self.nodes[n]['locked'].discard(a)
        if values:self.nodes[n]['attrs'][a]=values[0] if len(values)==1 else values
    def addAttr(self,n,**kw):
        self.nodes[n]['attrs'][kw['longName']]='' if kw.get('dataType')=='string' else 0.
    def createNode(self,kind,name,**kw):return self.add(name.lstrip(':').replace('#',str(self.serial+1)),kind)
    def connectAttr(self,src,dst,**kw):
        if self.fail_on==dst:raise RuntimeError('Injected connect failure')
        if dst in self.edges:raise RuntimeError('Destination already connected')
        self.edges[dst]=src;self.calls.append(('connect',src,dst))
    def delete(self,value):
        if isinstance(value,(tuple,list)):
            for n in value:self.delete(n)
            return
        del self.nodes[value];self.edges={d:s for d,s in self.edges.items() if d.split('.',1)[0]!=value and s.split('.',1)[0]!=value}
    def keyframe(self,curve,**kw):
        data=self.nodes[curve]
        if kw.get('query') and kw.get('keyframeCount'):return len(data['keys'])
        if kw.get('query') and kw.get('valueChange'):return [v for x,v in data['keys']]
        if kw.get('query') and kw.get('floatChange'):return [x for x,v in data['keys']]
        if kw.get('edit'):
            lo,hi=kw.get('index',(0,len(data['keys'])-1));amount=kw['valueChange']
            data['keys']=[(x,v+amount if lo<=i<=hi else v) for i,(x,v) in enumerate(data['keys'])]
    def setDrivenKeyframe(self,dst,**kw):
        if self.fail_on==dst:raise RuntimeError('Injected SDK failure')
        self.calls.append(('sdk',dst,kw.copy()));sources=self.listConnections(dst,source=True)
        if sources:curve=sources[0].split('.',1)[0]
        else:
            kind={'doubleAngle':'animCurveUA','doubleLinear':'animCurveUL','double':'animCurveUU'}[self.getAttr(dst,type=True)]
            curve=self.add('sdk'+str(self.serial+1),kind)
            self.connectAttr(kw['currentDriver'],curve+'.input');self.connectAttr(curve+'.output',dst)
        x,y=kw['driverValue'],kw['value'];data=self.nodes[curve]
        data['keys']=sorted([(a,b) for a,b in data['keys'] if a!=x]+[(x,y)])
        data['tangents'][x]={'in':kw['inTangentType'],'out':kw['outTangentType']}
        return 1
    def duplicate(self,curve,**kw):
        self.calls.append(('duplicate',curve,kw.copy()));new=self.add(kw['name'].lstrip(':').replace('#',str(self.serial+1)),self.nodes[curve]['type'])
        uid=self.nodes[new]['uuid'];self.nodes[new]=copy.deepcopy(self.nodes[curve]);self.nodes[new]['uuid']=uid;return [new]
    def scaleKey(self,curve,**kw):
        self.calls.append(('scaleKey',curve,kw.copy()));data=self.nodes[curve];keys=[]
        for x,y in data['keys']:
            if 'valueScale' in kw:y=kw['valuePivot']+kw['valueScale']*(y-kw['valuePivot'])
            if 'floatScale' in kw:x=kw['floatPivot']+kw['floatScale']*(x-kw['floatPivot'])
            keys.append((x,y))
        data['keys']=sorted(keys)
    def eval(self,curve,x):
        keys=self.nodes[curve]['keys']
        if not keys:return 0.
        if x<=keys[0][0]:return keys[0][1]
        if x>=keys[-1][0]:return keys[-1][1]
        for (a,u),(b,v) in zip(keys,keys[1:]):
            if a<=x<=b:return u+(v-u)*(x-a)/(b-a)
    def snap(self):return copy.deepcopy((self.nodes,self.edges,self.selection))
    def undoInfo(self,**kw):
        if kw.get('query'):return self.history[-1][0] if kw.get('undoName') and self.history else self.enabled
        if kw.get('openChunk'):self.open=(kw['chunkName'],self.snap())
        if kw.get('closeChunk'):
            self.history.append((self.open[0],self.open[1],self.snap()));self.open=None;self.future=[]
    def undo(self):
        name,before,after=self.history.pop();self.nodes,self.edges,self.selection=copy.deepcopy(before);self.future.append((name,before,after))
    def redo(self):
        name,before,after=self.future.pop();self.nodes,self.edges,self.selection=copy.deepcopy(after);self.history.append((name,before,after))
    def rename(self,old,new):
        self.nodes[new]=self.nodes.pop(old)
        def change(p):n,a=p.split('.',1);return (new if n==old else n)+'.'+a
        self.edges={change(d):change(s) for d,s in self.edges.items()};return new
    def select(self,nodes,**kw):self.selection=list(nodes) if isinstance(nodes,list) else [nodes]


def load_backend(cmds):
    path=Path(__file__).with_name('pose_driver_sdk.py');tree=ast.parse(path.read_text())
    tree.body=[n for n in tree.body if not isinstance(n,ast.Import) or not any(a.name=='maya.cmds' for a in n.names)]
    module=types.ModuleType('sdk_recorded');module.cmds=cmds;exec(compile(tree,str(path),'exec'),module.__dict__)
    def cycle(weight,target):
        cmds.calls.append(('cycle_check',weight,target))
        if target in cmds.blocked:raise ValueError('dependency cycle')
    module._native_cycle_check=module._cycle_check;module._cycle_check=cycle
    return module


class SDKTests(unittest.TestCase):
    def setUp(self):
        self.cmds=SDKCommands();self.left=self.cmds.add('face_L');self.right=self.cmds.add('face_R')
        self.a=self.cmds.weight('cone_L');self.b=self.cmds.weight('cone_R');self.driver=self.a+'.WeightRaw';self.target_driver=self.b+'.WeightRaw'
        self.api=load_backend(self.cmds)
    def rows(self,**kw):
        rows=self.api.inspect(self.driver,self.left)['rows']
        for r in rows:r['enabled']=r['channel']=='translateX'
        rows[0].update(kw);return rows
    def build(self,**kw):return self.api.capture(self.driver,self.left,self.rows(value=10.,**kw))
    def curve(self,target=None,channel='translateX'):return self.api.direct_curve((target or self.left)+'.'+channel)
    def test_capture_makes_native_sdk_zero_and_peak_without_writing_driver(self):
        self.cmds.setAttr(self.driver,.4);result=self.build()
        self.assertEqual(self.cmds.nodes[self.curve()]['keys'],[(0.,0.),(1.,10.)]);self.assertEqual(self.cmds.getAttr(self.driver),.4)
        self.assertEqual(self.cmds.getAttr(self.left+'.translateX'),4.);self.assertEqual(result['channels'],1)
        sdk=[x for x in self.cmds.calls if x[0]=='sdk']
        self.assertTrue(all(c[2]['insertBlend'] is False for c in sdk));self.assertFalse(self.cmds.nodes[self.left]['locked'])
    def test_add_and_update_existing_keys_keeps_curve_uuid(self):
        self.build();curve=self.curve();uid=self.api.identity(curve)
        self.api.capture(self.driver,self.left,self.rows(value=7),input_value=.5)
        self.api.capture(self.driver,self.left,self.rows(value=9),input_value=1)
        self.assertEqual(self.api.identity(self.curve()),uid);self.assertEqual(self.cmds.nodes[curve]['keys'],[(0.,0.),(.5,7.),(1.,9.)])
    def test_all_rows_preflight_before_any_edits(self):
        rows=self.rows(value=3);rows[1]['enabled']=True;self.cmds.nodes[self.left]['locked'].add('translateY');before=self.cmds.snap()
        with self.assertRaisesRegex(ValueError,'locked'):self.api.capture(self.driver,self.left,rows)
        self.assertEqual(self.cmds.snap(),before)
    def test_other_animation_blends_and_constraints_are_kept(self):
        for kind in ('animCurveTL','parentConstraint','blendWeighted'):
            other=self.cmds.add('foreign'+kind,kind);self.cmds.edges[self.left+'.translateX']=other+'.output';before=self.cmds.snap()
            with self.assertRaises(ValueError):self.build()
            self.assertEqual(self.cmds.snap(),before)
    def test_existing_child_sdk_does_not_look_like_a_whole_compound_driver(self):
        self.build();original=self.cmds.listConnections
        def aggregate(plug,**kw):
            if plug==self.left+'.translate' and kw.get('source'):return original(self.left+'.translateX',**kw)
            return original(plug,**kw)
        self.cmds.listConnections=aggregate
        self.api.capture(self.driver,self.left,self.rows(value=8),input_value=.5)
        self.assertEqual(len(self.cmds.nodes[self.curve()]['keys']),3)

    def test_existing_unowned_sdk_is_not_adopted_or_overwritten(self):
        self.cmds.setDrivenKeyframe(self.left+'.translateX',currentDriver=self.driver,driverValue=0,value=2,inTangentType='linear',outTangentType='linear')
        before=self.cmds.snap()
        with self.assertRaisesRegex(ValueError,'not owned'):self.build()
        self.assertEqual(self.cmds.snap(),before)
    def test_new_sdk_zero_value_conflict_is_explicit(self):
        with self.assertRaisesRegex(ValueError,'At driver 0'):self.api.capture(self.driver,self.left,self.rows(value=10),input_value=0)
        self.assertFalse(self.api.bindings())
    def test_capture_failure_rolls_back_all_channels_and_metadata(self):
        rows=self.rows(value=10);rows[1]['enabled']=True;self.cmds.fail_on=self.left+'.translateY';before=self.cmds.snap()
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.api.capture(self.driver,self.left,rows)
        self.assertEqual(self.cmds.snap(),before)
    def test_mirror_flip_delta_between_different_neutral_offsets(self):
        self.cmds.setAttr(self.left+'.translateX',5);self.build(neutral=5)
        rows=self.rows(value=10,neutral=5,target_neutral=20,rule='flip_delta')
        self.api.mirror(self.driver,self.left,self.target_driver,self.right,rows)
        curve=self.curve(self.right)
        for x in (0,.2,.5,1):self.assertAlmostEqual(self.cmds.eval(curve,x),20-(self.cmds.eval(self.curve(),x)-5))
        self.assertEqual(self.cmds.nodes[self.curve()]['keys'],[(0.,5.),(1.,10.)])
    def test_keep_delta_and_keep_values_have_distinct_meanings(self):
        for rule,expected in (('keep_delta',[(0.,20.),(1.,25.)]),('keep_values',[(0.,5.),(1.,10.)])):
            self.setUp();self.build(neutral=5);self.api.mirror(self.driver,self.left,self.target_driver,self.right,self.rows(neutral=5,target_neutral=20,rule=rule))
            self.assertEqual(self.cmds.nodes[self.curve(self.right)]['keys'],expected)
    def test_axis_remapping_and_input_reverse_are_independent_of_value_flip(self):
        self.build();rows=self.rows(value=10,mirror_channel='translateZ',rule='flip_delta',target_neutral=2,input_rule='reverse')
        self.api.mirror(self.driver,self.left,self.target_driver,self.right,rows)
        keys=self.cmds.nodes[self.curve(self.right,'translateZ')]['keys'];self.assertEqual(keys,[(0.,-8.),(1.,2.)])
        self.assertFalse(self.cmds.listConnections(self.right+'.translateX',source=True))
    def test_curve_clone_keeps_weighted_tangent_settings_and_infinity(self):
        self.build();curve=self.curve();self.cmds.nodes[curve]['tangents']['fixture']={'weights':[.7,.9],'locks':[True,False]}
        self.cmds.setAttr(curve+'.weightedTangents',True);self.cmds.setAttr(curve+'.preInfinity',2);self.cmds.setAttr(curve+'.postInfinity',4)
        self.api.mirror(self.driver,self.left,self.target_driver,self.right,self.rows(input_rule='reverse'))
        copied=self.curve(self.right)
        self.assertEqual(self.cmds.nodes[copied]['tangents'],self.cmds.nodes[curve]['tangents']);self.assertTrue(self.cmds.getAttr(copied+'.weightedTangents'))
        self.assertEqual((self.cmds.getAttr(copied+'.preInfinity'),self.cmds.getAttr(copied+'.postInfinity')),(4,2))
        call=next(c for c in self.cmds.calls if c[0]=='duplicate');self.assertFalse(call[2]['inputConnections']);self.assertFalse(call[2]['upstreamNodes'])
    def test_preview_never_adds_nodes_connections_or_undo(self):
        self.build();before=self.cmds.snap();history=len(self.cmds.history)
        preview=self.api.preview_mirror(self.driver,self.left,self.target_driver,self.right,self.rows())
        self.assertEqual(len(preview),1);self.assertEqual(self.cmds.snap(),before);self.assertEqual(len(self.cmds.history),history)
    def test_mirror_existing_target_requires_explicit_owned_replacement(self):
        self.build();self.api.mirror(self.driver,self.left,self.target_driver,self.right,self.rows())
        old=self.api.identity(self.curve(self.right));before=self.cmds.snap()
        with self.assertRaisesRegex(ValueError,'already exists'):self.api.mirror(self.driver,self.left,self.target_driver,self.right,self.rows())
        self.assertEqual(self.cmds.snap(),before)
        self.api.mirror(self.driver,self.left,self.target_driver,self.right,self.rows(rule='flip_delta'),replace=True)
        self.assertNotEqual(self.api.identity(self.curve(self.right)),old)
    def test_foreign_target_and_shared_source_curves_are_protected(self):
        self.build();self.cmds.edges[self.right+'.translateX']=self.curve()+'.output';before=self.cmds.snap()
        with self.assertRaisesRegex(ValueError,'shared'):self.api.mirror(self.driver,self.left,self.target_driver,self.right,self.rows(),replace=True)
        self.assertEqual(self.cmds.snap(),before)
    def test_mirror_failure_restores_existing_target_curves_and_map(self):
        self.build();self.api.mirror(self.driver,self.left,self.target_driver,self.right,self.rows());before=self.cmds.snap()
        self.cmds.fail_on=self.right+'.translateX'
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.api.mirror(self.driver,self.left,self.target_driver,self.right,self.rows(rule='flip_delta'),replace=True)
        self.assertEqual(self.cmds.snap(),before)
    def test_duplicate_mappings_and_cross_unit_mapping_are_rejected(self):
        self.build();rows=self.rows();rows[1].update(enabled=True,mirror_channel='translateX')
        with self.assertRaisesRegex(ValueError,'same target'):self.api.preview_mirror(self.driver,self.left,self.target_driver,self.right,rows)
        rows=self.rows(mirror_channel='rotateX')
        with self.assertRaisesRegex(ValueError,'Map translation'):self.api.preview_mirror(self.driver,self.left,self.target_driver,self.right,rows)
    def test_rule_skip_never_writes_its_target_channel(self):
        self.build();rows=self.rows(rule='skip')
        with self.assertRaisesRegex(ValueError,'non-Skip'):self.api.mirror(self.driver,self.left,self.target_driver,self.right,rows)
    def test_maps_save_restore_after_renaming_and_unit_changes(self):
        self.build(neutral=4);rows=self.rows(neutral=4,target_neutral=8,rule='flip_delta',mirror_channel='translateZ')
        meta=self.api.save_map(self.driver,self.left,rows,self.target_driver,self.right)
        self.cmds.rename(self.left,'renamed_L');self.cmds.rename(self.a,'renamedCone_L');self.cmds.unit['linear']='m'
        loaded=self.api.inspect('renamedCone_L.WeightRaw','renamed_L');self.assertEqual(loaded['meta'],meta)
        row=loaded['rows'][0];self.assertAlmostEqual(row['neutral'],.04);self.assertAlmostEqual(row['target_neutral'],.08)
        self.assertEqual(row['mirror_channel'],'translateZ');self.assertEqual(row['rule'],'flip_delta')
    def test_mirror_persists_source_map_in_same_undo_action(self):
        result=self.build();history=len(self.cmds.history)
        self.api.mirror(self.driver,self.left,self.target_driver,self.right,self.rows(rule='flip_delta',target_neutral=12))
        _,data=self.api.read(result['meta']);self.assertEqual(data['rows']['translateX']['rule'],'flip_delta')
        self.assertEqual(data['mirror_driven'],self.api.identity(self.right));self.assertEqual(len(self.cmds.history),history+1)
    def test_remove_keeps_current_pose_and_native_undo_redo(self):
        result=self.build();self.cmds.setAttr(self.driver,.6);before=self.cmds.snap()
        count=self.api.remove(result['meta']);self.assertEqual(count,1);self.assertEqual(self.cmds.getAttr(self.left+'.translateX'),6.)
        self.assertFalse(self.api.direct_curve(self.left+'.translateX'));self.cmds.undo();self.assertEqual(self.cmds.snap(),before)
        self.cmds.redo();self.assertEqual(self.cmds.getAttr(self.left+'.translateX'),6.)
    def test_remove_after_pose_driver_freezes_curve_input(self):
        result=self.build();curve=self.curve();del self.cmds.edges[curve+'.input'];self.cmds.setAttr(curve+'.input',.3);self.cmds.delete(self.a)
        self.assertEqual(self.api.remove(result['meta']),1);self.assertEqual(self.cmds.getAttr(self.left+'.translateX'),3.)
    def test_remove_orphan_metadata_after_curve_deletion_keeps_new_foreign_driver(self):
        result=self.build();self.cmds.delete(self.curve())
        foreign=self.cmds.add('newAnimation','animCurveTL');self.cmds.edges[self.left+'.translateX']=foreign+'.output'
        self.assertEqual(self.api.remove(result['meta']),0)
        self.assertEqual(self.cmds.edges[self.left+'.translateX'],foreign+'.output')
    def test_remove_after_driven_transform_is_deleted_cleans_only_unconnected_owned_curve(self):
        result=self.build();curve=self.curve();self.cmds.delete(self.left)
        self.assertEqual(self.api.remove(result['meta']),1);self.assertNotIn(curve,self.cmds.nodes);self.assertIn(self.a,self.cmds.nodes)
    def test_disconnected_created_curve_can_be_removed_without_changing_driven_value(self):
        result=self.build();del self.cmds.edges[self.left+'.translateX'];self.cmds.setAttr(self.left+'.translateX',123.)
        self.assertEqual(self.api.remove(result['meta']),1);self.assertEqual(self.cmds.getAttr(self.left+'.translateX'),123.)

    def test_same_side_mirror_and_cycles_stop_before_writes(self):
        self.build();before=self.cmds.snap()
        with self.assertRaisesRegex(ValueError,'different'):self.api.mirror(self.driver,self.left,self.driver,self.left,self.rows())
        self.cmds.blocked.add(self.right)
        with self.assertRaisesRegex(ValueError,'cycle'):self.api.mirror(self.driver,self.left,self.target_driver,self.right,self.rows())
        self.assertEqual(self.cmds.snap(),before)
    def test_driver_modes_remain_separate_and_foreign_driver_is_kept(self):
        self.build();before=self.cmds.snap()
        with self.assertRaisesRegex(ValueError,'not owned'):self.api.capture(self.a+'.Weight',self.left,self.rows(value=5))
        self.assertEqual(self.cmds.snap(),before)
    def test_disabled_undo_invalid_weight_and_nonfinite_values_are_readonly(self):
        before=self.cmds.snap();self.cmds.enabled=False
        with self.assertRaisesRegex(ValueError,'Enable Undo'):self.build()
        self.cmds.enabled=True
        for x in (-1,2,float('nan')):
            with self.assertRaises(ValueError):self.api.capture(self.driver,self.left,self.rows(),input_value=x)
        self.assertEqual(self.cmds.snap(),before)



class SDKDependencyTests(unittest.TestCase):
    """API call/ancestor traversal contract; not native Maya graph evaluation."""
    def check(self,visited,ancestors=(),null=False):
        import sys
        from unittest import mock
        cmds=SDKCommands();target=cmds.add('target');weight=cmds.weight('driver')+'.WeightRaw';api=load_backend(cmds)
        class Object:
            def __init__(self,uid,dag=False,parents=()):self.uid,self.dag,self.parents=uid,dag,parents
            def isNull(self):return null
            def hasFn(self,fn):return self.dag
        class Fn:
            def __init__(self,obj):self.obj=obj
            def uuid(self):return types.SimpleNamespace(asString=lambda:self.obj.uid)
        class Path:
            def __init__(self,objects):self.objects=objects[:]
            def length(self):return len(self.objects)
            def node(self):return self.objects[-1]
            def pop(self):self.objects.pop()
        class Selection:
            def add(self,p):self.plug=p
            def getPlug(self,index):return self.plug
        root=Object('driver-uuid');obj=Object('u1' if visited=='self' else 'other',bool(ancestors),[Object('u1' if x=='target' else 'parent') for x in ancestors])
        class Iterator:
            kUpstream=1;kDepthFirst=0;kPlugLevel=1
            def __init__(self,*args):self.items=[root,obj];self.index=0;self.traversingOverWorldSpaceDependents=False;self.args=args;holder.append(self)
            def currentNode(self):return self.items[self.index]
            def isDone(self):return self.index==len(self.items)
            def next(self):self.index+=1
        holder=[];om=types.ModuleType('maya.api.OpenMaya');om.MSelectionList=Selection;om.MFn=types.SimpleNamespace(kInvalid=0,kDagNode=1)
        om.MItDependencyGraph=Iterator;om.MFnDependencyNode=Fn
        om.MDagPath=types.SimpleNamespace(getAllPathsTo=lambda o:[Path(o.parents+[o])])
        maya=types.ModuleType('maya');maya_api=types.ModuleType('maya.api');maya.api=maya_api;maya_api.OpenMaya=om
        with mock.patch.dict(sys.modules,{'maya':maya,'maya.api':maya_api,'maya.api.OpenMaya':om}):
            api._native_cycle_check(weight,target)
        return holder
    def test_direct_upstream_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'cycle'):self.check('self')
    def test_implicit_dag_parent_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'cycle'):self.check('other',ancestors=('target',))
    def test_unrelated_upstream_is_allowed_with_world_dependencies_enabled(self):
        holder=self.check('other',ancestors=('other',));self.assertTrue(holder[0].traversingOverWorldSpaceDependents)
    def test_unknown_dependency_stops_preflight(self):
        with self.assertRaisesRegex(ValueError,'unknown dependency'):self.check('other',null=True)

if __name__=='__main__':unittest.main()
