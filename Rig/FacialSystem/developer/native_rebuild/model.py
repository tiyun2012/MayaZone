"""Portable facial behavior, scoped by connected scene outputs and joint names."""
import collections
import math
import re


def build(dna, manifest, rbf_details):
    definition, behavior = dna['definition'], dna['behavior']
    if dna['descriptor']['translationUnit'] != 0 or dna['descriptor']['rotationUnit'] != 0:
        raise ValueError('This version expects centimeter/degree DNA')
    if any(tuple(x.values()) != (0, 0, 0) for x in dna['joint_metadata']['jointRepresentations']):
        raise ValueError('Non-Euler joint representations need an explicit implementation')
    names = {name: i for i, name in enumerate(definition['jointNames'])}
    raw_count = len(definition['rawControlNames'])
    psd_count = behavior['controls']['psdCount']
    rbf_count = len(dna['rbf_ext']['poseControlNames'])
    outputs = []
    for link in manifest['evaluator']['outgoing_connections']:
        match = re.search(r'jnt(Translation|Rotation|Scale)Outputs\[(\d+)\]', link['source'])
        if not match:
            continue
        node, attr = link['destination'].rsplit('.', 1)
        if node not in names:
            raise ValueError(f'Connected joint absent from DNA: {node}')
        kind = match[1]
        dof = 'xyz'.index(attr[-1]) + {'Translation': 0, 'Rotation': 3, 'Scale': 6}[kind]
        ji = names[node]
        neutral = definition['neutralJointTranslations'][['xs', 'ys', 'zs'][dof]][ji] if dof < 3 else (1.0 if dof >= 6 else 0.0)
        outputs.append({'destination': link['destination'], 'joint_index': ji, 'dof': dof,
                        'row': ji * 9 + dof, 'neutral': neutral, 'terms': []})
    output_by_row = {entry['row']: entry for entry in outputs}
    if len(output_by_row) != len(outputs):
        raise ValueError('Duplicate driven output channel')
    seen = set()
    for group in behavior['joints']['jointGroups']:
        cols = group['inputIndices']
        for r, index in enumerate(group['outputIndices']):
            if index not in output_by_row:
                continue
            if index in seen:
                raise ValueError('Overlapping joint matrix rows are not supported')
            seen.add(index)
            output_by_row[index]['terms'] = [[c, v] for c, v in zip(cols, group['values'][r * len(cols):(r + 1) * len(cols)]) if v != 0.0]
    outputs.sort(key=lambda entry: entry['row'])
    psds = {}
    table = behavior['controls']['psds']
    for row, col, weight in zip(table['rows'], table['columns'], table['values']):
        entry = psds.setdefault(row, {'output': row, 'inputs': [], 'weight': 1.0})
        entry['inputs'].append(col)
        entry['weight'] *= weight
    if any(raw_count <= c < raw_count + psd_count for row in psds.values() for c in row['inputs']):
        raise ValueError('Recursive PSD dependency')
    solvers = []
    for si, solver in enumerate(dna['rbf']['solvers']):
        if solver['distanceMethod'] != 1 or solver['solverType'] != 1 or solver['functionType'] != 0:
            raise ValueError('This compiler currently supports the reference quaternion/Gaussian/interpolative RBF')
        count = len(solver['rawControlIndices'])
        targets = [solver['rawControlValues'][i:i + count] for i in range(0, len(solver['rawControlValues']), count)]
        poses = []
        for index in solver['poseIndices']:
            p = dict(dna['rbf_ext']['poses'][index])
            p['scale'] = dna['rbf']['poses'][index]['scale']
            p['name'] = dna['rbf']['poses'][index]['name']
            poses.append(p)
        solvers.append({'name': solver['name'], 'input_indices': solver['rawControlIndices'],
                        'targets': targets, 'poses': poses, 'radius': rbf_details[si]['radius'],
                        'coefficients': rbf_details[si]['coefficients'],
                        'normalize_method': solver['normalizeMethod'], 'threshold': solver['weightThreshold']})
    raw_sources = manifest['evaluator']['raw_control_inputs']
    for source in raw_sources:
        if definition['rawControlNames'][source['index']] != source['source']:
            raise ValueError('Raw control name/index mismatch')
    map_links = []
    for link in manifest['evaluator']['outgoing_connections']:
        match = re.search(r'\.amOutputs\[(\d+)\]', link['source'])
        if match:
            map_links.append({'index': int(match[1]), 'destination': link['destination']})
    return {'format': 'native_facial_v1', 'source_scene_sha256': manifest['source']['sha256'],
            'source_solver': manifest['evaluator']['name'], 'raw_count': raw_count,
            'psd_count': psd_count, 'rbf_count': rbf_count,
            'raw_names': definition['rawControlNames'], 'raw_sources': raw_sources,
            'psds': sorted(psds.values(), key=lambda entry: entry['output']), 'rbf_solvers': solvers,
            'outputs': outputs, 'animated_maps': behavior['animatedMaps']['conditionals'],
            'animated_map_links': map_links, 'animated_map_count': len(definition['animatedMapNames']),
            'driver_joints': ['neck_01', 'neck_02', 'head'],
            'scope_joint_count': len({o['destination'].rsplit('.', 1)[0] for o in outputs})}


def conditional(table, signals, count):
    result = [0.0] * count
    row = 0
    while row < len(table['inputIndices']):
        i, o = table['inputIndices'][row], table['outputIndices'][row]
        end = row + 1
        while end < len(table['inputIndices']) and table['inputIndices'][end] == i and table['outputIndices'][end] == o:
            end += 1
        value = signals[i]
        for k in range(row, end):
            if table['fromValues'][k] <= value <= table['toValues'][k]:
                result[o] += table['slopeValues'][k] * value + table['cutValues'][k]
                break
        row = end
    return [min(1.0, max(0.0, value)) for value in result]


def evaluate(model, raw):
    if len(raw) != model['raw_count']:
        raise ValueError('Wrong raw control count')
    signals = list(raw) + [0.0] * (model['psd_count'] + model['rbf_count'])
    for solver in model['rbf_solvers']:
        source = [signals[i] for i in solver['input_indices']]
        kernels = []
        for target in solver['targets']:
            squared_distance = 0.0
            for offset in range(0, len(source), 4):
                dot = sum(source[offset + k] * target[offset + k] for k in range(4))
                dot2 = dot * dot
                arc = 0.0 if dot2 > 1.0 else math.acos(max(-1.0, min(1.0, 2.0 * dot2 - 1.0)))
                squared_distance += arc * arc
            kernels.append(math.exp(-math.sqrt(squared_distance) / (solver['radius'] * solver['radius'])))
        weights = [min(1.0, max(0.0, sum(c * w for c, w in zip(row, kernels)))) for row in solver['coefficients']]
        total = sum(weights)
        ratio = 1.0 / total if total > 1.0 or (solver['normalize_method'] == 1 and total > 0.0) else 1.0
        for pose in solver['poses']:
            for index in pose['outputControlIndices']:
                signals[index] = 0.0
        for pose, weight in zip(solver['poses'], weights):
            weight *= ratio * pose['scale']
            if weight <= solver['threshold']:
                continue
            for index in pose['inputControlIndices']:
                weight *= signals[index]
            for index, factor in zip(pose['outputControlIndices'], pose['outputControlWeights']):
                signals[index] += factor * weight
    for psd in model['psds']:
        weight = psd['weight']
        for i in psd['inputs']:
            weight *= max(0.0, min(1.0, signals[i]))
        signals[psd['output']] = min(1.0, weight)
    values = [output['neutral'] + sum(signals[index] * value for index, value in output['terms']) for output in model['outputs']]
    maps = conditional(model['animated_maps'], signals, model['animated_map_count'])
    return values, maps, signals
