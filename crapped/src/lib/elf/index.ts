/** Public surface of the ELF library: parse model output, inspect it, save it. */

export { parseHex, toHex, hexDump, DUMP_WIDTH, type DumpRow } from "./hex";
export {
  inspect,
  CODE_OFFSET,
  type Inspection,
  type ElfImage,
  type ElfHeader,
  type Segment,
  type ConsistencyNote,
} from "./inspect";
export { decode, type Instruction, type Register } from "./x86";
export { saveBytes, copyText } from "./download";
