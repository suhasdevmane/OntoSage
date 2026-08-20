#!/usr/bin/env node
/**
 * DWG -> JSON reader, using LibreDWG compiled to WebAssembly.
 *
 * Why this exists: ezdxf cannot read DWG, and neither the ODA File Converter
 * nor libredwg-tools is installable in every environment. This gets the same
 * job done with `npm i @mlightcad/libredwg-web` and nothing else - the WASM
 * build of LibreDWG reads the DWG directly and hands back a full database
 * (header, layer table, block records, modelspace entities).
 *
 * Output is a compact JSON document consumed by pipeline/from_dwg_json.py.
 * Only the entity kinds the knowledge-graph pipeline cares about are kept,
 * because a full Abacws floor dump is hundreds of megabytes of JSON.
 *
 * Usage:
 *   node tools/dwg_read.mjs <input.dwg> <output.json> [--all-entities]
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const KEEP = new Set([
  'LWPOLYLINE', 'POLYLINE', 'INSERT', 'TEXT', 'MTEXT',
  'DIMENSION', 'HATCH', 'CIRCLE', 'LINE', 'ARC', 'ATTRIB', 'ATTDEF',
]);

function point(p) {
  if (!p) return null;
  return p.z === undefined ? [p.x, p.y] : [p.x, p.y, p.z];
}

function slimEntity(e) {
  const base = {
    type: e.type,
    handle: e.handle,
    layer: e.layer,
    paperSpace: !!e.isInPaperSpace,
  };
  if (e.xdata) base.xdata = e.xdata;

  switch (e.type) {
    case 'LWPOLYLINE':
      return {
        ...base,
        closed: (e.flag & 1) === 1,
        elevation: e.elevation,
        vertices: (e.vertices || []).map((v) => [v.x, v.y, v.bulge || 0]),
      };
    case 'POLYLINE':
      return {
        ...base,
        closed: !!(e.flag & 1),
        vertices: (e.vertices || []).map((v) => point(v.position ?? v)),
      };
    case 'INSERT':
      return {
        ...base,
        name: e.name,
        insertionPoint: point(e.insertionPoint),
        rotation: e.rotation,
        xScale: e.xScale,
        yScale: e.yScale,
        attribs: (e.attribs || []).map((a) => ({
          tag: a.tag,
          text: a.text,
          layer: a.layer,
        })),
      };
    case 'TEXT':
      return {
        ...base,
        text: e.text,
        height: e.height,
        rotation: e.rotation,
        insertionPoint: point(e.startPoint ?? e.insertionPoint),
        secondPoint: point(e.endPoint ?? e.secondAlignmentPoint),
      };
    case 'MTEXT':
      return {
        ...base,
        text: e.text,
        height: e.height,
        rotation: e.rotation,
        insertionPoint: point(e.insertionPoint),
        width: e.width,
      };
    case 'DIMENSION':
      // The whole point of asking for dimensions: `measurement` is the value
      // AutoCAD computed from the geometry, in drawing units. `text` is the
      // override the drafter typed, if any ("<>" means "use measurement").
      return {
        ...base,
        dimensionType: e.dimensionType,
        subclassMarker: e.subclassMarker,
        measurement: e.measurement,
        text: e.text,
        styleName: e.styleName ?? e.name,
        definitionPoint: point(e.definitionPoint),
        textPoint: point(e.textPoint),
        insertionPoint: point(e.insertionPoint),
        subDefinitionPoint1: point(e.subDefinitionPoint1),
        subDefinitionPoint2: point(e.subDefinitionPoint2),
        rotationAngle: e.rotationAngle,
      };
    case 'CIRCLE':
      return { ...base, center: point(e.center), radius: e.radius };
    case 'ARC':
      return {
        ...base, center: point(e.center), radius: e.radius,
        startAngle: e.startAngle, endAngle: e.endAngle,
      };
    case 'LINE':
      return { ...base, start: point(e.startPoint), end: point(e.endPoint) };
    case 'HATCH':
      return { ...base, patternName: e.patternName, elevation: e.elevation };
    default:
      return base;
  }
}

async function main() {
  const [input, output, ...flags] = process.argv.slice(2);
  if (!input || !output) {
    console.error('usage: node dwg_read.mjs <input.dwg> <output.json> [--all-entities]');
    process.exit(2);
  }
  const keepAll = flags.includes('--all-entities');

  const { LibreDwg, Dwg_File_Type } = await import('@mlightcad/libredwg-web');

  // The package restricts subpath exports, so resolve the wasm directory by
  // walking up from the resolved entry point rather than require.resolve().
  const entry = fileURLToPath(await import.meta.resolve('@mlightcad/libredwg-web'));
  const wasmDir = join(dirname(dirname(entry)), 'wasm');

  process.stderr.write('Loading LibreDWG WASM...\n');
  const libredwg = await LibreDwg.create(wasmDir);

  const bytes = readFileSync(input);
  process.stderr.write(`Reading ${input} (${(bytes.length / 1048576).toFixed(1)} MB)...\n`);

  const ptr = libredwg.dwg_read_data(
    bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    Dwg_File_Type.DWG,
  );
  if (ptr === undefined || ptr === null || ptr === 0) {
    console.error(`FAILED: LibreDWG could not parse ${input}`);
    process.exit(1);
  }

  const { database: db, stats } = libredwg.convertEx(ptr);
  libredwg.dwg_free(ptr);

  // A non-zero pointer is NOT proof of a successful read - LibreDWG returns a
  // pointer alongside a non-fatal error code for a malformed file. Validate
  // the converted database instead.
  const entityCount = (db.entities || []).length;
  const layerCount = (db.tables?.LAYER?.entries || []).length;
  if (entityCount === 0 && layerCount === 0) {
    console.error(`FAILED: ${input} parsed to an empty database - not a readable DWG.`);
    process.exit(1);
  }

  const entities = (db.entities || [])
    .filter((e) => keepAll || KEEP.has(e.type))
    .map(slimEntity);

  const typeCounts = {};
  for (const e of db.entities || []) {
    typeCounts[e.type] = (typeCounts[e.type] || 0) + 1;
  }

  const layers = (db.tables?.LAYER?.entries || []).map((l) => ({
    name: l.name,
    colorIndex: l.colorIndex,
    isOff: l.isOff,
    isFrozen: l.isFrozen,
  }));

  const payload = {
    source: input,
    header: {
      INSUNITS: db.header?.INSUNITS,
      ACADVER: db.header?.ACADVER,
      EXTMIN: point(db.header?.EXTMIN),
      EXTMAX: point(db.header?.EXTMAX),
      DIMSCALE: db.header?.DIMSCALE,
    },
    layers,
    blockRecords: (db.tables?.BLOCK_RECORD?.entries || []).map((b) => b.name),
    entityTypeCounts: typeCounts,
    unknownEntityCount: stats?.unknownEntityCount ?? 0,
    entities,
  };

  writeFileSync(output, JSON.stringify(payload));
  process.stderr.write(
    `Wrote ${output}: ${entities.length} kept of ${(db.entities || []).length} entities, ` +
    `${layers.length} layers, ${stats?.unknownEntityCount ?? 0} unknown\n`,
  );
}

main().catch((err) => {
  console.error('ERROR:', err?.message || err);
  process.exit(1);
});
