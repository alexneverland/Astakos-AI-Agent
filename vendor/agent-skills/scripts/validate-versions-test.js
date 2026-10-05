"use strict";

const assert = require("node:assert/strict");
const { existsSync, readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const test = require("node:test");

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
    assert.ok(match, `${provenancePath} must contain a release entry`);
    return match[1];
  }
  return readManifestVersion("plugin.json");
}

test("all plugin manifests use the vendored release or root plugin.json version", () => {
  const expectedVersion = readExpectedVersion();
  assert.ok(expectedVersion, "plugin.json must define a version");

  for (const manifestPath of manifestPaths) {
    assert.equal(
      readManifestVersion(manifestPath),
      expectedVersion,
      `${manifestPath} must use version ${expectedVersion}`,
    );
  }
});
