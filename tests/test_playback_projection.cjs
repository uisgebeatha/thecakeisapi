const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const appPath = path.join(__dirname, "..", "thecakeisapi", "webui", "static", "app.js");
const source = fs.readFileSync(appPath, "utf8");

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} is present`);

  const bodyStart = source.indexOf("{", start);
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === "{") {
      depth += 1;
    } else if (source[index] === "}") {
      depth -= 1;
      if (depth === 0) {
        return source.slice(start, index + 1);
      }
    }
  }

  throw new Error(`${name} function body is incomplete`);
}

const helperNames = [
  "playbackView",
  "nowPlayingLabel",
  "isPausedPlayback",
  "isActivePlayback",
  "transportEndpoint",
  "playPauseAction",
];
const helperContext = vm.createContext({});
vm.runInContext(
  `${helperNames.map(extractFunction).join("\n")}\n` +
    helperNames.map((name) => `this.${name} = ${name};`).join("\n"),
  helperContext,
);

const playbackState = {
  active_output: "bose",
  repeat_track: true,
  queue: [{ path: "Queued.mp3", name: "Queued.mp3", is_current: true }],
  outputs: {
    local: {
      backend: "mpv",
      state: "paused",
      paused: true,
      elapsed_seconds: 12,
      duration_seconds: 90,
      now_playing: { path: "Pi.mp3", name: "Pi.mp3" },
      message: "Paused",
    },
    bose: {
      backend: "bose_aftertouch",
      state: "playing",
      paused: false,
      elapsed_seconds: 30,
      duration_seconds: 180,
      now_playing: { path: "Bose.mp3", name: "Bose.mp3" },
      message: "Playing on Bose: Bose.mp3",
      external_playback_active: false,
    },
  },
};

test("Pi to Bose to Pi restores each output projection", () => {
  const localView = helperContext.playbackView(playbackState, "local");
  const boseView = helperContext.playbackView(playbackState, "bose");
  const restoredLocalView = helperContext.playbackView(playbackState, "local");

  assert.equal(helperContext.nowPlayingLabel(localView), "Pi.mp3");
  assert.equal(localView.state, "paused");
  assert.equal(localView.elapsed_seconds, 12);
  assert.equal(localView.duration_seconds, 90);
  assert.equal(helperContext.isPausedPlayback(localView), true);

  assert.equal(helperContext.nowPlayingLabel(boseView), "Bose.mp3");
  assert.equal(boseView.state, "playing");
  assert.equal(boseView.elapsed_seconds, 30);
  assert.equal(boseView.duration_seconds, 180);
  assert.equal(helperContext.isActivePlayback(boseView), true);

  assert.deepEqual(restoredLocalView, localView);
});

test("external Bose title is rendered from the Bose projection", () => {
  const externalState = structuredClone(playbackState);
  externalState.outputs.bose = {
    state: "stopped",
    now_playing: { path: null, name: "BBC Radio 2" },
    external_playback_active: true,
    external_display_name: "BBC Radio 2",
    external_source: "TUNEIN",
  };

  const boseView = helperContext.playbackView(externalState, "bose");

  assert.equal(helperContext.nowPlayingLabel(boseView), "BBC Radio 2");
  assert.equal(boseView.external_source, "TUNEIN");
  assert.equal(helperContext.nowPlayingLabel(externalState.outputs.local), "Pi.mp3");
});

test("transport and Play Pause use the selected projection", () => {
  assert.equal(helperContext.transportEndpoint("next", "local"), "/api/player/local/next");
  assert.equal(helperContext.transportEndpoint("next", "bose"), "/api/player/bose/next");
  assert.equal(
    helperContext.playPauseAction(helperContext.playbackView(playbackState, "local")),
    "resume",
  );
  assert.equal(
    helperContext.playPauseAction(helperContext.playbackView(playbackState, "bose")),
    "pause",
  );
});

test("selector change renders cached state before requesting refresh", () => {
  const calls = [];
  const selectionContext = vm.createContext({
    lastPlaybackState: playbackState,
    outputSelectionInitialized: false,
    updateBosePresetsLauncher() { calls.push("launcher"); },
    renderPlaybackState(state) {
      assert.equal(state, playbackState);
      calls.push("render");
    },
    refreshPlaybackStatus() { calls.push("refresh"); },
  });
  vm.runInContext(
    `${extractFunction("handleOutputSelectionChange")}\n` +
      "this.handleOutputSelectionChange = handleOutputSelectionChange;",
    selectionContext,
  );

  selectionContext.handleOutputSelectionChange();

  assert.equal(selectionContext.outputSelectionInitialized, true);
  assert.deepEqual(calls, ["launcher", "render", "refresh"]);
});

test("status refresh observes Bose only while Bose is selected", () => {
  const statusUrlContext = vm.createContext({ selectedOutput: () => "bose" });
  vm.runInContext(
    `${extractFunction("playbackStatusUrl")}\nthis.playbackStatusUrl = playbackStatusUrl;`,
    statusUrlContext,
  );
  assert.equal(statusUrlContext.playbackStatusUrl(), "/api/player/status?observe_bose=true");

  statusUrlContext.selectedOutput = () => "local";
  assert.equal(statusUrlContext.playbackStatusUrl(), "/api/player/status");
});
