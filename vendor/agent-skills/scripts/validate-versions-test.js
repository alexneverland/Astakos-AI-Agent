"use strict";

const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
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
  const manifest = JSON.parse(
    readFileSync(resolve(vendorRoot, manifestPath), "utf8"),
  );
  return manifest.version ?? manifest.plugins?.[0]?.version;
}

function readExpectedVersion() {
  if (existsSync(provenancePath)) {
    const provenance = readFileSync(provenancePath, "utf8");
    const match = provenance.match(/^- Release: `([^`]+)`$/m);
    assert.ok(match, `${provenancePath} must contain a release entry`);
    return match[1];
  }

  return execFileSync("git", ["describe", "--tags", "--abbrev=0"], {
    cwd: vendorRoot,
    encoding: "utf8",
  }).trim();
}

test("all plugin manifests use the vendored or standalone release", () => {
  const expectedVersion = readExpectedVersion();

  for (const manifestPath of manifestPaths) {
    assert.equal(
      readManifestVersion(manifestPath),
      expectedVersion,
      `${manifestPath} must use version ${expectedVersion}`,
    );
  }
});
