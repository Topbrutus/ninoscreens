#!/bin/bash
cd ~/Ninoscreens
LOG=logs/run_$(date +%Y%m%d_%H%M%S).log
mkdir -p logs
echo "Démarrage $(date)" >> $LOG
export PULSE_SERVER=/dev/null
export ALSA_CONFIG_PATH=/dev/null
python3 main.py 2>&1 | tee -a $LOG
echo "Fin $(date)" >> $LOG
