"""Brush staging, spatial scope and event-independent sampling; no Maya runtime."""
import copy
import unittest
import layer_skin_brush as brush
import layer_skin_relax as relax
import layer_skin_core as core
from test_layer_skin_relax import layer_state,amounts


class BrushMathTests(unittest.TestCase):
    def test_falloff_is_one_at_center_and_zero_at_and_outside_edge(self):
        self.assertEqual(brush.falloff(0),1.);self.assertEqual(brush.falloff(1),0.)
        self.assertEqual(brush.falloff(2),0.);self.assertAlmostEqual(brush.falloff(.5),.5625)
    def test_sampler_has_same_stamps_for_coarse_and_fine_events(self):
        a=brush.PointSampler(2);b=brush.PointSampler(2)
        coarse=a.feed((0,0))+a.feed((10,0))
        fine=[]
        for x in range(11):fine+=b.feed((x,0))
        self.assertEqual(coarse,fine);self.assertEqual([p[0] for p in fine],[0,2,4,6,8,10])
        self.assertEqual(b.feed((10,0)),[])
    def test_sampler_respects_polyline_corners_and_bounds_fast_move_work(self):
        sampler=brush.PointSampler(2,max_samples=3)
        self.assertEqual(sampler.feed((0,0)),[(0,0)])
        self.assertEqual(sampler.feed((1,0)),[]);self.assertEqual(sampler.feed((1,3)),[(1.,1.),(1.,3.)])
        self.assertEqual(len(sampler.feed((1000,3))),3)
    def test_grid_uses_connected_patch_and_does_not_jump_to_close_island(self):
        grid=brush.SurfaceGrid([(0,0,0),(.5,0,0),(.05,0,.01),(2,0,0)],1.)
        graph={0:[1],1:[0,3],2:[],3:[1]}
        values=grid.footprint((0,0,0),[0],graph.__getitem__)
        self.assertEqual(set(values),{0,1});self.assertEqual(values[0],1.);self.assertAlmostEqual(values[1],.5625)
    def test_large_footprint_has_a_bounded_failure(self):
        grid=brush.SurfaceGrid([(0,0,0)]*5,1)
        with self.assertRaisesRegex(ValueError,'Reduce the radius'):grid.footprint((0,0,0),[0],lambda v:[],max_vertices=2)
    def test_screen_clipping_is_applied_before_connectivity_and_never_bridges_an_outside_vertex(self):
        grid=brush.SurfaceGrid([(0,0,0),(.1,0,0),(.2,0,0)],1.)
        graph={0:[1],1:[0,2],2:[1]}
        factors=grid.footprint((0,0,0),[0],graph.__getitem__,clip=lambda v:0. if v==1 else 1.)
        self.assertEqual(factors,{0:1.})
    def test_dynamic_radius_obeys_boundary_and_preserves_the_position_hash(self):
        points=[(0,0,0),(.5,0,0),(1.,0,0),(1.5,0,0),(2.,0,0),(200.,0,0)]
        grid=brush.SurfaceGrid(points,.25);cells=grid.cells
        for radius,expected in ((1.,{0,1}),(2.,{0,1,2,3}),(100.,{0,1,2,3,4})):
            with self.subTest(radius=radius):
                factors=grid.footprint((0,0,0),range(len(points)),lambda v:[],radius=radius)
                self.assertEqual(set(factors),expected);self.assertIs(grid.cells,cells)
        for radius in (0.,-1.,float('inf'),float('nan')):
            with self.assertRaises(ValueError):grid.footprint((0,0,0),[0],lambda v:[],radius=radius)
    def test_many_passes_and_stamps_only_update_current_footprint_for_weights_and_mask(self):
        for mode in ('weights','mask'):
            with self.subTest(mode=mode):
                state,layer=layer_state([[1,0],[0,1],[1,0],[0,1]])
                state=core.edit(state,'paint',dict(layer=layer,mode='mask',values={'0':0.,'1':.4,'2':.2}))
                source=copy.deepcopy(state)
                stroke=brush.RelaxStroke(state,layer,mode,dict(iterations=20,strength=.6),relax)
                graph={0:[1],1:[0,2],2:[1,3],3:[2]}
                for _ in range(10):stroke.stamp({0:1.,1:0.},graph.__getitem__)
                if mode=='weights':before=copy.deepcopy(relax.sample_at(stroke.layer,0))
                else:before=stroke.layer['mask']['0']
                stroke.stamp({2:1.},graph.__getitem__)
                after=relax.sample_at(stroke.layer,0) if mode=='weights' else stroke.layer['mask']['0']
                self.assertEqual(after,before) # The old stamp is not smoothed again by the new stamp.
                payload=stroke.payload();rows=payload['samples' if mode=='weights' else 'values']
                self.assertEqual(set(rows),{'0','2'});self.assertEqual(state,source)
                for v in (1,3):
                    if mode=='weights':self.assertEqual(relax.sample_at(stroke.layer,v),relax.sample_at(stroke.source,v))
                    else:self.assertEqual(stroke.layer['mask'].get(str(v),1.),stroke.source['mask'].get(str(v),1.))
    def test_brush_strength_opacity_and_falloff_multiply_without_mutating_source(self):
        state,layer=layer_state([[1,0],[0,1]]);before=copy.deepcopy(state)
        stroke=brush.RelaxStroke(state,layer,'weights',dict(strength=.5,opacity=.5),relax)
        changed=stroke.stamp({0:.5},lambda v:[1-v])
        self.assertEqual(changed,[0]);self.assertAlmostEqual(stroke.preview([0],'1')[0],.125)
        self.assertEqual(state,before);self.assertEqual(stroke.payload()['samples']['0']['coverage'],1.)
    def test_preserve_coverage_keeps_empty_region_empty_and_retains_partial_amount(self):
        state,layer=layer_state([[1,0],[0,1]],coverage=[.2,.8])
        stroke=brush.RelaxStroke(state,layer,'weights',dict(preserve_coverage=True),relax)
        stroke.stamp({0:1.},lambda v:[1-v]);sample=stroke.payload()['samples']['0']
        self.assertAlmostEqual(sample['coverage'],.2)
        state,layer=layer_state([[1,0],[0,1]],coverage=[0.,1.])
        stroke=brush.RelaxStroke(state,layer,'weights',dict(preserve_coverage=True),relax)
        self.assertEqual(stroke.stamp({0:1.},lambda v:[1-v]),[])
        stroke=brush.RelaxStroke(state,layer,'weights',dict(preserve_coverage=False),relax)
        stroke.stamp({0:1.},lambda v:[1-v]);self.assertAlmostEqual(stroke.payload()['samples']['0']['coverage'],.5)
    def test_default_brush_feathers_a_single_joint_patch_into_empty_neighbors(self):
        state,layer=layer_state([[0.,1.],[1.,0.],[1.,0.]],ids=['a','b'],coverage=[1.,0.,0.])
        stroke=brush.RelaxStroke(state,layer,'weights',{},relax)
        changed=stroke.stamp({0:1.,1:1.},lambda v:{0:[1],1:[0,2],2:[1]}[v])
        self.assertEqual(changed,[0,1]);self.assertEqual(stroke.preview([0,1,2],'b'),{0:.5,1:.25,2:0.})
        self.assertEqual(set(stroke.payload()['samples']),{'0','1'})
    def test_default_brush_averages_single_influence_coverage_instead_of_normalizing_it_away(self):
        state,layer=layer_state([[1.],[1.]],ids=['onlyJoint'],coverage=[.2,.8])
        stroke=brush.RelaxStroke(state,layer,'weights',{},relax)
        stroke.stamp({0:1.,1:1.},lambda v:[1-v])
        for value in stroke.preview([0,1],'onlyJoint').values():self.assertAlmostEqual(value,.5)
    def test_new_influence_cap_is_relative_to_start_of_entire_stroke(self):
        state,layer=layer_state([[1,0,0],[0,1,0],[0,0,1]])
        stroke=brush.RelaxStroke(state,layer,'weights',dict(max_new=1,strength=.5),relax)
        stroke.stamp({0:1.},lambda v:[1]);stroke.stamp({0:1.},lambda v:[2])
        row=stroke.payload()['samples']['0']['weights']
        self.assertLessEqual(sum(value>1e-12 for value in row[1:]),1)
        self.assertAlmostEqual(sum(row),1.)
    def test_preserve_coverage_at_full_strength_keeps_row_when_neighbors_are_empty(self):
        state,layer=layer_state([[.2,.8],[1,0]],coverage=[.4,0.])
        stroke=brush.RelaxStroke(state,layer,'weights',dict(strength=1.,preserve_coverage=True),relax)
        self.assertEqual(stroke.stamp({0:1.},lambda v:[1-v]),[])
        self.assertEqual(stroke.payload()['samples'],{})
        self.assertAlmostEqual(relax.sample_at(stroke.layer,0)['coverage'],.4)
        free=brush.RelaxStroke(state,layer,'weights',dict(strength=1.,preserve_coverage=False),relax)
        free.stamp({0:1.},lambda v:[1-v]);self.assertEqual(free.payload()['samples']['0']['coverage'],0.)
    def test_group_relax_keeps_unselected_joint_and_group_budget(self):
        state,layer=layer_state([[.2,.3,.5],[.8,.2,0]],['a','b','c'])
        stroke=brush.RelaxStroke(state,layer,'weights',dict(joints=['a','b'],strength=1.),relax)
        stroke.stamp({0:1.},lambda v:[1-v]);row=stroke.payload()['samples']['0']['weights']
        for actual,expected in zip(row,[.4,.1,.5]):self.assertAlmostEqual(actual,expected)
    def test_mask_relax_smooths_only_mask_and_keeps_weight_samples(self):
        state,layer=layer_state([[1,0],[0,1]])
        state=core.edit(state,'paint',dict(layer=layer,mode='mask',values={'0':0.}))
        source=copy.deepcopy(state);stroke=brush.RelaxStroke(state,layer,'mask',{},relax)
        stroke.stamp({0:1.},lambda v:[1-v])
        self.assertEqual(stroke.payload()['values'],{'0':.5})
        self.assertEqual(stroke.layer['samples'],state['layers'][0]['samples']);self.assertEqual(state,source)
    def test_zero_strength_opacity_and_outside_footprint_are_noops(self):
        state,layer=layer_state([[1,0],[0,1]])
        for settings in ({'strength':0},{'opacity':0}):
            stroke=brush.RelaxStroke(state,layer,'weights',settings,relax)
            self.assertEqual(stroke.stamp({0:1.},lambda v:[1-v]),[]);self.assertEqual(stroke.payload()['samples'],{})
    def test_only_scope_and_halo_samples_are_read_for_sparse_brush(self):
        state,layer=layer_state([[1,0],[0,1],[1,0],[0,1]])
        original=relax.sample_at;seen=[]
        def track(row,v):seen.append(v);return original(row,v)
        from unittest import mock
        with mock.patch.object(relax,'sample_at',side_effect=track):
            relax.relax_samples(state,layer,{0:[1]},[0],iterations=3)
        self.assertEqual(set(seen),{0,1})
    def test_invalid_brush_settings_and_out_of_range_vertices_are_rejected(self):
        state,layer=layer_state([[1,0],[0,1]])
        for setting in ({'opacity':float('nan')},{'iterations':0},{'max_new':-1},{'strength':2},{'preserve_coverage':'yes'}):
            with self.subTest(setting=setting),self.assertRaises(ValueError):brush.RelaxStroke(state,layer,'weights',setting,relax)
        stroke=brush.RelaxStroke(state,layer,'weights',{},relax)
        with self.assertRaises(ValueError):stroke.stamp({9:1.},lambda v:[])
