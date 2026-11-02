# Sparse Structure Viewer

The Sparse Structure Viewer provides a paged view of the chunk layout of an Android Sparse Image. It is available from the **Sparse structure** button in the main toolbar.

## Validation before browsing

Click **Validate and load** to run the normal full Sparse inspection first. This validates the file header, chunk structure, payloads, per-chunk CRC32 checkpoints, and image-level checksum where present. The viewer does not mark rows as verified until that full inspection succeeds.

After validation, the viewer reads chunk headers again to populate pages. It does not load the entire chunk table or file contents into memory. The default page size is 200 rows. Changing the type filter, search, or page causes another bounded scan of chunk metadata.

The file's size, modification timestamp, and file identity are checked between validation, page reads, and exports. If the source changes, the cached validation is discarded and the file must be validated again.

## Table columns

- **Index** — one-based display index of the chunk.
- **Type** — `RAW`, `FILL`, `DONT_CARE`, or `CRC32`.
- **File offset** — location of the chunk header in the Sparse file.
- **RAW offset** — logical output offset where the data begins.
- **Blocks** — number of output blocks represented by the chunk (CRC32 checkpoints have no output blocks).
- **Stored** — total bytes occupied by the chunk in the Sparse file, including its header.
- **Expanded** — number of logical RAW bytes represented by the chunk.
- **Checksum** — stored CRC32 value for CRC32 checkpoint chunks, when present.
- **Status** — indicates that the preceding full validation succeeded; CRC32 checkpoint rows are labelled separately.

Select a row to inspect additional offsets, payload size, block count, checksum, and FILL pattern details.

## Search and filters

Use the type selector to show one chunk type or all types. Search matches the displayed index, type code, file/RAW offsets, block count, stored/expanded sizes, checksum, and FILL pattern. Results are paginated; previous/next controls do not retain the full result set in memory.

## Export

After a successful full validation, export the complete chunk table as CSV or JSON. Export runs in a background worker, updates progress, and can be cancelled. The exporter streams one chunk record at a time to a temporary file, then atomically publishes the completed export. Existing files are not replaced unless the user explicitly confirms overwrite. The export contains metadata and chunk layout only; it does not include or copy RAW payload contents.

For the underlying format and CLI conversion options, see the [CLI guide](cli-guide.md).
