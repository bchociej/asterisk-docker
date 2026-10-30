# Audio codec testing

Optional test playback uses `app_playback` and `format_sln`. Local licensed audio
and test dialplans belong in ignored private configuration, then a validated
release snapshot. Keep attribution and source/conversion details with the files.
Do not put actual deployment details or recordings in Git.

Per-device `--codec ulaw` (PCMU, default) or `--codec g722` selects a single codec
without regenerating credentials. Coordinate the ATA preference, validate an
isolated snapshot, and activate only between calls. Preserve the prior snapshot,
image selection, and ATA codec settings for rollback. Confirm actual read/write
formats and translation on live calls; a registered account proves no codec use.
Keep packetization, gain, jitter and echo settings unchanged during comparisons.

For G.722 playback use a 16 kHz signed-linear source (`.sln16`) made from a
high-quality original. Use the same excerpt, mono mix, gain, timing and fades for
all references. An optional PCMU-degraded reference can be made by resampling to
8 kHz and encoding/decoding mu-law; playing that over G.722 demonstrates source
degradation, not an actual PCMU network call. Label that distinction clearly.

Use the same handset and physical volume for successive codec comparisons.
Listen for naturalness, high-frequency detail, hiss, distortion, silence gating
and delay; preserve subjective observations separately from packet statistics.
