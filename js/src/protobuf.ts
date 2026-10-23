/**
 * A protobuf codec driven by the Keynote schema in ``schema.json``.
 *
 * Messages are plain objects. A field is present when the object has it as
 * an own property; reading an absent scalar gives its default, and reading
 * an absent repeated field gives an empty array that becomes part of the
 * message. Absent sub-messages read as ``undefined``; use {@link ensure} to
 * create one. 64-bit integers are numbers when they fit in a double exactly,
 * otherwise bigints. Fields the schema doesn't know are kept as raw bytes
 * and written back unchanged.
 */

import schemaJson from "./schema.json" with { type: "json" };

/** [number, name, type, label, message type, packed, default?] */
type FieldTuple = [number, string, number, number, string | null, number, unknown?];

interface Schema {
  version: string;
  types: Record<string, string>;
  messages: Record<string, FieldTuple[]>;
  enums: Record<string, Record<string, number>>;
}

const schema = schemaJson as unknown as Schema;

export const KEYNOTE_VERSION = schema.version;

// Field types, as in google/protobuf/descriptor.proto.
const DOUBLE = 1, FLOAT = 2, INT64 = 3, UINT64 = 4, INT32 = 5, FIXED64 = 6, FIXED32 = 7, BOOL = 8;
const STRING = 9, MESSAGE = 11, BYTES = 12, UINT32 = 13, ENUM = 14, SFIXED32 = 15, SFIXED64 = 16;
const SINT32 = 17, SINT64 = 18;
const REPEATED = 3;

export interface Field {
  number: number;
  name: string;
  type: number;
  repeated: boolean;
  packed: boolean;
  messageType: string | null;
  defaultValue: unknown;
}

interface MessageInfo {
  name: string;
  fields: Field[];
  byNumber: Map<number, Field>;
  byName: Map<string, Field>;
  prototype: object;
}

export const TYPE = Symbol("keynotejs.type");
const UNKNOWN = Symbol("keynotejs.unknown");

/** A decoded protobuf message. */
export type Message = { [field: string]: any; readonly [TYPE]: string };

const infos = new Map<string, MessageInfo>();

function scalarDefault(type: number): unknown {
  switch (type) {
    case BOOL:
      return false;
    case STRING:
      return "";
    case BYTES:
      return new Uint8Array(0);
    default:
      return 0;
  }
}

function parseDefault(field: FieldTuple): unknown {
  const [, , type, , , , value] = field;
  if (value === undefined) return scalarDefault(type);
  if (type === BYTES) return hexToBytes(value as string);
  if (typeof value === "string" && type !== STRING) {
    if (value === "inf") return Infinity;
    if (value === "-inf") return -Infinity;
    if (value === "nan") return NaN;
    return BigInt(value);
  }
  return value;
}

function hexToBytes(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

function info(name: string): MessageInfo {
  let found = infos.get(name);
  if (found) return found;
  const tuples = schema.messages[name];
  if (!tuples) throw new Error(`unknown message type ${name}`);
  const fields = tuples
    .map((t) => ({
      number: t[0],
      name: t[1],
      type: t[2],
      repeated: t[3] === REPEATED,
      packed: t[5] === 1,
      messageType: t[4],
      defaultValue: t[3] === REPEATED || t[2] === MESSAGE ? undefined : parseDefault(t),
    }))
    .sort((a, b) => a.number - b.number);
  const prototype: Record<string | symbol, unknown> = {};
  Object.defineProperty(prototype, TYPE, { value: name });
  for (const f of fields) {
    if (f.repeated) {
      // An absent repeated field reads as an empty array that sticks.
      Object.defineProperty(prototype, f.name, {
        get(this: Record<string, unknown>) {
          const value: unknown[] = [];
          Object.defineProperty(this, f.name, { value, writable: true, enumerable: true, configurable: true });
          return value;
        },
        set(this: Record<string, unknown>, value: unknown) {
          Object.defineProperty(this, f.name, { value, writable: true, enumerable: true, configurable: true });
        },
        configurable: true,
      });
    } else {
      Object.defineProperty(prototype, f.name, {
        get: () => f.defaultValue,
        set(this: Record<string, unknown>, value: unknown) {
          Object.defineProperty(this, f.name, { value, writable: true, enumerable: true, configurable: true });
        },
        configurable: true,
      });
    }
  }
  found = {
    name,
    fields,
    byNumber: new Map(fields.map((f) => [f.number, f])),
    byName: new Map(fields.map((f) => [f.name, f])),
    prototype,
  };
  infos.set(name, found);
  return found;
}

export function hasMessageType(name: string): boolean {
  return name in schema.messages;
}

/** The message type name for an archive type number, e.g. 5 is ``"KN.SlideArchive"``. */
export function archiveTypeName(type: number): string | undefined {
  return schema.types[String(type)];
}

const nameToArchiveType = new Map(Object.entries(schema.types).map(([k, v]) => [v, Number(k)]));

export function archiveTypeNumber(name: string): number | undefined {
  return nameToArchiveType.get(name);
}

/** A value of a protobuf enum, e.g. ``enumValue("KN.TransitionAttributesArchive.TransitionCustomAttributesTimingCurveType", "...EaseInEaseOut")``. */
export function enumValue(enumName: string, valueName: string): number {
  const value = schema.enums[enumName]?.[valueName];
  if (value === undefined) throw new Error(`unknown enum value ${enumName}.${valueName}`);
  return value;
}

/** A new, empty message, optionally with some fields set. */
export function create(type: string, fields: Record<string, unknown> = {}): Message {
  const m = Object.create(info(type).prototype) as Message;
  for (const [k, v] of Object.entries(fields)) m[k] = v;
  return m;
}

export function typeOf(message: Message): string {
  return message[TYPE];
}

export function fieldsOf(type: string): readonly Field[] {
  return info(type).fields;
}

export function field(type: string, name: string): Field {
  const f = info(type).byName.get(name);
  if (!f) throw new Error(`${type} has no field ${name}`);
  return f;
}

/** Whether a field is set. For a repeated field, whether it has any items. */
export function has(message: Message, name: string): boolean {
  if (!Object.hasOwn(message, name)) return false;
  const value = message[name];
  return Array.isArray(value) ? value.length > 0 : value !== undefined;
}

export function clear(message: Message, name: string): void {
  delete message[name];
}

/** The sub-message in ``name``, created empty if it isn't set yet. */
export function ensure(message: Message, name: string): Message {
  if (!has(message, name)) {
    const f = field(message[TYPE], name);
    if (f.type !== MESSAGE || f.repeated) throw new Error(`${message[TYPE]}.${name} isn't a single message field`);
    message[name] = create(f.messageType!);
  }
  return message[name];
}

/** The sub-message in ``name``, or an empty one (not attached) for reading defaults. */
export function sub(message: Message, name: string): Message {
  if (has(message, name)) return message[name];
  const f = field(message[TYPE], name);
  return create(f.messageType!);
}

// --- decoding ----------------------------------------------------------------

const utf8Decoder = new TextDecoder("utf-8", { fatal: false });
const utf8Encoder = new TextEncoder();
const TWO_32 = 2 ** 32;

class Reader {
  pos: number;
  readonly view: DataView;

  constructor(readonly buf: Uint8Array, start = 0, readonly end = buf.length) {
    this.pos = start;
    this.view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  }

  /** A varint as unsigned (lo, hi) 32-bit halves. */
  varint64(): [number, number] {
    let lo = 0;
    let hi = 0;
    let b: number;
    for (let shift = 0; shift < 28; shift += 7) {
      b = this.buf[this.pos++];
      lo |= (b & 0x7f) << shift;
      if (b < 0x80) return [lo >>> 0, 0];
    }
    b = this.buf[this.pos++];
    lo |= (b & 0x0f) << 28;
    hi = (b & 0x7f) >> 4;
    if (b < 0x80) return [lo >>> 0, hi];
    for (let shift = 3; shift < 32; shift += 7) {
      b = this.buf[this.pos++];
      if (b === undefined) throw new Error("protobuf: truncated varint");
      hi |= (b & 0x7f) << shift;
      if (b < 0x80) return [lo >>> 0, hi >>> 0];
    }
    throw new Error("protobuf: varint too long");
  }

  uint32(): number {
    let result = 0;
    for (let shift = 0; ; shift += 7) {
      const b = this.buf[this.pos++];
      if (b === undefined) throw new Error("protobuf: truncated varint");
      if (shift < 28) result |= (b & 0x7f) << shift;
      else if (shift === 28) result |= (b & 0x0f) << 28;
      if (b < 0x80) return result >>> 0;
      if (shift > 63) throw new Error("protobuf: varint too long");
    }
  }

  skip(wireType: number): void {
    switch (wireType) {
      case 0:
        this.varint64();
        break;
      case 1:
        this.pos += 8;
        break;
      case 2:
        this.pos += this.uint32();
        break;
      case 3:
        for (;;) {
          const tag = this.uint32();
          if ((tag & 7) === 4) break;
          this.skip(tag & 7);
        }
        break;
      case 5:
        this.pos += 4;
        break;
      default:
        throw new Error(`protobuf: bad wire type ${wireType}`);
    }
    if (this.pos > this.end) throw new Error("protobuf: field runs past the end");
  }
}

function joinUnsigned(lo: number, hi: number): number | bigint {
  if (hi < 0x200000) return hi * TWO_32 + lo;
  return (BigInt(hi) << 32n) | BigInt(lo);
}

function joinSigned(lo: number, hi: number): number | bigint {
  if (hi & 0x80000000) {
    const value = BigInt.asIntN(64, (BigInt(hi) << 32n) | BigInt(lo));
    return value >= BigInt(Number.MIN_SAFE_INTEGER) ? Number(value) : value;
  }
  return joinUnsigned(lo, hi);
}

function readScalar(r: Reader, type: number): unknown {
  switch (type) {
    case DOUBLE: {
      const v = r.view.getFloat64(r.pos, true);
      r.pos += 8;
      return v;
    }
    case FLOAT: {
      const v = r.view.getFloat32(r.pos, true);
      r.pos += 4;
      return v;
    }
    case INT64: {
      const [lo, hi] = r.varint64();
      return joinSigned(lo, hi);
    }
    case UINT64: {
      const [lo, hi] = r.varint64();
      return joinUnsigned(lo, hi);
    }
    case INT32:
    case ENUM:
      return r.varint64()[0] | 0;
    case UINT32:
      return r.varint64()[0];
    case SINT32: {
      const n = r.varint64()[0];
      return (n >>> 1) ^ -(n & 1);
    }
    case SINT64: {
      const [lo, hi] = r.varint64();
      const v = (BigInt(hi) << 32n) | BigInt(lo);
      const decoded = (v >> 1n) ^ -(v & 1n);
      return Number.isSafeInteger(Number(decoded)) ? Number(decoded) : decoded;
    }
    case FIXED64: {
      const lo = r.view.getUint32(r.pos, true);
      const hi = r.view.getUint32(r.pos + 4, true);
      r.pos += 8;
      return joinUnsigned(lo, hi);
    }
    case SFIXED64: {
      const lo = r.view.getUint32(r.pos, true);
      const hi = r.view.getUint32(r.pos + 4, true);
      r.pos += 8;
      return joinSigned(lo, hi);
    }
    case FIXED32: {
      const v = r.view.getUint32(r.pos, true);
      r.pos += 4;
      return v;
    }
    case SFIXED32: {
      const v = r.view.getInt32(r.pos, true);
      r.pos += 4;
      return v;
    }
    case BOOL: {
      const [lo, hi] = r.varint64();
      return lo !== 0 || hi !== 0;
    }
    default:
      throw new Error(`protobuf: unsupported field type ${type}`);
  }
}

function wireTypeOf(type: number): number {
  switch (type) {
    case DOUBLE:
    case FIXED64:
    case SFIXED64:
      return 1;
    case FLOAT:
    case FIXED32:
    case SFIXED32:
      return 5;
    case STRING:
    case BYTES:
    case MESSAGE:
      return 2;
    default:
      return 0;
  }
}

function decodeInto(message: Message, r: Reader, end: number): void {
  const mi = info(message[TYPE]);
  while (r.pos < end) {
    const tagStart = r.pos;
    const tag = r.uint32();
    const number = tag >>> 3;
    const wireType = tag & 7;
    const f = mi.byNumber.get(number);
    const expected = f ? wireTypeOf(f.type) : -1;
    if (!f || (wireType !== expected && !(f.repeated && wireType === 2 && expected !== 2))) {
      r.skip(wireType);
      const unknown: Uint8Array[] = ((message as any)[UNKNOWN] ??= []);
      unknown.push(r.buf.slice(tagStart, r.pos));
      continue;
    }
    let value: unknown;
    if (f.type === MESSAGE) {
      const len = r.uint32();
      const child = create(f.messageType!);
      decodeInto(child, r, r.pos + len);
      value = child;
    } else if (f.type === STRING) {
      const len = r.uint32();
      value = utf8Decoder.decode(r.buf.subarray(r.pos, r.pos + len));
      r.pos += len;
    } else if (f.type === BYTES) {
      const len = r.uint32();
      value = r.buf.slice(r.pos, r.pos + len);
      r.pos += len;
    } else if (wireType === 2) {
      // Packed repeated scalars.
      const len = r.uint32();
      const stop = r.pos + len;
      const list: unknown[] = message[f.name];
      while (r.pos < stop) list.push(readScalar(r, f.type));
      continue;
    } else {
      value = readScalar(r, f.type);
    }
    if (f.repeated) (message[f.name] as unknown[]).push(value);
    else message[f.name] = value;
  }
  if (r.pos !== end) throw new Error(`protobuf: ${message[TYPE]} overran its length`);
}

export function decode(type: string, bytes: Uint8Array): Message {
  const message = create(type);
  decodeInto(message, new Reader(bytes), bytes.length);
  return message;
}

// --- encoding ----------------------------------------------------------------

class Writer {
  buf = new Uint8Array(256);
  pos = 0;
  private view = new DataView(this.buf.buffer);

  reserve(n: number): void {
    if (this.pos + n <= this.buf.length) return;
    const bigger = new Uint8Array(Math.max(this.buf.length * 2, this.pos + n));
    bigger.set(this.buf.subarray(0, this.pos));
    this.buf = bigger;
    this.view = new DataView(bigger.buffer);
  }

  uint32(n: number): void {
    this.reserve(5);
    n >>>= 0;
    while (n >= 0x80) {
      this.buf[this.pos++] = (n & 0x7f) | 0x80;
      n >>>= 7;
    }
    this.buf[this.pos++] = n;
  }

  varint(value: number | bigint): void {
    if (typeof value === "number" && value >= 0 && value <= 0xffffffff && Number.isInteger(value)) {
      this.uint32(value);
      return;
    }
    let v = BigInt.asUintN(64, BigInt(value));
    this.reserve(10);
    while (v >= 0x80n) {
      this.buf[this.pos++] = Number(v & 0x7fn) | 0x80;
      v >>= 7n;
    }
    this.buf[this.pos++] = Number(v);
  }

  bytes(b: Uint8Array): void {
    this.reserve(b.length);
    this.buf.set(b, this.pos);
    this.pos += b.length;
  }

  fixed32(v: number, signed: boolean): void {
    this.reserve(4);
    if (signed) this.view.setInt32(this.pos, v, true);
    else this.view.setUint32(this.pos, v >>> 0, true);
    this.pos += 4;
  }

  fixed64(v: number | bigint): void {
    this.reserve(8);
    this.view.setBigUint64(this.pos, BigInt.asUintN(64, BigInt(v)), true);
    this.pos += 8;
  }

  float(v: number): void {
    this.reserve(4);
    this.view.setFloat32(this.pos, v, true);
    this.pos += 4;
  }

  double(v: number): void {
    this.reserve(8);
    this.view.setFloat64(this.pos, v, true);
    this.pos += 8;
  }

  finish(): Uint8Array {
    return this.buf.slice(0, this.pos);
  }
}

function writeScalar(w: Writer, type: number, value: any): void {
  switch (type) {
    case DOUBLE:
      return w.double(value);
    case FLOAT:
      return w.float(value);
    case INT64:
    case UINT64:
      return w.varint(value);
    case INT32:
    case ENUM:
      return value < 0 ? w.varint(BigInt(value)) : w.uint32(value);
    case UINT32:
      return w.uint32(value);
    case SINT32:
      return w.uint32(((value << 1) ^ (value >> 31)) >>> 0);
    case SINT64: {
      const v = BigInt(value);
      return w.varint((v << 1n) ^ (v >> 63n));
    }
    case FIXED64:
    case SFIXED64:
      return w.fixed64(value);
    case FIXED32:
      return w.fixed32(value, false);
    case SFIXED32:
      return w.fixed32(value, true);
    case BOOL:
      return w.uint32(value ? 1 : 0);
    default:
      throw new Error(`protobuf: unsupported field type ${type}`);
  }
}

function writeLengthDelimited(w: Writer, body: (w: Writer) => void): void {
  // Write the body after a 5-byte gap, then move it back once its length is known.
  w.reserve(5);
  const lengthAt = w.pos;
  w.pos += 5;
  const bodyStart = w.pos;
  body(w);
  const len = w.pos - bodyStart;
  let lenBytes = 1;
  while (len >= 2 ** (7 * lenBytes)) lenBytes++;
  w.buf.copyWithin(lengthAt + lenBytes, bodyStart, w.pos);
  w.pos = lengthAt;
  w.uint32(len);
  w.pos = lengthAt + lenBytes + len;
}

function encodeInto(message: Message, w: Writer): void {
  const mi = info(message[TYPE]);
  for (const f of mi.fields) {
    if (!Object.hasOwn(message, f.name)) continue;
    const value = message[f.name];
    if (value === undefined) continue;
    const wireType = wireTypeOf(f.type);
    const tag = (f.number << 3) | wireType;
    const items: any[] = f.repeated ? value : [value];
    if (f.repeated && f.packed && wireType !== 2) {
      if (items.length === 0) continue;
      w.uint32((f.number << 3) | 2);
      writeLengthDelimited(w, (w) => {
        for (const item of items) writeScalar(w, f.type, item);
      });
      continue;
    }
    for (const item of items) {
      w.uint32(tag);
      if (f.type === MESSAGE) {
        if (item[TYPE] !== f.messageType) {
          throw new Error(`${mi.name}.${f.name} needs a ${f.messageType}, not ${item[TYPE] ?? typeof item}`);
        }
        writeLengthDelimited(w, (w) => encodeInto(item, w));
      } else if (f.type === STRING) {
        const bytes = utf8Encoder.encode(item);
        w.uint32(bytes.length);
        w.bytes(bytes);
      } else if (f.type === BYTES) {
        w.uint32(item.length);
        w.bytes(item);
      } else {
        writeScalar(w, f.type, item);
      }
    }
  }
  const unknown: Uint8Array[] | undefined = (message as any)[UNKNOWN];
  if (unknown) for (const b of unknown) w.bytes(b);
}

export function encode(message: Message): Uint8Array {
  const w = new Writer();
  encodeInto(message, w);
  return w.finish();
}

/** A deep copy of a message. */
export function clone<T extends Message>(message: T): T {
  return decode(message[TYPE], encode(message)) as T;
}

/** Call ``visit`` on ``message`` and every message nested inside it. */
export function walk(message: Message, visit: (m: Message) => void): void {
  visit(message);
  const mi = info(message[TYPE]);
  for (const f of mi.fields) {
    if (f.type !== MESSAGE || !Object.hasOwn(message, f.name)) continue;
    const value = message[f.name];
    if (value === undefined) continue;
    if (f.repeated) for (const item of value) walk(item, visit);
    else walk(value, visit);
  }
}
