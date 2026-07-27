# Site binding — USB only; never shipped via OTA.
# NODE_ID prefix selects the site (WiFi + server). See docs/SITES.md.
#
#   Plant-NNN     → plant WiFi + plant Pi SERVER_URL
#   Byrne417_NN   → lab WiFi + lab Pi SERVER_URL
#
# Do not mix Plant credentials with Byrne417 SERVER_URL (or the reverse).

WIFI_SSID = "YOUR_WIFI_NAME"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"

# Example plant:  http://192.168.1.19:5000/api/submit
# Example lab:    http://140.192.162.150:5000/api/submit
SERVER_URL = "http://192.168.1.19:5000/api/submit"

# Production: Plant-123 (floor + room + sensor-within-room)
# Lab:        Byrne417_01
NODE_ID = "Plant-123"
