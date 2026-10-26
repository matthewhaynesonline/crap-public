/**
 * The ELF library's only DOM code. Downloads hand over exactly the model's
 * bytes: no text encoding, no trailing newline.
 */

/** Opaque bytes, so no browser tries to render the download. */
const OCTET_STREAM = "application/octet-stream";

/**
 * An anchor click rather than `showSaveFilePicker`, which is still
 * Chromium-only. Firefox ignores clicks on detached nodes, hence the append;
 * the `finally` stops a failed click leaking the buffer.
 */
function saveBytes(bytes: Uint8Array, fileName: string): void {
  const url = URL.createObjectURL(new Blob([bytes as BlobPart], { type: OCTET_STREAM }));

  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Returns whether the clipboard accepted the write. The Clipboard API rejects
 * outside a user gesture or a secure context; that's a UI state, not an error.
 */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);

    return true;
  } catch {
    return false;
  }
}

export { saveBytes, copyText };
