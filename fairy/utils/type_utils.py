from __future__ import annotations

from functools import wraps
import inspect
from typing import Any, Callable


def type_check(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if args and getattr(args[0], "require_explicit_tool_docs", False):
            from fairy.tool_utils import typed_arguments_error
            # Direct calls retain Python's missing/extra argument TypeError.
            inspect.signature(func).bind(*args, **kwargs)
            error = typed_arguments_error(func, args[0], args[1:], kwargs, check_choices=False)
            if error is not None:
                return {"error": error}
        return func(*args, **kwargs)

    return wrapper

