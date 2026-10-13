/**
 * CSVs are gzipped in the browser before upload: text compresses 3 to 10 times,
 * so big files upload that much faster and fit under the upload cap. The server
 * recognises the gzip header and decompresses as it reads.
 */

// Below this, compressing saves less time than it takes.
export const COMPRESS_FROM_BYTES = 1024 * 1024;

export function canCompress(file: File): boolean {
  return typeof CompressionStream !== "undefined" && typeof file.stream === "function";
}

export async function gzipFile(file: File): Promise<File> {
  const stream = file.stream().pipeThrough(new CompressionStream("gzip"));
  const blob = await new Response(stream).blob();
  return new File([blob], `${file.name}.gz`, { type: "application/gzip" });
}
