/**
 * Raw Snappy compression, the format inside each .iwa chunk.
 *
 * A block starts with the uncompressed length as a varint, followed by
 * elements that are either literal bytes or copies of earlier output.
 * See https://github.com/google/snappy/blob/main/format_description.txt
 */

export function uncompress(input: Uint8Array): Uint8Array {
  let pos = 0;
  let length = 0;
  for (let shift = 0; ; shift += 7) {
    const b = input[pos++];
    if (b === undefined) throw new Error("snappy: truncated length");
    length += (b & 0x7f) * 2 ** shift;
    if (b < 0x80) break;
  }
  const out = new Uint8Array(length);
  let o = 0;
  while (pos < input.length) {
    const tag = input[pos++];
    const kind = tag & 3;
    if (kind === 0) {
      let len = tag >> 2;
      if (len >= 60) {
        const bytes = len - 59;
        len = 0;
        for (let i = 0; i < bytes; i++) len |= input[pos++] << (8 * i);
      }
      len += 1;
      if (pos + len > input.length || o + len > length) throw new Error("snappy: literal out of range");
      out.set(input.subarray(pos, pos + len), o);
      pos += len;
      o += len;
      continue;
    }
    let len: number;
    let offset: number;
    if (kind === 1) {
      len = 4 + ((tag >> 2) & 7);
      offset = ((tag >> 5) << 8) | input[pos++];
    } else if (kind === 2) {
      len = (tag >> 2) + 1;
      offset = input[pos] | (input[pos + 1] << 8);
      pos += 2;
    } else {
      len = (tag >> 2) + 1;
      offset = (input[pos] | (input[pos + 1] << 8) | (input[pos + 2] << 16) | (input[pos + 3] << 24)) >>> 0;
      pos += 4;
    }
    if (offset === 0 || offset > o || o + len > length) throw new Error("snappy: bad copy");
    // Copies may overlap their own output, so go byte by byte.
    for (let i = 0; i < len; i++, o++) out[o] = out[o - offset];
  }
  if (o !== length) throw new Error("snappy: length mismatch");
  return out;
}

const HASH_BITS = 14;
const MAX_BLOCK = 65536;

/** Compress ``input``. Inputs over 64 KiB are fine but match only within 64 KiB windows. */
export function compress(input: Uint8Array): Uint8Array {
  const out = new Writer(input.length + Math.ceil(input.length / 6) + 16);
  out.varint(input.length);
  for (let start = 0; start < input.length; start += MAX_BLOCK) {
    compressBlock(input, start, Math.min(start + MAX_BLOCK, input.length), out);
  }
  return out.finish();
}

function load32(b: Uint8Array, i: number): number {
  return (b[i] | (b[i + 1] << 8) | (b[i + 2] << 16) | (b[i + 3] << 24)) >>> 0;
}

function hash(v: number): number {
  return Math.imul(v, 0x1e35a7bd) >>> (32 - HASH_BITS);
}

function compressBlock(input: Uint8Array, start: number, end: number, out: Writer): void {
  const table = new Int32Array(1 << HASH_BITS).fill(-1);
  let literalStart = start;
  let i = start;
  while (i + 4 <= end) {
    const v = load32(input, i);
    const h = hash(v);
    const candidate = table[h];
    table[h] = i;
    if (candidate < start || i - candidate > 0xffff || load32(input, candidate) !== v) {
      i++;
      continue;
    }
    let len = 4;
    while (i + len < end && input[candidate + len] === input[i + len]) len++;
    emitLiteral(input, literalStart, i, out);
    emitCopy(i - candidate, len, out);
    i += len;
    literalStart = i;
  }
  emitLiteral(input, literalStart, end, out);
}

function emitLiteral(input: Uint8Array, from: number, to: number, out: Writer): void {
  const len = to - from;
  if (len === 0) return;
  const n = len - 1;
  if (n < 60) {
    out.byte(n << 2);
  } else if (n < 0x100) {
    out.byte(60 << 2);
    out.byte(n);
  } else if (n < 0x10000) {
    out.byte(61 << 2);
    out.byte(n & 0xff);
    out.byte(n >> 8);
  } else {
    out.byte(62 << 2);
    out.byte(n & 0xff);
    out.byte((n >> 8) & 0xff);
    out.byte(n >> 16);
  }
  out.bytes(input.subarray(from, to));
}

function emitCopy(offset: number, len: number, out: Writer): void {
  while (len > 0) {
    // Leave at least 4 bytes for the last copy, since copies are 4 bytes or more.
    let n = Math.min(len, 64);
    if (len - n > 0 && len - n < 4) n = len - 4;
    if (n >= 4 && n <= 11 && offset < 2048) {
      out.byte(1 | ((n - 4) << 2) | ((offset >> 8) << 5));
      out.byte(offset & 0xff);
    } else {
      out.byte(2 | ((n - 1) << 2));
      out.byte(offset & 0xff);
      out.byte(offset >> 8);
    }
    len -= n;
  }
}

class Writer {
  private buf: Uint8Array;
  private pos = 0;

  constructor(size: number) {
    this.buf = new Uint8Array(Math.max(size, 16));
  }

  private reserve(n: number): void {
    if (this.pos + n <= this.buf.length) return;
    const bigger = new Uint8Array(Math.max(this.buf.length * 2, this.pos + n));
    bigger.set(this.buf.subarray(0, this.pos));
    this.buf = bigger;
  }

  byte(b: number): void {
    this.reserve(1);
    this.buf[this.pos++] = b;
  }

  bytes(b: Uint8Array): void {
    this.reserve(b.length);
    this.buf.set(b, this.pos);
    this.pos += b.length;
  }

  varint(n: number): void {
    while (n >= 0x80) {
      this.byte((n & 0x7f) | 0x80);
      n = Math.floor(n / 128);
    }
    this.byte(n);
  }

  finish(): Uint8Array {
    return this.buf.slice(0, this.pos);
  }
}
