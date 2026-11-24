# Android Boot Image Inspector

`sparse-to-raw` includes a read-only inspector for Android boot and vendor boot image headers. The CLI command is `boot-info`; the desktop dialog is available from **Tools → Boot Image Inspector**.

## Supported formats

- Legacy Android boot image headers v0, v1, and v2 (`ANDROID!`).
- Generic boot image headers v3 and v4 (`ANDROID!`).
- `vendor_boot` headers v3 and v4 (`VNDRBOOT`).

The version field determines which header layout is parsed. AOSP documents v0 for Android 8 and earlier, v1 for Android 9, v2 for Android 10, v3 for Android 11, and v3/v4 for Android 12 and later devices, depending on launch and GKI configuration. `vendor_boot` was introduced with the GKI boot split; v4 adds a table describing multiple vendor ramdisk fragments. See the official [boot image header](https://source.android.com/docs/core/architecture/bootloader/boot-image-header), [vendor boot partitions](https://source.android.com/docs/core/architecture/partitions/vendor-boot-partitions), [generic boot partition](https://source.android.com/docs/core/architecture/partitions/generic-boot), and AOSP [`bootimg.h`](https://android.googlesource.com/platform/system/tools/mkbootimg/+/refs/heads/android17-release/include/bootimg/bootimg.h).

## CLI

Inspect an image and print the report:

```powershell
py sparse_to_raw.py boot-info boot.img
py sparse_to_raw.py boot-info vendor_boot.img
py sparse_to_raw.py boot-info init_boot.img --json-report init-boot-report.json
py sparse_to_raw.py --lang ru boot-info recovery.img
```

Existing JSON reports are protected from overwrite. Use `--force` only when replacement is intended:

```powershell
py sparse_to_raw.py boot-info boot.img --json-report boot-report.json --force
```

The JSON report includes the detected image type, header version and size, page size, image length, decoded header fields, component offsets and lengths, kernel/ramdisk format hints, trailing-data length, AVB-footer details, and warnings. When a 64-byte AVB footer is found at the end of the file, the inspector reports its version, original image size, VBMeta offset and size, presence of the `AVB0` magic, whether reserved bytes are zero, and structural range-check status. The trailing area is further described as unclassified data before VBMeta, the VBMeta block itself, and unclassified data after VBMeta before the footer when those ranges are consistent. The 64-byte footer layout follows AOSP's [`AvbFooter`](https://android.googlesource.com/platform/external/avb/+/refs/heads/main/libavb/avb_footer.h) definition; footer placement and the VBMeta pointer are also documented in [AOSP avbtool](https://android.googlesource.com/platform/external/avb/+/refs/heads/main/avbtool). For `vendor_boot` v4, it also includes vendor ramdisk table entries with fragment names, types, byte ranges, and board IDs.

## Information shown

For legacy boot v0–v2, the inspector reports the page size, load addresses, board name, kernel command line, OS version and security patch month encoded in the header, legacy image ID, and the kernel, ramdisk, second-stage, recovery DTBO, and DTB section positions where present.

For generic boot v3–v4, it reports the kernel and ramdisk sizes and positions, OS version fields, command line, and v4 boot signature size. The boot signature payload is not cryptographically verified.

For `vendor_boot` v3–v4, it reports the vendor ramdisk, DTB, board name, load addresses, vendor command line, and (for v4) the vendor ramdisk fragment table and bootconfig section. Fragment previews are used only to suggest a common compression/container format.

Kernel and ramdisk format detection is heuristic. For Kernel, it recognizes ARM64 Image, ARM32 zImage, x86 bzImage, and common compressed payload signatures: gzip, bzip2, XZ, Zstandard, LZ4 frame/legacy, LZO/lzop, and LZMA. Ramdisk detection additionally recognizes CPIO newc/crc. A signature must be visible at the beginning of the relevant component.

## GUI

Open **Tools → Boot Image Inspector**, choose `boot.img`, `init_boot.img`, `recovery.img`, or `vendor_boot.img`, and click **Read structure**. The table displays each component's absolute file offset, size, and detected format hint. Select a row to view its parsed details. Use **Export JSON** to save the complete report.

The dialog does not modify the selected image. It opens and reads the file directly and does not create extracted payload files.

## Interpretation and limitations

- An Android boot header does not store the partition filename. A `boot.img` and a `recovery.img` can use the same header format, so the inspector does not claim to distinguish them based on the header alone.
- `init_boot` is reported only as a probable role when a generic boot v3/v4 image has an empty kernel and a non-empty ramdisk. The role is inferred from the image shape, not proven by the header. Android 13 launch devices using GKI place the generic ramdisk in `init_boot`, while upgraded devices may retain a different layout; see the AOSP [generic boot partition](https://source.android.com/docs/core/architecture/partitions/generic-boot) documentation.
- A `valid` footer status means only that the footer/VBMeta structure is internally consistent: ranges are in bounds, `AVB0` is present, reserved bytes are zero, and the footer major version is supported. `warning` indicates caveats (for example an unknown major version or unexpected magic); `invalid` indicates invalid ranges or a zero-sized VBMeta block. Footer handling is structural only. It does not verify the VBMeta contents, embedded digest, cryptographic signature, or trust in the key. Use the AVB / VBMeta Inspector or `avbtool` for a separate AVB verification workflow.
- The inspector does not decompress or extract kernel/ramdisk payloads, unpack CPIO archives, parse DTB/FDT contents, rebuild images, or flash devices.
- It checks header and component boundaries before reading small previews. Format labels are signature-based hints, not a guarantee that the complete payload is valid or bootable.
- Vendor-specific or repackaged formats that do not use the supported AOSP magic/header layouts are not recognized.

Use a separate, trusted extraction or verification workflow when you need to unpack a ramdisk, inspect a device tree, or establish image authenticity.
