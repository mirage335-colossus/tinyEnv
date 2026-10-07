#!/usr/bin/env python3
"""Compare real native captures against shared geometry and color declarations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib

if not __debug__:
    raise RuntimeError('visual qualification requires active Python assertions')

BACKENDS = ('framebuffer', 'fltk', 'rev')
SIZES = ((800, 640), (480, 360))


def read_ppm(path):
    header, dimensions, maximum, pixels = Path(path).read_bytes().split(b'\n', 3)
    width, height = map(int, dimensions.split())
    if header != b'P6' or maximum != b'255' or len(pixels) != width * height * 3:
        raise ValueError('invalid RGB capture')
    return width, height, pixels


def write_png(path, width, height, pixels):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    filtered = b''.join(b'\0' + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height))
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(filtered)) + chunk(b'IEND', b''))


def color(image, x, y):
    width, height, pixels = image
    if not 0 <= x < width or not 0 <= y < height:
        raise AssertionError('pixel probe is outside captured viewport')
    offset = (y * width + x) * 3
    return tuple(pixels[offset:offset + 3])


def near(left, right, tolerance=3):
    return max(abs(a - b) for a, b in zip(left, right)) <= tolerance


def ink_coverage(pixel, background, foreground):
    # Integrate RGB contrast: subpixel antialiasing can leave one channel light
    # even where the other two carry ink. Counting only fully dark pixels loses it.
    contrast = sum(background[c] - foreground[c] for c in range(3))
    assert contrast > 0, 'text foreground must contrast with the light surface'
    return max(0.0, min(1.0, sum(background[c] - pixel[c] for c in range(3)) / contrast))


def compare_text(actual, expected, identity):
    assert max(abs(actual[i] - expected[i]) for i in (0, 2)) <= 8, identity + ': text horizontal extent differs'
    assert max(abs(actual[i] - expected[i]) for i in (1, 3)) <= 8, identity + ': text vertical placement differs'
    assert 0.45 <= actual[4] / expected[4] <= 2.2, identity + ': text coverage differs'


def inspect(image, view):
    width, height, _ = image
    assert (width, height) == (view['width'], view['height']), (
        f"capture viewport differs: physical {width}x{height}, logical {view['width']}x{view['height']}")
    palette = view['palette']; assert near(color(image, 4, 4), palette['background']), 'wrong viewport surface'
    text_boxes = {}
    for widget in view['widgets']:
        x, y, w, h = map(round, widget['bounds']); bottom = min(y + h, height)
        if not widget['visible'] or y >= height or w < 20 or bottom - y < 10:
            continue
        kind = widget['kind']; identity = widget['key']['id']
        fill = palette['disabled'] if not widget['enabled'] else palette['surface']
        if kind in (0, 2, 5, 6, 8):
            assert near(color(image, min(width - 5, x + w - 10), y + min(10, bottom - y - 3)), fill), identity + ': wrong shared fill'
            # A one-pixel stroke may land on either neighbor after native rounding.
            probe_x = min(width - 5, x + w - 12)
            assert any(near(color(image, probe_x, yy), palette['border']) for yy in range(max(0, y - 1), min(height, y + 2))), identity + ': missing or shifted top border'
            if kind != 0:
                probe_y = y + min(12, bottom - y - 3)
                assert any(near(color(image, xx, probe_y), palette['border']) for xx in range(max(0, x - 1), min(width, x + 2))), identity + ': missing or shifted left border'
        if kind == 0:
            continue
        text = widget['text'] or widget['label'] or widget['placeholder']
        if kind == 6:
            text = widget['records'][0]['text'] if widget['records'] else widget['placeholder']
        if not text:
            continue
        margin = 0 if kind == 1 else 3
        background = fill if kind in (2, 5, 6, 8) else palette['surface']
        foreground = palette[('text', 'muted', 'accent', 'error')[widget['font']['tone']]]
        if not widget['enabled'] or (not widget['text'] and not widget['label'] and kind != 6):
            foreground = palette['muted']
        samples = [(xx, yy, ink_coverage(color(image, xx, yy), background, foreground))
                   for yy in range(y + margin, min(bottom - margin, y + 30))
                   for xx in range(x + margin, min(width - margin, x + w - margin))]
        # Quarter-opacity edges count as visible; weaker antialiasing fringes do
        # not expand the bounds. This is relative to the declared text contrast,
        # so legitimate accent/error colors receive the same visibility rule.
        points = [(xx, yy) for xx, yy, opacity in samples if opacity >= 0.25]
        assert len(points) >= max(8, len(text) * 2), identity + ': missing visible text'
        coverage = sum(opacity for _, _, opacity in samples)
        # Four visible extents followed by equivalent opaque RGB pixels.
        text_boxes[identity] = [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points), coverage]
    return text_boxes


def negative_checks(image, view):
    """Prove these assertions detect erased text, wrong fill and moved controls."""
    import copy
    failures = []
    heading = next(widget for widget in view['widgets'] if widget['kind'] == 1)
    x, y, w, h = map(round, heading['bounds'])
    pixels = bytearray(image[2])
    for yy in range(y, min(y + h, image[1])):
        for xx in range(x, min(x + w, image[0])):
            offset = (yy * image[0] + xx) * 3
            pixels[offset:offset + 3] = bytes(view['palette']['surface'])
    disabled = next(widget for widget in view['widgets'] if not widget['enabled'])
    dx, dy, dw, _ = map(round, disabled['bounds'])
    wrong_fill = bytearray(image[2]); offset = ((dy + 10) * image[0] + dx + dw - 10) * 3
    wrong_fill[offset:offset + 3] = bytes(view['palette']['surface'])
    moved = copy.deepcopy(view)
    next(widget for widget in moved['widgets'] if widget['kind'] == 5)['bounds'][0] += 10
    for name, candidate, declarations in [
        ('erased label', (image[0], image[1], bytes(pixels)), view),
        ('wrong disabled fill', (image[0], image[1], bytes(wrong_fill)), view),
        ('shifted control', image, moved),
    ]:
        try:
            inspect(candidate, declarations)
        except AssertionError:
            failures.append(name)
        else:
            raise AssertionError('visual comparator accepted ' + name)
    return failures


def compare(directory):
    directory = Path(directory); result = {}
    for width, height in SIZES:
        views = {name: json.loads((directory / f'{name}-{width}.json').read_text()) for name in BACKENDS}
        baseline = views['framebuffer']
        assert all(view == baseline for view in views.values()), 'native shared declarations differ'
        images = {name: read_ppm(directory / f'{name}-{width}.ppm') for name in BACKENDS}
        boxes = {name: inspect(image, views[name]) for name, image in images.items()}
        negative_checks(images['framebuffer'], baseline)
        for name in BACKENDS:
            assert boxes[name].keys() == boxes['framebuffer'].keys(), 'visible control set differs'
            for identity, expected in boxes['framebuffer'].items():
                actual = boxes[name][identity]
                compare_text(actual, expected, identity)
            error = sum(abs(a - b) for a, b in zip(images[name][2], images['framebuffer'][2])) / len(images[name][2])
            assert error < 4.0, name + ': excessive overall rendering difference'
            result[f'{name}-{width}'] = {'mean_channel_error': round(error, 5), 'text_bounds': boxes[name], 'text_coverage_metric': 'normalized-rgb-ink', 'capture_sha256': hashlib.sha256((directory / f'{name}-{width}.ppm').read_bytes()).hexdigest()}
            write_png(directory / f'{name}-{width}.png', *images[name])
    return result


def capture_environment(directory):
    # Pixel comparisons use one physical pixel per logical unit. The standalone
    # native host fixture still tests the display's actual scale independently.
    # REV_SCALE is the retained Linux toolkit's documented scale input; it is
    # confined to these capture subprocesses and never changes the parent host.
    return dict(os.environ, FOUNDATION_GUI_CAPTURE_DIR=str(directory), REV_SCALE='1')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parity', type=Path, required=True); parser.add_argument('--fltk', type=Path, required=True); parser.add_argument('--rev', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='run-', dir=args.output)).resolve()
    env = capture_environment(directory)
    binaries = {}
    for name in ['parity', 'fltk', 'rev']:
        executable = getattr(args, name).resolve(); binaries[name] = hashlib.sha256(executable.read_bytes()).hexdigest()
        completed = subprocess.run([str(executable)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
        (directory / f'{name}.log').write_bytes(completed.stdout)
        if completed.returncode:
            raise RuntimeError(name + ' native fixture failed: ' + completed.stdout.decode(errors='replace'))
    result = {'schema_version': 1, 'binary_sha256': binaries, 'viewports': list(SIZES), 'capture_scale': 1, 'captures': compare(directory), 'limits': 'Logical geometry and shared palette checks with bounded native font raster tolerance; physical display and assistive-device qualification separate.'}
    (directory / 'qualification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'evidence': str(directory), 'captures': len(result['captures']), 'result': 'passed'}))

if __name__ == '__main__':
    main()
