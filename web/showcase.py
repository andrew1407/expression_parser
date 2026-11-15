"""Browser-side glue for the GitHub Pages showcase.

Runs the same pipeline as ExpressionDataBuilder (main.py) but collects the
results into a JSON-serialisable dict instead of printing / writing files,
so it needs no graphviz and no filesystem. The package itself is untouched.
"""
from expression_parser.parser.expression_parser import ExpressionParser
from expression_parser.analyzer.syntax_analyzer import SyntaxAnalyzer, SyntaxAnalysisException
from expression_parser.analyzer.tree_nodes import Node, UnaryOperatorNode, BinaryOperatorNode, FunctionNode
from expression_parser.parallel_tree.builder import build_parallel_tree
from expression_parser.parallel_tree.optimizer_tools import open_brackets
from expression_parser.tree_output.str_converter import stringify_tree
from expression_parser.equivalent_forms.distributivity import generate_distributivity_forms
from expression_parser.equivalent_forms.commutativity import generate_commutativity_forms
from expression_parser.conveyor_simulation.dynamic import DynamicConveyor
from expression_parser.conveyor_simulation.utils import flat_operations
from expression_parser.conveyor_simulation.containers import SimulationData, OperationDuration, LAYERS_COUNT


FORMS_LIMIT = 50
# Equivalent forms grow ~2^operations (14 ops ~ 14 s native, slower in WebAssembly),
# so the showcase skips them above this many operations to keep the page responsive.
MAX_FORM_OPERATIONS = 10
ROUND_DIGITS = 4


def token_dict(t) -> dict:
  return dict(type=t.type.value, value=t.value, start=t.start, end=t.end)


def tree_dict(node: Node | None) -> dict | None:
  if node is None or not node.value: return None
  kind = node.__class__.__name__
  match node:
    case UnaryOperatorNode():
      children = [tree_dict(node.expression)]
    case BinaryOperatorNode():
      children = [tree_dict(node.left), tree_dict(node.right)]
    case FunctionNode():
      children = [tree_dict(a) for a in node.args]
    case _:
      children = []
  return dict(kind=kind, label=node.value.value, type=node.value.type.value, children=children)


def tree_depth(node: Node | None) -> int:
  match node:
    case UnaryOperatorNode(): return 1 + tree_depth(node.expression)
    case BinaryOperatorNode(): return 1 + max(tree_depth(node.left), tree_depth(node.right))
    case FunctionNode(): return 1 + max((tree_depth(a) for a in node.args), default=0)
    case Node(): return 1 if node.value else 0
  return 0


def unique_forms(tree: Node, generator) -> list[Node]:
  # same filtering as ExpressionDataBuilder.__get_filtered_equivalent_form
  default = stringify_tree(tree)
  forms = ((stringify_tree(n), n) for n in map(build_parallel_tree, generator(tree)))
  unique = {k: v for k, v in forms if k != default}
  return [open_brackets(n) for n in unique.values()]


def simulation_dict(data: SimulationData) -> dict:
  # mirrors console_output.log_conveyor_data labelling (0_1, 0_2, ...)
  formulas: list[tuple[str, Node]] = []
  find = lambda n: next((k for k, v in formulas if v is n), '')
  steps = []
  for step in data.steps:
    entries = []
    for e in step.layers:
      if e is None:
        entries.append(None)
        continue
      label = find(e)
      if label:
        entries.append(dict(label=label, formula=None, op=e.value.value))
        continue
      label = '0_%d' % (len(formulas) + 1)
      ref = lambda n: find(n) or stringify_tree(n)
      match e:
        case BinaryOperatorNode():
          formula = ' '.join((ref(e.left), e.value.value, ref(e.right)))
        case FunctionNode():
          formula = '%s(%s)' % (e.value.value, ', '.join(ref(a) for a in e.args))
        case _:
          formula = stringify_tree(e)
      formulas.append((label, e))
      entries.append(dict(label=label, formula=formula, op=e.value.value))
    steps.append(dict(tacts=step.tacts, layers=entries))
  params = {p: round(getattr(data, p), ROUND_DIGITS) for p in ('sequential', 'dynamic', 'acceleration', 'efficiency')}
  return dict(layers=data.layers, steps=steps, **params)


def simulate(node: Node) -> dict:
  return simulation_dict(DynamicConveyor.of(node).simulate())


def analyze(expression: str) -> dict:
  result: dict = dict(input=expression, ok=False, stage='parse')
  ep = ExpressionParser(expression)
  tokens = ep.get_tokens()
  result['tokens'] = [token_dict(t) for t in tokens]
  errors = ep.get_exceptions()
  if errors:
    result['errors'] = [dict(message=str(e), symbol=e.symbol, position=e.position) for e in errors]
    return result

  result['stage'] = 'syntax'
  try:
    syntax_tree = SyntaxAnalyzer(tokens).get_tree()
  except SyntaxAnalysisException as e:
    t = e.token
    result['errors'] = [dict(message=str(e), symbol=t.value, position=t.start, end=t.end)]
    return result
  if not syntax_tree.value:
    result['stage'] = 'empty'
    return result

  result['stage'] = 'transform'
  parallel = build_parallel_tree(syntax_tree)
  normalized = open_brackets(parallel)
  result['syntax_tree'] = tree_dict(syntax_tree)
  result['parallel_tree'] = tree_dict(parallel)
  result['normalized_tree'] = tree_dict(normalized)
  result['forms'] = dict(
    original=expression.strip(),
    syntax=stringify_tree(syntax_tree),
    parallel=stringify_tree(parallel),
    normalized=stringify_tree(normalized),
  )
  result['depth'] = dict(syntax=tree_depth(syntax_tree), parallel=tree_depth(parallel))

  operations: list[Node] = []
  flat_operations(normalized, operations)
  result['operations'] = len(operations)
  skipped = len(operations) > MAX_FORM_OPERATIONS
  result['forms_skipped'] = dict(limit=MAX_FORM_OPERATIONS) if skipped else None
  dist = [] if skipped else unique_forms(normalized, generate_distributivity_forms)
  comm = [] if skipped else unique_forms(normalized, generate_commutativity_forms)
  default_str = stringify_tree(normalized)

  def rows(nodes):
    seen, out = {default_str}, []
    for n in nodes:
      s = stringify_tree(n)
      if s in seen: continue
      seen.add(s)
      out.append((s, n))
    return out

  dist_rows, comm_rows = rows(dist), rows(comm)
  result['distributive'] = dict(total=len(dist_rows), items=[s for s, _ in dist_rows[:FORMS_LIMIT]])
  result['commutative'] = dict(total=len(comm_rows), items=[s for s, _ in comm_rows[:FORMS_LIMIT]])

  result['stage'] = 'simulate'
  table = [dict(kind='default', expression=default_str, sim=simulate(normalized))]
  table += [dict(kind='distributive', expression=s, sim=simulate(n)) for s, n in dist_rows]
  table += [dict(kind='commutative', expression=s, sim=simulate(n)) for s, n in comm_rows]
  best = lambda kind: min((r for r in table if r['kind'] == kind), key=lambda r: r['sim']['efficiency'], default=None)
  result['conveyor'] = dict(
    default=table[0],
    distributive=best('distributive'),
    commutative=best('commutative'),
    table=[dict(kind=r['kind'], expression=r['expression'], **{k: v for k, v in r['sim'].items() if k != 'steps'})
           for r in sorted(table, key=lambda r: r['sim']['efficiency'])[:FORMS_LIMIT]],
    table_total=len(table),
    durations={k: getattr(OperationDuration, k) for k in ('PLUS', 'MIN', 'MUL', 'DIV', 'POW', 'FUNCTION')},
    layers=LAYERS_COUNT,
  )
  result['ok'] = True
  result['stage'] = 'done'
  return result
