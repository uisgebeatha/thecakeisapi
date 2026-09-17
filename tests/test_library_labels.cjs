const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const appPath = path.join(__dirname, "..", "thecakeisapi", "webui", "static", "app.js");
const source = fs.readFileSync(appPath, "utf8");
const start = source.indexOf("function entryTypeLabel(entry) {");
const end = source.indexOf("\nasync function playTrack(", start);
assert.ok(start >= 0 && end > start, "library entry renderer is present");

const context = vm.createContext({
  document: {
    createElement(tagName) {
      return {
        tagName,
        children: [],
        append(...children) { this.children.push(...children); },
        appendChild(child) { this.children.push(child); },
        addEventListener() {},
      };
    },
  },
  formatSize: () => "1 MB",
});
vm.runInContext(`${source.slice(start, end)}\nthis.createEntry = createEntry;`, context);

for (const [type, name, expected] of [
  ["directory", "Album.mp3", "DIR"],
  ["file", "song.mp3", "MP3"],
  ["file", "song.MP3", "MP3"],
  ["file", "song.flac", "FLAC"],
  ["file", "song.FLAC", "FLAC"],
  ["file", "song.wav", "AUD"],
]) {
  test(`${type} ${name} displays ${expected}`, () => {
    const item = context.createEntry({ type, name, path: name, size_bytes: 1 });
    const icon = item.children[0].children[0].children[0];
    assert.equal(icon.textContent, expected);
  });
}
