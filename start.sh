#!/usr/bin/env bash
uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT
