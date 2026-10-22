"""Pre-skin/bind-space capture with recording API objects; no Maya evaluation."""
import copy
import math
import types
import unittest

import layer_skin_assignment as geometry
import layer_skin_assignment_scene as scene
import layer_skin_core as core


class Matrix:
    def __init__(self,values=None):
        self.values=list(values) if values is not None else [1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.]
    def __iter__(self):return iter(self.values)
    def __mul__(self,other):
        a=self.values;b=other.values
        return Matrix([sum(a[r*4+k]*b[k*4+c] for k in range(4)) for r in range(4) for c in range(4)])
    def inverse(self):
        rows=[self.values[r*4:r*4+4]+[float(r==c) for c in range(4)] for r in range(4)]
        for col in range(4):
            pivot=max(range(col,4),key=lambda r:abs(rows[r][col]))
            if abs(rows[pivot][col])<1e-12:raise ValueError('singular')
            rows[col],rows[pivot]=rows[pivot],rows[col];divisor=rows[col][col]
            rows[col]=[value/divisor for value in rows[col]]
            for r in range(4):
                if r!=col:
                    factor=rows[r][col];rows[r]=[a-factor*b for a,b in zip(rows[r],rows[col])]
        return Matrix([value for row in rows for value in row[4:]])
    def isSingular(self):
        try:self.inverse();return False
        except ValueError:return True


def transform(x=0.,y=0.,z=0.,sx=1.,sy=1.,sz=1.,angle=0.):
    c=math.cos(angle);s=math.sin(angle)
    return Matrix([sx*c,sx*s,0.,0.,-sy*s,sy*c,0.,0.,0.,0.,sz,0.,x,y,z,1.])


class Point:
    def __init__(self,*values):self.values=list(values[:3])+[1.]
    def __iter__(self):return iter(self.values)
    def __mul__(self,matrix):
        result=[sum(self.values[k]*matrix.values[k*4+c] for k in range(4)) for c in range(4)]
        return Point(*result)


class Vector(Point):
    def __init__(self,*values):self.values=list(values[:3])+[0.]
    def __iter__(self):return iter(self.values[:3])
    def __mul__(self,matrix):
        return Vector(*[sum(self.values[k]*matrix.values[k*4+c] for k in range(4)) for c in range(3)])


class Mesh:
    def __init__(self,points):self.points=points;self.reads=[]
    def getPoints(self,space):self.reads.append(space);return [Point(*point) for point in self.points]


class CaptureFixture:
    def __init__(self):
        self.input=Mesh([[.5,0.,0.],[1.5,0.,0.],[-2.,0.,0.]])
        self.output=Mesh([[999.,0.,0.],[998.,0.,0.],[997.,0.,0.]])
        self.geom=transform(10.,20.,sx=2.,sy=3.)
        self.bind={'|rig|a':transform(10.,20.),'|rig|a|offset|b':transform(12.,20.)}
        self.live={path:transform(100.+i*10.,200.,angle=.7) for i,path in enumerate(self.bind)}
        self.ids={'|rig|a':'a','|rig|a|offset|b':'b'};self.logical={'|rig|a':7,'|rig|a|offset|b':31}
        self.live_reads=[];self.matrix_reads=[];self.input_reads=[];self.mesh_world=transform(1000.,2000.,angle=.8)
        case=self
        class Dag:
            def __init__(self,path):self.path=path
            def fullPathName(self):return self.path
            def node(self):return self.path
            def inclusiveMatrix(self):case.live_reads.append(self.path);return case.live[self.path]
        self.dag_type=Dag;self.dags={path:Dag(path) for path in self.bind}
        class Plug:
            def __init__(self,name,index=None):self.name=name;self.index=index
            def elementByLogicalIndex(self,index):return Plug(self.name,index)
            def numChildren(self):return 1
            def child(self,index):return Plug('inputGeometry',self.index)
            def attribute(self):return self.name
            def asMObject(self):
                case.matrix_reads.append((self.name,self.index))
                if self.name=='geomMatrix':return case.geom
                if self.name=='inputGeometry':case.input_reads.append(self.index);return case.input
                if self.name=='bindPreMatrix':
                    path=next(path for path,index in case.logical.items() if index==self.index)
                    return case.bind[path].inverse()
                raise AssertionError(self.name)
        self.fn=types.SimpleNamespace(findPlug=lambda name,*_:Plug(name),indexForOutputShape=lambda node:4,
            indexForInfluenceObject=lambda dag:self.logical[dag.fullPathName()])
        self.om=types.SimpleNamespace(MSpace=types.SimpleNamespace(kObject='object',kWorld='world'),MPoint=Point,MVector=Vector,
            MFnMesh=lambda obj:obj,MFnMatrixData=lambda value:types.SimpleNamespace(matrix=lambda:value),
            MFnAttribute=lambda name:types.SimpleNamespace(name=name))
        self.ctx=dict(mesh=self.output,input_mesh=self.input,fn=self.fn,skin='skin',count=3,
            dag=types.SimpleNamespace(node=lambda:'mesh',inclusiveMatrix=lambda:self.mesh_world),
            influences=list(self.dags.values()),ids=['a','b'])
        self.owner=dict(om=self.om,sibling=lambda name:geometry,joint_id=lambda path:self.ids[path],
            reference_joint_paths=lambda ctx:list(self.dags.values()),cmds=types.SimpleNamespace(currentTime=lambda **kw:12.))
    def capture(self):return scene.capture_reference(self.owner,self.ctx)
    def unbound(self,path,live):self.ids[path]='unbound';self.live[path]=live;self.dags[path]=self.dag_type(path)


class PredeformReferenceTests(unittest.TestCase):
    def setUp(self):self.fixture=CaptureFixture()
    def assert_matrix_near(self,actual,expected):
        for a,b in zip(actual,expected):self.assertAlmostEqual(a,b,places=9)

    def test_input_points_use_geom_bind_space_and_never_read_visible_world_points(self):
        f=self.fixture;ref=f.capture()
        self.assertEqual(ref['points'],[[11.,20.,0.],[13.,20.,0.],[6.,20.,0.]])
        self.assertEqual(f.input.reads,['object']);self.assertFalse(f.output.reads)
        self.assertEqual(ref['geometry_source'],'skin_input_bind')
        self.assertEqual(ref['geometry_matrix'],list(f.geom))
        self.assert_matrix_near(ref['joints']['a']['position'],[10.,20.,0.])
        self.assert_matrix_near(ref['joints']['b']['position'],[12.,20.,0.])
        self.assertFalse(f.live_reads)

    def test_sparse_logical_influence_indices_are_not_physical_weight_columns(self):
        f=self.fixture;f.capture()
        self.assertIn(('bindPreMatrix',7),f.matrix_reads);self.assertIn(('bindPreMatrix',31),f.matrix_reads)
        self.assertNotIn(('bindPreMatrix',0),f.matrix_reads);self.assertNotIn(('bindPreMatrix',1),f.matrix_reads)

    def test_legacy_context_reads_exact_input_geometry_slot_without_orig_name_guessing(self):
        f=self.fixture;f.ctx.pop('input_mesh');ref=f.capture()
        self.assertEqual(f.input_reads,[4]);self.assertFalse(f.output.reads)
        self.assertEqual(ref['points'][0],[11.,20.,0.])

    def test_all_assignment_methods_are_identical_after_live_pose_and_mesh_transform_changes(self):
        f=self.fixture;first=f.capture()
        f.live={path:transform(-500.,80.,angle=2.,sx=3.) for path in f.live}
        f.mesh_world=transform(-1000.,-2000.,sx=-2.,sy=4.,angle=-1.)
        f.output.points=[[100000.,100000.,0.]]*3;second=f.capture()
        self.assertEqual(first,second)
        for method in ('point','bone','axis'):
            with self.subTest(method=method):
                cache=geometry.AssignmentCache();settings=dict(method=method,radius=4.)
                a,_=cache.generate(first,['a','b'],['a','b'],settings)
                count=cache.vertex_tests;b,info=cache.generate(second,['a','b'],['a','b'],settings)
                self.assertEqual(a,b);self.assertTrue(info['reused']);self.assertEqual(cache.vertex_tests,count)

    def test_mirrored_scaled_rotated_bind_geometry_and_axes_stay_in_one_space(self):
        f=self.fixture;f.geom=transform(10.,20.,sx=-2.,sy=3.,angle=.6)
        f.bind['|rig|a']=f.geom
        f.bind['|rig|a|offset|b']=transform(1.)*f.geom
        ref=f.capture();samples,_=geometry.AssignmentCache().generate(ref,['a','b'],['a','b'],dict(method='axis'))
        self.assertEqual(samples['0']['weights'],[1.,0.]);self.assertEqual(samples['1']['weights'],[0.,1.])
        self.assertEqual(samples['2']['weights'],[1.,0.])

    def test_unbound_child_keeps_captured_local_offset_under_ancestor_bind_frame(self):
        f=self.fixture;parent='|rig|a|offset|b';path=parent+'|buffer|unbound';local=transform(2.,3.,angle=.2)
        f.unbound(path,local*f.live[parent]);ref=f.capture()
        expected=local*f.bind[parent]
        self.assert_matrix_near(ref['joints']['unbound']['position'],list(expected)[12:15])
        self.assertEqual(ref['joints']['unbound']['reference_source'],'ancestor_bind_offset')
        self.assertEqual(ref['derived_joints'],['unbound'])
        f.live[parent]=transform(-100.,40.,angle=1.3);f.live[path]=local*f.live[parent]
        recaptured=f.capture()['joints']['unbound']
        for key in ('position','end','x','y','z'):self.assert_matrix_near(recaptured[key],ref['joints']['unbound'][key])

    def test_unbound_separate_root_uses_captured_offset_relative_to_geometry(self):
        f=self.fixture;local=transform(2.,3.);path='|separate|unbound';f.unbound(path,local*f.mesh_world)
        ref=f.capture();expected=local*f.geom
        self.assert_matrix_near(ref['joints']['unbound']['position'],list(expected)[12:15])
        self.assertEqual(ref['joints']['unbound']['reference_source'],'mesh_relative_offset')

    def test_old_posed_reference_migrates_only_on_explicit_assignment_and_keeps_layer_data(self):
        f=self.fixture;old=dict(points=[[900.,0.,0.]]*3,joints={},time=1.,hierarchy_version=1)
        state=dict(reference=old,layers=[dict(samples={'0':.4},mask={'1':.5})]);before=copy.deepcopy(state)
        new=scene.ensure_reference(f.owner,f.ctx,state)
        self.assertEqual(state,before);self.assertIs(new['layers'],state['layers'])
        self.assertEqual(new['reference']['geometry_source'],'skin_input_bind')
        self.assertNotEqual(new['reference']['points'],old['points'])

    def test_existing_input_reference_is_reused_without_reading_live_data(self):
        f=self.fixture;state=dict(reference=f.capture());before=(len(f.input.reads),len(f.matrix_reads))
        self.assertIs(scene.ensure_reference({},f.ctx,state),state)
        self.assertEqual((len(f.input.reads),len(f.matrix_reads)),before)

    def test_refresh_updates_old_planner_and_installs_settings_cleaner_only_once(self):
        f=self.fixture;owner=dict(f.owner,core=core,_layer_skin_assignment_planner=True)
        old=dict(reference=dict(points=[[900.,0.,0.]]*3,joints={},time=1.,hierarchy_version=1))
        owner['_layer_skin_assignment_runtime']={'ensure_reference':lambda owner,ctx,state:state}
        def existing_planner(ctx,meta,state,action,data):
            return owner['_layer_skin_assignment_runtime']['ensure_reference'](owner,ctx,state),[],False
        owner['prepare_edit']=existing_planner
        self.assertTrue(scene.install(owner));installed=owner['prepare_edit']
        self.assertTrue(scene.install(owner));self.assertIs(owner['prepare_edit'],installed)
        result,_,_=owner['prepare_edit'](f.ctx,None,old,'assign',{})
        self.assertEqual(result['reference']['geometry_source'],'skin_input_bind')
        self.assertEqual(old['reference']['points'],[[900.,0.,0.]]*3)

    def test_explicit_recapture_of_changed_pre_skin_points_invalidates_the_result_cache(self):
        f=self.fixture;cache=geometry.AssignmentCache();a=f.capture()
        first,_=cache.generate(a,['a','b'],['a','b'],dict(method='axis'))
        f.input.points[0]=[3.,0.,0.];b=f.capture()
        second,info=cache.generate(b,['a','b'],['a','b'],dict(method='axis'))
        self.assertFalse(info['reused']);self.assertEqual(first['0']['weights'],[1.,0.]);self.assertEqual(second['0']['weights'],[0.,1.])

    def test_missing_or_singular_bind_input_fails_without_using_visible_mesh(self):
        f=self.fixture;f.geom=transform(sx=0.)
        with self.assertRaisesRegex(ValueError,'Invalid skin bind matrix'):f.capture()
        self.assertFalse(f.output.reads)

    def test_input_vertex_count_change_is_rejected_before_generation(self):
        f=self.fixture;f.input.points.pop()
        with self.assertRaisesRegex(ValueError,'vertex count'):f.capture()

    def test_registered_command_migrates_posed_reference_with_native_weight_undo_intact(self):
        from test_layer_skin_command import CommandTests
        case=CommandTests();case.setUp();layer=case.attach();original_class=case.ns['LayerCommand'];f=self.fixture
        old_context=case.ns['context']
        for name in ('findPlug','indexForOutputShape','indexForInfluenceObject'):setattr(case.skin,name,getattr(f.fn,name))
        def context(target):return dict(old_context(target),mesh=f.output,input_mesh=f.input,influences=f.ctx['influences'],dag=f.ctx['dag'])
        case.ns['context']=context
        for name,value in vars(f.om).items():setattr(case.ns['om'],name,value)
        case.ns['reference_joint_paths']=f.owner['reference_joint_paths'];case.ns['joint_id']=f.owner['joint_id']
        old=dict(points=[[900.,0.,0.]]*3,joints={},time=1.,hierarchy_version=1)
        case.graph['raw']=core.encode(core.edit(core.decode(case.graph['raw']),'reference',dict(reference=old)))
        before=case.graph['raw'];weights=case.weights[:]
        with case.assignment_environment():
            case.ns['cmds'].currentTime=lambda **kw:12.
            command=case.command('assign',layer=layer,joints=['a','b'],whole=True,settings=dict(method='point',radius=4.))
        self.assertIs(case.ns['LayerCommand'],original_class)
        self.assertEqual(core.decode(case.graph['raw'])['reference']['geometry_source'],'skin_input_bind')
        after=case.graph['raw'];new_weights=case.weights[:]
        command.undoIt();self.assertEqual(case.graph['raw'],before);self.assertEqual(case.weights,weights)
        command.redoIt();self.assertEqual(case.graph['raw'],after);self.assertEqual(case.weights,new_weights)


if __name__=='__main__':unittest.main(verbosity=2)
