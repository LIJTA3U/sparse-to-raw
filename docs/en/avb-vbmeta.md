# AVB / VBMeta Inspector

`sparse-to-raw` includes a read-only Android Verified Boot (AVB) metadata inspector. It accepts a standalone `vbmeta.img` or a partition image with an AVB footer. The command is available in the CLI as `vbmeta-info` and in the GUI under **Tools → AVB / VBMeta Inspector**.

## CLI

```powershell
py sparse_to_raw.py vbmeta-info vbmeta.img
py sparse_to_raw.py vbmeta-info system.img --json-report vbmeta-report.json
```

The JSON report includes the VBMeta header and block sizes, required libavb version, algorithm, rollback index and location, flags, release string, public-key dimensions and SHA-1 / SHA-256 fingerprints, public-key metadata summary, footer information when present, and parsed descriptors. Supported descriptors are Property, Hash, Hashtree, Kernel Cmdline, and Chain Partition. Unknown descriptor tags are retained with their tag and a payload digest.

For supported SHA-256 and SHA-512 AVB algorithms, the inspector computes the embedded digest over the VBMeta header and auxiliary block and compares it with the digest stored in the authentication block. It reports `match`, `mismatch`, or an appropriate not-applicable/unsupported status. The parser also checks declared block boundaries, descriptor lengths, non-overlapping auth/aux regions, and safety limits before reading blocks.

## GUI

Open **Tools → AVB / VBMeta Inspector**, select `vbmeta.img` or an image with an AVB footer, and click **Inspect metadata**. The descriptor table provides a compact summary. Select a row to display the complete parsed descriptor in the details pane. The report becomes available through the main window's JSON report action.

## Security limitations

This tool is a metadata inspector, not a complete AVB verifier. It does **not**:

- verify the RSA signature using the embedded public key;
- compare the key with a trusted key, bootloader trust store, or user-supplied trust anchor;
- compare the rollback index with rollback values stored by a device;
- flash, patch, disable, or otherwise modify AVB metadata or device partitions.

A matching embedded digest confirms only that the digest stored in this VBMeta structure matches the header and auxiliary block read by the inspector. It does not prove that the image was signed by a trusted key or that a device will accept it. Use an independent AVB verification workflow when signature or device-trust validation is required.
