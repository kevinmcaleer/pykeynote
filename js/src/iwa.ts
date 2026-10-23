/**
 * Reading and writing .iwa files.
 *
 * An .iwa file is a series of chunks, each a 4-byte header (a zero byte and
 * a 3-byte little-endian length) followed by Snappy-compressed data. The
 * uncompressed data is a stream of archive segments. Each segment starts
 * with a varint-length ``TSP.ArchiveInfo`` header whose ``message_infos``
 * give the type and length of the protobuf messages that follow it.
 */

import { archiveTypeName, decode, encode, type Message } from "./protobuf.js";
import { compress, uncompress } from "./snappy.js";

/** An archive whose type we don't know, or that failed to decode, kept as raw bytes. */
export class RawArchive {
  constructor(
    readonly typeId: number,
    readonly data: Uint8Array,
  ) {}
}

export interface Segment {
  /** The ``TSP.ArchiveInfo`` header. */
  header: Message;
  objects: (Message | RawArchive)[];
}

const CHUNK_SIZE = 65536;

export function parseIwa(data: Uint8Array, filename = ""): Segment[] {
  const parts: Uint8Array[] = [];
  let pos = 0;
  while (pos < data.length) {
    if (data[pos] !== 0) throw new Error(`${filename}: IWA chunk doesn't start with 0x00`);
    const length = data[pos + 1] | (data[pos + 2] << 8) | (data[pos + 3] << 16);
    const chunk = data.subarray(pos + 4, pos + 4 + length);
    pos += 4 + length;
    parts.push(uncompress(chunk));
  }
  const all = concat(parts);
  const segments: Segment[] = [];
  pos = 0;
  while (pos < all.length) {
    let headerLength = 0;
    for (let shift = 0; ; shift += 7) {
      const b = all[pos++];
      headerLength |= (b & 0x7f) << shift;
      if (b < 0x80) break;
    }
    const header = decode("TSP.ArchiveInfo", all.subarray(pos, pos + headerLength));
    pos += headerLength;
    const objects: (Message | RawArchive)[] = [];
    for (const info of header.message_infos as Message[]) {
      const payload = all.subarray(pos, pos + info.length);
      pos += info.length;
      objects.push(decodeArchive(header, info, payload));
    }
    segments.push({ header, objects });
  }
  return segments;
}

function decodeArchive(header: Message, info: Message, payload: Uint8Array): Message | RawArchive {
  const typeName = archiveTypeName(info.type);
  // Type 0 with should_merge is a patch to another message; keep it as it is.
  if (typeName === undefined || (info.type === 0 && header.should_merge)) {
    return new RawArchive(info.type, payload.slice());
  }
  try {
    return decode(typeName, payload);
  } catch {
    return new RawArchive(info.type, payload.slice());
  }
}

export function serializeSegment(segment: Segment): Uint8Array {
  const bodies = segment.objects.map((o) => (o instanceof RawArchive ? o.data : encode(o)));
  const infos = segment.header.message_infos as Message[];
  bodies.forEach((body, i) => {
    infos[i].length = body.length;
  });
  const header = encode(segment.header);
  const prefix: number[] = [];
  let n = header.length;
  while (n >= 0x80) {
    prefix.push((n & 0x7f) | 0x80);
    n >>>= 7;
  }
  prefix.push(n);
  return concat([Uint8Array.from(prefix), header, ...bodies]);
}

export function serializeIwa(segments: Segment[]): Uint8Array {
  const all = concat(segments.map(serializeSegment));
  const out: Uint8Array[] = [];
  for (let start = 0; start < all.length; start += CHUNK_SIZE) {
    const payload = compress(all.subarray(start, start + CHUNK_SIZE));
    const length = payload.length;
    out.push(Uint8Array.of(0, length & 0xff, (length >> 8) & 0xff, (length >> 16) & 0xff), payload);
  }
  return concat(out);
}

export function concat(parts: Uint8Array[]): Uint8Array {
  let total = 0;
  for (const p of parts) total += p.length;
  const out = new Uint8Array(total);
  let pos = 0;
  for (const p of parts) {
    out.set(p, pos);
    pos += p.length;
  }
  return out;
}
