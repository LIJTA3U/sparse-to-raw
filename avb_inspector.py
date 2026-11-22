#!/usr/bin/env python3
"""Read-only Android Verified Boot (AVB) vbmeta inspector.

The module parses AVB0 headers, authentication/auxiliary blocks, AVB footers,
and standard descriptors using only the Python standard library. It checks
container bounds and the embedded vbmeta digest, but deliberately does not
claim to verify RSA signatures or establish trust in an embedded public key.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

from cli_i18n import tr, localize_error

VBMETA_MAGIC = b"AVB0"
FOOTER_MAGIC = b"AVBf"
VBMETA_HEADER_SIZE = 256
FOOTER_SIZE = 64
DESCRIPTOR_HEADER_SIZE = 16
MAX_DESCRIPTOR_BYTES = 64 * 1024 * 1024
MAX_VBMETA_BLOCK_BYTES = 128 * 1024 * 1024

ALGORITHMS: dict[int, dict[str, Any]] = {
    0: {"name": "NONE", "hash": None, "signature_size": 0, "rsa_bits": None},
    1: {"name": "SHA256_RSA2048", "hash": "sha256", "signature_size": 256, "rsa_bits": 2048},
    2: {"name": "SHA256_RSA4096", "hash": "sha256", "signature_size": 512, "rsa_bits": 4096},
    3: {"name": "SHA256_RSA8192", "hash": "sha256", "signature_size": 1024, "rsa_bits": 8192},
    4: {"name": "SHA512_RSA2048", "hash": "sha512", "signature_size": 256, "rsa_bits": 2048},
    5: {"name": "SHA512_RSA4096", "hash": "sha512", "signature_size": 512, "rsa_bits": 4096},
    6: {"name": "SHA512_RSA8192", "hash": "sha512", "signature_size": 1024, "rsa_bits": 8192},
}
DESCRIPTOR_NAMES = {
    0: "PROPERTY",
    1: "HASHTREE",
    2: "HASH",
    3: "KERNEL_CMDLINE",
    4: "CHAIN_PARTITION",
}


class AVBImageError(ValueError):
    """Raised when an AVB image is malformed or inconsistent."""


def _be32(data: bytes, offset: int, field: str) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise AVBImageError(f"Truncated VBMeta header while reading {field}")
    return struct.unpack_from("!I", data, offset)[0]


def _be64(data: bytes, offset: int, field: str) -> int:
    if offset < 0 or offset + 8 > len(data):
        raise AVBImageError(f"Truncated VBMeta header while reading {field}")
    return struct.unpack_from("!Q", data, offset)[0]


def _bounded_region(offset: int, size: int, limit: int, label: str) -> tuple[int, int]:
    if offset < 0 or size < 0 or offset > limit or size > limit - offset:
        raise AVBImageError(f"{label} lies outside its declared block")
    return offset, offset + size


def _decode_utf8(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _validate_non_overlapping_regions(
    regions: list[tuple[int, int, str]], label: str
) -> None:
    """Reject non-empty subregions that overlap within a declared AVB block."""
    occupied = sorted((start, end, name) for start, end, name in regions if end > start)
    for previous, current in zip(occupied, occupied[1:]):
        if current[0] < previous[1]:
            raise AVBImageError(
                f"{label} regions overlap: {previous[2]} and {current[2]}"
            )


def _decode_rsa_public_key(blob: bytes) -> dict[str, Any]:
    """Return the AVB-encoded RSA key dimensions and a stable fingerprint."""
    result: dict[str, Any] = {
        "size_bytes": len(blob),
        "sha1_fingerprint": hashlib.sha1(blob).hexdigest(),
        "sha256_fingerprint": hashlib.sha256(blob).hexdigest(),
        "rsa_bits": None,
        "size_consistent": False,
    }
    if len(blob) < 8:
        return result
    num_bits = struct.unpack_from("!I", blob, 4)[0]
    if num_bits <= 0 or num_bits % 8:
        return result
    required = 8 + 2 * (num_bits // 8)
    if required != len(blob):
        return result
    result["rsa_bits"] = num_bits
    result["size_consistent"] = True
    return result


def _parse_descriptor_blob(data: bytes) -> list[dict[str, Any]]:
    descriptors: list[dict[str, Any]] = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < DESCRIPTOR_HEADER_SIZE:
            raise AVBImageError("Truncated AVB descriptor header")
        tag, following = struct.unpack_from("!QQ", data, offset)
        if following % 8:
            raise AVBImageError(f"Descriptor {tag} has a non-aligned payload length")
        total_size = DESCRIPTOR_HEADER_SIZE + following
        if total_size > len(data) - offset:
            raise AVBImageError(f"Descriptor {tag} extends beyond the descriptor table")
        if total_size < DESCRIPTOR_HEADER_SIZE:
            raise AVBImageError(f"Descriptor {tag} has an invalid size")
        raw = data[offset:offset + total_size]
        payload = raw[DESCRIPTOR_HEADER_SIZE:]
        item: dict[str, Any] = {
            "tag": tag,
            "type": DESCRIPTOR_NAMES.get(tag, f"UNKNOWN_{tag}"),
            "size_bytes": total_size,
        }

        if tag == 0:  # Property descriptor: 32-byte fixed header + key/value strings.
            if len(raw) < 32:
                raise AVBImageError("Truncated AVB property descriptor")
            key_size, value_size = struct.unpack_from("!QQ", raw, 16)
            expected = ((32 + key_size + 1 + value_size + 1 + 7) // 8) * 8
            if expected != total_size:
                raise AVBImageError("AVB property descriptor has inconsistent string lengths")
            key_start = 32
            key_end = key_start + key_size
            if raw[key_end:key_end + 1] != b"\0":
                raise AVBImageError("AVB property key is not NUL-terminated")
            value_start = key_end + 1
            value_end = value_start + value_size
            if raw[value_end:value_end + 1] != b"\0":
                raise AVBImageError("AVB property value is not NUL-terminated")
            key_raw = raw[key_start:key_end]
            value_raw = raw[value_start:value_end]
            item.update({
                "key": _decode_utf8(key_raw),
                "value": _decode_utf8(value_raw),
                "value_hex": value_raw.hex(),
                "value_size_bytes": value_size,
            })

        elif tag == 1:  # Hashtree descriptor, 180-byte fixed header.
            fixed_size = 180
            if len(raw) < fixed_size:
                raise AVBImageError("Truncated AVB hashtree descriptor")
            values = struct.unpack_from("!QQIQQQIIIQQ32sIIII60s", raw, 0)
            (_, _, dm_verity_version, image_size, tree_offset, tree_size,
             data_block_size, hash_block_size, fec_num_roots, fec_offset,
             fec_size, algorithm_raw, name_len, salt_len, digest_len, flags,
             reserved) = values
            expected = ((fixed_size + name_len + salt_len + digest_len + 7) // 8) * 8
            if expected != total_size:
                raise AVBImageError("AVB hashtree descriptor has inconsistent variable-field lengths")
            cursor = fixed_size
            name_raw = raw[cursor:cursor + name_len]; cursor += name_len
            salt = raw[cursor:cursor + salt_len]; cursor += salt_len
            root_digest = raw[cursor:cursor + digest_len]
            item.update({
                "partition_name": _decode_utf8(name_raw),
                "dm_verity_version": dm_verity_version,
                "image_size_bytes": image_size,
                "tree_offset_bytes": tree_offset,
                "tree_size_bytes": tree_size,
                "data_block_size": data_block_size,
                "hash_block_size": hash_block_size,
                "fec_num_roots": fec_num_roots,
                "fec_offset_bytes": fec_offset,
                "fec_size_bytes": fec_size,
                "hash_algorithm": algorithm_raw.rstrip(b"\0").decode("ascii", "replace"),
                "salt_hex": salt.hex(),
                "root_digest_hex": root_digest.hex(),
                "flags": flags,
                "reserved_zero": not any(reserved),
            })

        elif tag == 2:  # Hash descriptor, 132-byte fixed header.
            fixed_size = 132
            if len(raw) < fixed_size:
                raise AVBImageError("Truncated AVB hash descriptor")
            (_, _, image_size, algorithm_raw, name_len, salt_len,
             digest_len, flags, reserved) = struct.unpack_from("!QQQ32sIIII60s", raw, 0)
            expected = ((fixed_size + name_len + salt_len + digest_len + 7) // 8) * 8
            if expected != total_size:
                raise AVBImageError("AVB hash descriptor has inconsistent variable-field lengths")
            cursor = fixed_size
            name_raw = raw[cursor:cursor + name_len]; cursor += name_len
            salt = raw[cursor:cursor + salt_len]; cursor += salt_len
            digest = raw[cursor:cursor + digest_len]
            item.update({
                "partition_name": _decode_utf8(name_raw),
                "image_size_bytes": image_size,
                "hash_algorithm": algorithm_raw.rstrip(b"\0").decode("ascii", "replace"),
                "salt_hex": salt.hex(),
                "digest_hex": digest.hex(),
                "flags": flags,
                "reserved_zero": not any(reserved),
            })

        elif tag == 3:  # Kernel command-line descriptor.
            if len(raw) < 24:
                raise AVBImageError("Truncated AVB kernel command-line descriptor")
            _, _, flags, cmdline_size = struct.unpack_from("!QQII", raw, 0)
            expected = ((24 + cmdline_size + 7) // 8) * 8
            if expected != total_size:
                raise AVBImageError("AVB kernel command-line descriptor has inconsistent length")
            item.update({
                "flags": flags,
                "kernel_cmdline": _decode_utf8(raw[24:24 + cmdline_size]),
            })

        elif tag == 4:  # Chain-partition descriptor, 92-byte fixed header.
            fixed_size = 92
            if len(raw) < fixed_size:
                raise AVBImageError("Truncated AVB chain-partition descriptor")
            (_, _, rollback_location, name_len, key_len, flags,
             reserved) = struct.unpack_from("!QQIIII60s", raw, 0)
            expected = ((fixed_size + name_len + key_len + 7) // 8) * 8
            if expected != total_size:
                raise AVBImageError("AVB chain-partition descriptor has inconsistent field lengths")
            name_raw = raw[fixed_size:fixed_size + name_len]
            key_blob = raw[fixed_size + name_len:fixed_size + name_len + key_len]
            item.update({
                "partition_name": _decode_utf8(name_raw),
                "rollback_index_location": rollback_location,
                "flags": flags,
                "public_key": _decode_rsa_public_key(key_blob),
                "reserved_zero": not any(reserved),
            })
        else:
            item["payload_sha256"] = hashlib.sha256(payload).hexdigest()

        descriptors.append(item)
        offset += total_size

    if offset != len(data):
        raise AVBImageError("AVB descriptor table length accounting mismatch")
    return descriptors


def inspect_vbmeta_image(path: str | Path) -> dict[str, Any]:
    """Inspect a raw vbmeta image or an image containing an AVB footer.

    The source is opened read-only. Hash integrity is checked where the AVB
    algorithm defines one. RSA signature verification and trust decisions are
    intentionally outside this inspector's scope.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"VBMeta image not found: {source}")
    file_size = source.stat().st_size
    if file_size < VBMETA_HEADER_SIZE:
        raise AVBImageError("File is too small to contain an AVB VBMeta header")

    with source.open("rb") as stream:
        first_magic = stream.read(4)
        footer_info: dict[str, Any] | None = None
        if first_magic == VBMETA_MAGIC:
            vbmeta_offset = 0
            container_type = "standalone-vbmeta"
        else:
            if file_size < FOOTER_SIZE:
                raise AVBImageError("AVB0 header not found and file is too small for an AVB footer")
            stream.seek(file_size - FOOTER_SIZE)
            footer_raw = stream.read(FOOTER_SIZE)
            if footer_raw[:4] != FOOTER_MAGIC:
                raise AVBImageError("AVB0 header not found; no AVBf footer is present")
            magic, footer_major, footer_minor, original_size, vbmeta_offset, vbmeta_size, reserved = struct.unpack(
                "!4sIIQQQ28s", footer_raw
            )
            if magic != FOOTER_MAGIC:
                raise AVBImageError("Invalid AVB footer magic")
            if any(reserved):
                raise AVBImageError("AVB footer reserved bytes are not zero")
            footer_start = file_size - FOOTER_SIZE
            if (vbmeta_offset < original_size or vbmeta_size < VBMETA_HEADER_SIZE
                    or vbmeta_offset > footer_start or vbmeta_size > footer_start - vbmeta_offset):
                raise AVBImageError("AVB footer points outside the image or overlaps the original image")
            footer_info = {
                "version_major": footer_major,
                "version_minor": footer_minor,
                "original_image_size_bytes": original_size,
                "vbmeta_offset_bytes": vbmeta_offset,
                "vbmeta_size_bytes": vbmeta_size,
            }
            container_type = "footer-backed-image"

        stream.seek(vbmeta_offset)
        header = stream.read(VBMETA_HEADER_SIZE)
        if len(header) != VBMETA_HEADER_SIZE:
            raise AVBImageError("Truncated AVB VBMeta header")
        if header[:4] != VBMETA_MAGIC:
            raise AVBImageError("Invalid VBMeta magic at the selected offset")

        required_major = _be32(header, 4, "required libavb major version")
        required_minor = _be32(header, 8, "required libavb minor version")
        auth_size = _be64(header, 12, "authentication block size")
        aux_size = _be64(header, 20, "auxiliary block size")
        algorithm_type = _be32(header, 28, "algorithm type")
        fields = {
            "hash_offset": _be64(header, 32, "hash offset"),
            "hash_size": _be64(header, 40, "hash size"),
            "signature_offset": _be64(header, 48, "signature offset"),
            "signature_size": _be64(header, 56, "signature size"),
            "public_key_offset": _be64(header, 64, "public key offset"),
            "public_key_size": _be64(header, 72, "public key size"),
            "public_key_metadata_offset": _be64(header, 80, "public key metadata offset"),
            "public_key_metadata_size": _be64(header, 88, "public key metadata size"),
            "descriptors_offset": _be64(header, 96, "descriptors offset"),
            "descriptors_size": _be64(header, 104, "descriptors size"),
        }
        rollback_index = _be64(header, 112, "rollback index")
        flags = _be32(header, 120, "flags")
        rollback_index_location = _be32(header, 124, "rollback index location")
        release_string = header[128:176].split(b"\0", 1)[0].decode("utf-8", "replace")
        reserved_header = header[176:256]

        if auth_size % 64 or aux_size % 64:
            raise AVBImageError("VBMeta authentication and auxiliary block sizes must be multiples of 64")
        if auth_size > MAX_VBMETA_BLOCK_BYTES or aux_size > MAX_VBMETA_BLOCK_BYTES:
            raise AVBImageError("VBMeta authentication or auxiliary block exceeds the safety limit")
        if auth_size > file_size or aux_size > file_size or VBMETA_HEADER_SIZE + auth_size + aux_size > file_size - vbmeta_offset:
            raise AVBImageError("VBMeta blocks extend beyond the input image")
        if footer_info and VBMETA_HEADER_SIZE + auth_size + aux_size > footer_info["vbmeta_size_bytes"]:
            raise AVBImageError("VBMeta data exceeds the size declared by the AVB footer")

        _bounded_region(fields["hash_offset"], fields["hash_size"], auth_size, "Authentication hash")
        _bounded_region(fields["signature_offset"], fields["signature_size"], auth_size, "Authentication signature")
        _bounded_region(fields["public_key_offset"], fields["public_key_size"], aux_size, "Public key")
        _bounded_region(fields["public_key_metadata_offset"], fields["public_key_metadata_size"], aux_size, "Public key metadata")
        _bounded_region(fields["descriptors_offset"], fields["descriptors_size"], aux_size, "Descriptor table")
        _validate_non_overlapping_regions([
            (fields["hash_offset"], fields["hash_offset"] + fields["hash_size"], "hash"),
            (fields["signature_offset"], fields["signature_offset"] + fields["signature_size"], "signature"),
        ], "Authentication block")
        _validate_non_overlapping_regions([
            (fields["public_key_offset"], fields["public_key_offset"] + fields["public_key_size"], "public key"),
            (fields["public_key_metadata_offset"], fields["public_key_metadata_offset"] + fields["public_key_metadata_size"], "public key metadata"),
            (fields["descriptors_offset"], fields["descriptors_offset"] + fields["descriptors_size"], "descriptors"),
        ], "Auxiliary block")
        if fields["descriptors_size"] > MAX_DESCRIPTOR_BYTES:
            raise AVBImageError("Descriptor table exceeds the safety limit")

        stream.seek(vbmeta_offset + VBMETA_HEADER_SIZE)
        auth_block = stream.read(auth_size)
        if len(auth_block) != auth_size:
            raise AVBImageError("Truncated VBMeta authentication block")
        aux_start = vbmeta_offset + VBMETA_HEADER_SIZE + auth_size
        stream.seek(aux_start)
        aux_block = stream.read(aux_size)
        if len(aux_block) != aux_size:
            raise AVBImageError("Truncated VBMeta auxiliary block")

    algorithm = ALGORITHMS.get(algorithm_type)
    algorithm_name = algorithm["name"] if algorithm else f"UNKNOWN_{algorithm_type}"
    digest_info: dict[str, Any] = {
        "algorithm": algorithm_name,
        "stored_hash_hex": None,
        "computed_hash_hex": None,
        "status": "not-available",
    }
    if algorithm is None:
        digest_info["status"] = "unsupported-algorithm"
    elif algorithm_type == 0:
        if fields["hash_size"] or fields["signature_size"]:
            raise AVBImageError("Algorithm NONE must not declare a hash or signature")
        digest_info["status"] = "not-applicable"
    else:
        expected_hash_size = hashlib.new(algorithm["hash"]).digest_size
        if fields["hash_size"] != expected_hash_size:
            raise AVBImageError(
                f"Hash size does not match {algorithm['hash']} ({expected_hash_size} bytes expected)"
            )
        if fields["signature_size"] != algorithm["signature_size"]:
            raise AVBImageError("Signature size does not match the selected AVB RSA algorithm")
        stored_hash = auth_block[fields["hash_offset"]:fields["hash_offset"] + fields["hash_size"]]
        computed_hash = hashlib.new(algorithm["hash"], header + aux_block).digest()
        digest_info.update({
            "stored_hash_hex": stored_hash.hex(),
            "computed_hash_hex": computed_hash.hex(),
            "status": "match" if stored_hash == computed_hash else "mismatch",
        })

    public_key_blob = aux_block[fields["public_key_offset"]:fields["public_key_offset"] + fields["public_key_size"]]
    public_key_info = _decode_rsa_public_key(public_key_blob) if public_key_blob else None
    public_key_metadata = aux_block[
        fields["public_key_metadata_offset"]:
        fields["public_key_metadata_offset"] + fields["public_key_metadata_size"]
    ]
    descriptor_blob = aux_block[
        fields["descriptors_offset"]:
        fields["descriptors_offset"] + fields["descriptors_size"]
    ]
    descriptors = _parse_descriptor_blob(descriptor_blob)

    total_blob_size = VBMETA_HEADER_SIZE + auth_size + aux_size
    if footer_info and footer_info["vbmeta_size_bytes"] < total_blob_size:
        raise AVBImageError("VBMeta footer size is smaller than the parsed VBMeta structure")

    report = {
        "operation": "avb-vbmeta-inspect",
        "input": str(source),
        "file_size_bytes": file_size,
        "container_type": container_type,
        "vbmeta_offset_bytes": vbmeta_offset,
        "vbmeta_size_bytes": total_blob_size,
        "required_libavb_version": f"{required_major}.{required_minor}",
        "algorithm_type": algorithm_type,
        "algorithm": algorithm_name,
        "authentication_data_block_size": auth_size,
        "auxiliary_data_block_size": aux_size,
        "rollback_index": rollback_index,
        "rollback_index_location": rollback_index_location,
        "flags": flags,
        "hashtree_disabled": bool(flags & 1),
        "verification_disabled": bool(flags & 2),
        "release_string": release_string,
        "header_reserved_zero": not any(reserved_header),
        "embedded_hash": digest_info,
        "signature": {
            "present": fields["signature_size"] > 0,
            "size_bytes": fields["signature_size"],
            "status": "not-verified" if fields["signature_size"] else "not-present",
        },
        "public_key": public_key_info,
        "public_key_metadata": {
            "size_bytes": len(public_key_metadata),
            "sha256": hashlib.sha256(public_key_metadata).hexdigest() if public_key_metadata else None,
        },
        "descriptor_count": len(descriptors),
        "descriptors": descriptors,
        "vbmeta_blob_sha256": hashlib.sha256(header + auth_block + aux_block).hexdigest(),
        "footer": footer_info,
        "limitations": [
            "The embedded vbmeta hash is checked when the algorithm is supported.",
            "RSA signature verification is not performed.",
            "The embedded public key is not compared with a trusted key or device trust store.",
            "Rollback index is displayed but is not compared with device-stored rollback state.",
        ],
    }
    return report


def run_vbmeta_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sparse-to-raw vbmeta-info",
        description=tr("avb_info_desc"),
    )
    parser.add_argument("input_image", help=tr("avb_input"))
    parser.add_argument("--json-report", metavar="FILE", help=tr("avb_json"))
    args = parser.parse_args(argv)
    try:
        source = Path(args.input_image).expanduser().resolve()
        report_path = Path(args.json_report).expanduser().resolve() if args.json_report else None
        if report_path and report_path == source:
            parser.error("JSON report path must differ from the input image")
        if report_path and not report_path.parent.is_dir():
            parser.error(f"JSON report directory not found: {report_path.parent}")
        report = inspect_vbmeta_image(source)
        payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        print(payload, end="")
        if report_path:
            if report_path.exists():
                raise FileExistsError(f"JSON report already exists: {report_path}")
            with report_path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
        return 0
    except (OSError, ValueError) as exc:
        print(f"{tr('error')}: {localize_error(str(exc))}", file=sys.stderr)
        return 2
