"""Deterministic, bounded motion planning. No application, file, or network access."""
import math
import copy
from validation import integer, keys, text

PROPERTIES = {'x', 'y', 'rotation', 'scaleX', 'scaleY', 'alpha', 'firstFrame'}
EASINGS = {'linear', 'ease_in', 'ease_out', 'ease_in_out', 'back_out', 'bounce_out'}


def number(value, low=-100000, high=100000):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Finite number outside allowed range')
    return value


def point(value):
    keys(value, ('x', 'y'))
    return {k: number(value[k]) for k in ('x', 'y')}


def bezier(curve, position):
    # Solve the x component. Using y(position) directly gives incorrect timing.
    x1, y1, x2, y2 = curve
    def component(t, a, b):
        return 3*(1-t)**2*t*a + 3*(1-t)*t*t*b + t**3
    lo, hi = 0.0, 1.0
    for _ in range(36):
        middle = (lo + hi) / 2
        if component(middle, x1, x2) < position: lo = middle
        else: hi = middle
    return component((lo + hi) / 2, y1, y2)


def ease(kind, t):
    if isinstance(kind, list): return bezier(kind, t)
    if kind == 'ease_in': return t*t
    if kind == 'ease_out': return 1-(1-t)**2
    if kind == 'ease_in_out': return t*t*(3-2*t)
    if kind == 'back_out':
        return 1 + 2.70158*(t-1)**3 + 1.70158*(t-1)**2
    if kind == 'bounce_out':
        if t < 1/2.75: return 7.5625*t*t
        if t < 2/2.75: t -= 1.5/2.75; return 7.5625*t*t+.75
        if t < 2.5/2.75: t -= 2.25/2.75; return 7.5625*t*t+.9375
        t -= 2.625/2.75; return 7.5625*t*t+.984375
    return t


def validate_tracks(tracks, step=2):
    integer(step, 1, 12)
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= 16:
        raise ValueError('Supply 1 to 16 tracks')
    identities = set()
    for index, track in enumerate(tracks):
        keys(track, ('layer', 'instance', 'keys'), ('pivot', 'parent', 'rotation_mode', 'playback', 'sync_to_timeline'))
        text(track['layer'], 128); text(track['instance'], 128)
        identity = track['layer'], track['instance']
        if identity in identities: raise ValueError('Duplicate target track')
        identities.add(identity)
        if 'pivot' in track: point(track['pivot'])
        if 'parent' in track: integer(track['parent'], 0, index-1)
        if track.get('rotation_mode', 'explicit') not in ('explicit', 'shortest'):
            raise ValueError('Invalid rotation mode')
        if track.get('playback','single frame') not in ('single frame','play once','loop'): raise ValueError('Invalid graphic playback')
        if type(track.get('sync_to_timeline',False)) is not bool: raise ValueError('sync_to_timeline must be boolean')
        if track.get('sync_to_timeline') and track.get('playback','single frame')=='single frame': raise ValueError('Timeline sync requires play once or loop')
        poses = track['keys']
        if not isinstance(poses, list) or not 1 <= len(poses) <= 64:
            raise ValueError('Supply 1 to 64 keys per track')
        previous = -1
        for pose in poses:
            keys(pose, ('frame', 'values'), ('interpolation', 'easing', 'path'))
            previous = integer(pose['frame'], previous+1, 9999)
            values = pose['values']
            if not isinstance(values, dict) or not values or set(values)-PROPERTIES:
                raise ValueError('Unsupported motion properties')
            for name, value in values.items():
                if name == 'firstFrame': integer(value, 0, 9999)
                else:
                    low, high = {'alpha': (0, 100), 'scaleX': (-100, 100), 'scaleY': (-100, 100)}.get(name, (-100000, 100000))
                    number(value, low, high)
            if pose.get('interpolation', 'interpolate') not in ('interpolate', 'hold'):
                raise ValueError('Invalid interpolation')
            curve = pose.get('easing', 'linear')
            if isinstance(curve, list):
                if len(curve) != 4: raise ValueError('Bezier needs four control coordinates')
                for n, value in enumerate(curve): number(value, 0 if n%2 == 0 else -4, 1 if n%2 == 0 else 5)
            elif not isinstance(curve, str) or curve not in EASINGS:
                raise ValueError('Unsupported easing')
            if 'path' in pose:
                if not isinstance(pose['path'], list) or len(pose['path']) != 2:
                    raise ValueError('Cubic motion path needs two control points')
                for control in pose['path']: point(control)
        if not {'x', 'y'} <= set(poses[0]['values']):
            raise ValueError('First pose must explicitly define x and y')
        if track.get('sync_to_timeline'):
            origin=poses[0]['values'].get('firstFrame',0)
            for pose in poses:
                if 'firstFrame' in pose['values'] and pose['values']['firstFrame']!=origin+pose['frame']-poses[0]['frame']:
                    raise ValueError('Synced graphic pose must follow the track timeline')
            integer(origin+poses[-1]['frame']-poses[0]['frame'],0,9999)
    return tracks


def expanded(track):
    values = dict(x=0., y=0., rotation=0., scaleX=1., scaleY=1., alpha=100., firstFrame=0)
    result = []
    for entry in track['keys']:
        values.update(entry['values'])
        result.append({**entry, 'values': dict(values)})
    return result


def evaluate(track, frame):
    poses = expanded(track)
    if frame <= poses[0]['frame']: return dict(poses[0]['values'])
    if frame >= poses[-1]['frame']: return dict(poses[-1]['values'])
    for left, right in zip(poses, poses[1:]):
        if frame == right['frame']: return dict(right['values'])
        if left['frame'] <= frame < right['frame']:
            if left.get('interpolation') == 'hold': return dict(left['values'])
            t = (frame-left['frame'])/(right['frame']-left['frame'])
            u = ease(left.get('easing', 'linear'), t)
            result = {}
            for name, value in left['values'].items():
                delta = right['values'][name]-value
                if name == 'firstFrame': result[name] = value; continue
                if name == 'rotation' and track.get('rotation_mode') == 'shortest':
                    delta = (delta+180)%360-180
                result[name] = value+delta*u
            if 'path' in left:
                for name in ('x', 'y'):
                    a, b = left['path']
                    result[name] = (1-u)**3*left['values'][name]+3*(1-u)**2*u*a[name]+3*(1-u)*u*u*b[name]+u**3*right['values'][name]
            result['alpha'] = max(0, min(100, result['alpha']))
            for name in ('scaleX', 'scaleY'): result[name] = max(-100, min(100, result[name]))
            return result
    raise ValueError('Cannot evaluate track')


def matrix(values, pivot):
    angle = math.radians(values['rotation'])
    a, b = math.cos(angle)*values['scaleX'], math.sin(angle)*values['scaleX']
    c, d = -math.sin(angle)*values['scaleY'], math.cos(angle)*values['scaleY']
    return dict(a=a, b=b, c=c, d=d, tx=values['x']-a*pivot['x']-c*pivot['y'], ty=values['y']-b*pivot['x']-d*pivot['y'])


def multiply(parent, child):
    return dict(a=parent['a']*child['a']+parent['c']*child['b'], b=parent['b']*child['a']+parent['d']*child['b'],
        c=parent['a']*child['c']+parent['c']*child['d'], d=parent['b']*child['c']+parent['d']*child['d'],
        tx=parent['a']*child['tx']+parent['c']*child['ty']+parent['tx'], ty=parent['b']*child['tx']+parent['d']*child['ty']+parent['ty'])


def world(tracks, index, frame):
    track = tracks[index]; value = evaluate(track, frame)
    transform = matrix(value, track.get('pivot', {'x': 0, 'y': 0}))
    if 'parent' in track:
        ancestor, alpha = world(tracks, track['parent'], frame)
        transform = multiply(ancestor, transform); value['alpha'] *= alpha/100
    return transform, value['alpha']


def compile_motion(tracks, step=2):
    validate_tracks(tracks, step)
    poses, summaries = [], []
    for index, track in enumerate(tracks):
        start, end = track['keys'][0]['frame'], track['keys'][-1]['frame']
        # Include exact keys even when they are off the sampling grid.
        frames = set(range(start, end+1, step)) | {p['frame'] for p in track['keys']}
        ancestor = track.get('parent')
        while ancestor is not None:
            frames.update(p['frame'] for p in tracks[ancestor]['keys'] if start <= p['frame'] <= end)
            ancestor = tracks[ancestor].get('parent')
        frames = sorted(frames)
        if len(poses)+len(frames) > 400: raise ValueError('Motion plan exceeds 400 baked poses; split into shorter inspected spans')
        previous = None; maximum_speed = 0
        for frame in frames:
            values = evaluate(track, frame); transform, alpha = world(tracks, index, frame)
            for value in transform.values(): number(value, -10000000, 10000000)
            if previous:
                maximum_speed = max(maximum_speed, math.hypot(transform['tx']-previous[1]['tx'], transform['ty']-previous[1]['ty'])/(frame-previous[0]))
            previous = frame, transform
            graphic_frame=track['keys'][0]['values'].get('firstFrame',0)+frame-start if track.get('sync_to_timeline') else values['firstFrame']
            poses.append(dict(layer=track['layer'], instance=track['instance'], frame=frame,
                matrix={k: round(v, 8) for k, v in transform.items()}, alpha=round(alpha, 6), firstFrame=graphic_frame,loop=track.get('playback','single frame')))
        summaries.append(dict(layer=track['layer'], instance=track['instance'], start_frame=start, end_frame=end,
            pose_count=len(frames), max_registration_speed_pixels_per_frame=round(maximum_speed, 4)))
    return dict(poses=poses, tracks=summaries, pose_count=len(poses), sampling_step=step,
        coordinate_system='Timeline coordinates; pivot is local to the symbol; parent transforms are baked into full affine matrices',
        interpolation='Explicit sampled keyframes, no Animate tween approximation; firstFrame is discrete')


def solve_two_bone(base, target, upper, lower, bend=1):
    base, target = point(base), point(target)
    number(upper, .01, 10000); number(lower, .01, 10000)
    if type(bend) is not int or bend not in (-1, 1): raise ValueError('Bend must be -1 or 1')
    dx, dy = target['x']-base['x'], target['y']-base['y']; distance = math.hypot(dx, dy)
    radius = max(abs(upper-lower)+1e-9, min(upper+lower-1e-9, distance))
    direction = math.atan2(dy, dx)
    shoulder = direction + bend*math.acos(max(-1, min(1, (upper*upper+radius*radius-lower*lower)/(2*upper*radius))))
    elbow = dict(x=base['x']+upper*math.cos(shoulder), y=base['y']+upper*math.sin(shoulder))
    achieved = dict(x=base['x']+radius*math.cos(direction), y=base['y']+radius*math.sin(direction))
    forearm = math.atan2(achieved['y']-elbow['y'], achieved['x']-elbow['x'])
    return dict(elbow=elbow, achieved_target=achieved, upper_rotation=math.degrees(shoulder),
        lower_world_rotation=math.degrees(forearm), lower_local_rotation=math.degrees(forearm-shoulder),
        target_error=math.hypot(target['x']-achieved['x'], target['y']-achieved['y']), reachable=abs(upper-lower) <= distance <= upper+lower)


def retime_motion(tracks, new_start, new_end):
    validate_tracks(tracks)
    integer(new_start,0,9999); integer(new_end,new_start,9999)
    start=min(t['keys'][0]['frame'] for t in tracks)
    end=max(t['keys'][-1]['frame'] for t in tracks)
    if end==start and new_end!=new_start: raise ValueError('A single instant cannot be stretched into a span')
    result=copy.deepcopy(tracks)
    for track in result:
        for key in track['keys']:
            key['frame']=new_start if end==start else new_start+int((key['frame']-start)*(new_end-new_start)/(end-start)+.5)
        if track.get('sync_to_timeline'):
            origin=track['keys'][0]['values'].get('firstFrame',0)
            for key in track['keys']:
                if 'firstFrame' in key['values']:key['values']['firstFrame']=origin+key['frame']-track['keys'][0]['frame']
    validate_tracks(result)
    return dict(tracks=result,source_start=start,source_end=end,new_start=new_start,new_end=new_end)
