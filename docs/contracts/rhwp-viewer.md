# rhwp Viewer Integration Contract

> Status: DRAFT v0.1  
> Target: `@rhwp/core@0.8.6`

## Boundary

- Backend stores the authoritative HWP/HWPX/PDF bytes and exposes render-safe source URLs.
- Frontend renders HWP/HWPX with `@rhwp/core` WebAssembly.
- Frontend renders PDF with PDF.js or the browser PDF viewer.
- Extracted text is a comparison/search layer. It must not replace the visual document.

## Document metadata

`GET /api/v1/notices/{notice_id}` returns each latest-version document with:

```json
{
  "id": "uuid",
  "name": "공고문.hwpx",
  "viewer_type": "RHWP",
  "render_source_url": "/api/v1/notices/.../source",
  "text_url": "/api/v1/notices/.../text",
  "preview_url": null,
  "file_sha256": "...",
  "extracted_text_sha256": "..."
}
```

`viewer_type` values:

- `RHWP`: fetch `render_source_url` as `ArrayBuffer` and render it with rhwp.
- `PDF`: embed `preview_url`; use `text_url` for page-level comparison text.
- `DOWNLOAD`: no supported inline renderer; retain the original download action.

## HWP/HWPX frontend flow

```ts
import init, { HwpDocument } from "@rhwp/core";

await init({ module_or_path: "/rhwp_bg.wasm" });

const response = await fetch(`${API_BASE_URL}${document.render_source_url}`);
if (!response.ok) throw new Error(`document fetch failed: ${response.status}`);

const bytes = new Uint8Array(await response.arrayBuffer());
const hwp = new HwpDocument(bytes);
const firstPageSvg = hwp.renderPageSvg(0);
```

Mount the generated SVG inside an isolated viewer component. Keep the source URL and
original-download action available even when rendering fails.

## Comparison locations

`GET {text_url}` returns `text` and `blocks`.

- PDF block: `page`, `location`, `text`
- HWP/HWPX block: `section_index`, `paragraph_index`, `location`, `text`

The comparison result should reference stable source identifiers rather than copying
only a page label:

```json
{
  "document_id": "uuid",
  "document_sha256": "...",
  "block_index": 41,
  "page": 4,
  "section_index": 0,
  "paragraph_index": 41,
  "quote": "최근 3년 이내 유사사업 수행실적..."
}
```

rhwp layout coordinates can later extend this object with `x`, `y`, `width`, and
`height` without changing the source identity.

## Accuracy rule

rhwp output is a preview produced by its layout engine, not proof of pixel identity
with Hancom Office. The original file remains authoritative. Regression-test the
actual G2B corpus, especially fonts, tables, floating objects, headers, and footnotes.
