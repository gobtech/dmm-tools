#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { Document, Packer, Paragraph, TextRun, LevelFormat, AlignmentType, UnderlineType } = require('docx');

// --- CLI argument parsing ---
const args = process.argv.slice(2);

function getArg(flag) {
  const idx = args.indexOf(flag);
  if (idx === -1 || idx + 1 >= args.length) return null;
  return args[idx + 1];
}

function getFlag(flag) {
  return args.includes(flag);
}

const artist = getArg('--artist');
const inputDir = getArg('--input');
const inputFiles = getArg('--files');
const outputPath = getArg('--output');
const period = getArg('--period') || 'last 28 days';
const helpFlag = getFlag('--help') || getFlag('-h');

if (helpFlag || (!inputDir && !inputFiles)) {
  console.log(`
Djo Airplay Report Generator
=============================

Usage:
  node generate_report.js --artist "Artist Name" --input ./csv-folder/ --output report.docx
  node generate_report.js --artist "Artist Name" --files ar.csv,br.csv,co.csv --output report.docx

Options:
  --artist   Artist name (used in filename if no --output specified)
  --input    Directory containing CSV files (named *_XX_*.csv where XX is country code)
  --files    Comma-separated list of CSV file paths
  --output   Output .docx file path (default: auto-generated from artist name)
  --period   Time period label for report title (default: "last 28 days")
  --help     Show this help message

CSV Requirements:
  - Must contain columns: Song, Station, 28D, Country
  - Country code is extracted from the "Country" column in the CSV

Country Codes (auto-detected from filename or CSV content):
  AR = Argentina, BR = Brazil, CL = Chile, CO = Colombia,
  CR = Costa Rica, EC = Ecuador, MX = Mexico, PE = Peru, etc.

Examples:
  # Process all CSVs in a folder
  node generate_report.js --artist "Djo" --input ./data/djo/

  # Process specific files
  node generate_report.js --artist "Djo" --files djo_ar.csv,djo_br.csv --output djo_report.docx
`);
  process.exit(0);
}

// --- Country code mapping ---
const COUNTRY_MAP = {
  'argentina': 'ARGENTINA',
  'brazil': 'BRAZIL',
  'brasil': 'BRAZIL',
  'chile': 'CHILE',
  'colombia': 'COLOMBIA',
  'costa rica': 'COSTA RICA',
  'ecuador': 'ECUADOR',
  'mexico': 'MEXICO',
  'méxico': 'MEXICO',
  'panama': 'PANAMA',
  'panamá': 'PANAMA',
  'peru': 'PERU',
  'perú': 'PERU',
  'uruguay': 'URUGUAY',
  'venezuela': 'VENEZUELA',
  'spain': 'SPAIN',
  'españa': 'SPAIN',
  'united states': 'UNITED STATES',
  'canada': 'CANADA',
  'dominican republic': 'DOMINICAN REPUBLIC',
  'guatemala': 'GUATEMALA',
  'honduras': 'HONDURAS',
  'el salvador': 'EL SALVADOR',
  'paraguay': 'PARAGUAY',
  'bolivia': 'BOLIVIA',
  'nicaragua': 'NICARAGUA',
  'puerto rico': 'PUERTO RICO',
};

// --- CSV parser ---
function parseCSV(filepath) {
  const content = fs.readFileSync(filepath, 'utf-8');
  const lines = content.trim().split('\n');

  // Parse header to find column indices
  const headerLine = lines[0];
  const headers = parseCSVLine(headerLine).map(h => h.trim().toLowerCase());

  const songIdx = headers.indexOf('song');
  const stationIdx = headers.indexOf('station');
  const plays28dIdx = headers.indexOf('28d');
  const countryIdx = headers.indexOf('country');

  if (songIdx === -1 || stationIdx === -1 || plays28dIdx === -1) {
    console.error(`Error: CSV ${filepath} missing required columns (Song, Station, 28D)`);
    console.error(`Found headers: ${headers.join(', ')}`);
    process.exit(1);
  }

  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    if (!lines[i].trim()) continue;
    const fields = parseCSVLine(lines[i]);
    const song = fields[songIdx]?.trim();
    const station = fields[stationIdx]?.trim();
    const plays28d = parseInt(fields[plays28dIdx]) || 0;
    const country = countryIdx !== -1 ? fields[countryIdx]?.trim() : null;

    if (plays28d > 0 && song && station) {
      rows.push({ song, station, plays28d, country });
    }
  }
  return rows;
}

function parseCSVLine(line) {
  const fields = [];
  let current = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < line.length && line[i + 1] === '"') {
          current += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        current += ch;
      }
    } else {
      if (ch === '"') {
        inQuotes = true;
      } else if (ch === ',') {
        fields.push(current);
        current = '';
      } else {
        current += ch;
      }
    }
  }
  fields.push(current);
  return fields;
}

// --- Collect CSV files ---
let csvFiles = [];

if (inputDir) {
  if (!fs.existsSync(inputDir)) {
    console.error(`Error: Input directory "${inputDir}" does not exist`);
    process.exit(1);
  }
  csvFiles = fs.readdirSync(inputDir)
    .filter(f => f.toLowerCase().endsWith('.csv'))
    .map(f => path.join(inputDir, f))
    .sort();
} else if (inputFiles) {
  csvFiles = inputFiles.split(',').map(f => f.trim());
  for (const f of csvFiles) {
    if (!fs.existsSync(f)) {
      console.error(`Error: File "${f}" does not exist`);
      process.exit(1);
    }
  }
}

if (csvFiles.length === 0) {
  console.error('Error: No CSV files found');
  process.exit(1);
}

console.log(`Processing ${csvFiles.length} CSV file(s)...`);

// --- Parse all files and group by country ---
const countryData = {}; // country -> [{ song, station, plays28d }]

for (const file of csvFiles) {
  console.log(`  Reading: ${path.basename(file)}`);
  const rows = parseCSV(file);

  for (const row of rows) {
    let countryKey = 'UNKNOWN';
    if (row.country) {
      const normalized = row.country.toLowerCase().trim();
      countryKey = COUNTRY_MAP[normalized] || row.country.toUpperCase();
    }
    if (!countryData[countryKey]) countryData[countryKey] = [];
    countryData[countryKey].push(row);
  }
}

// Sort countries alphabetically
const countries = Object.keys(countryData).sort();

if (countries.length === 0) {
  console.error('Error: No data with 28D > 0 found in any file');
  process.exit(1);
}

console.log(`Found data for ${countries.length} country/countries: ${countries.join(', ')}`);

// --- Build document ---
const children = [];

// Title
const titleText = artist
  ? `Radio Plays (${period}) — ${artist}`
  : `Radio Plays (${period})`;

children.push(new Paragraph({
  spacing: { after: 200, line: 240 },
  children: [new TextRun({ text: titleText, bold: true, color: 'CC0000', size: 28, font: 'Arial' })]
}));

let totalEntries = 0;

for (const country of countries) {
  const rows = countryData[country];

  // Group by station
  const stationMap = {};
  for (const row of rows) {
    if (!stationMap[row.station]) stationMap[row.station] = [];
    // Check for duplicates (same song in same station from different files)
    const existing = stationMap[row.station].find(s => s.song === row.song);
    if (existing) {
      existing.plays = Math.max(existing.plays, row.plays28d); // take highest if duplicate
    } else {
      stationMap[row.station].push({ song: row.song, plays: row.plays28d });
    }
  }

  // Sort stations alphabetically
  const stations = Object.keys(stationMap).sort((a, b) => a.localeCompare(b));

  if (stations.length === 0) continue;

  // Country heading
  children.push(new Paragraph({
    spacing: { before: 240, after: 80, line: 240 },
    children: [new TextRun({
      text: country,
      color: '4A86C8',
      size: 24,
      font: 'Arial',
      underline: { type: UnderlineType.SINGLE }
    })]
  }));

  for (const station of stations) {
    const songs = stationMap[station];
    songs.sort((a, b) => b.plays - a.plays);

    // Station name + songs as a single paragraph with line breaks
    // This prevents Google Docs from adding spacing between each song
    const runs = [new TextRun({ text: station, bold: true, size: 22, font: 'Arial' })];
    for (const song of songs) {
      runs.push(new TextRun({ text: `     \u2022  ${song.song} (${song.plays}x)`, size: 22, font: 'Arial', break: 1 }));
      totalEntries++;
    }

    children.push(new Paragraph({
      spacing: { before: 80, after: 20, line: 240 },
      children: runs,
    }));
  }
}

const doc = new Document({
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    children
  }]
});

// --- Output ---
const defaultOutput = artist
  ? `${artist.toLowerCase().replace(/\s+/g, '_')}_radio_plays_28d.docx`
  : 'radio_plays_28d.docx';

const finalOutput = outputPath || defaultOutput;

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(finalOutput, buffer);
  console.log(`\nReport saved: ${finalOutput}`);
  console.log(`  Countries: ${countries.length}`);
  const totalStations = Object.values(countryData).reduce((acc, rows) => {
    const stations = new Set(rows.map(r => r.station));
    return acc + stations.size;
  }, 0);
  console.log(`  Stations: ${totalStations}`);
  console.log(`  Entries: ${totalEntries}`);
});
