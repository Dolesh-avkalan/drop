# Runs inside Blender (headless):
#   blender -b scene/hornbill_v14.blend -P render.py -- START END OUTDIR [--check]
# Points every missing texture / linked asset / cache at ./assets, sets the
# final render settings (720x1280, 96 samples, GPU) and renders START..END.
import bpy, os, sys

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
start, end, outdir = int(argv[0]), int(argv[1]), os.path.abspath(argv[2])
check = '--check' in argv
here = os.path.dirname(os.path.abspath(__file__))
assets = os.path.join(here, 'assets')

index = {}
for root, _, files in os.walk(assets):
    for f in files:
        index.setdefault(f.lower(), os.path.join(root, f))

def base(p):
    return p.replace('\\', '/').split('/')[-1].lower()

missing = []
for lib in bpy.data.libraries:
    p = bpy.path.abspath(lib.filepath)
    if not os.path.exists(p):
        if base(p) in index:
            lib.filepath = index[base(p)]
            lib.reload()
        else:
            missing.append(('library', lib.filepath))
for coll, kind in ((bpy.data.images, 'image'), (bpy.data.cache_files, 'cache'), (bpy.data.sounds, 'sound')):
    for d in coll:
        if d.library or not d.filepath or getattr(d, 'packed_file', None):
            continue
        if kind == 'image' and d.source not in ('FILE', 'SEQUENCE', 'TILED'):
            continue
        p = bpy.path.abspath(d.filepath)
        if os.path.exists(p):
            continue
        if base(p) in index:
            d.filepath = index[base(p)]
            if kind == 'image':
                d.reload()
        elif d.users:
            missing.append((kind, d.filepath))
print('HH missing files:', missing if missing else 'none')

s = bpy.context.scene
r = s.render
r.resolution_x, r.resolution_y, r.resolution_percentage = 720, 1280, 100
r.use_persistent_data = True
r.image_settings.file_format = 'PNG'
r.filepath = os.path.join(outdir, 'f_')
r.use_overwrite = False
r.use_placeholder = False
s.cycles.samples = 96
s.frame_start, s.frame_end = start, end

prefs = bpy.context.preferences.addons['cycles'].preferences
gpu = None
for t in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL'):
    try:
        prefs.compute_device_type = t
        prefs.refresh_devices()
    except Exception:
        continue
    devs = [d for d in prefs.devices if d.type == t]
    if devs:
        for d in prefs.devices:
            d.use = d.type == t
        gpu = t
        break
s.cycles.device = 'GPU' if gpu else 'CPU'
print('HH device:', gpu or 'CPU', [d.name for d in prefs.devices if d.use])

if not check:
    bpy.ops.render.render(animation=True)
