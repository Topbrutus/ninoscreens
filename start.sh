#!/bin/bash
cd ~/Ninoscreens
LOG=logs/run_$(date +%Y%m%d_%H%M%S).log
echo "Démarrage $(date)" >> $LOG
python3 main.py 2>&1 | tee -a $LOG
echo "Fin $(date)" >> $LOG
