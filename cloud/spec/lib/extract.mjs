// Source-level extraction for values that live inside component bodies (not exported) in the
// studio code. Used by adapter "inject" transforms at bundle time; never modifies studio files.
const OPEN = "([{", CLOSE = ")]}";

/** Text of the balanced bracket group that starts right after `re` matches (re must end before the opener). */
export const grabGroup = (src, re, from = 0) => {
  const m = re.exec(src.slice(from));
  if (!m) throw new Error(`extract: pattern not found: ${re}`);
  let i = from + m.index + m[0].length;
  while (/\s/.test(src[i])) i++;
  if (!OPEN.includes(src[i])) throw new Error(`extract: expected an opening bracket after ${re}, got '${src[i]}'`);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (OPEN.includes(src[j])) depth++;
    else if (CLOSE.includes(src[j]) && --depth === 0) return src.slice(i, j + 1);
  }
  throw new Error(`extract: unbalanced group after ${re}`);
};

/** Expression text after `re` up to the first depth-0 ',' ';' or closing bracket. */
export const grabExpr = (src, re, from = 0) => {
  const m = re.exec(src.slice(from));
  if (!m) throw new Error(`extract: pattern not found: ${re}`);
  const i = from + m.index + m[0].length;
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    const c = src[j];
    if (OPEN.includes(c)) depth++;
    else if (CLOSE.includes(c)) { if (depth === 0) return src.slice(i, j).trim(); depth--; }
    else if ((c === "," || c === ";") && depth === 0) return src.slice(i, j).trim();
  }
  throw new Error(`extract: unterminated expression after ${re}`);
};
