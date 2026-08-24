Place shared mihomo patch files in `patches/common` and reference that directory with the
top-level `patches` field in `kernel-builder.json`. The builder applies this patch set to every
configured channel.

Patch files are applied after the template repository's own patches. Keep patches small and make
them apply cleanly to every selected upstream ref.
