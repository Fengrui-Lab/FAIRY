from __future__ import annotations

from functools import wraps
import inspect
from typing import Any, Callable


def type_check(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if args and getattr(args[0], "validate_tool_arguments", False):
            from fairy.tool_utils import ToolArgumentRejection, typed_arguments_exception
            # Direct calls retain Python's missing/extra argument TypeError.
            inspect.signature(func).bind(*args, **kwargs)
            exception = typed_arguments_exception(func, args[0], args[1:], kwargs)
            if exception is not None:
                return ToolArgumentRejection(exception)
        return func(*args, **kwargs)

    return wrapper

