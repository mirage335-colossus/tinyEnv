"""Offline numeric-language cases, including its resource and authority limits."""

import builtins
import json
import socket
import unittest
from unittest import mock

from workbench.services import calculations


class CalculationTests(unittest.TestCase):
    def value(self, code, data=None):
        result = calculations.calculate(code, data=data)
        self.assertIs(result['ok'], True)
        self.assertGreater(result['operations'], 0)
        self.assertLessEqual(result['operations'], calculations.MAX_OPERATIONS)
        return result['value']

    def rejects(self, code, error_code=None):
        result = calculations.tool_result({'code': code})
        self.assertIs(result['ok'], False, code)
        self.assertLessEqual(len(result['error']), 200)
        if error_code:
            self.assertEqual(result['error_code'], error_code)
        return result

    def test_scalar_math_and_constants(self):
        self.assertEqual(self.value('2 + 3 * 4 - 8 / 2'), 10)
        self.assertEqual(self.value('(-11 // 3, -11 % 3, 2**255)'), [-4, 1, 2**255])
        self.assertAlmostEqual(self.value('sin(pi / 2) + cos(0)'), 2)
        self.assertEqual(self.value('(hypot(3, 4), atan2(0, 1), sqrt(25))'), [5, 0, 5])
        self.assertEqual(self.value('(floor(2.9), ceil(2.1), trunc(-2.9), abs(-8), round(pi, 3))'),
                         [2, 3, -2, 8, 3.142])
        self.assertAlmostEqual(self.value('degrees(radians(180))'), 180)
        self.assertAlmostEqual(self.value('log(e) + log(8, 2) + log2(4) + log10(100)'), 8)

    def test_assignments_unpacking_and_small_coordinate_transform(self):
        code = ('points = [(1, 2), (3, 4), (-1, 0)]\n'
                'angle = pi / 2\n'
                '[(round(x*cos(angle)-y*sin(angle), 8), '
                'round(x*sin(angle)+y*cos(angle), 8)) for x, y in points]')
        self.assertEqual(self.value(code), [[-2, 1], [-4, 3], [0, -1]])
        self.assertEqual(self.value('[x*x for x in range(-3, 4) if x >= 0]'), [0, 1, 4, 9])

    def test_bounded_loops_conditionals_and_result_variable(self):
        self.assertEqual(self.value('total = 0\nfor n in range(5):\n    total += n*n\nresult = total'), 30)
        self.assertEqual(self.value('result = []\nfor x in range(3):\n    result += [(x, x+1)]'),
                         [[0, 1], [1, 2], [2, 3]])
        self.assertEqual(self.value('x = 3\nif x > 2:\n    x *= 4\nelse:\n    x = 0\nx'), 12)
        self.assertEqual(self.value('True and (8 if 1 < 2 <= 3 else 0)'), 8)
        self.assertEqual(self.value('0 or 7'), 7)
        self.assertEqual(self.value('(True == 1, False < 1, not [])'), [True, True, True])

    def test_aggregates_indexing_and_comprehension_scope(self):
        self.assertEqual(self.value('values = [3, 1, 4]\n(sum(values), min(values), max(1, 4, 2), '
                                    'len(values), values[-1])'), [8, 1, 4, 3, 4])
        self.assertEqual(self.value('x = 9\n[x for x in range(2)]\nx'), 9)
        self.assertEqual(self.value('[(x,y) for x in range(2) for y in range(2)]'),
                         [[0, 0], [0, 1], [1, 0], [1, 1]])
        self.assertEqual(self.value('(sum([]), range(4, -1, -2), range(0, 3, -1))'), [0, [4, 2, 0], []])

    def test_source_is_never_general_python_execution(self):
        with mock.patch.object(builtins, 'eval', side_effect=AssertionError('eval called')), \
                mock.patch.object(builtins, 'exec', side_effect=AssertionError('exec called')), \
                mock.patch.object(builtins, 'open', side_effect=AssertionError('file opened')), \
                mock.patch.object(socket, 'create_connection', side_effect=AssertionError('network called')):
            self.assertEqual(self.value('[n*n for n in range(3)]'), [0, 1, 4])
            for code in ('open("file")', '__import__("os")', 'eval("1")', 'exec("1")'):
                self.rejects(code)

    def test_rejects_all_unsupported_syntax_including_dead_branches(self):
        cases = (
            'import os', 'from math import sqrt', 'x.real', '(1).__class__',
            'lambda: 1', 'class C:\n    x = 1', 'try:\n    x=1\nexcept:\n    x=2',
            'with 1:\n    x=2', 'del x', 'print(1)', 'break', 'continue',
            '{1: 2}', '{1, 2}', '(n for n in range(2))', '[*range(2)]',
            'range(stop=2)', 'range(**{})', '[1]*2',
            'result[:] = [1]', 'x = y = 1', 'x, *y = [1,2]',
            'for x in []:\n    y = 1\nelse:\n    y = 2',
            'if False:\n    import os\n1', '1 if True else open("x")',
            'False and (1).__class__', 'f"{1}"', 'None', '"text"', '1j',
            '_hidden = 1', 'pi = 1', 'range = 2',
        )
        for code in cases:
            with self.subTest(code=code):
                self.rejects(code)

    def test_exact_argument_shape_and_ascii_source(self):
        for arguments in (None, [], {}, {'code': '1', 'path': '/tmp'}, {'code': 1}):
            with self.subTest(arguments=arguments):
                self.assertIs(calculations.tool_result(arguments)['ok'], False)
        for code in ('', ' \n', '1\x00', '1\x1b', '1\ud800', 'K=1\nK', '# café\n1',
                     '1' + ' ' * calculations.MAX_SOURCE_BYTES):
            with self.subTest(code=repr(code)):
                self.rejects(code)
        self.assertEqual(self.value('# ordinary comment\n1\r\n'), 1)

    def test_numeric_domains_and_expensive_exponent_rejection(self):
        for code in ('1e309', '1e101', str(2**256), '2**256', '9**9**9',
                     '1**1025', '2**-1025', '(-1)**0.5', '1e100**2',
                     '1e100+1e100', '1/0', 'sqrt(-1)', 'exp(1000)',
                     'log(0)', 'round(1, 1000000)', 'round(1, 2.0)', 'True+1'):
            with self.subTest(code=code):
                self.rejects(code)
        with mock.patch.object(calculations.math, 'exp', side_effect=AssertionError('unapproved host call')):
            self.rejects('exp((2**256))')
        self.assertEqual(self.value('(-1)**1024'), 1)
        self.assertEqual(self.value('round(1.25, 1)'), 1.2)

    def test_unknown_or_callable_names_cannot_escape_as_values(self):
        for code in ('missing', 'sin', '[range]', 'fn = sqrt\nfn(4)', 'globals()', 'getattr(1, 2)',
                     'sum(3)', 'min([])', 'len(3)', 'range(0, 1, 0)', 'range(2.0)',
                     '[1][2]', '[1][True]', 'x,y = [1]\nx'):
            with self.subTest(code=code):
                self.rejects(code)

    def test_syntax_depth_and_node_limits(self):
        self.rejects('+' * 5000 + '1')
        self.rejects('1' + '+1' * 100, 'syntax_limit')
        self.rejects('\n'.join('x = 1' for _ in range(1100)), 'syntax_limit')

    def test_preallocation_range_container_and_iteration_limits(self):
        for code in ('range(65537)', 'range(-10**70, 10**70)', 'range(10**70, -10**70, -1)'):
            with self.subTest(code=code):
                self.rejects(code, 'container_limit')
        self.rejects('a = range(33000)\na+a', 'container_limit')
        self.assertEqual(self.value('len(range(65536))'), 65536)
        with mock.patch.object(calculations, 'MAX_ITERATIONS', 1024):
            self.rejects('[x for x in range(33) for y in range(33) if False]', 'iteration_limit')
            self.rejects('for x in range(33):\n    for y in range(33):\n        pass\n1', 'iteration_limit')

    def test_cumulative_storage_and_alias_nesting_limits(self):
        with mock.patch.object(calculations, 'MAX_CONTAINER_SLOTS', 16384):
            self.rejects('for x in range(17):\n    a=range(1024)\n1', 'container_limit')
        self.rejects('x=1\n' + '\n'.join('x=[x]' for _ in range(13)) + '\nx', 'container_limit')
        with mock.patch.object(calculations, 'MAX_OPERATIONS', 20000):
            self.rejects('x=range(100)\ny=[x for i in range(100)]\n[y,y]', 'operation_limit')
        with mock.patch.object(calculations, 'MAX_VALUE_NODES', 32):
            self.rejects('x=[1]\n' + '\n'.join('x=[x,x]' for _ in range(5)) + '\n1', 'container_limit')
        self.rejects('\n'.join('v'+str(n)+'=1' for n in range(calculations.MAX_VARIABLES))+'\n1',
                     'variable_limit')

    def test_operation_and_output_limits(self):
        with mock.patch.object(calculations, 'MAX_OPERATIONS', 50):
            self.rejects('sum(range(100))', 'operation_limit')
        self.rejects('[10**70 for n in range(1000)]', 'output_limit')
        self.assertEqual(self.value('result=1'), 1)
        self.rejects('x=1')

    def test_output_size_precedes_aggregate_serialization_and_matches_encoding(self):
        original = calculations.json.dumps

        def scalar_only(value, **kwargs):
            if isinstance(value, (list, tuple)):
                raise AssertionError('Oversized aggregate reached full JSON serialization')
            return original(value, **kwargs)

        with mock.patch.object(calculations.json, 'dumps', side_effect=scalar_only):
            self.rejects('x=[10**70 for n in range(200)]\n[x,x,x,x,x]', 'output_limit')
        code = '(True, [False, 1.25, -2, (1e100, 2**255)], ())'
        expected = [True, [False, 1.25, -2, [1e100, 2**255]], []]
        size = len(json.dumps(expected, separators=(',', ':')))
        with mock.patch.object(calculations, 'MAX_OUTPUT_BYTES', size):
            self.assertEqual(self.value(code), expected)
        with mock.patch.object(calculations, 'MAX_OUTPUT_BYTES', size - 1):
            self.rejects(code, 'output_limit')

    def test_private_numeric_input_and_scalar_mutation(self):
        original = [[1, 2], [3, 4]]
        code = 'data[0][1] = 9\ndata[1][0] += 2\ndata'
        self.assertEqual(self.value(code, original), [[1, 9], [5, 4]])
        self.assertEqual(original, [[1, 2], [3, 4]])
        shared = [1]
        self.assertEqual(self.value('data[0][0] = 8\ndata', [shared, shared]), [[8], [1]])
        self.assertEqual(shared, [1])
        self.assertEqual(self.value('row=[1]\na=[row,row]\na[0][0]=8\na'), [[8], [8]])
        self.assertEqual(self.value('data'), [])
        self.assertEqual(self.value('data + 1', 4), 5)
        self.assertEqual(self.value('not data', False), True)
        self.assertEqual(calculations.tool_result({'code': 'sum(data)', 'data': [1, 2]})['value'], 3)

    def test_input_rejects_host_values_cycles_and_expansion_before_copy(self):
        cycle = []
        cycle.append(cycle)
        for data in (None, '1', {}, (1,), {1}, [1, None], [float('nan')],
                     [float('inf')], [1e101], [2**256], cycle, object()):
            with self.subTest(data_type=type(data).__name__):
                self.assertFalse(calculations.tool_result({'code': '1', 'data': data})['ok'])
        with mock.patch.object(calculations._Interpreter, 'reserve',
                               side_effect=AssertionError('copy began before complete input validation')):
            self.assertFalse(calculations.tool_result({'code': '1', 'data': [1, [None]]})['ok'])
        with mock.patch.object(calculations, 'MAX_CONTAINER_ITEMS', 2):
            self.assertEqual(calculations.tool_result({'code': '1', 'data': [1, 2, 3]})['error_code'],
                             'container_limit')
        with mock.patch.object(calculations, 'MAX_VALUE_NODES', 8):
            leaf = [1, 2]
            self.assertEqual(calculations.tool_result({'code': '1', 'data': [leaf, leaf, leaf]})['error_code'],
                             'container_limit')

    def test_input_copy_rechecks_observed_values_after_validation(self):
        reserve = calculations._Interpreter.reserve
        for replacement in (object(), [], None):
            data = [1]

            def mutate(interpreter, count):
                reserve(interpreter, count)
                data[0] = data if type(replacement) is list else replacement

            with self.subTest(replacement_type=type(replacement).__name__), \
                    mock.patch.object(calculations._Interpreter, 'reserve', side_effect=mutate, autospec=True):
                self.assertFalse(calculations.tool_result({'code': 'bool(data)', 'data': data})['ok'])

    def test_exact_builtin_boundary_rejects_subclass_hooks(self):
        class HostString(str):
            def strip(self, *args):
                raise AssertionError('host string method')

        class HostList(list):
            def __iter__(self):
                raise AssertionError('host list iterator')

        class HostDict(dict):
            def __iter__(self):
                raise AssertionError('host dict iterator')

        class HostInt(int):
            def bit_length(self):
                raise AssertionError('host integer method')

        for args in (HostDict(code='1'), {'code': HostString('1')},
                     {'code': '1', 'data': HostList([1])}, {'code': '1', 'data': HostInt(1)},
                     {'code': '1', 'data': [HostList([1])]}):
            self.assertFalse(calculations.tool_result(args)['ok'])

    def test_quote_backslash_and_non_ascii_rejection_precedes_parser(self):
        for code in ('# quote "\n1', "# quote '\n1", '# slash ' + chr(92) + '\n1',
                     '# é\n1', chr(92) + 'u0031', '1' + chr(92) + '\n+1'):
            with self.subTest(code=code), mock.patch.object(calculations.ast, 'parse',
                                                          side_effect=AssertionError('parser reached')):
                self.rejects(code)

    def test_functions_local_scopes_forward_declarations_and_control_flow(self):
        code = ('factor=3\n'
                'def scale(xs, amount):\n'
                '    factor=amount\n'
                '    out=[0 for item in xs]\n'
                '    for i in range(len(xs)):\n'
                '        out[i]=xs[i]*factor\n'
                '    return out\n'
                '(scale(data, 2), factor)')
        self.assertEqual(self.value(code, [2, 4, 5]), [[4, 8, 10], 3])
        self.assertEqual(self.value('result=helper(3)\ndef helper(x):\n    return x+1'), 4)
        self.assertEqual(self.value('def f(x):\n    return g(x)\ndef g(x):\n    return x*x\nf(4)'), 16)
        self.assertEqual(self.value('factor=7\ndef f(x):\n    return x*factor\nf(2)'), 14)
        self.assertEqual(self.value('def f():\n    for x in range(3):\n        while True:\n'
                                    '            return x+4\n    return 0\nf()'), 4)

    def test_function_identities_and_full_definition_validation(self):
        cases = ('def f(x):\n    return x\nf', 'def f(x):\n    return x\na=f\na(1)',
                 'def f(x):\n    return x\nf=1\n1', 'def f(data):\n    return data\n1',
                 'def data(x):\n    return x\n1', 'def f(x=1):\n    return x\n1',
                 'def f(x, /):\n    return x\n1', 'def f(*xs):\n    return 1\n1',
                 'def f(x: int):\n    return x\n1', 'def f(x) -> int:\n    return x\n1',
                 '@sqrt\ndef f(x):\n    return x\n1', 'def f(x,x):\n    return x\n1',
                 'def f():\n    def g():\n        return 1\n    return 1\n1',
                 'if False:\n    def f():\n        return 1\n1',
                 'def f():\n    global x\n    return 1\n1', 'def f():\n    return\n1',
                 'def f():\n    pass\nf()', 'def f(x):\n    return x\nf()',
                 'def f():\n    return f()\n1',
                 'def f():\n    return g()\ndef g():\n    if False:\n        return f()\n    return 1\n1',
                 'return 1', 'if False:\n    return 1\n1',
                 'def f():\n    break\n    return 1\n1',
                 'def f():\n    continue\n    return 1\n1', 'data=1\n1')
        for code in cases:
            with self.subTest(code=code):
                self.rejects(code)
        chain = '\n'.join('def f'+str(i)+'():\n    return f'+str(i+1)+'()'
                          for i in range(calculations.MAX_CALL_DEPTH))
        chain += '\ndef f'+str(calculations.MAX_CALL_DEPTH)+'():\n    return 1\nf0()'
        self.rejects(chain, 'recursion_limit')
        with mock.patch.object(calculations, 'MAX_FUNCTIONS', 1):
            self.rejects('def f():\n    return 1\ndef g():\n    return 2\n1', 'function_limit')

    def test_combined_nesting_limits_precede_host_stack_exhaustion(self):
        parts = []
        for index in range(calculations.MAX_CALL_DEPTH):
            parts.append('def f'+str(index)+'():')
            for depth in range(35):
                parts.append(' '*(depth+1)+'if True:')
            expression = 'f'+str(index+1)+'()' if index < calculations.MAX_CALL_DEPTH-1 else '1'
            parts.append(' '*36+'return '+expression)
        parts.append('f0()')
        self.rejects('\n'.join(parts), 'recursion_limit')
        generators = ' '.join('for v'+str(index)+' in [1]'
                              for index in range(calculations.MAX_EVALUATION_DEPTH))
        self.rejects('[1 '+generators+']', 'recursion_limit')
        with mock.patch.object(calculations, 'MAX_EVALUATION_DEPTH', 8):
            self.rejects('+'*10+'1', 'recursion_limit')
        with mock.patch.object(calculations.ast, 'parse', side_effect=AssertionError('parser reached')):
            self.rejects(' '*(calculations.MAX_SOURCE_BYTES+1))

    def test_bounded_while_break_continue_and_empty_work(self):
        code = ('i=0\ntotal=0\nwhile i<20:\n    i+=1\n    if i%2==0:\n        continue\n'
                '    if i>7:\n        break\n    total+=i\n(total,i)')
        self.assertEqual(self.value(code), [16, 9])
        self.assertEqual(self.value('total=0\nfor x in range(4):\n    for y in range(4):\n'
                                    '        if y==2:\n            break\n        total+=1\ntotal'), 8)
        with mock.patch.object(calculations, 'MAX_ITERATIONS', 5):
            for code in ('while True:\n    pass\n1', 'while True:\n    continue\n1',
                         'for i in range(6):\n    pass\n1'):
                self.rejects(code, 'iteration_limit')
            self.assertEqual(self.value('while True:\n    break\n1'), 1)
        self.rejects('while False:\n    pass\nelse:\n    pass\n1')

    def test_integer_bit_operations_conversions_and_prebounded_shifts(self):
        self.assertEqual(self.value('(12&10,12|10,12^10,~12,3<<4,48>>4,int(-2.8),'
                                    'int(True),float(3),bool([]),bool([0]))'),
                         [8, 14, 6, -13, 48, 3, -2, 1, 3.0, False, True])
        self.assertEqual(self.value('value=1\nvalue<<=7\nvalue|=3\nvalue'), 131)
        for code in ('1<<256', '1<<1000000000000', '1<<-1', '1>>256', '1<<True',
                     '1.0&1', 'True|1', '~True', '~(2**256-1)', 'int(1e100)',
                     'int([])', 'float([])', 'bool()', 'int(1,2)'):
            with self.subTest(code=code):
                self.rejects(code)
        self.assertEqual(self.value('1<<255'), 2**255)
        self.assertEqual(self.value('-1>>255'), -1)

    def test_read_only_slices_and_scalar_mutation_never_link_containers(self):
        self.assertEqual(self.value('a=[0,1,2,3,4]\n(a[1:4:2],a[::-1],a[20:30],a[-3:])'),
                         [[1, 3], [4, 3, 2, 1, 0], [], [2, 3, 4]])
        self.assertEqual(self.value('(0,1,2)[:2]'), [0, 1])
        for code in ('[1][::0]', '[1][:True]', '[1][1.0:]', 'a=[1]\na[:]=[2]\na',
                     'a=[1]\na[0]=a\na', 'a=[1]\nb=[a]\na[0]=b\na',
                     'a=[[]]\na[0]+=[1]\na', 'a=(1,)\na[0]=2\na'):
            with self.subTest(code=code):
                self.rejects(code)
        code = ('def position():\n    data[0]+=1\n    return 1\n'
                'def change():\n    data[1]=10\n    return 4\n'
                'data[position()]+=change()\ndata')
        self.assertEqual(self.value(code, [0, 3]), [1, 7])

    def test_user_logic_remains_without_host_execution_or_io(self):
        with mock.patch.object(builtins, 'eval', side_effect=AssertionError('eval called')), \
                mock.patch.object(builtins, 'exec', side_effect=AssertionError('exec called')), \
                mock.patch.object(builtins, 'open', side_effect=AssertionError('file opened')), \
                mock.patch.object(socket, 'create_connection', side_effect=AssertionError('network called')):
            self.assertEqual(self.value('def popcount(n):\n    total=0\n    while n:\n'
                                        '        total+=n&1\n        n>>=1\n    return total\n'
                                        '[popcount(n) for n in data]', [0, 1, 7, 255]), [0, 1, 3, 8])
            for code in ('import cv2', 'from pyzbar import decode', 'import qrcode',
                         'if False:\n    import zxing\n1', 'data.append(1)', 'input()',
                         'def f():\n    return open(1)\n1'):
                self.rejects(code)


if __name__ == '__main__':
    unittest.main()
