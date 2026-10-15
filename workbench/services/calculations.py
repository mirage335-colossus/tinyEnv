"""A bounded numeric language interpreted from a Python-shaped syntax tree.

Only the explicitly listed nodes and primitive operations exist. User source is
never compiled to bytecode or passed to eval/exec. No user value is a host object,
callable, string, path, image codec, or capability to perform input/output.
"""

import ast
import json
import math
import re


MAX_SOURCE_BYTES = 32768
MAX_AST_NODES = 4096
MAX_AST_DEPTH = 48
MAX_OPERATIONS = 2000000
MAX_ITERATIONS = 200000
MAX_CONTAINER_ITEMS = 65536
MAX_CONTAINER_SLOTS = 1048576
MAX_VALUE_NODES = 262144
MAX_VALUE_DEPTH = 12
MAX_VARIABLES = 256
MAX_FUNCTIONS = 64
MAX_CALL_DEPTH = 16
MAX_EVALUATION_DEPTH = 128
MAX_INTEGER_BITS = 256
MAX_FLOAT_ABS = 1e100
MAX_EXPONENT_ABS = 1024
MAX_OUTPUT_BYTES = 65536
MAX_CALL_ARGUMENTS = 64
CONSTANTS = {'pi': math.pi, 'e': math.e, 'tau': math.tau}
_MATH_ARITIES = {
    'sqrt': (1, 1), 'sin': (1, 1), 'cos': (1, 1), 'tan': (1, 1),
    'asin': (1, 1), 'acos': (1, 1), 'atan': (1, 1), 'atan2': (2, 2),
    'sinh': (1, 1), 'cosh': (1, 1), 'tanh': (1, 1),
    'asinh': (1, 1), 'acosh': (1, 1), 'atanh': (1, 1),
    'exp': (1, 1), 'log': (1, 2), 'log2': (1, 1), 'log10': (1, 1),
    'floor': (1, 1), 'ceil': (1, 1), 'trunc': (1, 1),
    'degrees': (1, 1), 'radians': (1, 1), 'hypot': (1, MAX_CALL_ARGUMENTS),
}
FUNCTIONS = frozenset(_MATH_ARITIES) | frozenset((
    'abs', 'round', 'min', 'max', 'sum', 'len', 'range', 'int', 'float', 'bool',
))
_NODES = frozenset((
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.For, ast.While, ast.If,
    ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Break, ast.Continue, ast.Pass,
    ast.Constant, ast.Name, ast.List, ast.Tuple, ast.BinOp, ast.UnaryOp,
    ast.BoolOp, ast.Compare, ast.IfExp, ast.Call, ast.Subscript, ast.Slice,
    ast.ListComp, ast.comprehension, ast.Load, ast.Store,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift, ast.Invert,
    ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
))
_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}\Z')


class CalculationError(ValueError):
    """A bounded locally generated error, suitable for a model correction."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _error(message, code='invalid_calculation'):
    raise CalculationError(code, message)


def _number(value):
    if type(value) is int:
        if value.bit_length() > MAX_INTEGER_BITS:
            _error('Integer magnitude exceeds the 256-bit limit.', 'numeric_limit')
    elif type(value) is float:
        if not math.isfinite(value) or abs(value) > MAX_FLOAT_ABS:
            _error('Numbers must be finite with magnitude at most 1e100.', 'numeric_limit')
    else:
        _error('This operation requires numeric values.')
    return value


def _integer(value):
    if type(value) is not int:
        _error('This operation requires integer values.')
    return _number(value)


def _name(name):
    if not _NAME.fullmatch(name):
        _error('Names must be ASCII identifiers of at most 64 characters without a leading underscore.')


def _target(node, reserved, indexed=True):
    if isinstance(node, ast.Name):
        if node.id in reserved:
            _error('Functions, constants and data cannot be rebound.')
    elif isinstance(node, (ast.Tuple, ast.List)):
        for item in node.elts:
            _target(item, reserved, indexed)
    elif indexed and isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
        pass
    else:
        _error('Use names, fixed unpacking, or a single indexed element as assignment targets.')


def _parse(code):
    # Reject lexical escape/encoding tricks before the parser sees any source,
    # including quotes and backslashes in comments or unexecuted branches.
    if (type(code) is not str or len(code) > MAX_SOURCE_BYTES or not code.strip() or
            any(not (' ' <= char <= '~' or char in '\n\r\t') for char in code) or
            any(char in code for char in ('\\', '"', "'"))):
        _error('Code requires 1-32768 ASCII bytes without quotes, backslashes or other control characters.')
    try:
        tree = ast.parse(code, mode='exec')
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        _error('Invalid or excessively nested calculation syntax.')
    functions = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            _name(node.name)
            if node.name in FUNCTIONS or node.name in CONSTANTS or node.name == 'data' or node.name in functions:
                _error('Function names must be unique and cannot replace reserved names.')
            functions[node.name] = node
            if len(functions) > MAX_FUNCTIONS:
                _error('Calculation function limit exceeded.', 'function_limit')
    reserved = FUNCTIONS | frozenset(CONSTANTS) | frozenset(functions) | {'data'}
    pending, count = [(tree, 0, False, 0)], 0
    while pending:
        node, depth, in_function, loops = pending.pop()
        count += 1
        if count > MAX_AST_NODES or depth > MAX_AST_DEPTH:
            _error('Calculation syntax exceeds the node or depth limit.', 'syntax_limit')
        if type(node) not in _NODES:
            _error('Unsupported calculation syntax.')
        if isinstance(node, ast.Constant):
            if type(node.value) is not bool:
                _number(node.value)
        elif isinstance(node, ast.Name):
            _name(node.id)
        elif isinstance(node, ast.FunctionDef):
            if functions.get(node.name) is not node:
                _error('Function definitions must appear directly at the top level.')
            if node.decorator_list or node.returns is not None or node.type_comment or getattr(node, 'type_params', ()):
                _error('Function decorators, annotations and type parameters are unavailable.')
        elif isinstance(node, ast.arguments):
            if (node.posonlyargs or node.vararg or node.kwonlyargs or node.kwarg or
                    node.defaults or node.kw_defaults or len(node.args) > MAX_CALL_ARGUMENTS):
                _error('Functions accept at most 64 ordinary positional parameters without defaults.')
            names = [item.arg for item in node.args]
            if len(set(names)) != len(names) or any(name in reserved for name in names):
                _error('Function parameters must be unique and cannot replace reserved names.')
        elif isinstance(node, ast.arg):
            _name(node.arg)
            if node.annotation is not None or node.type_comment:
                _error('Function parameter annotations are unavailable.')
        elif isinstance(node, ast.Return):
            if not in_function or node.value is None:
                _error('Return requires a value inside a function.')
        elif isinstance(node, (ast.Break, ast.Continue)):
            if not loops:
                _error('Break and continue require an enclosing loop in the same function.')
        elif isinstance(node, ast.Call):
            if (not isinstance(node.func, ast.Name) or node.func.id not in reserved - {'data'} - frozenset(CONSTANTS) or
                    node.keywords or len(node.args) > MAX_CALL_ARGUMENTS):
                _error('Use declared or approved bare functions with bounded positional arguments only.')
        elif isinstance(node, ast.Assign):
            if len(node.targets) != 1:
                _error('Use one assignment target at a time.')
            _target(node.targets[0], reserved)
        elif isinstance(node, ast.AugAssign):
            if not isinstance(node.target, (ast.Name, ast.Subscript)):
                _error('Augmented assignment accepts a name or indexed element only.')
            _target(node.target, reserved)
        elif isinstance(node, (ast.For, ast.While)):
            if isinstance(node, ast.For):
                _target(node.target, reserved, indexed=False)
            if node.orelse:
                _error('Loop-else is unavailable.')
        elif isinstance(node, ast.comprehension):
            _target(node.target, reserved, indexed=False)
            if node.is_async:
                _error('Async comprehensions are unavailable.')
        elif isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) > MAX_CONTAINER_ITEMS:
            _error('Container item limit exceeded.', 'container_limit')
        for child in ast.iter_child_nodes(node):
            child_function, child_loops = in_function, loops
            if isinstance(node, ast.FunctionDef):
                child_function, child_loops = True, 0
            elif isinstance(node, (ast.For, ast.While)) and child in node.body:
                child_loops += 1
            pending.append((child, depth + 1, child_function, child_loops))
    if not tree.body:
        _error('Provide a calculation expression.')
    # Reject all static recursive call cycles, including those in dead branches.
    edges = {name: {child.func.id for child in ast.walk(node)
                    if isinstance(child, ast.Call) and child.func.id in functions}
             for name, node in functions.items()}
    done, active = set(), set()

    def visit(name):
        if name in active:
            _error('Recursive function calls are unavailable.', 'recursion_limit')
        if name not in done:
            active.add(name)
            for child in edges[name]:
                visit(child)
            active.remove(name)
            done.add(name)

    for name in functions:
        visit(name)
    return tree, functions


class _Flow(Exception):
    """Interpreter-only control transfer; never a user-visible value."""

    def __init__(self, kind, value=None):
        self.kind, self.value = kind, value


class _Interpreter:
    def __init__(self, functions, data):
        self.variables = {}
        self.functions = functions
        self.operations = self.iterations = self.slots = self.call_depth = self.evaluation_depth = 0
        self.variables['data'] = [] if data is None else self.input_data(data)

    def tick(self, count=1):
        self.operations += count
        if self.operations > MAX_OPERATIONS:
            _error('Calculation operation budget exhausted.', 'operation_limit')

    def enter(self):
        # AST, loop and function limits do not independently bound their composed
        # host stack. Count all recursive interpreter entry points together.
        self.evaluation_depth += 1
        if self.evaluation_depth > MAX_EVALUATION_DEPTH:
            _error('Calculation combined evaluation nesting exhausted.', 'recursion_limit')

    def iteration(self):
        self.tick()
        self.iterations += 1
        if self.iterations > MAX_ITERATIONS:
            _error('Calculation total loop iteration budget exhausted.', 'iteration_limit')

    def shape(self, value, depth=0):
        """Count expanded nodes (including aliases), bounding traversal itself."""
        total = 0

        def inspect(item, level):
            nonlocal total
            self.tick()
            total += 1
            if level > MAX_VALUE_DEPTH or total > MAX_VALUE_NODES:
                _error('Calculation expanded value size or nesting limit exceeded.', 'container_limit')
            if type(item) in (list, tuple):
                if len(item) > MAX_CONTAINER_ITEMS:
                    _error('Container item limit exceeded.', 'container_limit')
                for child in item:
                    inspect(child, level + 1)
            elif type(item) is not bool:
                _number(item)

        inspect(value, depth)
        return total

    def input_data(self, data):
        # Complete validation precedes all input copies. Track active identities
        # to reject cycles; repeated aliases are counted and copied independently.
        total, slots, active = 0, 0, set()

        def inspect(item, depth):
            nonlocal total, slots
            self.tick()
            total += 1
            if depth > MAX_VALUE_DEPTH or total > MAX_VALUE_NODES:
                _error('Input data size or nesting limit exceeded.', 'container_limit')
            if type(item) is list:
                if len(item) > MAX_CONTAINER_ITEMS:
                    _error('Input list item limit exceeded.', 'container_limit')
                if id(item) in active:
                    _error('Input data cannot contain cycles.')
                slots += len(item)
                if slots > MAX_CONTAINER_SLOTS:
                    _error('Input data allocation limit exceeded.', 'container_limit')
                active.add(id(item))
                for child in item:
                    inspect(child, depth + 1)
                active.remove(id(item))
            elif type(item) is not bool:
                _number(item)

        inspect(data, 0)

        copied, copying = 0, set()

        def copy(item, depth=0):
            nonlocal copied
            self.tick()
            copied += 1
            if depth > MAX_VALUE_DEPTH or copied > MAX_VALUE_NODES:
                _error('Input data changed beyond its size or nesting limit.', 'container_limit')
            if type(item) is list:
                if id(item) in copying:
                    _error('Input data cannot contain cycles.')
                count = len(item)
                self.reserve(count)
                self.tick(count)
                copying.add(id(item))
                try:
                    # Index a frozen length rather than following a list that a
                    # concurrent direct API caller might keep extending. Recheck
                    # every observed child so mutation cannot admit host objects.
                    value = [copy(item[index], depth + 1) for index in range(count)]
                except IndexError:
                    _error('Input data changed during its private copy.')
                finally:
                    copying.remove(id(item))
                return value
            if type(item) is not bool:
                _number(item)
            return item

        return copy(data)

    def reserve(self, count):
        if count > MAX_CONTAINER_ITEMS:
            _error('Container item limit exceeded.', 'container_limit')
        self.slots += count
        if self.slots > MAX_CONTAINER_SLOTS:
            _error('Calculation cumulative container allocation budget exhausted.', 'container_limit')

    def output_size(self, value):
        """Refuse an expanded JSON result before allocating its full encoding."""
        pending, size = [value], 0
        while pending:
            self.tick()
            item = pending.pop()
            if type(item) in (list, tuple):
                size += 2 + max(0, len(item) - 1)
                pending.extend(reversed(item))
            else:
                size += len(json.dumps(item, allow_nan=False, separators=(',', ':')))
            if size > MAX_OUTPUT_BYTES:
                _error('Calculation JSON output exceeds 65536 bytes.', 'output_limit')

    def check_items(self, values):
        total = 1
        for value in values:
            total += self.shape(value, 1)
            if total > MAX_VALUE_NODES:
                _error('Calculation expanded value size limit exceeded.', 'container_limit')

    def container(self, values, kind=list):
        self.reserve(len(values))
        self.check_items(values)
        return kind(values)

    def sequence(self, value):
        if type(value) not in (list, tuple):
            _error('A list or tuple is required.')
        return value

    def location(self, target, variables):
        values = self.sequence(self.expression(target.value, variables))
        index = self.expression(target.slice, variables)
        if type(index) is not int or not -len(values) <= index < len(values):
            _error('Index must be an integer within the list or tuple.')
        return values, index

    def assign(self, target, value, variables):
        self.tick()
        if isinstance(target, ast.Name):
            if target.id not in variables and len(variables) >= MAX_VARIABLES:
                _error('Calculation variable limit exceeded.', 'variable_limit')
            variables[target.id] = value
        elif isinstance(target, ast.Subscript):
            self.store(self.location(target, variables), value)
        else:
            values = self.sequence(value)
            if len(target.elts) != len(values):
                _error('Unpacking target length must match the value.')
            for child, item in zip(target.elts, values):
                self.assign(child, item, variables)

    def store(self, location, value):
        values, index = location
        if type(values) is not list:
            _error('Only list elements can be mutated.')
        if type(value) is not bool:
            _number(value)
        # Container links cannot be changed: scalar writes cannot create cycles
        # or deepen an alias graph. Existing aliases have ordinary shared writes.
        values[index] = value

    def binary(self, operation, left, right):
        self.tick()
        if isinstance(operation, ast.Add) and type(left) in (list, tuple):
            if type(left) is not type(right):
                _error('Container concatenation requires matching lists or tuples.')
            self.reserve(len(left) + len(right))
            # Check their expanded union before allocating its slot array.
            total = 1
            for sequence in (left, right):
                for value in sequence:
                    total += self.shape(value, 1)
                    if total > MAX_VALUE_NODES:
                        _error('Calculation expanded value size limit exceeded.', 'container_limit')
            return left + right
        if isinstance(operation, (ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift)):
            left, right = _integer(left), _integer(right)
            if isinstance(operation, (ast.LShift, ast.RShift)):
                if not 0 <= right < MAX_INTEGER_BITS:
                    _error('Shift counts must be integers from 0 to 255.', 'numeric_limit')
                if isinstance(operation, ast.LShift) and left and left.bit_length() + right > MAX_INTEGER_BITS:
                    _error('Shift result exceeds the 256-bit integer limit.', 'numeric_limit')
                value = left << right if isinstance(operation, ast.LShift) else left >> right
            elif isinstance(operation, ast.BitAnd):
                value = left & right
            elif isinstance(operation, ast.BitOr):
                value = left | right
            else:
                value = left ^ right
            return _number(value)
        left, right = _number(left), _number(right)
        if isinstance(operation, ast.Pow):
            if abs(right) > MAX_EXPONENT_ABS:
                _error('Power exponent magnitude exceeds 1024.', 'numeric_limit')
            if left < 0 and type(right) is float and not right.is_integer():
                _error('Complex numbers are unavailable.')
            if type(left) is int and type(right) is int and right >= 0 and abs(left) >= 2:
                if (abs(left).bit_length() - 1) * right >= MAX_INTEGER_BITS:
                    _error('Power result exceeds the 256-bit integer limit.', 'numeric_limit')
        try:
            if isinstance(operation, ast.Add):
                value = left + right
            elif isinstance(operation, ast.Sub):
                value = left - right
            elif isinstance(operation, ast.Mult):
                value = left * right
            elif isinstance(operation, ast.Div):
                value = left / right
            elif isinstance(operation, ast.FloorDiv):
                value = left // right
            elif isinstance(operation, ast.Mod):
                value = left % right
            else:
                value = left ** right
        except (ArithmeticError, ValueError):
            _error('Calculation arithmetic is outside its numeric domain.', 'numeric_error')
        return _number(value)

    def call(self, name, arguments):
        self.tick()
        if name in self.functions:
            function = self.functions[name]
            if len(arguments) != len(function.args.args):
                _error('User function argument count must match its parameters.')
            if self.call_depth >= MAX_CALL_DEPTH:
                _error('Calculation function call depth exhausted.', 'recursion_limit')
            local = dict(zip((item.arg for item in function.args.args), arguments))
            self.call_depth += 1
            try:
                self.block(function.body, local)
            except _Flow as control:
                if control.kind == 'return':
                    return control.value
                _error('Invalid function control transfer.')
            finally:
                self.call_depth -= 1
            _error('User function must return a value on the executed path.')
        if name == 'range':
            if not 1 <= len(arguments) <= 3 or any(type(item) is not int for item in arguments):
                _error('range accepts one to three integer arguments.')
            start, stop = (0, arguments[0]) if len(arguments) == 1 else arguments[:2]
            step = arguments[2] if len(arguments) == 3 else 1
            if not step:
                _error('range step cannot be zero.')
            count = max(0, (stop - start + step - (1 if step > 0 else -1)) // step)
            self.reserve(count)
            self.tick(count)
            return list(range(start, stop, step))
        if name in ('int', 'float', 'bool'):
            if len(arguments) != 1:
                _error('Conversions accept exactly one value.')
            value = arguments[0]
            if name == 'bool':
                return bool(value)
            if type(value) is not bool:
                _number(value)
            if name == 'int':
                if type(value) is float and abs(value) >= 2 ** MAX_INTEGER_BITS:
                    _error('Integer conversion exceeds the 256-bit limit.', 'numeric_limit')
                return _number(int(value))
            return _number(float(value))
        if name == 'len':
            if len(arguments) != 1:
                _error('len accepts one list or tuple.')
            return len(self.sequence(arguments[0]))
        if name in ('sum', 'min', 'max'):
            if name == 'sum' or len(arguments) == 1:
                if len(arguments) != 1:
                    _error('sum accepts one numeric list or tuple.')
                values = self.sequence(arguments[0])
            else:
                values = arguments
            if not values and name != 'sum':
                _error('min and max require at least one numeric value.')
            value = 0 if name == 'sum' else _number(values[0])
            for item in values:
                self.tick()
                item = _number(item)
                if name == 'sum':
                    value = self.binary(ast.Add(), value, item)
                elif name == 'min':
                    value = min(value, item)
                else:
                    value = max(value, item)
            return value
        arities = {'abs': (1, 1), 'round': (1, 2)}
        minimum, maximum = arities.get(name, _MATH_ARITIES.get(name, (0, 0)))
        if not minimum <= len(arguments) <= maximum:
            _error('Calculation function has an invalid argument count.')
        numbers = [_number(value) for value in arguments]
        if name == 'round' and len(numbers) == 2:
            if type(numbers[1]) is not int or abs(numbers[1]) > 100:
                _error('round digits must be an integer between -100 and 100.')
        try:
            if name == 'abs':
                value = abs(numbers[0])
            elif name == 'round':
                value = round(*numbers)
            else:
                value = getattr(math, name)(*numbers)
        except (ArithmeticError, ValueError):
            _error('Calculation function is outside its numeric domain.', 'numeric_error')
        return _number(value)

    def expression(self, node, variables):
        self.enter()
        try:
            return self._expression(node, variables)
        finally:
            self.evaluation_depth -= 1

    def _expression(self, node, variables):
        self.tick()
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            if node.id in variables:
                return variables[node.id]
            if node.id in self.variables:
                return self.variables[node.id]
            _error('Unknown calculation variable; functions are callable only.')
        if isinstance(node, (ast.List, ast.Tuple)):
            self.reserve(len(node.elts))
            values = [self.expression(item, variables) for item in node.elts]
            return self.container(values, tuple if isinstance(node, ast.Tuple) else list)
        if isinstance(node, ast.BinOp):
            return self.binary(node.op, self.expression(node.left, variables), self.expression(node.right, variables))
        if isinstance(node, ast.UnaryOp):
            value = self.expression(node.operand, variables)
            if isinstance(node.op, ast.Not):
                return not value
            if isinstance(node.op, ast.Invert):
                return _number(~_integer(value))
            value = _number(value)
            return _number(-value if isinstance(node.op, ast.USub) else value)
        if isinstance(node, ast.BoolOp):
            for child in node.values:
                value = self.expression(child, variables)
                if (isinstance(node.op, ast.And) and not value) or (isinstance(node.op, ast.Or) and value):
                    break
            return value
        if isinstance(node, ast.Compare):
            left = self.expression(node.left, variables)
            for operation, child in zip(node.ops, node.comparators):
                right = self.expression(child, variables)
                for value in (left, right):
                    if type(value) is not bool:
                        _number(value)
                if isinstance(operation, ast.Eq):
                    matched = left == right
                elif isinstance(operation, ast.NotEq):
                    matched = left != right
                elif isinstance(operation, ast.Lt):
                    matched = left < right
                elif isinstance(operation, ast.LtE):
                    matched = left <= right
                elif isinstance(operation, ast.Gt):
                    matched = left > right
                else:
                    matched = left >= right
                if not matched:
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            selected = node.body if self.expression(node.test, variables) else node.orelse
            return self.expression(selected, variables)
        if isinstance(node, ast.Call):
            return self.call(node.func.id, [self.expression(item, variables) for item in node.args])
        if isinstance(node, ast.Subscript):
            if not isinstance(node.slice, ast.Slice):
                values, index = self.location(node, variables)
                return values[index]
            values = self.sequence(self.expression(node.value, variables))
            bounds = [self.expression(item, variables) if item is not None else None
                      for item in (node.slice.lower, node.slice.upper, node.slice.step)]
            if any(item is not None and type(item) is not int for item in bounds) or bounds[2] == 0:
                _error('Slice bounds require integers and a nonzero step.')
            start, stop, step = slice(*bounds).indices(len(values))
            count = len(range(start, stop, step))
            self.reserve(count)
            self.tick(count)
            total = 1
            for index in range(start, stop, step):
                total += self.shape(values[index], 1)
                if total > MAX_VALUE_NODES:
                    _error('Calculation expanded value size limit exceeded.', 'container_limit')
            return values[slice(*bounds)]
        if isinstance(node, ast.ListComp):
            values, local, total = [], dict(variables), 1

            def generate(index):
                self.enter()
                try:
                    generate_values(index)
                finally:
                    self.evaluation_depth -= 1

            def generate_values(index):
                nonlocal total
                if index == len(node.generators):
                    self.reserve(1)
                    if len(values) >= MAX_CONTAINER_ITEMS:
                        _error('Container item limit exceeded.', 'container_limit')
                    value = self.expression(node.elt, local)
                    total += self.shape(value, 1)
                    if total > MAX_VALUE_NODES:
                        _error('Calculation expanded value size limit exceeded.', 'container_limit')
                    values.append(value)
                    return
                generator = node.generators[index]
                items = self.sequence(self.expression(generator.iter, local))
                for item in items:
                    self.iteration()
                    self.assign(generator.target, item, local)
                    if all(self.expression(condition, local) for condition in generator.ifs):
                        generate(index + 1)

            generate(0)
            return values
        _error('Unsupported calculation expression.')

    def block(self, body, variables):
        for node in body:
            self.statement(node, variables)

    def statement(self, node, variables):
        self.enter()
        try:
            self._statement(node, variables)
        finally:
            self.evaluation_depth -= 1

    def _statement(self, node, variables):
        self.tick()
        if isinstance(node, ast.Assign):
            self.assign(node.targets[0], self.expression(node.value, variables), variables)
        elif isinstance(node, ast.AugAssign):
            # Resolve indexed targets once, before RHS evaluation, as in Python.
            location = self.location(node.target, variables) if isinstance(node.target, ast.Subscript) else None
            value = location[0][location[1]] if location else self.expression(node.target, variables)
            value = self.binary(node.op, value, self.expression(node.value, variables))
            if location:
                self.store(location, value)
            else:
                self.assign(node.target, value, variables)
        elif isinstance(node, ast.Expr):
            self.expression(node.value, variables)
        elif isinstance(node, ast.If):
            self.block(node.body if self.expression(node.test, variables) else node.orelse, variables)
        elif isinstance(node, ast.Return):
            raise _Flow('return', self.expression(node.value, variables))
        elif isinstance(node, ast.Break):
            raise _Flow('break')
        elif isinstance(node, ast.Continue):
            raise _Flow('continue')
        elif isinstance(node, (ast.For, ast.While)):
            items = self.sequence(self.expression(node.iter, variables)) if isinstance(node, ast.For) else None
            index = 0
            while True:
                if items is not None:
                    if index >= len(items):
                        break
                    item = items[index]
                    index += 1
                elif not self.expression(node.test, variables):
                    break
                self.iteration()  # Count even empty/pass/continue loop bodies.
                if items is not None:
                    self.assign(node.target, item, variables)
                try:
                    self.block(node.body, variables)
                except _Flow as control:
                    if control.kind == 'break':
                        break
                    if control.kind != 'continue':
                        raise
        elif not isinstance(node, (ast.FunctionDef, ast.Pass)):
            _error('Unsupported calculation statement.')


def calculate(code, data=None):
    """Return a bounded JSON numeric result; optional input is numeric/list data."""
    tree, functions = _parse(code)
    interpreter = _Interpreter(functions, data)
    final_expression = isinstance(tree.body[-1], ast.Expr)
    interpreter.block(tree.body[:-1] if final_expression else tree.body, interpreter.variables)
    if final_expression:
        value = interpreter.expression(tree.body[-1].value, interpreter.variables)
    elif 'result' in interpreter.variables:
        value = interpreter.variables['result']
    else:
        _error('End with a result expression or assign a variable named result.')
    interpreter.shape(value)
    interpreter.output_size(value)
    encoded = json.dumps(value, allow_nan=False, separators=(',', ':'))
    return {'ok': True, 'value': json.loads(encoded), 'operations': interpreter.operations}


def tool_result(arguments):
    """Convert invalid model arguments/code into a bounded correction result."""
    try:
        if (type(arguments) is not dict or len(arguments) not in (1, 2) or
                any(type(key) is not str for key in arguments) or
                set(arguments) not in ({'code'}, {'code', 'data'})):
            _error('calculate accepts code and optional numeric/list data only.')
        if 'data' in arguments and arguments['data'] is None:
            _error('Explicit data must be finite numeric/bool values or nested lists.')
        return calculate(arguments['code'], arguments.get('data'))
    except CalculationError as error:
        return {'ok': False, 'error_code': error.code, 'error': str(error)}


def policy():
    """Authoritative language contract included only for the selected tool."""
    return (
        'Code uses the calculate tool. Arguments are {"code":"ASCII numeric source"} with optional "data": a finite '
        'int/float/bool or nested numeric lists, including raw pixel arrays. Input is privately copied '
        'and exposed as reserved data; omitted data is []. No image files, PNG/JPEG decoding, strings, '
        'objects or implicit attachment access. Source must contain no quotes or backslashes, even '
        'in comments. End with a result expression or assign result. Supported: finite int/float and '
        'True/False literals, variables, lists/tuples, fixed unpacking, integer indexing, read-only '
        'integer slices, + - * / // % **, integer & | ^ ~ << >> (shift counts 0-255), comparisons, '
        'and/or/not, if statements/expressions, assignments, bounded for/while loops, pass, '
        'break/continue inside loops, and list comprehensions. List elements can be assigned or '
        'augmented with numeric/bool scalars only; container link writes and slice writes are '
        'forbidden, so cycles cannot be created. Existing list aliases share scalar writes. '
        'Concatenation requires matching list/tuple types; no repetition. Top-level def functions '
        'accept ordinary positional parameters without defaults, decorators or annotations. '
        'Calls require matching arity and explicit return of a value on the executed path. '
        'Assignments in functions are local; globals are readable. Functions are declarations '
        'available throughout the program, never values. Static recursive call cycles are rejected '
        'even in dead branches. Function/constant names and data cannot be rebound or used as '
        'parameters. Use bare functions ' + ', '.join(sorted(FUNCTIONS)) + '; constants pi, e, tau. '
        'int/float accept one numeric/bool value; bool accepts one numeric/bool/list/tuple; sum/len '
        'accept one list/tuple, min/max one numeric list/tuple or numeric arguments; range accepts '
        '1-3 integers; round optionally accepts integer digits -100 to 100. No imports or library '
        'readers (including QR libraries), attributes, strings, dictionaries, sets, nested functions, '
        'classes, lambdas, generators, loop-else, async, keyword arguments, input, files, network, '
        'shell, eval, exec or Python bytecode execution. Unsupported syntax is rejected in every branch. '
        'Limits per call: 32768 ASCII source bytes, 4096 AST nodes/depth 48, 2000000 operations, '
        '200000 total loop iterations, 65536 items per container, 1048576 cumulative allocated slots, '
        '262144 expanded value nodes/depth 12, 256 variables per frame, 64 user functions, '
        '16 active function calls, 128 combined evaluation nesting, 64 function arguments, '
        '256-bit integers, finite float magnitude '
        '<=1e100, power exponent magnitude <=1024, JSON result <=65536 bytes. Small numeric/image '
        'algorithms and sample filters must fit these bounds; no compressed image decoder is provided. '
        'A calculation error is a tool observation correctable within the existing tool-call budget. '
    )
