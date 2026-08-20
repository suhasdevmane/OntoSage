Put the DWG files here:

  Abacws floor 0.dwg
  Abacws floor 1.dwg
  Abacws floor 2.dwg
  Abacws floor 3.dwg
  Abacws floor 4.dwg
  Abacws floor 5.dwg

Download each from AutoCAD Web: click the red "A" (top left) to open the file
browser, then right-click a file -> Download.

No conversion step is needed. LibreDWG's WebAssembly build reads DWG directly.

The first read of each DWG is the slow part (LibreDWG parsing 10-30 MB), so
the result is cached next to the output as <name>.dwg.json and reused on
later runs. Delete the cache folder to force a re-read.
