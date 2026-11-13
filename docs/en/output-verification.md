# RAW output verification

Read-back verification was introduced during v0.5.0 development and is included in the v0.5.0 release line and the v0.6.0 release candidate and release line.

## What is checked

After the Sparse input has been parsed and its applicable chunk and image checksums have been validated, the converter closes and flushes the RAW staging file. If output verification is enabled, it then:

1. Checks that the staged output is a regular file with the expected logical RAW size.
2. Re-reads the staged file in bounded 1 MiB chunks.
3. Computes SHA-256 over the bytes actually read from the staging file.
4. Compares this digest with the SHA-256 of the expected logical RAW contents accumulated while expanding the Sparse input.
5. Checks that the file identity, size, and modification time did not change during the read-back pass.
6. Publishes the destination atomically only after all checks pass.

This checks the actual staged RAW bytes, not just the input Sparse data or the success of write calls. It is still not a guarantee against later disk, controller, or filesystem corruption after the application exits.

## CLI usage

```bash
python sparse_to_raw.py input_sparse.img output_raw.img --verify-output
python sparse_to_raw.py --merge-parts part.0 part.1 --output merged_raw.img --verify-output
```

The option can be combined with `--json-report`. The JSON result contains an `output_verification` object with `passed`, `method`, expected and actual sizes, expected and actual SHA-256, verified byte count, and elapsed time. `--verify-output` is for operations that create a RAW destination; it cannot be combined with `--info` or `--verify-only`.

## GUI usage

The main conversion window, batch queue, and Merge Sparse dialog include **Verify RAW after writing**. The current development branch enables it by default and persists the preference with the other GUI settings.

## Performance and disk space

Verification performs an additional sequential read of the entire RAW staging file. It therefore increases I/O and elapsed time, especially for multi-gigabyte images. The preflight free-space estimate accounts for the staging output; verification reuses that staging file and does not create a second full-size copy.

## Failure and cancellation behavior

A size mismatch, read error, SHA-256 mismatch, or cancellation prevents the staging file from being committed. The temporary file is removed, and a pre-existing destination is not replaced.

## What this does not do

- It does not compare the compressed Sparse file hash with the RAW hash; those representations are different.
- It does not replace Sparse header, chunk CRC32, or image-checksum validation.
- It does not independently verify a destination after the atomic commit; it verifies the staging file immediately before commit.
