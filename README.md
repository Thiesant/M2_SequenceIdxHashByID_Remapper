# M2_SequenceIdxHashByID_Remapper
Rebuild correct mapping lookup table at EOL of downported M2 on 3.3.5a

## Description
Downporting between WoW expansions often breaks the SequenceIdxHashByID lookup table inside .m2 files, causing animation mismatches or missing animations in-game.
This script scans the model, rebuilds the correct lookup table based on the sequences actually present, and writes a corrected version of the .m2 at the EOL.

## How it works:
- SequenceIdxHashByID is a lookup table indexed by Animation ID (from AnimationData.dbc)
- Each entry points to the index in the Sequences array, or -1 if that animation doesn't exist
- Downported models can have mismatches - this script rebuilds the table correctly

## Usage:
    python M2_SequenceIdxHashByID_Remapper.py <input.m2> [output.m2] [options]
    
### Options:
    --force      Force reprocessing even if file was already processed
    --recursive  Process subfolders recursively
    
If output is not specified, a back of the the input file will be made and then file will be modified.

Adds a SEQREMAP signature at EOL to prevent double-processing to the final 64 bytes of the file.
If detected again, the file is skipped unless --force is used.

IF YOU EDIT M2 AGAIN AT EOL AFTER THAT SIGNATURE IT WILL NULLIFY THIS CHECK.

## Credits
Inspired by the script of ** Supora and Morfium. **
I just wanted a faster way to do it rather than having to use a script on Warcraft Blender Studio. Also Because I tend to break my models with WBS.
