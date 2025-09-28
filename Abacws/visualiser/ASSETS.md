# Visualiser assets: swap your building GLB files

You can change the 3D building by dropping your GLB files into `visualiser/public/assets` and listing them in `visualiser/public/assets/manifest.json`.

Steps:

1. Put your files in `visualiser/public/assets/` (GLTF/GLB).
2. Edit `visualiser/public/assets/manifest.json` and set the order of layers to load, for example:

```
{
  "layers": [
    "floors.glb",
    "exterior-walls.glb",
    "windows.glb"
  ]
}
```

Layer files are loaded in the order specified.

Device markers: The API seeds device coordinates from `api/src/api/data/devices.json`. Use the `offset` block in that file to align device positions to your model. After changing devices, restart the API container to re-import.

Important: these example GLB files are tracked with Git LFS. If you see tiny files (~130 bytes) with content like:

```
version https://git-lfs.github.com/spec/v1
oid sha256:...
size ...
```

then you only have pointer stubs, not the real models. Fix by pulling LFS objects before building:

```
git lfs install
git lfs pull
```

Verify real binaries by checking file sizes are large (KB/MB), not ~130 bytes.
