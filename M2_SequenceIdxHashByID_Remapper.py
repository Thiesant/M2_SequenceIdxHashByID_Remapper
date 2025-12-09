#!/usr/bin/env python3
"""
M2 SequenceIdxHashByID Remapper

This script fixes the mismatch between SequenceIdxHashByID and Sequences in downported WoW M2 models.
It rebuilds the SequenceIdxHashByID lookup table based on the actual Sequences present in the model.

How it works:
- SequenceIdxHashByID is a lookup table indexed by Animation ID (from AnimationData.dbc)
- Each entry points to the index in the Sequences array, or -1 if that animation doesn't exist
- Downported models can have mismatches - this script rebuilds the table correctly

Usage:
    python M2_SequenceIdxHashByID_Remapper.py <input.m2> [output.m2] [options]
    
Options:
    --force      Force reprocessing even if file was already processed
    --recursive  Process subfolders recursively
    
If output is not specified, a back of the the input file will be made and then file will be modified.
"""

import struct
import sys
import os
import shutil
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict


# Signature to detect if file was already processed, won't work if you edit you M2 and add new stuff at EOL
REMAP_SIGNATURE = b'SEQREMAP'


@dataclass
class M2Header:
    """M2 file header information"""
    magic: bytes
    version: int
    base_offset: int
    n_sequences: int
    ofs_sequences: int
    n_sequence_idx_hash: int
    ofs_sequence_idx_hash: int


@dataclass 
class Sequence:
    """M2 Sequence entry"""
    sequence_id: int  # Animation ID
    sub_sequence_id: int  # Sub-animation index
    index: int  # Index in the sequences array


def read_uint32(data: bytes, offset: int) -> int:
    """Read unsigned 32-bit integer from data"""
    return struct.unpack_from('<I', data, offset)[0]


def read_uint16(data: bytes, offset: int) -> int:
    """Read unsigned 16-bit integer from data"""
    return struct.unpack_from('<H', data, offset)[0]


def read_int16(data: bytes, offset: int) -> int:
    """Read signed 16-bit integer from data"""
    return struct.unpack_from('<h', data, offset)[0]


def write_uint32(data: bytearray, offset: int, value: int) -> None:
    """Write unsigned 32-bit integer to data"""
    struct.pack_into('<I', data, offset, value)


def write_int16(data: bytearray, offset: int, value: int) -> None:
    """Write signed 16-bit integer to data"""
    struct.pack_into('<h', data, offset, value)


def parse_m2_header(data: bytes) -> M2Header:
    """Parse M2 file header and return header info"""
    magic = data[0:4]
    
    if magic == b'MD21':
        # MD21 chunked format (Legion+)
        # MD21 header is 4 bytes magic + 4 bytes size, then MD20 data
        base_offset = 8
        inner_magic = data[base_offset:base_offset+4]
        if inner_magic != b'MD20':
            raise ValueError(f"Expected MD20 inside MD21 chunk, got {inner_magic}")
    elif magic == b'MD20':
        base_offset = 0
    else:
        raise ValueError(f"Unknown M2 format: {magic}")
    
    version = read_uint32(data, base_offset + 0x04)
    n_sequences = read_uint32(data, base_offset + 0x1C)
    ofs_sequences = read_uint32(data, base_offset + 0x20)
    n_sequence_idx_hash = read_uint32(data, base_offset + 0x24)
    ofs_sequence_idx_hash = read_uint32(data, base_offset + 0x28)
    
    return M2Header(
        magic=magic,
        version=version,
        base_offset=base_offset,
        n_sequences=n_sequences,
        ofs_sequences=ofs_sequences,
        n_sequence_idx_hash=n_sequence_idx_hash,
        ofs_sequence_idx_hash=ofs_sequence_idx_hash
    )


def read_sequences(data: bytes, header: M2Header) -> List[Sequence]:
    """Read all sequences from M2 data"""
    sequences = []
    seq_size = 0x40  # Each sequence entry is 64 bytes
    
    for i in range(header.n_sequences):
        offset = header.base_offset + header.ofs_sequences + (i * seq_size)
        seq_id = read_uint16(data, offset)
        sub_seq_id = read_uint16(data, offset + 2)
        sequences.append(Sequence(
            sequence_id=seq_id,
            sub_sequence_id=sub_seq_id,
            index=i
        ))
    
    return sequences


def read_sequence_idx_hash(data: bytes, header: M2Header) -> List[int]:
    """Read current SequenceIdxHashByID lookup table"""
    lookup = []
    for i in range(header.n_sequence_idx_hash):
        offset = header.base_offset + header.ofs_sequence_idx_hash + (i * 2)
        lookup.append(read_int16(data, offset))
    return lookup


def build_sequence_idx_hash(sequences: List[Sequence]) -> List[int]:
    """
    Build correct SequenceIdxHashByID lookup table from sequences.
    
    The lookup table maps Animation ID -> Sequence index.
    For each Animation ID (0 to max_id), we find the FIRST sequence
    with that animation ID and store its index. If no sequence has that
    animation ID, we store -1.
    
    Size is determined by the highest animation ID found in sequences + 1.
    """
    if not sequences:
        return []
    
    # Find max animation ID in this model's sequences
    max_anim_id = max(seq.sequence_id for seq in sequences)
    hash_size = max_anim_id + 1
    
    lookup = [-1] * hash_size
    
    # Build mapping: for each unique animation ID, store the first sequence index
    for seq in sequences:
        if lookup[seq.sequence_id] == -1:
            lookup[seq.sequence_id] = seq.index
    
    return lookup


def check_already_processed(data: bytes) -> bool:
    """Check if file has already been processed by looking for signature"""
    return REMAP_SIGNATURE in data[-64:]  # Check last 64 bytes


def remap_m2_sequence_idx_hash(input_path: str, output_path: Optional[str] = None, force: bool = False) -> Tuple[bool, str]:
    """
    Remap SequenceIdxHashByID in an M2 file.
    
    Args:
        input_path: Path to input M2 file
        output_path: Path to output M2 file (optional, defaults to modifying in place)
        force: Force reprocessing even if already processed
    
    Returns:
        Tuple of (success: bool, message: str)
    """
    # Read input file
    with open(input_path, 'rb') as f:
        data = bytearray(f.read())
    
    # Check if already processed
    if not force and check_already_processed(data):
        return False, "File has already been processed. Use --force to reprocess."
    
    # Parse header
    try:
        header = parse_m2_header(data)
    except ValueError as e:
        return False, f"Failed to parse M2 header: {e}"
    
    print(f"M2 File: {input_path}")
    print(f"  Format: {header.magic.decode()}")
    print(f"  Version: {header.version}")
    print(f"  Base offset: 0x{header.base_offset:X}")
    print(f"  nSequences: {header.n_sequences}")
    print(f"  ofsSequences: 0x{header.ofs_sequences:X}")
    print(f"  nSequenceIdxHashByID: {header.n_sequence_idx_hash}")
    print(f"  ofsSequenceIdxHashByID: 0x{header.ofs_sequence_idx_hash:X}")
    print()
    
    # Read sequences
    sequences = read_sequences(data, header)
    
    # Build dynamic animation name mapping from the sequences found
    anim_names: Dict[int, str] = {}
    for seq in sequences:
        if seq.sequence_id not in anim_names:
            anim_names[seq.sequence_id] = f"Anim_{seq.sequence_id}"
    
    print(f"Sequences found ({len(sequences)}):")
    for seq in sequences:
        print(f"  [{seq.index}] {anim_names[seq.sequence_id]}_{seq.sub_sequence_id}")
    print()
    
    # Read current lookup table
    old_lookup = read_sequence_idx_hash(data, header)
    
    # Build new lookup table (size based on max animation ID in model)
    new_lookup = build_sequence_idx_hash(sequences)
    new_hash_size = len(new_lookup)
    
    print(f"Old nSequenceIdxHashByID: {header.n_sequence_idx_hash}")
    print(f"New nSequenceIdxHashByID: {new_hash_size} (max_anim_id + 1)")
    print()
    
    # Compare and report changes for existing entries
    changes = 0
    print("SequenceIdxHashByID remapping:")
    
    # Check existing entries that changed
    for i in range(min(len(old_lookup), new_hash_size)):
        old_val = old_lookup[i]
        new_val = new_lookup[i]
        if old_val != new_val:
            changes += 1
            print(f"  [{i}] Anim_{i}: {old_val} -> {new_val}")
    
    # Show new entries beyond old size
    if new_hash_size > len(old_lookup):
        print(f"\nNew entries (beyond old size {len(old_lookup)}):")
        for i in range(len(old_lookup), new_hash_size):
            if new_lookup[i] != -1:
                changes += 1
                print(f"  [{i}] Anim_{i}: (new) -> {new_lookup[i]}")
    
    if changes == 0:
        print("  No changes needed - lookup table is already correct!")
        return True, "No changes needed"
    
    print(f"\nTotal changes: {changes}")
    
    # Calculate the location for new data
    # We'll append the new SequenceIdxHashByID at the end of the file
    # First, find the end of the current data
    
    # Pad to align to 16 bytes
    current_size = len(data)
    padding_needed = (16 - (current_size % 16)) % 16
    if padding_needed > 0:
        data.extend(b'\x00' * padding_needed)
    
    # New offset for SequenceIdxHashByID (relative to base_offset)
    new_ofs_sequence_idx_hash = len(data) - header.base_offset
    
    # Write new lookup table at end of file
    for val in new_lookup:
        data.extend(struct.pack('<h', val))
    
    # Add signature to mark file as processed
    data.extend(REMAP_SIGNATURE)
    
    # Update the header to point to new lookup table and new size
    write_uint32(data, header.base_offset + 0x24, new_hash_size)  # nSequenceIdxHashByID
    write_uint32(data, header.base_offset + 0x28, new_ofs_sequence_idx_hash)  # ofsSequenceIdxHashByID
    
    print(f"\nNew nSequenceIdxHashByID: {new_hash_size}")
    print(f"New ofsSequenceIdxHashByID: 0x{new_ofs_sequence_idx_hash:X}")
    
    # Determine output path
    if output_path is None:
        # Create backup
        backup_path = input_path + '.bak'
        shutil.copy2(input_path, backup_path)
        print(f"Backup created: {backup_path}")
        output_path = input_path
    
    # Write output file
    with open(output_path, 'wb') as f:
        f.write(data)
    
    print(f"Output written to: {output_path}")
    
    return True, f"Successfully remapped {changes} entries"


def process_file(input_path: str, output_path: Optional[str], force: bool, quiet: bool = False) -> Tuple[bool, str]:
    """Process a single M2 file"""
    if not quiet:
        success, message = remap_m2_sequence_idx_hash(input_path, output_path, force)
    else:
        # Suppress detailed output for batch processing
        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            success, message = remap_m2_sequence_idx_hash(input_path, output_path, force)
        finally:
            sys.stdout = old_stdout
    return success, message


def process_folder(folder_path: str, force: bool, recursive: bool) -> Tuple[int, int, int]:
    """
    Process all M2 files in a folder.
    
    Args:
        folder_path: Path to folder containing M2 files
        force: Force reprocessing even if already processed
        recursive: Process subfolders recursively
    
    Returns:
        Tuple of (processed, skipped, failed) counts
    """
    processed = 0
    skipped = 0
    failed = 0
    
    if recursive:
        # Walk through all subdirectories
        for root, dirs, files in os.walk(folder_path):
            for filename in files:
                if filename.lower().endswith('.m2'):
                    filepath = os.path.join(root, filename)
                    rel_path = os.path.relpath(filepath, folder_path)
                    print(f"Processing: {rel_path}...", end=" ")
                    
                    success, message = process_file(filepath, None, force, quiet=True)
                    
                    if success:
                        processed += 1
                        print("✓")
                    elif "already been processed" in message:
                        skipped += 1
                        print("(skipped - already processed)")
                    else:
                        failed += 1
                        print(f"✗ {message}")
    else:
        # Only process files in the specified folder
        for filename in os.listdir(folder_path):
            if filename.lower().endswith('.m2'):
                filepath = os.path.join(folder_path, filename)
                print(f"Processing: {filename}...", end=" ")
                
                success, message = process_file(filepath, None, force, quiet=True)
                
                if success:
                    processed += 1
                    print("✓")
                elif "already been processed" in message:
                    skipped += 1
                    print("(skipped - already processed)")
                else:
                    failed += 1
                    print(f"✗ {message}")
    
    return processed, skipped, failed


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print(__doc__)
        print("Usage:")
        print("  Single file:  python M2_SequenceIdxHashByID_Remapper.py <input.m2> [output.m2] [--force]")
        print("  Folder:       python M2_SequenceIdxHashByID_Remapper.py <folder> [--recursive] [--force]")
        print("\nOptions:")
        print("  --force      Force reprocessing even if file was already processed")
        print("  --recursive  Process subfolders recursively (folder mode only)")
        print("\nTip: You can drag and drop a file or folder onto this script!")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    # Parse arguments
    force = '--force' in sys.argv
    recursive = '--recursive' in sys.argv or '-r' in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    
    input_path = args[0].strip('"')
    
    if not os.path.exists(input_path):
        print(f"Error: Path not found: {input_path}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    exit_code = 0
    
    # Check if input is a folder or file
    if os.path.isdir(input_path):
        print(f"Processing folder: {input_path}")
        if recursive:
            print("Mode: Recursive")
        else:
            print("Mode: Non-recursive (use --recursive or -r for subfolders)")
        print()
        
        processed, skipped, failed = process_folder(input_path, force, recursive)
        
        print()
        print(f"Summary: {processed} processed, {skipped} skipped, {failed} failed")
        
        if failed > 0:
            exit_code = 1
    else:
        # Single file mode
        output_path = args[1] if len(args) > 1 else None
        
        success, message = remap_m2_sequence_idx_hash(input_path, output_path, force)
        
        if success:
            print(f"\n✓ {message}")
        else:
            print(f"\n✗ {message}")
            exit_code = 1
    
    input("\nPress Enter to exit...")
    sys.exit(exit_code)


if __name__ == '__main__':
    main()