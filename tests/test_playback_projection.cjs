const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const appPath = path.join(__dirname, "..", "thecakeisapi", "webui", "static", "app.js");
const source = fs.readFileSync(appPath, "utf8");

function extractFunction(name) {
  const asyncStart = source.indexOf(`async function ${name}(`);
  const regularStart = source.indexOf(`function ${name}(`);
  const start = asyncStart >= 0 ? asyncStart : regularStart;
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
  "isLocalRadioPlayback",
  "isQueueTrackCurrent",
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
  queue: [
    {
      path: "Pi Queue.mp3",
      name: "Pi Queue.mp3",
      is_current: false,
      is_current_local: true,
      is_current_bose: false,
    },
    {
      path: "Bose Queue.mp3",
      name: "Bose Queue.mp3",
      is_current: true,
      is_current_local: false,
      is_current_bose: true,
    },
  ],
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

const localRadioState = structuredClone(playbackState);
localRadioState.outputs.local = {
  backend: "mpv",
  state: "playing",
  paused: false,
  source_type: "radio",
  source_name: "Example FM",
  elapsed_seconds: null,
  duration_seconds: null,
  now_playing: { path: null, name: "Example FM" },
  message: "Playing live radio on Pi: Example FM",
};

function playbackResponse(state) {
  return {
    ok: true,
    async json() {
      return state;
    },
  };
}

function createSelectorFlow(initialOutput = "bose") {
  let selectedOutputValue = initialOutput;
  let selectorSyncCount = 0;
  let refreshCount = 0;
  const rendered = [];
  const selectorContext = vm.createContext({
    lastPlaybackState: null,
    outputSelectionInitialized: false,
    isActivePlayback: helperContext.isActivePlayback,
    playbackView: helperContext.playbackView,
    selectOutput(output) {
      selectedOutputValue = output;
    },
    selectedOutput() {
      return selectedOutputValue;
    },
    updateRadioPresetsLauncher() {},
    updateBosePresetsLauncher() {},
    renderPlaybackState(state) {
      const outputState = helperContext.playbackView(state, selectedOutputValue);
      rendered.push({
        output: selectedOutputValue,
        title: helperContext.nowPlayingLabel(outputState),
        state: outputState.state,
      });
    },
    refreshPlaybackStatus() {
      refreshCount += 1;
    },
  });
  vm.runInContext(
    [
      "syncOutputSelector",
      "handleOutputSelectionChange",
      "renderPlaybackResponse",
      "transportOutput",
      "transportEndpoint",
    ].map(extractFunction).join("\n") +
      "\nthis.syncOutputSelector = syncOutputSelector;" +
      "\nthis.handleOutputSelectionChange = handleOutputSelectionChange;" +
      "\nthis.renderPlaybackResponse = renderPlaybackResponse;" +
      "\nthis.transportEndpoint = transportEndpoint;",
    selectorContext,
  );

  const initialSync = selectorContext.syncOutputSelector;
  selectorContext.syncOutputSelector = (state) => {
    selectorSyncCount += 1;
    initialSync(state);
  };

  return {
    context: selectorContext,
    rendered,
    select(output) {
      selectedOutputValue = output;
      selectorContext.handleOutputSelectionChange();
    },
    selectedOutput() {
      return selectedOutputValue;
    },
    selectorSyncCount() {
      return selectorSyncCount;
    },
    refreshCount() {
      return refreshCount;
    },
  };
}

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

test("local radio renders its station without exposing a queue path", () => {
  const localView = helperContext.playbackView(localRadioState, "local");

  assert.equal(helperContext.isLocalRadioPlayback(localView), true);
  assert.equal(helperContext.nowPlayingLabel(localView), "Example FM");
  assert.equal(localView.now_playing.path, null);
  assert.equal(localView.elapsed_seconds, null);
  assert.equal(localView.duration_seconds, null);
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

test("queue current state follows the selected output cursor", () => {
  assert.equal(helperContext.isQueueTrackCurrent(playbackState.queue[0], "local"), true);
  assert.equal(helperContext.isQueueTrackCurrent(playbackState.queue[0], "bose"), false);
  assert.equal(helperContext.isQueueTrackCurrent(playbackState.queue[1], "local"), false);
  assert.equal(helperContext.isQueueTrackCurrent(playbackState.queue[1], "bose"), true);
  assert.equal(
    helperContext.isQueueTrackCurrent(
      playbackState.queue[0],
      "local",
      localRadioState.outputs.local,
    ),
    false,
  );
});

test("local radio disables finite-track controls without changing repeat state", () => {
  function controlButton() {
    return {
      disabled: false,
      dataset: {},
      setAttribute(name, value) { this[name] = value; },
    };
  }

  const controls = {
    playButton: controlButton(),
    stopButton: controlButton(),
    previousButton: controlButton(),
    nextButton: controlButton(),
    repeatButton: controlButton(),
  };
  const controlContext = vm.createContext({
    ...controls,
    selectedOutput: () => "local",
  });
  vm.runInContext(
    [
      "isPausedPlayback",
      "isLocalRadioPlayback",
      "isExternalBosePlayback",
      "isQueueTrackCurrent",
      "updateTransportButtons",
    ].map(extractFunction).join("\n") +
      "\nthis.updateTransportButtons = updateTransportButtons;",
    controlContext,
  );

  controlContext.updateTransportButtons(
    localRadioState.outputs.local,
    localRadioState.queue,
    true,
  );

  assert.equal(controls.playButton.disabled, true);
  assert.equal(controls.stopButton.disabled, false);
  assert.equal(controls.previousButton.disabled, true);
  assert.equal(controls.nextButton.disabled, true);
  assert.equal(controls.repeatButton.disabled, true);
  assert.equal(controls.repeatButton.dataset.active, "true");
  assert.equal(helperContext.transportEndpoint("stop", "local"), "/api/player/local/stop");

  controlContext.updateTransportButtons(
    { ...localRadioState.outputs.local, state: "error", now_playing: null },
    localRadioState.queue,
    true,
  );
  assert.equal(controls.stopButton.disabled, false);
});

test("local radio timer is presented as live and remains non-seekable", () => {
  const timerContext = vm.createContext({
    elapsedTime: {},
    durationTime: {},
    trackProgress: {},
  });
  vm.runInContext(
    ["formatTime", "isLocalRadioPlayback", "renderTimer"].map(extractFunction).join("\n") +
      "\nthis.renderTimer = renderTimer;",
    timerContext,
  );

  timerContext.renderTimer(localRadioState.outputs.local);

  assert.equal(timerContext.elapsedTime.textContent, "LIVE");
  assert.equal(timerContext.durationTime.textContent, "--:--");
  assert.equal(timerContext.trackProgress.disabled, true);
  assert.equal(timerContext.trackProgress.value, 0);
});

test("selector initialization prefers an active legacy output then a sole active output", () => {
  const selected = [];
  const selectorContext = vm.createContext({
    outputSelectionInitialized: false,
    isActivePlayback: helperContext.isActivePlayback,
    playbackView: helperContext.playbackView,
    selectOutput(output) { selected.push(output); },
  });
  vm.runInContext(
    `${extractFunction("syncOutputSelector")}\n` +
      "this.syncOutputSelector = syncOutputSelector;",
    selectorContext,
  );

  selectorContext.syncOutputSelector(playbackState);
  assert.deepEqual(selected, ["bose"]);

  const localOnly = structuredClone(playbackState);
  localOnly.active_output = "bose";
  localOnly.outputs.bose.state = "stopped";
  selectorContext.outputSelectionInitialized = false;
  selectorContext.syncOutputSelector(localOnly);
  assert.deepEqual(selected, ["bose", "local"]);
});

test("selector change renders cached state before requesting refresh", () => {
  const calls = [];
  const selectionContext = vm.createContext({
    lastPlaybackState: playbackState,
    outputSelectionInitialized: false,
    updateRadioPresetsLauncher() { calls.push("radio-launcher"); },
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
  assert.deepEqual(calls, ["radio-launcher", "launcher", "render", "refresh"]);
});

test("explicit local selection survives repeated Bose-active status refreshes", async () => {
  const flow = createSelectorFlow();

  await flow.context.renderPlaybackResponse(playbackResponse(playbackState), true);
  assert.equal(flow.selectedOutput(), "bose");
  assert.deepEqual(flow.rendered.at(-1), {
    output: "bose",
    title: "Bose.mp3",
    state: "playing",
  });

  flow.select("local");
  await flow.context.renderPlaybackResponse(playbackResponse(playbackState));
  await flow.context.renderPlaybackResponse(playbackResponse(playbackState));

  assert.equal(flow.selectedOutput(), "local");
  assert.equal(flow.selectorSyncCount(), 1);
  assert.equal(flow.refreshCount(), 1);
  assert.deepEqual(flow.rendered.slice(-2), [
    { output: "local", title: "Pi.mp3", state: "paused" },
    { output: "local", title: "Pi.mp3", state: "paused" },
  ]);
  assert.equal(flow.context.transportEndpoint("next"), "/api/player/local/next");
});

test("selected Pi radio survives polling while Bose is also active", async () => {
  const flow = createSelectorFlow();

  await flow.context.renderPlaybackResponse(playbackResponse(localRadioState), true);
  flow.select("local");
  await flow.context.renderPlaybackResponse(playbackResponse(localRadioState));
  await flow.context.renderPlaybackResponse(playbackResponse(localRadioState));

  assert.equal(flow.selectedOutput(), "local");
  assert.equal(flow.selectorSyncCount(), 1);
  assert.deepEqual(flow.rendered.at(-1), {
    output: "local",
    title: "Example FM",
    state: "playing",
  });
  assert.equal(flow.context.transportEndpoint("stop"), "/api/player/local/stop");
});

test("explicit Bose selection survives repeated local-active status refreshes", async () => {
  const localPreferredState = structuredClone(playbackState);
  localPreferredState.active_output = "local";
  const flow = createSelectorFlow("local");

  await flow.context.renderPlaybackResponse(playbackResponse(localPreferredState), true);
  assert.equal(flow.selectedOutput(), "local");

  flow.select("bose");
  await flow.context.renderPlaybackResponse(playbackResponse(localPreferredState));
  await flow.context.renderPlaybackResponse(playbackResponse(localPreferredState));

  assert.equal(flow.selectedOutput(), "bose");
  assert.equal(flow.selectorSyncCount(), 1);
  assert.deepEqual(flow.rendered.at(-1), {
    output: "bose",
    title: "Bose.mp3",
    state: "playing",
  });
  assert.equal(flow.context.transportEndpoint("next"), "/api/player/bose/next");
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
