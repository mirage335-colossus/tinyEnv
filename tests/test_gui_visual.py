"""Image metric fixtures require no display, toolkit, or downloaded captures."""
import copy
import importlib.util
from pathlib import Path
import unittest
import subprocess
import sys
import os
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gui_visual', ROOT / 'gui/tests/visual_test.py')
subject = importlib.util.module_from_spec(spec); spec.loader.exec_module(subject)


class GuiVisualTests(unittest.TestCase):
    def test_assertion_disabled_interpreter_cannot_qualify_captures(self):
        for option in ('-O', '-OO'):
            with self.subTest(option=option):
                result = subprocess.run([sys.executable, '-B', option,
                    str(ROOT / 'gui/tests/visual_test.py'), '--help'],
                    capture_output=True, text=True, timeout=10)
                self.assertNotEqual(0, result.returncode)
                self.assertIn('requires active Python assertions', result.stderr)

    def test_capture_unit_scale_is_confined_to_child_environment(self):
        with mock.patch.dict(os.environ, {'REV_SCALE': '1.25', 'GDK_SCALE': '2'}):
            child = subject.capture_environment(Path('capture output'))
            self.assertEqual('1', child['REV_SCALE'])
            self.assertEqual('2', child['GDK_SCALE'])
            self.assertEqual('capture output', child['FOUNDATION_GUI_CAPTURE_DIR'])
            self.assertEqual('1.25', os.environ['REV_SCALE'])
        image, view = self.fixture()
        # A scaled physical image cannot pass as the common logical viewport.
        with self.assertRaisesRegex(AssertionError, 'capture viewport differs'):
            subject.inspect((160, 90, bytes(160 * 90 * 3)), view)

    def fixture(self, rendering='gray', shift=0, *, enabled=False, tone=0):
        palette = {'background': [240, 242, 246], 'surface': [248, 248, 248],
                   'disabled': [224, 224, 224], 'text': [32, 32, 32],
                   'muted': [96, 96, 96], 'accent': [40, 93, 164],
                   'error': [170, 36, 48], 'border': [145, 156, 174]}
        view = {'width': 128, 'height': 72, 'palette': palette, 'widgets': [
            {'bounds': [16, 16, 96, 36], 'visible': True, 'enabled': enabled,
             'kind': 2, 'key': {'id': 'fixture.button'}, 'text': '', 'label': 'ABCDE',
             'placeholder': '', 'records': [], 'font': {'tone': tone}}]}
        pixels = bytearray(palette['background'] * (128 * 72))
        def paint(x, y, rgb):
            offset = (y * 128 + x) * 3; pixels[offset:offset + 3] = bytes(rgb)
        for y in range(16, 52):
            for x in range(16, 112):
                paint(x, y, palette['border'] if x in (16, 111) or y in (16, 51)
                      else palette['surface' if enabled else 'disabled'])
        background = palette['surface' if enabled else 'disabled']
        foreground = palette[('text', 'muted', 'accent', 'error')[tone] if enabled else 'muted']
        for glyph in range(5):
            for y in range(12):
                for x in range(4):
                    anchor = x in (0, 3) and y in (0, 11)
                    alpha = 1 if anchor or rendering == 'opaque' else (0.1 if rendering == 'faint' else 2 / 3)
                    rgb = [round(b + alpha * (f - b)) for b, f in zip(background, foreground)]
                    if rendering == 'subpixel' and not anchor:
                        rgb = [background[c] if c == (x + y + glyph) % 3 else foreground[c] for c in range(3)]
                    if rendering == 'missing' or (rendering == 'clipped' and glyph >= 2):
                        continue
                    paint(24 + glyph * 9 + x + shift, 24 + y, rgb)
        if rendering == 'heavy':
            for y in range(24, 36):
                for x in range(24, 64): paint(x, y, foreground)
        return (128, 72, bytes(pixels)), view

    def boxes(self, rendering='gray', shift=0):
        image, view = self.fixture(rendering, shift)
        return subject.inspect(image, view)['fixture.button']

    def test_equivalent_rgb_antialiasing_preserves_ink(self):
        expected, actual = self.boxes(), self.boxes('subpixel')
        self.assertEqual(expected[:4], actual[:4])
        self.assertAlmostEqual(1, actual[4] / expected[4], delta=0.01)
        subject.compare_text(actual, expected, 'fixture.button')

    def test_every_declared_enabled_tone_has_visible_opaque_text(self):
        for tone in range(4):
            with self.subTest(tone=tone):
                image, view = self.fixture('opaque', enabled=True, tone=tone)
                box = subject.inspect(image, view)['fixture.button']
                self.assertEqual([24, 24, 63, 35], box[:4])
                self.assertAlmostEqual(240, box[4])

    def test_faint_text_with_identical_bounds_is_rejected(self):
        expected, actual = self.boxes(), self.boxes('faint')
        self.assertEqual(expected[:4], actual[:4])
        self.assertLess(actual[4] / expected[4], 0.45)
        with self.assertRaisesRegex(AssertionError, 'text coverage differs'):
            subject.compare_text(actual, expected, 'fixture.button')

    def test_missing_text_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'missing visible text'):
            self.boxes('missing')

    def test_clipped_text_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'text horizontal extent differs'):
            subject.compare_text(self.boxes('clipped'), self.boxes(), 'fixture.button')

    def test_moved_text_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'text horizontal extent differs'):
            subject.compare_text(self.boxes(shift=10), self.boxes(), 'fixture.button')

    def test_excessive_ink_with_identical_bounds_is_rejected(self):
        expected, actual = self.boxes(), self.boxes('heavy')
        self.assertEqual(expected[:4], actual[:4])
        self.assertGreater(actual[4] / expected[4], 2.2)
        with self.assertRaisesRegex(AssertionError, 'text coverage differs'):
            subject.compare_text(actual, expected, 'fixture.button')

    def test_palette_viewport_and_control_geometry_remain_checked(self):
        image, view = self.fixture()
        pixels = bytearray(image[2]); offset = (26 * 128 + 102) * 3
        pixels[offset:offset + 3] = bytes(view['palette']['surface'])
        with self.assertRaisesRegex(AssertionError, 'wrong shared fill'):
            subject.inspect((128, 72, bytes(pixels)), view)
        shifted = copy.deepcopy(view); shifted['widgets'][0]['bounds'][0] += 10
        shifted['widgets'][0]['bounds'][2] -= 10
        with self.assertRaisesRegex(AssertionError, 'missing or shifted left border'):
            subject.inspect(image, shifted)
        resized = copy.deepcopy(view); resized['width'] += 1
        with self.assertRaisesRegex(AssertionError, 'capture viewport differs'):
            subject.inspect(image, resized)


if __name__ == '__main__':
    unittest.main()
