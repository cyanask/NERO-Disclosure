"""Leaf JSON-schema helpers shared by document tools and attachment tools."""


def obj(properties=None, required=None):
    return {'type': 'object', 'properties': properties or {}, 'required': required or [], 'additionalProperties': False}
