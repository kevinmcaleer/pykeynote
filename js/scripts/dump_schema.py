"""Write src/schema.json: the protobuf schema keynotejs uses to read .iwa archives.

The message definitions come from keynote-parser (MIT), which extracts them
from Keynote itself. Run with keynote-parser installed:

    python js/scripts/dump_schema.py
"""

import importlib
import json
import os
import pkgutil

from google.protobuf.descriptor import FieldDescriptor

VERSION = "v14_5"

mapping = importlib.import_module(f"keynote_parser.versions.{VERSION}.mapping")
generated = importlib.import_module(f"keynote_parser.versions.{VERSION}.generated")

messages = {}
enums = {}
extensions = []


def label_of(field):
    # protobuf 6 replaced FieldDescriptor.label with is_repeated and is_required.
    if hasattr(field, "is_repeated"):
        return 3 if field.is_repeated else 2 if field.is_required else 1
    return field.label


def default_of(field):
    if label_of(field) == 3 or field.type in (FieldDescriptor.TYPE_MESSAGE, FieldDescriptor.TYPE_GROUP):
        return None
    if field.type == FieldDescriptor.TYPE_ENUM:
        return field.default_value if field.has_default_value else field.enum_type.values[0].number
    value = field.default_value
    if field.type == FieldDescriptor.TYPE_BYTES:
        return value.hex() if value else None
    if isinstance(value, float) and value in (float("inf"), float("-inf")) or value != value:
        return str(value)
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53:
        return str(value)
    return value if value not in (0, "", False) else None


def field_entry(field, name):
    entry = [field.number, name, field.type, label_of(field)]
    if field.type in (FieldDescriptor.TYPE_MESSAGE, FieldDescriptor.TYPE_GROUP):
        entry.append(field.message_type.full_name)
    else:
        entry.append(None)
    packed = label_of(field) == 3 and field.GetOptions().packed
    entry.append(1 if packed else 0)
    d = default_of(field)
    if d is not None:
        entry.append(d)
    return entry


def add_message(desc):
    messages[desc.full_name] = [field_entry(f, f.name) for f in desc.fields]
    for e in desc.enum_types:
        add_enum(e)
    for nested in desc.nested_types:
        add_message(nested)
    extensions.extend(desc.extensions)


def add_enum(desc):
    enums[desc.full_name] = {v.name: v.number for v in desc.values}


for module in pkgutil.iter_modules(generated.__path__):
    if not module.name.endswith("_pb2"):
        continue
    fd = importlib.import_module(f"{generated.__name__}.{module.name}").DESCRIPTOR
    for desc in fd.message_types_by_name.values():
        add_message(desc)
    for desc in fd.enum_types_by_name.values():
        add_enum(desc)
    extensions.extend(fd.extensions_by_name.values())

# Extensions are read as ordinary fields of the message they extend, named by
# their full name.
for ext in extensions:
    target = ext.containing_type.full_name
    if target in messages:
        messages[target].append(field_entry(ext, ext.full_name))

schema = {
    "version": "14.5",
    "types": {str(k): v.DESCRIPTOR.full_name for k, v in sorted(mapping.ID_NAME_MAP.items())},
    "messages": dict(sorted(messages.items())),
    "enums": dict(sorted(enums.items())),
}

out = os.path.join(os.path.dirname(__file__), "..", "src", "schema.json")
with open(out, "w") as fh:
    json.dump(schema, fh, separators=(",", ":"))
    fh.write("\n")
print(f"wrote {out}: {len(schema['types'])} archive types, {len(messages)} messages")
