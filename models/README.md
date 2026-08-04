# Model bundles

Trained weights and HEF binaries are release artifacts and are not committed to Git.

Expected bundle:

```text
rave-model-X.Y.Z/
├── detector.hef
├── labels.json
├── pipeline.toml
├── tracker.toml
├── crop-profile.json
├── manifest.json
└── manifest.sig
```

The manifest must bind the model to the accelerator architecture, input dimensions, class set, calibration dataset version, runtime compatibility range, expected performance, and file hashes.
