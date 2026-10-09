const STORAGE_KEYS = {
  currentUser: "gym-dashboard-current-user",
};

const state = {
  currentUser: null,
  sessionConfig: null,
  session: null,
  cameraActive: false,
  bluetoothConnected: false,
  sessionInterval: null,
  posturePollInterval: null,
  emgPollInterval: null,
  emgLastSeq: 0,
  emgSeriesA: Array.from({ length: 500 }, () => null),
  emgSeriesB: Array.from({ length: 500 }, () => null),
};

const els = {
  pageTitle: document.getElementById("page-title"),
  authView: document.getElementById("auth-view"),
  signupView: document.getElementById("signup-view"),
  setupView: document.getElementById("setup-view"),
  sessionView: document.getElementById("session-view"),
  summaryView: document.getElementById("summary-view"),
  loginForm: document.getElementById("login-form"),
  signupForm: document.getElementById("signup-form"),
  goSignupBtn: document.getElementById("go-signup-btn"),
  goLoginBtn: document.getElementById("go-login-btn"),
  logoutBtn: document.getElementById("logout-btn"),
  userChip: document.getElementById("user-chip"),
  setupForm: document.getElementById("setup-form"),
  analysisType: document.getElementById("analysis-type"),
  exerciseType: document.getElementById("exercise-type"),
  cameraSource: document.getElementById("camera-source"),
  esp32Url: document.getElementById("esp32-url"),
  targetReps: document.getElementById("target-reps"),
  totalSets: document.getElementById("total-sets"),
  restSeconds: document.getElementById("rest-seconds"),
  monitorSeconds: document.getElementById("monitor-seconds"),
  setupCopy: document.getElementById("setup-copy"),
  sessionHeading: document.getElementById("session-heading"),
  analysisPill: document.getElementById("analysis-pill"),
  exercisePill: document.getElementById("exercise-pill"),
  elapsedTimer: document.getElementById("elapsed-timer"),
  currentSet: document.getElementById("current-set"),
  repCounter: document.getElementById("rep-counter"),
  restTimer: document.getElementById("rest-timer"),
  muscleTimer: document.getElementById("muscle-timer"),
  cameraBtn: document.getElementById("camera-btn"),
  bluetoothBtn: document.getElementById("bluetooth-btn"),
  emgPort: document.getElementById("emg-port"),
  emgBaud: document.getElementById("emg-baud"),
  repBtn: document.getElementById("rep-btn"),
  finishBtn: document.getElementById("finish-btn"),
  cameraFeed: document.getElementById("camera-feed"),
  cameraStatus: document.getElementById("camera-status"),
  postureStage: document.getElementById("posture-stage"),
  postureScore: document.getElementById("posture-score"),
  postureRecommendation: document.getElementById("posture-recommendation"),
  bluetoothStatus: document.getElementById("bluetooth-status"),
  mvcA: document.getElementById("mvc-a"),
  mvcB: document.getElementById("mvc-b"),
  activationLevel: document.getElementById("activation-level"),
  imbalanceLevel: document.getElementById("imbalance-level"),
  fatigueLevel: document.getElementById("fatigue-level"),
  muscleRecommendation: document.getElementById("muscle-recommendation"),
  emgRawLine: document.getElementById("emg-raw-line"),
  summaryContent: document.getElementById("summary-content"),
  doctorBtn: document.getElementById("doctor-btn"),
  doctorResults: document.getElementById("doctor-results"),
  newSessionBtn: document.getElementById("new-session-btn"),
  toast: document.getElementById("toast"),
  cameraCard: document.getElementById("camera-card"),
  muscleCard: document.getElementById("muscle-card"),
  emgChart: document.getElementById("emg-chart"),
};

function formatTime(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
  const seconds = Math.floor(totalSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function capitalize(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => els.toast.classList.add("hidden"), 2600);
}

function setView(view) {
  const views = {
    auth: { element: els.authView, title: "Login" },
    signup: { element: els.signupView, title: "Signup" },
    setup: { element: els.setupView, title: "Session Setup" },
    session: { element: els.sessionView, title: "Live Dashboard" },
    summary: { element: els.summaryView, title: "Session Summary" },
  };
  Object.values(views).forEach(({ element }) => element.classList.remove("active"));
  views[view].element.classList.add("active");
  els.pageTitle.textContent = views[view].title;
}

function updateAuthUI() {
  if (state.currentUser) {
    els.userChip.textContent = state.currentUser.name || state.currentUser.email;
    els.userChip.classList.remove("hidden");
    els.logoutBtn.classList.remove("hidden");
  } else {
    els.userChip.classList.add("hidden");
    els.logoutBtn.classList.add("hidden");
  }
}

function loginUser(user) {
  state.currentUser = user;
  localStorage.setItem(STORAGE_KEYS.currentUser, JSON.stringify(user));
  updateAuthUI();
  setView("setup");
}

function logoutUser() {
  stopSession();
  state.currentUser = null;
  localStorage.removeItem(STORAGE_KEYS.currentUser);
  updateAuthUI();
  setView("auth");
}

function getSetupNarrative(type) {
  if (type === "posture") {
    return "Posture mode now uses your Python MediaPipe code path through the local server, with Laptop Webcam or ESP32-CAM selection.";
  }
  if (type === "muscle") {
    return "Muscle mode reads real ESP32 Bluetooth serial values through the Python bridge.";
  }
  return "Combined mode uses Python posture analysis and the Python ESP32 serial bridge together.";
}

function updateSetupFields() {
  els.setupCopy.textContent = getSetupNarrative(els.analysisType.value);
}

function drawChart() {
  const canvas = els.emgChart;
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#0f1c1d";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(255,255,255,0.12)";
  ctx.lineWidth = 1;
  for (let index = 1; index < 5; index += 1) {
    const y = (height / 5) * index;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  ctx.fillStyle = "rgba(255,255,255,0.8)";
  ctx.font = "16px Space Grotesk";
  ctx.fillText("Raw 1", 24, 28);
  ctx.fillText("Raw 2", 110, 28);

  if (!state.bluetoothConnected) {
    ctx.font = "24px Space Grotesk";
    ctx.fillText("Waiting for ESP32 EMG connection", 215, 150);
    ctx.font = "16px Space Grotesk";
    ctx.fillText("Use the Bluetooth COM port assigned by Windows", 225, 182);
    return;
  }

  const values = [...state.emgSeriesA, ...state.emgSeriesB].filter((value) => typeof value === "number");
  const maxAbs = Math.max(10, ...values.map((value) => Math.abs(value)));
  const zeroY = height / 2;

  ctx.strokeStyle = "rgba(255,255,255,0.9)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(0, zeroY);
  ctx.lineTo(width, zeroY);
  ctx.stroke();

  ctx.fillStyle = "rgba(255,255,255,0.7)";
  ctx.font = "14px Space Grotesk";
  ctx.fillText(`+${maxAbs.toFixed(0)}`, width - 58, 20);
  ctx.fillText("0", width - 22, zeroY - 6);
  ctx.fillText(`-${maxAbs.toFixed(0)}`, width - 60, height - 10);

  const drawSeries = (data, color) => {
    let started = false;
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
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

  drawSeries(state.emgSeriesA, "#ff7a45");
  drawSeries(state.emgSeriesB, "#49c6c7");
}

function renderSessionConfig() {
  const { analysisType, exerciseType, totalSets, targetReps } = state.sessionConfig;
  const titles = {
    posture: "Posture Analysis",
    muscle: "Muscle Analysis",
    both: "Combined Analysis",
  };
  els.sessionHeading.textContent = `${titles[analysisType]} for ${capitalize(exerciseType)}`;
  els.analysisPill.textContent = capitalize(analysisType);
  els.exercisePill.textContent = capitalize(exerciseType);
  els.currentSet.textContent = `${state.session.currentSet} / ${totalSets}`;
  els.repCounter.textContent = `${state.session.completedReps} / ${targetReps}`;
  els.restTimer.textContent = analysisType === "muscle" ? "Timer active" : "Ready";

  const showCamera = analysisType === "posture" || analysisType === "both";
  const showMuscle = analysisType === "muscle" || analysisType === "both";
  els.cameraCard.classList.toggle("hidden", !showCamera);
  els.muscleCard.classList.toggle("hidden", !showMuscle);
}

function renderSessionState() {
  if (!state.session) return;
  const { targetReps, totalSets } = state.sessionConfig;
  els.currentSet.textContent = `${state.session.currentSet} / ${totalSets}`;
  els.repCounter.textContent = `${state.session.completedReps} / ${targetReps}`;
  els.postureStage.textContent = `Stage: ${state.session.stage}`;
  els.postureScore.textContent = `Form score: ${state.session.postureScore}%`;
  els.postureRecommendation.textContent = state.session.postureTip;
  drawChart();
}

function computeFatigue(sensorA, sensorB, mvcA, mvcB) {
  const ratioA = mvcA > 0 ? sensorA / mvcA : 0;
  const ratioB = mvcB > 0 ? sensorB / mvcB : 0;
  const average = (ratioA + ratioB) / 2;
  if (average > 0.8) return "High";
  if (average > 0.55) return "Moderate";
  return "Low";
}

async function pollEmgStatus() {
  try {
    const response = await fetch(`/api/emg/status?since=${state.emgLastSeq}`, { cache: "no-store" });
    const data = await response.json();
    state.bluetoothConnected = Boolean(data.connected);
    state.emgLastSeq = Number(data.seq || state.emgLastSeq);
    els.bluetoothStatus.textContent = data.connected ? `ESP32 connected: ${data.port}` : "ESP32 not connected";
    els.bluetoothStatus.classList.toggle("warn", !data.connected);
    els.emgRawLine.textContent = data.last_line ? `Raw: ${data.last_line}` : data.last_error ? `Error: ${data.last_error}` : "";

    if (!data.connected) {
      els.mvcA.textContent = "--";
      els.mvcB.textContent = "--";
      els.activationLevel.textContent = "--";
      els.imbalanceLevel.textContent = "--";
      els.fatigueLevel.textContent = "--";
      els.muscleRecommendation.textContent = data.last_error || "Waiting for ESP32 EMG serial connection.";
      drawChart();
      return;
    }

    const incomingSamples = Array.isArray(data.samples) ? data.samples : [];
    incomingSamples.forEach((sample) => {
      const sensorA = typeof sample.a === "number" ? sample.a : null;
      const sensorB = typeof sample.b === "number" ? sample.b : null;
      state.emgSeriesA.push(sensorA);
      state.emgSeriesB.push(sensorB);
      state.emgSeriesA.shift();
      state.emgSeriesB.shift();
    });

    const sensorA = typeof data.sensor_a === "number" ? data.sensor_a : null;
    const sensorB = typeof data.sensor_b === "number" ? data.sensor_b : null;

    els.mvcA.textContent = typeof data.mvc_a === "number" ? `${Math.round(data.mvc_a)}` : "--";
    els.mvcB.textContent = typeof data.mvc_b === "number" ? `${Math.round(data.mvc_b)}` : "--";
    els.activationLevel.textContent =
      sensorA !== null || sensorB !== null
        ? `A ${sensorA !== null ? Math.round(sensorA) : "--"} | B ${sensorB !== null ? Math.round(sensorB) : "--"}`
        : "--";
    els.imbalanceLevel.textContent = typeof data.imbalance === "number" ? `${Math.round(data.imbalance)}` : "--";
    els.fatigueLevel.textContent =
      sensorA !== null && sensorB !== null ? computeFatigue(sensorA, sensorB, data.mvc_a || 0, data.mvc_b || 0) : "--";

    if (sensorA !== null && sensorB !== null) {
      els.muscleRecommendation.textContent =
        Math.abs(sensorA - sensorB) > 20
          ? "Muscle imbalance detected. Reduce load and improve left-right symmetry."
          : "Live raw EMG data is arriving. Keep movement controlled and monitor fatigue.";
    } else {
      els.muscleRecommendation.textContent = "Connected to ESP32. Waiting for both raw values.";
    }
    drawChart();
  } catch (error) {
    els.bluetoothStatus.textContent = "ESP32 bridge unavailable";
    els.bluetoothStatus.classList.add("warn");
    els.muscleRecommendation.textContent = "Could not reach the local EMG bridge server.";
  }
}

function startEmgPolling() {
  clearInterval(state.emgPollInterval);
  state.emgLastSeq = 0;
  pollEmgStatus();
  state.emgPollInterval = setInterval(pollEmgStatus, 50);
}

async function pollPostureStatus() {
  if (!state.cameraActive || !state.session) return;
  try {
    const response = await fetch("/api/posture/status", { cache: "no-store" });
    const data = await response.json();
    els.cameraStatus.textContent = data.running ? "Python camera online" : "Python camera offline";
    if (data.last_error) {
      els.postureRecommendation.textContent = data.last_error;
      els.cameraStatus.textContent = "Camera error";
    }
    if (!data.running) return;

    const totalReps = Number(data.total_reps || 0);
    const targetReps = state.sessionConfig.targetReps;
    const totalSets = state.sessionConfig.totalSets;
    const completedSets = Math.min(Math.floor(totalReps / targetReps), totalSets - 1);
    state.session.currentSet = Math.min(completedSets + 1, totalSets);
    state.session.completedReps = totalReps % targetReps;
    if (totalReps > 0 && totalReps % targetReps === 0 && totalReps / targetReps <= totalSets) {
      state.session.completedReps = targetReps;
    }
    state.session.totalRepsDone = totalReps;
    state.session.stage = data.stage || "READY";
    state.session.postureScore = data.posture_score || 0;
    state.session.postureTip = (data.feedback && data.feedback[0]) || "Keep moving in frame.";
    renderSessionState();

    if (totalReps > 0 && totalReps % targetReps === 0 && totalReps / targetReps < totalSets && state.session.restRemaining === 0) {
      state.session.restRemaining = state.sessionConfig.restSeconds;
      els.restTimer.textContent = `${state.session.restRemaining}s`;
      showToast("Set completed. Rest timer started.");
    }

    if (totalReps >= targetReps * totalSets) {
      finishSession();
    }
  } catch (error) {
    els.cameraStatus.textContent = "Python posture bridge unavailable";
  }
}

function startPosturePolling() {
  clearInterval(state.posturePollInterval);
  pollPostureStatus();
  state.posturePollInterval = setInterval(pollPostureStatus, 700);
}

function buildSessionConfig() {
  return {
    analysisType: els.analysisType.value,
    exerciseType: els.exerciseType.value,
    cameraSource: els.cameraSource.value,
    esp32Url: els.esp32Url.value.trim(),
    targetReps: Number(els.targetReps.value),
    totalSets: Number(els.totalSets.value),
    restSeconds: Number(els.restSeconds.value),
    monitorSeconds: Number(els.monitorSeconds.value),
  };
}

function startSession(config) {
  stopSession(false);
  state.sessionConfig = config;
  state.session = {
    startedAt: Date.now(),
    currentSet: 1,
    completedReps: 0,
    totalRepsDone: 0,
    restRemaining: 0,
    muscleElapsed: 0,
    postureScore: 0,
    stage: "READY",
    postureTip: "Start the Python posture camera to begin analysis.",
  };
  renderSessionConfig();
  renderSessionState();
  els.elapsedTimer.textContent = "00:00";
  els.muscleTimer.textContent = "00:00";
  setView("session");
  startEmgPolling();

  state.sessionInterval = setInterval(() => {
    if (!state.session) return;
    const elapsed = Math.floor((Date.now() - state.session.startedAt) / 1000);
    els.elapsedTimer.textContent = formatTime(elapsed);

    if (state.session.restRemaining > 0) {
      state.session.restRemaining -= 1;
      els.restTimer.textContent = `${state.session.restRemaining}s`;
      if (state.session.restRemaining === 0) {
        els.restTimer.textContent = "Back to work";
        showToast("Rest complete. Start the next set.");
      }
    }

    if (config.analysisType !== "posture") {
      state.session.muscleElapsed += 1;
      els.muscleTimer.textContent = formatTime(state.session.muscleElapsed);
      if (config.analysisType === "muscle" && state.session.muscleElapsed >= config.monitorSeconds) {
        finishSession();
      }
    }
  }, 1000);
}

async function enableCamera() {
  try {
    const response = await fetch("/api/posture/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        exercise: state.sessionConfig?.exerciseType || "squats",
        camera_source: state.sessionConfig?.cameraSource || "webcam",
        esp32_url: state.sessionConfig?.esp32Url || "",
      }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.message || "Unable to start Python posture analysis.");
    }
    state.cameraActive = true;
    els.cameraFeed.src = `/api/posture/feed?ts=${Date.now()}`;
    startPosturePolling();
    els.postureRecommendation.textContent =
      (state.sessionConfig?.cameraSource || "webcam") === "esp32"
        ? `Trying ESP32-CAM stream: ${state.sessionConfig?.esp32Url || ""}`
        : "Laptop webcam selected. Starting Python posture analysis.";
    showToast(data.message);
  } catch (error) {
    els.cameraStatus.textContent = "Python camera failed";
    showToast(error.message);
  }
}

async function connectBluetooth() {
  try {
    state.emgSeriesA = Array.from({ length: 500 }, () => null);
    state.emgSeriesB = Array.from({ length: 500 }, () => null);
    state.emgLastSeq = 0;
    const response = await fetch("/api/emg/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        port: els.emgPort.value.trim() || "COM4",
        baud_rate: Number(els.emgBaud.value) || 115200,
      }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.message || "Unable to connect to ESP32 EMG bridge.");
    }
    startEmgPolling();
    showToast(data.message);
  } catch (error) {
    els.muscleRecommendation.textContent = error.message;
    showToast(error.message);
  }
}

function buildPerformanceRecommendation() {
  const { analysisType, exerciseType, totalSets, targetReps } = state.sessionConfig;
  const totalGoal = totalSets * targetReps;
  const totalDone = state.session.totalRepsDone;
  const lines = [];
  lines.push(`<p><strong>Exercise:</strong> ${capitalize(exerciseType)} | <strong>Mode:</strong> ${capitalize(analysisType)}</p>`);
  lines.push(`<p><strong>Total reps done:</strong> ${totalDone} of ${totalGoal}</p>`);

  if (analysisType !== "muscle") {
    lines.push(`<p><strong>Posture score:</strong> ${state.session.postureScore}%</p>`);
    lines.push(`<p>${state.session.postureTip}</p>`);
  }
  if (analysisType !== "posture") {
    lines.push(`<p><strong>EMG status:</strong> ${state.bluetoothConnected ? "ESP32 serial bridge connected." : "ESP32 serial bridge was not connected."}</p>`);
  }
  lines.push("<p class='muted'>This workflow uses your Python posture code path and is not a medical diagnosis.</p>");
  return lines.join("");
}

function finishSession() {
  if (!state.session) return;
  els.summaryContent.innerHTML = buildPerformanceRecommendation();
  stopSession(false);
  setView("summary");
}

async function stopPostureBackend() {
  try {
    await fetch("/api/posture/stop", { method: "POST" });
  } catch (error) {
    console.error(error);
  }
}

function stopSession(clearSession = true) {
  clearInterval(state.sessionInterval);
  clearInterval(state.posturePollInterval);
  clearInterval(state.emgPollInterval);
  state.sessionInterval = null;
  state.posturePollInterval = null;
  state.emgPollInterval = null;
  state.cameraActive = false;
  state.emgLastSeq = 0;
  els.cameraFeed.removeAttribute("src");
  els.cameraStatus.textContent = "Camera offline";
  stopPostureBackend();

  if (clearSession) {
    state.session = null;
  }
}

function addManualRep() {
  showToast("Python posture analysis counts reps automatically.");
}

function findDoctors() {
  if (!navigator.geolocation) {
    els.doctorResults.innerHTML = "<p>Geolocation is not available in this browser.</p>";
    return;
  }
  els.doctorResults.innerHTML = "<p>Fetching your location...</p>";
  navigator.geolocation.getCurrentPosition(
    ({ coords }) => {
      const { latitude, longitude } = coords;
      const links = [
        ["Nearby orthopedic doctors", `https://www.google.com/maps/search/orthopedic+doctor/@${latitude},${longitude},14z`],
        ["Nearby physiotherapy clinics", `https://www.google.com/maps/search/physiotherapy+clinic/@${latitude},${longitude},14z`],
        ["Nearby sports medicine specialists", `https://www.google.com/maps/search/sports+medicine+doctor/@${latitude},${longitude},14z`],
      ];
      els.doctorResults.innerHTML = links
        .map(([label, href]) => `<a class="doctor-link" href="${href}" target="_blank" rel="noreferrer">${label}</a>`)
        .join("");
    },
    () => {
      els.doctorResults.innerHTML = "<p>Unable to fetch location. Please enable location access and try again.</p>";
    }
  );
}

els.loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const email = document.getElementById("login-email").value.trim().toLowerCase();
  const password = document.getElementById("login-password").value.trim();
  if (!email || !password) {
    showToast("Enter any email and password to continue.");
    return;
  }
  loginUser({ email, password, name: email.split("@")[0] || "User" });
  showToast("Logged in successfully.");
  els.loginForm.reset();
});

els.signupForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const name = document.getElementById("signup-name").value.trim() || "User";
  const email = document.getElementById("signup-email").value.trim().toLowerCase();
  const password = document.getElementById("signup-password").value.trim();
  if (!email || !password) {
    showToast("Enter email and password to create the profile.");
    return;
  }
  loginUser({ name, email, password });
  showToast("Signup complete.");
  els.signupForm.reset();
});

els.goSignupBtn.addEventListener("click", () => setView("signup"));
els.goLoginBtn.addEventListener("click", () => setView("auth"));
els.logoutBtn.addEventListener("click", logoutUser);
els.analysisType.addEventListener("change", updateSetupFields);
els.setupForm.addEventListener("submit", (event) => {
  event.preventDefault();
  startSession(buildSessionConfig());
});
els.repBtn.addEventListener("click", addManualRep);
els.cameraBtn.addEventListener("click", enableCamera);
els.bluetoothBtn.addEventListener("click", connectBluetooth);
els.finishBtn.addEventListener("click", finishSession);
els.doctorBtn.addEventListener("click", findDoctors);
els.newSessionBtn.addEventListener("click", () => {
  state.session = null;
  setView("setup");
});

function bootstrap() {
  updateSetupFields();
  drawChart();
  startEmgPolling();
  const storedUser = localStorage.getItem(STORAGE_KEYS.currentUser);
  if (storedUser) {
    state.currentUser = JSON.parse(storedUser);
    updateAuthUI();
    setView("setup");
  } else {
    setView("auth");
  }
}

bootstrap();
