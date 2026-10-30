#!/usr/bin/env python3
"""Hornbill render helper: renders frames from the end of the film backwards,
in small chunks, and pushes each chunk to this repo.

    python go.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe"

control.json (updated by the studio side) says where to stop: frames below
`stop_below` are being rendered on the studio PC.
"""
import argparse, glob, hashlib, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, 'scene', 'hornbill_v14.blend')
FRAMES = os.path.join(HERE, 'frames')

def sh(*cmd, check=True):
    print('$', ' '.join(cmd), flush=True)
    return subprocess.run(cmd, cwd=HERE, check=check)

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()

def join_scene():
    want = open(os.path.join(HERE, 'scene', 'SHA256')).read().split()[0]
    if os.path.exists(SCENE) and sha256(SCENE) == want:
        return
    parts = sorted(glob.glob(SCENE + '.part*'))
    with open(SCENE, 'wb') as out:
        for p in parts:
            with open(p, 'rb') as f:
                shutil.copyfileobj(f, out)
    got = sha256(SCENE)
    if got != want:
        sys.exit(f'scene checksum mismatch: {got} != {want}  (git pull again?)')
    print('scene joined OK', flush=True)

def pull():
    for i in range(5):
        if sh('git', 'pull', '--rebase', '-q', check=False).returncode == 0:
            return
        time.sleep(5 * (i + 1))

def push(msg):
    sh('git', 'add', 'frames')
    if sh('git', 'commit', '-q', '-m', msg, check=False).returncode != 0:
        return
    for i in range(6):
        if sh('git', 'push', '-q', check=False).returncode == 0:
            return
        pull()
        time.sleep(5 * (i + 1))
    sys.exit('git push keeps failing: check that this PC can push to the repo')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--blender', default=shutil.which('blender') or 'blender')
    ap.add_argument('--chunk', type=int, default=10)
    a = ap.parse_args()
    os.makedirs(FRAMES, exist_ok=True)
    pull()
    join_scene()
    sh(a.blender, '-b', SCENE, '-P', os.path.join(HERE, 'render.py'), '--', '1', '1', FRAMES, '--check')
    while True:
        pull()
        ctl = json.load(open(os.path.join(HERE, 'control.json')))
        if ctl.get('stop'):
            print('control.json says stop', flush=True); break
        done = {int(os.path.basename(p)[2:6]) for p in glob.glob(os.path.join(FRAMES, 'f_*.png'))}
        todo = [f for f in range(ctl['end'], ctl['stop_below'] - 1, -1) if f not in done]
        if not todo:
            print('all assigned frames are done', flush=True); break
        hi = todo[0]; lo = hi
        while lo - 1 >= ctl['stop_below'] and lo - 1 not in done and hi - (lo - 1) < a.chunk:
            lo -= 1
        t = time.time()
        sh(a.blender, '-b', SCENE, '-P', os.path.join(HERE, 'render.py'), '--', str(lo), str(hi), FRAMES)
        print(f'frames {lo}-{hi}: {(time.time() - t) / (hi - lo + 1):.1f} s/frame', flush=True)
        push(f'hornbill frames {lo}-{hi}')
    print('DONE', flush=True)

if __name__ == '__main__':
    main()
