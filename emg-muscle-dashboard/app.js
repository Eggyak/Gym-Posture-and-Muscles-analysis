const state = {
  lastSeq: 0,
  connected: false,
  source: "fake",
  scenario: "resting",
  seriesA: Array.from({ length: 900 }, () => null),
  seriesB: Array.from({ length: 900 }, () => null),
};

const els = {
  sourceMode: document.getElementById("source-mode"),
  scenario: document.getElementById("scenario"),
  comPort: document.getElementById("com-port"),
  baudRate: document.getElementById("baud-rate"),
  startFakeBtn: document.getElementById("start-fake-btn"),
  connectSerialBtn: document.getElementById("connect-serial-btn"),
  disconnectBtn: document.getElementById("disconnect-btn"),
  connectionBadge: document.getElementById("connection-badge"),
  scenarioPill: document.getElementById("scenario-pill"),
  statusCopy: document.getElementById("status-copy"),
  emgChart: document.getElementById("emg-chart"),
  rawLine: document.getElementById("raw-line"),
  mvcA: document.getElementById("mvc-a"),
  mvcB: document.getElementById("mvc-b"),
  activation: document.getElementById("activation"),
  imbalance: document.getElementById("imbalance"),
  fatigue: document.getElementById("fatigue"),
  signalSource: document.getElementById("signal-source"),
  recommendation: document.getElementById("recommendation"),
};

function friendlyScenario(value) {
  return {
    resting: "Resting State",
    mild: "Mild Contractions",
    maximal: "Maximal Activation",
    fatigue: "Muscle Fatigue Detection",
    imbalance: "Identification of Muscle Imbalance",
  }[value] || value;
}

function drawChart() {
  const canvas = els.emgChart;
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#0f1c1d";
  ctx.fillRect(0, 0, width, height);

  const values = [...state.seriesA, ...state.seriesB].filter((value) => typeof value === "number");
  const maxAbs = Math.max(10, ...values.map((value) => Math.abs(value)));
  const zeroY = height / 2;

  ctx.strokeStyle = "rgba(255,255,255,0.10)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 6; i += 1) {
    const y = (height / 6) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  ctx.strokeStyle = "rgba(255,255,255,0.95)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(0, zeroY);
  ctx.lineTo(width, zeroY);
  ctx.stroke();

  ctx.fillStyle = "rgba(255,255,255,0.85)";
  ctx.font = "16px Space Grotesk";
  ctx.fillText("Raw 1", 24, 28);
  ctx.fillText("Raw 2", 110, 28);
  ctx.font = "14px Space Grotesk";
  ctx.fillText(`+${maxAbs.toFixed(0)}`, width - 60, 22);
  ctx.fillText("0", width - 22, zeroY - 8);
  ctx.fillText(`-${maxAbs.toFixed(0)}`, width - 62, height - 10);

  if (!state.connected) {
    ctx.font = "24px Space Grotesk";
    ctx.fillText("Start simulation or connect the sensor", 355, 250);
    return;
  }

  const drawSeries = (data, color) => {
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.2;
    let started = false;
    data.forEach((value, index) => {
      if (value === null) return;
      const x = (index / (data.length - 1)) * width;
      const normalized = Math.max(-1, Math.min(1, value / maxAbs));
      const y = zeroY - normalized * (height * 0.42);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    if (started) ctx.stroke();
  };

  drawSeries(state.seriesA, "#2d5bff");
  drawSeries(state.seriesB, "#ff3b30");
}

function computeFatigue(sensorA, sensorB, mvcA, mvcB) {
  const ratioA = mvcA > 0 ? Math.abs(sensorA) / mvcA : 0;
  const ratioB = mvcB > 0 ? Math.abs(sensorB) / mvcB : 0;
  const average = (ratioA + ratioB) / 2;
  if (average > 0.82) return "High";
  if (average > 0.55) return "Moderate";
  return "Low";
}

function recommendationText(source, scenario, imbalance, fatigue) {
  if (source === "serial") {
    if (imbalance > 45) return "Real EMG signals show noticeable left-right imbalance. Reduce load and correct technique symmetry.";
    if (fatigue === "High") return "Real EMG signals suggest high fatigue. Increase rest and avoid continuing at the same intensity.";
    return "Real EMG data is stable. Monitor trends across time for fatigue and imbalance changes.";
  }

  if (scenario === "resting") return "Resting state shows low baseline EMG. This is useful as a reference before exercise begins.";
  if (scenario === "mild") return "Mild contractions show moderate activation. This condition is ideal for warm-up and controlled movement checks.";
  if (scenario === "maximal") return "Maximal activation shows strong muscle recruitment. Use this to demonstrate peak effort and MVC behavior.";
  if (scenario === "fatigue") return "Fatigue mode demonstrates signal decay and instability over time. This helps explain reduced muscle performance.";
  return "Imbalance mode demonstrates stronger activation on one channel. This is useful to explain asymmetric muscle loading.";
}

async function pollStatus() {
  try {
    const response = await fetch(`/api/emg/status?since=${state.lastSeq}`, { cache: "no-store" });
    const data = await response.json();
    state.lastSeq = Number(data.seq || state.lastSeq);
    state.connected = Boolean(data.connected);
    state.source = data.source || state.source;
    state.scenario = data.scenario || state.scenario;

    const samples = Array.isArray(data.samples) ? data.samples : [];
    samples.forEach((sample) => {
      state.seriesA.push(typeof sample.a === "number" ? sample.a : null);
      state.seriesB.push(typeof sample.b === "number" ? sample.b : null);
      state.seriesA.shift();
      state.seriesB.shift();
    });

    els.connectionBadge.textContent = "Sensor Connected";
    els.connectionBadge.classList.toggle("warn", !data.connected);
    els.scenarioPill.textContent = friendlyScenario(state.scenario);
    els.signalSource.textContent = data.source ? data.source.toUpperCase() : "--";

    if (!data.connected) {
      els.mvcA.textContent = "--";
      els.mvcB.textContent = "--";
      els.activation.textContent = "--";
      els.imbalance.textContent = "--";
      els.fatigue.textContent = "--";
      els.rawLine.textContent = data.last_error ? `Error: ${data.last_error}` : "No EMG samples available yet.";
      els.recommendation.textContent = "Start a simulation scenario or connect the sensor to begin muscle analysis.";
      drawChart();
      return;
    }

    const sensorA = typeof data.sensor_a === "number" ? data.sensor_a : 0;
    const sensorB = typeof data.sensor_b === "number" ? data.sensor_b : 0;
    const mvcA = Number(data.mvc_a || 0);
    const mvcB = Number(data.mvc_b || 0);
    const imbalance = Number(data.imbalance || 0);
    const fatigue = computeFatigue(sensorA, sensorB, mvcA, mvcB);
    const activation = ((Math.abs(sensorA) + Math.abs(sensorB)) / 2).toFixed(0);

    els.mvcA.textContent = `${Math.round(mvcA)}`;
    els.mvcB.textContent = `${Math.round(mvcB)}`;
    els.activation.textContent = activation;
    els.imbalance.textContent = `${Math.round(imbalance)}`;
    els.fatigue.textContent = fatigue;
    els.rawLine.textContent = data.last_line ? `Latest sample: ${data.last_line}` : "Signal active";
    els.recommendation.textContent = recommendationText(data.source, data.scenario, imbalance, fatigue);
    drawChart();
  } catch (error) {
    els.connectionBadge.textContent = "Backend unavailable";
    els.connectionBadge.classList.add("warn");
    els.statusCopy.textContent = "Could not reach the backend server.";
  }
}

function resetPlot() {
  state.lastSeq = 0;
  state.seriesA = Array.from({ length: 900 }, () => null);
  state.seriesB = Array.from({ length: 900 }, () => null);
  drawChart();
}

async function startFakeMode() {
  resetPlot();
  const scenario = els.scenario.value;
  const response = await fetch("/api/emg/fake/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario }),
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.message || "Unable to start simulation mode.");
  }
  els.statusCopy.textContent = `Simulation running: ${friendlyScenario(scenario)}`;
}

async function connectSerial() {
  resetPlot();
  const response = await fetch("/api/emg/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      port: els.comPort.value.trim(),
      baud_rate: Number(els.baudRate.value) || 115200,
    }),
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.message || "Unable to connect COM port.");
  }
  els.statusCopy.textContent = data.message;
}

async function disconnectAll() {
  await fetch("/api/emg/disconnect", { method: "POST" });
  resetPlot();
  els.statusCopy.textContent = "Signal source stopped.";
}

els.startFakeBtn.addEventListener("click", async () => {
  try {
    await startFakeMode();
  } catch (error) {
    els.statusCopy.textContent = error.message;
  }
});

els.connectSerialBtn.addEventListener("click", async () => {
  try {
    await connectSerial();
  } catch (error) {
    els.statusCopy.textContent = error.message;
  }
});

els.disconnectBtn.addEventListener("click", async () => {
  try {
    await disconnectAll();
  } catch (error) {
    els.statusCopy.textContent = error.message;
  }
});

els.scenario.addEventListener("change", () => {
  els.scenarioPill.textContent = friendlyScenario(els.scenario.value);
});

drawChart();
setInterval(pollStatus, 40);
pollStatus();
