"""DSL JSON Schema（M3）。jsonschema 校验用，错误定位到字段路径。

设计约束（SPEC §7 / §15）：
- 嵌套不超过三层，大量默认值，坐标优先语义化（transform.translate），不写裸像素坐标表。
- color 字段仅在裸原语上允许，pattern 为 #RRGGBB；构件实例颜色经样式调色板后续接入。
"""

HEX = r"^#[0-9a-fA-F]{6}$"

PROJECT_SCHEMA = {
    "type": "object",
    "required": ["seed", "width", "height"],
    "properties": {
        "seed": {"type": "string", "minLength": 1},
        "width": {"type": "integer", "minimum": 1, "maximum": 8192},
        "height": {"type": "integer", "minimum": 1, "maximum": 8192},
        "fps": {"type": "integer", "minimum": 1, "maximum": 120},
        "duration": {"type": "number", "minimum": 0.0, "maximum": 600.0},
        "style": {"type": "string"},
        "background": {"type": "string", "pattern": HEX},
    },
}

STYLE_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "default_ink": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "grayscale": {"type": "boolean"},
        "palette": {
            "type": "object",
            "additionalProperties": {"type": "string", "pattern": HEX},
        },
    },
}

_COMPONENT_PARAM_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {"type": "string"},
        "default": {},
        "lo": {},
        "hi": {},
        "kind": {"type": "string", "enum": ["float", "int", "bool"]},
        "p_true": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}

COMPONENTS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["name", "pattern", "params"],
        "properties": {
            "name": {"type": "string"},
            "pattern": {"type": "string"},
            "params": {"type": "array", "items": _COMPONENT_PARAM_SCHEMA},
        },
    },
}

_TRANSFORM_SCHEMA = {
    "type": "object",
    "properties": {
        "translate": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
        "rotate": {"type": "number"},
        "scale": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 1,
            "maxItems": 2,
        },
    },
}

_ANIM_CHANNEL_SCHEMA = {
    "type": "object",
    "required": ["channel", "keys"],
    "additionalProperties": False,
    "properties": {
        "channel": {"type": "string", "enum": ["translate", "rotate", "scale", "ink_shift"]},
        "ease": {"type": "string", "enum": ["linear", "smooth", "in", "out"]},
        "keys": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["t", "v"],
                "additionalProperties": False,
                "properties": {
                    "t": {"type": "number"},
                    "v": {
                        "oneOf": [
                            {"type": "number"},
                            {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 2,
                                "maxItems": 2,
                            },
                        ]
                    },
                },
            },
        },
    },
}

_TIMELINE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "component": {"type": "string"},
        "primitive": {"type": "string", "enum": ["line", "shape", "dot"]},
        "iid": {"type": "string"},
        "overrides": {"type": "object"},
        "transform": _TRANSFORM_SCHEMA,
        "anim": {"type": "array", "items": _ANIM_CHANNEL_SCHEMA},
        "points": {"type": "array"},
        "ring": {"type": "array"},
        "pos": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
        "width": {"type": "number"},
        "ink": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "r": {"type": "number", "minimum": 0.0},
        "closed": {"type": "boolean"},
        "fill": {"type": "boolean"},
        "color": {"type": "string", "pattern": HEX},
    },
    "anyOf": [{"required": ["component"]}, {"required": ["primitive"]}],
}

TIMELINE_SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {"items": {"type": "array", "items": _TIMELINE_ITEM_SCHEMA}},
}
