use invariant::{decode, encode, verify, MAX_CONTAINER_BYTES, MAX_INPUT_BYTES};
use std::env;
use std::error::Error;
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;

fn read_limited(path: &Path, limit: usize) -> Result<Vec<u8>, Box<dyn Error>> {
    let mut file = File::open(path)?;
    let mut bytes = Vec::new();
    file.by_ref()
        .take((limit as u64) + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > limit {
        return Err(format!("file exceeds limit of {limit} bytes").into());
    }
    Ok(bytes)
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), Box<dyn Error>> {
    let mut output = OpenOptions::new().write(true).create_new(true).open(path)?;
    output.write_all(bytes)?;
    output.sync_all()?;
    Ok(())
}

fn usage() -> &'static str {
    "Usage: invariant pack INPUT NEW_OUTPUT | unpack INPUT NEW_OUTPUT | verify INPUT"
}

fn run() -> Result<(), Box<dyn Error>> {
    let mut args = env::args().skip(1);
    let command = args.next().ok_or_else(usage)?;
    match command.as_str() {
        "pack" | "unpack" => {
            let input = args.next().ok_or_else(usage)?;
            let output = args.next().ok_or_else(usage)?;
            if args.next().is_some() {
                return Err(usage().into());
            }
            let limit = if command == "pack" {
                MAX_INPUT_BYTES
            } else {
                MAX_CONTAINER_BYTES
            };
            let data = read_limited(Path::new(&input), limit)?;
            let result = if command == "pack" {
                encode(&data)?
            } else {
                decode(&data)?
            };
            write_new(Path::new(&output), &result)?;
            println!("{} bytes written", result.len());
        }
        "verify" => {
            let input = args.next().ok_or_else(usage)?;
            if args.next().is_some() {
                return Err(usage().into());
            }
            let package = read_limited(Path::new(&input), MAX_CONTAINER_BYTES)?;
            let bytes = verify(&package)?;
            println!("verified: {bytes} reconstructed bytes");
        }
        _ => return Err(usage().into()),
    }
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("invariant: {error}");
        std::process::exit(1);
    }
}
