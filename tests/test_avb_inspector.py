from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from avb_inspector import AVBImageError, inspect_vbmeta_image, run_vbmeta_cli


def _align(value: int, alignment: int = 8) -> int:
    return (value + alignment - 1) // alignment * alignment


def _property_descriptor(key: bytes, value: bytes) -> bytes:
    total = _align(32 + len(key) + 1 + len(value) + 1)
    following = total - 16
    return struct.pack("!QQQQ", 0, following, len(key), len(value)) + key + b"\0" + value + b"\0" + b"\0" * (total - 32 - len(key) - 1 - len(value) - 1)


def _hash_descriptor() -> bytes:
    name, salt, digest = b"boot", b"salt", b"D" * 32
    total = _align(132 + len(name) + len(salt) + len(digest))
    header = struct.pack(
        "!QQQ32sIIII60s", 2, total - 16, 4096, b"sha256".ljust(32, b"\0"),
        len(name), len(salt), len(digest), 0, b"\0" * 60,
    )
    payload = name + salt + digest
    return header + payload + b"\0" * (total - len(header) - len(payload))


def _hashtree_descriptor() -> bytes:
    name, salt, digest = b"system", b"salt2", b"R" * 32
    total = _align(180 + len(name) + len(salt) + len(digest))
    header = struct.pack(
        "!QQIQQQIIIQQ32sIIII60s",
        1, total - 16, 1, 8192, 8192, 4096, 4096, 4096, 0, 0, 0,
        b"sha256".ljust(32, b"\0"), len(name), len(salt), len(digest), 0, b"\0" * 60,
    )
    payload = name + salt + digest
    return header + payload + b"\0" * (total - len(header) - len(payload))


def _kernel_cmdline_descriptor() -> bytes:
    text = b"rootwait ro"
    total = _align(24 + len(text))
    return struct.pack("!QQII", 3, total - 16, 1, len(text)) + text + b"\0" * (total - 24 - len(text))


def _chain_descriptor() -> bytes:
    name = b"vbmeta_system"
    key = struct.pack("!II", 0, 2048) + b"K" * 512
    total = _align(92 + len(name) + len(key))
    header = struct.pack("!QQIIII60s", 4, total - 16, 2, len(name), len(key), 0, b"\0" * 60)
    payload = name + key
    return header + payload + b"\0" * (total - len(header) - len(payload))


def make_vbmeta(*, algorithm_type: int = 1, include_descriptors: bool = True) -> bytes:
    descriptors = b""
    if include_descriptors:
        descriptors = b"".join((
            _property_descriptor(b"com.android.build", b"test-build"),
            _hash_descriptor(),
            _hashtree_descriptor(),
            _kernel_cmdline_descriptor(),
            _chain_descriptor(),
            struct.pack("!QQQ", 99, 8, 0x1234),
        ))
    key = struct.pack("!II", 0, 2048) + b"M" * 512
    metadata = b"pkmd"
    if algorithm_type == 0:
        auth_size = 0
        hash_offset = hash_size = signature_offset = signature_size = 0
        hash_name = None
    elif algorithm_type in (1, 4):
        hash_name = "sha256" if algorithm_type == 1 else "sha512"
        hash_size = hashlib.new(hash_name).digest_size
        signature_size = 256
        hash_offset = 0
        signature_offset = hash_size
        auth_size = _align(hash_size + signature_size, 64)
    else:
        hash_name = None
        auth_size = 320
        hash_offset, hash_size, signature_offset, signature_size = 0, 32, 32, 256
    aux_size = _align(len(descriptors) + len(key) + len(metadata), 64)
    aux = descriptors + key + metadata
    aux += b"\0" * (aux_size - len(aux))
    header = bytearray(256)
    header[0:4] = b"AVB0"
    struct.pack_into("!IIQQI", header, 4, 1, 0, auth_size, aux_size, algorithm_type)
    struct.pack_into("!10Q", header, 32,
        hash_offset, hash_size, signature_offset, signature_size,
        len(descriptors), len(key), len(descriptors) + len(key), len(metadata),
        0, len(descriptors))
    # rollback_index=12345, flags=1 (hashtree disabled), rollback location=1
    struct.pack_into("!QII", header, 112, 12345, 1, 1)
    header[128:176] = b"avbtool synthetic test\0".ljust(48, b"\0")
    header_bytes = bytes(header)
    if algorithm_type == 0:
        auth = b""
    else:
        digest = hashlib.new(hash_name or "sha256", header_bytes + aux).digest()
        auth = digest + b"S" * signature_size
        auth += b"\0" * (auth_size - len(auth))
    return header_bytes + auth + aux


def make_footer_image(vbmeta: bytes) -> bytes:
    prefix = b"PARTITION-DATA".ljust(4096, b"P")
    padding = b"\0" * ((512 - (len(vbmeta) % 512)) % 512)
    footer = struct.pack("!4sIIQQQ28s", b"AVBf", 1, 0, len(prefix), len(prefix), len(vbmeta), b"\0" * 28)
    return prefix + vbmeta + padding + footer


class AVBInspectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_inspects_header_digest_and_standard_descriptors(self) -> None:
        image = self.root / "vbmeta.img"
        image.write_bytes(make_vbmeta())
        report = inspect_vbmeta_image(image)
        self.assertEqual(report["algorithm"], "SHA256_RSA2048")
        self.assertEqual(report["rollback_index"], 12345)
        self.assertEqual(report["rollback_index_location"], 1)
        self.assertTrue(report["hashtree_disabled"])
        self.assertEqual(report["embedded_hash"]["status"], "match")
        self.assertEqual(report["signature"]["status"], "not-verified")
        self.assertTrue(report["public_key"]["size_consistent"])
        self.assertEqual(report["public_key"]["rsa_bits"], 2048)
        self.assertEqual([item["type"] for item in report["descriptors"]], [
            "PROPERTY", "HASH", "HASHTREE", "KERNEL_CMDLINE", "CHAIN_PARTITION", "UNKNOWN_99"
        ])
        self.assertEqual(report["descriptors"][0]["value"], "test-build")
        self.assertEqual(report["descriptors"][1]["partition_name"], "boot")
        self.assertEqual(report["descriptors"][2]["partition_name"], "system")
        self.assertEqual(report["descriptors"][3]["kernel_cmdline"], "rootwait ro")
        self.assertEqual(report["descriptors"][4]["partition_name"], "vbmeta_system")

    def test_detects_embedded_hash_mismatch_without_claiming_signature_verification(self) -> None:
        raw = bytearray(make_vbmeta())
        raw[256] ^= 0x01
        image = self.root / "bad-hash.img"
        image.write_bytes(raw)
        report = inspect_vbmeta_image(image)
        self.assertEqual(report["embedded_hash"]["status"], "mismatch")
        self.assertEqual(report["signature"]["status"], "not-verified")

    def test_inspects_algorithm_none_vbmeta(self) -> None:
        image = self.root / "unsigned-vbmeta.img"
        image.write_bytes(make_vbmeta(algorithm_type=0, include_descriptors=False))
        report = inspect_vbmeta_image(image)
        self.assertEqual(report["algorithm"], "NONE")
        self.assertEqual(report["embedded_hash"]["status"], "not-applicable")
        self.assertFalse(report["signature"]["present"])
        self.assertEqual(report["descriptor_count"], 0)

    def test_inspects_footer_backed_partition_image(self) -> None:
        image = self.root / "system.img"
        image.write_bytes(make_footer_image(make_vbmeta(include_descriptors=False)))
        report = inspect_vbmeta_image(image)
        self.assertEqual(report["container_type"], "footer-backed-image")
        self.assertEqual(report["footer"]["original_image_size_bytes"], 4096)
        self.assertEqual(report["embedded_hash"]["status"], "match")

    def test_rejects_invalid_magic(self) -> None:
        image = self.root / "not-vbmeta.img"
        image.write_bytes(b"NOPE" + b"\0" * 1024)
        with self.assertRaises(AVBImageError):
            inspect_vbmeta_image(image)

    def test_rejects_authentication_block_out_of_bounds(self) -> None:
        raw = bytearray(make_vbmeta())
        struct.pack_into("!Q", raw, 12, 0x100000)
        image = self.root / "bad-auth-size.img"
        image.write_bytes(raw)
        with self.assertRaises(AVBImageError):
            inspect_vbmeta_image(image)

    def test_rejects_malformed_descriptor_length(self) -> None:
        raw = bytearray(make_vbmeta())
        # The first descriptor starts at the beginning of the auxiliary block.
        descriptor_start = 256 + 320
        struct.pack_into("!Q", raw, descriptor_start + 8, 0xFFFFFFF8)
        # Refresh the embedded digest so parsing reaches the malformed descriptor.
        aux_start = 256 + 320
        aux = bytes(raw[aux_start:])
        raw[256:288] = hashlib.sha256(bytes(raw[:256]) + aux).digest()
        image = self.root / "bad-descriptor.img"
        image.write_bytes(raw)
        with self.assertRaises(AVBImageError):
            inspect_vbmeta_image(image)


    def test_checks_sha512_embedded_digest(self) -> None:
        image = self.root / "vbmeta-sha512.img"
        image.write_bytes(make_vbmeta(algorithm_type=4, include_descriptors=False))
        report = inspect_vbmeta_image(image)
        self.assertEqual(report["algorithm"], "SHA512_RSA2048")
        self.assertEqual(report["embedded_hash"]["status"], "match")
        self.assertEqual(len(report["embedded_hash"]["computed_hash_hex"]), 128)

    def test_rejects_overlapping_authentication_regions(self) -> None:
        raw = bytearray(make_vbmeta(include_descriptors=False))
        # Make the signature overlap the stored hash, then refresh the digest
        # so the parser reaches the independent overlap validation.
        struct.pack_into("!Q", raw, 48, 16)
        aux_start = 256 + 320
        digest = hashlib.sha256(bytes(raw[:256]) + bytes(raw[aux_start:])).digest()
        raw[256:288] = digest
        image = self.root / "overlapping-auth.img"
        image.write_bytes(raw)
        with self.assertRaisesRegex(AVBImageError, "regions overlap"):
            inspect_vbmeta_image(image)

    def test_rejects_oversized_auxiliary_block_before_reading_it(self) -> None:
        raw = bytearray(make_vbmeta(include_descriptors=False))
        struct.pack_into("!Q", raw, 20, 128 * 1024 * 1024 + 64)
        image = self.root / "oversized-aux.img"
        image.write_bytes(raw)
        with self.assertRaisesRegex(AVBImageError, "safety limit"):
            inspect_vbmeta_image(image)


    def test_reports_unknown_algorithm_without_claiming_digest_validation(self) -> None:
        image = self.root / "vbmeta-unknown-algorithm.img"
        image.write_bytes(make_vbmeta(algorithm_type=99, include_descriptors=False))
        report = inspect_vbmeta_image(image)
        self.assertEqual(report["algorithm"], "UNKNOWN_99")
        self.assertEqual(report["embedded_hash"]["status"], "unsupported-algorithm")
        self.assertEqual(report["signature"]["status"], "not-verified")

    def test_cli_writes_json_report_without_overwriting(self) -> None:
        image = self.root / "vbmeta-json.img"
        image.write_bytes(make_vbmeta(include_descriptors=False))
        report_path = self.root / "vbmeta-report.json"
        from contextlib import redirect_stderr, redirect_stdout
        import io

        with redirect_stdout(io.StringIO()):
            first_code = run_vbmeta_cli([str(image), "--json-report", str(report_path)])
        self.assertEqual(first_code, 0)
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["operation"], "avb-vbmeta-inspect")

        stderr = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            second_code = run_vbmeta_cli([str(image), "--json-report", str(report_path)])
        self.assertEqual(second_code, 2)
        self.assertIn("already exists", stderr.getvalue())
        self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), saved)

    def test_cli_prints_json_report(self) -> None:
        image = self.root / "vbmeta-cli.img"
        image.write_bytes(make_vbmeta(include_descriptors=False))
        import io
        from contextlib import redirect_stdout
        output = io.StringIO()
        with redirect_stdout(output):
            code = run_vbmeta_cli([str(image)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["operation"], "avb-vbmeta-inspect")


if __name__ == "__main__":
    unittest.main()
