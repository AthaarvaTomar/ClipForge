#!/bin/bash
# Timeline API Curl Walkthrough (Task T5)
set -e

BASE_URL="http://127.0.0.1:8000"

echo "=== Step 0: Get a video ID ==="
VIDEO_ID=$(curl -s "$BASE_URL/api/videos" | grep -o '"id":"[^"]*' | head -n 1 | cut -d'"' -f4)
echo "Using Video ID: $VIDEO_ID"

echo -e "\n=== Step 1: POST /api/timelines (Create from video) ==="
TIMELINE=$(curl -s -X POST "$BASE_URL/api/timelines" \
  -H "Content-Type: application/json" \
  -d "{\"video_id\": \"$VIDEO_ID\"}")
echo "$TIMELINE"
TIMELINE_ID=$(echo "$TIMELINE" | grep -o '"id":"[^"]*' | head -n 1 | cut -d'"' -f4)
VERSION=$(echo "$TIMELINE" | grep -o '"version":[0-9]*' | head -n 1 | cut -d':' -f2)
echo "Timeline ID: $TIMELINE_ID (Version $VERSION)"

echo -e "\n=== Step 2: GET /api/timelines/{id} ==="
curl -s "$BASE_URL/api/timelines/$TIMELINE_ID"

echo -e "\n=== Step 3: POST /api/timelines/{id}/ops (Batch Edit) ==="
EDITED=$(curl -s -X POST "$BASE_URL/api/timelines/$TIMELINE_ID/ops" \
  -H "Content-Type: application/json" \
  -d "{
    \"expected_version\": $VERSION,
    \"actor\": \"agent\",
    \"ops\": [
      {\"op\": \"add_track\", \"track_type\": \"video\", \"name\": \"V1\"},
      {\"op\": \"add_item\", \"track_index\": 0, \"item\": {\"source\": \"$VIDEO_ID\", \"src_in\": 0, \"src_out\": 5000, \"start\": 0}}
    ]
  }")
echo "$EDITED"
VERSION=$(echo "$EDITED" | grep -o '"version":[0-9]*' | head -n 1 | cut -d':' -f2)

echo -e "\n=== Step 4: POST /api/timelines/{id}/ops (409 Conflict Test) ==="
curl -s -X POST "$BASE_URL/api/timelines/$TIMELINE_ID/ops" \
  -H "Content-Type: application/json" \
  -d "{
    \"expected_version\": 1,
    \"actor\": \"user\",
    \"ops\": [{\"op\": \"add_track\", \"track_type\": \"audio\", \"name\": \"BGM\"}]
  }"

echo -e "\n=== Step 5: POST /api/timelines/{id}/undo ==="
UNDONE=$(curl -s -X POST "$BASE_URL/api/timelines/$TIMELINE_ID/undo" \
  -H "Content-Type: application/json" \
  -d "{\"expected_version\": $VERSION}")
echo "$UNDONE"
VERSION=$(echo "$UNDONE" | grep -o '"version":[0-9]*' | head -n 1 | cut -d':' -f2)

echo -e "\n=== Step 6: POST /api/timelines/{id}/redo ==="
REDONE=$(curl -s -X POST "$BASE_URL/api/timelines/$TIMELINE_ID/redo" \
  -H "Content-Type: application/json" \
  -d "{\"expected_version\": $VERSION}")
echo "$REDONE"
VERSION=$(echo "$REDONE" | grep -o '"version":[0-9]*' | head -n 1 | cut -d':' -f2)

echo -e "\n=== Step 7: GET /api/timelines/{id}/history ==="
curl -s "$BASE_URL/api/timelines/$TIMELINE_ID/history"

echo -e "\n=== Step 8: POST /api/timelines/{id}/restore/1 ==="
RESTORED=$(curl -s -X POST "$BASE_URL/api/timelines/$TIMELINE_ID/restore/1" \
  -H "Content-Type: application/json" \
  -d "{\"expected_version\": $VERSION}")
echo "$RESTORED"

echo -e "\n=== Walkthrough Finished ==="
