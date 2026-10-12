/** A small ⓘ that explains a number on hover or focus, in place of a paragraph. */
export default function Hint({ text }: { text: string }) {
  return (
    <span className="hint" tabIndex={0} role="img" aria-label={text} title={text}>
      ⓘ
    </span>
  );
}
