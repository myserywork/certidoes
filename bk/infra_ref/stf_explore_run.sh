#!/bin/bash
# STF SPA Explorer — wrapper with Whisper integration
export DISPLAY=:121
export NODE_PATH=/home/ramza/node_modules
export HOME=/home/ramza

LOG=/tmp/stf_explore.log
RESULT=/tmp/stf_spa_map.json

echo "=== STF SPA Explorer ===" > "$LOG"
echo "Started: $(date)" >> "$LOG"

# Run Node with Python Whisper pipe
node /home/ramza/telegram_downloads/PEDRO_PROJECT/infra/stf_explore.js 2>>"$LOG" | while IFS= read -r line; do
    echo "NODE>> $line" >> "$LOG"
    
    # Check if Whisper needed
    STATUS=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null)
    
    if [ "$STATUS" = "need_whisper" ]; then
        AUDIO=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('audio_file',''))" 2>/dev/null)
        echo "Whisper transcribing: $AUDIO" >> "$LOG"
        
        # Convert AAC to WAV
        WAV="${AUDIO%.aac}.wav"
        ffmpeg -y -i "$AUDIO" -ar 16000 -ac 1 "$WAV" 2>/dev/null
        [ -f "$WAV" ] && AUDIO="$WAV"
        
        # Transcribe with Whisper medium
        ANSWER=$(python3 -c "
import whisper, re, sys
model = whisper.load_model('medium', device='cuda')
result = model.transcribe('$AUDIO', language='en', fp16=True)
text = result['text'].strip()
print('RAW: ' + text, file=sys.stderr)
lower = text.lower()
if 'by me' in lower:
    after = lower.split('by me')[-1].strip()
    parts = [p.strip() for p in after.replace('.', ' ').replace(',', ' ').split() if p.strip()]
    noise = {'the','a','an','is','are','was','were','of','and','to','in','for','from','which','that','this','not','but','its','with','has','been','will','can','may','must','also'}
    words = [w for w in parts if w.lower() not in noise and len(w) > 2 and w.isalpha()]
    print(words[0].lower() if words else text.split()[-1].lower())
else:
    clean = re.sub(r'[^a-z0-9 ]', '', lower).strip()
    print(clean.split()[-1] if clean else 'unknown')
" 2>>"$LOG")
        
        echo "Whisper answer: $ANSWER" >> "$LOG"
        echo "{\"answer\":\"$ANSWER\"}"
    fi
    
    if [ "$STATUS" = "done" ]; then
        echo "DONE! Results in $RESULT" >> "$LOG"
        break
    fi
done

echo "Finished: $(date)" >> "$LOG"
echo "EXPLORE_COMPLETE" >> "$LOG"
