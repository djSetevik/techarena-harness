"""Exact, bounded integer polynomials in an explicitly unconstrained integer.

Only `Let x be an arbitrary integer. Evaluate <expression>.` is interpreted.
Unknown prose/operators/constraints are UNKNOWN. No eval or task-code execution.
"""
import ast
import re
from src.domain import Evidence, FeasibilityResult, Status


def analyze(instruction):
    match = re.fullmatch(r'Let ([A-Za-z]) be an arbitrary integer\.\s*'
                         r'(?:Evaluate|Compute) (.{1,4096})\.', instruction, re.I | re.S)
    if not match:
        from src.solvers import solve_math
        answer = solve_math(instruction)
        if answer is None:
            return FeasibilityResult(Status.UNKNOWN, 'UNSUPPORTED_MATH')
        return FeasibilityResult(Status.SOLVABLE, 'EXACT_WAREHOUSE', scope_complete=True,
                                 answer=answer, parser_version='warehouse-v2')
    variable, expression = match.groups()
    def bounded(polynomial):
        result = {degree: coefficient for degree, coefficient in polynomial.items() if coefficient}
        if any(degree > 8 or coefficient.bit_length() > 4096 for degree, coefficient in result.items()):
            raise ValueError('Polynomial resource limit')
        return result
    def parse(node):
        if isinstance(node, ast.Constant) and type(node.value) is int and node.value.bit_length() <= 128:
            return {0: node.value} if node.value else {}
        if isinstance(node, ast.Name) and node.id == variable:
            return {1: 1}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            sign = -1 if isinstance(node.op, ast.USub) else 1
            return {degree: sign * coefficient for degree, coefficient in parse(node.operand).items()}
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            raise ValueError('Unsupported expression')
        left, right = parse(node.left), parse(node.right)
        result = dict(left) if isinstance(node.op, (ast.Add, ast.Sub)) else {}
        if isinstance(node.op, (ast.Add, ast.Sub)):
            sign = -1 if isinstance(node.op, ast.Sub) else 1
            for degree, coefficient in right.items():
                result[degree] = result.get(degree, 0) + sign * coefficient
        else:
            for degree, coefficient in left.items():
                for other_degree, other_coefficient in right.items():
                    key = degree + other_degree
                    result[key] = result.get(key, 0) + coefficient * other_coefficient
        return bounded(result)
    try:
        tree = ast.parse(expression.strip(), mode='eval')
        if sum(1 for _ in ast.walk(tree)) > 128:
            raise ValueError('Expression resource limit')
        polynomial = bounded(parse(tree.body))
    except (SyntaxError, ValueError, RecursionError):
        return FeasibilityResult(Status.UNKNOWN, 'UNSUPPORTED_MATH_EXPRESSION')
    degree = max(polynomial, default=0)
    if degree == 0:
        return FeasibilityResult(Status.SOLVABLE, 'VARIABLE_CANCELS',
            (Evidence('instruction', 'Exact polynomial reduces to a constant'),),
            scope_complete=True, parser_version='integer-polynomial-v1',
            answer=str(polynomial.get(0, 0)))
    first = polynomial.get(0, 0)
    # A nonconstant degree-d polynomial cannot equal the same constant at d+1
    # distinct points. These bounded evaluations construct an actual witness.
    for value in range(1, degree + 1):
        other = sum(coefficient * value ** exponent for exponent, coefficient in polynomial.items())
        if other != first:
            return FeasibilityResult(Status.UNSOLVABLE, 'FREE_INTEGER_CHANGES_ANSWER',
                (Evidence('instruction', f'{variable}=0 gives {first}; {variable}={value} gives {other}; '
                          'both are admissible arbitrary integers', (str(first), str(other))),),
                scope_complete=True, required_information=(variable,), missing_information=(variable,),
                alternatives_checked=(f'{variable}=0', f'{variable}={value}'),
                parser_version='integer-polynomial-v1')
    return FeasibilityResult(Status.UNKNOWN, 'NO_WITNESS_FOUND')
