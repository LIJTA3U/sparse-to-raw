# sparse-to-raw v0.6.0

Stable release of the v0.6.0 feature line.

## Highlights

- Streaming conversion from RAW to Android Sparse v1.0 with RAW, FILL, and DONT_CARE chunks, CRC32, optional SHA-256, cancellation, and JSON reports.
- Logical RAW/Sparse comparison without intermediate RAW files, including first-difference offsets and logical SHA-256 hashes.
- Standalone Sparse Validator for headers, chunk layout, block accounting, CRC32 checkpoints, image checksum, and trailing data.
- Reusable JSON Batch Profiles for mixed Sparse → RAW, RAW → Sparse, and QFIL queues.
- Qualcomm QFIL XML analysis and RAW assembly by physical partition. Patch commands are reported but not executed.
- Structured JSON reports for conversion, output verification, validation, comparison, QFIL, and batch operations.
- English/Russian CLI and GUI.

## Windows downloads

The GitHub Actions Windows workflow builds and attaches:

- `sparse-to-raw.exe` — standalone CLI.
- `sparse-to-raw-gui.exe` — standalone GUI executable.
- `sparse-to-raw-gui-windows.zip` — folder-based GUI package. Extract the complete folder and keep its directory structure intact.
- `SHA256SUMS.txt` — SHA-256 checksums for the three application packages.

The packaged application was confirmed to run on a Windows computer without Python installed.

## Compatibility validation scope

Byte-for-byte comparison against `simg2img.exe` was performed on two real Android Sparse images: Blackview factory `super.img` (approximately 3.6 GB) and Google Pixel factory `userdata_exp.ai.img` (approximately 6.83 GB). Both comparisons matched. This is a limited validation sample and does not certify every vendor-specific Sparse variant or firmware layout.

Android Dynamic Partitions (`super`) containers and arbitrary multi-file `super_*` layouts are outside the tested scope. The [4PDA discussion, posts #5464–#5481](https://4pda.to/forum/index.php?showtopic=496786&st=5460) describes a ten-file Vivo V70 Elite `super` layout and explains why it must not be blindly concatenated with `copy /b` or assumed to be one standalone Sparse v1 file. This case has not been tested with `sparse-to-raw`.

## Safety and limitations

- The utility processes files only. It does not flash devices or communicate with connected phones.
- QFIL patch commands are parsed and included in reports, but they are not executed.
- `--merge-parts` is for independent, valid Sparse v1 inputs; it is not a Dynamic Partitions parser or arbitrary split-container reconstruction tool.
- For critical firmware work, independently verify output images before use.

