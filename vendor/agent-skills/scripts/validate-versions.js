#!/usr/bin/env node

"use strict";

const { existsSync, readFileSync } = require("node:fs");
const { resolve } = require("node:path");

const vendorRoot = resolve(__dirname, "..");
const provenancePath = resolve(vendorRoot, "..", "agent-skills.UPSTREAM.md");

const manifestPaths = [
  "plugin.json",
  ".codex-plugin/plugin.json",
  ".claude-plugin/plugin.json",
  ".claude-plugin/marketplace.json",
  ".agents/plugins/marketplace.json",
];

function readManifestVersion(manifestPath) {
  const manifest = JSON.parse(readFileSync(resolve(vendorRoot, manifestPath), "utf8"));
  return manifest.version ?? manifest.plugins?.[0]?.version;
}

function readExpectedVersion() {
  if (existsSync(provenancePath)) {
    const match = readFileSync(provenancePath, "utf8").match(/^- Release: `([^`]+)`$/m);
    if (!match) {
      throw new Error(`${provenancePath} is missing a release entry`);
    }
    return match[1];
  }
  return readManifestVersion("plugin.json");
}

const expectedVersion = readExpectedVersion();
if (!expectedVersion) {
  throw new Error("plugin.json is missing a version field");
}

for (const manifestPath of manifestPaths) {
  const version = readManifestVersion(manifestPath);
  if (version !== expectedVersion) {
    throw new Error(
      `${manifestPath} has version ${version ?? "<missing>"}; expected ${expectedVersion}`,
    );
  }
}

console.log(`All plugin manifests use version ${expectedVersion}.`);
