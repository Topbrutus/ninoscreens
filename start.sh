#!/bin/bash
cd ~/Ninoscreens
LOG=logs/run_$(date +%Y%m%d_%H%M%S).log
mkdir -p logs
echo "Démarrage $(date)" >> $LOG
export GOOGLE_API_KEY="AIzaSyBjqFFsCpSrS0LtoY4B6gs6uGS-jbB7OT4"
python3 main.py 2>&1 | tee -a $LOG
echo "Fin $(date)" >> $LOG
