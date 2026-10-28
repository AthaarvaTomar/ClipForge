"""Service for generating Gemini function-calling declarations from T3 op models (Milestone P1).

Translates strict Pydantic v2 timeline operation schemas into Gemini REST API tool declarations,
inlines nested $defs, resolves OpenAPI/JSON-Schema types to Gemini types, and provides
strict round-trip validation so the model can only emit valid operation shapes.
"""

import copy
import logging
from typing import Any

from pydantic import ValidationError

from app.schemas.timeline_ops import (
    OP_MODEL_MAP,
    BaseTimelineOp,
)

logger = logging.getLogger(__name__)


class TimelineToolValidationError(ValueError):
    """Raised when an emitted tool call cannot be validated against operation models."""

    def __init__(self, message: str, tool_name: str | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.details = details


class TimelineToolSchemaService:
    """Generates Gemini function declarations and validates LLM tool call payloads."""

    @classmethod
    def _json_type_to_gemini_type(cls, prop_type: str | None) -> str:
        """Map JSON Schema primitive types to Gemini API type identifiers."""
        if not prop_type:
            return "STRING"
        mapping = {
            "string": "STRING",
            "integer": "INTEGER",
            "number": "NUMBER",
            "boolean": "BOOLEAN",
            "array": "ARRAY",
            "object": "OBJECT",
        }
        return mapping.get(str(prop_type).lower(), "STRING")

    @classmethod
    def _resolve_schema_node(
        cls,
        node: dict[str, Any],
        defs: dict[str, Any],
    ) -> dict[str, Any]:
        """Recursively inline $ref pointers from $defs and convert types to Gemini format."""
        if "$ref" in node:
            ref_path = node["$ref"]
            ref_name = ref_path.split("/")[-1]
            target_def = defs.get(ref_name, {})
            # Merge target definition and any overrides in the referencing node
            resolved = cls._resolve_schema_node(copy.deepcopy(target_def), defs)
            for k, v in node.items():
                if k != "$ref":
                    resolved[k] = v
            return resolved

        # Handle anyOf / allOf (e.g. nullable fields or unions)
        if "anyOf" in node:
            non_null = [item for item in node["anyOf"] if item.get("type") != "null"]
            if non_null:
                base = cls._resolve_schema_node(non_null[0], defs)
                if "description" in node:
                    base["description"] = node["description"]
                return base

        result: dict[str, Any] = {}

        # Convert type
        raw_type = node.get("type")
        if raw_type:
            result["type"] = cls._json_type_to_gemini_type(raw_type)

        # Description
        if "description" in node:
            result["description"] = node["description"]

        # Enums
        if "enum" in node:
            result["enum"] = [str(x) for x in node["enum"]]

        # Array items
        if "items" in node and isinstance(node["items"], dict):
            result["items"] = cls._resolve_schema_node(node["items"], defs)

        # Object properties
        if "properties" in node and isinstance(node["properties"], dict):
            resolved_props: dict[str, Any] = {}
            for prop_name, prop_node in node["properties"].items():
                # Omit internal discriminator 'type' from LLM parameters
                if prop_name == "type":
                    continue
                resolved_props[prop_name] = cls._resolve_schema_node(prop_node, defs)
            result["properties"] = resolved_props

        # Required fields (filter out 'type' since tool name implies it)
        if "required" in node and isinstance(node["required"], list):
            result["required"] = [req for req in node["required"] if req != "type"]

        return result

    @classmethod
    def generate_function_declaration(cls, op_name: str) -> dict[str, Any]:
        """Generate a single Gemini FunctionDeclaration for a given T3 operation name."""
        model_cls = OP_MODEL_MAP.get(op_name)
        if not model_cls:
            raise ValueError(f"Unknown operation model: '{op_name}'")

        raw_json_schema = model_cls.model_json_schema()
        defs = raw_json_schema.get("$defs", {})

        # Extract top-level description from model docstring
        description = (model_cls.__doc__ or "").strip()

        # Resolve properties and required list
        resolved_params = cls._resolve_schema_node(raw_json_schema, defs)
        resolved_params["type"] = "OBJECT"

        return {
            "name": op_name,
            "description": description,
            "parameters": resolved_params,
        }

    @classmethod
    def get_tool_declarations(cls) -> list[dict[str, Any]]:
        """Generate Gemini FunctionDeclaration items for all 13 timeline operations."""
        return [cls.generate_function_declaration(op_name) for op_name in OP_MODEL_MAP]

    @classmethod
    def get_gemini_tools_payload(cls) -> list[dict[str, Any]]:
        """Generate the complete 'tools' array formatted for Gemini REST API calls."""
        return [
            {
                "functionDeclarations": cls.get_tool_declarations(),
            }
        ]

    @classmethod
    def parse_tool_call(
        cls,
        name: str,
        args: dict[str, Any] | None = None,
    ) -> BaseTimelineOp:
        """Parse and strictly validate a Gemini tool call against its corresponding op model.

        Returns the validated BaseTimelineOp model instance.
        Raises TimelineToolValidationError if validation fails.
        """
        model_cls = OP_MODEL_MAP.get(name)
        if not model_cls:
            raise TimelineToolValidationError(
                f"Unknown tool name '{name}'. Must be one of: {list(OP_MODEL_MAP.keys())}",
                tool_name=name,
            )

        payload = copy.deepcopy(args or {})
        payload["type"] = name

        try:
            return model_cls.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Tool call validation failed for '%s': %s", name, exc)
            raise TimelineToolValidationError(
                f"Invalid arguments for tool '{name}': {exc}",
                tool_name=name,
                details=exc.errors(),
            ) from exc

    @classmethod
    def validate_plan_ops(
        cls,
        ops: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Validate an array of operation dictionaries emitted by an AI planner.

        Each op must contain a valid 'type' or 'name' and valid parameters.
        Returns a list of validated operation dicts ready for TimelineEngine.apply().
        """
        validated_dicts: list[dict[str, Any]] = []
        for index, raw_op in enumerate(ops):
            op_name = raw_op.get("name") or raw_op.get("type") or raw_op.get("op")
            if not op_name or not isinstance(op_name, str):
                raise TimelineToolValidationError(
                    f"Op at index {index} missing required 'name' or 'type' field",
                    details=raw_op,
                )

            # Extract arguments
            if "args" in raw_op and isinstance(raw_op["args"], dict):
                args = raw_op["args"]
            else:
                args = {k: v for k, v in raw_op.items() if k not in ("name", "type", "op")}

            validated_model = cls.parse_tool_call(name=op_name, args=args)
            validated_dicts.append(validated_model.model_dump(mode="json"))

        return validated_dicts
