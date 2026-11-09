"""Check reconstructed source without importing or executing the application."""
from pathlib import Path
import ast
import dis
import json
import marshal
import types
import warnings

ROOT = Path(__file__).resolve().parents[1]


def walk(code):
    yield code
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            yield from walk(value)


def constant(value):
    if isinstance(value, types.CodeType):
        return ("code", value.co_name)
    if isinstance(value, tuple):
        return ("tuple", tuple(constant(v) for v in value))
    if isinstance(value, frozenset):
        return ("frozenset", tuple(sorted(repr(constant(v)) for v in value)))
    return (type(value).__name__, repr(value))


def signature(code):
    instructions = []
    for instruction in dis.get_instructions(code):
        if instruction.opname in ("RESUME", "NOP"):
            continue
        if instruction.opcode in dis.hasjabs or instruction.opcode in dis.hasjrel:
            # Keep actual destination offsets for a conservative comparison.
            argument = instruction.argval
        else:
            argument = constant(instruction.argval)
        instructions.append((instruction.opname, argument))
    return (code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount,
            code.co_flags, tuple(instructions), code.co_exceptiontable)


def main():
    rows = []
    for source in sorted((ROOT / "decompiled-raw").glob("*.py")):
        text = source.read_text(encoding="utf-8")
        original = marshal.loads((ROOT / "bytecode" / (source.stem + ".pyc")).read_bytes()[16:])
        syntax_error = None
        with warnings.catch_warnings(record=True) as found:
            warnings.simplefilter("always")
            try:
                reconstructed = compile(text, str(source), "exec")
            except SyntaxError as error:
                syntax_error = dict(line=error.lineno, message=error.msg)
        original_codes = list(walk(original))
        rebuilt_codes = list(walk(reconstructed)) if not syntax_error else []
        # Qualnames alone are insufficient for repeated lambdas: compare a
        # function only when its qualname is unique in both module versions.
        original_map = {}
        rebuilt_map = {}
        for code in original_codes:
            original_map.setdefault(code.co_qualname, []).append(code)
        for code in rebuilt_codes:
            rebuilt_map.setdefault(code.co_qualname, []).append(code)
        matching, different, ambiguous, missing = [], [], [], []
        for name, codes in original_map.items():
            candidates = rebuilt_map.get(name, [])
            if not candidates:
                missing.append(name)
            elif len(codes) != 1 or len(candidates) != 1:
                ambiguous.append(name)
            elif signature(codes[0]) == signature(candidates[0]):
                matching.append(name)
            else:
                different.append(name)
        tree = ast.parse(text) if not syntax_error else None
        none_calls = [node.lineno for node in ast.walk(tree)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Constant)
                      and node.func.value is None] if tree else []
        rows.append(dict(module=source.stem, syntax_error=syntax_error,
                         compiler_warnings=[str(w.message) for w in found],
                         decompiler_incomplete="Decompyle incomplete" in text,
                         calls_to_none=none_calls,
                         original_code_objects=len(original_codes),
                         reconstructed_code_objects=len(rebuilt_codes),
                         matching_instruction_signatures=matching,
                         different_instruction_signatures=different,
                         ambiguous_qualnames=ambiguous, missing_qualnames=missing))
    report = dict(
        tool="ejfkdev/pycdc v0.8.2",
        source="https://github.com/ejfkdev/pycdc/releases/tag/v0.8.2",
        application_executed=False,
        note="Syntax and conservative instruction comparison only. Different signatures do not prove incorrect behavior; successful parsing does not prove equivalence.",
        module_count=len(rows),
        syntax_valid=sum(row['syntax_error'] is None for row in rows),
        incomplete_modules=[row['module'] for row in rows if row['decompiler_incomplete']],
        modules=rows)
    (ROOT / "reports/decompilation-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != 'modules'}, indent=2))
    print("Instruction-identical unambiguous code objects:", sum(len(row['matching_instruction_signatures']) for row in rows))
    print("Modules containing calls to None:", [row['module'] for row in rows if row['calls_to_none']])


if __name__ == "__main__":
    main()
