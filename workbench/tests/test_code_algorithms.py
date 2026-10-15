"""Offline acceptance of user-authored signal, vision and bit algorithms.

All image inputs are synthetic numeric grids. The finder-pattern and
Reed-Solomon cases establish useful QR primitives, not a complete QR reader,
image-file decoding, perspective recovery or error correction.
"""

import copy
import math
import unittest

from workbench.services import calculations


BIQUAD = """
def biquad(samples, b0, b1, b2, a1, a2):
    output = [0.0 for i in range(len(samples))]
    x1 = 0.0
    x2 = 0.0
    y1 = 0.0
    y2 = 0.0
    for i in range(len(samples)):
        x = samples[i]
        y = b0*x + b1*x1 + b2*x2 - a1*y1 - a2*y2
        output[i] = y
        x2 = x1
        x1 = x
        y2 = y1
        y1 = y
    return output
biquad(data, 0.0625, 0.125, 0.0625, -1.0, 0.25)
"""


VISION = """
def smooth(image):
    height = len(image)
    width = len(image[0])
    output = [[0.0 for c in range(width)] for r in range(height)]
    for r in range(1, height-1):
        for c in range(1, width-1):
            total = 0.0
            for dr in range(-1, 2):
                for dc in range(-1, 2):
                    total += image[r+dr][c+dc]
            output[r][c] = total / 9
    return output
def threshold(image, level):
    height = len(image)
    width = len(image[0])
    mask = [[False for c in range(width)] for r in range(height)]
    for r in range(height):
        for c in range(width):
            mask[r][c] = image[r][c] >= level
    return mask
def components(mask):
    height = len(mask)
    width = len(mask[0])
    seen = [[False for c in range(width)] for r in range(height)]
    rows = [0 for i in range(height*width)]
    cols = [0 for i in range(height*width)]
    found = []
    for r in range(height):
        for c in range(width):
            if not mask[r][c] or seen[r][c]:
                continue
            head = 0
            tail = 1
            rows[0] = r
            cols[0] = c
            seen[r][c] = True
            area = 0
            minrow = r
            maxrow = r
            mincol = c
            maxcol = c
            while head < tail:
                row = rows[head]
                col = cols[head]
                head += 1
                area += 1
                minrow = min(minrow, row)
                maxrow = max(maxrow, row)
                mincol = min(mincol, col)
                maxcol = max(maxcol, col)
                for nr, nc in [(row-1,col), (row+1,col), (row,col-1), (row,col+1)]:
                    if nr < 0 or nr >= height or nc < 0 or nc >= width:
                        continue
                    if not mask[nr][nc] or seen[nr][nc]:
                        continue
                    seen[nr][nc] = True
                    rows[tail] = nr
                    cols[tail] = nc
                    tail += 1
            found += [[area, minrow, mincol, maxrow, maxcol]]
    return found
blurred = smooth(data)
mask = threshold(blurred, 8)
[blurred, mask, components(mask)]
"""


FINDERS = """
def finder_positions(image):
    positions = []
    for row in range(len(image)-6):
        for col in range(len(image[0])-6):
            matches = True
            for r in range(7):
                for c in range(7):
                    black = r == 0 or r == 6 or c == 0 or c == 6 or (2 <= r <= 4 and 2 <= c <= 4)
                    if image[row+r][col+c] != int(black):
                        matches = False
                        break
                if not matches:
                    break
            if matches:
                positions += [[row, col]]
    return positions
finder_positions(data)
"""


GF256 = """
def gf_mul(a, b):
    product = 0
    while b > 0:
        if b & 1:
            product ^= a
        b >>= 1
        a <<= 1
        if a & 256:
            a ^= 285
    return product
"""


GF_PRODUCTS = GF256 + """
products = [0 for i in range(len(data))]
for i in range(len(data)):
    products[i] = gf_mul(data[i][0], data[i][1])
products
"""


RS_SYNDROMES = GF256 + """
def syndromes(codeword, count):
    output = [0 for i in range(count)]
    root = 1
    for order in range(count):
        value = 0
        for coefficient in codeword:
            value = gf_mul(value, root) ^ coefficient
        output[order] = value
        root = gf_mul(root, 2)
    return output
syndromes(data, 7)
"""


def polynomial_product(a, b):
    """Independent oracle: carryless convolution, then polynomial division."""
    product = 0
    for left in range(8):
        for right in range(8):
            if a & (1 << left) and b & (1 << right):
                product ^= 1 << (left + right)
    for degree in range(14, 7, -1):
        if product & (1 << degree):
            product ^= 0x11D << (degree - 8)
    return product


def polynomial_power(value, exponent):
    result = 1
    for unused in range(exponent):
        result = polynomial_product(result, value)
    return result


class CodeAlgorithmTests(unittest.TestCase):
    def value(self, code, data):
        # Every fixture stays within the numeric source contract, including
        # comments: these programs do not hide host calls in quoted text.
        self.assertTrue(code.isascii())
        self.assertFalse(any(char in code for char in ("'", '"', chr(92))))
        before = copy.deepcopy(data)
        result = calculations.calculate(code, data=data)
        self.assertIs(result['ok'], True, result)
        self.assertGreater(result['operations'], 0)
        self.assertLessEqual(result['operations'], calculations.MAX_OPERATIONS)
        self.assertEqual(data, before, 'Code modified the caller-owned input')
        return result['value']

    def assert_samples_close(self, actual, expected, tolerance=1e-12):
        self.assertEqual(len(actual), len(expected))
        for index, (observed, reference) in enumerate(zip(actual, expected)):
            with self.subTest(sample=index):
                self.assertAlmostEqual(observed, reference, delta=tolerance)

    def test_user_biquad_impulse_matches_closed_form_feedback_response(self):
        samples = [1.0] + [0.0] * 39
        output = self.value(BIQUAD, samples)
        # H(z) = (1 + z^-1)^2 / (16 * (1 - z^-1/2)^2).
        # Expanding the double pole gives this closed impulse response,
        # independently of the direct-form recurrence in the Code program.
        expected = [1 / 16] + [(9*n - 3) / (16 * 2**n) for n in range(1, 40)]
        self.assert_samples_close(output, expected)
        self.assertGreater(output[8], 0)
        self.assertGreater(output[2], output[1])

    def test_user_biquad_step_converges_to_unity_without_resetting_feedback(self):
        output = self.value(BIQUAD, [1.0] * 80)
        expected = [1 - (9*n + 15) / (16 * 2**n) for n in range(80)]
        self.assert_samples_close(output, expected)
        self.assertAlmostEqual(output[-1], 1.0, delta=1e-12)
        self.assertTrue(all(left <= right for left, right in zip(output, output[1:])))

    def test_user_biquad_frequency_response_at_pass_and_stop_frequencies(self):
        amplitudes = []
        for period in (32, 4):
            with self.subTest(period=period):
                omega = 2 * math.pi / period
                samples = [math.cos(omega*n) for n in range(384)]
                output = self.value(BIQUAD, samples)
                self.assertEqual(len(output), len(samples))
                # Discard the transient; project an integer number of periods
                # onto the fundamental instead of replaying the recurrence.
                start = 128
                count = len(output) - start
                real = sum(output[n] * math.cos(omega*n) for n in range(start, len(output)))
                imaginary = sum(output[n] * math.sin(omega*n) for n in range(start, len(output)))
                observed = 2 * math.hypot(real, imaginary) / count
                expected = (2 + 2 * math.cos(omega)) / (16 * (1.25 - math.cos(omega)))
                self.assertAlmostEqual(observed, expected, delta=1e-12)
                amplitudes.append(observed)
        self.assertGreater(amplitudes[0], 0.9)
        self.assertAlmostEqual(amplitudes[1], 0.1, delta=1e-12)
        self.assertGreater(amplitudes[0] / amplitudes[1], 9)

    def test_user_convolution_threshold_and_components_on_numeric_pixels(self):
        height, width = 9, 13
        image = [[0 for col in range(width)] for row in range(height)]
        blocks = ((1, 3, 1, 3), (5, 7, 9, 11))
        for top, bottom, left, right in blocks:
            for row in range(top, bottom + 1):
                for col in range(left, right + 1):
                    image[row][col] = 18
        image[2][9] = 18
        blurred, mask, found = self.value(VISION, image)
        # Count overlap with each solid rectangle geometrically. This does
        # not repeat the Code program's nine-neighbour convolution loop.
        expected_blur = [[0.0 for col in range(width)] for row in range(height)]
        for row in range(1, height - 1):
            for col in range(1, width - 1):
                overlaps = 0
                for top, bottom, left, right in blocks:
                    rows = max(0, min(row+1, bottom) - max(row-1, top) + 1)
                    cols = max(0, min(col+1, right) - max(col-1, left) + 1)
                    overlaps += rows * cols
                noise = abs(row-2) <= 1 and abs(col-9) <= 1
                expected_blur[row][col] = 2 * (overlaps + int(noise))
        self.assertEqual(len(blurred), height)
        for row, (actual, expected) in enumerate(zip(blurred, expected_blur)):
            with self.subTest(row=row):
                self.assert_samples_close(actual, expected)
        expected_mask = [[(1 <= row <= 3 and 1 <= col <= 3) or
                          (5 <= row <= 7 and 9 <= col <= 11)
                          for col in range(width)] for row in range(height)]
        self.assertEqual(mask, expected_mask)
        self.assertIs(mask[2][9], False)
        self.assertEqual(found, [[9, 1, 1, 3, 3], [9, 5, 9, 7, 11]])

    def test_user_finder_scan_finds_three_patterns_and_rejects_damaged_one(self):
        # Explicit row fixtures independently describe a 7x7 finder; the
        # Code scanner derives expected pixels from coordinates instead.
        pattern = (
            (1, 1, 1, 1, 1, 1, 1),
            (1, 0, 0, 0, 0, 0, 1),
            (1, 0, 1, 1, 1, 0, 1),
            (1, 0, 1, 1, 1, 0, 1),
            (1, 0, 1, 1, 1, 0, 1),
            (1, 0, 0, 0, 0, 0, 1),
            (1, 1, 1, 1, 1, 1, 1),
        )
        positions = [[1, 1], [1, 13], [13, 1]]
        image = [[0 for col in range(21)] for row in range(21)]
        for top, left in positions:
            for row, pixels in enumerate(pattern):
                image[top+row][left:left+7] = pixels
        image[12][12] = 1
        self.assertEqual(self.value(FINDERS, image), positions)
        damaged = copy.deepcopy(image)
        damaged[4][16] = 0
        self.assertEqual(self.value(FINDERS, damaged), [[1, 1], [13, 1]])

    def test_user_gf256_bit_arithmetic_matches_polynomial_long_division(self):
        pairs = [[left, right] for left in (0, 1, 2, 3, 0x57, 0x80, 0xFE, 0xFF)
                 for right in (0, 1, 2, 0x83, 0xFF)]
        expected = [polynomial_product(left, right) for left, right in pairs]
        self.assertEqual(polynomial_product(0x57, 0x83), 0x31)
        self.assertEqual(self.value(GF_PRODUCTS, pairs), expected)

    def test_user_reed_solomon_syndromes_accept_codeword_and_detect_one_bit_error(self):
        # Synthetic systematic RS codeword over GF(256), modulus 0x11D,
        # with seven parity symbols and roots alpha^0 through alpha^6.
        codeword = [32, 91, 11, 120, 209, 114, 220, 255, 198, 226, 122, 164, 250, 136]
        self.assertEqual(self.value(RS_SYNDROMES, codeword), [0] * 7)
        corrupted = codeword[:]
        location, delta = 3, 4
        corrupted[location] ^= delta
        expected = [polynomial_product(delta, polynomial_power(2, order * (len(codeword)-1-location)))
                    for order in range(7)]
        self.assertEqual(self.value(RS_SYNDROMES, corrupted), expected)
        self.assertTrue(all(expected))


if __name__ == '__main__':
    unittest.main()
