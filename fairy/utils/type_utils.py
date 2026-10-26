from __future__ import annotations

from functools import wraps
import inspect
from typing import Any, Callable


_MISSING = object()


class _LegacyContext:
    def __init__(self, instance: Any) -> None:
        self.instance = instance
        self.clock = getattr(instance, "time_manager", None)
        self.recorder = None
        self.farm_id = getattr(instance, "farm_id", None)
        if self.farm_id is None:
            self.farm_id = getattr(getattr(instance, "_farm_world_app", None), "farm_id", None)
        self.asset_id = getattr(instance, "asset_id", None)
        self.raw_return: Any = _MISSING
        self.original_exception: Exception | None = None
        self.original_traceback = None


def uses_shared_executor(instance: Any, function: Callable[..., Any]) -> bool:
    if getattr(function, "_uses_shared_executor", False):
        return True
    runtime = getattr(instance, "runtime", None)
    return runtime is not None and hasattr(runtime, "executor")


def _legacy_gate(instance: Any, function: Callable[..., Any]):
    from fairy.tool_execution import ToolExecutionError, ToolRegistry
    from fairy.tool_utils import (OperationType, ToolContract, app_tool_parameters_schema,
                                  canonical_json, parameters_schema)

    raw = inspect.unwrap(function)
    public = getattr(raw, "_legacy_tool_public", function)
    name = f"{getattr(instance, 'name', type(instance).__name__)}__{raw.__name__}"
    cache = getattr(instance, "_legacy_tool_gates", None)
    if cache is None:
        cache = {}
        instance._legacy_tool_gates = cache
    explicit = getattr(instance, "validate_tool_arguments", False)
    schema = app_tool_parameters_schema(instance, public) if explicit else parameters_schema(public)
    key = (raw, name, canonical_json(schema)) if explicit else (raw, name)
    if key not in cache:
        contract = ToolContract(
            name, inspect.getdoc(public) or raw.__name__, schema,
            operation_type=getattr(public, "_event_operation_type", None) or OperationType.READ,
            metadata={"legacy_bound_app": getattr(instance, "name", type(instance).__name__),
                      "legacy_class": type(instance).__name__},
        )

        def handler(context, **payload):
            try:
                result = raw(context.instance, **payload)
            except Exception as error:
                context.original_exception = error
                context.original_traceback = error.__traceback__
                raise
            context.raw_return = result
            if isinstance(result, dict) and result.get("error"):
                # Interpret an existing rejection, without duplicating any
                # business rule or inventing a no-side-effect guarantee.
                raise ToolExecutionError(
                    str(result.get("error_code", "OPERATION_REJECTED")), str(result["error"]),
                    details={"legacy_result": result}, stage="execution", partial_effects="unknown",
                )
            return result

        registry = ToolRegistry()
        registry.register(contract, handler)
        registry.freeze({"legacy_bound_app": name, "class": type(instance).__name__})
        cache[key] = registry
    return cache[key], raw, public, name


def legacy_tool_call(instance: Any, function: Callable[..., Any], args=(), kwargs=None, *, captured=False):
    """Use the canonical executor while preserving a legacy method's API.

    Capturing records the original event only. Captured execution uses this
    helper again, so it cannot bypass schema checks. Private domain calls inside
    an executor are deliberately unwrapped and never re-captured.
    """
    from fairy.tool_execution import ToolExecutor, inside_tool_execution
    from fairy.types import EventRegisterer

    kwargs = dict(kwargs or {})
    raw = inspect.unwrap(function)
    if inside_tool_execution() or uses_shared_executor(instance, function):
        return raw(instance, *args, **kwargs)
    registry, raw, public, name = _legacy_gate(instance, function)
    bound = inspect.signature(public).bind(instance, *args, **kwargs)
    bound.apply_defaults()
    arguments = {key: value for key, value in bound.arguments.items() if key not in {"self", "cls"}}
    if getattr(instance, "validate_tool_arguments", False):
        from fairy.tool_utils import SchemaValidationError, bind_app_tool_arguments

        try:
            bind_app_tool_arguments(instance, public, args, kwargs)
            registry.contract(name).validate(arguments)
        except SchemaValidationError as error:
            return {"error": str(error).replace("must be one of", "choose one of")}
    if EventRegisterer.is_capturing() and not captured:
        registry.validate_static(name, arguments)
        return public(instance, *args, **kwargs)
    context = _LegacyContext(instance)
    receipts = getattr(instance, "_legacy_tool_receipts", None)
    if receipts is None:
        receipts = []
        instance._legacy_tool_receipts = receipts
    executor = ToolExecutor(registry, lambda contract, arguments: context,
                            clock=context.clock, recorder=receipts.append)
    result = executor.execute(name, arguments, response_format="legacy")
    if context.original_exception is not None:
        raise context.original_exception.with_traceback(context.original_traceback)
    # Preserve domain warnings, rejection details, and Python return shape.
    if context.raw_return is not _MISSING:
        return context.raw_return
    return result


def type_check(func: Callable[..., Any]) -> Callable[..., Any]:
    raw = inspect.unwrap(func)
    setattr(raw, "_legacy_type_checked", True)
    setattr(raw, "_legacy_tool_public", func)

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not args or not hasattr(args[0], "time_manager"):
            return func(*args, **kwargs)
        # Shared public services already have their own canonical contract.
        if uses_shared_executor(args[0], func):
            return func(*args, **kwargs)
        return legacy_tool_call(args[0], func, args[1:], kwargs)

    return wrapper

