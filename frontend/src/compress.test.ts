import { describe, expect, it } from "vitest";
import { canCompress, gzipFile } from "./compress";

describe("gzipFile", () => {
  it.runIf(typeof CompressionStream !== "undefined" && typeof new File([""], "a").stream === "function")(
    "produces a smaller gzip file named .gz that decompresses to the original",
    async () => {
      const text = "date,region,sales\n" + "2024-01-01,North,100\n".repeat(5000);
      const file = new File([text], "sales.csv");
      const gz = await gzipFile(file);
      expect(gz.name).toBe("sales.csv.gz");
      const bytes = new Uint8Array(await gz.arrayBuffer());
      expect([bytes[0], bytes[1]]).toEqual([0x1f, 0x8b]);
      expect(gz.size).toBeLessThan(file.size / 10);
      const back = await new Response(gz.stream().pipeThrough(new DecompressionStream("gzip"))).text();
      expect(back).toBe(text);
    },
  );

  it("reports whether this browser can compress", () => {
    expect(typeof canCompress(new File(["x"], "a.csv"))).toBe("boolean");
  });
});
