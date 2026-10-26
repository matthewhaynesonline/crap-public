import { err, ok, type Result } from "../result";

const checkedSource: unique symbol = Symbol("checked GGUF source");

/** Local GGUF files, checked for readable headers and a complete shard set. */
interface LocalGgufSource {
  readonly kind: "local";
  readonly [checkedSource]: true;
  readonly files: readonly [File, ...File[]];
  readonly totalBytes: number;
}

/** A public GGUF download URL; split models name their first shard. */
interface UrlGgufSource {
  readonly kind: "url";
  readonly [checkedSource]: true;
  readonly url: string;
  /** Whether the URL names the first shard of a split model. */
  readonly split: boolean;
}

type GgufSource = LocalGgufSource | UrlGgufSource;

const SHARD_NAME = /^(.*)-(\d{5})-of-(\d{5})\.gguf$/i;

/**
 * Parse a download target without allowing credentials or insecure remote hosts.
 *
 * The server must allow browser CORS requests, including HEAD. This checks the
 * URL, not availability or model contents; the runtime owns those checks.
 * @param value - An HTTPS GGUF URL, or a loopback HTTP URL for local testing.
 */
function readGgufUrl(value: string): Result<UrlGgufSource, string> {
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    return err("Enter a complete HTTPS URL to a GGUF file.");
  }

  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) {
    return err("Use HTTPS for remote models. HTTP is allowed only on localhost.");
  }
  if (url.username !== "" || url.password !== "" || url.search !== "" || url.hash !== "") {
    return err("Use a public GGUF URL without credentials, query parameters or a fragment.");
  }
  if (!url.pathname.endsWith(".gguf")) {
    return err("The download URL must end in .gguf. On Hugging Face, use /resolve/, not /blob/.");
  }
  if (url.hostname === "huggingface.co" && !url.pathname.includes("/resolve/")) {
    return err("Use the Hugging Face /resolve/ download URL, not the file's web page.");
  }
  const shard = url.pathname.match(SHARD_NAME);
  if (shard !== null && (Number(shard[2]) !== 1 || Number(shard[3]) < 1)) {
    return err("For a split GGUF, use the URL of the first shard (00001).");
  }

  return ok({ kind: "url", [checkedSource]: true, url: url.href, split: shard !== null });
}

/**
 * Check local files before asking the runtime to allocate model memory.
 *
 * This checks the container header and shard names, not tensor integrity.
 * The runtime still owns architecture and tensor validation.
 * @param selected - Files from the picker, in any order.
 * @returns A complete source, or a message explaining how to fix the selection.
 */
async function readGgufSource(selected: readonly File[]): Promise<Result<LocalGgufSource, string>> {
  const files = [...selected].sort((left, right) => left.name.localeCompare(right.name));
  const first = files[0];

  if (first === undefined) {
    return err("Choose a GGUF file, or all shards of a split model.");
  }

  const firstShard = first.name.match(SHARD_NAME);

  if (firstShard === null && files.length !== 1) {
    return err("Choose one model. Multiple files must be shards of the same split GGUF.");
  }

  if (firstShard !== null) {
    const count = Number(firstShard[3]);
    const complete =
      files.length === count &&
      files.every((file, index) => {
        const shard = file.name.match(SHARD_NAME);

        return (
          shard !== null &&
          shard[1] === firstShard[1] &&
          Number(shard[2]) === index + 1 &&
          Number(shard[3]) === count
        );
      });

    if (!complete) {
      return err(`Choose all ${count} shards of ${firstShard[1]}, with no duplicates.`);
    }
  }

  for (const file of files) {
    try {
      const header = new Uint8Array(await file.slice(0, 24).arrayBuffer());
      const version = header.length >= 8 ? new DataView(header.buffer).getUint32(4, true) : 0;

      if (
        header.length < 24 ||
        String.fromCharCode(...header.slice(0, 4)) !== "GGUF" ||
        (version !== 2 && version !== 3)
      ) {
        return err(`${file.name} is not a supported GGUF v2/v3 file.`);
      }
    } catch {
      return err(`Could not read ${file.name}. Choose the file again.`);
    }
  }

  return ok({
    kind: "local",
    [checkedSource]: true,
    files: [first, ...files.slice(1)],
    totalBytes: files.reduce((sum, file) => sum + file.size, 0),
  });
}

export { readGgufSource, readGgufUrl, type GgufSource };
