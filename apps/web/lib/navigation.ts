/** Authentication boundaries deliberately force a fresh document. */
export function replaceWith(href: string) {
  window.location.replace(href);
}
