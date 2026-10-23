import { readFileSync } from "node:fs";
import { unzipSync } from "fflate";
import { uncompress } from "./dist/snappy.js";
import { serializeSegment, parseIwa, concat } from "./dist/iwa.js";
const files = unzipSync(readFileSync("../tests/fixtures/layouts-basic-white.key"));
let same=0, diff=0, ex=[];
for (const [name,data] of Object.entries(files)) if (name.endsWith(".iwa")) {
  // raw uncompressed
  const parts=[]; let pos=0;
  while(pos<data.length){const len=data[pos+1]|(data[pos+2]<<8)|(data[pos+3]<<16); parts.push(uncompress(data.subarray(pos+4,pos+4+len))); pos+=4+len;}
  const orig = concat(parts);
  const mine = concat(parseIwa(data).map(serializeSegment));
  if (Buffer.compare(Buffer.from(orig),Buffer.from(mine))===0) same++; else {diff++; ex.push([name, orig.length, mine.length]);}
}
console.log(same, diff, ex.slice(0,10));
