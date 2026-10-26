from __future__ import annotations

import inspect
import json
import math
import re
import types
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Annotated, Any, Callable, Literal, Union, get_args, get_origin, get_type_hints, is_typeddict


class OperationType(Enum):
    READ = "read"
    WRITE = "write"


class ToolAttributeName(Enum):
    APP = "_is_app_tool"
    ENV = "_is_env_tool"
    DATA = "_is_data_tool"
    USER = "_is_user_tool"


class SchemaValidationError(ValueError):
    """An argument disagrees with the same schema supplied to the model."""

    def __init__(self, message: str, *, field: str = "arguments") -> None:
        self.field = field
        super().__init__(message)


def json_value(value: Any) -> Any:
    """Copy supported Python values into finite, portable JSON values."""
    if isinstance(value, Enum):
        return json_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return json_value(asdict(value))
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("NaN and Infinity are not valid tool values")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((json_value(item) for item in value), key=canonical_json)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(json_value(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class ToolParameter:
    """Explicit parameter information, also usable inside Annotated."""

    description: str | None = None
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: float | None = None
    exclusive_maximum: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    min_items: int | None = None
    max_items: int | None = None
    pattern: str | None = None
    enum: tuple[Any, ...] | None = None
    entity_kind: str | None = None

    def to_schema(self) -> dict[str, Any]:
        names = {"unit": "x-unit", "exclusive_minimum": "exclusiveMinimum",
                 "exclusive_maximum": "exclusiveMaximum", "min_length": "minLength",
                 "max_length": "maxLength", "min_items": "minItems", "max_items": "maxItems",
                 "entity_kind": "x-entity-kind"}
        return {names.get(key, key): json_value(value)
                for key, value in asdict(self).items() if value is not None}


ParameterMetadata = ToolParameter
Param = ToolParameter


def _metadata_schema(metadata: Any) -> dict[str, Any]:
    if isinstance(metadata, ToolParameter):
        return metadata.to_schema()
    if isinstance(metadata, str):
        return {"description": metadata}
    if isinstance(metadata, Mapping):
        result = json_value(metadata)
        if "unit" in result:
            result["x-unit"] = result.pop("unit")
        return result
    raise TypeError(f"Unsupported tool parameter metadata: {metadata!r}")


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    raise TypeError(f"Unsupported JSON type: {type(value).__name__}")


def annotation_schema(annotation: Any) -> dict[str, Any]:
    """Translate supported annotations; unsupported types fail registration."""
    if annotation is Any:
        return {}
    if annotation is None or annotation is type(None):
        return {"type": "null"}
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        result = annotation_schema(args[0])
        for metadata in args[1:]:
            result.update(_metadata_schema(metadata))
        return result
    if origin in (Union, types.UnionType):
        return {"anyOf": [annotation_schema(item) for item in args]}
    if origin is Literal:
        values = [json_value(value) for value in args]
        kinds = {_value_type(value) for value in values}
        result = {"enum": values}
        if len(kinds) == 1:
            result["type"] = kinds.pop()
        return result
    if inspect.isclass(annotation) and issubclass(annotation, Enum):
        values = [json_value(item.value) for item in annotation]
        if not values:
            raise TypeError("A public tool cannot use an empty Enum")
        return annotation_schema(Literal[tuple(values)])
    simple = {str: "string", int: "integer", float: "number", bool: "boolean"}
    if annotation in simple:
        return {"type": simple[annotation]}
    if annotation in (list, tuple, set, frozenset, Sequence) or origin in (list, tuple, set, frozenset, Sequence):
        result: dict[str, Any] = {"type": "array"}
        if (origin or annotation) is tuple and args and args[-1] is not Ellipsis:
            result.update(prefixItems=[annotation_schema(item) for item in args], minItems=len(args), maxItems=len(args))
        else:
            result["items"] = annotation_schema(args[0]) if args else {}
        if (origin or annotation) in (set, frozenset):
            result["uniqueItems"] = True
        return result
    if annotation in (dict, Mapping) or origin in (dict, Mapping):
        if args and args[0] not in (str, Any):
            raise TypeError("Tool JSON objects require string keys")
        return {"type": "object", "additionalProperties": annotation_schema(args[1]) if len(args) > 1 else {}}
    if is_typeddict(annotation):
        hints = get_type_hints(annotation, include_extras=True)
        def unwrap(item):
            return get_args(item)[0] if str(get_origin(item)) in {"typing.Required", "typing.NotRequired"} else item
        return {"type": "object", "properties": {key: annotation_schema(unwrap(item)) for key, item in hints.items()},
                "required": sorted(annotation.__required_keys__), "additionalProperties": False}
    if inspect.isclass(annotation) and is_dataclass(annotation):
        return parameters_schema(annotation, skip_self=False, require_annotations=True)
    raise TypeError(f"Unsupported public tool annotation: {annotation!r}")


def _argument_descriptions(function: Callable[..., Any]) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    active = False
    current: str | None = None
    for line in (inspect.getdoc(function) or "").splitlines():
        stripped = line.strip()
        if stripped in {"Args:", "Arguments:", "Parameters:"}:
            active = True
            continue
        if not active:
            continue
        if line and not line[0].isspace():
            active = False
            current = None
            continue
        match = re.match(r"\s+(\w+)(?:\s*\([^)]*\))?\s*:\s*(.*)", line)
        if match:
            current = match.group(1)
            descriptions[current] = match.group(2).strip()
        elif current and stripped:
            descriptions[current] += " " + stripped
    return descriptions


def parameters_schema(function: Callable[..., Any], *, skip_self: bool = True,
                      parameter_metadata: Mapping[str, Any] | None = None,
                      require_annotations: bool = False) -> dict[str, Any]:
    signature = inspect.signature(function)
    hint_target = function.__init__ if inspect.isclass(function) and is_dataclass(function) else function
    hints = get_type_hints(hint_target, include_extras=True)
    descriptions = _argument_descriptions(function)
    metadata = dict(getattr(function, "_tool_parameter_metadata", {}) or {})
    metadata.update(parameter_metadata or {})
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in signature.parameters.items():
        if skip_self and name in {"self", "cls"}:
            continue
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise TypeError(f"Public tool {function.__name__} must declare {name!r} explicitly")
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            raise TypeError(f"Public tool argument {name!r} must accept JSON keyword calls")
        if name not in hints and require_annotations:
            raise TypeError(f"Public tool argument {name!r} needs a type annotation")
        schema = annotation_schema(hints.get(name, str))
        if name in descriptions and "description" not in schema:
            schema["description"] = descriptions[name]
        if name in metadata:
            schema.update(_metadata_schema(metadata[name]))
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
        else:
            schema["default"] = json_value(parameter.default)
        properties[name] = schema
    unknown = set(metadata) - set(properties)
    if unknown:
        raise ValueError(f"Metadata names unknown parameters: {sorted(unknown)}")
    result = {"type": "object", "properties": properties, "required": required, "additionalProperties": False}
    validate_schema_definition(result)
    return result


_SCHEMA_KEYWORDS = {
    "type", "properties", "required", "additionalProperties", "items", "prefixItems",
    "anyOf", "oneOf", "allOf", "enum", "const", "default", "description", "title",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems",
    "minProperties", "maxProperties", "examples", "deprecated", "readOnly", "writeOnly",
    "$schema", "$id", "$comment",
}


def validate_schema_definition(schema: Any) -> None:
    """Reject advertised constraints which the local validator cannot enforce."""
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise TypeError("A tool schema must be a JSON schema object")
    canonical_json(schema)
    unknown = {key for key in schema if key not in _SCHEMA_KEYWORDS and not key.startswith("x-")}
    if unknown:
        raise ValueError(f"Unsupported tool schema keywords: {sorted(unknown)}")
    declared_type = schema.get("type")
    if declared_type is not None:
        kinds = declared_type if isinstance(declared_type, list) else [declared_type]
        if not kinds or any(item not in {"string", "integer", "number", "boolean", "null", "array", "object"} for item in kinds):
            raise ValueError(f"Invalid JSON schema type {declared_type!r}")
    for item in (schema.get("properties") or {}).values():
        validate_schema_definition(item)
    for key in ("items", "additionalProperties"):
        if key in schema:
            validate_schema_definition(schema[key])
    for key in ("prefixItems", "anyOf", "oneOf", "allOf"):
        for item in schema.get(key, []):
            validate_schema_definition(item)
    if "pattern" in schema:
        re.compile(schema["pattern"])
    if "required" in schema and (not isinstance(schema["required"], list) or any(not isinstance(item, str) for item in schema["required"])):
        raise ValueError("required must be a list of parameter names")
    if "properties" in schema and set(schema.get("required", [])) - set(schema["properties"]):
        raise ValueError("Every required parameter must have a declared property")
    for key in ("minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties"):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], int) or schema[key] < 0):
            raise ValueError(f"{key} must be a nonnegative integer")
    for low, high in (("minimum", "maximum"), ("minLength", "maxLength"),
                      ("minItems", "maxItems"), ("minProperties", "maxProperties")):
        if low in schema and high in schema and schema[low] > schema[high]:
            raise ValueError(f"{low} cannot exceed {high}")
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        raise ValueError("enum must contain at least one permitted value")
    for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], (int, float))):
            raise ValueError(f"{key} must be a finite number")
    if "multipleOf" in schema and schema["multipleOf"] <= 0:
        raise ValueError("multipleOf must be positive")
    if "default" in schema:
        validate_schema(schema, schema["default"], path="default")


def validate_schema(schema: Mapping[str, Any] | bool, value: Any, *, path: str = "arguments",
                    apply_defaults: bool = False) -> Any:
    try:
        value = json_value(value)
    except (TypeError, ValueError) as error:
        raise SchemaValidationError(str(error), field=path) from error
    if schema is False:
        raise SchemaValidationError(f"{path} is not permitted", field=path)
    if schema is True:
        return value
    def fail(message: str):
        raise SchemaValidationError(f"{path}: {message}", field=path)
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema:
            matches = []
            for candidate in schema[keyword]:
                try:
                    matches.append(validate_schema(candidate, value, path=path, apply_defaults=apply_defaults))
                except SchemaValidationError:
                    pass
            if not matches or (keyword == "oneOf" and len(matches) != 1):
                fail(f"does not match {keyword}")
            value = matches[0]
    for candidate in schema.get("allOf", []):
        value = validate_schema(candidate, value, path=path, apply_defaults=apply_defaults)
    declared_type = schema.get("type")
    if declared_type:
        accepted = declared_type if isinstance(declared_type, list) else [declared_type]
        actual = _value_type(value)
        if actual not in accepted and not (actual == "integer" and "number" in accepted):
            fail(f"expected {declared_type}, got {actual}")
    if "enum" in schema and not any(canonical_json(value) == canonical_json(item) for item in schema["enum"]):
        fail(f"must be one of {schema['enum']!r}")
    if "const" in schema and canonical_json(value) != canonical_json(schema["const"]):
        fail(f"must equal {schema['const']!r}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        result = dict(value)
        for name in schema.get("required", []):
            if name not in result:
                raise SchemaValidationError(f"{path}: missing required parameter {name!r}", field=f"{path}.{name}")
        if apply_defaults:
            for name, child in properties.items():
                if name not in result and isinstance(child, Mapping) and "default" in child:
                    result[name] = deepcopy(child["default"])
        additional = schema.get("additionalProperties", True)
        for name, item in result.items():
            child = properties.get(name, additional)
            if child is False:
                raise SchemaValidationError(f"{path}: unknown parameter {name!r}", field=f"{path}.{name}")
            result[name] = validate_schema(child, item, path=f"{path}.{name}", apply_defaults=apply_defaults)
        if len(result) < schema.get("minProperties", 0) or len(result) > schema.get("maxProperties", math.inf):
            fail("object size is outside allowed limits")
        return result
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            fail("array size is outside allowed limits")
        if schema.get("uniqueItems") and len({canonical_json(item) for item in value}) != len(value):
            fail("array items must be unique")
        prefix = schema.get("prefixItems", [])
        return [validate_schema(prefix[index] if index < len(prefix) else schema.get("items", True), item,
                                path=f"{path}[{index}]", apply_defaults=apply_defaults) for index, item in enumerate(value)]
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", math.inf):
            fail("string length is outside allowed limits")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            fail(f"must match {schema['pattern']!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for keyword, invalid in (("minimum", lambda limit: value < limit), ("maximum", lambda limit: value > limit),
                                 ("exclusiveMinimum", lambda limit: value <= limit), ("exclusiveMaximum", lambda limit: value >= limit)):
            if keyword in schema and invalid(schema[keyword]):
                fail(f"violates {keyword}={schema[keyword]}")
        if "multipleOf" in schema and not math.isclose(value / schema["multipleOf"], round(value / schema["multipleOf"]), abs_tol=1e-9):
            fail(f"must be a multiple of {schema['multipleOf']}")
    return value


@dataclass(frozen=True)
class ToolContract:
    name: str
    description: str
    parameters_schema: dict[str, Any]
    result_schema: dict[str, Any] | None = None
    operation_type: OperationType | str = OperationType.READ
    routing_parameters: tuple[str, ...] = ()
    semantic_version: str = "1"
    metadata: dict[str, Any] = field(default_factory=dict)
    response_format: str = "data"

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("A tool contract needs a nonempty name")
        object.__setattr__(self, "parameters_schema", deepcopy(self.parameters_schema))
        object.__setattr__(self, "result_schema", deepcopy(self.result_schema))
        object.__setattr__(self, "metadata", json_value(self.metadata))
        object.__setattr__(self, "routing_parameters", tuple(self.routing_parameters))
        if isinstance(self.operation_type, str):
            object.__setattr__(self, "operation_type", OperationType(self.operation_type.lower()))
        if not isinstance(self.semantic_version, str) or not self.semantic_version:
            raise ValueError("semantic_version must be a nonempty string")
        if self.response_format not in {"data", "envelope"}:
            raise ValueError("response_format must be data or envelope")
        validate_schema_definition(self.parameters_schema)
        if self.parameters_schema.get("type") != "object":
            raise ValueError("Tool parameters must be a JSON object")
        if self.parameters_schema.get("additionalProperties") is not False:
            raise ValueError("Tool contracts must explicitly reject unknown parameters")
        unknown = set(self.routing_parameters) - set(self.parameters_schema.get("properties", {}))
        if unknown:
            raise ValueError(f"Unknown routing parameters: {sorted(unknown)}")
        if self.result_schema is not None:
            validate_schema_definition(self.result_schema)

    @classmethod
    def from_callable(cls, function: Callable[..., Any], *, name: str | None = None,
                      description: str | None = None, parameter_metadata: Mapping[str, Any] | None = None, **kwargs):
        return cls(name=name or function.__name__, description=description or inspect.getdoc(function) or "",
                   parameters_schema=parameters_schema(function, parameter_metadata=parameter_metadata,
                                                       require_annotations=True), **kwargs)

    def to_open_ai(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                   "parameters": deepcopy(self.parameters_schema)}}

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": deepcopy(self.parameters_schema),
                "result_schema": deepcopy(self.result_schema), "operation_type": self.operation_type.value,
                "routing_parameters": list(self.routing_parameters), "semantic_version": self.semantic_version,
                "metadata": deepcopy(self.metadata), "response_format": self.response_format}

    def validate(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        return validate_schema(self.parameters_schema, arguments, apply_defaults=True)


@dataclass
class AppToolArg:
    name: str
    arg_type: str
    description: str | None = None
    has_default: bool = False
    default: Any | None = None
    schema: dict[str, Any] | None = None


@dataclass
class AppTool:
    class_name: str
    app_name: str
    name: str
    function_description: str | None
    args: list[AppToolArg]
    function: Callable[..., Any]
    class_instance: Any
    write_operation: bool | None = None
    parameters_schema: dict[str, Any] | None = None
    result_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if getattr(self.class_instance, "validate_tool_arguments", False):
            try:
                arguments = bind_app_tool_arguments(self.class_instance, self.function, args, kwargs)
                validate_schema(self.parameters_schema or app_tool_parameters_schema(
                    self.class_instance, self.function), arguments)
            except (TypeError, SchemaValidationError) as error:
                return {"error": str(error).replace("must be one of", "choose one of")}
        # Legacy apps keep their return values and validation behaviour.
        if inspect.ismethod(self.function) and self.function.__self__ is not None:
            return self.function(*args, **kwargs)
        return self.function(self.class_instance, *args, **kwargs)

    def to_open_ai(self) -> dict[str, Any]:
        if self.parameters_schema is not None:
            schema = deepcopy(self.parameters_schema)
        else:
            properties = {}
            for arg in self.args:
                item = deepcopy(arg.schema) if arg.schema is not None else {"type": _json_type(arg.arg_type)}
                item.setdefault("description", arg.description or "")
                if arg.has_default:
                    item["default"] = json_value(arg.default)
                properties[arg.name] = item
            schema = {"type": "object", "properties": properties,
                      "required": [arg.name for arg in self.args if not arg.has_default], "additionalProperties": False}
        return {"type": "function", "function": {"name": f"{self.app_name}__{self.name}",
                                                   "description": self.function_description or "", "parameters": schema}}


def _json_type(type_name: str) -> str:
    known = {"str": "string", "int": "integer", "float": "number", "bool": "boolean",
             "list": "array", "tuple": "array", "dict": "object", "NoneType": "null"}
    if type_name not in known:
        raise TypeError(f"Unsupported public tool type name {type_name!r}")
    return known[type_name]


def _mark_tool(attr: ToolAttributeName, func: Callable[..., Any] | None = None, **metadata):
    def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
        setattr(function, attr.value, True)
        for key, value in metadata.items():
            if value is not None:
                setattr(function, f"_tool_{key}", value)
        return function
    return decorator if func is None else decorator(func)


def app_tool(func: Callable[..., Any] | None = None, *, parameters=None, parameter_metadata=None,
             description=None, result_schema=None, metadata=None, **_):
    return _mark_tool(ToolAttributeName.APP, func, parameter_metadata=parameter_metadata or parameters,
                      description=description, result_schema=result_schema, metadata=metadata)


def data_tool(func: Callable[..., Any] | None = None, **metadata):
    return _mark_tool(ToolAttributeName.DATA, func, **metadata)


def env_tool(func: Callable[..., Any] | None = None, **metadata):
    return _mark_tool(ToolAttributeName.ENV, func, **metadata)


def user_tool(func: Callable[..., Any] | None = None, **metadata):
    return _mark_tool(ToolAttributeName.USER, func, **metadata)


def agent_tool(func: Callable[..., Any] | None = None, *, doc_enabled: bool = True, **metadata):
    def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
        setattr(function, "is_agent_tool", True)
        if not doc_enabled:
            function.__doc__ = ""
        return app_tool(function, **metadata)
    return decorator if func is None else decorator(func)


def app_tool_parameters_schema(instance: Any, func: Callable[..., Any]) -> dict[str, Any]:
    """Use one declared schema for opted-in discovery and runtime dispatch."""
    schema = parameters_schema(func)
    if getattr(instance, "require_explicit_tool_docs", False):
        descriptions = _argument_descriptions(func)
        actual = set(schema["properties"])
        if set(descriptions) != actual or any(not text.strip() for text in descriptions.values()):
            raise ValueError(
                f"{instance.name}.{func.__name__}: Args must match the declared parameters; "
                f"expected {sorted(actual)}, documented {sorted(descriptions)}"
            )
    # Instance directories describe actual configured farm/seed identities.
    # The same schema validates dispatch; do not inject a fictitious signature.
    for name, values in getattr(instance, "tool_parameter_choices", {}).items():
        if name in schema["properties"]:
            schema["properties"][name]["enum"] = list(values)
    validate_schema_definition(schema)
    return schema


def bind_app_tool_arguments(instance: Any, function: Callable[..., Any], args=(), kwargs=None) -> dict[str, Any]:
    """Bind the real signature and reject numbers a float parameter cannot represent."""
    supplied = args if inspect.ismethod(function) and function.__self__ is not None else (instance, *args)
    bound = inspect.signature(function).bind(*supplied, **dict(kwargs or {}))
    hints = get_type_hints(function, include_extras=True)
    arguments = {key: value for key, value in bound.arguments.items() if key not in {"self", "cls"}}
    for name, value in arguments.items():
        if hints.get(name) is float and type(value) in (int, float):
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise SchemaValidationError(f"Invalid {name}: expected finite float", field=f"arguments.{name}")
    return arguments


def build_tool(instance: Any, func: Callable[..., Any], failure_probability=None) -> AppTool:
    schema = app_tool_parameters_schema(instance, func)
    signature = inspect.signature(func)
    hints = get_type_hints(func, include_extras=True)
    args = []
    for name, parameter in signature.parameters.items():
        if name in {"self", "cls"}:
            continue
        annotation = hints.get(name, str)
        item = schema["properties"][name]
        args.append(AppToolArg(name=name, arg_type=getattr(annotation, "__name__", str(annotation)),
                               description=item.get("description"), has_default=parameter.default is not inspect.Parameter.empty,
                               default=None if parameter.default is inspect.Parameter.empty else parameter.default, schema=deepcopy(item)))
    description = getattr(func, "_tool_description", None) or inspect.getdoc(func)
    bound_farm_id = getattr(instance, "bound_farm_id", None)
    if bound_farm_id is not None:
        description = f"{description or ''}\n\nBound farm: {bound_farm_id}.".strip()
    return AppTool(class_name=instance.__class__.__name__, app_name=getattr(instance, "name", instance.__class__.__name__),
                   name=func.__name__, function_description=description,
                   args=args, function=func, class_instance=instance,
                   write_operation=getattr(func, "_event_operation_type", None) == OperationType.WRITE,
                   parameters_schema=schema, result_schema=getattr(func, "_tool_result_schema", None),
                   metadata=deepcopy(getattr(func, "_tool_metadata", {}) or {}))
