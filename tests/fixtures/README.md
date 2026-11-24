# Super Image test fixture: multiple extents

`super_multi_extent.img` is a small synthetic Android LP `super` image for
manual GUI checks and regression testing. It is a file-only fixture; it does
not contain device-specific data and must not be flashed to a device.

The `system` logical partition consists of two physically separated linear
extents in metadata order:

1. 8 sectors at source sector 64 (`A` bytes).
2. 8 sectors at source sector 88 (`B` bytes).

The `vendor` partition occupies sectors 72–79 (`V` bytes), physically between
the two `system` extents. Correct extraction of `system` must concatenate the
first and second system extents, not copy the intervening vendor data.

## Manual GUI test

1. Open **Super Image** in the application.
2. Select `super_multi_extent.img` and metadata slot `0`.
3. Read the structure. `system` must show `2` extents; `vendor` must show `1`.
4. Select only `system` and extract it to a new, empty directory.
5. Compare the extracted `system.img` with `expected_system.img` by SHA-256.

Expected SHA-256 values:

| File | Size | SHA-256 |
|---|---:|---|
| `super_multi_extent.img` | 131,072 bytes | `cf01d3aebcec93d6f8de5f49744439f006f9ac8319e463f451c87b38190d9e03` |
| `expected_system.img` | 8,192 bytes | `54f624253436dcd5fe656688f7ddb3a314b4524453ce553a5b39a62ce0de4ee5` |
| `expected_vendor.img` | 4,096 bytes | `7efbe488eeb8ed87554b3b6da2af209fb3271790f63db5bbd2ed98e3c76c42bd` |

In PowerShell, from the project root:

```powershell
Get-FileHash "tests\fixtures\expected_system.img" -Algorithm SHA256
Get-FileHash "C:\path\to\output\system.img" -Algorithm SHA256
```

The two `system.img` hashes must match.

These three `.img` files are required test assets. The repository `.gitignore` explicitly permits `tests/fixtures/*.img`; keep all three files tracked in Git so the Super Image test passes in GitHub Actions on Windows and Linux.
