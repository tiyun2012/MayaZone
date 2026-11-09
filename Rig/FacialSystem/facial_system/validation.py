"""Fit-aware behavior and geometry checks. Maya is imported only on demand."""
import gzip
import json
import math
from pathlib import Path
import time

from . import core

DATA = Path(__file__).resolve().parent / 'data'


def adjusted_reference(outputs, expected, offsets):
    """Keep ROM response references, adding only current neutral T offsets."""
    if len(outputs) != len(expected):
        raise ValueError('Reference output count does not match the behavior model')
    values = []
    for row, value in zip(outputs, expected):
        if row['dof'] < 3:
            value += offsets.get(row['destination'], 0.)
        if not math.isfinite(value):
            raise ValueError('Non-finite reference value')
        values.append(value)
    return values


def _read_channel(plug, dof):
    if dof < 3:
        return plug.asMDistance().asCentimeters()
    if dof < 6:
        return plug.asMAngle().asDegrees()
    return plug.asDouble()


def check_behavior(limit=None, progress=None):
    """Check 107 poses with current neutral T constants; restore raw inputs.

    This tests the raw-to-local-channel evaluator, not GUI or mesh quality.
    Captured/default geometry is checked separately by check_fit().
    """
    import maya.cmds as cmds
    import maya.api.OpenMaya as om
    from . import fit, scene_ops
    bus = fit.native_bus(scene_ops.scope_document())
    prefix = bus[:-len('NFRv1_RAW')]
    with (DATA / 'behavior.json').open(encoding='utf-8') as handle:
        model = json.load(handle)
    with gzip.open(DATA / 'validation_cases.json.gz', 'rt', encoding='utf-8') as handle:
        case_data = json.load(handle)
    cases = case_data['cases'] if limit is None else case_data['cases'][:int(limit)]
    if not cases:
        raise ValueError('Choose at least one behavior test pose')
    plugs, offsets = [], {}
    for row in model['outputs']:
        full = prefix + row['destination']
        selection = om.MSelectionList()
        selection.add(full)
        plugs.append(selection.getPlug(0))
        if row['dof'] < 3:
            joint = full.split('.', 1)[0]
            writer = fit.translation_writer(joint, 'XYZ'[row['dof']])
            if writer['kind'] != 'native_constant':
                raise ValueError('Behavior check expects a connected native translation: ' + full)
            matrix = fit.flat(cmds.getAttr(writer['plug']))
            offset = matrix[writer['cell']] - row['neutral']
            if not math.isfinite(offset):
                raise ValueError('Non-finite neutral translation offset: ' + full)
            offsets[row['destination']] = offset
    saved = []
    for index in range(model['raw_count']):
        destination = bus + '.value[' + str(index) + ']'
        incoming = fit.sources(destination)
        if len(incoming) > 1 or cmds.getAttr(destination, lock=True):
            raise ValueError('Raw input cannot be temporarily tested: ' + destination)
        value = cmds.getAttr(destination)
        if not math.isfinite(value):
            raise ValueError('Non-finite raw input: ' + destination)
        saved.append((destination, incoming[0] if incoming else None, value))
    maxima = {'translation_cm': 0., 'rotation_degrees': 0., 'scale': 0.}
    worst = dict.fromkeys(maxima)
    keys = ['translation_cm'] * 3 + ['rotation_degrees'] * 3 + ['scale'] * 3
    started = time.monotonic()
    undo_enabled = cmds.undoInfo(query=True, state=True)
    disconnected, suspended = [], False
    restore_errors = []
    try:
        # Preserve the artist's undo queue; temporary test inputs must not
        # create hundreds of editable pose operations in that queue.
        cmds.undoInfo(stateWithoutFlush=False)
        for destination, source, value in saved:
            if source:
                cmds.disconnectAttr(source, destination)
            disconnected.append((destination, source, value))
        cmds.refresh(suspend=True)
        suspended = True
        for index, case in enumerate(cases):
            if progress and progress(index, len(cases), 'Check pose: ' + case['name']) is False:
                from .scene_adapter import Cancelled
                raise Cancelled('Behavior check cancelled; original raw inputs were restored.')
            for (destination, _, _), value in zip(saved, case['raw']):
                cmds.setAttr(destination, value)
            expected = adjusted_reference(model['outputs'], case['expected'], offsets)
            for row, plug, reference in zip(model['outputs'], plugs, expected):
                actual = _read_channel(plug, row['dof'])
                if not math.isfinite(actual):
                    raise ValueError('Non-finite output in ' + case['name'] + ': ' + row['destination'])
                error = abs(actual - reference)
                key = keys[row['dof']]
                if error > maxima[key]:
                    maxima[key] = error
                    worst[key] = {'case': case['name'], 'channel': prefix + row['destination'],
                                  'actual': actual, 'expected': reference}
    finally:
        for destination, source, value in disconnected:
            try:
                cmds.setAttr(destination, value)
                if source:
                    cmds.connectAttr(source, destination, force=True)
            except Exception as exc:
                restore_errors.append(destination + ': ' + str(exc))
        try:
            if suspended:
                cmds.refresh(suspend=False)
                cmds.refresh(force=True)
        finally:
            cmds.undoInfo(stateWithoutFlush=undo_enabled)
        if restore_errors:
            raise RuntimeError('Behavior check could not restore raw inputs:\n' + '\n'.join(restore_errors))
    tolerances = {'translation_cm': .006, 'rotation_degrees': .025, 'scale': 1e-5}
    return {'schema': 'facialSystemBehaviorCheck', 'version': 1,
            'created_utc': core.utc_now(), 'cases': len(cases), 'joint_channels': len(plugs),
            'seconds': time.monotonic() - started, 'maximum_errors': maxima,
            'tolerances': tolerances, 'worst': worst,
            'translation_reference': 'Original ROM plus current native neutral translation offsets',
            'neutral_translation_offsets_cm': offsets,
            'passed': all(maxima[key] <= tolerances[key] for key in maxima),
            'scope': 'Raw input to local joint channels; GUI, mesh playback, and fitted shape need separate review.'}


def check_fit(document, mapping, install_mesh=True, reset=False):
    from . import fit, scene_adapter as adapter
    plan = fit.prepare(document, mapping, install_mesh=install_mesh, reset=reset, for_apply=False)
    joint_error, mesh_error, linear_error = 0., 0., 0.
    for job in plan['joints']:
        joint_error = max(joint_error, core.distance2(fit.world_position(job['name']), job['position_cm']) ** .5)
    for row in document['joints']:
        saved = row.get('default_world_matrix')
        if saved:
            state = fit.rotation_state(adapter.resolve(row['joint'], 'joint'))
            linear_error = max(linear_error, max(abs(a - saved[index]) for a, index in
                                                zip(state['world_linear'], (0, 1, 2, 4, 5, 6, 8, 9, 10))))
    for key, mesh in document['meshes'].items():
        source = adapter.mesh_path(adapter.resolve(mesh['identity']))
        expected = mesh['default_positions_cm']
        if install_mesh and not reset and mapping.get(key, '').strip():
            expected = fit.points(adapter.mesh_path(mapping[key]))
        actual = fit.points(source)
        if len(expected) != len(actual):
            raise ValueError('Mesh vertex count changed while checking the fit')
        mesh_error = max(mesh_error, max((core.distance2(a, b) ** .5 for a, b in zip(actual, expected)), default=0.))
    return {'schema': 'facialSystemFitCheck', 'version': 1, 'created_utc': core.utc_now(),
            'joint_count': len(plan['joints']), 'mesh_count': len(document['meshes']),
            'maximum_joint_position_error_cm': joint_error,
            'maximum_mesh_position_error_cm': mesh_error,
            'maximum_world_linear_matrix_error': linear_error,
            'install_mesh': bool(install_mesh), 'reset_to_template': bool(reset),
            'passed': joint_error <= .0001 and mesh_error <= .002 and linear_error <= 1e-5}
