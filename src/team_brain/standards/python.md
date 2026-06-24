# Python Coding Standards

## Type Hints
- Type hints are required on all public functions and methods (PEP 484)
- Use `Optional[T]` for nullable parameters, not `T | None` (maintains Python 3.10 compatibility)
- Use `list[T]`, `dict[K, V]` (lowercase) for generics in Python 3.9+
- Return type must be annotated: `def process(x: str) -> dict[str, int]:`
- No bare `Any` types without a comment explaining why it's unavoidable

## Pydantic Models
- Use `pydantic.BaseModel` for all inter-component data contracts
- Field validators should use `@field_validator` (Pydantic v2 style), not `@validator`
- Never pass untyped `dict` between modules — create a Pydantic model instead
- Use `model_dump_json()` for serialization, `model_validate()` for deserialization

## Error Handling
- Never use bare `except:` — always catch specific exception types
- Prefer `except (ValueError, TypeError) as e:` over `except Exception as e:` when the exception type is known
- Re-raise with context: `raise RuntimeError("context message") from e`
- Log the exception before re-raising in library code; let application code decide how to surface it

## File Operations
- Use `pathlib.Path` for all file path operations — never `os.path`
- Use context managers (`with open(...) as f:`) for all file I/O
- Prefer `Path.read_text()` / `Path.write_text()` for simple file reads/writes

## String Formatting
- Use f-strings for string interpolation — not `.format()` or `%s`
- For multi-line strings, use triple-quoted strings
- Do not concatenate strings in a loop; use `"".join([...])`

## Function Design
- Maximum function length: 50 lines — if longer, extract into helpers
- Maximum parameter count: 5 — beyond that, group into a Pydantic model or dataclass
- Functions must do one thing — a function that fetches AND processes AND logs violates this rule
- Prefer returning values over mutating arguments

## Naming
- Variables and functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private helpers: prefix with single underscore `_helper()`
- Test functions: `test_<function_name>_<scenario>` pattern

## Imports
- Standard library imports first, third-party second, local imports third (separated by blank lines)
- Never use wildcard imports: `from module import *` is forbidden
- Prefer explicit imports over imports inside functions (exception: circular import avoidance)
