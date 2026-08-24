#!/bin/bash
# Daily Brief Android Otomasyon Kurulum Scripti

echo "=== DAILY BRIEF ANDROID İSTASYONU KURULUMU ==="
pkg update -y
pkg install -y python git termux-api termux-tools

pip install --upgrade pip
pip install uiautomator2

mkdir -p /sdcard/Pictures/DailyBrief
termux-wake-lock

echo "Kurulum tamamlandı! İstasyonu başlatmak için: python android/otomasyon.py"
