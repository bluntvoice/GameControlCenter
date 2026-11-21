"""Convert ProfileStore catalogue entries and their native JSON to versioned Android data."""
import argparse
import hashlib
import json
import math
from pathlib import Path

BUTTONS = dict(zip(
    ('1', '2', '3', '4', '5', '6', '7', '8', '9', '0', 'Minus', 'Equal',
     'BracketLeft', 'BracketRight', 'Return', 'Backspace'),
    ('A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'UP', 'DOWN', 'LEFT', 'RIGHT',
     'LS', 'RS', 'START', 'SELECT'),
))
CONTROL_NAMES = {'UP': '↑', 'DOWN': '↓', 'LEFT': '←', 'RIGHT': '→',
                 'START': 'Start', 'SELECT': 'Back'}
SCRIPTS = {'mapi.holdpress();': 'hold',
           'if(mapi.isPress()){mapi.click();}': 'tap'}
MODES = {'hold': 'hold', 'once': 'tap', 'repeat': 'repeat'}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def number(value, minimum, maximum):
    if type(value) not in (float, int) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'Expected number between {minimum} and {maximum}')
    return value


def point(value):
    return {axis: number(value[axis], 0, 1) for axis in ('x', 'y')}


def mapping(node, controls, settings):
    kind = node['type']
    if kind == 'KMT_STEER_WHEEL':
        # The reference frame aspect ratio is part of the Windows node generation.
        extent = {}
        for direction, dimension in (('left', 2608), ('right', 2608), ('up', 1200), ('down', 1200)):
            extent[direction] = number(node[direction + 'Offset'], 0.001, 0.5) * dimension
        return {'id': 'left', 'action': 'joystick', 'point': point(node['centerPos']),
                'rangeAt1200': extent}
    if kind == 'KMT_CAMERA_MOVE':
        return {'id': 'right', 'action': 'camera', 'point': point(node['pos']),
                'speedScale': number(controls.get('右摇杆', {}).get('radius', 100), 10, 400) / 100}
    key = node.get('key', '')
    button = BUTTONS.get(key.removeprefix('Key_')) if key.startswith('Key_') else None
    if button is None:
        raise ValueError(f'No physical controller binding for {key or kind}')
    control = controls.get(CONTROL_NAMES.get(button, button), {})
    if kind == 'KMT_FREE_LOOK':
        return {'id': button, 'button': button, 'action': 'aim', 'point': point(node['startPos']),
                'radiusAt1200': number(control.get('radius', settings['skill_radius_px']), 10, 400)}
    if kind != 'KMT_SCRIPT':
        raise ValueError(f'Unknown native action {kind}')
    script = SCRIPTS.get(''.join(node['script'].split()))
    if script is None:
        raise ValueError('Script is outside the declaration whitelist')
    action = MODES[control['mode']] if 'mode' in control else script
    result = {'id': button, 'button': button, 'action': action, 'point': point(node['pos'])}
    if action == 'repeat':
        result['repeatHz'] = number(control.get('hz', 10), 1, 20)
    return result


def convert(entry, native_bytes, settings):
    native = json.loads(native_bytes.decode('utf-8-sig'))
    controls = {} if entry.get('legacy') else {c['name']: c for c in entry['controls']}
    result = {
        'schemaVersion': 1,
        'profileId': entry['id'],
        'revision': entry['revision'],
        'name': entry['name'],
        'gamePackage': 'com.netease.party',
        'orientation': 'landscape',
        'coordinateSystem': {'type': 'normalizedGameViewport', 'referenceHeight': 1200},
        'parameters': {'leftDeadzone': number(settings['left_deadzone'], 0, 0.4),
                       'rightDeadzone': number(settings['right_deadzone'], 0, 0.4),
                       'rightCurve': number(settings['right_curve'], 0.5, 3),
                       'cameraPxPerSecondAt1200': number(settings['camera_px_per_sec'], 50, 4000),
                       'tapMs': 50},
        'sourceSha256': hashlib.sha256(native_bytes).hexdigest(),
        'mappings': [],
        'unconverted': [],
    }
    seen = set()
    for index, node in enumerate(native['keyMapNodes']):
        try:
            item = mapping(node, controls, settings)
            if item['id'] in seen:
                raise ValueError('Controller binding is duplicated')
            seen.add(item['id'])
            result['mappings'].append(item)
        except (KeyError, TypeError, ValueError) as failure:
            result['unconverted'].append({'index': index, 'reason': str(failure), 'node': node})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('library', type=Path)
    parser.add_argument('settings', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('ids', nargs='+')
    args = parser.parse_args()
    library = read_json(args.library)
    if library.get('version') != 1:
        parser.error('Unsupported Windows catalogue version')
    profiles = {entry['id']: entry for entry in library['profiles']}
    settings = read_json(args.settings)
    for profile_id in args.ids:
        entry = profiles[profile_id]
        result = convert(entry, Path(entry['path']).read_bytes(), settings)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / f'{profile_id}.json').write_text(
            json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + '\n',
            encoding='utf-8',
        )
        print(f"{result['name']}: {len(result['mappings'])} converted, "
              f"{len(result['unconverted'])} unconverted, {result['sourceSha256']}")


if __name__ == '__main__':
    main()
