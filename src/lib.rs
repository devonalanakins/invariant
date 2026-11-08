//! Experimental INVARIANT v0 container.
//!
//! Not a new compression algorithm or a stable archival format. The encoder
//! selects between literal storage and existing Zstandard compression.
//! A fixed maximum size bounds allocations during early-stage research.

use sha2::{Digest, Sha256};
use std::fmt;

const MAGIC: &[u8; 4] = b"IVN0";
const VERSION: u8 = 0;
const CODEC_RAW: u8 = 0;
const CODEC_ZSTD: u8 = 1;
const HEADER_BYTES: usize = 4 + 1 + 1 + 8 + 8 + 32;
pub const MAX_INPUT_BYTES: usize = 64 * 1024 * 1024;
pub const MAX_CONTAINER_BYTES: usize = MAX_INPUT_BYTES + 1024 * 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ContainerError {
    TooLarge,
    InvalidHeader,
    UnsupportedVersion(u8),
    UnsupportedCodec(u8),
    LengthMismatch,
    DigestMismatch,
    Codec(String),
}

impl fmt::Display for ContainerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TooLarge => write!(f, "input exceeds experimental size limit"),
            Self::InvalidHeader => write!(f, "invalid or truncated IVN0 header"),
            Self::UnsupportedVersion(v) => write!(f, "unsupported IVN0 version: {v}"),
            Self::UnsupportedCodec(c) => write!(f, "unsupported codec identifier: {c}"),
            Self::LengthMismatch => write!(f, "declared and actual lengths differ"),
            Self::DigestMismatch => write!(f, "reconstructed SHA-256 digest mismatch"),
            Self::Codec(e) => write!(f, "codec failure: {e}"),
        }
    }
}

impl std::error::Error for ContainerError {}

/// Encodes no more than 64 MiB. Format v0 is provisional and may change.
pub fn encode(input: &[u8]) -> Result<Vec<u8>, ContainerError> {
    if input.len() > MAX_INPUT_BYTES {
        return Err(ContainerError::TooLarge);
    }

    let compressed =
        zstd::bulk::compress(input, 3).map_err(|e| ContainerError::Codec(e.to_string()))?;
    let (codec, payload): (u8, &[u8]) = if compressed.len() < input.len() {
        (CODEC_ZSTD, &compressed)
    } else {
        (CODEC_RAW, input)
    };

    let mut output = Vec::with_capacity(HEADER_BYTES + payload.len());
    output.extend_from_slice(MAGIC);
    output.push(VERSION);
    output.push(codec);
    output.extend_from_slice(&(input.len() as u64).to_le_bytes());
    output.extend_from_slice(&(payload.len() as u64).to_le_bytes());
    output.extend_from_slice(&Sha256::digest(input));
    output.extend_from_slice(payload);
    Ok(output)
}

/// Restores exactly the original bytes, or returns an explicit error.
pub fn decode(container: &[u8]) -> Result<Vec<u8>, ContainerError> {
    if container.len() > MAX_CONTAINER_BYTES {
        return Err(ContainerError::TooLarge);
    }
    if container.len() < HEADER_BYTES || &container[..4] != MAGIC {
        return Err(ContainerError::InvalidHeader);
    }
    if container[4] != VERSION {
        return Err(ContainerError::UnsupportedVersion(container[4]));
    }

    let codec = container[5];
    if codec != CODEC_RAW && codec != CODEC_ZSTD {
        return Err(ContainerError::UnsupportedCodec(codec));
    }

    let original_len = u64::from_le_bytes(container[6..14].try_into().expect("fixed header slice"));
    let encoded_len = u64::from_le_bytes(container[14..22].try_into().expect("fixed header slice"));
    if original_len > MAX_INPUT_BYTES as u64 || encoded_len > MAX_CONTAINER_BYTES as u64 {
        return Err(ContainerError::TooLarge);
    }
    let original_len = original_len as usize;
    let encoded_len = encoded_len as usize;

    if HEADER_BYTES.checked_add(encoded_len) != Some(container.len()) {
        return Err(ContainerError::LengthMismatch);
    }

    let payload = &container[HEADER_BYTES..];
    let decoded = match codec {
        CODEC_RAW => payload.to_vec(),
        CODEC_ZSTD => zstd::bulk::decompress(payload, original_len)
            .map_err(|e| ContainerError::Codec(e.to_string()))?,
        _ => unreachable!("codec already checked"),
    };

    if decoded.len() != original_len {
        return Err(ContainerError::LengthMismatch);
    }
    let digest = Sha256::digest(&decoded);
    if digest.as_slice() != &container[22..54] {
        return Err(ContainerError::DigestMismatch);
    }
    Ok(decoded)
}

/// Verifies that a container can be decoded and its digest matches.
pub fn verify(container: &[u8]) -> Result<usize, ContainerError> {
    decode(container).map(|decoded| decoded.len())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_varied_data() {
        let cases = [
            vec![],
            vec![0],
            vec![1, 0, 255, 128, 0, 255],
            "an exact unicode sample \u{1f680}".as_bytes().to_vec(),
            vec![42; 128 * 1024],
            (0..65536).map(|i| (i % 251) as u8).collect(),
        ];
        for original in cases {
            let package = encode(&original).unwrap();
            assert_eq!(decode(&package).unwrap(), original);
            assert_eq!(verify(&package).unwrap(), original.len());
        }
    }

    #[test]
    fn deterministic_output() {
        let input = b"repeatable research input";
        assert_eq!(encode(input).unwrap(), encode(input).unwrap());
    }

    #[test]
    fn repetitive_data_uses_zstd() {
        let package = encode(&vec![b'A'; 100_000]).unwrap();
        assert_eq!(package[5], CODEC_ZSTD);
        assert!(package.len() < 100_000);
    }

    #[test]
    fn detects_tampered_plaintext() {
        let mut package = encode(b"short").unwrap();
        let end = package.len() - 1;
        package[end] ^= 1;
        assert_eq!(decode(&package), Err(ContainerError::DigestMismatch));
    }

    #[test]
    fn rejects_truncated_header_and_payload() {
        assert_eq!(decode(b"IVN0"), Err(ContainerError::InvalidHeader));
        let mut package = encode(b"hello").unwrap();
        package.pop();
        assert_eq!(decode(&package), Err(ContainerError::LengthMismatch));
    }

    #[test]
    fn rejects_unrecognized_version_and_codec() {
        let mut package = encode(b"hello").unwrap();
        package[4] = 1;
        assert_eq!(decode(&package), Err(ContainerError::UnsupportedVersion(1)));
        package[4] = 0;
        package[5] = 255;
        assert_eq!(decode(&package), Err(ContainerError::UnsupportedCodec(255)));
    }

    #[test]
    fn rejects_bad_declared_output_size() {
        let mut package = encode(b"hello").unwrap();
        package[6..14].copy_from_slice(&((MAX_INPUT_BYTES as u64) + 1).to_le_bytes());
        assert_eq!(decode(&package), Err(ContainerError::TooLarge));
    }

    #[test]
    fn rejects_trailing_bytes() {
        let mut package = encode(b"hello").unwrap();
        package.push(0);
        assert_eq!(decode(&package), Err(ContainerError::LengthMismatch));
    }

    #[test]
    fn refuses_oversized_input() {
        assert_eq!(
            encode(&vec![0; MAX_INPUT_BYTES + 1]),
            Err(ContainerError::TooLarge)
        );
    }
}
