#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include <esp_timer.h>

// ===========================
// Camera Configuration
// ===========================
// Select camera model
#define CAMERA_MODEL_AI_THINKER  // Most common ESP32-CAM board

#include "camera_pins.h"

// ===========================
// WiFi Configuration
// ===========================
const char* ssid = "yash";      // Replace with your WiFi name
const char* password = "Eggyak12";  // Replace with your WiFi password

// ===========================
// Server Configuration
// ===========================
WebServer server(81);  // Using port 81 (common for ESP32-CAM streams)

// ===========================
// Frame Variables
// ===========================
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=123456789000000000000987654321";
static const char* _STREAM_BOUNDARY = "\r\n--123456789000000000000987654321\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

// ===========================
// Function Prototypes
// ===========================
void setupCamera();
void handleStream();
void handleJPG();
void handleRoot();
void handleNotFound();

// ===========================
// Setup
// ===========================
void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println("\n\n=== ESP32-CAM Stream Server ===");
  
  // Initialize camera
  setupCamera();
  
  // Connect to WiFi
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n✅ WiFi Connected!");
  Serial.print("📡 ESP32-CAM IP Address: ");
  Serial.println(WiFi.localIP());
  Serial.println("=================================");
  Serial.println("Stream URLs:");
  Serial.printf("   - MJPG Stream: http://%s:81/stream\n", WiFi.localIP().toString().c_str());
  Serial.printf("   - JPEG Snapshot: http://%s:81/photo\n", WiFi.localIP().toString().c_str());
  Serial.println("=================================\n");
  
  // Setup server routes
  server.on("/", handleRoot);
  server.on("/stream", HTTP_GET, handleStream);
  server.on("/photo", HTTP_GET, handleJPG);
  server.onNotFound(handleNotFound);
  
  // Start server
  server.begin();
  Serial.println("✅ Web server started!");
  Serial.println("Waiting for client connection...\n");
}

// ===========================
// Main Loop
// ===========================
void loop() {
  server.handleClient();
  
  // Print memory status every 30 seconds
  static unsigned long lastPrint = 0;
  if (millis() - lastPrint > 30000) {
    lastPrint = millis();
    Serial.printf("📊 Free heap: %d bytes\n", ESP.getFreeHeap());
  }
}

// ===========================
// Camera Initialization
// ===========================
void setupCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  
  // Select frame size based on your needs
  // Options: FRAMESIZE_QVGA (320x240), FRAMESIZE_VGA (640x480), FRAMESIZE_SVGA (800x600)
  config.frame_size = FRAMESIZE_VGA;  // 640x480 - good balance
  config.jpeg_quality = 12;           // 0-63, lower = better quality
  config.fb_count = 1;                // 1 = better for streaming, 2 = better for stability
  
  // Initialize camera
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("❌ Camera init failed with error 0x%x", err);
    return;
  }
  
  // Adjust camera settings for better performance
  sensor_t *s = esp_camera_sensor_get();
  if (s) {
    s->set_framesize(s, FRAMESIZE_VGA);
    s->set_quality(s, 12);
    s->set_brightness(s, 1);      // -2 to 2
    s->set_contrast(s, 1);        // -2 to 2
    s->set_saturation(s, 1);      // -2 to 2
    s->set_special_effect(s, 0);   // 0 = no effect
    s->set_whitebal(s, 1);         // 1 = enable
    s->set_awb_gain(s, 1);         // 1 = enable
    s->set_wb_mode(s, 0);          // 0 = auto
    s->set_exposure_ctrl(s, 1);    // 1 = enable
    s->set_aec2(s, 1);             // 1 = enable
    s->set_gain_ctrl(s, 1);        // 1 = enable
    s->set_agc_gain(s, 0);         // 0 = auto
    s->set_gainceiling(s, (gainceiling_t)2);
    s->set_bpc(s, 1);              // 1 = enable
    s->set_wpc(s, 1);              // 1 = enable
    s->set_raw_gma(s, 1);          // 1 = enable
    s->set_lenc(s, 1);             // 1 = enable
    s->set_hmirror(s, 1);          // Mirror horizontally for better viewing
    s->set_vflip(s, 0);            // No vertical flip
    s->set_dcw(s, 1);              // 1 = enable
    s->set_colorbar(s, 0);         // 0 = disable
  }
  
  Serial.println("✅ Camera initialized!");
}

// ===========================
// Stream Handler (MJPG)
// ===========================
void handleStream() {
  WiFiClient client = server.client();
  
  // Send stream headers
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Cache-Control", "no-cache, no-store, must-revalidate");
  server.sendHeader("Pragma", "no-cache");
  server.sendHeader("Expires", "-1");
  server.setContentLength(CONTENT_LENGTH_UNKNOWN);
  server.send(200, "multipart/x-mixed-replace;boundary=123456789000000000000987654321", "");
  
  Serial.println("📹 Client connected to stream");
  unsigned long frameCount = 0;
  unsigned long startTime = millis();
  
  while (client.connected()) {
    camera_fb_t *fb = esp_camera_fb_get();
    
    if (!fb) {
      Serial.println("❌ Camera capture failed");
      break;
    }
    
    // Send frame
    client.print(_STREAM_BOUNDARY);
    client.printf(_STREAM_PART, fb->len);
    client.write(fb->buf, fb->len);
    client.print("\r\n");
    
    frameCount++;
    
    // Print stream stats every 100 frames
    if (frameCount % 100 == 0) {
      unsigned long elapsed = millis() - startTime;
      float fps = (frameCount * 1000.0) / elapsed;
      Serial.printf("📊 Stream stats - Frames: %lu, FPS: %.1f, Size: %u bytes\n", 
                    frameCount, fps, fb->len);
    }
    
    esp_camera_fb_return(fb);
    
    // Small delay to prevent overwhelming the client
    delay(10);
  }
  
  Serial.println("📹 Client disconnected from stream");
}

// ===========================
// JPEG Snapshot Handler
// ===========================
void handleJPG() {
  camera_fb_t *fb = esp_camera_fb_get();
  
  if (!fb) {
    server.send(500, "text/plain", "Camera capture failed");
    Serial.println("❌ Failed to capture snapshot");
    return;
  }
  
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Cache-Control", "no-cache, no-store, must-revalidate");
  server.sendHeader("Pragma", "no-cache");
  server.sendHeader("Expires", "-1");
  server.send(200, "image/jpeg", fb->buf, fb->len);
  
  Serial.printf("📸 Snapshot captured: %u bytes\n", fb->len);
  
  esp_camera_fb_return(fb);
}

// ===========================
// Root Page Handler
// ===========================
void handleRoot() {
  String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ESP32-CAM Exercise Tracker</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            text-align: center;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            margin: 0;
            padding: 20px;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: rgba(255,255,255,0.1);
            border-radius: 20px;
            padding: 20px;
            backdrop-filter: blur(10px);
        }
        h1 {
            margin-bottom: 10px;
        }
        .stream-container {
            background: black;
            border-radius: 10px;
            overflow: hidden;
            margin: 20px 0;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }
        img {
            width: 100%;
            height: auto;
            display: block;
        }
        .controls {
            margin: 20px 0;
        }
        button {
            background: #4CAF50;
            color: white;
            border: none;
            padding: 10px 20px;
            margin: 5px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
            transition: all 0.3s;
        }
        button:hover {
            background: #45a049;
            transform: scale(1.05);
        }
        .info {
            background: rgba(0,0,0,0.7);
            padding: 15px;
            border-radius: 10px;
            margin-top: 20px;
            text-align: left;
        }
        .status {
            color: #4CAF50;
            font-weight: bold;
        }
        a {
            color: #4CAF50;
            text-decoration: none;
        }
        @media (max-width: 600px) {
            .container {
                padding: 10px;
            }
            button {
                padding: 8px 16px;
                font-size: 14px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎥 ESP32-CAM Exercise Tracker</h1>
        <p>Streaming to AI Exercise Analyzer</p>
        
        <div class="stream-container">
            <img id="stream" src="/stream" alt="ESP32-CAM Stream">
        </div>
        
        <div class="controls">
            <button onclick="location.reload()">🔄 Refresh Stream</button>
            <button onclick="window.location.href='/photo'">📸 Take Snapshot</button>
        </div>
        
        <div class="info">
            <h3>📡 Connection Info:</h3>
            <p>🔗 Stream URL: <code id="streamUrl"></code></p>
            <p>📸 Snapshot URL: <code id="photoUrl"></code></p>
            <p>✅ Status: <span class="status">Streaming Active</span></p>
            <p>💡 Use this IP address in the Python exercise analyzer</p>
        </div>
    </div>
    
    <script>
        // Display URLs
        const currentUrl = window.location.host;
        document.getElementById('streamUrl').textContent = `http://${currentUrl}/stream`;
        document.getElementById('photoUrl').textContent = `http://${currentUrl}/photo`;
        
        // Auto-reconnect on error
        const streamImg = document.getElementById('stream');
        streamImg.onerror = function() {
            setTimeout(() => {
                streamImg.src = '/stream?' + new Date().getTime();
            }, 1000);
        };
        
        // Log connection
        console.log('ESP32-CAM Stream Viewer Connected');
    </script>
</body>
</html>
)rawliteral";
  
  server.send(200, "text/html", html);
  Serial.println("🌐 Root page served");
}

// ===========================
// 404 Handler
// ===========================
void handleNotFound() {
  server.send(404, "text/plain", "404: Not Found");
}