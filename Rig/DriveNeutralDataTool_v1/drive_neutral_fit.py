"""Translation-only fitting for the reconstructed NFRv1 Maya rig.

All scene writes use undoable Maya commands. No evaluation callbacks or
plug-ins are installed. Existing animation connections are retained.
"""
import json
import math
import re

import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma

import drive_neutral_core as core
import drive_neutral_maya as adapter

PREVIEW = 'DN_FitPreview'
UNDO_CHUNK = 'DriveNeutralData_ApplyFit'
IDENTITY = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]
# These upper-nose modifiers are saved at 1 in the supplied GUI. They have
# no direct joint or animated-map response: the native evaluator only uses
# them in products with noseWrinkleL/R (raw 51/52), which must remain zero.
NEUTRAL_MODIFIERS = frozenset((53, 54))


def flat(value):
    while isinstance(value, (tuple, list)) and len(value) == 1 and isinstance(value[0], (tuple, list)):
        value = value[0]
    return list(value)


def sources(plug):
    return cmds.listConnections(plug, source=True, destination=False, plugs=True) or []


def points(path, space=om.MSpace.kWorld):
    return [core.point([p.x, p.y, p.z]) for p in om.MFnMesh(path).getPoints(space)]


def ui_distance(value_cm):
    return om.MDistance(value_cm, om.MDistance.kCentimeters).asUnits(om.MDistance.uiUnit())


def world_position(name):
    return core.point(list(adapter.dag_path(name).inclusiveMatrix())[12:15])


def rotation_state(name):
    matrix = list(adapter.dag_path(name).inclusiveMatrix())
    state = {'rotate': flat(cmds.getAttr(name + '.rotate')),
            'jointOrient': flat(cmds.getAttr(name + '.jointOrient')),
            'scale': flat(cmds.getAttr(name + '.scale')),
            'world_linear': [matrix[i] for i in (0, 1, 2, 4, 5, 6, 8, 9, 10)]}
    if not all(math.isfinite(x) for values in state.values() for x in values):
        raise ValueError('Non-finite joint transform: ' + name)
    return state


def native_bus(document):
    prefixes = set()
    for row in document['joints']:
        name = adapter.resolve(row['joint'], 'joint')
        for axis in 'XYZ':
            for source in sources(name + '.translate' + axis):
                node = source.split('.', 1)[0]
                match = re.fullmatch(r'(.*)NFRv1_channel_\d+', node)
                if match:
                    prefixes.add(match[1])
    buses = [prefix + 'NFRv1_RAW' for prefix in prefixes if cmds.objExists(prefix + 'NFRv1_RAW')]
    if len(buses) != 1:
        raise ValueError('Apply expects one reconstructed NFRv1 facial rig in the saved joint scope.')
    return buses[0]


def check_neutral(document):
    bus = native_bus(document)
    indices = cmds.getAttr(bus + '.value', multiIndices=True) or []
    if not set(range(263)).issubset(indices):
        raise ValueError('The native raw input bus is incomplete')
    wrong = []
    for index in range(263):
        expected = 1. if index in (254, 258, 262) else 0.
        value = cmds.getAttr(bus + '.value[' + str(index) + ']')
        if index in NEUTRAL_MODIFIERS:
            valid = math.isfinite(value) and -1e-5 <= value <= 1. + 1e-5
            expected_text = '0..1 (inactive while noseWrinkleL/R are zero)'
        else:
            valid = math.isfinite(value) and abs(value - expected) <= 1e-5
            expected_text = str(expected)
        if not valid:
            plug = bus + '.value[' + str(index) + ']'
            incoming = sources(plug)
            label = incoming[0] if incoming else plug
            wrong.append('{} (raw {}, value {!r}; expected {})'.format(
                label, index, value, expected_text))
    if wrong:
        raise ValueError('Return facial GUI and neck/head rotations to neutral before fitting. '
                         'Non-neutral controls:\n' + '\n'.join(wrong[:15]))
    return bus


def translation_writer(joint, axis):
    plug = joint + '.translate' + axis
    incoming = sources(plug)
    if not incoming:
        if cmds.getAttr(plug, lock=True):
            raise ValueError('Unconnected translation is locked: ' + plug)
        return {'kind': 'direct', 'plug': plug}
    if len(incoming) != 1:
        raise ValueError('Unexpected translation inputs: ' + plug)
    conversion = incoming[0].split('.', 1)[0]
    if cmds.nodeType(conversion) != 'unitConversion' or not re.search(r'(?:^|:)NFRv1_channel_\d+$', conversion):
        raise ValueError('Translation has an unsupported driver: ' + plug + ' <- ' + incoming[0])
    if abs(cmds.getAttr(conversion + '.conversionFactor') - 1.) > 1e-12:
        raise ValueError('Unexpected native translation unit conversion: ' + conversion)
    point_source = sources(conversion + '.input')
    if len(point_source) != 1:
        raise ValueError('Missing native matrix extractor: ' + conversion)
    extractor, output = point_source[0].split('.', 1)
    axes = {'outputX': 0, 'outputY': 1, 'outputZ': 2, 'ox': 0, 'oy': 1, 'oz': 2}
    if cmds.nodeType(extractor) != 'pointMatrixMult' or output not in axes:
        raise ValueError('Unexpected native matrix output: ' + point_source[0])
    if not cmds.getAttr(extractor + '.vectorMultiply'):
        raise ValueError('Expected native vector row extraction')
    cell = core.matrix_cell_from_extractor(flat(cmds.getAttr(extractor + '.inPoint')), axes[output])
    matrix_source = sources(extractor + '.inMatrix')
    if len(matrix_source) != 1:
        raise ValueError('Missing native weighted matrix: ' + extractor)
    matrix_node = matrix_source[0].split('.', 1)[0]
    if cmds.nodeType(matrix_node) != 'wtAddMatrix' or not re.search(r'(?:^|:)NFRv1_joint_matrix_\d+$', matrix_node):
        raise ValueError('Unexpected native matrix node: ' + matrix_node)
    # The v1 compiler always emits the neutral constant in matrix slot zero.
    constant = matrix_node + '.wtMatrix[0].matrixIn'
    weight = matrix_node + '.wtMatrix[0].weightIn'
    if sources(constant) or sources(weight) or abs(cmds.getAttr(weight) - 1.) > 1e-12:
        raise ValueError('Native neutral matrix slot has been modified: ' + matrix_node)
    if cmds.getAttr(constant, lock=True):
        raise ValueError('Native neutral matrix is locked: ' + constant)
    values = flat(cmds.getAttr(constant))
    if len(values) != 16 or not all(math.isfinite(x) for x in values):
        raise ValueError('Invalid native neutral matrix')
    return {'kind': 'native_constant', 'plug': constant, 'cell': cell}


def skin_function(name):
    selection = om.MSelectionList()
    selection.add(name)
    return oma.MFnSkinCluster(selection.getDependNode(0))


def skin_jobs(document):
    names = set()
    for mesh in document['meshes'].values():
        path = adapter.mesh_path(adapter.resolve(mesh['identity']))
        names.update(adapter.skin_history(path.fullPathName()))
    jobs, poses = [], set()
    for name in sorted(names):
        binds = []
        for index in cmds.getAttr(name + '.matrix', multiIndices=True) or []:
            plug = name + '.bindPreMatrix[' + str(index) + ']'
            if sources(plug) or cmds.getAttr(plug, lock=True):
                raise ValueError('Bind matrix must be a writable static value: ' + plug)
            matrix = om.MMatrix(flat(cmds.getAttr(name + '.matrix[' + str(index) + ']')))
            if not math.isfinite(matrix.det4x4()) or abs(matrix.det4x4()) < 1e-12:
                raise ValueError('Singular skin influence matrix: ' + name)
            binds.append(index)
        jobs.append({'name': name, 'indices': binds})
        poses.update(cmds.listConnections(name + '.bindPose', source=True, destination=False, type='dagPose') or [])
    pose_jobs = []
    for pose in sorted(poses):
        members = cmds.dagPose(pose, query=True, members=True) or []
        if members:
            pose_jobs.append({'name': pose, 'members': members})
    return jobs, pose_jobs


def base_edit(snapshot, source_path, desired_world):
    skins = adapter.skin_history(source_path.fullPathName())
    if len(skins) != 1:
        raise ValueError('Installing a rest mesh currently requires one skinCluster: ' + source_path.fullPathName())
    skin = skin_function(skins[0])
    if skin.numOutputConnections() != 1:
        raise ValueError('Expected one skinCluster output geometry')
    index = skin.indexForOutputConnection(0)
    input_object = skin.inputShapeAtIndex(index)
    base = om.MDagPath.getAPathTo(input_object)
    if not base.node().hasFn(om.MFn.kMesh) or base.fullPathName() == source_path.fullPathName():
        raise ValueError('Could not find a distinct pre-skin input mesh')
    adapter.assert_topology(snapshot, base)
    if cmds.lockNode(base.fullPathName(), query=True, lock=True)[0]:
        raise ValueError('Pre-skin input mesh is locked: ' + base.fullPathName())
    current_output = points(source_path)
    current_base = points(base, om.MSpace.kObject)
    inverse = base.inclusiveMatrixInverse()
    source_matrix = source_path.inclusiveMatrix()
    def geometry_points(plug_name):
        selection = om.MSelectionList()
        selection.add(plug_name)
        data = selection.getPlug(0).asMObject()
        return [core.point([p.x, p.y, p.z]) for p in om.MFnMesh(data).getPoints(om.MSpace.kObject)]
    current_skin_input = geometry_points(skins[0] + '.input[' + str(index) + '].inputGeometry')
    current_skin_output = geometry_points(skins[0] + '.outputGeometry[' + str(index) + ']')
    if not (len(current_base) == len(current_skin_input) == len(current_skin_output) == len(desired_world)):
        raise ValueError('Input/output mesh vertex counts differ before fitting')
    target_base = []
    # Bake any existing neutral skin deformation before resetting inverse bind
    # matrices. Keep upstream/downstream tweaks and add only the desired surface
    # delta, rather than double-applying those tweaks.
    for original, visible, desired, skin_in, skin_out in zip(
            current_base, current_output, desired_world, current_skin_input, current_skin_output):
        old_skin_delta = om.MVector(*[a - b for a, b in zip(skin_out, skin_in)]) * source_matrix
        surface_delta = om.MVector(*[a - b for a, b in zip(desired, visible)])
        delta = (old_skin_delta + surface_delta) * inverse
        target_base.append([original[0] + delta.x, original[1] + delta.y, original[2] + delta.z])
    return {'name': base.fullPathName(), 'points_object_cm': target_base, 'before_object_cm': current_base}


def prepare(document, mapping, install_mesh=True, reset=False, for_apply=True):
    core.validate(document)
    problems = adapter.validate_scene(document)
    if problems:
        raise ValueError('\n'.join(problems[:12]))
    check_neutral(document)
    target_points, target_paths = {}, {}
    source_paths = {key: adapter.mesh_path(adapter.resolve(mesh['identity']))
                    for key, mesh in document['meshes'].items()}
    if set(mapping) - set(document['meshes']):
        raise ValueError('Target mapping contains an unknown saved source mesh')
    for key, path in source_paths.items():
        saved = document['meshes'][key].get('default_world_matrix')
        if saved and max(abs(a - b) for a, b in zip(saved, list(path.inclusiveMatrix()))) > 1e-7:
            raise ValueError('Original source mesh placement changed after capture: ' + path.fullPathName())
    if reset:
        target_points = {key: mesh['default_positions_cm'] for key, mesh in document['meshes'].items()}
    else:
        for key, target_name in mapping.items():
            if key not in document['meshes'] or not target_name.strip():
                continue
            target = adapter.mesh_path(target_name)
            adapter.assert_topology(document['meshes'][key], target)
            if adapter.identity(target)['uuid'] in document['meshes']:
                raise ValueError('Use an independent fitting copy as the target: ' + target.fullPathName())
            history = cmds.listHistory(target.fullPathName()) or []
            if history and cmds.ls(history, type='skinCluster'):
                raise ValueError('Fitting target must be unskinned: ' + target.fullPathName())
            history_meshes = (cmds.ls(history, long=True, type='mesh') or []) if history else []
            source_parents = {path.fullPathName().rsplit('|', 1)[0] for path in source_paths.values()}
            if any(name.rsplit('|', 1)[0] in source_parents for name in history_meshes):
                raise ValueError('Target still depends on the original rig; use an independent copy.')
            target_points[key] = points(target)
            target_paths[key] = target.fullPathName()
        if not target_points:
            raise ValueError('Map at least one saved source mesh to Head_FitTarget or another edited target.')
    fitted = core.fit_positions(document, target_points)
    plan = {'joints': [], 'mesh_edits': [], 'skins': [], 'poses': [], 'expected_meshes': [],
            'rotations': {}, 'target_mapping': target_paths, 'reset_to_template': reset,
            'install_mesh': install_mesh, 'created_utc': core.utc_now()}
    for row, fit in zip(document['joints'], fitted):
        joint = adapter.resolve(row['joint'], 'joint')
        state = rotation_state(joint)
        saved = row.get('default_world_matrix')
        if saved and max(abs(a - saved[i]) for a, i in zip(state['world_linear'], (0, 1, 2, 4, 5, 6, 8, 9, 10))) > 1e-5:
            raise ValueError('Joint orientation/scale differs from the captured neutral: ' + joint)
        plan['rotations'][joint] = state
        job = {'name': joint, 'position_cm': fit['position_cm'], 'delta_cm': fit['delta_cm'],
               'joint': fit['joint'], 'assigned': fit['assigned']}
        if for_apply:
            if cmds.attributeQuery('offsetParentMatrix', node=joint, exists=True):
                if max(abs(a - b) for a, b in zip(flat(cmds.getAttr(joint + '.offsetParentMatrix')), IDENTITY)) > 1e-9:
                    raise ValueError('Non-identity offsetParentMatrix is unsupported for Apply: ' + joint)
            for attr in ('rotatePivot', 'rotatePivotTranslate'):
                if max(abs(x) for x in flat(cmds.getAttr(joint + '.' + attr))) > 1e-9:
                    raise ValueError('Nonzero joint pivot is unsupported for Apply: ' + joint)
            job['writers'] = [translation_writer(joint, axis) for axis in 'XYZ']
        plan['joints'].append(job)
    plan['joints'].sort(key=lambda row: row['name'].count('|'))
    if for_apply:
        for key, source in source_paths.items():
            expected = target_points[key] if install_mesh and key in target_points else points(source)
            plan['expected_meshes'].append({'name': source.fullPathName(), 'points_world_cm': expected})
            # Rebinding must also preserve unchanged meshes when their original
            # bind matrices differed slightly from the captured neutral pose.
            plan['mesh_edits'].append(base_edit(document['meshes'][key], source, expected))
        plan['skins'], plan['poses'] = skin_jobs(document)
    return plan


class MayaFitScene:
    def __init__(self):
        self.changed = False
        self.open = False

    def begin(self):
        if not cmds.undoInfo(query=True, state=True):
            raise ValueError('Enable Maya Undo before Apply so a failed or cancelled fit can roll back.')
        cmds.undoInfo(openChunk=True, chunkName=UNDO_CHUNK)
        self.open = True

    def place_joint(self, job, report):
        path = adapter.dag_path(job['name'])
        parent = om.MDagPath(path)
        parent.pop()
        inverse = parent.inclusiveMatrixInverse() if parent.length() else om.MMatrix()
        desired = om.MPoint(*job['position_cm']) * inverse
        current = om.MFnTransform(path).translation(om.MSpace.kTransform)
        core.point([desired.x, desired.y, desired.z])
        core.point([current.x, current.y, current.z])
        for value, old, writer in zip((desired.x, desired.y, desired.z), (current.x, current.y, current.z), job['writers']):
            delta = value - old
            if abs(delta) <= 1e-10:
                continue
            if writer['kind'] == 'native_constant':
                matrix = flat(cmds.getAttr(writer['plug']))
                matrix[writer['cell']] += delta
                cmds.setAttr(writer['plug'], *matrix, type='matrix')
            else:
                cmds.setAttr(writer['plug'], ui_distance(value))
            self.changed = True

    def write_mesh(self, job, report):
        for index, (old, new) in enumerate(zip(job['before_object_cm'], job['points_object_cm'])):
            if index % 128 == 0:
                report('Install rest mesh: {} / {}'.format(index, len(job['points_object_cm'])))
            if core.distance2(old, new) <= 1e-18:
                continue
            cmds.xform(job['name'] + '.vtx[' + str(index) + ']', objectSpace=True,
                       translation=[ui_distance(x) for x in new])
            self.changed = True

    def update_skin(self, job, report):
        for index in job['indices']:
            matrix = om.MMatrix(flat(cmds.getAttr(job['name'] + '.matrix[' + str(index) + ']')))
            inverse = list(matrix.inverse())
            if not all(math.isfinite(x) for x in inverse):
                raise ValueError('Non-finite inverse bind matrix: ' + job['name'])
            plug = job['name'] + '.bindPreMatrix[' + str(index) + ']'
            if max(abs(a - b) for a, b in zip(flat(cmds.getAttr(plug)), inverse)) > 1e-12:
                cmds.setAttr(plug, *inverse, type='matrix')
                self.changed = True

    def update_pose(self, job, report):
        cmds.dagPose(job['members'], reset=True, name=job['name'])
        self.changed = True

    def verify(self, plan):
        joint_error = 0.
        rotation_error = 0.
        mesh_error = 0.
        records = []
        for job in plan['joints']:
            actual = world_position(job['name'])
            joint_error = max(joint_error, core.distance2(actual, job['position_cm']) ** .5)
            current_state = rotation_state(job['name'])
            old_state = plan['rotations'][job['name']]
            rotation_error = max(rotation_error, max(abs(a - b) for key in current_state
                                                     for a, b in zip(current_state[key], old_state[key])))
            local = om.MFnTransform(adapter.dag_path(job['name'])).translation(om.MSpace.kTransform)
            records.append({'joint': job['joint'], 'position_cm': actual,
                            'local_translation_cm': [local.x, local.y, local.z], 'delta_cm': job['delta_cm']})
        for mesh in plan['expected_meshes']:
            actual = points(adapter.mesh_path(mesh['name']))
            if len(actual) != len(mesh['points_world_cm']):
                raise ValueError('Mesh topology changed while applying the fit')
            mesh_error = max(mesh_error, max((core.distance2(a, b) ** .5 for a, b in zip(actual, mesh['points_world_cm'])), default=0.))
        return {'schema': 'driveNeutralFitResult', 'version': 1, 'applied_to_scene': True,
                'created_utc': core.utc_now(), 'translation_only': True,
                'reset_to_template': plan['reset_to_template'], 'install_mesh': plan['install_mesh'],
                'target_mapping': plan['target_mapping'], 'joint_count': len(records), 'joints': records,
                'maximum_joint_position_error_cm': joint_error, 'maximum_mesh_position_error_cm': mesh_error,
                'maximum_rotation_scale_attribute_change': rotation_error,
                'passed': joint_error <= .0001 and mesh_error <= .002 and rotation_error <= 1e-7}

    def commit(self):
        if self.open:
            cmds.undoInfo(closeChunk=True)
            self.open = False

    def rollback(self):
        self.commit()
        if self.changed:
            if cmds.undoInfo(query=True, undoName=True) != UNDO_CHUNK:
                raise RuntimeError('The Maya undo queue changed; automatic rollback cannot identify the fit action. '
                                   'No unrelated undo action was executed. Reopen the saved test copy if needed.')
            cmds.undo()


def apply(document, mapping, install_mesh=True, reset=False, progress=None):
    plan = prepare(document, mapping, install_mesh=install_mesh, reset=reset, for_apply=True)
    return core.execute_fit(plan, MayaFitScene(), progress)


def clear_preview():
    if cmds.objExists(PREVIEW):
        if not cmds.attributeQuery('driveNeutralPreview', node=PREVIEW, exists=True):
            raise ValueError('An unrelated object already uses the preview group name')
        cmds.delete(PREVIEW)


def preview(document, mapping, size=.15, moved_only=True):
    plan = prepare(document, mapping, install_mesh=False, for_apply=False)
    clear_preview()
    cmds.undoInfo(openChunk=True, chunkName='DriveNeutralData_Preview')
    try:
        group = cmds.group(empty=True, name=PREVIEW)
        cmds.addAttr(group, longName='driveNeutralPreview', attributeType='bool', defaultValue=True)
        for job in plan['joints']:
            if moved_only and sum(x * x for x in job['delta_cm']) <= 1e-14:
                continue
            short = job['joint']['name'].split('|')[-1].replace(':', '_')
            locator = cmds.spaceLocator(name='DNFP_' + short)[0]
            cmds.xform(locator, worldSpace=True, translation=[ui_distance(x) for x in job['position_cm']])
            cmds.parent(locator, group)
            shape = cmds.listRelatives(locator, shapes=True, fullPath=True)[0]
            cmds.setAttr(shape + '.localScale', size, size, size, type='double3')
            cmds.setAttr(shape + '.overrideEnabled', True)
            cmds.setAttr(shape + '.overrideColor', 14)
        cmds.select(group, replace=True)
    finally:
        cmds.undoInfo(closeChunk=True)
    return {'schema': 'driveNeutralFitResult', 'version': 1, 'applied_to_scene': False,
            'translation_only': True, 'created_utc': core.utc_now(),
            'target_mapping': plan['target_mapping'], 'joint_count': len(plan['joints']),
            'joints': [{key: job[key] for key in ('joint', 'position_cm', 'delta_cm', 'assigned')}
                       for job in plan['joints']]}


def guess_target(document, name='Head_FitTarget'):
    if not cmds.objExists(name):
        return {}
    try:
        target = adapter.mesh_path(name)
        matches = []
        for key, mesh in document['meshes'].items():
            try:
                adapter.assert_topology(mesh, target)
                matches.append(key)
            except ValueError:
                pass
        return {matches[0]: target.fullPathName()} if len(matches) == 1 else {}
    except (RuntimeError, ValueError):
        return {}


def save_report(report, path):
    if report is None:
        raise ValueError('Preview or Apply a fit before exporting its result')
    from pathlib import Path
    # Keep the captured driveNeutralData document untouched.
    with open(Path(path), 'w', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    return str(path)
