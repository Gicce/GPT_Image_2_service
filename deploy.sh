#!/usr/bin/env bash
set -euo pipefail

cd /opt/GPT_Image_2_service

git pull

sudo docker compose build backend
sudo docker compose up -d
sudo docker compose restart nginx

sudo docker compose ps