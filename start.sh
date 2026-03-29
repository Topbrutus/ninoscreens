#!/bin/bash
cd ~/Ninoscreens
LOG=logs/run_$(date +%Y%m%d_%H%M%S).log
mkdir -p logs
echo "Démarrage $(date)" >> $LOG

export GOOGLE_API_KEY="AIzaSyBjqFFsCpSrS0LtoY4B6gs6uGS-jbB7OT4"

# Redémarrer le bridge Gemini
pkill -f gemini_bridge 2>/dev/null
sleep 1
cd ~/MonDeuxiemeProjet
nohup python3 src/gemini_bridge.py --watch < /dev/null > /tmp/bridge.log 2>&1 &
echo "Bridge PID: $!" >> /tmp/bridge.log
sleep 2

cd ~/Ninoscreens
python3 main.py 2>&1 | tee -a $LOG
echo "Fin $(date)" >> $LOG
