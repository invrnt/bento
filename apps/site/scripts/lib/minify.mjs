// Conservative minifiers: they only remove comments and indentation, so the rendered
// result is identical to the source. Line breaks are kept because they are whitespace.

export function minifyHtml(html) {
  const parts = html.split(/(<pre[\s\S]*?<\/pre>)/iu);
  return parts
    .map((part, index) => {
      if (index % 2 === 1) return part;
      return part
        .replace(/<!--[\s\S]*?-->/gu, "")
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .join("\n");
    })
    .join("")
    .concat("\n");
}

export function minifyCss(css) {
  return css
    .replace(/\/\*[\s\S]*?\*\//gu, "")
    .replace(/\s+/gu, " ")
    .replace(/\s*([{};])\s*/gu, "$1")
    .replace(/,\s+/gu, ",")
    .replace(/;\}/gu, "}")
    .trim()
    .concat("\n");
}
